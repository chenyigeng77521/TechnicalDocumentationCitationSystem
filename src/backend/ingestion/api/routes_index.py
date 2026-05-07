"""写入侧路由：POST /index, GET /stats, /health。

增量索引接口（批量 + 并发，永远返回 list）：

入参支持 3 种（query param / body / 混合，自动合并）：

  # query 形式（多 add 累加成 list）
  POST /index?add=a.md&add=b.md&modify=c.md&delete=docs/old/x.md

  # JSON body 形式
  POST /index
  Content-Type: application/json
  {"add": ["a.md", "b.md"], "modify": ["c.md"], "delete": ["docs/old/x.md"]}

  # 混合（query + body 合并）
  POST /index?add=a.md
  {"add": ["b.md"]}
  → 实际处理 add=[a.md, b.md]

物理目录约定：
- 评委已有 164 文件 → data/docs/<domain>/...（DB 里 file_path = docs/<domain>/...）
- 前端上传新文件 → data/documents/...（DB 里 file_path = documents/...）

add/modify 路径规范化：
- basename "foo.md"          → "documents/foo.md"（自动加前缀）
- "documents/foo.md"          → 不动
- "docs/react/foo.md"         → 不动（评委文件 reindex 用）

delete 必须传完整路径，不会自动加前缀（避免误删 docs/ 下文件）

并发控制：默认 4，可通过 INGESTION_INDEX_MAX_CONCURRENT env 调
错误处理：单条失败不打断整体，结果里带 error_type，整体 200

返回格式（永远 list，即使单文件）：
{
  "results": [
    {"file_path": "documents/a.md", "op": "add", "status": "indexed", "chunk_count": 5, ...},
    {"file_path": "documents/b.md", "op": "modify", "status": "unchanged"},
    {"file_path": "docs/old.md", "op": "delete", "status": "deleted", "deleted_chunks": 3},
    {"file_path": "documents/x.md", "op": "add", "status": "error",
     "error_type": "file_not_found", "detail": "raw=x.md"}
  ]
}

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §4.1
"""
import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from backend.ingestion.common.errors import (
    IngestionError, ParseError, EmbeddingError, DBError,
    UnsupportedFormatError,
)
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.documents_repo import count_documents
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import (
    index_pipeline, handle_file_delete, DB_PATH,
)

router = APIRouter()

# 并发处理数（多文件批量时同时跑几个）。默认 4，可通过 env 调
MAX_CONCURRENT = int(os.getenv("INGESTION_INDEX_MAX_CONCURRENT", "4"))


def _normalize_add_modify_path(file_path: str) -> str:
    """add/modify 路径规范化：basename 自动加 documents/ 前缀。

    规则：
    - 不含 / 视为 basename，加 'documents/' 前缀（约定上传文件在 data/documents/）
    - 已含 / 不动，让前端自己决定（兼容评委 docs/<domain>/foo.md 文件 reindex）
    """
    if "/" not in file_path:
        return f"documents/{file_path}"
    return file_path


class IndexBody(BaseModel):
    """JSON body 形式的批量索引请求。三个字段都是 list[str]，可任意组合。"""
    add: list[str] = []
    modify: list[str] = []
    delete: list[str] = []


async def _process_one(op: str, raw_path: str) -> dict:
    """处理单个文件的单个操作（add/modify/delete）。永不抛异常，结果带 error_type。"""
    base = {"file_path": raw_path, "op": op}
    try:
        if op == "delete":
            # delete 不规范化，必须传完整路径（避免 documents/foo.md 和 docs/react/foo.md 撞同名误删）
            result = await handle_file_delete(raw_path)
            return {**base, **result}

        # add / modify：basename 自动加 documents/ 前缀
        file_path = _normalize_add_modify_path(raw_path)
        result = await index_pipeline(file_path)
        return {"file_path": file_path, "op": op, **result}

    except FileNotFoundError:
        actual = raw_path if op == "delete" else _normalize_add_modify_path(raw_path)
        return {
            **base, "file_path": actual,
            "status": "error", "error_type": "file_not_found",
            "detail": f"raw={raw_path}, resolved={actual}",
        }
    except UnsupportedFormatError as e:
        return {**base, "status": "error", **e.to_dict()}
    except ParseError as e:
        return {**base, "status": "error", **e.to_dict()}
    except (EmbeddingError, DBError, IngestionError) as e:
        return {**base, "status": "error", **e.to_dict()}


@router.post("/index")
async def post_index(
    add: list[str] = Query(default_factory=list, description="新增文件列表（query param 形式）"),
    modify: list[str] = Query(default_factory=list, description="更新文件列表"),
    delete: list[str] = Query(default_factory=list, description="删除文件列表（必须完整路径）"),
    body: Optional[IndexBody] = Body(default=None),
):
    """批量增量索引。query param 和 body 两种入参合并处理，永远返回 list。"""
    # 合并 query 和 body 的入参
    all_add = list(add) + (body.add if body else [])
    all_modify = list(modify) + (body.modify if body else [])
    all_delete = list(delete) + (body.delete if body else [])

    operations: list[tuple[str, str]] = []
    operations.extend([("add", fp) for fp in all_add])
    operations.extend([("modify", fp) for fp in all_modify])
    operations.extend([("delete", fp) for fp in all_delete])

    if not operations:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error_type": "invalid_params",
                "detail": "必须提供至少一个 add/modify/delete（query param 或 body）",
            },
        )

    # 并发处理（信号量控制）
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _bounded(op: str, fp: str) -> dict:
        async with sem:
            return await _process_one(op, fp)

    results = await asyncio.gather(*[_bounded(op, fp) for op, fp in operations])
    return {"results": results}


@router.get("/stats")
async def get_stats():
    # init_db 已在 server.create_app() 启动时跑过；请求路径不再重复调用
    conn = get_connection(DB_PATH)
    try:
        size_mb = (DB_PATH.stat().st_size / 1024 / 1024) if DB_PATH.exists() else 0
        return {
            "documents": count_documents(conn),
            "chunks": count_chunks(conn),
            "index_size_mb": round(size_mb, 2),
        }
    finally:
        conn.close()


@router.get("/health")
async def get_health():
    # init_db 已在 server.create_app() 启动时跑过；请求路径不再重复调用
    return {
        "status": "ok",
        "db_writable": DB_PATH.exists(),
        "embedding_model_loaded": False,
    }
