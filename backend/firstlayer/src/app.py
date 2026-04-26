# -*- coding: utf-8 -*-
"""
第一层问题分类服务 - FastAPI 应用入口
"""
import sys
import os
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from .routes.classify import router as classify_router


# 创建 FastAPI 应用
app = FastAPI(
    title="FirstLayer Question Classification Service",
    description="第一层问题分类服务 - 使用 GLiClass 模型对问题进行五大类分类",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(classify_router)


@app.get("/", tags=["健康检查"])
async def root():
    """服务根路径"""
    return {
        "service": "FirstLayer Question Classification",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health", tags=["健康检查"])
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "firstlayer-classifier",
        "version": "1.0.0"
    }


@app.on_event("startup")
async def startup_event():
    """服务启动时的操作"""
    print("=" * 60)
    print("  FirstLayer 问题分类服务启动中...")
    print("=" * 60)
    
    # 预加载分类器模型
    from classifier import get_classifier
    classifier = get_classifier()
    classifier.load_model()
    
    print("=" * 60)
    print(f"  ✅ 服务启动完成!")
    print(f"  🌐 访问地址：http://{Config.HOST}:{Config.PORT}")
    print(f"  📚 API 文档：http://{Config.HOST}:{Config.PORT}/docs")
    print("=" * 60)


if __name__ == "__main__":
    # 启动服务
    import uvicorn
    uvicorn.run(
        app,  # 直接使用 app 对象，而不是字符串
        host=Config.HOST,
        port=Config.PORT,
        reload=False,
        log_level="info"
    )
