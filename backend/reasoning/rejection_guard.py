"""
拒答守卫
核心要求 4: 边界严控（拒答）- 严格限制推理范围

修订对齐（修订.md §3.2 / §3.4）：
  - 拒答文本统一为："抱歉，我无法从提供的文档中找到答案。"（README §7.1 强制格式）
  - 新增 is_valid_refusal() 验证函数
  - 新增 safety_check_refusal_rate() 防全拒答保护
  - RejectionReason 枚举对齐三级门控（empty_retrieval / score_below_threshold / llm_judged_unanswerable）
"""

from __future__ import annotations
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field
from ._types import RetrievedChunk, RERANKER_SCORE_THRESHOLD


# ============================================================
# 统一拒答文本（README §7.1 强制格式，不得改动任何词语）
# ============================================================
REFUSAL_TEXT = "抱歉，我无法从提供的文档中找到答案。"


def is_valid_refusal(answer: str) -> bool:
    """
    验证 LLM 输出是否符合拒答格式规范。
    README §4.2 acceptable_response_keywords: ["抱歉", "无法", "未找到", "不存在"]
    README §7.1 统一表述示例: "抱歉,我无法从提供的文档中找到答案"
    """
    must_have = ["抱歉", "无法"]
    must_not  = ["确实存在", "可以这样使用"]
    return (all(kw in answer for kw in must_have) and
            not any(kw in answer for kw in must_not))


def safety_check_refusal_rate(session_stats: dict) -> bool:
    """
    评测期间监控：若拒答率超过 60%，触发告警。
    防止因阈值设置过高导致全部拒答（有答案题 75 道全错）。
    对齐修订.md §3.4 防"全拒答"保护（README §7.1 雷 2）。
    """
    import logging
    refusal_rate = session_stats.get("refused", 0) / max(session_stats.get("total", 1), 1)
    if refusal_rate > 0.60:
        logging.warning(f"拒答率异常高：{refusal_rate:.1%}，请检查阈值设置")
        return False
    return True


# ============================================================
# ============================================================
class RejectionReason(str, Enum):
    NO_CHUNKS            = 'empty_retrieval'          # 门控1：无检索结果
    LOW_SCORE            = 'score_below_threshold'    # 门控2：分数不足
    LLM_UNANSWERABLE     = 'llm_judged_unanswerable'  # 门控3：LLM 判断无法回答
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
    在进入 LLM 推理之前进行多重检查（三级门控）
    """

    def __init__(self, score_threshold: float = RERANKER_SCORE_THRESHOLD):
        self.score_threshold = score_threshold

    def evaluate(self, query: str, chunks: List[RetrievedChunk]) -> RejectionResult:
        """
        检查是否应该拒答（对齐修订.md §3.4 三级拒答触发机制）
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

        # 2. 门控1：无检索结果（empty_retrieval）
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

        # 3. 门控2：检索得分不足（score_below_threshold）
        #    阈值 0.40 基于 bge-reranker-v2-m3 分布调参（防误拒过严，对齐雷1）
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

        # 4. 通过门控1+2（门控3：llm_judged_unanswerable 在 pipeline 层处理）
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
        生成拒答消息（统一格式，对齐 README §7.1 强制要求）
        """
        # 统一拒答文本（评测必须包含"抱歉"+"无法从提供的文档中找到答案"）
        return REFUSAL_TEXT

    def get_debug_info(self, result: RejectionResult) -> str:
        """
        获取调试信息（供评委验证检索质量）
        """
        if not result.debug_info:
            return ''
        d = result.debug_info
        top_scores_str = ', '.join(f'{s:.2f}' for s in d.get('top_scores', []))
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
