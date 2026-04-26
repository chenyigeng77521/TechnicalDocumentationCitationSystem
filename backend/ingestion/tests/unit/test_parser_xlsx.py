import pytest
from backend.ingestion.parser.xlsx_parser import parse


@pytest.mark.asyncio
async def test_parse_xlsx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.xlsx")
    assert "Header" in result.raw_text
    assert "Value" in result.raw_text
    assert "Sheet1" in result.metadata.get("sheet_names", [])


@pytest.mark.asyncio
async def test_parse_xlsx_builds_title_tree(fixtures_dir):
    """sheet 名进 title_tree，让 chunker 能给数据 chunk 填 title_path。"""
    result = await parse(fixtures_dir / "sample.xlsx")
    assert len(result.title_tree) >= 1
    assert any(node.text == "Sheet1" for node in result.title_tree)
    # title_tree 每个节点 char_offset 应该指向 raw_text 里实际的位置
    for node in result.title_tree:
        header = f"## Sheet: {node.text}"
        assert result.raw_text[node.char_offset:node.char_offset + len(header)] == header
