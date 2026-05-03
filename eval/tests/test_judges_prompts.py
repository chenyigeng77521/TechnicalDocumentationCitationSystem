import pytest
from judges.prompts import (
    render_prompt, parse_verdict, JudgeVerdict, PROMPT_VERSION, JudgeParseError
)


def test_render_prompt():
    out = render_prompt(
        question="React 增量采用？",
        gold_answer="可以增量",
        evidences=["原文1", "原文2"],
        model_answer="是的可以",
    )
    assert "React 增量采用？" in out
    assert "可以增量" in out
    assert "原文1" in out and "原文2" in out
    assert "是的可以" in out
    assert "例子 1（correct）" in out
    assert "例子 2（wrong）" in out


def test_render_no_evidence():
    out = render_prompt("q", "a", [], "m")
    assert "（无原文出处）" in out


def test_render_three_evidence():
    out = render_prompt("q", "a", ["e1", "e2", "e3"], "m")
    assert "1. e1" in out and "2. e2" in out and "3. e3" in out


def test_parse_clean_json():
    v = parse_verdict('{"verdict": "correct", "reason": "ok"}')
    assert v.verdict == "correct" and v.reason == "ok"


def test_parse_with_markdown_fence():
    v = parse_verdict('```json\n{"verdict": "wrong", "reason": "bad"}\n```')
    assert v.verdict == "wrong"


def test_parse_with_leading_text():
    v = parse_verdict('让我判一下。\n{"verdict": "correct", "reason": "fine"}')
    assert v.verdict == "correct"


def test_parse_invalid_raises():
    with pytest.raises(JudgeParseError, match="no JSON"):
        parse_verdict("just plain text no json")


def test_parse_missing_field_raises():
    with pytest.raises(JudgeParseError, match="missing"):
        parse_verdict('{"verdict": "correct"}')


def test_parse_invalid_verdict_raises():
    with pytest.raises(JudgeParseError, match="invalid verdict"):
        parse_verdict('{"verdict": "maybe", "reason": "x"}')


def test_prompt_version_constant():
    assert PROMPT_VERSION == "v1.0"
