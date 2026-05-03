from judges.cache import compute_cache_key, JudgeCache
from judges.prompts import JudgeVerdict


def test_cache_roundtrip(tmp_path):
    cache = JudgeCache(tmp_path)
    cache.put("abc", JudgeVerdict("correct", "ok"))
    got = cache.get("abc")
    assert got and got.verdict == "correct" and got.reason == "ok"


def test_cache_creates_dir(tmp_path):
    sub = tmp_path / "nested" / "cache"
    JudgeCache(sub)
    assert sub.exists()


def test_corrupt_cache_treated_as_miss(tmp_path):
    cache = JudgeCache(tmp_path)
    (tmp_path / "bad.json").write_text("not valid json")
    assert cache.get("bad") is None


def test_multiple_keys(tmp_path):
    cache = JudgeCache(tmp_path)
    cache.put("k1", JudgeVerdict("correct", "r1"))
    cache.put("k2", JudgeVerdict("wrong", "r2"))
    assert cache.get("k1").verdict == "correct"
    assert cache.get("k2").verdict == "wrong"


def test_different_answer_misses():
    k1 = compute_cache_key("q1", "answer A", "gold", "model", "v1")
    k2 = compute_cache_key("q1", "answer B", "gold", "model", "v1")
    assert k1 != k2


def test_prompt_version_invalidates():
    k1 = compute_cache_key("q1", "ans", "gold", "model", "v1.0")
    k2 = compute_cache_key("q1", "ans", "gold", "model", "v2.0")
    assert k1 != k2
