import json
from pathlib import Path
from unittest.mock import patch

import pytest

from score import run_eval
from judges.prompts import JudgeVerdict
from judges.batch import BatchResult


class _Args:
    def __init__(self, gold, results, out):
        self.gold = gold
        self.results = results
        self.out = out
        self.judge_model = "aliyun/deepseek-v3.2"
        self.judge_strictness = "medium"
        self.judge_timeout = 90.0
        self.top_k = 5
        self.concurrency = 4
        self.no_cache = True


@pytest.mark.asyncio
async def test_e2e_writes_md_and_json(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGW_API_KEY", "fake-test-key")
    fix = Path(__file__).parent / "fixtures"
    args = _Args(
        gold=str(fix / "sample_gold_10.jsonl"),
        results=str(fix / "sample_results_10.jsonl"),
        out=str(tmp_path / "smoke_test"),
    )

    async def fake_batch(pairs, cfg, cache=None, concurrency=4):
        return [
            BatchResult(p, JudgeVerdict("correct", "mocked"), False, None)
            for p in pairs
        ]

    with patch("score.judge_batch_async", side_effect=fake_batch):
        data = await run_eval(args)

    md = Path(str(tmp_path / "smoke_test") + ".md")
    js = Path(str(tmp_path / "smoke_test") + ".json")
    assert md.exists() and js.exists()

    md_text = md.read_text(encoding="utf-8")
    assert "RAG 评分报告" in md_text
    assert "## 一、元信息" in md_text
    assert "## 二、总分" in md_text
    assert "## 五、Bad Cases" in md_text

    js_data = json.loads(js.read_text(encoding="utf-8"))
    assert {
        "meta", "totals", "summary", "by_domain", "by_difficulty",
        "by_answer_type", "per_question", "bad_cases",
    }.issubset(js_data.keys())

    # 8 mocked correct + 2 trap refused
    assert js_data["totals"]["answer_correct"] == 8
    assert js_data["totals"]["refuse_correct"] == 2
    assert js_data["totals"]["total"] == 10
    # score = (8 + 2) / 10 = 1.0
    assert js_data["summary"]["score"] == pytest.approx(1.0)
    # per_question 长度 = 10
    assert len(js_data["per_question"]) == 10
    # 检索字段在 answer_correct 题里
    react_001 = next(q for q in js_data["per_question"] if q["id"] == "react_001")
    assert react_001["bucket"] == "answer_correct"
    assert react_001["retrieval"]["hit_strict_at_5"] is True
