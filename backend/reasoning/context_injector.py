"""
上下文注入器
核心要求 1: 精准注入（转化）
对齐 TypeScript: backend/chunking-rag/src/Reasoning/context_injector.ts

将检索到的"最小充分信息集合"封装并注入模型，逻辑与 TS 版严格一致。
"""

from __future__ import annotations
import math
from typing import List, Tuple, Dict
from .types import (
    RetrievedChunk,
    ContextBlock,
    GovernanceConfig,
    DEFAULT_GOVERNANCE_CONFIG,
)


class ContextInjector:
    """
    上下文注入器 - 对齐 TS ContextInjector class
    负责将检索到的 chunks 转化为模型可消费的上下文格式
    """

    def __init__(self, config: GovernanceConfig = None):
        self.config = config or GovernanceConfig(
            max_context_tokens=DEFAULT_GOVERNANCE_CONFIG.max_context_tokens,
            conflict_resolution=DEFAULT_GOVERNANCE_CONFIG.conflict_resolution,
            deduplication_threshold=DEFAULT_GOVERNANCE_CONFIG.deduplication_threshold,
        )

    def inject(
        self,
        chunks: List[RetrievedChunk],
        max_tokens: int = None,
    ) -> Tuple[List[ContextBlock], bool, int]:
        """
        将检索到的 chunks 注入为上下文块
        对齐 TS: inject(chunks, maxTokens) -> { blocks, truncated, totalChars }

        Returns:
            (blocks, truncated, total_chars)
        """
        if max_tokens is None:
            max_tokens = self.config.max_context_tokens

        # 按 reranker 得分降序 - 对齐 TS
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (c.reranker_score or 0),
            reverse=True,
        )

        # 去重：移除高度相似的 chunk - 对齐 TS deduplicate()
        deduplicated = self._deduplicate(sorted_chunks)

        # 截断：确保不超过最大 token 数 - 对齐 TS truncate()
        blocks_raw, total_chars, was_truncated = self._truncate(deduplicated, max_tokens)

        # 分配 ID（从 1 开始）- 对齐 TS
        blocks = [
            ContextBlock(
                id=index + 1,
                source=self._format_source(chunk),
                content=chunk.content,
                is_truncated=chunk.is_truncated,
                anchor_id=chunk.anchor_id,
                title_path=chunk.title_path,
                reranker_score=chunk.reranker_score or 0.0,
            )
            for index, chunk in enumerate(blocks_raw)
        ]

        return blocks, was_truncated, total_chars

    def format_for_prompt(self, blocks: List[ContextBlock]) -> str:
        """
        将上下文块转换为可读字符串格式，用于注入 LLM prompt
        对齐 TS: formatForPrompt(blocks)
        """
        parts = []
        for block in blocks:
            formatted = f"[ID: {block.id}, Source: {block.source}]\n{block.content}"
            if block.is_truncated:
                formatted += "\n[此段内容已截断，建议查阅原文]"
            parts.append(formatted)
        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # 私有方法 - 对齐 TS 私有方法                                          #
    # ------------------------------------------------------------------ #

    def _format_source(self, chunk: RetrievedChunk) -> str:
        """
        格式化来源字符串 - 对齐 TS formatSource()
        """
        path = chunk.anchor_id
        title = f" | {chunk.title_path}" if chunk.title_path else ""
        return f"{path}{title}"

    def _deduplicate(self, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """
        去重：移除高度相似的 chunk - 对齐 TS deduplicate()
        使用与 TS 相同的余弦相似度算法
        """
        result: List[RetrievedChunk] = []
        for chunk in chunks:
            is_dup = any(
                self._cosine_similarity(
                    self._get_token_vector(chunk.content),
                    self._get_token_vector(existing.content),
                ) >= self.config.deduplication_threshold
                for existing in result
            )
            if not is_dup:
                result.append(chunk)
        return result

    def _get_token_vector(self, text: str) -> Dict[str, int]:
        """
        简单 token 向量化（用于去重）- 对齐 TS getTokenVector()
        """
        import re
        tokens = re.split(r"[\s,.!?;:()\[\]{}]+", text.lower())
        tokens = [t for t in tokens if len(t) > 2]
        vector: Dict[str, int] = {}
        for token in tokens:
            vector[token] = vector.get(token, 0) + 1
        return vector

    def _cosine_similarity(self, vec1: Dict[str, int], vec2: Dict[str, int]) -> float:
        """
        计算余弦相似度 - 对齐 TS cosineSimilarity()
        """
        keys = set(vec1.keys()) | set(vec2.keys())
        dot_product = 0.0
        norm1 = 0.0
        norm2 = 0.0
        for key in keys:
            v1 = vec1.get(key, 0)
            v2 = vec2.get(key, 0)
            dot_product += v1 * v2
            norm1 += v1 * v1
            norm2 += v2 * v2
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (math.sqrt(norm1) * math.sqrt(norm2))

    def _truncate(
        self,
        chunks: List[RetrievedChunk],
        max_tokens: int,
    ) -> Tuple[List[RetrievedChunk], int, bool]:
        """
        截断：确保不超过最大 token 数 - 对齐 TS truncate()
        粗略估算：1 token ≈ 4 chars
        """
        result: List[RetrievedChunk] = []
        total_chars = 0
        max_chars = max_tokens * 4  # 与 TS 保持一致

        for chunk in chunks:
            new_total = total_chars + chunk.char_count
            if new_total > max_chars and result:
                # 标记最后一个 chunk 为截断 - 对齐 TS
                result[-1].is_truncated = True
                return result, total_chars, True
            result.append(chunk)
            total_chars = new_total

        return result, total_chars, False


def create_context_injector(config: GovernanceConfig = None) -> ContextInjector:
    """创建默认上下文注入器 - 对齐 TS createContextInjector()"""
    return ContextInjector(config)
