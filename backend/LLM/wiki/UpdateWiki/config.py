"""
配置模块
"""
import os
from pathlib import Path
from typing import Optional, Literal
from dataclasses import dataclass, field
import yaml
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


@dataclass
class LLMConfig:
    """大模型配置"""
    api_type: Literal["openai", "azure", "anthropic", "deepseek", "zhipu"] = "openai"
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4"
    temperature: float = 0.1
    max_tokens: int = 8192

    def __post_init__(self):
        # 从环境变量读取
        if not self.api_key:
            self.api_key = os.environ.get("LLM_API_KEY", "")
        if not self.api_base:
            self.api_base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
        if not self.model:
            self.model = os.environ.get("LLM_MODEL", "gpt-4")


@dataclass
class PathConfig:
    """路径配置"""
    project_root: Optional[Path] = None
    raw_dir: str = "raw"
    wiki_dir: str = "wiki"
    logs_dir: str = "logs"
    state_file: str = ".raw_manifest"

    def __post_init__(self):
        if self.project_root is None:
            self.project_root = Path(__file__).parent.parent

    @property
    def raw_path(self) -> Path:
        return self.project_root / self.raw_dir

    @property
    def wiki_path(self) -> Path:
        return self.project_root / self.wiki_dir

    @property
    def logs_path(self) -> Path:
        return self.project_root / self.logs_dir

    @property
    def state_path(self) -> Path:
        return self.project_root / self.state_file

    @property
    def agents_path(self) -> Path:
        return self.project_root / "AGENTS.md"


@dataclass
class AppConfig:
    """应用配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    max_file_size: int = 1024 * 1024  # 1MB
    max_content_length: int = 5000

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "AppConfig":
        """从 YAML 文件加载配置"""
        if not yaml_path.exists():
            return cls()

        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            return cls()

        llm_data = data.get("llm", {})
        paths_data = data.get("paths", {})

        return cls(
            llm=LLMConfig(
                api_type=llm_data.get("api_type", "openai"),
                api_key=llm_data.get("api_key", ""),
                api_base=llm_data.get("api_base", "https://api.openai.com/v1"),
                model=llm_data.get("model", "gpt-4"),
                temperature=llm_data.get("temperature", 0.1),
                max_tokens=llm_data.get("max_tokens", 8192),
            ),
            paths=PathConfig(
                project_root=Path(paths_data.get("project_root")) if paths_data.get("project_root") else None,
                raw_dir=paths_data.get("raw_dir", "raw"),
                wiki_dir=paths_data.get("wiki_dir", "wiki"),
                logs_dir=paths_data.get("logs_dir", "logs"),
                state_file=paths_data.get("state_file", ".raw_manifest"),
            ),
            max_file_size=llm_data.get("max_file_size", 1024 * 1024),
            max_content_length=llm_data.get("max_content_length", 5000),
        )