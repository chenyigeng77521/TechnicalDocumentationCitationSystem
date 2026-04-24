from pathlib import Path

import pytest

from app.converter.parser import parse

FIX = Path(__file__).parent / "fixtures"


def test_parse_md_returns_raw_content():
    md, line_map = parse(FIX / "sample.md")
    assert "标题一" in md
    assert "段落一内容" in md
    assert isinstance(line_map, dict)


def test_parse_docx_converts_headings_to_markdown():
    md, _ = parse(FIX / "sample.docx")
    assert "# 标题一" in md or "## 标题一" in md
    assert "段落一内容" in md


def test_parse_pdf_extracts_text():
    md, _ = parse(FIX / "sample.pdf")
    # PDF 用 Latin 文本（PyMuPDF 默认 Helvetica 字体不支持中文字形）
    assert "Hello PDF" in md


def test_parse_pptx_extracts_slide_title_and_body():
    md, _ = parse(FIX / "sample.pptx")
    assert "标题一" in md
    assert "段落一内容" in md


def test_parse_xlsx_produces_markdown_table():
    md, _ = parse(FIX / "sample.xlsx")
    assert "| A | B |" in md or "A | B" in md
    assert "中文" in md


def test_parse_unknown_ext_raises(tmp_path):
    (tmp_path / "x.xyz").write_text("data")
    with pytest.raises(ValueError, match="unsupported"):
        parse(tmp_path / "x.xyz")
