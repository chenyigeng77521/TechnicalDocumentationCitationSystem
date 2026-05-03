"""Retrieval recall@K (strict + loose) and citation precision."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RetrievalScore:
    hit_strict: bool
    hit_loose: bool
    strict_hit_count: int
    loose_hit_count: int
    citation_precision_strict: float
    citations_used: int  # min(len(citations), top_k)


def score_retrieval(
    gold_sources: list[dict], citations: list[dict], top_k: int = 5
) -> RetrievalScore:
    cits = (citations or [])[:top_k]
    if not cits or not gold_sources:
        return RetrievalScore(False, False, 0, 0, 0.0, len(cits))

    strict_set = {(s.get("doc_path", ""), s.get("anchor", "")) for s in gold_sources}
    loose_set = {s.get("doc_path", "") for s in gold_sources}

    strict_count = sum(
        1 for c in cits if (c.get("doc_path", ""), c.get("anchor", "")) in strict_set
    )
    loose_count = sum(1 for c in cits if c.get("doc_path", "") in loose_set)

    return RetrievalScore(
        hit_strict=strict_count > 0,
        hit_loose=loose_count > 0,
        strict_hit_count=strict_count,
        loose_hit_count=loose_count,
        citation_precision_strict=strict_count / len(cits) if cits else 0.0,
        citations_used=len(cits),
    )
