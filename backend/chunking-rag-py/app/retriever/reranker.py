import threading


class BgeReranker:
    def __init__(self, model, lock: threading.Lock):
        self._model = model
        self._lock = lock

    @classmethod
    def load(cls, model_name: str, lock: threading.Lock) -> "BgeReranker":
        from FlagEmbedding import FlagReranker
        model = FlagReranker(model_name, use_fp16=True)
        return cls(model=model, lock=lock)

    def score(self, question: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        pairs = [(question, d) for d in docs]
        with self._lock:
            raw = self._model.compute_score(pairs, normalize=True)
        if isinstance(raw, (int, float)):
            return [float(raw)]
        return [float(x) for x in raw]
