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
    # refuse_recall = refuse_correct / 应拒题 = 1/(1+1) = 0.5
    assert s["refuse_recall"] == pytest.approx(0.5)
    # refuse_precision = refuse_correct / 拒答总数 = 1/(1+1) = 0.5
    # （= refuse_correct / (refuse_correct + refuse_false)）
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
    """空输入时，所有比率都是 None（"N/A"），区分于真实的 0%。"""
    out = aggregate_totals([])
    assert out["totals"]["total"] == 0
    assert out["summary"]["score"] is None
    assert out["summary"]["answer_acc"] is None
    assert out["summary"]["refuse_recall"] is None
    assert out["summary"]["refuse_precision"] is None
    assert out["summary"]["avg_confidence"] is None


def test_aggregate_no_unanswerable_returns_none():
    """gold 全是可答题时，refuse_recall/hallucination_rate = None（不是 0）。

    Regression: 之前 React domain 没有 trap 题，refuse_precision (旧字段) 显示 "0.00%"，
    误以为"拒答全错"，其实是"无可拒题"。新版本拆成 recall/precision，
    recall 分母是应拒题数，仍是 None。
    """
    per_q = [_q(f"q{i}", "answer_correct") for i in range(5)]
    out = aggregate_totals(per_q)
    assert out["summary"]["refuse_recall"] is None
    assert out["summary"]["hallucination_rate"] is None
    # 没有任何拒答（refuse_correct=0, refuse_false=0）→ refuse_precision 也是 None
    assert out["summary"]["refuse_precision"] is None


def test_refuse_precision_distinct_from_recall():
    """关键回归：refuse_precision != refuse_recall 当模型有误拒时。

    例：50 个 trap 全拒（recall=1.0），但同时还误拒了 50 个可答题
    → precision = 50/(50+50) = 0.5（拒答里只有一半该拒）
    """
    per_q = []
    # 50 应拒题，全拒对了
    per_q += [_q(f"trap{i}", "refuse_correct") for i in range(50)]
    # 50 可答题，全被误拒了
    per_q += [_q(f"miss{i}", "refuse_false") for i in range(50)]
    out = aggregate_totals(per_q)
    s = out["summary"]
    # recall：应拒题里拒了多少 = 50/50 = 100%
    assert s["refuse_recall"] == pytest.approx(1.0)
    # precision：拒了的题里真该拒的 = 50/(50+50) = 50%
    assert s["refuse_precision"] == pytest.approx(0.5)
    # 这两个差 50 个点，证明它们是独立指标
    assert s["refuse_recall"] != s["refuse_precision"]


def test_render_none_displays_as_dash():
    """渲染 None 时显示 "—"，跟 "0.00%" 区分开。"""
    from render.markdown import render_full
    data = {
        "meta": {
            "run_id": "x", "timestamp": "t",
            "input": {"gold_path": "g", "results_path": "r",
                      "matched": 5, "gold_only": 0, "results_only": 0},
            "params": {},
        },
        "totals": {
            "total": 5, "answer_correct": 5, "answer_wrong": 0,
            "refuse_correct": 0, "refuse_missed": 0, "refuse_false": 0,
            "judge_failed": 0,
        },
        "summary": {
            "score": 1.0, "answer_acc": 1.0,
            "refuse_recall": None,  # 没有 trap 题（应拒题为 0）
            "refuse_precision": None,  # 没有任何拒答
            "hallucination_rate": None,
            "false_refuse_rate": 0.0,
            "false_refuse_rate": 0.0,
            "avg_confidence": 0.9,
            "hit_rate_strict_at_5": 0.5, "hit_rate_loose_at_5": 1.0,
            "citation_precision_strict": 0.6,
        },
        "by_domain": {}, "by_difficulty": {},
        "per_question": [], "bad_cases": {},
    }
    md = render_full(data)
    # 拒答 Recall + Precision 都应是 — （无 trap、无拒答）
    assert "**拒答 Recall（覆盖率）** | —" in md
    assert "**拒答 Precision（精准率）** | —" in md
    assert "**幻觉率 ⚠️** | —" in md
    # 真实的 0% 不应被替换
    assert "**误拒率** | 0.00%" in md


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
