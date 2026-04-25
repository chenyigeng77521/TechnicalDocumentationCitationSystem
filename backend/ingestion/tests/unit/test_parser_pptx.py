import pytest
from backend.ingestion.parser.pptx_parser import parse


@pytest.mark.asyncio
async def test_parse_pptx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.pptx")
    assert "Slide One" in result.raw_text
