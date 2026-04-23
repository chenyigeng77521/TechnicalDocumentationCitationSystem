import numpy as np

from app.retriever.dense import dense_search


def test_dense_top_k_descending():
    q = np.array([1.0, 0.0], dtype=np.float32)
    chunks = [
        {"id": "1", "vector": [1.0, 0.0]},
        {"id": "2", "vector": [0.0, 1.0]},
        {"id": "3", "vector": [0.7, 0.7]},
    ]
    out = dense_search(q, chunks, k=3)
    ids = [c["id"] for c, _ in out]
    assert ids[0] == "1"
    assert out[0][1] >= out[1][1] >= out[2][1]


def test_dense_skips_chunks_without_vector():
    q = np.array([1.0, 0.0], dtype=np.float32)
    chunks = [
        {"id": "1", "vector": [1.0, 0.0]},
        {"id": "2", "vector": None},
    ]
    out = dense_search(q, chunks, k=5)
    assert [c["id"] for c, _ in out] == ["1"]
