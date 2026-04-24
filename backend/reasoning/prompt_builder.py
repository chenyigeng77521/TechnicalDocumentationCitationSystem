"""
提示词构建器
核心要求 4: 边界严控（拒答）- 构建严格的提示词，确保模型只基于上下文回答
对齐 TypeScript: backend/chunking-rag/src/Reasoning/prompt_builder.ts
"""

from __future__ import annotations
import re
from typing import List, Optional, Tuple
from .types import ContextBlock


# ============================================================
# 对齐 TS 的提示词模板常量
# ============================================================

SYSTEM_PROMPT = """你是一个严格的技术文档问答助手。

【核心规则】
1. 仅根据下方提供的 Context 回答，严禁使用任何外部知识或猜测。
2. 每个事实性陈述句末必须标注来源，格式为 [n]（n 为对应 Chunk 的 ID）。
3. 如果 Context 中不包含回答所需信息，直接回复："根据现有文档无法回答此问题。"
4. 如果 Context 标注了"内容已截断"，可说明信息不足并建议查阅原文。
5. 不得合并多个 Chunk 的内容进行推断，每条引用必须有直接支撑。
6. 保持回答简洁准确，不要添加冗余解释。

【引用规则】
- 每个句子的引用必须是直接的、一一对应的
- 避免泛泛而谈，每个观点都需要具体引用支撑
- 数字、版本号、配置项等关键信息必须标注来源"""

USER_PROMPT_TEMPLATE = """【Context】
{context}

---

【问题】
{query}

---

【回答要求】
请严格基于 Context 回答，每个事实陈述后标注引用。"""

REJECTION_PROMPT = """根据现有文档无法回答此问题。

提示：当前检索得分（{max_score}）低于系统阈值，无法确保回答准确性。
建议：
1. 尝试重新表述问题
2. 上传更多相关文档
3. 确认文档中确实包含此信息"""

NO_LLM_PROMPT = """【问题】
{query}

【检索到的相关文档】
{context}

---
根据上述检索结果，以下是相关信息汇总：

{summary}"""


class PromptBuilder:
    """
    提示词构建器 - 对齐 TS PromptBuilder class
    """

    def __init__(self, system_prompt: str = None):
        self.system_prompt = system_prompt or SYSTEM_PROMPT

    def build(
        self,
        query: str,
        context_blocks: List[ContextBlock],
        context_truncated: bool = False,
    ) -> Tuple[str, str]:
        """
        构建完整的推理提示词 - 对齐 TS build()
        Returns: (system_prompt, user_prompt)
        """
        context = self._format_context(context_blocks)

        extended_system = self.system_prompt
        if context_truncated:
            extended_system += '\n\n⚠️ 警告：以下 Context 因长度限制被截断，可能不包含完整信息。'

        user_prompt = (
            USER_PROMPT_TEMPLATE
            .replace('{context}', context)
            .replace('{query}', query)
        )

        return extended_system, user_prompt

    def build_rejection(self, max_score: float) -> Tuple[str, str]:
        """
        构建拒答提示词 - 对齐 TS buildRejection()
        Returns: (system_prompt, user_prompt)
        """
        user = REJECTION_PROMPT.replace('{max_score}', f'{max_score:.2f}')
        return self.system_prompt, user

    def build_no_llm(
        self,
        query: str,
        context_blocks: List[ContextBlock],
    ) -> Tuple[str, str]:
        """
        构建无 LLM 模式提示词 - 对齐 TS buildNoLLM()
        Returns: (system_prompt, user_prompt)
        """
        context = self._format_context(context_blocks)
        summary = self._summarize_results(context_blocks)
        user = (
            NO_LLM_PROMPT
            .replace('{query}', query)
            .replace('{context}', context)
            .replace('{summary}', summary)
        )
        return '你是一个信息检索助手，负责汇总检索结果。', user

    def extract_citation_ids(self, answer: str) -> List[int]:
        """
        从 LLM 回答中提取引用 ID - 对齐 TS extractCitationIds()
        """
        ids: List[int] = []
        for match in re.finditer(r'\[(\d+)\]', answer):
            cid = int(match.group(1))
            if cid not in ids:
                ids.append(cid)
        return ids

    def build_stream_message(
        self,
        query: str,
        context_blocks: List[ContextBlock],
        context_truncated: bool = False,
    ) -> str:
        """
        构建用于流式生成的单条消息 - 对齐 TS buildStreamMessage()
        """
        context = self._format_context(context_blocks)
        prompt = f"【Context】\n{context}\n\n"

        if context_truncated:
            prompt += "⚠️ 注意：Context 因长度限制被截断，以下回答可能不完整。\n\n"

        prompt += f"【问题】{query}\n\n"
        prompt += "请严格基于 Context 回答，每个事实陈述后标注 [引用ID]。"
        return prompt

    # ------------------------------------------------------------------ #
    # 私有辅助                                                             #
    # ------------------------------------------------------------------ #

    def _format_context(self, blocks: List[ContextBlock]) -> str:
        """格式化上下文块 - 对齐 TS formatContext()"""
        if not blocks:
            return '（无相关文档）'
        parts = []
        for block in blocks:
            formatted = f"[ID: {block.id}, Source: {block.source}]\n{block.content}"
            if block.is_truncated:
                formatted += '\n[此段内容已截断，建议查阅原文]'
            parts.append(formatted)
        return '\n\n---\n\n'.join(parts)

    def _summarize_results(self, blocks: List[ContextBlock]) -> str:
        """汇总检索结果（无 LLM 模式）- 对齐 TS summarizeResults()"""
        lines = []
        for i, block in enumerate(blocks):
            snippet = block.content[:200]
            suffix = '...' if len(block.content) > 200 else ''
            lines.append(f"{i + 1}. {snippet}{suffix}")
        return '\n'.join(lines)


def create_prompt_builder(system_prompt: str = None) -> PromptBuilder:
    """创建提示词构建器 - 对齐 TS createPromptBuilder()"""
    return PromptBuilder(system_prompt)
