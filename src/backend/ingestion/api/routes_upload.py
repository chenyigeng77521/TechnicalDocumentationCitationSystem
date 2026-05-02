"""POST /upload 端点（联调用，受 INGESTION_UPLOAD_ENABLED 开关控制）。

Spec: docs/superpowers/specs/2026-04-27-upload-endpoint-design.md
"""
import os
import re
import time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.ingestion.sync.pipeline import index_pipeline

MAX_FILENAME_LEN = 255
ILLEGAL_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')

ALLOWED_EXTS = {".docx", ".pdf", ".xlsx", ".pptx", ".md", ".txt"}
MAX_FILES = 50
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# 上传专用目录（默认项目根 data/docs/）。比赛阶段不会上传新文件，
# 但路由保留供后续使用。文件直接落到该目录根下（不分 domain 子目录），
# 由用户事后整理到具体 domain。测试用环境变量覆盖。
DOCS_UPLOAD_DIR = Path(os.getenv(
    "INGESTION_DOCS_UPLOAD_DIR",
    str(Path(__file__).resolve().parents[4] / "data" / "docs"),
))


class PathTraversalError(ValueError):
    """文件名含路径穿越字符——安全级，应触发请求级 400 拒绝整批。"""


class InvalidFilenameError(ValueError):
    """文件名其它问题（空 / 长度 / 编码）——单文件级，应返 status=error 但其它继续。"""


def sanitize_filename(filename: str) -> str:
    """两层错误分类清理。优先级：安全级（PathTraversalError）→ 单文件级（InvalidFilenameError）→ 清理"""
    # 安全级最先（决定 PathTraversalError）
    if ".." in filename or "/" in filename or "\\" in filename:
        raise PathTraversalError(f"path traversal not allowed: {filename}")
    # 单文件级
    if not filename or not filename.strip():
        raise InvalidFilenameError("filename is empty")
    if len(filename) > MAX_FILENAME_LEN:
        raise InvalidFilenameError(f"filename too long ({len(filename)} > {MAX_FILENAME_LEN})")
    # 清理（不抛错）
    cleaned = ILLEGAL_CHARS_RE.sub("_", filename)
    return cleaned


router = APIRouter()


@router.post("/upload")
async def post_upload(
    files: list[UploadFile] = File(...),
    index: bool = False,
):
    if not files:
        raise HTTPException(status_code=400, detail="no_files_provided")
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too_many_files: {len(files)} > {MAX_FILES}",
        )

    # 请求级安全检查（路径穿越 → 整批 400）
    for f in files:
        try:
            sanitize_filename(f.filename or "")
        except PathTraversalError:
            raise HTTPException(status_code=400, detail="path_traversal_detected")
        except InvalidFilenameError:
            pass  # 单文件级先放过，下面 for 循环再处理

    # ===== 阶段 1：上传落地 =====
    DOCS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for f in files:
        original_name = f.filename or ""
        try:
            safe_name = sanitize_filename(original_name)
        except InvalidFilenameError as e:
            uploaded.append({
                "filename": original_name,
                "status": "error",
                "error_type": "invalid_filename",
                "detail": str(e),
            })
            continue

        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            uploaded.append({
                "filename": safe_name,
                "status": "error",
                "error_type": "unsupported_format",
                "detail": f"扩展名 {ext} 不在白名单",
            })
            continue

        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            uploaded.append({
                "filename": safe_name,
                "status": "error",
                "error_type": "oversized",
                "detail": f"size {len(content)} > {MAX_FILE_SIZE}",
            })
            continue

        target = DOCS_UPLOAD_DIR / safe_name
        target.write_bytes(content)
        uploaded.append({
            "filename": safe_name,
            "size": len(content),
            "status": "saved",
        })

    response = {"success": True, "uploaded": uploaded}

    # ===== 阶段 2：可选索引（仅当 ?index=true）=====
    if index:
        indexed = []
        for u in uploaded:
            if u["status"] != "saved":
                continue  # 单文件级失败的不索引
            t0 = time.time()
            # pipeline 入参是相对 STORAGE_DIR 的路径，上传文件落在 docs/ 根，
            # 故 file_path = "docs/<basename>"
            rel_path = f"docs/{u['filename']}"
            try:
                result = await index_pipeline(rel_path)
                indexed.append({
                    "filename": u["filename"],
                    "chunks": result.get("chunk_count", 0),
                    "elapsed_s": round(time.time() - t0, 2),
                })
            except Exception as e:
                indexed.append({
                    "filename": u["filename"],
                    "status": "error",
                    "error_type": type(e).__name__,
                    "detail": str(e),
                })
        response["indexed"] = indexed

    return response
