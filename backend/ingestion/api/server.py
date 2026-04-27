"""FastAPI app 入口 + uvicorn 启动。"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.ingestion.api.routes_index import router as index_router
from backend.ingestion.api.routes_search import router as search_router
from backend.ingestion.db.connection import init_db, DEFAULT_DB_PATH

PORT = 3003


def create_app() -> FastAPI:
    # 启动时初始化 DB（建表 / 启用 WAL），避免请求时表不存在导致 500
    init_db(DEFAULT_DB_PATH)

    app = FastAPI(title="Ingestion Service", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(index_router)
    app.include_router(search_router)

    # 联调用：可选注册 /upload 端点
    if os.getenv("INGESTION_UPLOAD_ENABLED", "false").lower() == "true":
        from backend.ingestion.api.routes_upload import router as upload_router
        app.include_router(upload_router)
        print("⚠️ /upload endpoint enabled (联调模式)")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.ingestion.api.server:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )
