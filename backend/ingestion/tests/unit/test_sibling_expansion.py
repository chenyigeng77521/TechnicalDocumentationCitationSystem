"""Task 8: vector_search 同章节邻居救援。

主匹配 chunk 触发 sibling expansion：把同 (file_path, title_path) 且
chunk_index 相邻 (±2) 的兄弟也带进 top-K，让 LLM 看到的引用是完整一节。
"""
from datetime import datetime, timezone
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import insert_chunks, vector_search
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


def _make_chunk(chunk_id, content, embedding, chunk_index, title_path=None,
                file_path="a.md"):
    offset = chunk_index * 100
    return {
        "chunk_id": chunk_id, "file_path": file_path, "file_hash": "h",
        "index_version": "v1", "content": content,
        "anchor_id": f"{file_path}#{offset}", "title_path": title_path,
        "char_offset_start": offset, "char_offset_end": offset + len(content),
        "char_count": len(content), "chunk_index": chunk_index,
        "is_truncated": False, "content_type": "document", "language": "zh",
        "embedding": embedding,
    }


def _query_emb_aligned_with(emb):
    return list(emb)


def test_siblings_pulled_in_when_primary_matches(conn):
    """主匹配 #2 触发 → 同节兄弟 #1 #3 一起出现在 top-K。

    关键：#1 和 #3 自己的 cosine 很低（embedding 跟 query 距离远），
    本来不会进 top-3，但因为是 #2 的兄弟被拉进来。
    """
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    far_emb = [0.0] + [1.0] + [0.0] * 1022  # cosine = 0
    insert_chunks(conn, [
        _make_chunk("c1", "section content 1 long enough", far_emb, 1,
                    title_path="API 发起驱逐的工作原理"),
        _make_chunk("c2", "section content 2 - matches query", primary_emb, 2,
                    title_path="API 发起驱逐的工作原理"),
        _make_chunk("c3", "section content 3 long enough", far_emb, 3,
                    title_path="API 发起驱逐的工作原理"),
        # 远处的不相关 chunk，cosine 高于 c1/c3 但低于 c2
        _make_chunk("c_far", "unrelated chunk content here longer than 50",
                    [0.7, 0.7] + [0.0] * 1022, 100,
                    title_path="另一节标题"),
    ])
    results = vector_search(conn, _query_emb_aligned_with(primary_emb), top_k=3)
    chunk_ids = [r["chunk_id"] for r in results]
    # 主匹配 c2 必在；兄弟 c1 c3 也应被拉进 top-3
    assert "c2" in chunk_ids, f"主匹配 c2 必须在结果里，实际: {chunk_ids}"
    assert "c1" in chunk_ids and "c3" in chunk_ids, \
        f"兄弟 c1/c3 应被拉入 top-3，实际: {chunk_ids}"
    assert len(results) == 3, f"返回数应 ≤ top_k=3，实际 {len(results)}"


def test_null_title_path_does_not_expand(conn):
    """主匹配 chunk title_path=NULL 时不展开，不报错。"""
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    insert_chunks(conn, [
        _make_chunk("c1", "no title path content here long enough", primary_emb,
                    1, title_path=None),
        _make_chunk("c2", "another no-title content here long enough",
                    [0.0, 1.0] + [0.0] * 1022, 2, title_path=None),
    ])
    results = vector_search(conn, _query_emb_aligned_with(primary_emb), top_k=10)
    # 不报错；c1 仍在结果里
    assert results[0]["chunk_id"] == "c1"


def test_sibling_chunk_index_within_2(conn):
    """chunk_index 跨度 > ±2 的 chunk 不算 sibling，不被展开。"""
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    far_emb = [0.0] + [1.0] + [0.0] * 1022
    insert_chunks(conn, [
        # 主匹配在 chunk_index=10
        _make_chunk("primary", "primary chunk content here long enough",
                    primary_emb, 10, title_path="同一节"),
        # 邻居 chunk_index=11（在 ±2 内）→ 应被展开
        _make_chunk("near", "near sibling chunk content here long enough",
                    far_emb, 11, title_path="同一节"),
        # 远 chunk_index=15（超出 ±2）→ 不应被展开
        _make_chunk("far", "far same-section content here long enough",
                    far_emb, 15, title_path="同一节"),
    ])
    results = vector_search(conn, _query_emb_aligned_with(primary_emb), top_k=2)
    chunk_ids = [r["chunk_id"] for r in results]
    assert "primary" in chunk_ids
    assert "near" in chunk_ids, f"邻近兄弟 near 应展开，实际: {chunk_ids}"
    assert "far" not in chunk_ids, f"远 chunk far 不应展开，实际: {chunk_ids}"


def test_top_k_hard_cap(conn):
    """sibling 展开后总数不超过 top_k。"""
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    far_emb = [0.0] + [1.0] + [0.0] * 1022
    chunks = [
        _make_chunk(f"c{i}", f"content chunk number {i} here long enough",
                    primary_emb if i == 5 else far_emb, i, title_path="同一节")
        for i in range(10)
    ]
    insert_chunks(conn, chunks)
    results = vector_search(conn, _query_emb_aligned_with(primary_emb), top_k=3)
    assert len(results) == 3, f"返回数 = top_k=3，实际 {len(results)}"


def test_expand_siblings_false_disables(conn):
    """expand_siblings=False 时回退到原版纯 cosine 行为。"""
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    insert_chunks(conn, [
        _make_chunk("c1", "section content 1 here long enough",
                    [0.0, 1.0] + [0.0] * 1022, 1, title_path="同一节"),
        _make_chunk("c2", "section content 2 matches here long enough",
                    primary_emb, 2, title_path="同一节"),
        _make_chunk("c3", "section content 3 here long enough",
                    [0.0, 1.0] + [0.0] * 1022, 3, title_path="同一节"),
    ])
    results = vector_search(
        conn, _query_emb_aligned_with(primary_emb),
        top_k=1, expand_siblings=False,
    )
    # expand_siblings=False 时 top-1 仅 c2，不展开
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c2"


def test_solo_chunk_in_section_no_error(conn):
    """主匹配独占一节（无兄弟）也不报错。"""
    _seed_doc(conn)
    primary_emb = [1.0] + [0.0] * 1023
    insert_chunks(conn, [
        _make_chunk("solo", "solo chunk in its own section, no siblings here",
                    primary_emb, 1, title_path="独占节"),
    ])
    results = vector_search(conn, _query_emb_aligned_with(primary_emb), top_k=5)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "solo"
