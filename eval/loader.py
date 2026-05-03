"""Load gold + results JSONL files and match by id."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Pair:
    id: str
    gold: dict
    result: dict


@dataclass
class LoadResult:
    matched: list[Pair] = field(default_factory=list)
    gold_only: list[dict] = field(default_factory=list)
    results_only: list[dict] = field(default_factory=list)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    records = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{ln}: invalid JSON: {e}") from e
    return records


def load_pair(gold_path: str | Path, results_path: str | Path) -> LoadResult:
    gold = _load_jsonl(Path(gold_path))
    results = _load_jsonl(Path(results_path))
    gold_by_id = {r["id"]: r for r in gold}
    res_by_id = {r["id"]: r for r in results}

    out = LoadResult()
    for gid, g in gold_by_id.items():
        if gid in res_by_id:
            out.matched.append(Pair(id=gid, gold=g, result=res_by_id[gid]))
        else:
            out.gold_only.append(g)
    for rid, r in res_by_id.items():
        if rid not in gold_by_id:
            out.results_only.append(r)
    return out
