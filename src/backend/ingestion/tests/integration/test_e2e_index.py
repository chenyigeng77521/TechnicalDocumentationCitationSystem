"""端到端：上传 sample 文件 → POST /index → 查 chunks → 检索。

注意：用 mock embedding 跑，不加载真实 bge-m3 模型。
"""
import shutil
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app
from backend.ingestion.db.connection import init_db


@pytest.fixture
async def e2e_client(tmp_path, monkeypatch, fixtures_dir):
    db_path = tmp_path / "knowledge.db"
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    test_domain_dir = storage_dir / "docs" / "test"
    test_domain_dir.mkdir(parents=True)

    init_db(db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.DB_PATH", db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.STORAGE_DIR", storage_dir)
    monkeypatch.setattr("backend.ingestion.api.routes_search.DB_PATH", db_path)

    sample = fixtures_dir / "sample.md"
    if sample.exists():
        shutil.copy(sample, test_domain_dir / "sample.md")
    else:
        (test_domain_dir / "sample.md").write_text(
            "# Title\n\nOAuth2 token refresh requires Authorization header.\n\n"
            "Installation guide for the system."
        )

    async def fake_embed(texts, concurrency=8):
        return [[(hash(t) % 100) / 100.0] + [0.0] * 1023 for t in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        app = create_app()
        # Patch routes_index DB_PATH symbol after app created (it imports from pipeline)
        import backend.ingestion.api.routes_index as ri
        monkeypatch.setattr(ri, "DB_PATH", db_path)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_full_flow_add_then_search(e2e_client):
    resp = await e2e_client.post("/index?add=docs/test/sample.md")
    assert resp.status_code == 200, resp.text
    item = resp.json()["results"][0]
    assert item["status"] == "indexed"
    assert item["chunk_count"] >= 1

    resp = await e2e_client.get("/stats")
    assert resp.json()["chunks"] == item["chunk_count"]

    resp = await e2e_client.post(
        "/chunks/text-search",
        json={"query": "OAuth2", "top_k": 5},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert "OAuth2" in results[0]["content"]


@pytest.mark.asyncio
async def test_unchanged_skips(e2e_client):
    await e2e_client.post("/index?add=docs/test/sample.md")
    resp = await e2e_client.post("/index?modify=docs/test/sample.md")
    assert resp.json()["results"][0]["status"] == "unchanged"


@pytest.mark.asyncio
async def test_delete_removes_chunks(e2e_client):
    await e2e_client.post("/index?add=docs/test/sample.md")
    resp = await e2e_client.post("/index?delete=docs/test/sample.md")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "deleted"
    stats = (await e2e_client.get("/stats")).json()
    assert stats["chunks"] == 0
