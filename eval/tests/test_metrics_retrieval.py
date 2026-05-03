import pytest
from metrics.retrieval import score_retrieval, RetrievalScore


def test_strict_hit_top1():
    gold = [{"doc_path": "a.md", "anchor": "#x"}]
    cits = [
        {"doc_path": "a.md", "anchor": "#x"},
        {"doc_path": "b.md", "anchor": "#y"},
    ]
    s = score_retrieval(gold, cits, top_k=5)
    assert s.hit_strict is True and s.hit_loose is True
    assert s.strict_hit_count == 1 and s.loose_hit_count == 1


def test_empty_citations():
    s = score_retrieval([{"doc_path": "a.md", "anchor": "#x"}], [], top_k=5)
    assert s.hit_strict is False and s.strict_hit_count == 0
    assert s.citation_precision_strict == 0.0


def test_empty_gold_sources():
    s = score_retrieval([], [{"doc_path": "a.md", "anchor": "#x"}], top_k=5)
    assert s.hit_strict is False and s.hit_loose is False


def test_gold_more_than_k():
    gold = [{"doc_path": f"d{i}.md", "anchor": "#x"} for i in range(10)]
    cits = [
        {"doc_path": "d0.md", "anchor": "#x"},
        {"doc_path": "d1.md", "anchor": "#x"},
    ]
    s = score_retrieval(gold, cits, top_k=5)
    assert s.strict_hit_count == 2  # 都命中


def test_missing_field_returns_zero():
    gold = [{"doc_path": "a.md", "anchor": "#x"}]
    cits = [{}]
    s = score_retrieval(gold, cits)
    assert s.strict_hit_count == 0


def test_loose_hit_strict_miss():
    gold = [{"doc_path": "a.md", "anchor": "#x"}]
    cits = [{"doc_path": "a.md", "anchor": "#WRONG"}]
    s = score_retrieval(gold, cits)
    assert s.hit_strict is False and s.hit_loose is True
    assert s.strict_hit_count == 0 and s.loose_hit_count == 1


def test_citation_precision():
    gold = [{"doc_path": "a.md", "anchor": "#x"}]
    cits = [
        {"doc_path": "a.md", "anchor": "#x"},     # strict hit
        {"doc_path": "b.md", "anchor": "#y"},     # miss
        {"doc_path": "c.md", "anchor": "#z"},     # miss
    ]
    s = score_retrieval(gold, cits)
    assert s.citation_precision_strict == pytest.approx(1 / 3)


def test_top_k_truncation():
    """citations 超过 top_k 应只看前 K 个。"""
    gold = [{"doc_path": "z.md", "anchor": "#z"}]
    cits = [{"doc_path": f"a{i}.md", "anchor": "#x"} for i in range(5)]
    cits.append({"doc_path": "z.md", "anchor": "#z"})  # 第 6 条才是命中
    s = score_retrieval(gold, cits, top_k=5)
    assert s.hit_strict is False  # top-5 内没命中
