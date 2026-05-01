"""测试 documents 表 CRUD。"""
from datetime import datetime, timezone
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import (
    upsert_document, get_document, delete_document,
    list_all_paths, update_status,
)


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def test_upsert_and_get(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md",
                    file_hash="hash1", file_size=100, format="md",
                    index_version="v1", last_modified=datetime(2026, 4, 25))
    doc = get_document(conn, "a.md")
    assert doc is not None
    assert doc["file_hash"] == "hash1"
    assert doc["index_status"] == "pending"


def test_upsert_overwrites(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h1",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.now(timezone.utc))
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h2",
                    file_size=20, format="md", index_version="v1",
                    last_modified=datetime.now(timezone.utc))
    doc = get_document(conn, "a.md")
    assert doc["file_hash"] == "h2"
    assert doc["file_size"] == 20


def test_get_returns_none_when_missing(conn):
    assert get_document(conn, "nope.md") is None


def test_update_status(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.now(timezone.utc))
    update_status(conn, "a.md", index_status="indexed",
                  chunk_count=5, indexed_at=datetime.now(timezone.utc))
    doc = get_document(conn, "a.md")
    assert doc["index_status"] == "indexed"
    assert doc["chunk_count"] == 5


def test_delete_document(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.now(timezone.utc))
    delete_document(conn, "a.md")
    assert get_document(conn, "a.md") is None


def test_list_all_paths(conn):
    for p in ["a.md", "b.md", "sub/c.md"]:
        upsert_document(conn, file_path=p, file_name=p.split("/")[-1],
                        file_hash="h", file_size=10, format="md",
                        index_version="v1", last_modified=datetime.now(timezone.utc))
    paths = list_all_paths(conn)
    assert set(paths) == {"a.md", "b.md", "sub/c.md"}
