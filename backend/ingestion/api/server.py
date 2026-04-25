"""FastAPI app 入口 + uvicorn 启动。"""
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
