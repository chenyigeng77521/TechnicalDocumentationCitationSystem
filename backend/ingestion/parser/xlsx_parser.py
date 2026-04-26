"""XLSX 解析器。每 sheet → markdown 表格段，sheet 名进 title_tree。"""
from pathlib import Path
from openpyxl import load_workbook
from backend.ingestion.parser.types import ParseResult, TitleNode


async def parse(path: Path) -> ParseResult:
    wb = load_workbook(path, data_only=True, read_only=True)
    sheet_names: list[str] = []
    parts: list[str] = []

    for ws in wb.worksheets:
        sheet_names.append(ws.title)
        parts.append(f"## Sheet: {ws.title}")
        parts.append("")  # 空行：让 chunker 把标题段和数据段分开
        rows = list(ws.iter_rows(values_only=True))
        for row in rows:
            cells = [str(c) if c is not None else "" for c in row]
            parts.append(" | ".join(cells))
        parts.append("")  # sheet 之间空行

    raw_text = "\n".join(parts)

    # 给每个 sheet 标题加 TitleNode（level=2，对应 "## Sheet:"）
    # 用 raw_text.find 定位每个标题的实际 char_offset，避免手算偏差
    title_nodes: list[TitleNode] = []
    cursor = 0
    for sheet_name in sheet_names:
        header = f"## Sheet: {sheet_name}"
        offset = raw_text.find(header, cursor)
        if offset >= 0:
            title_nodes.append(TitleNode(level=2, text=sheet_name, char_offset=offset))
            cursor = offset + len(header)

    return ParseResult(
        raw_text=raw_text,
        title_tree=title_nodes,
        content_type="document",
        metadata={"sheet_names": sheet_names},
    )
