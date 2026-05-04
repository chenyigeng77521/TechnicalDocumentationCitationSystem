"""写入侧路由：POST /index, GET /stats, /health。

增量索引协议（统一在 /index 路径，query param 区分操作）：
- POST /index?add=<basename>                新增文件（前端只传 basename，自动加 documents/ 前缀）
- POST /index?modify=<basename>             更新文件（同 add，basename 自动加 documents/ 前缀）
- POST /index?delete=<file_path>            删除文件的所有 chunks（必须传完整路径，避免歧义）

物理目录约定：
- 评委已有 164 文件 → data/docs/<domain>/...（DB 里 file_path = docs/<domain>/...）
- 前端上传新文件 → data/documents/...（DB 里 file_path = documents/...）

add/modify 路径规范化：
- 传 basename "foo.md"          → 自动加前缀 "documents/foo.md" → 物理找 data/documents/foo.md
- 传 "documents/foo.md"          → 不重复加前缀，物理找 data/documents/foo.md
- 传 "docs/react/foo.md"         → 完整路径不动，物理找 data/docs/react/foo.md（评委文件 reindex 用）

delete 必须传完整路径（不会自动加前缀，避免误删 docs/<domain>/foo.md）

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


def _normalize_add_modify_path(file_path: str) -> str:
    """add/modify 路径规范化：basename 自动加 documents/ 前缀。

    规则：
    - 不含 / 视为 basename，加 'documents/' 前缀（约定上传文件物理位置在 data/documents/）
    - 已含 / 不动，让前端自己决定（兼容 reindex 评委 docs/<domain>/foo.md 文件）
    """
    if "/" not in file_path:
        return f"documents/{file_path}"
    return file_path


@router.post("/index")
async def post_index(
    add: Optional[str] = Query(None, description="新增文件 basename（如 foo.md，自动加 documents/ 前缀）"),
    modify: Optional[str] = Query(None, description="更新文件 basename（同 add 规则）"),
    delete: Optional[str] = Query(None, description="删除文件完整 file_path（如 documents/foo.md 或 docs/react/x.md）"),
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
    op, raw_path = provided[0]

    try:
        if op == "delete":
            # delete 必须传完整路径（避免 documents/foo.md 和 docs/react/foo.md 撞同名误删）
            return await handle_file_delete(raw_path)
        # add / modify：basename 自动加 documents/ 前缀；完整路径不动
        file_path = _normalize_add_modify_path(raw_path)
        return await index_pipeline(file_path)
    except FileNotFoundError:
        # 报告原始入参 + 实际找的路径，方便前端排错（basename 被加了 documents/ 前缀）
        actual = raw_path if op == "delete" else _normalize_add_modify_path(raw_path)
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "error_type": "file_not_found",
                    "detail": f"raw={raw_path}, resolved={actual}"},
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
