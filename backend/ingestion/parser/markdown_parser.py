"""Markdown 解析器。提取 raw_text + heading 层级树。"""
import re
from pathlib import Path
from backend.ingestion.parser.types import ParseResult, TitleNode

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _build_tree(headings: list[TitleNode]) -> list[TitleNode]:
    """把扁平 heading 列表按 level 嵌套成树。"""
    if not headings:
        return []
    root: list[TitleNode] = []
    stack: list[TitleNode] = []
    for h in headings:
        while stack and stack[-1].level >= h.level:
            stack.pop()
        if stack:
            stack[-1].children.append(h)
        else:
            root.append(h)
        stack.append(h)
    return root


async def parse(path: Path) -> ParseResult:
    raw = path.read_text(encoding="utf-8")
    headings = []
    for m in _HEADING_RE.finditer(raw):
        headings.append(TitleNode(
            level=len(m.group(1)),
            text=m.group(2).strip(),
            char_offset=m.start(),
        ))
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
