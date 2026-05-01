import pytest
from backend.ingestion.parser.pdf_parser import parse


@pytest.mark.asyncio
async def test_parse_pdf_text(fixtures_dir):
    pdf = fixtures_dir / "sample.pdf"
    result = await parse(pdf)
    assert "Hello PDF World" in result.raw_text
    assert result.content_type == "document"
    assert result.metadata.get("pdf_pages") == 1


@pytest.mark.asyncio
async def test_parse_pdf_chinese(fixtures_dir):
    pdf = fixtures_dir / "sample.pdf"
    result = await parse(pdf)
    assert "中文" in result.raw_text


@pytest.mark.asyncio
async def test_parse_pdf_scanned_falls_back_to_ocr(monkeypatch, fixtures_dir):
    """文字提取为空时降级 OCR（mock 掉真实 OCR 调用）。"""
    from backend.ingestion.parser import pdf_parser

    async def fake_ocr(path):
        return "OCR fallback text"

    monkeypatch.setattr(pdf_parser, "_ocr_pdf", fake_ocr)
    monkeypatch.setattr(pdf_parser, "_extract_text_pymupdf",
                        lambda p: ("", 1))  # 空文本模拟扫描版
    result = await parse(fixtures_dir / "sample.pdf")
    assert result.raw_text == "OCR fallback text"
    assert result.metadata.get("pdf_is_scanned") is True
