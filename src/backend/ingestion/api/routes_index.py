"""写入侧路由：POST /index, GET /stats, /health。

增量索引协议（统一在 /index 路径，query param 区分操作）：
- POST /index?add=docs/<domain>/<file>      新增文件（已存在且 hash 未变会返 unchanged）
- POST /index?modify=docs/<domain>/<file>   更新文件（按 file_hash 自动判断 indexed/replaced/unchanged）
- POST /index?delete=docs/<domain>/<file>   删除文件的所有 chunks（含 documents 行）

file_path 形式：相对 STORAGE_DIR 的路径，必含 docs/<domain>/ 前缀，例：docs/react/foo.md

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §4.1
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.ingestion.common.errors import (
    IngestionError, ParseError, EmbeddingError, DBError,
    UnsupportedFormatError,
)
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import count_documents
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import (
    index_pipeline, handle_file_delete, DB_PATH,
)

router = APIRouter()


@router.post("/index")
async def post_index(
    add: Optional[str] = Query(None, description="新增文件 file_path（如 docs/react/foo.md）"),
    modify: Optional[str] = Query(None, description="更新文件 file_path"),
    delete: Optional[str] = Query(None, description="删除文件 file_path"),
):
    """三选一：add / modify / delete。互斥。"""
    provided = [(k, v) for k, v in [("add", add), ("modify", modify), ("delete", delete)] if v]
    if len(provided) != 1:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error_type": "invalid_params",
                "detail": "必须且只能提供 add / modify / delete 三个 query param 中的一个",
            },
        )
    op, file_path = provided[0]

    try:
        if op == "delete":
            return await handle_file_delete(file_path)
        # add / modify 走同一条 index_pipeline，内部按 file_hash 自动判断 indexed/replaced/unchanged
        return await index_pipeline(file_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "error_type": "file_not_found",
                    "detail": file_path},
        )
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except ParseError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except (EmbeddingError, DBError) as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except IngestionError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.get("/stats")
async def get_stats():
    init_db(DB_PATH)
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
    init_db(DB_PATH)
    return {
        "status": "ok",
        "db_writable": DB_PATH.exists(),
        "embedding_model_loaded": False,
    }
