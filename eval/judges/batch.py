"""Concurrent batch judging with semaphore."""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass

from loader import Pair
from judges.deepseek import judge_one_async, AIGWConfig
from judges.cache import JudgeCache
from judges.prompts import JudgeVerdict

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    pair: Pair
    verdict: JudgeVerdict | None  # None when judge_failed
    cache_hit: bool
    error: str | None  # None when success


async def judge_batch_async(
    pairs: list[Pair],
    cfg: AIGWConfig,
    cache: JudgeCache | None = None,
    concurrency: int = 4,
) -> list[BatchResult]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(p: Pair) -> BatchResult:
        async with sem:
            try:
                v, hit = await judge_one_async(p, cfg, cache=cache)
                return BatchResult(p, v, hit, None)
            except Exception as e:
                logger.error(f"[{p.id}] judge_failed: {type(e).__name__}: {e}")
                return BatchResult(p, None, False, f"{type(e).__name__}: {e}")

    return await asyncio.gather(*(_one(p) for p in pairs))
