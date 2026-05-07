"""检索侧路由：vector-search / text-search / by-id。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §4.2
"""
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.chunks_repo import (
    vector_search, text_search, get_chunk,
)
from backend.ingestion.api.x15 import (
    group_results,
    _format_result_x15,
)

X15_ENABLED = os.getenv("INGESTION_X15_ENABLED", "true").lower() == "true"

router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = PROJECT_ROOT / "src" / "backend" / "database" / "knowledge.db"


class VectorSearchRequest(BaseModel):
    embedding: list[float]
    top_k: int = 50
    filters: Optional[dict] = None


class TextSearchRequest(BaseModel):
    query: str
    top_k: int = 50
    filters: Optional[dict] = None


def _normalize_anchor(a: str | None) -> str:
    """归一化 markdown_anchor 为 '#section-id' 格式。

    chunker 偶发遗漏 # 前缀（AsciiDoc parser 已知 bug，影响 Spring 域），
    API 输出层兜底，保证下游拿到的契约永远是 '#section-id' 形式。
    chunker 修好后本函数 idempotent（已带 # 的不重复加），无副作用。

    None / 空 → "#top"
    "data-fetching" → "#data-fetching"
    "#data-fetching" → "#data-fetching"（不变）
    """
    if not a:
        return "#top"
    return a if a.startswith("#") else f"#{a}"


def _row_to_metadata(row: dict) -> dict:
    # doc_indexed_at 来自 search SQL 的 JOIN documents（vector/text-search 都带）
    # by-id 没 JOIN，没这字段时 fallback null
    last_modified = row.get("doc_indexed_at")
    if last_modified is not None:
        last_modified = str(last_modified)
    return {
        "file_path": row["file_path"],
        "anchor_id": row["anchor_id"],
        "title_path": row["title_path"],
        "char_offset_start": row["char_offset_start"],
        "char_offset_end": row["char_offset_end"],
        "is_truncated": bool(row["is_truncated"]),
        "is_x15_truncated": False,  # X1.5 max_chars 截断标记，默认 False，仅 X1.5 路径会改 True
        "content_type": row["content_type"],
        "language": row["language"],
        "last_modified": last_modified,
        "markdown_anchor": _normalize_anchor(row.get("markdown_anchor")),  # section 标识，赛题 citation 用，输出契约 '#xxx' 形式
    }


def _format_result_legacy(row: dict, include_bm25: bool = False) -> dict:
    out = {
        "chunk_id": row["chunk_id"],
        "content": row["content"],
        "score": float(row.get("score", 0.0)),
        "metadata": _row_to_metadata(row),
    }
    if include_bm25 and "bm25_rank" in row:
        out["bm25_rank"] = row["bm25_rank"]
    return out


@router.post("/chunks/vector-search")
async def post_vector_search(req: VectorSearchRequest):
    if len(req.embedding) != 1024:
        raise HTTPException(400, "embedding must be 1024-dim")
    # init_db 已在 server.create_app() 启动时跑过；请求路径不再重复调用，
    # 避免每请求 50-200ms 开销 + sqlite_master 锁竞争（云主机慢盘下导致 :3003 timeout）
    conn = get_connection(DB_PATH)
    try:
        rows = vector_search(conn, req.embedding, top_k=req.top_k)

        if not X15_ENABLED:
            return {
                "results": [_format_result_legacy(r) for r in rows],
                "total": len(rows),
            }

        # X1.5 路径：分组 → 排序 → 格式化
        groups = group_results(rows)
        # 输出顺序：按"组内最高分"降序
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: -kv[1][0].get("score", 0),
        )

        results = []
        for key, members in sorted_groups:
            title_path = members[0].get("title_path") or ""  # UNTITLED 路径自动是 ""
            metadata_x0 = _row_to_metadata(members[0])
            results.append(
                _format_result_x15(conn, members, title_path, metadata_x0)
            )

        return {"results": results, "total": len(results)}
    finally:
        conn.close()


@router.post("/chunks/text-search")
async def post_text_search(req: TextSearchRequest):
    # init_db 已在 server.create_app() 启动时跑过；请求路径不再重复调用
    conn = get_connection(DB_PATH)
    try:
        rows = text_search(conn, req.query, top_k=req.top_k)

        if not X15_ENABLED:
            return {
                "results": [_format_result_legacy(r, include_bm25=True) for r in rows],
                "total": len(rows),
            }

        groups = group_results(rows)
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: -kv[1][0].get("score", 0),
        )

        results = []
        for key, members in sorted_groups:
            title_path = members[0].get("title_path") or ""  # UNTITLED 路径自动是 ""
            metadata_x0 = _row_to_metadata(members[0])
            results.append(
                _format_result_x15(conn, members, title_path or "", metadata_x0)
            )

        return {"results": results, "total": len(results)}
    finally:
        conn.close()


@router.get("/chunks/{chunk_id}")
async def get_chunk_by_id(chunk_id: str):
    # init_db 已在 server.create_app() 启动时跑过；请求路径不再重复调用
    conn = get_connection(DB_PATH)
    try:
        row = get_chunk(conn, chunk_id)
        if row is None:
            raise HTTPException(404, f"chunk {chunk_id} not found")
        d = dict(row)
        return {
            "chunk_id": d["chunk_id"],
            "content": d["content"],
            "embedding": json.loads(d["embedding"]) if d["embedding"] else None,
            "metadata": _row_to_metadata(d),
        }
    finally:
        conn.close()
