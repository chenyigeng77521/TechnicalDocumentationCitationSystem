"""测试写入侧 HTTP 路由。"""
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_post_index_success(client, monkeypatch):
    async def fake_pipeline(file_path):
        return {"status": "indexed", "chunk_count": 5, "file_hash": "h"}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "a.md"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "indexed"
    assert body["chunk_count"] == 5


@pytest.mark.asyncio
async def test_post_index_file_not_found(client, monkeypatch):
    async def fake_pipeline(file_path):
        raise FileNotFoundError(file_path)

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "missing.md"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_type"] == "file_not_found"


@pytest.mark.asyncio
async def test_post_index_parse_error(client, monkeypatch):
    from backend.ingestion.common.errors import ParseError

    async def fake_pipeline(file_path):
        raise ParseError("PDF 加密")

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "a.pdf"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "parse_failed"


@pytest.mark.asyncio
async def test_delete_files(client, monkeypatch):
    async def fake_delete(file_path):
        return {"status": "deleted", "deleted_chunks": 3}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.handle_file_delete", fake_delete
    )
    resp = await client.request("DELETE", "/files", json={"file_path": "a.md"})
    assert resp.status_code == 200
    assert resp.json()["deleted_chunks"] == 3
