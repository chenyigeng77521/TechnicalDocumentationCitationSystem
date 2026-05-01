import pytest
from backend.ingestion.parser.pptx_parser import parse


@pytest.mark.asyncio
async def test_parse_pptx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.pptx")
    assert "Slide One" in result.raw_text


@pytest.mark.asyncio
async def test_parse_pptx_builds_title_tree(fixtures_dir):
    """slide 名进 title_tree（用 slide 第一段文字作为标签）。"""
    result = await parse(fixtures_dir / "sample.pptx")
    assert len(result.title_tree) >= 1
    # 每个 TitleNode 的 char_offset 应指向 raw_text 中实际的 "### Slide N: ..." 位置
    for node in result.title_tree:
        header = f"### {node.text}"
        assert result.raw_text[node.char_offset:node.char_offset + len(header)] == header
