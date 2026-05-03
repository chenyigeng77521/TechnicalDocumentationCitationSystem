"""4 buckets pre-classification (judge-independent).

answered_answerable    → 后续由 judge 拆成 answer_correct / answer_wrong
refused_unanswerable   → refuse_correct (拒答正确)
answered_unanswerable  → refuse_missed (该拒没拒，幻觉)
refused_answerable     → refuse_false (不该拒拒了，漏题)
"""
from __future__ import annotations
from loader import Pair

BUCKETS = (
    "answered_answerable",
    "refused_answerable",
    "answered_unanswerable",
    "refused_unanswerable",
)


def classify_buckets(pairs: list[Pair]) -> dict[str, list[Pair]]:
    out: dict[str, list[Pair]] = {b: [] for b in BUCKETS}
    for p in pairs:
        try:
            answerable = bool(p.gold["is_answerable"])
            refused = bool(p.result["is_refusal"])
        except KeyError as e:
            raise ValueError(f"{p.id}: missing required field {e}") from e
        if answerable and not refused:
            out["answered_answerable"].append(p)
        elif answerable and refused:
            out["refused_answerable"].append(p)
        elif not answerable and not refused:
            out["answered_unanswerable"].append(p)
        else:
            out["refused_unanswerable"].append(p)
    return out
