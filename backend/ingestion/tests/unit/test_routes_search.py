"""测试检索侧 HTTP 路由（被海军调）。"""
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import insert_chunks


@pytest.fixture
async def client_with_data(tmp_db_path, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr(
        "backend.ingestion.api.routes_search.DB_PATH", tmp_db_path
    )

    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="api/auth.md", file_name="auth.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1",
                    last_modified=datetime.now(timezone.utc))
    insert_chunks(conn, [{
        "chunk_id": "c1", "file_path": "api/auth.md", "file_hash": "h",
        "index_version": "v1",
        "content": "OAuth2 token refresh requires Authorization header",
        "anchor_id": "api/auth.md#0", "title_path": "Auth > OAuth2",
        "char_offset_start": 0, "char_offset_end": 50, "char_count": 50,
        "chunk_index": 0, "embedding": [1.0] + [0.0] * 1023,
    }, {
        "chunk_id": "c2", "file_path": "api/auth.md", "file_hash": "h",
        "index_version": "v1",
        "content": "Installation guide for the system",
        "anchor_id": "api/auth.md#100", "title_path": "Install",
        "char_offset_start": 100, "char_offset_end": 130, "char_count": 30,
        "chunk_index": 1, "embedding": [0.0, 1.0] + [0.0] * 1022,
    }])
    conn.close()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_vector_search_returns_top_k(client_with_data):
    resp = await client_with_data.post(
        "/chunks/vector-search",
        json={"embedding": [1.0] + [0.0] * 1023, "top_k": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    r = body["results"][0]
    assert r["chunk_id"] == "c1"
    assert r["metadata"]["file_path"] == "api/auth.md"
    assert r["metadata"]["title_path"] == "Auth > OAuth2"
    assert r["metadata"]["anchor_id"] == "api/auth.md#0"


@pytest.mark.asyncio
async def test_text_search_finds_oauth(client_with_data):
    resp = await client_with_data.post(
        "/chunks/text-search",
        json={"query": "OAuth2", "top_k": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    r = body["results"][0]
    assert r["chunk_id"] == "c1"
    assert "bm25_rank" in r


@pytest.mark.asyncio
async def test_get_chunk_by_id(client_with_data):
    resp = await client_with_data.get("/chunks/c1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_id"] == "c1"
    assert body["content"].startswith("OAuth2")
    assert len(body["embedding"]) == 1024


@pytest.mark.asyncio
async def test_get_chunk_404(client_with_data):
    resp = await client_with_data.get("/chunks/nonexistent")
    assert resp.status_code == 404
