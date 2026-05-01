"""POST /upload 端点测试。

Spec: docs/superpowers/specs/2026-04-27-upload-endpoint-design.md
"""
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.ingestion.api.routes_upload import (
    sanitize_filename, PathTraversalError, InvalidFilenameError,
)


def test_sanitize_normal_filename():
    assert sanitize_filename("kubernetes部署.docx") == "kubernetes部署.docx"
    assert sanitize_filename("foo.pdf") == "foo.pdf"


def test_sanitize_path_traversal_raises_specific():
    for bad in ["../../etc/passwd", "foo/../../bar.docx", "/absolute/path", "evil\\path.docx"]:
        with pytest.raises(PathTraversalError):
            sanitize_filename(bad)


def test_sanitize_empty_raises_invalid():
    for bad in ["", "   ", "\t\n"]:
        with pytest.raises(InvalidFilenameError):
            sanitize_filename(bad)


def test_sanitize_max_length():
    long_name = "a" * 250 + ".docx"  # 255 chars
    assert sanitize_filename(long_name) == long_name

    with pytest.raises(InvalidFilenameError, match="too long"):
        sanitize_filename("a" * 256 + ".docx")


def test_sanitize_illegal_chars_replaced():
    assert sanitize_filename('foo<bar>baz?.docx') == 'foo_bar_baz_.docx'
    assert sanitize_filename('a|b*c.pdf') == 'a_b_c.pdf'


# ============= Task 1.2: POST /upload 阶段 1 =============


@pytest.fixture
def app(tmp_path, monkeypatch):
    """每个测试用独立的 storage/raw/"""
    monkeypatch.setenv("INGESTION_RAW_DIR", str(tmp_path))
    from backend.ingestion.api import routes_upload
    from importlib import reload
    reload(routes_upload)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(routes_upload.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_single_file_upload(client, tmp_path):
    files = [("files", ("kubernetes.docx", b"fake docx", "application/octet-stream"))]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "indexed" not in data
    assert len(data["uploaded"]) == 1
    assert data["uploaded"][0]["filename"] == "kubernetes.docx"
    assert data["uploaded"][0]["status"] == "saved"
    assert (tmp_path / "kubernetes.docx").read_bytes() == b"fake docx"


def test_multi_file_upload(client, tmp_path):
    files = [
        ("files", ("a.docx", b"x", "application/octet-stream")),
        ("files", ("b.pdf", b"y", "application/octet-stream")),
        ("files", ("c.xlsx", b"z", "application/octet-stream")),
    ]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["uploaded"]) == 3
    assert all(u["status"] == "saved" for u in resp.json()["uploaded"])
    for name in ["a.docx", "b.pdf", "c.xlsx"]:
        assert (tmp_path / name).exists()


def test_no_files_returns_422(client):
    resp = client.post("/upload", files=[])
    assert resp.status_code == 422


def test_unsupported_format(client, tmp_path):
    files = [
        ("files", ("evil.exe", b"binary", "application/octet-stream")),
        ("files", ("good.docx", b"content", "application/octet-stream")),
    ]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["uploaded"][0]["status"] == "error"
    assert data["uploaded"][0]["error_type"] == "unsupported_format"
    assert data["uploaded"][1]["status"] == "saved"
    assert not (tmp_path / "evil.exe").exists()
    assert (tmp_path / "good.docx").exists()


def test_path_traversal_returns_400(client, tmp_path):
    files = [("files", ("../etc/passwd", b"x", "application/octet-stream"))]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 400
    assert "path_traversal" in resp.json()["detail"]
    assert not (tmp_path / "passwd").exists()


def test_traversal_with_valid_files_all_rejected(client, tmp_path):
    files = [
        ("files", ("legit.docx", b"x", "application/octet-stream")),
        ("files", ("../evil", b"y", "application/octet-stream")),
    ]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 400
    assert not (tmp_path / "legit.docx").exists()


def test_all_files_invalid_no_security(client, tmp_path):
    files = [
        ("files", (f"f{i}.exe", b"x", "application/octet-stream")) for i in range(3)
    ]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert all(u["status"] == "error" for u in data["uploaded"])
    assert all(u["error_type"] == "unsupported_format" for u in data["uploaded"])


def test_duplicate_safe_name_overwrite(client, tmp_path):
    files = [
        ("files", ("dup.docx", b"first content", "application/octet-stream")),
        ("files", ("dup.docx", b"second longer content", "application/octet-stream")),
    ]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["uploaded"]) == 2
    assert all(u["status"] == "saved" for u in data["uploaded"])
    assert data["uploaded"][0]["size"] == len(b"first content")
    assert data["uploaded"][1]["size"] == len(b"second longer content")
    assert (tmp_path / "dup.docx").read_bytes() == b"second longer content"


# ============= Task 1.3: server.py 开关 + start.sh =============


def test_endpoint_disabled(monkeypatch):
    monkeypatch.delenv("INGESTION_UPLOAD_ENABLED", raising=False)
    from backend.ingestion.api import server
    from importlib import reload
    reload(server)

    client = TestClient(server.app)
    resp = client.post("/upload", files=[("files", ("a.docx", b"x"))])
    assert resp.status_code == 404


def test_endpoint_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("INGESTION_UPLOAD_ENABLED", "true")
    monkeypatch.setenv("INGESTION_RAW_DIR", str(tmp_path))

    from backend.ingestion.api import server, routes_upload
    from importlib import reload
    reload(routes_upload)
    reload(server)

    client = TestClient(server.app)
    resp = client.post("/upload", files=[("files", ("a.docx", b"x"))])
    assert resp.status_code == 200


# ============= Task 1.4: ?index=true 阶段 2 =============


def test_upload_with_index(client, tmp_path, monkeypatch):
    """mock index_pipeline 避免真跑（依赖 bge-m3 加载慢）"""
    from backend.ingestion.api import routes_upload

    fake_calls = []

    async def fake_pipeline(file_path):
        fake_calls.append(file_path)
        return {"status": "indexed", "chunk_count": 7, "file_hash": "abc"}

    monkeypatch.setattr(routes_upload, "index_pipeline", fake_pipeline)

    files = [("files", ("test.docx", b"content", "application/octet-stream"))]
    resp = client.post("/upload?index=true", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "indexed" in data
    assert len(data["indexed"]) == 1
    assert data["indexed"][0]["chunks"] == 7
    assert "test.docx" in fake_calls


def test_index_fail_upload_succeeds(client, tmp_path, monkeypatch):
    from backend.ingestion.api import routes_upload

    async def fake_fail(file_path):
        raise RuntimeError("simulated index failure")

    monkeypatch.setattr(routes_upload, "index_pipeline", fake_fail)

    files = [("files", ("a.docx", b"x", "application/octet-stream"))]
    resp = client.post("/upload?index=true", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["uploaded"][0]["status"] == "saved"   # 阶段 1 OK
    assert data["indexed"][0]["status"] == "error"    # 阶段 2 失败
    assert "simulated" in data["indexed"][0]["detail"]
    assert (tmp_path / "a.docx").exists()  # 磁盘文件不删


# ============= Task 2.1: 50MB / 10 文件 限制 =============

MAX_FILE_SIZE = 50 * 1024 * 1024


def test_50mb_boundary(client, tmp_path):
    big = b"a" * MAX_FILE_SIZE
    files = [("files", ("big.docx", big, "application/octet-stream"))]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    assert resp.json()["uploaded"][0]["status"] == "saved"


def test_oversized_rejected(client, tmp_path):
    too_big = b"a" * (MAX_FILE_SIZE + 1)
    files = [("files", ("big.docx", too_big, "application/octet-stream"))]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200  # 单文件级，不是请求级
    u = resp.json()["uploaded"][0]
    assert u["status"] == "error"
    assert u["error_type"] == "oversized"
    assert not (tmp_path / "big.docx").exists()


def test_50_files_boundary(client, tmp_path):
    files = [("files", (f"f{i}.docx", b"x", "application/octet-stream")) for i in range(50)]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["uploaded"]) == 50


def test_51_files_rejected(client):
    files = [("files", (f"f{i}.docx", b"x", "application/octet-stream")) for i in range(51)]
    resp = client.post("/upload", files=files)
    assert resp.status_code == 400
    assert "too_many_files" in resp.json()["detail"]
