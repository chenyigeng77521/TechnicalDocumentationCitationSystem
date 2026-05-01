"""测试 document 三级 fallback 切分。"""
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.document_splitter import (
    split_document,
    MAX_CHARS,
)
from backend.ingestion.chunker.quality_filter import MIN_CHARS_QUALITY
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
    para1 = "First paragraph with enough characters to keep over the limit."  # 62 chars
    para2 = "Second paragraph also with enough length here over the limit."   # 61 chars
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


def test_quality_filter_drops_short():
    """split_document 调 quality_filter 后短 chunk 被丢"""
    pr = ParseResult(raw_text="x", title_tree=[])  # 1 char < MIN_CHARS_QUALITY
    chunks = split_document(pr, **_meta())
    assert chunks == [] or all(
        len(c.content) >= MIN_CHARS_QUALITY or c.is_truncated for c in chunks
    )


def test_chunker_uses_quality_filter():
    """split_document 末尾真调了 filter_quality（mock 验证）"""
    from unittest.mock import patch
    pr = ParseResult(
        raw_text="this is a paragraph with enough length to pass min_chars threshold easily.",
        title_tree=[],
    )
    with patch(
        "backend.ingestion.chunker.document_splitter.filter_quality",
        wraps=lambda x: x,
    ) as mock_fq:
        split_document(pr, **_meta())
        mock_fq.assert_called_once()


def test_chunker_drops_low_quality_chunks():
    """端到端：纯标点段落 + 正常段落 → output 不含纯标点 chunk（行为验证）"""
    junk = "." * 60
    normal = "This is a normal paragraph with enough alphanumeric content here."
    pr = ParseResult(raw_text=f"{junk}\n\n{normal}", title_tree=[])
    chunks = split_document(pr, **_meta())

    contents = [c.content for c in chunks]
    assert junk not in contents, f"纯点 chunk 没被过滤: {contents}"
    assert any(normal in c for c in contents), f"正常段落丢了: {contents}"


def test_chunker_keeps_hard_split_pieces_with_different_offsets():
    """端到端 regression：硬切产物 content 相同 offset 不同应全部保留

    spec §4.3 规范要求：identity 是 (file_path, content, char_offset_start)，
    硬切产生的 N 块 byte-identical chunks 在不同 offset 必须全留。
    """
    # 3000 字符单字符串 → 硬切 3 块 1000 字符（如果是同字符则 content 全相同）
    # 用 codex 推荐的 a/b/c 验证基本切分；我们这里更严验证 offset 保护
    giant = "x" * (MAX_CHARS * 3)  # 3000 'x' → 硬切应得 3 块全 'x' * 1000
    pr = ParseResult(raw_text=giant, title_tree=[])
    chunks = split_document(pr, **_meta())

    assert len(chunks) == 3, f"期望 3 块硬切产物，实际 {len(chunks)}"
    assert all(c.is_truncated for c in chunks), "全部应标 is_truncated"
    # 关键 regression：content 全一样但 offset 递增 → 全被保留（codex 修复前会被去重成 1 个）
    assert [c.char_offset_start for c in chunks] == [0, MAX_CHARS, MAX_CHARS * 2]
    assert all(c.content == "x" * MAX_CHARS for c in chunks)
