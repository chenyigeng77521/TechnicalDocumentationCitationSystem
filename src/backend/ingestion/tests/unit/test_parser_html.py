import pytest
from backend.ingestion.parser.html_parser import parse


@pytest.mark.asyncio
async def test_parse_html_to_md(tmp_path):
    f = tmp_path / "a.html"
    f.write_text("<h1>Title</h1><p>body</p>", encoding="utf-8")
    result = await parse(f)
    assert "Title" in result.raw_text
    assert "body" in result.raw_text
    assert result.title_tree[0].text == "Title"
