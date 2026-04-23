from pathlib import Path
from app.config import Settings, SERVICE_ROOT


def test_service_root_is_chunking_rag_py_dir():
    assert SERVICE_ROOT.name == "chunking-rag-py"
    assert (SERVICE_ROOT / "app" / "config.py").exists()


def test_resolve_path_absolute_passthrough(tmp_path):
    s = Settings(db_path=tmp_path / "x.db", _env_file=None)
    assert s.resolve_path(s.db_path) == tmp_path / "x.db"


def test_resolve_path_relative_anchored_to_service_root():
    s = Settings(db_path=Path("storage/knowledge.db"), _env_file=None)
    assert s.resolve_path(s.db_path) == (SERVICE_ROOT / "storage/knowledge.db").resolve()


def test_defaults_match_env_example():
    s = Settings(_env_file=None)
    assert s.port == 3002
    assert s.embedding_model == "BAAI/bge-m3"
    assert s.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert s.rerank_threshold == 0.4
