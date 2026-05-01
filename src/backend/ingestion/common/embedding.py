"""bge-m3 embedding 包装器。

normalize_embeddings=True，与海军端约定一致。
"""
import asyncio

EMBEDDING_DIM = 1024
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 8

_MODEL = None


def get_model():
    """懒加载 bge-m3。首次 ~10s（下载/加载到内存 ~2GB）。"""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


async def batch_embed(texts: list[str], concurrency: int = 8) -> list[list[float]]:
    if not texts:
        return []
    model = get_model()
    sem = asyncio.Semaphore(concurrency)

    async def _embed_batch(batch_texts: list[str]) -> list[list[float]]:
        async with sem:
            vecs = await asyncio.to_thread(
                model.encode,
                batch_texts,
                normalize_embeddings=True,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
            )
            return [v.tolist() for v in vecs]

    batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    results = await asyncio.gather(*[_embed_batch(b) for b in batches])
    return [vec for batch in results for vec in batch]


async def embed_single(text: str) -> list[float]:
    return (await batch_embed([text]))[0]
