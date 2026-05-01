"""集成测试：text_search 端到端行为

spec §3.2 + §5 T6/T7/T8/T9
"""
import pytest
from pathlib import Path

from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, text_search


@pytest.fixture
def empty_db(tmp_path):
    """全新 DB，无任何 chunk。"""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path


def _insert_doc_and_chunk(conn, file_path, chunk_id, content):
    """测试辅助：插一个 document + 一个 chunk。"""
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES (?, ?, 'h', 1, 'md', 'v1', '2026-04-28')
    """, (file_path, Path(file_path).name))
    insert_chunks(conn, [{
        "chunk_id": chunk_id,
        "file_path": file_path,
        "file_hash": "h",
        "index_version": "v1",
        "content": content,
        "anchor_id": "a",
        "char_offset_start": 0,
        "char_offset_end": len(content),
        "char_count": len(content),
        "chunk_index": 0,
    }])


def test_search_empty_query_returns_empty(empty_db):
    """T8: 空 / 全标点 query → text_search 返 []，不打 FTS5。"""
    conn = get_connection(empty_db)
    try:
        assert text_search(conn, "") == []
        assert text_search(conn, "   ") == []
        assert text_search(conn, "...") == []
        assert text_search(conn, "！？。") == []
    finally:
        conn.close()


def test_search_finds_chinese_chunk(empty_db):
    """T6 / spec §2.2: 中文 query "数据治理" 应命中含此词的 chunk 并排首。"""
    conn = get_connection(empty_db)
    try:
        _insert_doc_and_chunk(conn, "/cmpak.md", "c1",
                              "Cmpak 数据治理架构与体系建设")
        _insert_doc_and_chunk(conn, "/oracle.md", "c2",
                              "Oracle SQL 高性能优化技术")

        results = text_search(conn, "数据治理", top_k=10)
        assert len(results) >= 1, "应至少召回 1 条（含'数据'+'治理'两词的 chunk）"
        # 含"数据"+"治理"两词的 chunk 应排首（BM25 累加加分）
        assert results[0]["chunk_id"] == "c1", \
            f"top-1 应是含数据治理的 chunk，实际: {results[0]['chunk_id']}"
    finally:
        conn.close()


def test_search_finds_long_english_query(empty_db):
    """T7 / spec §2.2 / 修 #1: 长英文 query 不再 0 召回，含 F5 DNS 的 chunk 排首。"""
    conn = get_connection(empty_db)
    try:
        _insert_doc_and_chunk(conn, "/f5.md", "c1",
                              "F5 DNS configuration for high availability deployment")
        _insert_doc_and_chunk(conn, "/k8s.md", "c2",
                              "Kubernetes coredns and kube-dns service setup")

        long_query = "How to configure F5 DNS for high availability"
        results = text_search(conn, long_query, top_k=10)
        assert len(results) >= 1, \
            "长英文 query 不应 0 召回（修复前 trigram 会 0 召回）"
        # 同时命中 F5 + DNS + configure + high + availability 的 chunk 应排首
        assert results[0]["chunk_id"] == "c1", \
            f"top-1 应是 F5 DNS 文档，实际: {results[0]['chunk_id']}"
    finally:
        conn.close()


def test_search_returns_empty_when_no_words_match(empty_db):
    """T9 / spec §2.2: 库里没相关词的 query → text_search 返 []。

    这是 #3 brainstorm 选 H 路径的关键证据：BM25 在数据缺失时
    老实返空，不像 vector-search 强行返 top_k 噪音。
    """
    conn = get_connection(empty_db)
    try:
        _insert_doc_and_chunk(conn, "/oracle.md", "c1",
                              "Oracle SQL Hints documentation 高性能 SQL 优化")

        # 这些词在库里完全不出现
        results = text_search(conn, "如何提高召回率", top_k=10)
        assert results == [], \
            f"库里无此主题应返空，实际: {[r['chunk_id'] for r in results]}"
    finally:
        conn.close()
