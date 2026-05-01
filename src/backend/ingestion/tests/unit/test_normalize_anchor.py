"""_normalize_anchor 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §3 metadata 字段规范

API 输出 markdown_anchor 必须是 '#section-id' 形式。
chunker 偶发遗漏 # 前缀（AsciiDoc parser 已知 bug），由 _normalize_anchor 兜底。
"""
import pytest
from backend.ingestion.api.routes_search import _normalize_anchor


# 测什么行为：None 输入归一化为 #top
# 输入：None
# 期望："#top"
# 为什么必须测：DB 列允许 NULL，旧数据可能是 None
def test_none_to_top():
    assert _normalize_anchor(None) == "#top"


# 测什么行为：空字符串归一化为 #top
def test_empty_string_to_top():
    assert _normalize_anchor("") == "#top"


# 测什么行为：缺 # 前缀的 anchor（Spring AsciiDoc bug 场景）自动补 #
# 输入："databufferfactory"
# 期望："#databufferfactory"
# 为什么必须测：核心兜底场景，spec 契约要求
def test_missing_hash_added():
    assert _normalize_anchor("databufferfactory") == "#databufferfactory"


# 测什么行为：已带 # 前缀的 anchor 保持不变（idempotent）
# 输入："#data-fetching"
# 期望："#data-fetching"
# 为什么必须测：chunker 修复后此函数仍工作（不重复加 #）
def test_with_hash_unchanged():
    assert _normalize_anchor("#data-fetching") == "#data-fetching"


# 测什么行为：连续两次调用结果一致（idempotent）
# 输入：normalize 后再 normalize
# 期望：两次结果相同
# 为什么必须测：保证函数可在 pipeline 任意环节调用都安全
def test_idempotent():
    once = _normalize_anchor("foo")
    twice = _normalize_anchor(once)
    assert once == twice == "#foo"


# 测什么行为：复杂 anchor 名（含 dash / 中文）也正确处理
def test_complex_anchor_name():
    assert _normalize_anchor("api-发起驱逐") == "#api-发起驱逐"
    assert _normalize_anchor("#api-发起驱逐") == "#api-发起驱逐"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
