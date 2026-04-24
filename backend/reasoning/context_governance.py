"""
动态治理器
核心要求 3: 动态治理（清理）- 实时剔除冗余或冲突信息
对齐 TypeScript: backend/chunking-rag/src/Reasoning/context_governance.ts
"""

from __future__ import annotations
from typing import List, Optional
from dataclasses import dataclass, field
from .types import (
    RetrievedChunk,
    GovernanceConfig,
    DEFAULT_GOVERNANCE_CONFIG,
)


# ============================================================
# 对齐 TS: GovernanceResult interface
# ============================================================
@dataclass
class GovernanceResult:
    chunks: List[RetrievedChunk]
    removed: dict           # {duplicates, conflicts, low_score}
    stats: dict             # {original_count, final_count, removal_ratio}


class ContextGovernor:
    """
    上下文治理器 - 对齐 TS ContextGovernor class
    负责动态清理和优化上下文
    """

    def __init__(
        self,
        config: GovernanceConfig = None,
        min_score_threshold: float = 0.1,
    ):
        self.config = config or GovernanceConfig(
            max_context_tokens=DEFAULT_GOVERNANCE_CONFIG.max_context_tokens,
            conflict_resolution=DEFAULT_GOVERNANCE_CONFIG.conflict_resolution,
            deduplication_threshold=DEFAULT_GOVERNANCE_CONFIG.deduplication_threshold,
        )
        self.min_score_threshold = min_score_threshold

    def govern(self, chunks: List[RetrievedChunk]) -> GovernanceResult:
        """
        治理检索结果 - 对齐 TS govern()
        1. 去重（移除高度相似的 chunk）
        2. 解决冲突（同主题的不同说法）
        3. 过滤低分
        """
        original_count = len(chunks)
        removed = {
            'duplicates': [],
            'conflicts': [],
            'low_score': [],
        }

        # 按得分降序 - 对齐 TS
        filtered = sorted(chunks, key=lambda c: (c.reranker_score or 0), reverse=True)

        # 1. 去重 - 对齐 TS
        deduplicated: List[RetrievedChunk] = []
        for chunk in filtered:
            is_dup = any(
                self._compute_similarity(chunk, existing) >= self.config.deduplication_threshold
                for existing in deduplicated
            )
            if is_dup:
                removed['duplicates'].append(chunk)
            else:
                deduplicated.append(chunk)
        filtered = deduplicated

        # 2. 冲突解决 - 对齐 TS
        resolved: List[RetrievedChunk] = []
        for chunk in filtered:
            conflict = self._find_conflict(chunk, resolved)
            if conflict:
                if self.config.conflict_resolution == 'keep_higher_score':
                    if (chunk.reranker_score or 0) > (conflict.reranker_score or 0):
                        removed['conflicts'].append(conflict)
                        resolved.remove(conflict)
                        resolved.append(chunk)
                    else:
                        removed['conflicts'].append(chunk)
                else:
                    # keep_both 或 merge - 保留两者
                    resolved.append(chunk)
            else:
                resolved.append(chunk)
        filtered = resolved

        # 3. 过滤低分 - 对齐 TS
        final: List[RetrievedChunk] = []
        for chunk in filtered:
            if (chunk.reranker_score or 0) >= self.min_score_threshold:
                final.append(chunk)
            else:
                removed['low_score'].append(chunk)

        return GovernanceResult(
            chunks=final,
            removed=removed,
            stats={
                'original_count': original_count,
                'final_count': len(final),
                'removal_ratio': (original_count - len(final)) / original_count if original_count else 0.0,
            },
        )

    def merge_conflicts(self, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """
        合并冲突信息（当策略为 merge 时）- 对齐 TS mergeConflicts()
        """
        merged: List[RetrievedChunk] = []
        processed: set = set()

        for chunk in chunks:
            key = f"{chunk.file_path}:{chunk.chunk_index}"
            if key in processed:
                continue
            processed.add(key)

            mergeable = [
                c for c in chunks
                if c is not chunk
                and c.file_path == chunk.file_path
                and abs(c.char_offset_start - chunk.char_offset_start) < 200
                and f"{c.file_path}:{c.chunk_index}" not in processed
            ]

            if mergeable:
                all_content = '\n\n'.join([chunk.content] + [m.content for m in mergeable])
                max_end = max([chunk.char_offset_end] + [m.char_offset_end for m in mergeable])
                merged_chunk = RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    file_path=chunk.file_path,
                    file_hash=chunk.file_hash,
                    content=all_content,
                    anchor_id=chunk.anchor_id,
                    title_path=chunk.title_path,
                    char_offset_start=chunk.char_offset_start,
                    char_offset_end=max_end,
                    char_count=len(all_content),
                    is_truncated=chunk.is_truncated,
                    chunk_index=chunk.chunk_index,
                    content_type=chunk.content_type,
                    reranker_score=chunk.reranker_score,
                    raw_text=chunk.raw_text,
                )
                merged.append(merged_chunk)
                for m in mergeable:
                    processed.add(f"{m.file_path}:{m.chunk_index}")
            else:
                merged.append(chunk)

        return merged

    def update_config(self, config: GovernanceConfig) -> None:
        """更新配置 - 对齐 TS updateConfig()"""
        self.config = config

    def set_min_score_threshold(self, threshold: float) -> None:
        """设置最小分阈值 - 对齐 TS setMinScoreThreshold()"""
        self.min_score_threshold = threshold

    # ------------------------------------------------------------------ #
    # 私有辅助                                                             #
    # ------------------------------------------------------------------ #

    def _compute_similarity(self, a: RetrievedChunk, b: RetrievedChunk) -> float:
        """
        计算 Jaccard 相似度（token 重叠度）- 对齐 TS computeSimilarity()
        """
        tokens_a = set(self._tokenize(a.content))
        tokens_b = set(self._tokenize(b.content))
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        return intersection / union if union else 0.0

    def _tokenize(self, text: str) -> List[str]:
        """分词 - 对齐 TS tokenize()"""
        import re
        tokens = re.split(r'[\s,.!?;:()\[\]{}]+', text.lower())
        return [t for t in tokens if len(t) > 2]

    def _find_conflict(
        self,
        chunk: RetrievedChunk,
        existing: List[RetrievedChunk],
    ) -> Optional[RetrievedChunk]:
        """
        查找冲突（同主题的不同说法）- 对齐 TS findConflict()
        相同文件 + 相邻位置 = 可能冲突
        """
        for ex in existing:
            if ex.file_path == chunk.file_path:
                offset_diff = abs(ex.char_offset_start - chunk.char_offset_start)
                if offset_diff < 500 and self._compute_similarity(ex, chunk) > 0.7:
                    return ex
        return None


def create_context_governor(
    config: GovernanceConfig = None,
    min_score_threshold: float = None,
) -> ContextGovernor:
    """创建上下文治理器 - 对齐 TS createContextGovernor()"""
    kwargs = {}
    if config:
        kwargs['config'] = config
    if min_score_threshold is not None:
        kwargs['min_score_threshold'] = min_score_threshold
    return ContextGovernor(**kwargs)
