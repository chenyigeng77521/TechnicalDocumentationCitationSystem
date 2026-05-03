import pytest
from metrics.aggregate import aggregate_totals, group_by


def _q(id, bucket, domain="React", difficulty="easy", answer_type="concept",
       confidence=0.9, hit_strict=True, hit_loose=True, citation_prec=1.0):
    """Build a per_question record."""
    rec = {
        "id": id,
        "domain": domain,
        "difficulty": difficulty,
        "answer_type": answer_type,
        "bucket": bucket,
        "model": {"confidence": confidence},
    }
    if bucket in ("answer_correct", "answer_wrong"):
        rec["retrieval"] = {
            "hit_strict_at_5": hit_strict,
            "hit_loose_at_5": hit_loose,
            "citation_precision": citation_prec,
        }
    return rec


def test_aggregate_basic():
    per_q = [
        _q("q1", "answer_correct", confidence=0.9, hit_strict=True, citation_prec=1.0),
        _q("q2", "answer_wrong", confidence=0.5, hit_strict=False, hit_loose=True, citation_prec=0.0),
        _q("q3", "refuse_correct"),
        _q("q4", "refuse_missed"),
        _q("q5", "refuse_false"),
    ]
    out = aggregate_totals(per_q)
    t = out["totals"]
    assert t == {
        "total": 5,
        "answer_correct": 1, "answer_wrong": 1,
        "refuse_correct": 1, "refuse_missed": 1, "refuse_false": 1,
        "judge_failed": 0,
    }
    s = out["summary"]
    # score = (1 + 1) / 5 = 0.4
    assert s["score"] == pytest.approx(0.4)
    # answer_acc = 1/(1+1) = 0.5
    assert s["answer_acc"] == pytest.approx(0.5)
    # refuse_precision = 1/(1+1) = 0.5
    assert s["refuse_precision"] == pytest.approx(0.5)
    # hallucination = 1/(1+1) = 0.5
    assert s["hallucination_rate"] == pytest.approx(0.5)
    # false_refuse = 1/(1+1+1) = 1/3
    assert s["false_refuse_rate"] == pytest.approx(1 / 3)
    # avg_confidence = (0.9+0.5)/2 = 0.7
    assert s["avg_confidence"] == pytest.approx(0.7)
    # hit_rate_strict = 1/2 = 0.5
    assert s["hit_rate_strict_at_5"] == pytest.approx(0.5)
    # hit_rate_loose = 2/2 = 1.0
    assert s["hit_rate_loose_at_5"] == pytest.approx(1.0)


def test_aggregate_empty():
    out = aggregate_totals([])
    assert out["totals"]["total"] == 0
    assert out["summary"]["score"] == 0.0  # 不能 NaN


def test_aggregate_all_correct():
    per_q = [_q(f"q{i}", "answer_correct", confidence=1.0) for i in range(5)]
    out = aggregate_totals(per_q)
    assert out["summary"]["score"] == pytest.approx(1.0)
    assert out["summary"]["answer_acc"] == pytest.approx(1.0)


def test_group_by_domain():
    per_q = [
        _q("q1", "answer_correct", domain="React"),
        _q("q2", "answer_correct", domain="React"),
        _q("q3", "answer_wrong", domain="K8s"),
        _q("q4", "refuse_correct", domain="K8s"),
    ]
    out = group_by(per_q, "domain")
    assert set(out.keys()) == {"React", "K8s"}
    assert out["React"]["totals"]["total"] == 2
    assert out["K8s"]["totals"]["total"] == 2
    assert out["React"]["summary"]["score"] == pytest.approx(1.0)


def test_group_by_difficulty():
    per_q = [
        _q("q1", "answer_correct", difficulty="easy"),
        _q("q2", "answer_wrong", difficulty="medium"),
    ]
    out = group_by(per_q, "difficulty")
    assert set(out.keys()) == {"easy", "medium"}


def test_group_by_missing_field_raises():
    per_q = [{"id": "q1", "bucket": "answer_correct", "model": {"confidence": 0.9},
              "retrieval": {"hit_strict_at_5": True, "hit_loose_at_5": True, "citation_precision": 1.0}}]
    with pytest.raises(ValueError, match="missing field"):
        group_by(per_q, "domain")


def test_group_totals_sum_to_overall():
    """各 domain 的 total 之和应该等于 overall total。"""
    per_q = [_q(f"q{i}", "answer_correct", domain=("React" if i < 3 else "K8s"))
             for i in range(5)]
    overall = aggregate_totals(per_q)
    by_domain = group_by(per_q, "domain")
    sum_by_domain = sum(g["totals"]["total"] for g in by_domain.values())
    assert sum_by_domain == overall["totals"]["total"]
