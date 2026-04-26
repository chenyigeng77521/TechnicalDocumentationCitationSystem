"""
引用验证器
核心要求 2: 双重溯源（验证）- 同步 + 异步验证机制

同步验证: 检查引用 ID 是否真实存在于 chunks 列表（< 10ms）
异步验证: Token 级匹配验证，不阻塞响应链路
"""

from __future__ import annotations
import asyncio
import re
from typing import List, Optional, Callable
from ._types import (
    RetrievedChunk,
    ContextBlock,
    CitationSource,
    VerificationResult,
    ClaimedCitation,
    VerificationStatus,
)

# 预编译关键词正则，避免每次调用重复编译
_KEYWORD_PATTERN = re.compile(
    r'\b(?:API|SDK|CLI|GUI|JSON|XML|YAML|HTTP|REST|GraphQL|gRPC|OAuth|JWT|Token)\b'
)


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
    """引用验证器"""

    def __init__(
        self,
        verified_threshold: float = 0.8,
        context_window_chars: int = 50,
        snippet_length: int = 100,
    ):
        """
        参数（均可通过 reasoning_config.yaml [verification] 节配置）：
            verified_threshold   : Token 匹配率 >= 此值时置为 VERIFIED
            context_window_chars : 引用标记前后各取 N 字符作为 claim_text
            snippet_length       : CitationSource.snippet 最大字符数
        """
        self.verified_threshold   = verified_threshold
        self.context_window_chars = context_window_chars
        self.snippet_length       = snippet_length

    def sync_verify(
        self,
        claimed_ids: List[int],
        context_blocks: List[ContextBlock],
    ) -> SyncVerificationResult:
        """
        同步验证：检查引用 ID 是否真实存在于 context blocks。

        优化：预建 dict 索引，将查找从 O(n) 降为 O(1)。
        """
        # O(n) 一次建索引，后续查找 O(1)
        block_index: dict[int, ContextBlock] = {b.id: b for b in context_blocks}

        valid_ids: set[int] = set()
        invalid_ids: List[int] = []
        verified_sources: List[CitationSource] = []

        for cid in claimed_ids:
            block = block_index.get(cid)
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
                        snippet=block.content[:self.snippet_length],
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
        """异步验证：Token 级匹配验证"""
        results: List[VerificationResult] = []

        for claimed in claimed_citations:
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
        """验证单个声称的引用"""
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

        for token in claimed.key_tokens:
            if token in raw_text:
                matched_tokens.append(token)

        match_ratio = (
            len(matched_tokens) / len(claimed.key_tokens)
            if claimed.key_tokens
            else 0.0
        )

        # 状态判断：阈值来自 reasoning_config.yaml [verification.verified_threshold]
        if match_ratio >= self.verified_threshold:
            status = VerificationStatus.VERIFIED
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
        从文本中提取关键 token（名词、数字、版本号）。
        使用预编译正则，避免重复编译开销。
        """
        tokens: List[str] = []

        # 版本号：v1.0, 2.0.0 等
        tokens.extend(re.findall(r'\bv?\d+\.\d+(?:\.\d+)*\b', text))

        # 数字 + 单位
        tokens.extend(re.findall(r'\d+\s*(?:MB|GB|KB|ms|s|min|小时|分钟|秒|天|年|版本|版)', text))

        # 专有名词（驼峰 / 连续大写）
        tokens.extend(re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b|\b[A-Z]{2,}\b', text))

        # 配置项（反引号包裹）
        tokens.extend(re.findall(r'`([^`]+)`', text))

        # 关键词白名单 - 使用预编译正则一次匹配
        tokens.extend(_KEYWORD_PATTERN.findall(text))

        # 保序去重
        return list(dict.fromkeys(tokens))

    def is_valid_citation_id(self, cid: int, context_blocks: List[ContextBlock]) -> bool:
        """
        验证引用 ID 是否有效。

        注意：频繁调用时建议外部预建 {b.id: b} 索引以获得 O(1) 性能。
        """
        return any(b.id == cid for b in context_blocks)

    def clean_answer(
        self,
        answer: str,
        valid_ids: List[int],
        invalid_ids: List[int],
    ) -> str:
        """清理回答中的无效引用，将无效引用标记替换为注释"""
        cleaned = answer
        for cid in invalid_ids:
            cleaned = re.sub(rf'\[{cid}\]', f'[{cid}❓]', cleaned)
        return cleaned

    # ------------------------------------------------------------------ #
    # 私有辅助                                                             #
    # ------------------------------------------------------------------ #

    def _extract_file_path(self, anchor_id: str) -> str:
        """从 anchorId 提取文件路径"""
        parts = anchor_id.split('#')
        return parts[0] if parts else anchor_id

    def _find_context_block(
        self,
        cid: int,
        chunks: List[RetrievedChunk],
    ) -> Optional[RetrievedChunk]:
        """通过 chunkIndex + 1 匹配 ID"""
        return next(
            (c for c in chunks if (c.chunk_index + 1) == cid),
            None,
        )


def create_citation_verifier() -> CitationVerifier:
    """创建引用验证器，参数来自 reasoning_config.yaml"""
    from .config_loader import load_reasoning_config
    cfg = load_reasoning_config()
    return CitationVerifier(
        verified_threshold=cfg.verified_threshold,
        context_window_chars=cfg.context_window_chars,
        snippet_length=cfg.snippet_length,
    )
