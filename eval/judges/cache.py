"""SHA256 file-per-key cache for judge verdicts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from judges.prompts import JudgeVerdict


def compute_cache_key(question_id: str, model_answer: str, gold_answer: str,
                       judge_model: str, prompt_version: str) -> str:
    raw = "||".join([question_id, model_answer, gold_answer, judge_model, prompt_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class JudgeCache:
    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str) -> JudgeVerdict | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return JudgeVerdict(verdict=data["verdict"], reason=data["reason"])
        except (json.JSONDecodeError, KeyError):
            return None  # corrupt → treat as miss

    def put(self, key: str, verdict: JudgeVerdict) -> None:
        self._path(key).write_text(
            json.dumps({"verdict": verdict.verdict, "reason": verdict.reason}, ensure_ascii=False),
            encoding="utf-8",
        )
