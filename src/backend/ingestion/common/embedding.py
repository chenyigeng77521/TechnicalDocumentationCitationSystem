"""Embedding 包装器（走统一 AI 网关）。

历史：先前是本地加载 SentenceTransformer("BAAI/bge-m3") (~2GB)。
迁移至移动云统一 AI 网关后，无本地模型依赖，HTTP POST 调用。

接口签名保持不变（batch_embed / embed_single），调用方零感知。

环境变量：
- AIGW_API_KEY：必须
- AIGW_BASE_URL：默认 https://aigw.asiainfo.com/v1
- AIGW_EMBEDDING_MODEL：默认 10086/bge-m3

normalize：网关返回已 normalize（实测 norm=1.0），客户端不再做。
dim：1024（bge-m3 标准），与 DB 索引一致。
"""
import asyncio
import os
from typing import Optional

import httpx

EMBEDDING_DIM = 1024
BATCH_SIZE = 8
DEFAULT_BASE_URL = "https://aigw.asiainfo.com/v1"
DEFAULT_MODEL = "10086/bge-m3"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 2  # 失败重试 2 次（共 3 次尝试）


def _get_config() -> tuple[str, str, str]:
    """读环境变量。首次调用时检查 API key 必须设置。"""
    api_key = os.getenv("AIGW_API_KEY")
    if not api_key:
        raise RuntimeError(
            "AIGW_API_KEY 未设置。请在 src/.env 或 shell 中设置。"
            " start.sh 启动时会自动 source src/.env。"
        )
    base_url = os.getenv("AIGW_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("AIGW_EMBEDDING_MODEL", DEFAULT_MODEL)
    return api_key, base_url, model


async def _post_embeddings(
    client: httpx.AsyncClient,
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
) -> list[list[float]]:
    """单次 POST /v1/embeddings 调用，含指数退避重试。

    成功返回按输入顺序排好的 embedding 列表（按 response.data[*].index 排序）。
    """
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = await client.post(
                f"{base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json={"model": model, "input": texts},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            # 按 index 排序保证跟输入对齐（OpenAI 标准允许乱序）
            items = sorted(data["data"], key=lambda x: x["index"])
            embeddings = [item["embedding"] for item in items]

            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"网关返回 {len(embeddings)} 个 embedding，期望 {len(texts)}"
                )
            return embeddings
        except (httpx.HTTPError, httpx.TimeoutException, RuntimeError, KeyError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                # 指数退避：1s / 2s
                await asyncio.sleep(2 ** attempt)
            continue
    # 所有重试都失败
    raise RuntimeError(f"AIGW embedding 重试 {MAX_RETRIES + 1} 次仍失败: {last_err}") from last_err


_local_model = None


def _get_local_model():
    """懒加载本地 SentenceTransformer（仅 EMBEDDING_USE_LOCAL=1 时调用）。"""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _local_model = SentenceTransformer("BAAI/bge-m3")
    return _local_model


async def _local_batch_embed(texts: list[str]) -> list[list[float]]:
    """本地 SentenceTransformer 跑 embedding，绕开 AIGW（offline / VPN 不通时用）。"""
    model = _get_local_model()
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(
        None,
        lambda: model.encode(texts, normalize_embeddings=True).tolist(),
    )
    return embeddings


async def batch_embed(texts: list[str], concurrency: int = 8) -> list[list[float]]:
    """批量 embedding。保持 SentenceTransformer 时代的接口签名。

    Args:
        texts: 文本列表
        concurrency: 并发请求数（每个请求最多 BATCH_SIZE 条文本）

    Returns:
        embedding 列表，跟输入顺序对应，每个是 1024-d float list（normalized）

    环境变量：
    - EMBEDDING_USE_LOCAL=1：用本地 SentenceTransformer，绕开 AIGW（首次加载 ~2GB 内存）
    """
    if not texts:
        return []

    if os.getenv("EMBEDDING_USE_LOCAL") == "1":
        return await _local_batch_embed(texts)

    api_key, base_url, model = _get_config()
    sem = asyncio.Semaphore(concurrency)
    batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]

    async with httpx.AsyncClient() as client:
        async def _embed_batch(batch_texts: list[str]) -> list[list[float]]:
            async with sem:
                return await _post_embeddings(client, batch_texts, api_key, base_url, model)

        results = await asyncio.gather(*[_embed_batch(b) for b in batches])

    return [vec for batch in results for vec in batch]


async def embed_single(text: str) -> list[float]:
    return (await batch_embed([text]))[0]
