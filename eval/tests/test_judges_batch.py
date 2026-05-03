import asyncio
import pytest
from unittest.mock import patch

from loader import Pair
from judges.batch import judge_batch_async, BatchResult
from judges.deepseek import AIGWConfig
from judges.prompts import JudgeVerdict


def _pairs(n):
    return [
        Pair(
            id=f"q{i}",
            gold={"id": f"q{i}", "question": "q", "answer": "a"},
            result={"id": f"q{i}", "answer": "m"},
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_batch_success():
    cfg = AIGWConfig(api_key="fake")

    async def fake(pair, cfg, cache=None, prompt_version="v1.0"):
        return JudgeVerdict("correct", "ok"), False

    with patch("judges.batch.judge_one_async", side_effect=fake):
        results = await judge_batch_async(_pairs(10), cfg, concurrency=4)
    assert len(results) == 10
    assert all(r.verdict and r.verdict.verdict == "correct" for r in results)
    assert all(r.error is None for r in results)


@pytest.mark.asyncio
async def test_batch_empty():
    cfg = AIGWConfig(api_key="fake")
    assert await judge_batch_async([], cfg) == []


@pytest.mark.asyncio
async def test_batch_single():
    cfg = AIGWConfig(api_key="fake")

    async def fake(p, c, cache=None, prompt_version="v1.0"):
        return JudgeVerdict("wrong", "x"), False

    with patch("judges.batch.judge_one_async", side_effect=fake):
        results = await judge_batch_async(_pairs(1), cfg)
    assert len(results) == 1 and results[0].verdict.verdict == "wrong"


@pytest.mark.asyncio
async def test_batch_partial_failure():
    cfg = AIGWConfig(api_key="fake")

    async def fake(p, c, cache=None, prompt_version="v1.0"):
        if p.id == "q3":
            raise RuntimeError("oops")
        return JudgeVerdict("correct", "ok"), False

    with patch("judges.batch.judge_one_async", side_effect=fake):
        results = await judge_batch_async(_pairs(5), cfg)
    failed = [r for r in results if r.error]
    assert len(failed) == 1 and failed[0].pair.id == "q3"
    assert "RuntimeError" in failed[0].error
    # 其余 4 题成功
    assert len([r for r in results if r.verdict]) == 4


@pytest.mark.asyncio
async def test_concurrency_cap():
    cfg = AIGWConfig(api_key="fake")
    in_flight = {"n": 0, "max": 0}

    async def fake(p, c, cache=None, prompt_version="v1.0"):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        await asyncio.sleep(0.01)
        in_flight["n"] -= 1
        return JudgeVerdict("correct", "ok"), False

    with patch("judges.batch.judge_one_async", side_effect=fake):
        await judge_batch_async(_pairs(20), cfg, concurrency=3)
    assert in_flight["max"] <= 3


@pytest.mark.asyncio
async def test_concurrent_cache_writes(tmp_path):
    """缓存并发写入：多 task 写不同 key 不冲突。"""
    from judges.cache import JudgeCache, compute_cache_key
    from judges.prompts import PROMPT_VERSION

    cache = JudgeCache(tmp_path)
    cfg = AIGWConfig(api_key="fake")

    async def fake(p, c, cache=None, prompt_version=PROMPT_VERSION):
        if cache:
            key = compute_cache_key(p.id, "m", "a", c.model, prompt_version)
            cache.put(key, JudgeVerdict("correct", p.id))
        return JudgeVerdict("correct", p.id), False

    with patch("judges.batch.judge_one_async", side_effect=fake):
        await judge_batch_async(_pairs(20), cfg, cache=cache, concurrency=8)
    cached_files = list(tmp_path.glob("*.json"))
    assert len(cached_files) == 20
