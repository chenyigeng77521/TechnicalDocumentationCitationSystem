"""AsciiDoc 解析器。提取 raw_text + heading 层级树（含 anchor）。

spec §3.1：用手写 regex 抓 = 标题 + [[xxx]] 显式锚点。
adoc 高级语法（include / conditional / attributes）暂不支持，作普通正文。
"""
import re
from pathlib import Path
from typing import Optional
from backend.ingestion.parser.markdown_parser import _build_tree
from backend.ingestion.parser.types import ParseResult, TitleNode

# AsciiDoc 标题：= 到 ====== (1-6 级)
_HEADING_RE = re.compile(r"^(={1,6})\s+(.+?)\s*$", re.MULTILINE)
# 显式锚点：[[xxx]] 单独一行
_EXPLICIT_ANCHOR_RE = re.compile(r"^\[\[([\w-]+)\]\]\s*$", re.MULTILINE)


def _slugify(text: str) -> str:
    """转 GitHub 风格 slug：lowercase + 字母/数字/中文/连字符保留 + 其他转 -

    spec §3.3：跟赛题 Spring gold anchor 一致（kebab-case）。
    """
    s = text.lower()
    # 去掉 markdown/adoc 内部标记的 backtick / 加粗 / 下划线 / 波浪号
    s = re.sub(r'[`*_~]', '', s)
    # 非字母/数字/中文/连字符 替换为 -
    s = re.sub(r'[^\w一-鿿-]+', '-', s, flags=re.UNICODE)
    # 多个 - 合并 + 头尾 - 删除
    s = re.sub(r'-+', '-', s).strip('-')
    return s


def _extract_headings_with_anchors(raw: str) -> list[TitleNode]:
    """扫描 raw_text，提取标题 + 关联 anchor（spec §3.3 策略 α 升级版）。

    算法：
      1. 第 1 遍找出所有显式 [[xxx]] 单行 → {line_idx: anchor_name}
      2. 第 2 遍扫 = 标题，看前 1-2 行（跳空行）是否有显式 [[xxx]]
         - 有 → 用显式 anchor
         - 无 → 用 _slugify(标题文本) 自动生成
      3. 块级 [[xxx]] (后面跟 .Caption / 代码块 / 表格) 自动被忽略，
         因为下一行不是 = 标题
    """
    lines = raw.split("\n")

    # 第 1 遍：所有显式 [[xxx]] 行
    explicit_anchors: dict[int, str] = {}
    for i, line in enumerate(lines):
        m = _EXPLICIT_ANCHOR_RE.match(line)
        if m:
            explicit_anchors[i] = m.group(1)

    # 第 2 遍：扫标题
    headings: list[TitleNode] = []
    char_offset = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # 看前 1-2 行（跳空行）有没有 [[xxx]]
            anchor: Optional[str] = None
            for j in (i - 1, i - 2):
                if j < 0:
                    break
                if lines[j].strip() == "":
                    continue
                if j in explicit_anchors:
                    anchor = explicit_anchors[j]
                break  # 不是空行也不是显式 anchor 就停（不再往前找）
            # 没显式 anchor → 自动生成 slug
            if anchor is None:
                anchor = _slugify(text)
            headings.append(TitleNode(
                level=level,
                text=text,
                char_offset=char_offset,
                anchor=anchor,
            ))
        char_offset += len(line) + 1  # +1 是 \n

    return headings


async def parse(path: Path) -> ParseResult:
    """解析 AsciiDoc 文件。签名跟 markdown_parser.parse 一致。"""
    raw = path.read_text(encoding="utf-8")
    headings = _extract_headings_with_anchors(raw)
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
