from unittest.mock import MagicMock

import numpy as np

from app.qa.orchestrator import retrieve_and_rerank
from app.qa.prompt import build_prompt


def test_build_prompt_includes_question_and_chunks():
    prompt = build_prompt("你好？", [{"content": "hello world"}])
    assert "你好？" in prompt
    assert "hello world" in prompt


def _chunks(n: int):
    return [
        {"id": f"c{i}", "file_id": f"f{i}", "content": f"内容{i}", "vector": [float(i)] * 4}
        for i in range(n)
    ]


def test_retrieve_returns_empty_when_db_empty():
    db = MagicMock()
    db.get_completed_chunks.return_value = []
    emb = MagicMock(); emb.encode.return_value = np.zeros((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = []

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    assert result == []


def test_retrieve_filters_below_threshold():
    db = MagicMock(); db.get_completed_chunks.return_value = _chunks(3)
    emb = MagicMock(); emb.encode.return_value = np.ones((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = [0.3, 0.2, 0.1]

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    assert result == []


def test_retrieve_returns_topk_above_threshold():
    db = MagicMock(); db.get_completed_chunks.return_value = _chunks(3)
    emb = MagicMock(); emb.encode.return_value = np.ones((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = [0.9, 0.5, 0.1]

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    assert len(result) == 2
    assert result[0]["rerank_score"] >= result[1]["rerank_score"]
