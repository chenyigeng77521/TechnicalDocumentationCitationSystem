# -*- coding: utf-8 -*-
"""
文件上传路由 - 处理前端文件上传
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import shutil
import os
from pathlib import Path

router = APIRouter(prefix="/api/upload", tags=["文件上传"])

# 上传目录
UPLOAD_DIR = Path("/Users/chenyigeng/Library/Application Support/winclaw/.openclaw/workspace/TechnicalDocumentationCitationSystem/backend/storage/raw")

# 支持的文件类型
SUPPORTED_EXTENSIONS = {'.docx', '.xlsx', '.pptx', '.pdf', '.md', '.txt', '.html', '.htm'}


class UploadResponse(BaseModel):
    """上传响应"""
    success: bool
    message: str
    files: Optional[List[str]] = None
    error: Optional[str] = None


@router.post("", response_model=UploadResponse, summary="文件上传")
async def upload_files(
    files: List[UploadFile] = File(...),
):
    """
    上传文件到服务器
    
    支持的文件类型：
    - .docx (Word 文档)
    - .xlsx (Excel 表格)
    - .pptx (PowerPoint 演示文稿)
    - .pdf (PDF 文档)
    - .md (Markdown 文件)
    - .txt (文本文件)
    - .html/.htm (HTML 文件)
    
    **示例请求**：
    ```bash
    curl -X POST "http://localhost:3004/api/upload" \
      -F "files=@document.docx" \
      -F "files=@spreadsheet.xlsx"
    ```
    """
    try:
        # 确保上传目录存在
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        uploaded_files = []
        errors = []
        
        for file in files:
            # 检查文件扩展名
            file_ext = Path(file.filename).suffix.lower() if file.filename else ''
            
            # 调试日志
            print("=" * 60)
            print(f"📁 [upload] 文件检查")
            print(f"   文件名：{file.filename}")
            print(f"   扩展名：{file_ext}")
            print(f"   支持类型：{SUPPORTED_EXTENSIONS}")
            print(f"   检查结果：{'✅ 支持' if file_ext in SUPPORTED_EXTENSIONS else '❌ 不支持'}")
            print("=" * 60)
            
            if file_ext not in SUPPORTED_EXTENSIONS:
                errors.append(f"❌ {file.filename}: 不支持的文件类型 {file_ext}")
                continue
            
            # 保存文件
            file_path = UPLOAD_DIR / file.filename
            
            # 如果文件已存在，添加时间戳
            if file_path.exists():
                import time
                stem = Path(file.filename).stem
                suffix = Path(file.filename).suffix
                file_path = UPLOAD_DIR / f"{stem}_{int(time.time())}{suffix}"
            
            try:
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                uploaded_files.append(str(file_path.relative_to(UPLOAD_DIR)))
            except Exception as e:
                errors.append(f"❌ {file.filename}: 保存失败 - {str(e)}")
        
        if not uploaded_files:
            return UploadResponse(
                success=False,
                message="没有文件上传成功",
                error="; ".join(errors) if errors else "未知错误"
            )
        
        return UploadResponse(
            success=True,
            message=f"成功上传 {len(uploaded_files)} 个文件",
            files=uploaded_files
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败：{str(e)}")


@router.get("/raw-files", summary="获取已上传文件列表")
async def get_raw_files(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    """
    获取已上传的文件列表
    
    **示例**：
    ```
    GET /api/upload/raw-files?page=1&limit=10
    ```
    """
    try:
        if not UPLOAD_DIR.exists():
            return {
                "success": True,
                "files": [],
                "total": 0,
                "page": page,
                "limit": limit
            }
        
        # 获取所有文件
        all_files = []
        for f in UPLOAD_DIR.iterdir():
            if f.is_file():
                all_files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                    "extension": f.suffix
                })
        
        # 按修改时间排序（最新的在前）
        all_files.sort(key=lambda x: x["modified"], reverse=True)
        
        # 分页
        total = len(all_files)
        start = (page - 1) * limit
        end = start + limit
        paginated_files = all_files[start:end]
        
        return {
            "success": True,
            "files": paginated_files,
            "total": total,
            "page": page,
            "limit": limit
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败：{str(e)}")
