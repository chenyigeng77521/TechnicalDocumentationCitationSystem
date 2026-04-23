import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.database.sqlite import init_db
from app.embedder.bge_m3 import BgeM3Embedder
from app.llm.client import LlmClient
from app.retriever.reranker import BgeReranker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    settings.ensure_dirs()
    init_db(settings.resolve_path(settings.db_path))

    model_lock = threading.Lock()
    app.state.model_lock = model_lock
    app.state.settings = settings
    app.state.embedder = BgeM3Embedder.load(settings.embedding_model, model_lock)
    app.state.reranker = BgeReranker.load(settings.rerank_model, model_lock)
    app.state.llm = LlmClient.from_settings(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="chunking-rag-py", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    from app.routes import qa as qa_route
    from app.routes import qa_stream as qa_stream_route
    from app.routes import upload as upload_route
    app.include_router(upload_route.router)
    app.include_router(qa_route.router)
    app.include_router(qa_stream_route.router)

    return app


app = create_app()
