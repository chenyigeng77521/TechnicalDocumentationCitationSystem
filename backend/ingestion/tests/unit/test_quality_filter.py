"""quality_filter 模块单元测试。

Spec: docs/superpowers/specs/2026-04-27-chunk-quality-filter-design.md
"""
import pytest
from backend.ingestion.chunker.quality_filter import (
    filter_quality, MIN_CHARS_QUALITY, ALPHANUM_RATIO_THRESHOLD,
)
from backend.ingestion.chunker.types import Chunk


def _make_chunk(content: str, file_path: str = "test.docx", is_truncated: bool = False) -> Chunk:
    """测试用 helper，简化构造 Chunk 对象。"""
    return Chunk(
        chunk_id="x",
        file_path=file_path,
        file_hash="h",
        index_version="v1",
        content=content,
        anchor_id=f"{file_path}#0",
        title_path=None,
        char_offset_start=0,
        char_offset_end=len(content),
        char_count=len(content),
        chunk_index=0,
        is_truncated=is_truncated,
        content_type="document",
        language=None,
    )


def test_keeps_normal_chunks():
    chunks = [_make_chunk("a" * 60)]
    assert len(filter_quality(chunks)) == 1


def test_drops_chunk_below_min_chars():
    chunks = [_make_chunk("a" * 49)]
    assert filter_quality(chunks) == []


def test_keeps_truncated_short_chunk():
    chunks = [_make_chunk("a" * 10, is_truncated=True)]
    assert len(filter_quality(chunks)) == 1
