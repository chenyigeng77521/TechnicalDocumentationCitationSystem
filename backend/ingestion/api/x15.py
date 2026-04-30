"""X1.5 search 接口 section 全量化辅助函数。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md
"""
import functools
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RAW_DIR = Path("backend/storage/raw")
DEFAULT_MAX_CHARS = 2000


@functools.lru_cache(maxsize=200)
def _read_raw_file(file_path: str) -> str:
    """读源 markdown 文件，CRLF 归一化（跟 chunker 入口一致）。

    file_path 是 DB 里存的相对路径（不含 raw/ 前缀）。
    LRU 缓存上限 200，覆盖当前 164 文件且对未来扩到 10K+ 文件也稳定（自动淘汰冷文件）。
    测试 fixture 必须显式调 _read_raw_file.cache_clear() 防跨测污染。
    """
    abs_path = RAW_DIR / file_path
    text = abs_path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")
