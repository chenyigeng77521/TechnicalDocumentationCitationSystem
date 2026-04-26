"""测试 chunks 表 CRUD + 向量/全文检索。"""
from datetime import datetime, timezone
import json
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import (
    insert_chunks, delete_chunks_by_file, get_chunk,
    vector_search, text_search, count_chunks,
)


def _seed_doc(conn, file_path="a.md"):
    upsert_document(conn, file_path=file_path, file_name=file_path,
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.now(timezone.utc))


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def _make_chunk(chunk_id="c1", content="hello world", embedding=None,
                file_path="a.md", offset=0, title_path=None):
    return {
        "chunk_id": chunk_id, "file_path": file_path, "file_hash": "h",
        "index_version": "v1", "content": content,
        "anchor_id": f"{file_path}#{offset}", "title_path": title_path,
        "char_offset_start": offset, "char_offset_end": offset + len(content),
        "char_count": len(content), "chunk_index": 0,
        "is_truncated": False, "content_type": "document", "language": "zh",
        "embedding": embedding or [0.0] * 1024,
    }


def test_insert_chunks_and_get(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", "hello"), _make_chunk("c2", "world")])
    assert count_chunks(conn) == 2
    c = get_chunk(conn, "c1")
    assert c["content"] == "hello"
    assert json.loads(c["embedding"])[0] == 0.0


def test_delete_chunks_by_file(conn):
    _seed_doc(conn, "a.md")
    _seed_doc(conn, "b.md")
    insert_chunks(conn, [
        _make_chunk("c1", file_path="a.md"),
        _make_chunk("c2", file_path="b.md"),
    ])
    delete_chunks_by_file(conn, "a.md")
    assert count_chunks(conn) == 1
    assert get_chunk(conn, "c1") is None


def test_vector_search_returns_top_k_by_cosine(conn):
    _seed_doc(conn)
    e1 = [1.0] + [0.0] * 1023
    e2 = [0.5, 0.5] + [0.0] * 1022
    e3 = [0.0, 1.0] + [0.0] * 1022
    insert_chunks(conn, [
        _make_chunk("c1", "a", embedding=e1),
        _make_chunk("c2", "b", embedding=e2),
        _make_chunk("c3", "c", embedding=e3),
    ])
    query_emb = [1.0] + [0.0] * 1023
    results = vector_search(conn, query_emb, top_k=2)
    assert len(results) == 2
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["score"] > results[1]["score"]


def test_text_search_uses_fts(conn):
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk("c1", content="OAuth2 token refresh guide"),
        _make_chunk("c2", content="installation steps overview"),
    ])
    results = text_search(conn, "OAuth2", top_k=10)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "bm25_rank" in results[0]
    assert results[0]["score"] > 0


def test_text_search_returns_empty_on_no_match(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", content="hello world")])
    assert text_search(conn, "xyz_nonexistent", top_k=10) == []
