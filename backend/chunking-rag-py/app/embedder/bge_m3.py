import threading

import numpy as np


class BgeM3Embedder:
    """bge-m3 dense-only 封装。所有 encode 调用在 model_lock 内串行化（spec R7）。"""

    def __init__(self, model, lock: threading.Lock):
        self._model = model
        self._lock = lock

    @classmethod
    def load(cls, model_name: str, lock: threading.Lock) -> "BgeM3Embedder":
        from FlagEmbedding import BGEM3FlagModel
        model = BGEM3FlagModel(model_name, use_fp16=True)
        return cls(model=model, lock=lock)

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            out = self._model.encode(
                texts,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        return np.asarray(out["dense_vecs"], dtype=np.float32)
