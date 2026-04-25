"""HTML 解析器。先转 markdown，再走 markdown 解析。"""
from pathlib import Path
from bs4 import BeautifulSoup
from markdownify import markdownify
from backend.ingestion.parser.types import ParseResult, TitleNode


async def parse(path: Path) -> ParseResult:
    html = path.read_text(encoding="utf-8")
    md = markdownify(html, heading_style="ATX")
    soup = BeautifulSoup(html, "html.parser")
    headings = []
    cursor = 0
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = tag.get_text(strip=True)
        level = int(tag.name[1])
        offset = md.find(text, cursor)
        if offset == -1:
            offset = cursor
        headings.append(TitleNode(level=level, text=text, char_offset=offset))
        cursor = offset + len(text)
    # build tree
    from backend.ingestion.parser.markdown_parser import _build_tree
    return ParseResult(
        raw_text=md,
        title_tree=_build_tree(headings),
        content_type="document",
    )
