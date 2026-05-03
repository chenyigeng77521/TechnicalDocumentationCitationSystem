import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from loader import Pair
from judges.deepseek import judge_one_async, AIGWConfig
from judges.prompts import JudgeVerdict, JudgeParseError, PROMPT_VERSION
from judges.cache import JudgeCache, compute_cache_key


def _pair():
    return Pair(
        id="react_001",
        gold={
            "id": "react_001",
            "question": "React Compiler 的增量采用是什么？",
            "answer": "可以增量",
            "gold_sources": [{"evidence": "evidence text"}],
        },
        result={"id": "react_001", "answer": "是的可以分阶段"},
    )


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    """Build an HTTPStatusError with a real-looking response."""
    req = httpx.Request("POST", "https://x")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


@pytest.mark.asyncio
async def test_judge_success():
    cfg = AIGWConfig(api_key="fake")
    with patch("judges.deepseek._call_deepseek_once",
               return_value='{"verdict":"correct","reason":"ok"}'):
        v, hit = await judge_one_async(_pair(), cfg)
    assert v.verdict == "correct"
    assert hit is False


@pytest.mark.asyncio
async def test_cache_hit_skips_call(tmp_path):
    cache = JudgeCache(tmp_path)
    cfg = AIGWConfig(api_key="fake")
    p = _pair()
    key = compute_cache_key(
        p.id, p.result["answer"], p.gold["answer"], cfg.model, PROMPT_VERSION,
    )
    cache.put(key, JudgeVerdict("correct", "cached"))
    with patch("judges.deepseek._call_deepseek_once") as mc:
        v, hit = await judge_one_async(p, cfg, cache=cache)
    assert hit is True and v.reason == "cached"
    mc.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_writes(tmp_path):
    cache = JudgeCache(tmp_path)
    cfg = AIGWConfig(api_key="fake")
    with patch("judges.deepseek._call_deepseek_once",
               return_value='{"verdict":"correct","reason":"ok"}'):
        v, hit = await judge_one_async(_pair(), cfg, cache=cache)
    assert hit is False
    # 第二次调用应命中缓存
    with patch("judges.deepseek._call_deepseek_once") as mc2:
        v2, hit2 = await judge_one_async(_pair(), cfg, cache=cache)
    assert hit2 is True
    mc2.assert_not_called()


@pytest.mark.asyncio
async def test_empty_content_raises():
    cfg = AIGWConfig(api_key="fake")
    # All 4 attempts return empty → final JudgeParseError
    with patch("judges.deepseek._call_deepseek_once", return_value=""):
        with pytest.raises(JudgeParseError, match="empty"):
            await judge_one_async(_pair(), cfg)


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds():
    cfg = AIGWConfig(api_key="fake")
    call_count = {"n": 0}

    async def flaky(prompt, cfg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise _http_status_error(500)
        return '{"verdict":"correct","reason":"ok"}'

    with patch("judges.deepseek._call_deepseek_once", side_effect=flaky):
        v, _ = await judge_one_async(_pair(), cfg)
    assert v.verdict == "correct"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_429_backoff(monkeypatch):
    cfg = AIGWConfig(api_key="fake")
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("judges.deepseek.asyncio.sleep", fake_sleep)

    call_count = {"n": 0}

    async def flaky(prompt, cfg):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise _http_status_error(429)
        return '{"verdict":"correct","reason":"ok"}'

    with patch("judges.deepseek._call_deepseek_once", side_effect=flaky):
        v, _ = await judge_one_async(_pair(), cfg)
    assert v.verdict == "correct"
    assert sleeps == [5, 10]


@pytest.mark.asyncio
async def test_timeout_retries():
    cfg = AIGWConfig(api_key="fake")
    call_count = {"n": 0}

    async def flaky(prompt, cfg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.TimeoutException("timed out")
        return '{"verdict":"correct","reason":"ok"}'

    with patch("judges.deepseek._call_deepseek_once", side_effect=flaky):
        v, _ = await judge_one_async(_pair(), cfg)
    assert v.verdict == "correct"


@pytest.mark.asyncio
async def test_invalid_json_retries():
    cfg = AIGWConfig(api_key="fake")
    call_count = {"n": 0}

    async def flaky(prompt, cfg):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return "not json at all"
        return '{"verdict":"correct","reason":"ok"}'

    with patch("judges.deepseek._call_deepseek_once", side_effect=flaky):
        v, _ = await judge_one_async(_pair(), cfg)
    assert v.verdict == "correct"
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_prompt_passed():
    cfg = AIGWConfig(api_key="fake")
    captured = {}

    async def capture(prompt, cfg):
        captured["prompt"] = prompt
        return '{"verdict":"correct","reason":"ok"}'

    with patch("judges.deepseek._call_deepseek_once", side_effect=capture):
        await judge_one_async(_pair(), cfg)
    assert "React Compiler 的增量采用是什么？" in captured["prompt"]
    assert "是的可以分阶段" in captured["prompt"]
