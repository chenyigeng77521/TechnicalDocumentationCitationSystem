"""parser dataclass。"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TitleNode:
    level: int           # 1-6
    text: str
    char_offset: int
    children: list = field(default_factory=list)
    ancestors: list = field(default_factory=list)
    anchor: Optional[str] = None  # [[xxx]] 显式锚点 / 自动 slug。adoc parser 会填，markdown_parser 暂留 None（W2 改）


@dataclass
class ParseResult:
    raw_text: str
    title_tree: list[TitleNode] = field(default_factory=list)
    content_type: str = "document"
    language: Optional[str] = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)
    # HTML 注释范围列表 [(start_offset, end_offset_exclusive), ...]，由 markdown_parser 填，
    # chunker 用它跳过任何 char_offset 落在注释内的段（K8s 双语对照英文翻译源）。
    comment_ranges: list[tuple[int, int]] = field(default_factory=list)
