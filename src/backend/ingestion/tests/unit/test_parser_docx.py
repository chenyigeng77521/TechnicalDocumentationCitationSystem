import pytest
from backend.ingestion.parser.docx_parser import parse


@pytest.mark.asyncio
async def test_parse_docx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.docx")
    assert "DocX Title" in result.raw_text
    assert "First paragraph" in result.raw_text
    assert any(t.text == "DocX Title" for t in result.title_tree)
