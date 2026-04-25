import pytest
from backend.ingestion.parser.xlsx_parser import parse


@pytest.mark.asyncio
async def test_parse_xlsx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.xlsx")
    assert "Header" in result.raw_text
    assert "Value" in result.raw_text
    assert "Sheet1" in result.metadata.get("sheet_names", [])
