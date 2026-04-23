import threading
from unittest.mock import MagicMock

import numpy as np

from app.embedder.bge_m3 import BgeM3Embedder


def test_encode_returns_dense_vecs_only():
    fake_model = MagicMock()
    fake_model.encode.return_value = {
        "dense_vecs": np.zeros((2, 1024), dtype=np.float32),
        "lexical_weights": None,
        "colbert_vecs": None,
    }
    emb = BgeM3Embedder(model=fake_model, lock=threading.Lock())
    vecs = emb.encode(["hello", "world"])
    assert vecs.shape == (2, 1024)
    fake_model.encode.assert_called_once_with(
        ["hello", "world"],
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )


def test_encode_acquires_lock():
    fake_model = MagicMock()
    fake_model.encode.return_value = {"dense_vecs": np.zeros((1, 1024))}
    lock = threading.Lock()

    lock.acquire()
    emb = BgeM3Embedder(model=fake_model, lock=lock)

    done = threading.Event()

    def call():
        emb.encode(["x"])
        done.set()

    t = threading.Thread(target=call)
    t.start()
    assert not done.wait(0.2)
    lock.release()
    assert done.wait(1.0)
    t.join()
