from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 3002
    host: str = "0.0.0.0"

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_threshold: float = 0.4

    db_path: Path = Path("storage/knowledge.db")
    raw_dir: Path = Path("storage/raw")
    converted_dir: Path = Path("storage/converted")
    mappings_dir: Path = Path("storage/mappings")

    log_level: str = "INFO"

    def resolve_path(self, p: Path) -> Path:
        return p if p.is_absolute() else (SERVICE_ROOT / p).resolve()

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.converted_dir, self.mappings_dir):
            self.resolve_path(d).mkdir(parents=True, exist_ok=True)
        self.resolve_path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
