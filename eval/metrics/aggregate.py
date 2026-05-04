"""Group per_question records by domain/difficulty/answer_type and aggregate."""
from __future__ import annotations
from collections import defaultdict


def aggregate_totals(per_q: list[dict]) -> dict:
    """Compute totals + summary from per_question records.

    Each record must have:
      - bucket: one of answer_correct / answer_wrong / refuse_correct /
                refuse_missed / refuse_false / judge_failed
      - model.confidence: float (only used for answer_correct/answer_wrong)
      - retrieval: dict with hit_strict_at_5/hit_loose_at_5/citation_precision
                   (only present for answer_correct/answer_wrong)
    """
    totals: dict[str, int] = defaultdict(int)
    confidences: list[float] = []
    retrieval_hits_strict = 0
    retrieval_hits_loose = 0
    retrieval_eligible = 0
    citation_prec_sum = 0.0

    for q in per_q:
        bucket = q["bucket"]
        totals[bucket] += 1
        totals["total"] += 1
        if bucket in ("answer_correct", "answer_wrong"):
            confidences.append(q["model"]["confidence"])
            retrieval_eligible += 1
            if q["retrieval"]["hit_strict_at_5"]:
                retrieval_hits_strict += 1
            if q["retrieval"]["hit_loose_at_5"]:
                retrieval_hits_loose += 1
            citation_prec_sum += q["retrieval"]["citation_precision"]

    answer_correct = totals.get("answer_correct", 0)
    answer_wrong = totals.get("answer_wrong", 0)
    refuse_correct = totals.get("refuse_correct", 0)
    refuse_missed = totals.get("refuse_missed", 0)
    refuse_false = totals.get("refuse_false", 0)
    judge_failed = totals.get("judge_failed", 0)
    total = totals["total"]
    answered_answerable = answer_correct + answer_wrong
    unanswerable_total = refuse_correct + refuse_missed  # 应拒题（gold trap）
    answerable_total = answer_correct + answer_wrong + refuse_false  # 应答题
    refused_total = refuse_correct + refuse_false  # 模型拒答的题数

    def _div(n, d):
        """Returns ratio or None when denominator is 0 (= N/A, not 0%)."""
        return n / d if d else None

    return {
        "totals": {
            "total": total,
            "answer_correct": answer_correct,
            "answer_wrong": answer_wrong,
            "refuse_correct": refuse_correct,
            "refuse_missed": refuse_missed,
            "refuse_false": refuse_false,
            "judge_failed": judge_failed,
        },
        "summary": {
            "score": _div(answer_correct + refuse_correct, total),
            "answer_acc": _div(answer_correct, answered_answerable),
            # 拒答 Recall：应拒题里成功拒答的比例（高 = 不漏 trap）
            "refuse_recall": _div(refuse_correct, unanswerable_total),
            # 拒答 Precision：拒答的题里真正该拒的比例（高 = 不乱拒）
            "refuse_precision": _div(refuse_correct, refused_total),
            "hallucination_rate": _div(refuse_missed, unanswerable_total),
            "false_refuse_rate": _div(refuse_false, answerable_total),
            "avg_confidence": (
                sum(confidences) / len(confidences) if confidences else None
            ),
            "hit_rate_strict_at_5": _div(retrieval_hits_strict, retrieval_eligible),
            "hit_rate_loose_at_5": _div(retrieval_hits_loose, retrieval_eligible),
            "citation_precision_strict": _div(citation_prec_sum, retrieval_eligible),
        },
    }


def group_by(per_q: list[dict], field: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in per_q:
        if field not in q:
            raise ValueError(f"per_question record {q.get('id')} missing field {field!r}")
        groups[q[field]].append(q)
    return {key: aggregate_totals(qs) for key, qs in groups.items()}
