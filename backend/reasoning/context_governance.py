"""
动态治理器
核心要求 3: 动态治理（清理）- 实时剔除冗余或冲突信息
"""

from __future__ import annotations
from typing import List, Optional
from dataclasses import dataclass, field
from ._types import (
    RetrievedChunk,
    GovernanceConfig,
    DEFAULT_GOVERNANCE_CONFIG,
)


# ============================================================
# ============================================================
@dataclass
class GovernanceResult:
    chunks: List[RetrievedChunk]
    removed: dict           # {duplicates, conflicts, low_score}
    stats: dict             # {original_count, final_count, removal_ratio}


class ContextGovernor:
    """
    上下文治理器
    负责动态清理和优化上下文
    """

    def __init__(
        self,
        config: GovernanceConfig = None,
        min_score_threshold: float = 0.1,
        conflict_offset_threshold: int = 500,
        conflict_similarity_threshold: float = 0.7,
        token_min_length: int = 2,
    ):
        """
        参数（均可通过 reasoning_config.yaml [ governance ] 节配置）：
            min_score_threshold           : reranker_score 低于此值的块被丢弃
            conflict_offset_threshold     : 冲突判定最大字符偏移
            conflict_similarity_threshold : 冲突判定最小 Jaccard 相似度
            token_min_length              : 分词结果中长度 <= 此值的 token 被过滤
        """
        # 直接复用默认配置实例，无需手动展开字段
        self.config = config or DEFAULT_GOVERNANCE_CONFIG
        self.min_score_threshold          = min_score_threshold
        self.conflict_offset_threshold    = conflict_offset_threshold
        self.conflict_similarity_threshold = conflict_similarity_threshold
        self.token_min_length             = token_min_length

    def govern(self, chunks: List[RetrievedChunk]) -> GovernanceResult:
        """
        治理检索结果
        1. 去重（移除高度相似的 chunk）
        2. 解决冲突（同主题的不同说法）
        3. 过滤低分

        优化：预先缓存全部 token set，避免去重/冲突检测重复分词。
        """
        original_count = len(chunks)
        removed = {
            'duplicates': [],
            'conflicts': [],
            'low_score': [],
        }

        sorted_chunks = sorted(chunks, key=lambda c: c.reranker_score or 0, reverse=True)

        # 预先缓存每个 chunk 的 token set，避免去重和冲突检测重复分词
        token_sets = [set(self._tokenize(c.content)) for c in sorted_chunks]

        keep_flags = [True] * len(sorted_chunks)
        for i in range(len(sorted_chunks)):
            if not keep_flags[i]:
                continue
            for j in range(i + 1, len(sorted_chunks)):
                if not keep_flags[j]:
                    continue
                sim = self._jaccard_from_sets(token_sets[i], token_sets[j])
                if sim >= self.config.deduplication_threshold:
                    keep_flags[j] = False
                    removed['duplicates'].append(sorted_chunks[j])
        deduplicated = [c for c, keep in zip(sorted_chunks, keep_flags) if keep]
        dedup_sets = [ts for ts, keep in zip(token_sets, keep_flags) if keep]

        resolved: List[RetrievedChunk] = []
        resolved_sets: List[set] = []
        for chunk, ts in zip(deduplicated, dedup_sets):
            conflict_idx = self._find_conflict_index(chunk, ts, resolved, resolved_sets)
            if conflict_idx is not None:
                if self.config.conflict_resolution == 'keep_higher_score':
                    existing = resolved[conflict_idx]
                    if (chunk.reranker_score or 0) > (existing.reranker_score or 0):
                        removed['conflicts'].append(existing)
                        resolved[conflict_idx] = chunk
                        resolved_sets[conflict_idx] = ts
                    else:
                        removed['conflicts'].append(chunk)
                else:
                    # keep_both 或 merge - 保留两者
                    resolved.append(chunk)
                    resolved_sets.append(ts)
            else:
                resolved.append(chunk)
                resolved_sets.append(ts)

        final = []
        for chunk in resolved:
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
        合并冲突信息（当策略为 merge 时）
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
        """更新配置"""
        self.config = config

    def set_min_score_threshold(self, threshold: float) -> None:
        """设置最小分阈值"""
        self.min_score_threshold = threshold

    # ------------------------------------------------------------------ #
    # 私有辅助                                                             #
    # ------------------------------------------------------------------ #

    def _compute_similarity(self, a: RetrievedChunk, b: RetrievedChunk) -> float:
        """
        计算 Jaccard 相似度（token 重叠度）
        """
        tokens_a = set(self._tokenize(a.content))
        tokens_b = set(self._tokenize(b.content))
        return self._jaccard_from_sets(tokens_a, tokens_b)


def create_context_governor(
    config: GovernanceConfig = None,
    min_score_threshold: float = None,
) -> ContextGovernor:
    """创建上下文治理器，参数来自 reasoning_config.yaml"""
    from .config_loader import load_reasoning_config
    rc = load_reasoning_config()
    return ContextGovernor(
        config=config,
        min_score_threshold=min_score_threshold if min_score_threshold is not None else rc.min_score_threshold,
        conflict_offset_threshold=rc.conflict_offset_threshold,
        conflict_similarity_threshold=rc.conflict_similarity_threshold,
        token_min_length=rc.token_min_length,
    )
