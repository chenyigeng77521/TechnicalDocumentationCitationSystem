"""测试 document_splitter 的 markdown_anchor 绑定 + #top 兜底 + HTML 注释剥离。

Spec: docs/superpowers/specs/2026-04-29-group-a-anchor-html-strip-design.md
"""
from backend.ingestion.parser.types import ParseResult, TitleNode
from backend.ingestion.chunker.document_splitter import split_document


def _make_parse_result(raw_text: str, titles: list[TitleNode]) -> ParseResult:
    """辅助：构造 ParseResult。raw_text 跟 titles 的 char_offset 必须一致。"""
    return ParseResult(raw_text=raw_text, title_tree=titles)


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
