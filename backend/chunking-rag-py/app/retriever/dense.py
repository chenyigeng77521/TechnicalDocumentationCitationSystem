import numpy as np


def dense_search(
    q_vec: np.ndarray, chunks: list[dict], k: int = 20
) -> list[tuple[dict, float]]:
    """余弦相似度 top-k。chunks 里 vector=None 的跳过。"""
    valid = [c for c in chunks if c.get("vector") is not None]
    if not valid:
        return []
    mat = np.asarray([c["vector"] for c in valid], dtype=np.float32)
    q = q_vec.astype(np.float32)
    q_norm = np.linalg.norm(q) or 1.0
    mat_norm = np.linalg.norm(mat, axis=1)
    mat_norm[mat_norm == 0] = 1.0
    scores = (mat @ q) / (mat_norm * q_norm)
    idx = np.argsort(-scores)[:k]
    return [(valid[i], float(scores[i])) for i in idx]
