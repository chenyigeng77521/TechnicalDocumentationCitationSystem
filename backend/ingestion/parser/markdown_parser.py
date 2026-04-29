"""Markdown 解析器。提取 raw_text + heading 层级树（含 trailing anchor）。"""
import re
from pathlib import Path
from backend.ingestion.parser.types import ParseResult, TitleNode

# 标题行：捕获级别 + text(含 trailing 部分)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# trailing anchor: K8s {#slug} 或 React {/*slug*/}，紧贴 text 末尾（前面允许 \s+ 分隔）
# group(1) = 标题文字（去掉 trailing 锚点后的部分）
# group(2) = K8s 风格 slug（{#xxx} 里的 xxx）
# group(3) = React 风格 slug（{/*xxx*/} 里的 xxx）
_ANCHOR_RE = re.compile(
    r"^(.+?)\s+\{(?:#([^\s{}]+)|/\*([^*]+)\*/)\}\s*$"
)


def _split_text_and_anchor(raw_text: str) -> tuple[str, str | None]:
    """从标题文字里抽出 trailing {#xxx} / {/*xxx*/}，返回 (text, anchor or None)。

    anchor 始终带 `#` 前缀；malformed（空 slug）或无锚点返回 (text_unchanged, None)。
    """
    m = _ANCHOR_RE.match(raw_text)
    if not m:
        return raw_text, None
    text = m.group(1).strip()
    slug = m.group(2) or m.group(3)
    if not slug:
        return raw_text, None
    return text, f"#{slug}"


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
        text_raw = m.group(2).strip()
        text, anchor = _split_text_and_anchor(text_raw)
        headings.append(TitleNode(
            level=len(m.group(1)),
            text=text,
            char_offset=m.start(),
            anchor=anchor,
        ))
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
