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
    pr = ParseResult(raw_text="hello world", title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) == 1
    assert chunks[0].content == "hello world"
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_offset_start == 0
    assert chunks[0].char_offset_end == 11
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
    pr = ParseResult(raw_text="hello world", title_tree=[])
    c1 = split_document(pr, **_meta())[0]
    c2 = split_document(pr, **_meta())[0]
    assert c1.chunk_id == c2.chunk_id
    assert len(c1.chunk_id) == 64  # sha256 hex


def test_anchor_id_format():
    pr = ParseResult(raw_text="hello", title_tree=[])
    c = split_document(pr, **_meta())[0]
    assert c.anchor_id == "a.md#0"


def test_title_path_from_tree():
    tree = [TitleNode(level=1, text="Top", char_offset=0, children=[
        TitleNode(level=2, text="Sub", char_offset=20, children=[]),
    ])]
    pr = ParseResult(raw_text="Top intro\n\nSub content here", title_tree=tree)
    chunks = split_document(pr, **_meta())
    # 至少一个 chunk 有 title_path
    paths = [c.title_path for c in chunks if c.title_path]
    assert any("Top" in p for p in paths)


def test_min_chars_filter():
    pr = ParseResult(raw_text="x", title_tree=[])  # 1 char < MIN_CHARS
    chunks = split_document(pr, **_meta())
    # 过短 chunk 被过滤
    assert chunks == [] or all(c.char_count >= MIN_CHARS or c.is_truncated for c in chunks)
