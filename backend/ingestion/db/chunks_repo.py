"""chunks 表 CRUD + 向量/全文检索。"""
import json
import math
import sqlite3
import unicodedata
from typing import Optional

import jieba

# jieba.setLogLevel + initialize 已在 connection.py 模块加载时调用，这里不重复


def insert_chunks(conn: sqlite3.Connection, chunks: list[dict]) -> None:
    if not chunks:
        return
    rows = []
    for c in chunks:
        rows.append((
            c["chunk_id"], c["file_path"], c["file_hash"], c["index_version"],
            c["content"], c["anchor_id"], c.get("title_path"),
            c["char_offset_start"], c["char_offset_end"], c["char_count"],
            c["chunk_index"], int(c.get("is_truncated", False)),
            c.get("content_type", "document"), c.get("language"),
            json.dumps(c.get("embedding")) if c.get("embedding") is not None else None,
        ))
    conn.executemany(
        """
        INSERT OR REPLACE INTO chunks (
            chunk_id, file_path, file_hash, index_version, content, anchor_id,
            title_path, char_offset_start, char_offset_end, char_count,
            chunk_index, is_truncated, content_type, language, embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def delete_chunks_by_file(conn: sqlite3.Connection, file_path: str) -> int:
    cur = conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
    conn.commit()
    return cur.rowcount


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()


def count_chunks(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM chunks").fetchone()[0]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def vector_search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int = 50,
) -> list[dict]:
    """全表 cosine 排序（MVP，~10k chunks 100ms）。

    JOIN documents 取 indexed_at 作为 last_modified（给评委验证 5min SLA 用）。
    """
    rows = conn.execute(
        """
        SELECT c.*, d.indexed_at AS doc_indexed_at
        FROM chunks c
        JOIN documents d ON c.file_path = d.file_path
        WHERE c.embedding IS NOT NULL
        """
    ).fetchall()
    scored = []
    for r in rows:
        emb = json.loads(r["embedding"])
        score = _cosine_similarity(query_embedding, emb)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, r in scored[:top_k]:
        results.append({**dict(r), "score": float(score)})
    return results


def _is_meaningful_token(token: str) -> bool:
    """spec §6.4 AC3 单一规则：token 至少含一个字母/数字字符（unicode L/N category）。

    过滤掉纯标点、纯空白、emoji 等无检索意义的 token。
    """
    return any(unicodedata.category(c)[0] in 'LN' for c in token)


def _escape_fts_phrase(token: str) -> str:
    """FTS5 phrase 转义：内部 " → ""，整体包 "..."。

    被 phrase 包起来的 token 不会被 FTS5 识别成 boolean keyword (AND/OR/NEAR/NOT)
    或 reserved 字符，保证任意输入都是合法 FTS5 query。
    """
    return '"' + token.replace('"', '""') + '"'


def _build_fts_query(text: str) -> str:
    """用户原始 query → FTS5 OR 查询字符串。

    spec §3.2：jieba 切词 → _is_meaningful_token 过滤 → _escape_fts_phrase 包装 → OR 拼接。
    返回空字符串表示无有效 token，调用方应据此短路返 []。
    """
    tokens = [t for t in jieba.cut(text) if _is_meaningful_token(t)]
    return ' OR '.join(_escape_fts_phrase(t) for t in tokens) if tokens else ''


def text_search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 50,
) -> list[dict]:
    """FTS5 BM25。query 是用户原始字符串，内部走 jieba 切词 + sanitize。

    spec §3.2 + §6.4 AC4：函数签名不变，海军接口 100% 兼容。
    返回含 score (归一化) + bm25_rank (FTS5 原始) + doc_indexed_at。
    """
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []  # 空 / 全标点 query 直接返空，不打 FTS5（防 syntax error）
    rows = conn.execute(
        """
        SELECT c.*, fts.rank AS bm25_rank, d.indexed_at AS doc_indexed_at
        FROM chunks_fts fts
        JOIN chunks c ON c.chunk_id = fts.chunk_id
        JOIN documents d ON c.file_path = d.file_path
        WHERE chunks_fts MATCH ?
        ORDER BY fts.rank
        LIMIT ?
        """,
        (fts_query, top_k),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        rank = d["bm25_rank"]
        d["score"] = 1.0 / (1.0 + abs(rank))
        results.append(d)
    return results
