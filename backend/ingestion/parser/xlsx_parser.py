"""XLSX 解析器。每 sheet → markdown 表格段。"""
from pathlib import Path
from openpyxl import load_workbook
from backend.ingestion.parser.types import ParseResult


async def parse(path: Path) -> ParseResult:
    wb = load_workbook(path, data_only=True, read_only=True)
    sheet_names = []
    parts = []
    for ws in wb.worksheets:
        sheet_names.append(ws.title)
        parts.append(f"## Sheet: {ws.title}\n")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        for row in rows:
            cells = [str(c) if c is not None else "" for c in row]
            parts.append(" | ".join(cells))
        parts.append("")
    return ParseResult(
        raw_text="\n".join(parts),
        title_tree=[],
        content_type="document",
        metadata={"sheet_names": sheet_names},
    )
