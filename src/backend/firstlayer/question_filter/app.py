# -*- coding: utf-8 -*-
"""
问题过滤服务 - FastAPI 应用入口
"""
import sys
import os
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import Config
from routes.classify import router as classify_router


# 创建 FastAPI 应用
app = FastAPI(
    title="Question Filter Service",
    description="问题过滤服务 - 使用 StructBERT 识别无效问题和实时类问题",
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
        "service": "Question Filter Service",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health", tags=["健康检查"])
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "question-filter",
        "version": "1.0.0"
    }


@app.on_event("startup")
async def startup_event():
    """服务启动时的操作"""
    print("=" * 60)
    print("  问题过滤服务启动中...")
    print("=" * 60)
    
    # 预加载过滤分类器
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
        app,
        host=Config.HOST,
        port=Config.PORT,
        reload=False,
        log_level="info"
    )
