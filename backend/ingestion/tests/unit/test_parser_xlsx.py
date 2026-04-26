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


@pytest.mark.asyncio
async def test_parse_xlsx_large_sheet_paginated(tmp_path):
    """大 Sheet 主动按行分段：每段 < 800 字 + 重复表头，避免 chunker 硬切。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "BigSheet"
    ws.append(["ID", "Name", "Description"])
    # 100 行数据，每行 ~50 字 → 总共 ~5000 字（远超单段 800 字限制）
    for i in range(100):
        ws.append([str(i), f"Item{i:03d}", "abcdefghij" * 5])

    xlsx_path = tmp_path / "big.xlsx"
    wb.save(xlsx_path)

    result = await parse(xlsx_path)

    # 应该被分成多段（按 \n\n 切）
    paragraphs = result.raw_text.split("\n\n")
    data_paragraphs = [p for p in paragraphs if "Item" in p]
    assert len(data_paragraphs) > 1, (
        f"大 sheet 应分多段避免硬切，实际 {len(data_paragraphs)} 段"
    )

    # 每段都应自带表头（"ID | Name | Description"）
    for p in data_paragraphs:
        assert "ID | Name | Description" in p, (
            f"每段应自带表头，缺失:\n{p[:200]}"
        )

    # 每段长度 ≤ 1000（chunker MAX_CHARS）→ 不会触发硬切
    for p in data_paragraphs:
        assert len(p) <= 1000, f"段长 {len(p)} > 1000，仍可能被硬切"
