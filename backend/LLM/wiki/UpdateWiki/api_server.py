#!/usr/bin/env python3
"""
REST API 服务模块
提供 HTTP 接口供第三方调用更新知识库
"""
import sys
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uvicorn

app = FastAPI(
    title="知识库更新服务",
    description="提供 REST API 供第三方调用，触发知识库增量更新",
    version="1.0.0"
)

# 全局 updater 实例
_updater = None


class UpdateRequest(BaseModel):
    files: List[str] = Field(
        ...,
        description="文件路径列表，相对于 project_root 或 raw_dir 下的裸文件名"
    )


class UpdateResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    invalid_files: Optional[List[str]] = None


@app.on_event("startup")
async def startup_event():
    if _updater:
        _updater.logger.info("REST API 服务已启动")


@app.get("/health")
async def health_check():
    """健康检查接口"""
    if not _updater:
        raise HTTPException(status_code=503, detail="服务未初始化")
    return {
        "status": "ok",
        "config": {
            "model": _updater.config.llm.model,
            "project_root": str(_updater.config.paths.project_root),
            "raw_dir": _updater.config.paths.raw_dir,
            "wiki_dir": _updater.config.paths.wiki_dir,
        }
    }


@app.post("/api/v1/update", response_model=UpdateResponse)
async def update_files(request: UpdateRequest):
    """更新指定文件对应的 wiki 内容

    第三方传入已更新的文件名，服务调用大模型生成对应 wiki 内容并执行文件操作，
    最后将操作结果返回给调用方。

    - **files**: 文件路径列表（相对于 project_root 或 raw_dir 下的裸文件名）

    返回包含 success、message、data（操作详情）、invalid_files（无效文件列表）的 JSON
    """
    if not _updater:
        raise HTTPException(status_code=503, detail="服务未初始化")

    if not request.files:
        return UpdateResponse(
            success=False,
            message="文件列表不能为空",
            data=None,
            invalid_files=[]
        )

    result = _updater.update_files(request.files)
    return UpdateResponse(**result)


@app.post("/api/v1/update/{file_name:path}", response_model=UpdateResponse)
async def update_single_file(file_name: str):
    """更新单个文件对应的 wiki 内容

    - **file_name**: 文件路径（支持路径分隔符，如 `subdir/file.md`）
    """
    if not _updater:
        raise HTTPException(status_code=503, detail="服务未初始化")

    result = _updater.update_files([file_name])
    return UpdateResponse(**result)


def start_server(updater, host: str = "0.0.0.0", port: int = 8080):
    """启动 HTTP 服务

    Args:
        updater: KnowledgeBaseUpdater 实例
        host: 绑定地址
        port: 监听端口
    """
    global _updater
    _updater = updater

    # 添加 CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(app, host=host, port=port, log_level="info")
