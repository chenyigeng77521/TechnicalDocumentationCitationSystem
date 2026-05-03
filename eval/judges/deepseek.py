"""Async judge call to AIGW DeepSeek-v3.2 with cache + retry + timeout."""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
import httpx

from loader import Pair
from judges.prompts import (
    render_prompt, parse_verdict, JudgeVerdict, JudgeParseError, PROMPT_VERSION
)
from judges.cache import JudgeCache, compute_cache_key

logger = logging.getLogger(__name__)


@dataclass
class AIGWConfig:
    api_key: str
    base_url: str = "https://aigw.asiainfo.com/v1"
    model: str = "aliyun/deepseek-v3.2"
    timeout: float = 90.0


def _build_prompt_for_pair(pair: Pair) -> str:
    g = pair.gold
    r = pair.result
    evidences = [s["evidence"] for s in g.get("gold_sources", []) if s.get("evidence")]
    return render_prompt(
        question=g["question"],
        gold_answer=g.get("answer", ""),
        evidences=evidences,
        model_answer=r.get("answer", ""),
    )


async def _call_deepseek_once(prompt: str, cfg: AIGWConfig) -> str:
    """Single HTTP call. Raises HTTPStatusError, TimeoutException, etc."""
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        resp = await client.post(f"{cfg.base_url}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def judge_one_async(
    pair: Pair,
    cfg: AIGWConfig,
    cache: JudgeCache | None = None,
    prompt_version: str = PROMPT_VERSION,
) -> tuple[JudgeVerdict, bool]:
    """Returns (verdict, cache_hit). Retries on transient failures."""
    cache_key = None
    if cache:
        cache_key = compute_cache_key(
            pair.id, pair.result.get("answer", ""), pair.gold.get("answer", ""),
            cfg.model, prompt_version,
        )
        cached = cache.get(cache_key)
        if cached:
            return cached, True

    prompt = _build_prompt_for_pair(pair)

    # 重试策略：
    # - 5xx / 401 / 408 / 400：重 2 次
    # - 429：指数退避 5s/10s/20s
    # - timeout：重 2 次
    # - JSON parse 失败：重 3 次（每次重发）
    backoff_429 = [5, 10, 20]
    last_exc: Exception | None = None
    for attempt in range(4):  # 1 首调 + 最多 3 重试
        try:
            content = await _call_deepseek_once(prompt, cfg)
            if not content or not content.strip():
                raise JudgeParseError("empty response content")
            verdict = parse_verdict(content)
            if cache and cache_key:
                cache.put(cache_key, verdict)
            return verdict, False
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response else 0
            last_exc = e
            if status == 429 and attempt < len(backoff_429):
                logger.warning(f"[{pair.id}] 429 limit, backoff {backoff_429[attempt]}s")
                await asyncio.sleep(backoff_429[attempt])
                continue
            elif status in (400, 401, 408, 500) and attempt < 2:
                logger.warning(f"[{pair.id}] HTTP {status}, retry {attempt+1}/2")
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                raise
        except httpx.TimeoutException as e:
            last_exc = e
            if attempt < 2:
                logger.warning(f"[{pair.id}] timeout, retry {attempt+1}/2")
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except JudgeParseError as e:
            last_exc = e
            if attempt < 3:
                logger.warning(f"[{pair.id}] JSON parse fail, retry {attempt+1}/3: {e}")
                continue
            raise
    assert last_exc is not None
    raise last_exc
