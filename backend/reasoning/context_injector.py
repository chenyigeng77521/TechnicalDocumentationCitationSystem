"""
上下文注入器
核心要求 1: 精准注入（转化）

将检索到的"最小充分信息集合"封装并注入模型，逻辑与 TS 版严格一致。
"""

from __future__ import annotations
import math
from typing import List, Tuple, Dict
from ._types import (
    RetrievedChunk,
    ContextBlock,
    GovernanceConfig,
    DEFAULT_GOVERNANCE_CONFIG,
)


class ContextInjector:
    """
    上下文注入器
    负责将检索到的 chunks 转化为模型可消费的上下文格式
    """

    def __init__(
        self,
        config: GovernanceConfig = None,
        chars_per_token: int = 4,
        deduplication_threshold: float = None,
    ):
        """
        参数（均可通过 reasoning_config.yaml [ injection ] 节配置）：
            chars_per_token         : token → 字符数换算第数（1 token ≈ N chars）
            deduplication_threshold : 余弦相似度阈值，超过此值视为重复
        """
        # 直接复用默认配置实例，无需手动展开字段
        self.config = config or DEFAULT_GOVERNANCE_CONFIG
        self.chars_per_token = chars_per_token
        # deduplication_threshold 优先级：显式传入 > GovernanceConfig.deduplication_threshold > yaml
        self.deduplication_threshold = (
            deduplication_threshold
            if deduplication_threshold is not None
            else self.config.deduplication_threshold
        )

    def inject(
        self,
        chunks: List[RetrievedChunk],
        max_tokens: int = None,
    ) -> Tuple[List[ContextBlock], bool, int]:
        """
        将检索到的 chunks 注入为上下文块
       

        Returns:
            (blocks, truncated, total_chars)
        """
        if max_tokens is None:
            max_tokens = self.config.max_context_tokens

        sorted_chunks = sorted(
            chunks,
            key=lambda c: (c.reranker_score or 0),
            reverse=True,
        )

        deduplicated = self._deduplicate(sorted_chunks)

        blocks_raw, total_chars, was_truncated = self._truncate(deduplicated, max_tokens)

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
       
        """
        parts = []
        for block in blocks:
            formatted = f"[ID: {block.id}, Source: {block.source}]\n{block.content}"
            if block.is_truncated:
                formatted += "\n[此段内容已截断，建议查阅原文]"
            parts.append(formatted)
        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #

    def _format_source(self, chunk: RetrievedChunk) -> str:
        """
        格式化来源字符串
        """
        path = chunk.anchor_id
        title = f" | {chunk.title_path}" if chunk.title_path else ""
        return f"{path}{title}"

    def _deduplicate(self, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """
        去重：移除高度相似的 chunk
        优化：预先计算所有向量，避免重复调用 _get_token_vector。
        """
        if not chunks:
            return []
        vectors = [self._get_token_vector(c.content) for c in chunks]
        result_indices: List[int] = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            if not any(
                self._cosine_similarity(vec, vectors[j]) >= self.deduplication_threshold
                for j in result_indices
            ):
                result_indices.append(i)
        return [chunks[i] for i in result_indices]

    def _get_token_vector(self, text: str) -> Dict[str, int]:
        """
        简单 token 向量化（用于去重）
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
        计算余弦相似度
        优化：点积只需遍历 vec1 的 key，避免遍历 union 中的无效计算。
        """
        if not vec1 or not vec2:
            return 0.0
        dot_product = sum(v * vec2.get(k, 0) for k, v in vec1.items())
        norm1 = sum(v * v for v in vec1.values())
        norm2 = sum(v * v for v in vec2.values())
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (math.sqrt(norm1) * math.sqrt(norm2))

    def _truncate(
        self,
        chunks: List[RetrievedChunk],
        max_tokens: int,
    ) -> Tuple[List[RetrievedChunk], int, bool]:
        """
        截断：确保不超过最大 token 数
        粗略估算：1 token ≈ 4 chars
        """
        result: List[RetrievedChunk] = []
        total_chars = 0
        max_chars = max_tokens * self.chars_per_token  # 来自 reasoning_config.yaml [injection.chars_per_token]

        for chunk in chunks:
            new_total = total_chars + chunk.char_count
            if new_total > max_chars and result:
                result[-1].is_truncated = True
                return result, total_chars, True
            result.append(chunk)
            total_chars = new_total

        return result, total_chars, False


def create_context_injector(config: GovernanceConfig = None) -> ContextInjector:
    """创建默认上下文注入器，参数来自 reasoning_config.yaml"""
    from .config_loader import load_reasoning_config
    rc = load_reasoning_config()
    return ContextInjector(
        config=config,
        chars_per_token=rc.chars_per_token,
        deduplication_threshold=rc.inj_deduplication_threshold,
    )
