"""按扩展名分派到对应 parser。"""
from pathlib import Path
from backend.ingestion.common.errors import UnsupportedFormatError
from backend.ingestion.parser.types import ParseResult


_EXT_TO_PARSER: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
}


def get_parser_name(path: Path) -> str:
    ext = path.suffix.lower()
    name = _EXT_TO_PARSER.get(ext)
    if name is None:
        raise UnsupportedFormatError(ext)
    return name


async def parse_document(path: Path) -> ParseResult:
    """根据扩展名调用对应 parser。"""
    name = get_parser_name(path)
    if name == "markdown":
        from backend.ingestion.parser.markdown_parser import parse as p
    elif name == "txt":
        from backend.ingestion.parser.txt_parser import parse as p
    elif name == "html":
        from backend.ingestion.parser.html_parser import parse as p
    elif name == "pdf":
        from backend.ingestion.parser.pdf_parser import parse as p
    elif name == "docx":
        from backend.ingestion.parser.docx_parser import parse as p
    elif name == "xlsx":
        from backend.ingestion.parser.xlsx_parser import parse as p
    elif name == "pptx":
        from backend.ingestion.parser.pptx_parser import parse as p
    else:
        raise UnsupportedFormatError(name)
    return await p(path)
