"""
引用验证器
核心要求 2: 双重溯源（验证）- 同步 + 异步验证机制
对齐 TypeScript: backend/chunking-rag/src/Reasoning/citation_verifier.ts

同步验证: 检查引用 ID 是否真实存在于 chunks 列表（< 10ms）
异步验证: Token 级匹配验证，不阻塞响应链路
"""

from __future__ import annotations
import asyncio
import re
from typing import List, Optional, Callable, Tuple
from .types import (
    RetrievedChunk,
    ContextBlock,
    CitationSource,
    VerificationResult,
    ClaimedCitation,
    VerificationStatus,
)


# ============================================================
# 对齐 TS: SyncVerificationResult interface
# ============================================================
class SyncVerificationResult:
    def __init__(
        self,
        valid_citations: List[int],
        invalid_citations: List[int],
        verified_sources: List[CitationSource],
    ):
        self.valid_citations = valid_citations        # 有效的引用 ID
        self.invalid_citations = invalid_citations    # 无效的引用 ID
        self.verified_sources = verified_sources      # 验证通过的来源


class CitationVerifier:
    """
    引用验证器 - 对齐 TS CitationVerifier class
    """

    def sync_verify(
        self,
        claimed_ids: List[int],
        context_blocks: List[ContextBlock],
    ) -> SyncVerificationResult:
        """
        同步验证：检查引用 ID 是否真实存在于 context blocks
        对齐 TS: syncVerify() - 快速检查，< 10ms
        """
        valid_ids: set[int] = set()
        invalid_ids: List[int] = []
        verified_sources: List[CitationSource] = []

        for cid in claimed_ids:
            block = next((b for b in context_blocks if b.id == cid), None)
            if block:
                valid_ids.add(cid)
                verified_sources.append(
                    CitationSource(
                        id=block.id,
                        anchor_id=block.anchor_id,
                        title_path=block.title_path,
                        score=block.reranker_score,
                        verification_status=VerificationStatus.PENDING,  # 等待异步验证
                        file_path=self._extract_file_path(block.anchor_id),
                        snippet=block.content[:100],
                    )
                )
            else:
                invalid_ids.append(cid)

        return SyncVerificationResult(
            valid_citations=list(valid_ids),
            invalid_citations=invalid_ids,
            verified_sources=verified_sources,
        )

    async def async_verify(
        self,
        answer: str,
        claimed_citations: List[ClaimedCitation],
        chunks: List[RetrievedChunk],
        on_progress: Optional[Callable[[VerificationResult], None]] = None,
    ) -> List[VerificationResult]:
        """
        异步验证：Token 级匹配验证
        对齐 TS: asyncVerify() - 不阻塞响应链路，后台执行
        """
        results: List[VerificationResult] = []

        for claimed in claimed_citations:
            # 匹配 chunk: 通过 chunkIndex + 1 对应 ID - 对齐 TS findContextBlock()
            chunk = self._find_context_block(claimed.citation_id, chunks)
            result = await self._verify_claim(claimed, chunk)
            results.append(result)

            if on_progress:
                on_progress(result)

        return results

    async def _verify_claim(
        self,
        claimed: ClaimedCitation,
        chunk: Optional[RetrievedChunk],
    ) -> VerificationResult:
        """
        验证单个声称的引用 - 对齐 TS verifyClaim()
        """
        if not chunk:
            return VerificationResult(
                citation_id=claimed.citation_id,
                key_tokens=claimed.key_tokens,
                matched_tokens=[],
                match_ratio=0.0,
                status=VerificationStatus.FAILED,
            )

        raw_text = chunk.raw_text or chunk.content
        matched_tokens: List[str] = []

        # Token 级匹配 - 对齐 TS
        for token in claimed.key_tokens:
            if token in raw_text:
                matched_tokens.append(token)

        match_ratio = (
            len(matched_tokens) / len(claimed.key_tokens)
            if claimed.key_tokens
            else 0.0
        )

        # 状态判断 - 对齐 TS 阈值
        if match_ratio >= 0.8:
            status = VerificationStatus.VERIFIED
        elif match_ratio >= 0.5:
            status = VerificationStatus.UNCERTAIN
        elif match_ratio > 0:
            status = VerificationStatus.UNCERTAIN
        else:
            status = VerificationStatus.FAILED

        return VerificationResult(
            citation_id=claimed.citation_id,
            key_tokens=claimed.key_tokens,
            matched_tokens=matched_tokens,
            match_ratio=match_ratio,
            status=status,
        )

    def extract_key_tokens(self, text: str) -> List[str]:
        """
        从文本中提取关键 token（名词、数字、版本号）
        对齐 TS: extractKeyTokens()
        """
        tokens: List[str] = []

        # 版本号：v1.0, 2.0.0 等
        versions = re.findall(r'\bv?\d+\.\d+(?:\.\d+)*\b', text)
        tokens.extend(versions)

        # 数字 + 单位
        numbers = re.findall(r'\d+\s*(?:MB|GB|KB|ms|s|min|小时|分钟|秒|天|年|版本|版)', text)
        tokens.extend(numbers)

        # 专有名词（驼峰 / 连续大写）
        proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b|\b[A-Z]{2,}\b', text)
        tokens.extend(proper_nouns)

        # 配置项（反引号包裹）
        config_items = re.findall(r'`([^`]+)`', text)
        tokens.extend(config_items)

        # 关键词白名单 - 对齐 TS
        keywords = [
            'API', 'SDK', 'CLI', 'GUI', 'JSON', 'XML', 'YAML', 'HTTP',
            'REST', 'GraphQL', 'gRPC', 'OAuth', 'JWT', 'Token',
        ]
        for kw in keywords:
            if kw in text:
                tokens.append(kw)

        # 去重
        return list(dict.fromkeys(tokens))

    def is_valid_citation_id(self, cid: int, context_blocks: List[ContextBlock]) -> bool:
        """
        验证引用 ID 是否有效 - 对齐 TS isValidCitationId()
        """
        return any(b.id == cid for b in context_blocks)

    def clean_answer(
        self,
        answer: str,
        valid_ids: List[int],
        invalid_ids: List[int],
    ) -> str:
        """
        清理回答中的无效引用，将无效引用标记替换为注释
        对齐 TS: cleanAnswer()
        """
        cleaned = answer
        for cid in invalid_ids:
            # 将 [id] 替换为 [id❓] - 对齐 TS
            cleaned = re.sub(rf'\[{cid}\]', f'[{cid}❓]', cleaned)
        return cleaned

    # ------------------------------------------------------------------ #
    # 私有辅助                                                             #
    # ------------------------------------------------------------------ #

    def _extract_file_path(self, anchor_id: str) -> str:
        """从 anchorId 提取文件路径 - 对齐 TS extractFilePath()"""
        parts = anchor_id.split('#')
        return parts[0] if parts else anchor_id

    def _find_context_block(
        self,
        cid: int,
        chunks: List[RetrievedChunk],
    ) -> Optional[RetrievedChunk]:
        """
        通过 chunkIndex + 1 匹配 ID - 对齐 TS findContextBlock()
        """
        return next(
            (c for c in chunks if (c.chunk_index + 1) == cid),
            None,
        )


def create_citation_verifier() -> CitationVerifier:
    """创建引用验证器 - 对齐 TS createCitationVerifier()"""
    return CitationVerifier()
