"""测试 overlap 拼接。"""
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.overlap import apply_overlap, OVERLAP_CHARS


def _mk(idx, content):
    return Chunk(
        chunk_id=f"c{idx}", file_path="a.md", file_hash="h",
        index_version="v1", content=content, anchor_id=f"a.md#{idx*100}",
        title_path=None, char_offset_start=idx * 100,
        char_offset_end=idx * 100 + len(content), char_count=len(content),
        chunk_index=idx,
    )


def test_apply_overlap_prepends_tail_of_previous():
    c1 = _mk(0, "a" * 500)
    c2 = _mk(1, "b" * 500)
    result = apply_overlap([c1, c2])
    assert result[0].content == "a" * 500   # 第一个不变
    assert result[1].content.startswith("a" * OVERLAP_CHARS)
    assert result[1].content.endswith("b" * 500)


def test_apply_overlap_no_op_for_single():
    c = _mk(0, "hello")
    assert apply_overlap([c]) == [c]


def test_apply_overlap_skips_truncated():
    c1 = _mk(0, "a" * 500)
    c2 = _mk(1, "b" * 500)
    c2.is_truncated = True
    result = apply_overlap([c1, c2])
    # truncated chunk 不加 overlap（避免破坏硬切边界）
    assert result[1].content == "b" * 500
