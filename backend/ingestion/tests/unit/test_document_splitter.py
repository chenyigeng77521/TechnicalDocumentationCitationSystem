"""测试 document_splitter 的 markdown_anchor 绑定 + #top 兜底 + HTML 注释剥离。

Spec: docs/superpowers/specs/2026-04-29-group-a-anchor-html-strip-design.md
"""
import asyncio
import tempfile
from pathlib import Path

from backend.ingestion.parser.types import ParseResult, TitleNode
from backend.ingestion.parser.markdown_parser import parse as parse_md
from backend.ingestion.chunker.document_splitter import split_document


def _make_parse_result(
    raw_text: str,
    titles: list[TitleNode],
    comment_ranges: list[tuple[int, int]] | None = None,
) -> ParseResult:
    """辅助：构造 ParseResult。raw_text 跟 titles 的 char_offset 必须一致。"""
    return ParseResult(
        raw_text=raw_text,
        title_tree=titles,
        comment_ranges=comment_ranges or [],
    )


def _parse_md_str(md: str) -> ParseResult:
    """辅助：把字符串当 markdown 文件，跑真实 markdown_parser，返回带 comment_ranges 的 ParseResult。"""
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as f:
        f.write(md)
        p = Path(f.name)
    try:
        return asyncio.run(parse_md(p))
    finally:
        p.unlink()


# ============================================================
# Task 3: markdown_anchor 绑定 + #top 兜底
# ============================================================

def test_chunk_under_h2_inherits_anchor():
    """chunk 在 H2 下，markdown_anchor 应为该 H2 的 anchor"""
    raw = (
        "## Try React {/*try-react*/}\n\n"
        "First paragraph with enough words to pass quality_filter min length threshold here.\n\n"
        "Second paragraph also long enough to be kept by quality filter rules and so on.\n"
    )
    titles = [TitleNode(level=2, text="Try React", char_offset=0, anchor="#try-react")]
    result = _make_parse_result(raw, titles)

    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")
    assert len(chunks) >= 1
    for c in chunks:
        assert c.markdown_anchor == "#try-react", f"chunk {c.chunk_index} got {c.markdown_anchor}"


def test_chunk_at_section_boundary_uses_preceding_title():
    """chunk 起始 offset 在前一个 H2 之后、下一个 H2 之前 → 用前一个 H2 的 anchor"""
    raw = (
        "## First Section {#first}\n\n"
        "First section content long enough for quality filter to keep it well sure.\n\n"
        "## Second Section {#second}\n\n"
        "Second section content also long enough for quality filter retain mostly.\n"
    )
    second_offset = raw.index("## Second")
    titles = [
        TitleNode(level=2, text="First Section", char_offset=0, anchor="#first"),
        TitleNode(level=2, text="Second Section", char_offset=second_offset, anchor="#second"),
    ]
    result = _make_parse_result(raw, titles)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")

    first_section_chunks = [c for c in chunks if c.char_offset_start < second_offset]
    second_section_chunks = [c for c in chunks if c.char_offset_start >= second_offset]
    assert all(c.markdown_anchor == "#first" for c in first_section_chunks), \
        f"first section: {[c.markdown_anchor for c in first_section_chunks]}"
    assert all(c.markdown_anchor == "#second" for c in second_section_chunks), \
        f"second section: {[c.markdown_anchor for c in second_section_chunks]}"


def test_section_without_anchor_falls_back_to_top():
    """leaf section 标题 anchor=None → chunk 走 #top fallback"""
    raw = (
        "## A heading without anchor\n\n"
        "Some content paragraph long enough for quality filter to retain this chunk.\n"
    )
    titles = [TitleNode(level=2, text="A heading without anchor", char_offset=0, anchor=None)]
    result = _make_parse_result(raw, titles)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")

    assert len(chunks) >= 1
    for c in chunks:
        assert c.markdown_anchor == "#top"


def test_no_titles_at_all_uses_top():
    """没任何 title（空 title_tree）→ #top"""
    raw = "Just one big paragraph without any heading, long enough to be retained by quality filter rules.\n"
    result = _make_parse_result(raw, titles=[])
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")

    assert len(chunks) >= 1
    for c in chunks:
        assert c.markdown_anchor == "#top"


def test_chunk_before_first_title_uses_top():
    """文档开头有正文段，再出现第一个 title——前面段应该是 #top"""
    intro = "Intro paragraph at top of document, must be retained by quality filter rules well.\n\n"
    title_pos = len(intro)
    raw = intro + "## First Heading {#first}\n\nContent under heading also retained well enough.\n"
    titles = [TitleNode(level=2, text="First Heading", char_offset=title_pos, anchor="#first")]
    result = _make_parse_result(raw, titles)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")

    intro_chunks = [c for c in chunks if c.char_offset_start < title_pos]
    body_chunks = [c for c in chunks if c.char_offset_start >= title_pos]
    assert all(c.markdown_anchor == "#top" for c in intro_chunks), \
        f"intro: {[c.markdown_anchor for c in intro_chunks]}"
    assert all(c.markdown_anchor == "#first" for c in body_chunks), \
        f"body: {[c.markdown_anchor for c in body_chunks]}"


# ============================================================
# Task 4: HTML 注释剥离（基于 raw_text 范围）
# ============================================================

def test_html_comment_block_is_skipped():
    """整段 <!-- ... --> 应被跳过，不入 chunks。"""
    md = (
        "First Chinese paragraph long enough for quality filter retain content here.\n\n"
        "<!-- This is the English source line, must be skipped because of bilingual rule -->\n\n"
        "Second Chinese paragraph long enough for quality filter retain content here.\n"
    )
    result = _parse_md_str(md)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")
    contents = [c.content for c in chunks]
    assert any("First Chinese" in c for c in contents)
    assert any("Second Chinese" in c for c in contents)
    assert not any("English source" in c for c in contents), \
        f"chunks contained the comment: {contents}"


def test_multiline_html_comment_is_skipped():
    """多行 <!-- ... --> 也应跳过（跨段也算，因为 comment_ranges 是 raw_text 范围）。"""
    md = (
        "Para before comment, long enough for quality filter retain something here.\n\n"
        "<!--\nMultiple lines\nof English\ntranslation source\n-->\n\n"
        "Para after comment, long enough for quality filter retain something here.\n"
    )
    result = _parse_md_str(md)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")
    contents = [c.content for c in chunks]
    assert not any("Multiple lines" in c for c in contents)
    assert any("Para before" in c for c in contents)
    assert any("Para after" in c for c in contents)


def test_multi_paragraph_comment_is_fully_skipped():
    """注释跨多个 \\n\\n 段（被 \\n\\n 切散）也要全部跳过。
    回归 api-eviction.md 的 chunk #14 错误归到 #top 的 case：
        <!--\\n## English H2\\n\\nWhen you request...\\n--> ## 中文 H2 {#real-anchor}
    切散后中间段 'When you request...' 仍在注释范围内，必须跳过。
    """
    md = (
        "Body text before comment, long enough for quality filter retain something.\n\n"
        "<!--\n"
        "## English H2 inside comment\n"
        "\n"
        "Multi-paragraph English text that should be entirely skipped here.\n"
        "-->\n\n"
        "## 中文 H2 {#real-anchor}\n\n"
        "Body text after Chinese H2, long enough for quality filter retain content.\n"
    )
    result = _parse_md_str(md)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")
    contents = [c.content for c in chunks]
    # 跨段注释里所有内容都不应进 chunks
    assert not any("English H2 inside" in c for c in contents)
    assert not any("Multi-paragraph English" in c for c in contents)
    # 中文段保留 + 绑到正确 anchor
    chinese_chunks = [c for c in chunks if "Body text after" in c.content]
    assert len(chinese_chunks) >= 1
    assert all(c.markdown_anchor == "#real-anchor" for c in chinese_chunks)


def test_normal_paragraphs_not_affected():
    """没注释的普通段落，行为跟原来一致。"""
    md = "A single normal paragraph long enough for quality filter to retain it well.\n"
    result = _parse_md_str(md)
    chunks = split_document(result, file_path="test.md", file_hash="h", index_version="v1")
    assert len(chunks) == 1
    assert "single normal paragraph" in chunks[0].content
