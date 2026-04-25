"""测试 document 三级 fallback 切分。"""
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.document_splitter import (
    split_document,
    MAX_CHARS,
    MIN_CHARS,
)
from backend.ingestion.parser.types import ParseResult, TitleNode


def _meta():
    return {"file_path": "a.md", "file_hash": "h1", "index_version": "v1"}


def test_short_text_is_one_chunk():
    text = "hello world this is some sample content for testing chunker"  # 60 chars
    pr = ParseResult(raw_text=text, title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_offset_start == 0
    assert chunks[0].char_offset_end == len(text)
    assert chunks[0].is_truncated is False


def test_long_text_splits_by_paragraph():
    para1 = "p1 " * 50  # 150 chars
    para2 = "p2 " * 50
    pr = ParseResult(raw_text=f"{para1}\n\n{para2}", title_tree=[])
    chunks = split_document(pr, **_meta())
    # 两段都短于 MAX_CHARS，应该切成 2 个 chunk
    assert len(chunks) == 2


def test_very_long_paragraph_splits_by_sentence():
    sent = "这是一句话。" * 200  # ~1200 字
    pr = ParseResult(raw_text=sent, title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) > 1
    # 没有 chunk 超过 MAX_CHARS（除非 is_truncated）
    for c in chunks:
        assert c.char_count <= MAX_CHARS or c.is_truncated


def test_single_giant_sentence_triggers_hard_truncate():
    giant = "x" * (MAX_CHARS * 3)  # 单句无标点 3 倍 MAX_CHARS
    pr = ParseResult(raw_text=giant, title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) >= 3
    assert any(c.is_truncated for c in chunks)


def test_chunk_id_is_deterministic():
    text = "hello world some longer content to pass the MIN_CHARS filter"
    pr = ParseResult(raw_text=text, title_tree=[])
    c1 = split_document(pr, **_meta())[0]
    c2 = split_document(pr, **_meta())[0]
    assert c1.chunk_id == c2.chunk_id
    assert len(c1.chunk_id) == 64  # sha256 hex


def test_anchor_id_format():
    text = "hello world this is a paragraph long enough to pass MIN_CHARS"
    pr = ParseResult(raw_text=text, title_tree=[])
    c = split_document(pr, **_meta())[0]
    assert c.anchor_id == "a.md#0"


def test_heading_only_paragraph_is_skipped():
    """## Installation 这种纯标题段不应作为 chunk（信息已在 title_path）。"""
    raw = "## Installation\n\nactual content paragraph that is long enough to keep it"
    tree = [TitleNode(level=2, text="Installation", char_offset=0)]
    pr = ParseResult(raw_text=raw, title_tree=tree)
    chunks = split_document(pr, **_meta())
    # 只剩 1 个 chunk（实际内容那段），标题段被跳过
    assert len(chunks) == 1
    assert "Installation" not in chunks[0].content   # 标题不混进 content
    assert "actual content" in chunks[0].content


def test_no_overlap_means_offsets_match_content():
    """关掉 overlap 后 char_offset_end - char_offset_start == len(content)。"""
    para1 = "First paragraph with enough characters to keep."  # 47 chars
    para2 = "Second paragraph also with enough length here."   # 46 chars
    pr = ParseResult(raw_text=f"{para1}\n\n{para2}", title_tree=[])
    chunks = split_document(pr, **_meta())
    for c in chunks:
        assert c.char_offset_end - c.char_offset_start == len(c.content), \
            f"offset 跟 content 长度不匹配: {c.char_offset_start}-{c.char_offset_end} vs {len(c.content)}"
        assert c.char_count == len(c.content)


def test_title_path_from_tree():
    intro = "Top section intro paragraph long enough to keep around."  # 56 chars
    sub = "Sub section content here also long enough to be kept."        # 53 chars
    tree = [TitleNode(level=1, text="Top", char_offset=0, children=[
        TitleNode(level=2, text="Sub", char_offset=len(intro) + 2, children=[]),
    ])]
    pr = ParseResult(raw_text=f"{intro}\n\n{sub}", title_tree=tree)
    chunks = split_document(pr, **_meta())
    paths = [c.title_path for c in chunks if c.title_path]
    assert any("Top" in p for p in paths)


def test_min_chars_filter():
    pr = ParseResult(raw_text="x", title_tree=[])  # 1 char < MIN_CHARS
    chunks = split_document(pr, **_meta())
    # 过短 chunk 被过滤
    assert chunks == [] or all(c.char_count >= MIN_CHARS or c.is_truncated for c in chunks)
