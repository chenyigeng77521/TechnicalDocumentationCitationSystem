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


# Task 3 实现：_extract_headings_with_anchors
# Task 4 实现：parse()
