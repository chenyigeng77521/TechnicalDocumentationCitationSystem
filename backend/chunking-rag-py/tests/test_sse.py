from app.sse import sse_event


def test_sse_event_formats_ascii():
    assert sse_event({"answer": "hi"}) == 'data: {"answer": "hi"}\n\n'


def test_sse_event_preserves_chinese():
    out = sse_event({"answer": "你好"})
    assert "你好" in out
    assert out.endswith("\n\n")
