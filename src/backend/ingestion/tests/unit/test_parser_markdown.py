import pytest
from backend.ingestion.parser.markdown_parser import parse


@pytest.mark.asyncio
async def test_parse_md_extracts_title_tree(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Top\n\ncontent\n\n## Sub\n\nsub content", encoding="utf-8")
    result = await parse(f)
    assert "content" in result.raw_text
    assert len(result.title_tree) >= 1
    assert result.title_tree[0].text == "Top"
    assert result.title_tree[0].level == 1


@pytest.mark.asyncio
async def test_parse_md_no_titles(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("just plain text", encoding="utf-8")
    result = await parse(f)
    assert result.raw_text == "just plain text"
    assert result.title_tree == []
