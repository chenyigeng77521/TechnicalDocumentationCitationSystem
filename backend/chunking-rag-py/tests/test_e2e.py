"""End-to-end contract + robustness tests via FastAPI TestClient.

Covers the 6 frontend endpoints with mocked embedder/reranker/llm, plus
CORS, upload limits, failure recovery, concurrent upload, empty-DB refusal,
SSE framing, and delete path traversal.
"""
import json
import sqlite3
import threading


SAMPLE_MD_BYTES = b"# Intro\n\n\xe6\xa0\x87\xe9\xa2\x98 content body\xe3\x80\x82"


# ===== CONTRACT SHAPE =====

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_stats_shape(client):
    data = client.get("/qa/stats").json()
    assert set(data) >= {"success", "totalFiles", "stats"}
    assert isinstance(data["totalFiles"], int)
    assert set(data["stats"]) >= {"fileCount", "chunkCount", "indexedCount"}


def test_raw_files_shape_empty(client):
    data = client.get("/upload/raw-files?page=1&limit=10").json()
    assert {"success", "files", "total", "page", "limit", "totalPages"} <= set(data)
    assert data["total"] == 0


def test_files_shape_empty(client):
    data = client.get("/qa/files").json()
    assert {"success", "files", "total"} <= set(data)
    assert data["total"] == 0


def test_upload_happy_path(client):
    r = client.post("/upload", files={"files": ("sample.md", SAMPLE_MD_BYTES, "text/markdown")})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert len(data["files"]) == 1
    assert data["files"][0]["originalName"] == "sample.md"
    assert data["files"][0]["status"] == "completed"
    assert "message" in data


def test_files_list_after_upload(client):
    client.post("/upload", files={"files": ("sample.md", SAMPLE_MD_BYTES, "text/markdown")})
    data = client.get("/qa/files").json()
    assert data["total"] == 1
    f = data["files"][0]
    assert {"name", "size", "mtime", "id", "format", "uploadTime", "category"} <= set(f)
    assert f["name"] == "sample.md"


def test_raw_files_after_upload(client):
    client.post("/upload", files={"files": ("sample.md", SAMPLE_MD_BYTES, "text/markdown")})
    data = client.get("/upload/raw-files").json()
    assert data["total"] == 1
    entry = data["files"][0]
    assert {"name", "path", "size", "createdAt", "modifiedAt"} <= set(entry)


# ===== ASK-STREAM SSE =====

def _collect_sse_events(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            try:
                events.append(json.loads(block[len("data: "):]))
            except json.JSONDecodeError:
                pass
    return events


def test_ask_stream_with_chunks(client):
    client.post("/upload", files={"files": ("sample.md", SAMPLE_MD_BYTES, "text/markdown")})
    with client.stream("POST", "/qa/ask-stream", json={"question": "content"}) as r:
        body = "".join(r.iter_text())
    events = _collect_sse_events(body)
    answers = [e["answer"] for e in events if "answer" in e]
    sources_events = [e["sources"] for e in events if "sources" in e]
    assert answers == ["答案", "片段", "。"]
    assert sources_events == [["sample.md"]]


def test_ask_stream_empty_db_refusal(client):
    with client.stream("POST", "/qa/ask-stream", json={"question": "any"}) as r:
        body = "".join(r.iter_text())
    events = _collect_sse_events(body)
    assert any("未找到" in e.get("answer", "") for e in events)
    assert {"sources": []} in events


def test_ask_stream_empty_question(client):
    with client.stream("POST", "/qa/ask-stream", json={"question": ""}) as r:
        body = "".join(r.iter_text())
    events = _collect_sse_events(body)
    assert any("不能为空" in e.get("answer", "") for e in events)


def test_empty_db_does_not_call_reranker(client, fake_reranker):
    with client.stream("POST", "/qa/ask-stream", json={"question": "q"}) as r:
        _ = "".join(r.iter_text())
    fake_reranker.score.assert_not_called()


# ===== DELETE =====

def test_delete_cascade(client, tmp_settings):
    client.post("/upload", files={"files": ("sample.md", SAMPLE_MD_BYTES, "text/markdown")})
    assert client.get("/qa/files").json()["total"] == 1

    r = client.delete("/qa/files/sample.md")
    assert r.status_code == 200 and r.json()["success"] is True
    assert client.get("/qa/files").json()["total"] == 0
    assert not (tmp_settings.resolve_path(tmp_settings.raw_dir) / "sample.md").exists()


def test_delete_path_traversal_rejected(client):
    r = client.delete("/qa/files/..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_delete_nonexistent_returns_404(client):
    r = client.delete("/qa/files/no_such_file.md")
    assert r.status_code == 404


# ===== LIMITS =====

def test_upload_rejects_more_than_10_files(client):
    files = [("files", (f"a{i}.md", b"x", "text/markdown")) for i in range(11)]
    r = client.post("/upload", files=files)
    assert r.status_code == 413


def test_upload_unsupported_ext_returns_failed_entry(client):
    r = client.post("/upload", files={"files": ("a.xyz", b"data", "application/octet-stream")})
    data = r.json()
    assert data["success"] is True
    assert data["files"][0]["status"] == "failed"
    assert "unsupported" in data["files"][0]["error"]


def test_upload_rejects_over_50mb(client):
    big = b"x" * (50 * 1024 * 1024 + 1)
    r = client.post("/upload", files={"files": ("big.md", big, "text/markdown")})
    assert r.status_code == 413


# ===== FAILURE STATE MACHINE =====

def test_parser_failure_leaves_status_failed(client, tmp_settings, monkeypatch):
    from app.routes import upload as upload_mod

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(upload_mod, "parse", boom)
    r = client.post("/upload", files={"files": ("a.md", SAMPLE_MD_BYTES, "text/markdown")})
    data = r.json()
    assert data["files"][0]["status"] == "failed"
    assert "boom" in data["files"][0]["error"]

    # raw 文件保留
    assert (tmp_settings.resolve_path(tmp_settings.raw_dir) / "a.md").exists()

    # DB 记录 status='failed'
    c = sqlite3.connect(tmp_settings.resolve_path(tmp_settings.db_path))
    status = c.execute("SELECT status FROM files").fetchone()[0]
    c.close()
    assert status == "failed"


def test_embedder_failure_leaves_failed(client, fake_embedder):
    fake_embedder.encode.side_effect = RuntimeError("cuda oom")
    r = client.post("/upload", files={"files": ("a.md", SAMPLE_MD_BYTES, "text/markdown")})
    data = r.json()
    assert data["files"][0]["status"] == "failed"


# ===== CONCURRENT UPLOAD =====

def test_concurrent_same_name_upload_produces_dedupe_suffixes(client):
    results: list[str] = []
    lock = threading.Lock()

    def upload():
        r = client.post("/upload", files={"files": ("same.md", SAMPLE_MD_BYTES, "text/markdown")})
        with lock:
            results.append(r.json()["files"][0]["originalName"])

    threads = [threading.Thread(target=upload) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["same.md", "same_1.md", "same_2.md"]


# ===== CORS =====

def test_cors_preflight_allows_origin(client):
    r = client.options("/qa/stats", headers={
        "Origin": "http://any.example.com",
        "Access-Control-Request-Method": "GET",
    })
    # 允许 200 / 204 —— FastAPI CORSMiddleware 返回 200
    assert r.status_code in (200, 204)
    acao = r.headers.get("access-control-allow-origin")
    assert acao == "*" or acao == "http://any.example.com"


def test_cors_get_with_origin_succeeds(client):
    r = client.get("/qa/stats", headers={"Origin": "http://anywhere"})
    assert r.status_code == 200
