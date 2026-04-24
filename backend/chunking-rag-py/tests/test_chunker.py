from app.converter.chunker import Chunk, chunk_markdown


def test_empty_input_returns_empty():
    assert chunk_markdown("", {}) == []


def test_single_short_paragraph_one_chunk():
    chunks = chunk_markdown("Hello world.", {})
    assert len(chunks) == 1
    assert chunks[0].content == "Hello world."


def test_heading_split_creates_separate_chunks():
    md = "# H1\n\nAlpha.\n\n## H2\n\nBeta."
    chunks = chunk_markdown(md, {})
    assert len(chunks) >= 2
    joined = " ".join(c.content for c in chunks)
    assert "Alpha" in joined and "Beta" in joined


def test_blank_lines_split_paragraphs():
    md = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_markdown(md, {})
    joined = " ".join(c.content for c in chunks)
    assert "Para one" in joined and "Para three" in joined


def test_long_paragraph_split_at_target_size():
    long = "句。" * 501  # 1002 chars > HARD_MAX 1000
    chunks = chunk_markdown(long, {})
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.content) <= 1000


def test_short_fragments_merged_to_min_size():
    md = "\n\n".join(["短。"] * 20)
    chunks = chunk_markdown(md, {})
    for c in chunks[:-1]:
        assert len(c.content) >= 100


def test_code_block_not_split_internally():
    md = "前文。\n\n```python\ndef foo():\n    return 1\n    return 2\n```\n\n后文。"
    chunks = chunk_markdown(md, {})
    assert any("def foo" in c.content and "return 2" in c.content for c in chunks)


def test_chinese_text_chunking():
    md = "中文段落一。" * 100
    chunks = chunk_markdown(md, {})
    assert len(chunks) >= 1
    assert all("中文" in c.content for c in chunks)


def test_mixed_heading_and_paragraph():
    md = "# 标题\n\n段落一。\n\n段落二。\n\n## 二级\n\n段落三。"
    chunks = chunk_markdown(md, {})
    joined = " ".join(c.content for c in chunks)
    assert "段落一" in joined
    assert "段落三" in joined


def test_only_heading_no_content():
    chunks = chunk_markdown("# 只有标题", {})
    assert chunks == [] or (len(chunks) == 1 and "只有标题" in chunks[0].content)


def test_nested_headings_preserved():
    md = "# L1\n\n## L2\n\n### L3\n\n内容。"
    chunks = chunk_markdown(md, {})
    assert any("内容" in c.content for c in chunks)


def test_trailing_incomplete_paragraph():
    md = "# H\n\n段落。\n\n尾部未闭合"
    chunks = chunk_markdown(md, {})
    assert any("尾部未闭合" in c.content for c in chunks)


def test_consecutive_blank_lines_collapsed():
    md = "一段非常长的内容以满足最小长度要求" * 5 + "。\n\n\n\n\n" + "二段也非常长的内容以满足最小长度" * 5 + "。"
    chunks = chunk_markdown(md, {})
    joined = " ".join(c.content for c in chunks)
    assert "一段" in joined and "二段" in joined


def test_unicode_and_emoji():
    md = "Hello 世界 🌏。"
    chunks = chunk_markdown(md, {})
    assert len(chunks) >= 1
    assert "🌏" in chunks[0].content


def test_line_range_tracked():
    md = "line 1\n\nline 3\n\nline 5"
    chunks = chunk_markdown(md, {})
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line >= c.start_line
