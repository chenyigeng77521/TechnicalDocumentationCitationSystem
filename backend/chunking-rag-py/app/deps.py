import sqlite3
import threading
from functools import lru_cache
from typing import Iterator

from fastapi import Depends, Request

from app.config import Settings
from app.database.sqlite import Db
from app.embedder.bge_m3 import BgeM3Embedder
from app.llm.client import LlmClient
from app.retriever.reranker import BgeReranker


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[Db]:
    conn = sqlite3.connect(
        settings.resolve_path(settings.db_path),
        isolation_level=None,
    )
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield Db(conn)
    finally:
        conn.close()


def get_embedder(request: Request) -> BgeM3Embedder:
    return request.app.state.embedder


def get_reranker(request: Request) -> BgeReranker:
    return request.app.state.reranker


def get_model_lock(request: Request) -> threading.Lock:
    return request.app.state.model_lock


def get_llm(request: Request) -> LlmClient:
    return request.app.state.llm
