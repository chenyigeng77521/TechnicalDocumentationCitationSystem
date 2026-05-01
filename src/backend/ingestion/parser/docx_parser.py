"""DOCX 解析器。"""
from pathlib import Path
from docx import Document
from backend.ingestion.parser.types import ParseResult, TitleNode
from backend.ingestion.parser.markdown_parser import _build_tree


async def parse(path: Path) -> ParseResult:
    doc = Document(path)
    parts = []
    headings = []
    cursor = 0
    for para in doc.paragraphs:
        text = para.text
        if not text.strip():
            cursor += 1
            continue
        style = para.style.name if para.style else ""
        if style.startswith("Heading"):
            try:
                level = int(style.replace("Heading ", ""))
            except ValueError:
                level = 1
            headings.append(TitleNode(level=level, text=text, char_offset=cursor))
        parts.append(text)
        cursor += len(text) + 2
    raw = "\n\n".join(parts)
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
