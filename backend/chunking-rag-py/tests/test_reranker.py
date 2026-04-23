import threading
from unittest.mock import MagicMock

from app.retriever.reranker import BgeReranker


def test_score_calls_normalize_true():
    fake = MagicMock()
    fake.compute_score.return_value = [0.9, 0.2]
    r = BgeReranker(model=fake, lock=threading.Lock())
    out = r.score("q", ["d1", "d2"])
    assert out == [0.9, 0.2]
    args, kwargs = fake.compute_score.call_args
    assert args[0] == [("q", "d1"), ("q", "d2")]
    assert kwargs["normalize"] is True


def test_score_empty_docs_returns_empty():
    fake = MagicMock()
    r = BgeReranker(model=fake, lock=threading.Lock())
    assert r.score("q", []) == []
    fake.compute_score.assert_not_called()
