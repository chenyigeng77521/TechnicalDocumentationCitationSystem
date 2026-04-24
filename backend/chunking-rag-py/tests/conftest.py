import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """Isolated storage/db per test. Clears Settings cache so env vars apply."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "k.db"))
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("CONVERTED_DIR", str(tmp_path / "converted"))
    monkeypatch.setenv("MAPPINGS_DIR", str(tmp_path / "mappings"))
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake")
    monkeypatch.setenv("LLM_MODEL", "fake-model")

    from app import deps
    deps.get_settings.cache_clear()
    from app.config import Settings
    from app.database.sqlite import init_db
    s = Settings()
    s.ensure_dirs()
    init_db(s.resolve_path(s.db_path))
    return s


@pytest.fixture
def fake_embedder():
    m = MagicMock()
    m.encode = MagicMock(side_effect=lambda texts: np.ones((len(texts), 1024), dtype=np.float32))
    return m


@pytest.fixture
def fake_reranker():
    m = MagicMock()
    m.score = MagicMock(side_effect=lambda q, docs: [0.9] * len(docs))
    return m


@pytest.fixture
def fake_llm():
    m = MagicMock()

    async def stream_answer(prompt):
        for t in ["答案", "片段", "。"]:
            yield t

    m.stream_answer = stream_answer
    return m


@pytest.fixture
def app(tmp_settings, fake_embedder, fake_reranker, fake_llm):
    """FastAPI app with mocked models (skips real lifespan model loading)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="chunking-rag-py-test")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.state.settings = tmp_settings
    app.state.embedder = fake_embedder
    app.state.reranker = fake_reranker
    app.state.llm = fake_llm
    app.state.model_lock = threading.Lock()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    from app.routes import qa as qa_route
    from app.routes import qa_stream as qa_stream_route
    from app.routes import upload as upload_route
    app.include_router(upload_route.router)
    app.include_router(qa_route.router)
    app.include_router(qa_stream_route.router)
    return app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
