"""测试 markdown_parser 提取标题 trailing anchor（K8s {#xxx} / React {/*xxx*/}）。

Spec: docs/superpowers/specs/2026-04-29-group-a-anchor-html-strip-design.md
"""
import asyncio
import tempfile
from pathlib import Path

from backend.ingestion.parser.markdown_parser import parse


def _parse(md: str):
    """辅助：把字符串写入临时 .md 文件，跑 parser，返回 ParseResult。"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as f:
        f.write(md)
        p = Path(f.name)
    try:
        return asyncio.run(parse(p))
    finally:
        p.unlink()


def test_extract_kubernetes_anchor():
    """K8s 风格 {#slug}：从 api-eviction.md:109 真实写法（多空格分隔）"""
    result = _parse("## API 发起驱逐的工作原理   {#how-api-initiated-eviction-works}\n")
    assert len(result.title_tree) == 1
    h = result.title_tree[0]
    assert h.text == "API 发起驱逐的工作原理"
    assert h.anchor == "#how-api-initiated-eviction-works"


def test_extract_react_anchor():
    """React 风格 {/*slug*/}：从 incremental-adoption.md:20 真实写法"""
    result = _parse("## Why Incremental Adoption? {/*why-incremental-adoption*/}\n")
    assert len(result.title_tree) == 1
    h = result.title_tree[0]
    assert h.text == "Why Incremental Adoption?"
    assert h.anchor == "#why-incremental-adoption"


def test_no_anchor_returns_none():
    """没显式锚点 → anchor=None（不强求 GFM auto-slug）"""
    result = _parse("## A simple heading without anchor\n")
    assert len(result.title_tree) == 1
    h = result.title_tree[0]
    assert h.text == "A simple heading without anchor"
    assert h.anchor is None


def test_kubernetes_anchor_with_extra_whitespace():
    """多空格分隔 / slug 含中文 / 多余尾空白 都不影响"""
    result = _parse("###    SSH 身份认证 Secret    {#ssh-身份认证-secret-ssh-authentication-secrets}   \n")
    h = result.title_tree[0]
    assert h.text == "SSH 身份认证 Secret"
    assert h.anchor == "#ssh-身份认证-secret-ssh-authentication-secrets"


def test_malformed_anchor_treats_as_text():
    """malformed 锚点（空 slug）→ 视为标题文本一部分，anchor=None"""
    result = _parse("## Title with {#} empty slug\n")
    h = result.title_tree[0]
    assert h.anchor is None
    assert "{#}" in h.text


def test_mixed_anchor_styles_in_one_doc():
    """同一文档里 K8s + React + 无锚 共存"""
    md = (
        "# Top\n\n"
        "## K8s style {#k8s-style}\n\n"
        "## React style {/*react-style*/}\n\n"
        "## No anchor\n"
    )
    result = _parse(md)
    titles = result.title_tree
    assert titles[0].anchor is None  # 顶层 # Top 没带锚
    assert titles[0].children[0].anchor == "#k8s-style"
    assert titles[0].children[1].anchor == "#react-style"
    assert titles[0].children[2].anchor is None
