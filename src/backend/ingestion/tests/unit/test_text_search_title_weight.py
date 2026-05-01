"""Task 5: BM25 给 title_path 列加权（5x content）。

Chunk A: 查询词在 content（'授权'）→ 旧逻辑下分高
Chunk B: 查询词只在 title_path（标题里有'授权'）→ 加权后应该排第 1
"""
from datetime import datetime, timezone
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import (
    insert_chunks, text_search,
)
from backend.ingestion.db.documents_repo import upsert_document


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def _seed_doc(conn, fp="a.md"):
    upsert_document(
        conn, file_path=fp, file_name=fp, file_hash="h", file_size=10,
        format="md", index_version="v1", last_modified=datetime.now(timezone.utc),
    )


def _make_chunk(chunk_id, content, title_path=None, file_path="a.md", offset=0):
    return {
        "chunk_id": chunk_id, "file_path": file_path, "file_hash": "h",
        "index_version": "v1", "content": content,
        "anchor_id": f"{file_path}#{offset}", "title_path": title_path,
        "char_offset_start": offset, "char_offset_end": offset + len(content),
        "char_count": len(content), "chunk_index": 0,
        "is_truncated": False, "content_type": "document", "language": "zh",
        "embedding": [0.0] * 1024,
    }


def test_title_match_outranks_high_tf_content_match(conn):
    """title_path 含查询词的 chunk 应该比 content 高 TF 命中的排名更高（加权后）。

    设计（让 default 排序 A 排前，加权后 B 排前）：
    - chunk_A: content 含'授权' 5 次（TF 高）+ title 没'授权'
    - chunk_B: content 没'授权'（4 个其他长 token 占位避免 chunk 太短）+ title 含'授权' 1 次

    BM25 默认（content/title 同权重）：A 因 TF 高排第 1
    加权后（title 5x）：B 因 title 5x 加权压过 A 的 5x TF 排第 1
    """
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk(
            "A",
            content="授权 授权 授权 授权 授权 文档 内容 在 这里",
            title_path="安装 与 部署 流程",
        ),
        _make_chunk(
            "B",
            content="其他 不相关 文档 内容 占位 避免 chunk 太短",
            title_path="授权 流程 介绍",
        ),
    ])
    results = text_search(conn, "授权", top_k=10)
    assert len(results) == 2, f"应该返回 2 条，实得 {len(results)}: {results}"
    assert results[0]["chunk_id"] == "B", \
        f"加权后 title-match chunk B 应排第 1，实际排序: {[r['chunk_id'] for r in results]}"
    assert results[1]["chunk_id"] == "A"


def test_title_and_content_both_match_ranks_first(conn):
    """同时命中 title 和 content 的 chunk 应该排在只命中 content 的前面。"""
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk("A", content="授权 在内容里", title_path="安装"),
        _make_chunk("B", content="授权 在内容里也有", title_path="OAuth2 授权码"),
    ])
    results = text_search(conn, "授权", top_k=10)
    assert len(results) == 2
    assert results[0]["chunk_id"] == "B", \
        f"title+content 双命中的 B 应排第 1，实际: {[r['chunk_id'] for r in results]}"


def test_title_path_null_does_not_break(conn):
    """title_path=None 的 chunk 仍能被检索（不报错）。"""
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk("A", content="测试 关键词 在 content 里", title_path=None),
    ])
    results = text_search(conn, "关键词", top_k=10)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "A"
