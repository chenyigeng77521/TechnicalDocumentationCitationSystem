"""检索侧路由：vector-search / text-search / by-id。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §4.2
"""
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.chunks_repo import (
    vector_search, text_search, get_chunk,
)

router = APIRouter()
DB_PATH = Path("backend/storage/index/knowledge.db")


class VectorSearchRequest(BaseModel):
    embedding: list[float]
    top_k: int = 50
    filters: Optional[dict] = None


class TextSearchRequest(BaseModel):
    query: str
    top_k: int = 50
    filters: Optional[dict] = None


def _row_to_metadata(row: dict) -> dict:
    return {
        "file_path": row["file_path"],
        "anchor_id": row["anchor_id"],
        "title_path": row["title_path"],
        "char_offset_start": row["char_offset_start"],
        "char_offset_end": row["char_offset_end"],
        "is_truncated": bool(row["is_truncated"]),
        "content_type": row["content_type"],
        "language": row["language"],
        "last_modified": None,
    }


def _format_result(row: dict, include_bm25: bool = False) -> dict:
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
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        results = vector_search(conn, req.embedding, top_k=req.top_k)
        return {
            "results": [_format_result(r) for r in results],
            "total": len(results),
        }
    finally:
        conn.close()


@router.post("/chunks/text-search")
async def post_text_search(req: TextSearchRequest):
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        results = text_search(conn, req.query, top_k=req.top_k)
        return {
            "results": [_format_result(r, include_bm25=True) for r in results],
            "total": len(results),
        }
    finally:
        conn.close()


@router.get("/chunks/{chunk_id}")
async def get_chunk_by_id(chunk_id: str):
    init_db(DB_PATH)
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
