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


def test_drops_pure_punctuation():
    """36 个点 → 占比 0% → 丢"""
    chunks = [_make_chunk("." * 60)]
    assert filter_quality(chunks) == []


def test_drops_whitespace_heavy():
    """全空白 + 标点 → 占比 0% → 丢"""
    chunks = [_make_chunk("\t" * 30 + "   " * 10 + "," * 5)]
    assert filter_quality(chunks) == []


def test_keeps_chinese_content():
    """中文内容 → Unicode L 类有效 → 留（即使无英文字母）"""
    text = "数据治理是企业数据资产管理的核心实践包括元数据"
    chunks = [_make_chunk(text * 3)]
    assert len(filter_quality(chunks)) == 1


def test_keeps_code_with_symbols():
    """代码 chunk 含大量符号但字母 > 30% → 留"""
    text = "cat > /etc/kubernetes/controller-manager.conf <<EOF"
    chunks = [_make_chunk(text)]
    assert len(filter_quality(chunks)) == 1


def test_dedups_within_document():
    """同 file_path 内 content 完全相同 → 留第一条"""
    chunks = [
        _make_chunk("a" * 60, file_path="kube.docx"),
        _make_chunk("a" * 60, file_path="kube.docx"),
        _make_chunk("a" * 60, file_path="kube.docx"),
    ]
    result = filter_quality(chunks)
    assert len(result) == 1
    assert result[0].file_path == "kube.docx"


def test_keeps_cross_document_duplicates():
    """跨 file_path 同 content → 全留（合理引用）"""
    chunks = [
        _make_chunk("a" * 60, file_path="doc1.docx"),
        _make_chunk("a" * 60, file_path="doc2.docx"),
    ]
    result = filter_quality(chunks)
    assert len(result) == 2


def test_keeps_same_content_different_offset():
    """同文档 + 同 content 但不同 char_offset_start → 留（硬切产物保护）

    场景：超长段被硬切成多块 content 完全一样的 chunk，offset 不同 → 不该去重
    """
    c1 = _make_chunk("x" * 60, file_path="doc.docx")
    c2 = _make_chunk("x" * 60, file_path="doc.docx")
    c2.char_offset_start = 1000
    c2.char_offset_end = 1060
    c3 = _make_chunk("x" * 60, file_path="doc.docx")
    c3.char_offset_start = 2000
    c3.char_offset_end = 2060
    result = filter_quality([c1, c2, c3])
    assert len(result) == 3, "硬切产物 content 一样但 offset 不同，不应被去重"


def test_empty_input_returns_empty():
    """空 list 不报错，返空 list"""
    assert filter_quality([]) == []


def test_none_input_raises_typeerror():
    """None 输入抛 TypeError（按 Python 惯例不静默处理 None）"""
    with pytest.raises(TypeError):
        filter_quality(None)


# ============= 阈值边界测试（codex review 推荐）=============


def test_min_chars_exact_boundary():
    """len == MIN_CHARS_QUALITY (50) 应留；len == 49 应丢"""
    keep = _make_chunk("a" * MIN_CHARS_QUALITY)        # 50 chars
    drop = _make_chunk("b" * (MIN_CHARS_QUALITY - 1))  # 49 chars
    result = filter_quality([keep, drop])
    assert len(result) == 1
    assert result[0].content == "a" * MIN_CHARS_QUALITY


def test_alphanumeric_ratio_exact_boundary():
    """ratio == ALPHANUM_RATIO_THRESHOLD (0.30) 应留；ratio < 0.30 应丢

    构造 60 字符 chunk：恰好 18 字母（30%）vs 17 字母（< 30%）
    """
    # 60 chars, 18 alpha (30%), 42 dots → 留
    keep = _make_chunk("a" * 18 + "." * 42)
    # 60 chars, 17 alpha (28.3%), 43 dots → 丢
    drop = _make_chunk("a" * 17 + "." * 43)
    result = filter_quality([keep, drop])
    assert len(result) == 1
    assert result[0].content.count("a") == 18
