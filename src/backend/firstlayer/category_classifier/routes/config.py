# -*- coding: utf-8 -*-
"""
配置路由 - 提供前端所需的配置信息
"""
from fastapi import APIRouter
from pydantic import BaseModel
from config import Config

router = APIRouter(prefix="/api/config", tags=["配置"])


class FrontendConfig(BaseModel):
    """前端配置响应"""
    frontend_api_url: str
    file_processor_url: str
    local_test_mode: bool


@router.get("/frontend", response_model=FrontendConfig)
async def get_frontend_config():
    """获取前端配置"""
    return FrontendConfig(
        frontend_api_url=Config.FRONTEND_API_URL,
        file_processor_url=Config.FILE_PROCESSOR_URL,
        local_test_mode=Config.LOCAL_TEST_MODE
    )
