"""chunk 入库前内容质量过滤。

3 条规则按顺序：太短 / 字母数字占比低 / 同文档重复。

Spec: docs/superpowers/specs/2026-04-27-chunk-quality-filter-design.md
"""
import unicodedata
from backend.ingestion.chunker.types import Chunk

MIN_CHARS_QUALITY = 50
ALPHANUM_RATIO_THRESHOLD = 0.30


def _alphanumeric_ratio(text: str) -> float:
    """有效字符（字母 + 数字 + 中文等 Unicode L/N 类）占总字符数的比例。"""
    if not text:
        return 0.0
    valid = sum(
        1 for ch in text
        if unicodedata.category(ch)[0] in ('L', 'N')
    )
    return valid / len(text)


def _drop_too_short(chunks: list[Chunk]) -> list[Chunk]:
    """规则 ①：长度 < MIN_CHARS_QUALITY 的丢，但 is_truncated=True 的留。"""
    return [
        c for c in chunks
        if len(c.content) >= MIN_CHARS_QUALITY or c.is_truncated
    ]


def _drop_low_alphanumeric(chunks: list[Chunk]) -> list[Chunk]:
    """规则 ②：占位，下个 task 实现。"""
    return chunks


def _dedup_within_document(chunks: list[Chunk]) -> list[Chunk]:
    """规则 ③：占位，下个 task 实现。"""
    return chunks


def filter_quality(chunks: list[Chunk]) -> list[Chunk]:
    """主入口：按顺序应用 3 条规则。"""
    chunks = _drop_too_short(chunks)
    chunks = _drop_low_alphanumeric(chunks)
    chunks = _dedup_within_document(chunks)
    return chunks
