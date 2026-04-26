"""
拒答守卫
核心要求 4: 边界严控（拒答）- 严格限制推理范围
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field
from ._types import RetrievedChunk, RERANKER_SCORE_THRESHOLD


# ============================================================
# ============================================================
class RejectionReason(str, Enum):
    NO_CHUNKS            = 'no_chunks'
    LOW_SCORE            = 'low_score'
    EMPTY_QUERY          = 'empty_query'
    CONTEXT_EXCEEDS_LIMIT = 'context_exceeds_limit'


# ============================================================
# ============================================================
@dataclass
class RejectionResult:
    should_reject: bool
    reason: Optional[RejectionReason] = None
    message: Optional[str] = None
    max_score: Optional[float] = None
    debug_info: Optional[dict] = None


class RejectionGuard:
    """
    拒答守卫
    在进入 LLM 推理之前进行多重检查
    """

    def __init__(self, score_threshold: float = RERANKER_SCORE_THRESHOLD):
        self.score_threshold = score_threshold

    def evaluate(self, query: str, chunks: List[RetrievedChunk]) -> RejectionResult:
        """
        检查是否应该拒答
        """
        # 1. 空查询检查
        if not query or not query.strip():
            return RejectionResult(
                should_reject=True,
                reason=RejectionReason.EMPTY_QUERY,
                message='查询内容为空',
                debug_info={
                    'top_scores': [],
                    'threshold': self.score_threshold,
                    'chunk_count': 0,
                },
            )

        # 2. 无检索结果检查
        if not chunks:
            return RejectionResult(
                should_reject=True,
                reason=RejectionReason.NO_CHUNKS,
                message='未检索到相关文档',
                debug_info={
                    'top_scores': [],
                    'threshold': self.score_threshold,
                    'chunk_count': 0,
                },
            )

        # 3. 检索得分检查
        scores = [c.reranker_score or 0.0 for c in chunks]
        max_score = max(scores)

        if max_score < self.score_threshold:
            return RejectionResult(
                should_reject=True,
                reason=RejectionReason.LOW_SCORE,
                message=f'检索得分（{max_score:.2f}）低于系统阈值（{self.score_threshold}）',
                max_score=max_score,
                debug_info={
                    'top_scores': scores[:5],
                    'threshold': self.score_threshold,
                    'chunk_count': len(chunks),
                },
            )

        # 4. 通过所有检查
        return RejectionResult(
            should_reject=False,
            max_score=max_score,
            debug_info={
                'top_scores': scores[:5],
                'threshold': self.score_threshold,
                'chunk_count': len(chunks),
            },
        )

    def generate_rejection_message(self, result: RejectionResult) -> str:
        """
        生成拒答消息
        """
        if result.reason == RejectionReason.NO_CHUNKS:
            return (
                '根据现有文档无法回答此问题。\n\n'
                '提示：未检索到相关文档，请尝试：\n'
                '1. 使用不同的关键词\n'
                '2. 确认文档中包含相关信息\n'
                '3. 上传更多相关文档'
            )
        elif result.reason == RejectionReason.LOW_SCORE:
            return (
                f'根据现有文档无法回答此问题。\n\n'
                f'提示：当前检索得分（{result.max_score:.2f}）低于系统阈值（{self.score_threshold}），无法确保回答准确性。\n'
                f'建议：\n'
                f'1. 尝试重新表述问题\n'
                f'2. 使用更具体的关键词\n'
                f'3. 确认文档中包含此信息'
            )
        elif result.reason == RejectionReason.EMPTY_QUERY:
            return '请输入有效的问题'
        elif result.reason == RejectionReason.CONTEXT_EXCEEDS_LIMIT:
            return '问题过于复杂，请简化后重试'
        else:
            return '根据现有文档无法回答此问题'

    def get_debug_info(self, result: RejectionResult) -> str:
        """
        获取调试信息（供评委验证检索质量）
        """
        if not result.debug_info:
            return ''
        d = result.debug_info
        top_scores_str = ', '.join(f'{s:.2f}' for s in d.get('top_scores', []))
        # 修复：将条件表达式从格式化字符串中拆出，提高可读性
        score_str = f"{result.max_score:.2f}" if result.max_score is not None else "N/A"
        info = '\n\n--- 调试信息（供评委验证）---\n'
        info += f"最高检索得分: {score_str}\n"
        info += f"系统阈值: {d.get('threshold')}\n"
        info += f"检索到的文档块数: {d.get('chunk_count')}\n"
        info += f"Top 5 得分: [{top_scores_str}]\n"
        info += '--------------------------------'
        return info

    def set_threshold(self, threshold: float) -> None:
        """设置得分阈值"""
        self.score_threshold = threshold

    def get_threshold(self) -> float:
        """获取当前阈值"""
        return self.score_threshold


def create_rejection_guard(score_threshold: float = None) -> RejectionGuard:
    """创建拒答守卫，默认阈值来自 reasoning_config.yaml"""
    if score_threshold is not None:
        return RejectionGuard(score_threshold)
    from .config_loader import load_reasoning_config
    return RejectionGuard(load_reasoning_config().score_threshold)
