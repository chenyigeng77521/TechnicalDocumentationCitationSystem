import pytest
from loader import Pair
from metrics.refusal import classify_buckets, BUCKETS


def _pair(id, answerable, refused):
    return Pair(id=id,
                gold={"id": id, "is_answerable": answerable},
                result={"id": id, "is_refusal": refused})


def test_four_combinations():
    pairs = [
        _pair("ans_ans", True, False),
        _pair("ref_ans", True, True),
        _pair("ans_unans", False, False),
        _pair("ref_unans", False, True),
    ]
    out = classify_buckets(pairs)
    assert set(out.keys()) == set(BUCKETS)
    assert [p.id for p in out["answered_answerable"]] == ["ans_ans"]
    assert [p.id for p in out["refused_answerable"]] == ["ref_ans"]
    assert [p.id for p in out["answered_unanswerable"]] == ["ans_unans"]
    assert [p.id for p in out["refused_unanswerable"]] == ["ref_unans"]


def test_empty_input():
    assert classify_buckets([]) == {b: [] for b in BUCKETS}


def test_missing_field_raises():
    bad = Pair(id="x", gold={}, result={"is_refusal": False})
    with pytest.raises(ValueError, match="missing"):
        classify_buckets([bad])


def test_real_fixture_distribution():
    from pathlib import Path
    from loader import load_pair
    fix = Path(__file__).parent / "fixtures"
    res = load_pair(fix / "sample_gold_10.jsonl", fix / "sample_results_10.jsonl")
    out = classify_buckets(res.matched)
    assert len(out["answered_answerable"]) == 8
    assert len(out["refused_unanswerable"]) == 2
    assert len(out["answered_unanswerable"]) == 0
    assert len(out["refused_answerable"]) == 0
