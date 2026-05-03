import pytest
from render.markdown import render_full


def _full_data():
    return {
        "meta": {
            "run_id": "smoke10",
            "timestamp": "2026-05-03T17:30:00",
            "duration_seconds": 12,
            "input": {
                "gold_path": "g.jsonl", "results_path": "r.jsonl",
                "matched": 10, "gold_only": 0, "results_only": 0,
            },
            "params": {
                "judge_model": "aliyun/deepseek-v3.2",
                "judge_strictness": "medium",
                "top_k": 5, "concurrency": 4,
            },
        },
        "totals": {
            "total": 10,
            "answer_correct": 6, "answer_wrong": 2,
            "refuse_correct": 2, "refuse_missed": 0, "refuse_false": 0,
            "judge_failed": 0,
        },
        "summary": {
            "score": 0.8, "answer_acc": 0.75,
            "refuse_precision": 1.0, "hallucination_rate": 0.0,
            "false_refuse_rate": 0.0, "avg_confidence": 0.85,
            "hit_rate_strict_at_5": 0.625, "hit_rate_loose_at_5": 0.875,
            "citation_precision_strict": 0.7,
        },
        "by_domain": {
            "React": {
                "totals": {"total": 4},
                "summary": {
                    "score": 1.0, "answer_acc": 1.0,
                    "refuse_precision": 0.0, "hallucination_rate": 0.0,
                    "hit_rate_strict_at_5": 0.75, "hit_rate_loose_at_5": 1.0,
                },
            },
        },
        "by_difficulty": {
            "easy": {
                "totals": {"total": 5},
                "summary": {
                    "score": 0.8, "answer_acc": 1.0,
                    "refuse_precision": 0.0, "hallucination_rate": 0.0,
                    "hit_rate_strict_at_5": 0.6, "hit_rate_loose_at_5": 1.0,
                },
            },
        },
        "per_question": [],
        "bad_cases": {
            "wrong_answer_top10": [
                {
                    "id": "k8s_007", "domain": "K8s", "difficulty": "medium",
                    "question": "Pod 优先级抢占的工作机制是什么？",
                    "gold_answer": "高优先级 Pod 可抢占低优先级 Pod",
                    "model_answer": "Pod 不能抢占其他 Pod",
                    "model": {"confidence": 0.85},
                    "judge": {"verdict": "wrong", "reason": "跟标准答案完全相反"},
                    "citations": [{"doc_path": "k8s/x.md", "anchor": "#a"}],
                    "gold_sources": [{"doc_path": "k8s/scheduling.md", "anchor": "#preemption"}],
                },
            ],
            "hallucination": [],
            "retrieval_miss_top10": [],
            "false_refuse": [],
            "judge_failed": [],
        },
    }


def test_render_full_sections():
    md = render_full(_full_data())
    assert "RAG 评分报告 — smoke10" in md
    assert "## 一、元信息" in md
    assert "## 二、总分" in md
    assert "## 三、按 Domain 分组" in md
    assert "## 四、按难度分组" in md
    assert "## 五、Bad Cases" in md
    assert "## 六、附录" in md


def test_render_top6_values():
    md = render_full(_full_data())
    assert "80.00%" in md  # score
    assert "75.00%" in md  # answer_acc
    assert "0.850" in md   # avg_confidence


def test_render_5_buckets():
    md = render_full(_full_data())
    # 5 个口袋的标签都在
    assert "答对" in md
    assert "答错" in md
    assert "拒答正确" in md
    assert "该拒没拒" in md
    assert "不该拒拒了" in md


def test_render_bad_case_includes_judge_reason():
    md = render_full(_full_data())
    assert "跟标准答案完全相反" in md
    assert "k8s_007" in md
    assert "0.850" in md  # confidence


def test_render_empty_bad_cases():
    data = _full_data()
    data["bad_cases"]["wrong_answer_top10"] = []
    md = render_full(data)
    # "5.2 答错 Top 10" 段下应有"（无）"
    assert "5.2" in md and "（无）" in md


def test_render_zero_total():
    """边界：总数 0 的情况不应崩"""
    data = _full_data()
    data["totals"] = {
        "total": 0, "answer_correct": 0, "answer_wrong": 0,
        "refuse_correct": 0, "refuse_missed": 0, "refuse_false": 0,
        "judge_failed": 0,
    }
    data["summary"] = {
        "score": 0.0, "answer_acc": 0.0,
        "refuse_precision": 0.0, "hallucination_rate": 0.0,
        "false_refuse_rate": 0.0, "avg_confidence": 0.0,
        "hit_rate_strict_at_5": 0.0, "hit_rate_loose_at_5": 0.0,
        "citation_precision_strict": 0.0,
    }
    md = render_full(data)
    assert "0.00%" in md  # all zeros
    assert "**合计** | **0**" in md


def test_render_missing_top_field_raises():
    """data 缺顶层 totals 等必需字段应抛 KeyError"""
    bad = {"meta": {"run_id": "x", "timestamp": "t"}}
    with pytest.raises(KeyError):
        render_full(bad)


def test_render_buckets_sum_displayed():
    """5 口袋之和应显示且 = total"""
    md = render_full(_full_data())
    # 6+2+2+0+0+0 = 10
    assert "**合计** | **10**" in md
