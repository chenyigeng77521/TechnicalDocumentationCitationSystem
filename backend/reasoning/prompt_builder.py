"""
提示词构建器
核心要求 4: 边界严控（拒答）- 构建严格的提示词，确保模型只基于上下文回答

v2 变更：
  - 提示词模板改由 prompts/prompts.yaml 统一维护
  - 通过 config_loader.load_prompts_config() 加载（带 lru_cache）
  - 保留模块级常量（SYSTEM_PROMPT 等）作为向后兼容别名，首次访问时懒加载
"""

from __future__ import annotations
import re
from typing import List, Optional, Tuple
from ._types import ContextBlock


# ============================================================
# 懒加载模板（向后兼容，直接 import 常量仍可使用）
# ============================================================

def _get_prompts():
    """懒加载 PromptsConfig，避免模块导入时触发文件 IO"""
    from .config_loader import load_prompts_config
    return load_prompts_config()


# 向后兼容别名（首次访问时从 prompts.yaml 加载）
class _LazyStr(str):
    """惰性字符串代理，允许 `SYSTEM_PROMPT` 等常量在首次使用时才读取配置。"""
    pass


def __getattr__(name: str):
    """模块级 __getattr__：当常量被直接 import 时，从配置文件读取。"""
    _alias_map = {
        'SYSTEM_PROMPT':       lambda p: p.system_prompt,
        'USER_PROMPT_TEMPLATE': lambda p: p.user_prompt_template,
        'REJECTION_PROMPT':    lambda p: p.rejection_prompt,
        'NO_LLM_PROMPT':       lambda p: p.no_llm_prompt,
    }
    if name in _alias_map:
        return _alias_map[name](_get_prompts())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================
# PromptBuilder 类
# ============================================================

class PromptBuilder:
    """
    提示词构建器

    参数：
        system_prompt: 自定义系统提示词字符串（传 None 时从 prompts.yaml 读取）
        prompts_file:  自定义 prompts.yaml 路径（None = 使用默认路径）
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        prompts_file: Optional[str] = None,
    ):
        self._prompts_file = prompts_file
        self._override_system_prompt = system_prompt  # None = 使用 yaml

    # ── 属性懒加载 ──────────────────────────────────────────

    @property
    def _cfg(self):
        """懒加载 PromptsConfig（带缓存）"""
        from .config_loader import load_prompts_config
        return load_prompts_config(self._prompts_file)

    @property
    def system_prompt(self) -> str:
        return self._override_system_prompt or self._cfg.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str):
        self._override_system_prompt = value

    # ── 公开接口 ────────────────────────────────────────────

    def build(
        self,
        query: str,
        context_blocks: List[ContextBlock],
        context_truncated: bool = False,
    ) -> Tuple[str, str]:
        """
        构建完整的推理提示词
        Returns: (system_prompt, user_prompt)
        """
        context = self._format_context(context_blocks)

        extended_system = self.system_prompt
        if context_truncated:
            extended_system += self._cfg.system_truncation_suffix

        user_prompt = (
            self._cfg.user_prompt_template
            .replace('{context}', context)
            .replace('{query}', query)
        )

        return extended_system, user_prompt

    def build_rejection(self, max_score: float) -> Tuple[str, str]:
        """
        构建拒答提示词
        Returns: (system_prompt, user_prompt)
        """
        user = self._cfg.rejection_prompt.replace('{max_score}', f'{max_score:.2f}')
        return self.system_prompt, user

    def build_no_llm(
        self,
        query: str,
        context_blocks: List[ContextBlock],
    ) -> Tuple[str, str]:
        """
        构建无 LLM 模式提示词
        Returns: (system_prompt, user_prompt)
        """
        context = self._format_context(context_blocks)
        summary = self._summarize_results(context_blocks)
        user = (
            self._cfg.no_llm_prompt
            .replace('{query}', query)
            .replace('{context}', context)
            .replace('{summary}', summary)
        )
        return self._cfg.no_llm_system_prompt, user

    def extract_citation_ids(self, answer: str) -> List[int]:
        """
        从 LLM 回答中提取引用 ID
        使用 dict.fromkeys 保序去重，避免 O(n²) 的 list + not in 模式。
        """
        raw = [int(m.group(1)) for m in re.finditer(r'\[(\d+)\]', answer)]
        return list(dict.fromkeys(raw))

    def build_stream_message(
        self,
        query: str,
        context_blocks: List[ContextBlock],
        context_truncated: bool = False,
    ) -> str:
        """
        构建用于流式生成的单条消息
        """
        context = self._format_context(context_blocks)
        warning = self._cfg.stream_truncation_warning if context_truncated else ''

        return (
            self._cfg.stream_message_template
            .replace('{context}', context)
            .replace('{truncation_warning}', warning)
            .replace('{query}', query)
        )

    # ── 私有辅助 ────────────────────────────────────────────

    def _format_context(self, blocks: List[ContextBlock]) -> str:
        """格式化上下文块"""
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
        """汇总检索结果（无 LLM 模式）"""
        lines = []
        for i, block in enumerate(blocks):
            snippet = block.content[:200]
            suffix = '...' if len(block.content) > 200 else ''
            lines.append(f"{i + 1}. {snippet}{suffix}")
        return '\n'.join(lines)


def create_prompt_builder(
    system_prompt: Optional[str] = None,
    prompts_file: Optional[str] = None,
) -> PromptBuilder:
    """创建提示词构建器"""
    return PromptBuilder(system_prompt, prompts_file)
