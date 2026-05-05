"""测试写入侧 HTTP 路由（批量并发 /index 协议）。"""
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
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_post_index_add_basename_auto_prefix(client, monkeypatch):
    """add 传 basename 时自动加 documents/ 前缀传给 pipeline，返回单元素 list。"""
    captured = []

    async def fake_pipeline(file_path):
        captured.append(file_path)
        return {"status": "indexed", "chunk_count": 5, "file_hash": "h"}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index?add=foo.md")
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert len(body["results"]) == 1
    assert body["results"][0]["status"] == "indexed"
    assert body["results"][0]["op"] == "add"
    assert body["results"][0]["file_path"] == "documents/foo.md"
    assert captured == ["documents/foo.md"]


@pytest.mark.asyncio
async def test_post_index_add_full_path_unchanged(client, monkeypatch):
    """add 传完整路径（含 /）时不重复加前缀。"""
    async def fake_pipeline(file_path):
        return {"status": "indexed", "chunk_count": 3}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index?add=docs/react/y.md")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["file_path"] == "docs/react/y.md"


@pytest.mark.asyncio
async def test_post_index_modify(client, monkeypatch):
    captured = []

    async def fake_pipeline(file_path):
        captured.append(file_path)
        return {"status": "replaced", "chunk_count": 7}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index?modify=a.md")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "replaced"
    assert captured == ["documents/a.md"]


@pytest.mark.asyncio
async def test_post_index_delete(client, monkeypatch):
    async def fake_delete(file_path):
        return {"status": "deleted", "deleted_chunks": 3}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.handle_file_delete", fake_delete
    )
    resp = await client.post("/index?delete=docs/react/x.md")
    assert resp.status_code == 200
    assert resp.json()["results"][0]["deleted_chunks"] == 3
    assert resp.json()["results"][0]["op"] == "delete"


@pytest.mark.asyncio
async def test_post_index_no_param_400(client):
    """没传任何 add/modify/delete 应该 400。"""
    resp = await client.post("/index")
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "invalid_params"


@pytest.mark.asyncio
async def test_post_index_query_multi_files(client, monkeypatch):
    """query param 形式多文件 ?add=a&add=b，期望 results 是 2 个元素。"""
    captured = []

    async def fake_pipeline(file_path):
        captured.append(file_path)
        return {"status": "indexed", "chunk_count": 1}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index?add=a.md&add=b.md")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2
    file_paths = sorted(r["file_path"] for r in body["results"])
    assert file_paths == ["documents/a.md", "documents/b.md"]


@pytest.mark.asyncio
async def test_post_index_body_form(client, monkeypatch):
    """JSON body 形式 {add: [...], modify: [...], delete: [...]}。"""
    pipeline_called = []
    delete_called = []

    async def fake_pipeline(file_path):
        pipeline_called.append(file_path)
        return {"status": "indexed", "chunk_count": 1}

    async def fake_delete(file_path):
        delete_called.append(file_path)
        return {"status": "deleted", "deleted_chunks": 1}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.handle_file_delete", fake_delete
    )

    resp = await client.post("/index", json={
        "add": ["a.md", "b.md"],
        "modify": ["c.md"],
        "delete": ["docs/old/x.md"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 4

    # 检查每个 op 对应文件路径
    ops_files = {(r["op"], r["file_path"]) for r in body["results"]}
    assert ops_files == {
        ("add", "documents/a.md"),
        ("add", "documents/b.md"),
        ("modify", "documents/c.md"),
        ("delete", "docs/old/x.md"),
    }


@pytest.mark.asyncio
async def test_post_index_query_body_merge(client, monkeypatch):
    """query 和 body 合并：?add=q.md + body {add: [b1.md]} → 期望 2 个 add。"""
    async def fake_pipeline(file_path):
        return {"status": "indexed", "chunk_count": 1}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index?add=q.md", json={"add": ["b1.md"]})
    assert resp.status_code == 200
    file_paths = sorted(r["file_path"] for r in resp.json()["results"])
    assert file_paths == ["documents/b1.md", "documents/q.md"]


@pytest.mark.asyncio
async def test_post_index_one_failure_doesnt_break_rest(client, monkeypatch):
    """单条失败不打断其他文件，整体仍 200，失败条目带 error_type。"""
    async def fake_pipeline(file_path):
        if "bad" in file_path:
            raise FileNotFoundError(file_path)
        return {"status": "indexed", "chunk_count": 1}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"add": ["good.md", "bad.md", "good2.md"]})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 3
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["error", "indexed", "indexed"]
    failed = [r for r in results if r["status"] == "error"]
    assert failed[0]["error_type"] == "file_not_found"


@pytest.mark.asyncio
async def test_post_index_parse_error_per_item(client, monkeypatch):
    """ParseError 也按单条返回 error，不打断整体。"""
    from backend.ingestion.common.errors import ParseError

    async def fake_pipeline(file_path):
        if "pdf" in file_path:
            raise ParseError("PDF 加密")
        return {"status": "indexed", "chunk_count": 1}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"add": ["ok.md", "bad.pdf"]})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert any(r["status"] == "error" and r.get("error_type") == "parse_failed"
               for r in results)
    assert any(r["status"] == "indexed" for r in results)
