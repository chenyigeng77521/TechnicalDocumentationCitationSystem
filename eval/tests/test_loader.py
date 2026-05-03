from pathlib import Path
import pytest
from loader import load_pair, LoadResult

FIXTURES = Path(__file__).parent / "fixtures"


def test_perfect_match():
    result = load_pair(
        gold_path=FIXTURES / "sample_gold_10.jsonl",
        results_path=FIXTURES / "sample_results_10.jsonl",
    )
    assert isinstance(result, LoadResult)
    assert len(result.matched) == 10
    assert result.gold_only == []
    assert result.results_only == []
    react_001 = next(p for p in result.matched if p.id == "react_001")
    assert react_001.gold["question"].startswith("React Compiler")
    assert react_001.result["is_refusal"] is False


def test_empty_files(tmp_path):
    gp = tmp_path / "g.jsonl"; gp.write_text("")
    rp = tmp_path / "r.jsonl"; rp.write_text("")
    result = load_pair(gp, rp)
    assert result.matched == [] and result.gold_only == [] and result.results_only == []


def test_single_record(tmp_path):
    gp = tmp_path / "g.jsonl"; gp.write_text('{"id":"x1","question":"q"}\n')
    rp = tmp_path / "r.jsonl"; rp.write_text('{"id":"x1","answer":"a"}\n')
    assert len(load_pair(gp, rp).matched) == 1


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pair(tmp_path / "nope", tmp_path / "nope")


def test_invalid_jsonl_raises(tmp_path):
    bad = tmp_path / "bad.jsonl"; bad.write_text("not json\n")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_pair(bad, bad)


def test_partial_match(tmp_path):
    gp = tmp_path / "g.jsonl"; gp.write_text('{"id":"a"}\n{"id":"b"}\n')
    rp = tmp_path / "r.jsonl"; rp.write_text('{"id":"b"}\n{"id":"c"}\n')
    result = load_pair(gp, rp)
    assert {p.id for p in result.matched} == {"b"}
    assert [g["id"] for g in result.gold_only] == ["a"]
    assert [r["id"] for r in result.results_only] == ["c"]
