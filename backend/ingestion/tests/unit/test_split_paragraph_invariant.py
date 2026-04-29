"""chunker 不变量 + 列表保护 + CRLF 鲁棒性测试。

覆盖 Task 1 (重写 _split_paragraph) + Task 2 (split_document CRLF/多空行)。
"""
from backend.ingestion.chunker.document_splitter import _split_paragraph, split_document, MAX_CHARS
from backend.ingestion.parser.types import ParseResult


def test_join_equals_original():
    """不变量：所有产出片段拼接 == 原文（一字不差）。"""
    text = (
        "这是第一句。这是第二句。\n"
        "1. The Pod resource is updated.\n"
        "2. The kubelet notices.\n"
        "Python 3.12. 是新版本。结束。"
    ) * 50  # 重复让总长 > MAX_CHARS
    pieces = _split_paragraph(text)
    rebuilt = "".join(p for p, _ in pieces)
    assert rebuilt == text, f"不变量违反: 长度差 {len(text) - len(rebuilt)}"


def test_short_passthrough():
    """段落 <= MAX_CHARS 直接原样返回。"""
    text = "短段落。就这么短。"
    result = _split_paragraph(text)
    assert result == [(text, False)]


def test_long_split_by_sentence():
    """段落 > MAX_CHARS，按句号切；切片不丢字符且都 <= MAX_CHARS。"""
    sentence = "这是一个测试句。"
    text = sentence * 200  # 远超 MAX_CHARS
    pieces = _split_paragraph(text)
    assert all(len(p) <= MAX_CHARS for p, _ in pieces)
    assert "".join(p for p, _ in pieces) == text


def test_list_marker_protection():
    """列表项 '1. xxx' 不被错切；'Python 3.12.' 仍按句号切。"""
    text = "前言。" + ("一二三四五六七八九十" * 100) + "\n1. The Pod resource\n2. The kubelet\nPython 3.12. 发布于 2024 年。结束。"
    pieces = _split_paragraph(text)
    rebuilt = "".join(p for p, _ in pieces)
    # 列表标记后的空格保留
    assert "1. The Pod" in rebuilt, "列表 '1. The Pod' 中的空格被吞了"
    assert "2. The kubelet" in rebuilt, "列表 '2. The kubelet' 中的空格被吞了"
    # 'Python 3.12.' 这个伪列表不应被保护——仍按句号切，但拼回去仍完整
    assert "Python 3.12. 发布于" in rebuilt, "伪列表 'Python 3.12.' 后的空格被吞了"


def test_no_boundary_hard_split():
    """单句无内部边界 + 长度 > MAX_CHARS → 硬切，is_truncated=True。"""
    text = "啊" * (MAX_CHARS + 100)  # 没有任何句末标点
    pieces = _split_paragraph(text)
    assert any(trunc for _, trunc in pieces), "应至少有一片硬切"
    assert "".join(p for p, _ in pieces) == text


def test_edge_inputs():
    """空字符串、纯空白、纯标点的健壮性。"""
    # 空串
    assert _split_paragraph("") == [("", False)]
    # 纯空白
    s = "   \n\n   "
    assert _split_paragraph(s) == [(s, False)]
    # 纯标点
    s = "。！？"
    assert _split_paragraph(s) == [(s, False)]


# ---------- Task 2: split_document CRLF + 多空行 ----------


def _make_parse_result(text: str) -> ParseResult:
    """构造一个最简 ParseResult：无 title_tree、无 comment_ranges、无 language。"""
    return ParseResult(raw_text=text, title_tree=[], comment_ranges=[], language=None)


def test_crlf_normalized():
    """CRLF 输入正确切分，offset 字段对应归一化（LF）后文本。"""
    raw = "段落一第一句。段落一第二句。\r\n\r\n段落二第一句。\r\n\r\n段落三。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 3, f"期望 3 段，实得 {len(chunks)}: {[c.content for c in chunks]}"
    # offset 应在归一化文本中精确（归一化把 \r\n → \n，长度变短）
    normalized = raw.replace("\r\n", "\n")
    for c in chunks:
        assert c.content == normalized[c.char_offset_start:c.char_offset_end], \
            f"chunk content 与 offset 不一致: content={c.content!r} offsets=({c.char_offset_start},{c.char_offset_end}) normalized_slice={normalized[c.char_offset_start:c.char_offset_end]!r}"


def test_triple_newline():
    """三个连续换行（\\n\\n\\n）只产生一次段落边界，不让后续 offset 偏移。"""
    raw = "段落一。\n\n\n段落二。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 2
    # 第二段 offset 应指向 '段落二' 的 '段'
    assert chunks[1].content.startswith("段落二"), f"chunks[1].content={chunks[1].content!r}"


def test_mixed_line_endings():
    """raw 中 \\r\\n 和 \\n 混用，归一化后边界仍正确。"""
    raw = "段落一。\r\n\r\n段落二。\n\n段落三。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 3
    normalized = raw.replace("\r\n", "\n")
    for c in chunks:
        assert c.content == normalized[c.char_offset_start:c.char_offset_end]


def test_no_trailing_newline():
    """文档末尾无换行，最后一段仍被切出。"""
    raw = "段落一。\n\n段落二（无尾换行）。"
    chunks = split_document(_make_parse_result(raw), file_path="t.md", file_hash="h", index_version="v1")
    assert len(chunks) == 2
    assert chunks[1].content == "段落二（无尾换行）。"
