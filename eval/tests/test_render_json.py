import json
from render.json_report import render_json


def test_keys_present():
    data = {
        "meta": {"run_id": "x"},
        "totals": {"total": 1},
        "summary": {"score": 1.0},
        "by_domain": {},
        "by_difficulty": {},
        "by_answer_type": {},
        "per_question": [],
        "bad_cases": {},
    }
    out = render_json(data)
    parsed = json.loads(out)
    assert set(parsed.keys()) >= {
        "meta", "totals", "summary", "by_domain", "by_difficulty",
        "by_answer_type", "per_question", "bad_cases",
    }


def test_unicode_preserved():
    """中文不应被转成 backslash-u 序列。"""
    data = {"answer": "增量采用"}
    out = render_json(data)
    assert "增量采用" in out
    assert "\\u" not in out


def test_roundtrip():
    """render → parse 数据无损。"""
    data = {
        "totals": {"total": 200, "answer_correct": 130},
        "summary": {"score": 0.65, "answer_acc": 0.81},
        "per_question": [
            {"id": "react_001", "bucket": "answer_correct"},
        ],
    }
    out = render_json(data)
    parsed = json.loads(out)
    assert parsed == data


def test_indented():
    """indent=2 让人类可读。"""
    data = {"a": 1, "b": 2}
    out = render_json(data)
    assert "\n  " in out  # 2-space indent
