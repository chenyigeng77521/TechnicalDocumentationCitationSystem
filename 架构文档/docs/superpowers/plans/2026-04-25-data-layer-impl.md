# Layer 1 数据处理层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `backend/ingestion/`（端口 :3003）数据处理层 MVP——接收 entrance 上传文件 → 解析 + 切 chunk + bge-m3 embedding → 写 SQLite + FTS5；暴露 3 个 HTTP 检索接口给海军；watchdog 路径 B 5min SLA 兜底。

**Architecture:** FastAPI 单服务 + 单 SQLite 文件 + 6 个子模块（parser/chunker/db/sync/api/common）+ TDD 全覆盖。共用 `backend/storage/` 公共目录（raw 文件入口 + DB 落地）。

**Tech Stack:** Python 3.12 (conda env `sqllineage`) / FastAPI / uvicorn / pytest / pytest-asyncio / sentence-transformers (bge-m3) / PyMuPDF / python-docx / openpyxl / python-pptx / PaddleOCR / watchdog / better-sqlite3 通过 sqlite3 stdlib。

**对应 spec:** [`docs/superpowers/specs/2026-04-25-data-layer-design.md`](../specs/2026-04-25-data-layer-design.md)

---

## 总体说明

- **任务数**：17 个 task（不含 Task 0 项目骨架）
- **粒度**：每 task 含 5-7 个 step（每 step 2-5 分钟）
- **提交节奏**：每 task 完成后 commit 一次
- **测试**：TDD 优先，每个 task 先写 fail test
- **预估工作量**：7-8 天（与 spec 风险评估对齐）
- **关键约束**：
  - file_path 字段格式 = 相对 `backend/storage/raw/`，无 `raw/` 前缀
  - chunk_id = `sha256(f"{file_path}|{chunk_index}|{content[:100]}").hexdigest()`
  - bge-m3 强制 `normalize_embeddings=True`（与海军端对齐）

---

## File Structure（一次性映射所有要建的文件）

```
backend/ingestion/
├── __init__.py
├── requirements.txt
├── README.md
├── conftest.py                          # pytest 共享 fixture（tmp DB / sample files）
│
├── common/
│   ├── __init__.py
│   ├── errors.py                        # ErrorType enum + 自定义 Exception 树
│   ├── logger.py                        # JSON line logger
│   └── embedding.py                     # bge-m3 加载 + batch_embed
│
├── db/
│   ├── __init__.py
│   ├── schema.sql                       # CREATE TABLE / INDEX / TRIGGER
│   ├── connection.py                    # SQLite 连接 + WAL + 初始化建表
│   ├── documents_repo.py                # documents 表 CRUD
│   └── chunks_repo.py                   # chunks 表 CRUD + vector_search + text_search
│
├── chunker/
│   ├── __init__.py
│   ├── types.py                         # Chunk dataclass
│   ├── document_splitter.py             # 三级 fallback 切分
│   └── overlap.py                       # 200 char overlap 拼接
│
├── parser/
│   ├── __init__.py
│   ├── types.py                         # ParseResult / TitleNode dataclass
│   ├── dispatcher.py                    # 按扩展名 + MIME sniff 分派
│   ├── markdown_parser.py
│   ├── txt_parser.py
│   ├── html_parser.py
│   ├── pdf_parser.py                    # PyMuPDF 主路径 + PaddleOCR 降级
│   ├── docx_parser.py
│   ├── xlsx_parser.py
│   └── pptx_parser.py
│
├── sync/
│   ├── __init__.py
│   ├── file_lock.py                     # 文件级 asyncio.Lock 池
│   ├── pipeline.py                      # index_pipeline 主流程（A/B 共用）
│   ├── watchdog_runner.py               # 路径 B：watchdog observer
│   └── gc.py                            # 启动扫描 + 每小时 GC
│
├── api/
│   ├── __init__.py
│   ├── server.py                        # FastAPI app + uvicorn 启动入口
│   ├── routes_index.py                  # POST /index, DELETE /files, GET /stats, /health
│   └── routes_search.py                 # POST /chunks/{vector,text}-search, GET /chunks/{id}
│
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_errors.py
│   │   ├── test_logger.py
│   │   ├── test_embedding.py
│   │   ├── test_connection.py
│   │   ├── test_documents_repo.py
│   │   ├── test_chunks_repo.py
│   │   ├── test_chunker.py
│   │   ├── test_overlap.py
│   │   ├── test_dispatcher.py
│   │   ├── test_parser_markdown.py
│   │   ├── test_parser_txt.py
│   │   ├── test_parser_html.py
│   │   ├── test_parser_pdf.py
│   │   ├── test_parser_docx.py
│   │   ├── test_parser_xlsx.py
│   │   ├── test_parser_pptx.py
│   │   ├── test_file_lock.py
│   │   ├── test_pipeline.py
│   │   ├── test_watchdog_runner.py
│   │   ├── test_gc.py
│   │   ├── test_routes_index.py
│   │   └── test_routes_search.py
│   ├── integration/
│   │   ├── test_e2e_index.py            # 上传 → 索引 → 查询 全链路
│   │   └── test_sla.py                  # 性能基线
│   └── fixtures/
│       ├── sample.md
│       ├── sample.txt
│       ├── sample.html
│       ├── sample.pdf                   # 文字版（小）
│       ├── sample_scanned.pdf           # 扫描版（小）
│       ├── sample.docx
│       ├── sample.xlsx
│       └── sample.pptx
└── logs/                                # 运行时生成，gitignore
```

---

## Task 0: 项目骨架

**Files:**
- Create: `backend/ingestion/__init__.py`
- Create: `backend/ingestion/requirements.txt`
- Create: `backend/ingestion/README.md`
- Create: `backend/ingestion/conftest.py`
- Create: `backend/ingestion/{common,db,chunker,parser,sync,api,tests,tests/unit,tests/integration,tests/fixtures,logs}/__init__.py`（空目录用 `.gitkeep`）
- Create: `backend/ingestion/.gitignore`
- Modify: 项目根 `.gitignore` 追加 `backend/ingestion/logs/`、`backend/storage/index/`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p backend/ingestion/{common,db,chunker,parser,sync,api,logs}
mkdir -p backend/ingestion/tests/{unit,integration,fixtures}
mkdir -p backend/storage/index
touch backend/ingestion/__init__.py
touch backend/ingestion/{common,db,chunker,parser,sync,api}/__init__.py
touch backend/ingestion/tests/__init__.py
touch backend/ingestion/tests/{unit,integration}/__init__.py
touch backend/ingestion/logs/.gitkeep
touch backend/storage/index/.gitkeep
```

- [ ] **Step 2: 写 `backend/ingestion/requirements.txt`**

```
# Web 框架
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.6.0

# 文档解析
pymupdf>=1.23.0           # .pdf 文字版
python-docx>=1.1.0        # .docx
openpyxl>=3.1.0           # .xlsx
python-pptx>=0.6.23       # .pptx
markdown>=3.5             # .md
beautifulsoup4>=4.12.0    # .html
markdownify>=0.11.6       # html → md
chardet>=5.2.0            # txt 编码检测
python-magic>=0.4.27      # MIME sniff
paddleocr>=2.7.0          # 扫描 PDF（CPU 模式可跑）

# Embedding
sentence-transformers>=2.7.0   # bge-m3
torch>=2.2.0                   # sentence-transformers 依赖
numpy>=1.26.0

# 异步 / 文件监听
watchdog>=4.0.0
aiofiles>=23.2.0

# 测试
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0             # FastAPI 测试客户端
pytest-benchmark>=4.0.0   # SLA 性能测试
```

- [ ] **Step 3: 写 `backend/ingestion/README.md`**

````markdown
# backend/ingestion/ — Layer 1 数据处理层

## 启动

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
pip install -r backend/ingestion/requirements.txt
python -m backend.ingestion.api.server   # 监听 :3003
```

## 测试

```bash
cd backend/ingestion
pytest tests/unit -v               # 单元测试
pytest tests/integration -v        # 集成测试（要起服务）
```

## 设计文档

参考 [`docs/superpowers/specs/2026-04-25-data-layer-design.md`](../../docs/superpowers/specs/2026-04-25-data-layer-design.md)
````

- [ ] **Step 4: 写 `backend/ingestion/.gitignore`**

```
logs/*.log
__pycache__/
*.pyc
.pytest_cache/
.coverage
```

- [ ] **Step 5: 写 `backend/ingestion/conftest.py`（pytest 共享 fixture）**

```python
"""pytest 共享 fixture。"""
import os
import sqlite3
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """临时 SQLite 文件，每个测试独立。"""
    return tmp_path / "test_knowledge.db"


@pytest.fixture
def tmp_raw_dir(tmp_path):
    """临时 raw/ 目录，模拟 backend/storage/raw/。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    return raw


@pytest.fixture
def fixtures_dir():
    """tests/fixtures/ 绝对路径。"""
    return Path(__file__).parent / "tests" / "fixtures"
```

- [ ] **Step 6: 安装依赖 + 验证 pytest 可跑**

```bash
cd backend/ingestion
pip install -r requirements.txt
pytest tests/ -v
```
Expected: `no tests ran in 0.0Xs`（只有 fixture 没有 test，正常）

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion backend/storage/index/.gitkeep
git commit -m "feat(ingestion): scaffold layer1 module skeleton

- Create backend/ingestion/ with subdirs (parser/chunker/db/sync/api/common)
- Add requirements.txt, README, conftest, .gitignore
- Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md"
```

---

## Task 1: common/errors + common/logger

**Files:**
- Create: `backend/ingestion/common/errors.py`
- Create: `backend/ingestion/common/logger.py`
- Test: `backend/ingestion/tests/unit/test_errors.py`
- Test: `backend/ingestion/tests/unit/test_logger.py`

- [ ] **Step 1: 写 errors 失败测试**

`backend/ingestion/tests/unit/test_errors.py`：
```python
"""测试错误码 enum 与自定义 Exception。"""
import pytest
from backend.ingestion.common.errors import (
    ErrorType,
    IngestionError,
    ParseError,
    EmbeddingError,
    DBError,
    UnsupportedFormatError,
)


def test_error_type_enum_values():
    assert ErrorType.FILE_NOT_FOUND.value == "file_not_found"
    assert ErrorType.UNSUPPORTED_FORMAT.value == "unsupported_format"
    assert ErrorType.PARSE_FAILED.value == "parse_failed"
    assert ErrorType.EMBEDDING_TIMEOUT.value == "embedding_timeout"
    assert ErrorType.DB_ERROR.value == "db_error"


def test_parse_error_carries_type_and_detail():
    err = ParseError("PDF 加密")
    assert err.error_type == ErrorType.PARSE_FAILED
    assert err.detail == "PDF 加密"
    assert isinstance(err, IngestionError)


def test_unsupported_format_error_inherits():
    err = UnsupportedFormatError(".doc")
    assert err.error_type == ErrorType.UNSUPPORTED_FORMAT
    assert ".doc" in err.detail


def test_to_dict_format():
    err = EmbeddingError("超时 5 次重试")
    d = err.to_dict()
    assert d["status"] == "error"
    assert d["error_type"] == "embedding_timeout"
    assert d["detail"] == "超时 5 次重试"
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
cd backend/ingestion
pytest tests/unit/test_errors.py -v
```
Expected: FAIL — `ModuleNotFoundError: backend.ingestion.common.errors`

- [ ] **Step 3: 实现 `backend/ingestion/common/errors.py`**

```python
"""错误码 + 自定义 Exception。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §11
"""
from enum import Enum


class ErrorType(str, Enum):
    FILE_NOT_FOUND = "file_not_found"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARSE_FAILED = "parse_failed"
    EMBEDDING_TIMEOUT = "embedding_timeout"
    DB_ERROR = "db_error"


class IngestionError(Exception):
    """数据处理层错误基类。"""
    error_type: ErrorType = ErrorType.DB_ERROR

    def __init__(self, detail: str = ""):
        super().__init__(detail)
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "status": "error",
            "error_type": self.error_type.value,
            "detail": self.detail,
        }


class ParseError(IngestionError):
    error_type = ErrorType.PARSE_FAILED


class EmbeddingError(IngestionError):
    error_type = ErrorType.EMBEDDING_TIMEOUT


class DBError(IngestionError):
    error_type = ErrorType.DB_ERROR


class UnsupportedFormatError(IngestionError):
    error_type = ErrorType.UNSUPPORTED_FORMAT

    def __init__(self, ext: str):
        super().__init__(f"不支持的扩展名: {ext}")
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_errors.py -v
```
Expected: 4 passed

- [ ] **Step 5: 写 logger 失败测试**

`backend/ingestion/tests/unit/test_logger.py`：
```python
"""测试 JSON line logger。"""
import json
from pathlib import Path
from backend.ingestion.common.logger import get_logger


def test_logger_writes_json_lines(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test_module", log_file=log_file)

    logger.info("hello", extra={"chunk_id": "abc123"})

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "hello"
    assert record["level"] == "INFO"
    assert record["module"] == "test_module"
    assert record["chunk_id"] == "abc123"


def test_logger_levels(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("m", log_file=log_file)
    logger.warning("warn msg")
    logger.error("err msg")

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["level"] == "WARNING"
    assert json.loads(lines[1])["level"] == "ERROR"
```

- [ ] **Step 6: 实现 `backend/ingestion/common/logger.py`**

```python
"""JSON line logger（每行一个 JSON record）。

Spec: §11 日志：JSON line 便于聚合分析
"""
import json
import logging
from pathlib import Path
from typing import Optional


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # 把 extra={...} 里的 kv 平铺进 payload
        for k, v in record.__dict__.items():
            if k not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    """获取或创建一个 JSON line logger。

    Args:
        name: logger 名（一般传 __name__）
        log_file: 日志文件路径；None 时只输出到 stderr
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = _JsonLineFormatter()
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    else:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    logger.propagate = False
    _loggers[name] = logger
    return logger
```

- [ ] **Step 7: 跑 logger 测试**

```bash
pytest tests/unit/test_logger.py -v
```
Expected: 2 passed

- [ ] **Step 8: Commit**

```bash
git add backend/ingestion/common backend/ingestion/tests/unit/test_errors.py backend/ingestion/tests/unit/test_logger.py
git commit -m "feat(ingestion): add error types and JSON line logger"
```

---

## Task 2: common/embedding（bge-m3）

**Files:**
- Create: `backend/ingestion/common/embedding.py`
- Test: `backend/ingestion/tests/unit/test_embedding.py`

- [ ] **Step 1: 写失败测试（用 mock，避免真实加载 ~2GB 模型）**

`backend/ingestion/tests/unit/test_embedding.py`：
```python
"""测试 bge-m3 embedding 包装器（mock 模型避免下载）。"""
import asyncio
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from backend.ingestion.common.embedding import batch_embed, EMBEDDING_DIM


def test_embedding_dim_constant():
    assert EMBEDDING_DIM == 1024


@pytest.mark.asyncio
async def test_batch_embed_calls_model_with_normalize(monkeypatch):
    fake_vecs = np.array([[0.1] * 1024, [0.2] * 1024], dtype=np.float32)
    fake_model = MagicMock()
    fake_model.encode.return_value = fake_vecs

    with patch("backend.ingestion.common.embedding.get_model", return_value=fake_model):
        result = await batch_embed(["text1", "text2"], concurrency=2)

    assert len(result) == 2
    assert len(result[0]) == 1024
    assert isinstance(result[0], list)
    assert isinstance(result[0][0], float)
    fake_model.encode.assert_called()
    call_kwargs = fake_model.encode.call_args.kwargs
    assert call_kwargs["normalize_embeddings"] is True


@pytest.mark.asyncio
async def test_batch_embed_empty_input(monkeypatch):
    with patch("backend.ingestion.common.embedding.get_model"):
        result = await batch_embed([], concurrency=8)
    assert result == []
```

加 `pyproject.toml`/`pytest.ini` 启用 asyncio mode。改 `backend/ingestion/conftest.py` 头部加：
```python
import pytest_asyncio  # noqa: F401
```
并新建 `backend/ingestion/pytest.ini`：
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_embedding.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `backend/ingestion/common/embedding.py`**

```python
"""bge-m3 embedding 包装器。

Spec: §8 Embedding
"""
import asyncio
from typing import Optional
import numpy as np

EMBEDDING_DIM = 1024
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 8

_MODEL = None


def get_model():
    """懒加载 bge-m3。首次调用 ~10s（下载/加载到内存 ~2GB）。"""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


async def batch_embed(texts: list[str], concurrency: int = 8) -> list[list[float]]:
    """批量算 embedding，返回 list[list[float]]。

    Args:
        texts: 文本列表
        concurrency: 并发批数（用 Semaphore 限流）

    Returns:
        list[list[float]]，每个元素是 1024 维向量

    Note: normalize_embeddings=True，与海军端约定一致
    """
    if not texts:
        return []

    model = get_model()
    sem = asyncio.Semaphore(concurrency)

    async def _embed_batch(batch_texts: list[str]) -> list[list[float]]:
        async with sem:
            vecs = await asyncio.to_thread(
                model.encode,
                batch_texts,
                normalize_embeddings=True,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
            )
            return [v.tolist() for v in vecs]

    # 切批
    batches = [texts[i:i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    results = await asyncio.gather(*[_embed_batch(b) for b in batches])
    return [vec for batch in results for vec in batch]


async def embed_single(text: str) -> list[float]:
    """单条文本算 embedding。"""
    result = await batch_embed([text])
    return result[0]
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_embedding.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/common/embedding.py backend/ingestion/tests/unit/test_embedding.py backend/ingestion/pytest.ini backend/ingestion/conftest.py
git commit -m "feat(ingestion): add bge-m3 batch embedding wrapper

- Lazy-load model on first call (~2GB / ~10s)
- normalize_embeddings=True (aligned with retrieval layer)
- 1024-dim float vectors"
```

---

## Task 3: db/schema + db/connection

**Files:**
- Create: `backend/ingestion/db/schema.sql`
- Create: `backend/ingestion/db/connection.py`
- Test: `backend/ingestion/tests/unit/test_connection.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_connection.py`：
```python
"""测试 SQLite 连接 + schema 初始化。"""
import sqlite3
import pytest
from backend.ingestion.db.connection import init_db, get_connection


def test_init_db_creates_tables(tmp_db_path):
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "documents" in tables
    assert "chunks" in tables
    # FTS5 虚表
    assert "chunks_fts" in tables


def test_init_db_enables_wal(tmp_db_path):
    init_db(tmp_db_path)
    conn = sqlite3.connect(tmp_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_init_db_enables_foreign_keys(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_chunks_fts_trigger_fires_on_insert(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('a.md', 'a.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'a.md', 'h1', 'v1', 'hello world', 'a.md#0',
                0, 11, 11, 0)
    """)
    conn.commit()
    fts_count = conn.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'hello'"
    ).fetchone()[0]
    assert fts_count == 1


def test_chunks_fts_trigger_fires_on_delete(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    conn.execute("""
        INSERT INTO documents (file_path, file_name, file_hash, file_size,
                               format, index_version, last_modified)
        VALUES ('a.md', 'a.md', 'h1', 10, 'md', 'v1', '2026-04-25')
    """)
    conn.execute("""
        INSERT INTO chunks (chunk_id, file_path, file_hash, index_version,
                            content, anchor_id, char_offset_start, char_offset_end,
                            char_count, chunk_index)
        VALUES ('c1', 'a.md', 'h1', 'v1', 'hello', 'a.md#0', 0, 5, 5, 0)
    """)
    conn.execute("DELETE FROM chunks WHERE chunk_id='c1'")
    conn.commit()
    fts_count = conn.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'hello'"
    ).fetchone()[0]
    assert fts_count == 0
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_connection.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 `backend/ingestion/db/schema.sql`**

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    file_path        TEXT PRIMARY KEY,
    file_name        TEXT NOT NULL,
    file_hash        TEXT NOT NULL,
    file_size        INTEGER NOT NULL,
    format           TEXT NOT NULL,
    language         TEXT,
    index_version    TEXT NOT NULL,
    index_status     TEXT DEFAULT 'pending',
    error_detail     TEXT,
    chunk_count      INTEGER DEFAULT 0,
    last_modified    TIMESTAMP NOT NULL,
    indexed_at       TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          TEXT PRIMARY KEY,
    file_path         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,
    index_version     TEXT NOT NULL,
    content           TEXT NOT NULL,
    anchor_id         TEXT NOT NULL,
    title_path        TEXT,
    char_offset_start INTEGER NOT NULL,
    char_offset_end   INTEGER NOT NULL,
    char_count        INTEGER NOT NULL,
    chunk_index       INTEGER NOT NULL,
    is_truncated      INTEGER DEFAULT 0,
    content_type      TEXT NOT NULL DEFAULT 'document',
    language          TEXT,
    embedding         TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_path) REFERENCES documents(file_path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file    ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(index_version);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    title_path,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;
```

- [ ] **Step 4: 实现 `backend/ingestion/db/connection.py`**

```python
"""SQLite 连接 + WAL + 初始化建表。

Spec: §3 Schema
"""
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path("backend/storage/index/knowledge.db")


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """初始化数据库（建表 / 启用 WAL）。幂等。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开一个 SQLite 连接（启用 foreign_keys + row_factory）。

    调用方负责 close。
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 5: 跑测试验证 PASS**

```bash
pytest tests/unit/test_connection.py -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/db/schema.sql backend/ingestion/db/connection.py backend/ingestion/tests/unit/test_connection.py
git commit -m "feat(ingestion/db): add schema + connection helpers

- Tables: documents, chunks, chunks_fts (FTS5)
- Triggers ai/ad/au keep FTS synced
- WAL mode + foreign_keys ON"
```

---

## Task 4: db/documents_repo

**Files:**
- Create: `backend/ingestion/db/documents_repo.py`
- Test: `backend/ingestion/tests/unit/test_documents_repo.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_documents_repo.py`：
```python
"""测试 documents 表 CRUD。"""
from datetime import datetime
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import (
    upsert_document,
    get_document,
    delete_document,
    list_all_paths,
    update_status,
)


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def test_upsert_and_get(conn):
    upsert_document(
        conn,
        file_path="a.md",
        file_name="a.md",
        file_hash="hash1",
        file_size=100,
        format="md",
        index_version="v1",
        last_modified=datetime(2026, 4, 25),
    )
    doc = get_document(conn, "a.md")
    assert doc is not None
    assert doc["file_hash"] == "hash1"
    assert doc["index_status"] == "pending"


def test_upsert_overwrites(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h1",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.utcnow())
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h2",
                    file_size=20, format="md", index_version="v1",
                    last_modified=datetime.utcnow())
    doc = get_document(conn, "a.md")
    assert doc["file_hash"] == "h2"
    assert doc["file_size"] == 20


def test_get_returns_none_when_missing(conn):
    assert get_document(conn, "nope.md") is None


def test_update_status(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.utcnow())
    update_status(conn, "a.md", index_status="indexed",
                  chunk_count=5, indexed_at=datetime.utcnow())
    doc = get_document(conn, "a.md")
    assert doc["index_status"] == "indexed"
    assert doc["chunk_count"] == 5


def test_delete_document(conn):
    upsert_document(conn, file_path="a.md", file_name="a.md", file_hash="h",
                    file_size=10, format="md", index_version="v1",
                    last_modified=datetime.utcnow())
    delete_document(conn, "a.md")
    assert get_document(conn, "a.md") is None


def test_list_all_paths(conn):
    for p in ["a.md", "b.md", "sub/c.md"]:
        upsert_document(conn, file_path=p, file_name=p.split("/")[-1],
                        file_hash="h", file_size=10, format="md",
                        index_version="v1", last_modified=datetime.utcnow())
    paths = list_all_paths(conn)
    assert set(paths) == {"a.md", "b.md", "sub/c.md"}
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_documents_repo.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `backend/ingestion/db/documents_repo.py`**

```python
"""documents 表 CRUD。"""
import sqlite3
from datetime import datetime
from typing import Optional


def upsert_document(
    conn: sqlite3.Connection,
    *,
    file_path: str,
    file_name: str,
    file_hash: str,
    file_size: int,
    format: str,
    index_version: str,
    last_modified: datetime,
    language: Optional[str] = None,
    index_status: str = "pending",
    error_detail: Optional[str] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO documents (
            file_path, file_name, file_hash, file_size, format, language,
            index_version, index_status, error_detail, last_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            file_hash = excluded.file_hash,
            file_size = excluded.file_size,
            format = excluded.format,
            language = excluded.language,
            index_version = excluded.index_version,
            index_status = excluded.index_status,
            error_detail = excluded.error_detail,
            last_modified = excluded.last_modified
        """,
        (file_path, file_name, file_hash, file_size, format, language,
         index_version, index_status, error_detail, last_modified),
    )
    conn.commit()


def get_document(conn: sqlite3.Connection, file_path: str) -> Optional[sqlite3.Row]:
    row = conn.execute(
        "SELECT * FROM documents WHERE file_path = ?", (file_path,)
    ).fetchone()
    return row


def update_status(
    conn: sqlite3.Connection,
    file_path: str,
    *,
    index_status: str,
    chunk_count: Optional[int] = None,
    indexed_at: Optional[datetime] = None,
    error_detail: Optional[str] = None,
) -> None:
    fields = ["index_status = ?"]
    values: list = [index_status]
    if chunk_count is not None:
        fields.append("chunk_count = ?")
        values.append(chunk_count)
    if indexed_at is not None:
        fields.append("indexed_at = ?")
        values.append(indexed_at)
    if error_detail is not None:
        fields.append("error_detail = ?")
        values.append(error_detail)
    values.append(file_path)
    conn.execute(
        f"UPDATE documents SET {', '.join(fields)} WHERE file_path = ?",
        values,
    )
    conn.commit()


def delete_document(conn: sqlite3.Connection, file_path: str) -> None:
    conn.execute("DELETE FROM documents WHERE file_path = ?", (file_path,))
    conn.commit()


def list_all_paths(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT file_path FROM documents").fetchall()
    return [r["file_path"] for r in rows]


def count_documents(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM documents").fetchone()[0]
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_documents_repo.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/db/documents_repo.py backend/ingestion/tests/unit/test_documents_repo.py
git commit -m "feat(ingestion/db): documents repo (upsert/get/update_status/delete/list)"
```

---

## Task 5: db/chunks_repo（含 vector_search + text_search）

**Files:**
- Create: `backend/ingestion/db/chunks_repo.py`
- Test: `backend/ingestion/tests/unit/test_chunks_repo.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_chunks_repo.py`：
```python
"""测试 chunks 表 CRUD + 向量/全文检索。"""
from datetime import datetime
import json
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import (
    insert_chunks,
    delete_chunks_by_file,
    get_chunk,
    vector_search,
    text_search,
    count_chunks,
)


def _seed_doc(conn, file_path="a.md"):
    upsert_document(conn, file_path=file_path, file_name=file_path,
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.utcnow())


@pytest.fixture
def conn(tmp_db_path):
    init_db(tmp_db_path)
    c = get_connection(tmp_db_path)
    yield c
    c.close()


def _make_chunk(chunk_id="c1", content="hello world", embedding=None,
                file_path="a.md", offset=0, title_path=None):
    return {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "file_hash": "h",
        "index_version": "v1",
        "content": content,
        "anchor_id": f"{file_path}#{offset}",
        "title_path": title_path,
        "char_offset_start": offset,
        "char_offset_end": offset + len(content),
        "char_count": len(content),
        "chunk_index": 0,
        "is_truncated": False,
        "content_type": "document",
        "language": "zh",
        "embedding": embedding or [0.0] * 1024,
    }


def test_insert_chunks_and_get(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", "hello"), _make_chunk("c2", "world")])
    assert count_chunks(conn) == 2
    c = get_chunk(conn, "c1")
    assert c["content"] == "hello"
    assert json.loads(c["embedding"])[0] == 0.0


def test_delete_chunks_by_file(conn):
    _seed_doc(conn, "a.md")
    _seed_doc(conn, "b.md")
    insert_chunks(conn, [
        _make_chunk("c1", file_path="a.md"),
        _make_chunk("c2", file_path="b.md"),
    ])
    delete_chunks_by_file(conn, "a.md")
    assert count_chunks(conn) == 1
    assert get_chunk(conn, "c1") is None


def test_vector_search_returns_top_k_by_cosine(conn):
    _seed_doc(conn)
    # 三个 chunk，embedding 不同
    e1 = [1.0] + [0.0] * 1023        # 与 query 完全一致
    e2 = [0.5, 0.5] + [0.0] * 1022   # 部分相似
    e3 = [0.0, 1.0] + [0.0] * 1022   # 不相似
    insert_chunks(conn, [
        _make_chunk("c1", "a", embedding=e1),
        _make_chunk("c2", "b", embedding=e2),
        _make_chunk("c3", "c", embedding=e3),
    ])
    query_emb = [1.0] + [0.0] * 1023
    results = vector_search(conn, query_emb, top_k=2)
    assert len(results) == 2
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["score"] > results[1]["score"]


def test_text_search_uses_fts(conn):
    _seed_doc(conn)
    insert_chunks(conn, [
        _make_chunk("c1", content="OAuth2 token refresh guide"),
        _make_chunk("c2", content="installation steps overview"),
    ])
    results = text_search(conn, "OAuth2", top_k=10)
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "bm25_rank" in results[0]
    assert results[0]["score"] > 0


def test_text_search_returns_empty_on_no_match(conn):
    _seed_doc(conn)
    insert_chunks(conn, [_make_chunk("c1", content="hello world")])
    assert text_search(conn, "xyz_nonexistent", top_k=10) == []
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_chunks_repo.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `backend/ingestion/db/chunks_repo.py`**

```python
"""chunks 表 CRUD + 向量/全文检索。

Spec: §3 schema, §4.2 检索接口
"""
import json
import math
import sqlite3
from typing import Optional


def insert_chunks(conn: sqlite3.Connection, chunks: list[dict]) -> None:
    """批量插入 chunks。每个 chunk 是 dict。"""
    if not chunks:
        return
    rows = []
    for c in chunks:
        rows.append((
            c["chunk_id"], c["file_path"], c["file_hash"], c["index_version"],
            c["content"], c["anchor_id"], c.get("title_path"),
            c["char_offset_start"], c["char_offset_end"], c["char_count"],
            c["chunk_index"], int(c.get("is_truncated", False)),
            c.get("content_type", "document"), c.get("language"),
            json.dumps(c.get("embedding")) if c.get("embedding") is not None else None,
        ))
    conn.executemany(
        """
        INSERT OR REPLACE INTO chunks (
            chunk_id, file_path, file_hash, index_version, content, anchor_id,
            title_path, char_offset_start, char_offset_end, char_count,
            chunk_index, is_truncated, content_type, language, embedding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def delete_chunks_by_file(conn: sqlite3.Connection, file_path: str) -> int:
    cur = conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))
    conn.commit()
    return cur.rowcount


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()


def count_chunks(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM chunks").fetchone()[0]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def vector_search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int = 50,
) -> list[dict]:
    """全表 cosine 相似度排序（MVP 简化版，~10k chunks 100ms）。

    返回 list[dict]：每条含 chunk 字段 + score（cosine ∈ [0,1] when normalized）
    """
    rows = conn.execute(
        "SELECT * FROM chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    scored = []
    for r in rows:
        emb = json.loads(r["embedding"])
        score = _cosine_similarity(query_embedding, emb)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, r in scored[:top_k]:
        results.append({**dict(r), "score": float(score)})
    return results


def text_search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 50,
) -> list[dict]:
    """FTS5 BM25 全文检索。

    返回 list[dict]：每条含 chunk 字段 + score（归一化 0-1）+ bm25_rank（FTS5 原始）
    """
    rows = conn.execute(
        """
        SELECT c.*, fts.rank AS bm25_rank
        FROM chunks_fts fts
        JOIN chunks c ON c.chunk_id = fts.chunk_id
        WHERE chunks_fts MATCH ?
        ORDER BY fts.rank
        LIMIT ?
        """,
        (query, top_k),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        rank = d["bm25_rank"]
        # rank 是负数，越小越相关。归一化为 (0, 1]
        d["score"] = 1.0 / (1.0 + abs(rank))
        results.append(d)
    return results
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_chunks_repo.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/db/chunks_repo.py backend/ingestion/tests/unit/test_chunks_repo.py
git commit -m "feat(ingestion/db): chunks repo with vector + FTS search

- insert/delete/get + count
- vector_search: full-table cosine similarity (MVP, <10k chunks ok)
- text_search: FTS5 BM25 + normalized score + raw rank for RRF"
```

---

## Task 6: chunker/types + document_splitter

**Files:**
- Create: `backend/ingestion/chunker/types.py`
- Create: `backend/ingestion/chunker/document_splitter.py`
- Test: `backend/ingestion/tests/unit/test_chunker.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_chunker.py`：
```python
"""测试 document 三级 fallback 切分。"""
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.document_splitter import (
    split_document,
    MAX_CHARS,
    MIN_CHARS,
)
from backend.ingestion.parser.types import ParseResult, TitleNode


def _meta():
    return {"file_path": "a.md", "file_hash": "h1", "index_version": "v1"}


def test_short_text_is_one_chunk():
    pr = ParseResult(raw_text="hello world", title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) == 1
    assert chunks[0].content == "hello world"
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_offset_start == 0
    assert chunks[0].char_offset_end == 11
    assert chunks[0].is_truncated is False


def test_long_text_splits_by_paragraph():
    para1 = "p1 " * 50  # 150 chars
    para2 = "p2 " * 50
    pr = ParseResult(raw_text=f"{para1}\n\n{para2}", title_tree=[])
    chunks = split_document(pr, **_meta())
    # 两段都短于 MAX_CHARS，应该切成 2 个 chunk
    assert len(chunks) == 2


def test_very_long_paragraph_splits_by_sentence():
    sent = "这是一句话。" * 200  # ~1200 字
    pr = ParseResult(raw_text=sent, title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) > 1
    # 没有 chunk 超过 MAX_CHARS（除非 is_truncated）
    for c in chunks:
        assert c.char_count <= MAX_CHARS or c.is_truncated


def test_single_giant_sentence_triggers_hard_truncate():
    giant = "x" * (MAX_CHARS * 3)  # 单句无标点 3 倍 MAX_CHARS
    pr = ParseResult(raw_text=giant, title_tree=[])
    chunks = split_document(pr, **_meta())
    assert len(chunks) >= 3
    assert any(c.is_truncated for c in chunks)


def test_chunk_id_is_deterministic():
    pr = ParseResult(raw_text="hello world", title_tree=[])
    c1 = split_document(pr, **_meta())[0]
    c2 = split_document(pr, **_meta())[0]
    assert c1.chunk_id == c2.chunk_id
    assert len(c1.chunk_id) == 64  # sha256 hex


def test_anchor_id_format():
    pr = ParseResult(raw_text="hello", title_tree=[])
    c = split_document(pr, **_meta())[0]
    assert c.anchor_id == "a.md#0"


def test_title_path_from_tree():
    tree = [TitleNode(level=1, text="Top", char_offset=0, children=[
        TitleNode(level=2, text="Sub", char_offset=20, children=[]),
    ])]
    pr = ParseResult(raw_text="Top intro\n\nSub content here", title_tree=tree)
    chunks = split_document(pr, **_meta())
    # 至少一个 chunk 有 title_path
    paths = [c.title_path for c in chunks if c.title_path]
    assert any("Top" in p for p in paths)


def test_min_chars_filter():
    pr = ParseResult(raw_text="x", title_tree=[])  # 1 char < MIN_CHARS
    chunks = split_document(pr, **_meta())
    # 过短 chunk 被过滤
    assert chunks == [] or all(c.char_count >= MIN_CHARS or c.is_truncated for c in chunks)
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_chunker.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `backend/ingestion/chunker/types.py`**

```python
"""chunker dataclass。"""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Chunk:
    chunk_id: str
    file_path: str
    file_hash: str
    index_version: str
    content: str
    anchor_id: str
    title_path: Optional[str]
    char_offset_start: int
    char_offset_end: int
    char_count: int
    chunk_index: int
    is_truncated: bool = False
    content_type: str = "document"
    language: Optional[str] = None
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: 实现 `backend/ingestion/chunker/document_splitter.py`**

```python
"""document 类型三级 fallback 切分。

Spec: §7 chunk 切分策略
"""
import hashlib
import re
from typing import Optional
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.parser.types import ParseResult, TitleNode

MAX_CHARS = 1000
MIN_CHARS = 30
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*")


def _make_chunk_id(file_path: str, chunk_index: int, content: str) -> str:
    h = hashlib.sha256(f"{file_path}|{chunk_index}|{content[:100]}".encode("utf-8"))
    return h.hexdigest()


def _flatten_titles(tree: list[TitleNode]) -> list[TitleNode]:
    """把树平铺成按 char_offset 排序的列表。"""
    result = []

    def _walk(nodes, ancestors):
        for n in nodes:
            n.ancestors = ancestors[:]
            result.append(n)
            _walk(n.children or [], ancestors + [n])

    _walk(tree, [])
    return sorted(result, key=lambda n: n.char_offset)


def _title_path_at_offset(titles: list[TitleNode], offset: int) -> Optional[str]:
    """找 offset 之前最近的 title，拼接祖先链。"""
    last = None
    for t in titles:
        if t.char_offset <= offset:
            last = t
        else:
            break
    if last is None:
        return None
    chain = [t.text for t in last.ancestors] + [last.text]
    return " > ".join(chain)


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def _split_paragraph(text: str) -> list[tuple[str, bool]]:
    """单段 → list[(chunk_text, is_truncated)]，按句号 → 硬切。"""
    if len(text) <= MAX_CHARS:
        return [(text, False)]

    sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s]
    out: list[tuple[str, bool]] = []
    buf = ""
    for sent in sentences:
        if len(sent) > MAX_CHARS:
            if buf:
                out.append((buf, False))
                buf = ""
            for piece in _hard_split(sent, MAX_CHARS):
                out.append((piece, True))
        elif len(buf) + len(sent) <= MAX_CHARS:
            buf += sent
        else:
            if buf:
                out.append((buf, False))
            buf = sent
    if buf:
        out.append((buf, False))
    return out


def split_document(
    parse_result: ParseResult,
    *,
    file_path: str,
    file_hash: str,
    index_version: str,
) -> list[Chunk]:
    """三级 fallback 切分。"""
    raw = parse_result.raw_text
    titles = _flatten_titles(parse_result.title_tree or [])

    # 第 1 级：按段落 \n\n 切分
    paragraphs = raw.split("\n\n")

    chunks: list[Chunk] = []
    cursor = 0
    chunk_index = 0

    for para in paragraphs:
        if not para.strip():
            cursor += len(para) + 2
            continue

        for piece, is_truncated in _split_paragraph(para):
            if not piece:
                continue
            offset = raw.find(piece, cursor) if piece in raw[cursor:] else cursor
            title_path = _title_path_at_offset(titles, offset)
            chunk_id = _make_chunk_id(file_path, chunk_index, piece)
            chunks.append(Chunk(
                chunk_id=chunk_id,
                file_path=file_path,
                file_hash=file_hash,
                index_version=index_version,
                content=piece,
                anchor_id=f"{file_path}#{offset}",
                title_path=title_path,
                char_offset_start=offset,
                char_offset_end=offset + len(piece),
                char_count=len(piece),
                chunk_index=chunk_index,
                is_truncated=is_truncated,
                content_type="document",
                language=parse_result.language,
            ))
            chunk_index += 1
            cursor = offset + len(piece)

        cursor += 2  # 跳过 \n\n

    # 过滤过短 chunk（除非 is_truncated）
    chunks = [c for c in chunks if c.char_count >= MIN_CHARS or c.is_truncated]
    # 重新编号 chunk_index
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.chunk_id = _make_chunk_id(file_path, i, c.content)
    return chunks
```

- [ ] **Step 5: 跑测试验证 PASS**

```bash
pytest tests/unit/test_chunker.py -v
```
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/chunker/types.py backend/ingestion/chunker/document_splitter.py backend/ingestion/tests/unit/test_chunker.py
git commit -m "feat(ingestion/chunker): document splitter with 3-level fallback

- Paragraph → sentence → hard truncate
- chunk_id = sha256(file_path|index|content[:100])
- anchor_id format: file_path#char_offset_start"
```

---

## Task 7: chunker/overlap

**Files:**
- Create: `backend/ingestion/chunker/overlap.py`
- Modify: `backend/ingestion/chunker/document_splitter.py`（最后调 apply_overlap）
- Test: `backend/ingestion/tests/unit/test_overlap.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_overlap.py`：
```python
"""测试 overlap 拼接。"""
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.overlap import apply_overlap, OVERLAP_CHARS


def _mk(idx, content):
    return Chunk(
        chunk_id=f"c{idx}", file_path="a.md", file_hash="h",
        index_version="v1", content=content, anchor_id=f"a.md#{idx*100}",
        title_path=None, char_offset_start=idx * 100,
        char_offset_end=idx * 100 + len(content), char_count=len(content),
        chunk_index=idx,
    )


def test_apply_overlap_prepends_tail_of_previous():
    c1 = _mk(0, "a" * 500)
    c2 = _mk(1, "b" * 500)
    result = apply_overlap([c1, c2])
    assert result[0].content == "a" * 500   # 第一个不变
    assert result[1].content.startswith("a" * OVERLAP_CHARS)
    assert result[1].content.endswith("b" * 500)


def test_apply_overlap_no_op_for_single():
    c = _mk(0, "hello")
    assert apply_overlap([c]) == [c]


def test_apply_overlap_skips_truncated():
    c1 = _mk(0, "a" * 500)
    c2 = _mk(1, "b" * 500)
    c2.is_truncated = True
    result = apply_overlap([c1, c2])
    # truncated chunk 不加 overlap（避免破坏硬切边界）
    assert result[1].content == "b" * 500
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_overlap.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 `backend/ingestion/chunker/overlap.py`**

```python
"""overlap 拼接：把前一个 chunk 末尾 200 char 拼到下一个 chunk 前。

Spec: §7 overlap 200 char
"""
from backend.ingestion.chunker.types import Chunk

OVERLAP_CHARS = 200


def apply_overlap(chunks: list[Chunk]) -> list[Chunk]:
    """对 chunk 列表应用 overlap。第一个 chunk 不变；后续每个 chunk 前面
    拼上前一个的末尾 OVERLAP_CHARS 个字符。is_truncated chunk 不加。
    """
    if len(chunks) <= 1:
        return chunks

    out = [chunks[0]]
    for prev, curr in zip(chunks, chunks[1:]):
        if curr.is_truncated:
            out.append(curr)
            continue
        tail = prev.content[-OVERLAP_CHARS:]
        new_content = tail + curr.content
        new_chunk = Chunk(
            chunk_id=curr.chunk_id,
            file_path=curr.file_path,
            file_hash=curr.file_hash,
            index_version=curr.index_version,
            content=new_content,
            anchor_id=curr.anchor_id,
            title_path=curr.title_path,
            char_offset_start=curr.char_offset_start,
            char_offset_end=curr.char_offset_end,
            char_count=len(new_content),
            chunk_index=curr.chunk_index,
            is_truncated=curr.is_truncated,
            content_type=curr.content_type,
            language=curr.language,
        )
        out.append(new_chunk)
    return out
```

- [ ] **Step 4: 在 `document_splitter.py` 末尾接入 overlap**

修改 `backend/ingestion/chunker/document_splitter.py`，在 `split_document` 函数 `return chunks` 之前加：
```python
    from backend.ingestion.chunker.overlap import apply_overlap
    chunks = apply_overlap(chunks)
    return chunks
```

- [ ] **Step 5: 跑测试验证 PASS**

```bash
pytest tests/unit/test_overlap.py tests/unit/test_chunker.py -v
```
Expected: 全部 passed（包括之前的 chunker 测试）

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/chunker/overlap.py backend/ingestion/chunker/document_splitter.py backend/ingestion/tests/unit/test_overlap.py
git commit -m "feat(ingestion/chunker): apply 200-char overlap between chunks

- Truncated chunks skip overlap (preserve hard boundary)"
```

---

## Task 8: parser/types + parser/dispatcher

**Files:**
- Create: `backend/ingestion/parser/types.py`
- Create: `backend/ingestion/parser/dispatcher.py`
- Test: `backend/ingestion/tests/unit/test_dispatcher.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_dispatcher.py`：
```python
"""测试解析器分派。"""
import pytest
from backend.ingestion.parser.dispatcher import parse_document, get_parser_name
from backend.ingestion.common.errors import UnsupportedFormatError


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_dispatch_md(tmp_path):
    f = _write(tmp_path, "a.md", "# hello\nworld")
    assert get_parser_name(f) == "markdown"


def test_dispatch_txt(tmp_path):
    f = _write(tmp_path, "a.txt", "plain text")
    assert get_parser_name(f) == "txt"


def test_dispatch_html(tmp_path):
    f = _write(tmp_path, "a.html", "<p>hello</p>")
    assert get_parser_name(f) == "html"


def test_dispatch_pdf(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    assert get_parser_name(tmp_path / "a.pdf") == "pdf"


def test_dispatch_docx(tmp_path):
    (tmp_path / "a.docx").write_bytes(b"PK\x03\x04 fake")
    assert get_parser_name(tmp_path / "a.docx") == "docx"


def test_dispatch_unsupported_raises(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"\x00")
    with pytest.raises(UnsupportedFormatError):
        get_parser_name(tmp_path / "a.exe")


@pytest.mark.asyncio
async def test_parse_md_returns_parse_result(tmp_path):
    f = _write(tmp_path, "a.md", "# Title\n\nbody text")
    result = await parse_document(f)
    assert "Title" in result.raw_text or "body" in result.raw_text
    assert result.content_type == "document"
```

- [ ] **Step 2: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_dispatcher.py -v
```
Expected: FAIL

- [ ] **Step 3: 实现 `backend/ingestion/parser/types.py`**

```python
"""parser dataclass。"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TitleNode:
    level: int           # 1-6 (h1-h6)
    text: str
    char_offset: int     # 该 title 在 raw_text 中的 char offset
    children: list = field(default_factory=list)
    ancestors: list = field(default_factory=list)  # 运行时填充


@dataclass
class ParseResult:
    raw_text: str
    title_tree: list[TitleNode] = field(default_factory=list)
    content_type: str = "document"
    language: Optional[str] = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)
```

- [ ] **Step 4: 实现 `backend/ingestion/parser/dispatcher.py`**

```python
"""按扩展名分派到对应 parser。

Spec: §6 解析器分派
"""
from pathlib import Path
from typing import Awaitable, Callable
from backend.ingestion.common.errors import UnsupportedFormatError
from backend.ingestion.parser.types import ParseResult


_EXT_TO_PARSER: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
}


def get_parser_name(path: Path) -> str:
    ext = path.suffix.lower()
    name = _EXT_TO_PARSER.get(ext)
    if name is None:
        raise UnsupportedFormatError(ext)
    return name


async def parse_document(path: Path) -> ParseResult:
    """根据扩展名调用对应 parser。"""
    name = get_parser_name(path)
    if name == "markdown":
        from backend.ingestion.parser.markdown_parser import parse as p
    elif name == "txt":
        from backend.ingestion.parser.txt_parser import parse as p
    elif name == "html":
        from backend.ingestion.parser.html_parser import parse as p
    elif name == "pdf":
        from backend.ingestion.parser.pdf_parser import parse as p
    elif name == "docx":
        from backend.ingestion.parser.docx_parser import parse as p
    elif name == "xlsx":
        from backend.ingestion.parser.xlsx_parser import parse as p
    elif name == "pptx":
        from backend.ingestion.parser.pptx_parser import parse as p
    else:
        raise UnsupportedFormatError(name)
    return await p(path)
```

- [ ] **Step 5: 跑测试验证 PASS（除 test_parse_md，因为 markdown_parser 还没实现）**

```bash
pytest tests/unit/test_dispatcher.py -v -k "not parse_md"
```
Expected: 6 passed (test_parse_md skipped 或 fail, OK)

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/parser/types.py backend/ingestion/parser/dispatcher.py backend/ingestion/tests/unit/test_dispatcher.py
git commit -m "feat(ingestion/parser): type defs + extension dispatcher"
```

---

## Task 9: parser/markdown + txt + html

**Files:**
- Create: `backend/ingestion/parser/markdown_parser.py`
- Create: `backend/ingestion/parser/txt_parser.py`
- Create: `backend/ingestion/parser/html_parser.py`
- Test: `backend/ingestion/tests/unit/test_parser_markdown.py`
- Test: `backend/ingestion/tests/unit/test_parser_txt.py`
- Test: `backend/ingestion/tests/unit/test_parser_html.py`

- [ ] **Step 1: 写失败测试 - markdown**

`backend/ingestion/tests/unit/test_parser_markdown.py`：
```python
import pytest
from backend.ingestion.parser.markdown_parser import parse


@pytest.mark.asyncio
async def test_parse_md_extracts_title_tree(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Top\n\ncontent\n\n## Sub\n\nsub content", encoding="utf-8")
    result = await parse(f)
    assert "content" in result.raw_text
    assert len(result.title_tree) >= 1
    assert result.title_tree[0].text == "Top"
    assert result.title_tree[0].level == 1


@pytest.mark.asyncio
async def test_parse_md_no_titles(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("just plain text", encoding="utf-8")
    result = await parse(f)
    assert result.raw_text == "just plain text"
    assert result.title_tree == []
```

- [ ] **Step 2: 写失败测试 - txt**

`backend/ingestion/tests/unit/test_parser_txt.py`：
```python
import pytest
from backend.ingestion.parser.txt_parser import parse


@pytest.mark.asyncio
async def test_parse_utf8(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello 你好", encoding="utf-8")
    result = await parse(f)
    assert "你好" in result.raw_text


@pytest.mark.asyncio
async def test_parse_gbk(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes("中文测试".encode("gbk"))
    result = await parse(f)
    assert "中文" in result.raw_text
```

- [ ] **Step 3: 写失败测试 - html**

`backend/ingestion/tests/unit/test_parser_html.py`：
```python
import pytest
from backend.ingestion.parser.html_parser import parse


@pytest.mark.asyncio
async def test_parse_html_to_md(tmp_path):
    f = tmp_path / "a.html"
    f.write_text("<h1>Title</h1><p>body</p>", encoding="utf-8")
    result = await parse(f)
    assert "Title" in result.raw_text
    assert "body" in result.raw_text
    assert result.title_tree[0].text == "Title"
```

- [ ] **Step 4: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_parser_markdown.py tests/unit/test_parser_txt.py tests/unit/test_parser_html.py -v
```
Expected: FAIL

- [ ] **Step 5: 实现 `backend/ingestion/parser/markdown_parser.py`**

```python
"""Markdown 解析器。提取 raw_text + heading 层级树。"""
import re
from pathlib import Path
from backend.ingestion.parser.types import ParseResult, TitleNode

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _build_tree(headings: list[TitleNode]) -> list[TitleNode]:
    """把扁平 heading 列表按 level 嵌套成树。"""
    if not headings:
        return []
    root: list[TitleNode] = []
    stack: list[TitleNode] = []
    for h in headings:
        while stack and stack[-1].level >= h.level:
            stack.pop()
        if stack:
            stack[-1].children.append(h)
        else:
            root.append(h)
        stack.append(h)
    return root


async def parse(path: Path) -> ParseResult:
    raw = path.read_text(encoding="utf-8")
    headings = []
    for m in _HEADING_RE.finditer(raw):
        headings.append(TitleNode(
            level=len(m.group(1)),
            text=m.group(2).strip(),
            char_offset=m.start(),
        ))
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
```

- [ ] **Step 6: 实现 `backend/ingestion/parser/txt_parser.py`**

```python
"""TXT 解析器。chardet 自动编码检测。"""
from pathlib import Path
import chardet
from backend.ingestion.parser.types import ParseResult


async def parse(path: Path) -> ParseResult:
    raw_bytes = path.read_bytes()
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding") or "utf-8"
    try:
        text = raw_bytes.decode(encoding, errors="replace")
    except LookupError:
        text = raw_bytes.decode("utf-8", errors="replace")
    return ParseResult(raw_text=text, title_tree=[], content_type="document")
```

- [ ] **Step 7: 实现 `backend/ingestion/parser/html_parser.py`**

```python
"""HTML 解析器。先转 markdown，再走 markdown 解析。"""
from pathlib import Path
from bs4 import BeautifulSoup
from markdownify import markdownify
from backend.ingestion.parser.types import ParseResult, TitleNode


async def parse(path: Path) -> ParseResult:
    html = path.read_text(encoding="utf-8")
    md = markdownify(html, heading_style="ATX")
    soup = BeautifulSoup(html, "html.parser")
    headings = []
    cursor = 0
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = tag.get_text(strip=True)
        level = int(tag.name[1])
        offset = md.find(text, cursor)
        if offset == -1:
            offset = cursor
        headings.append(TitleNode(level=level, text=text, char_offset=offset))
        cursor = offset + len(text)
    # build tree
    from backend.ingestion.parser.markdown_parser import _build_tree
    return ParseResult(
        raw_text=md,
        title_tree=_build_tree(headings),
        content_type="document",
    )
```

- [ ] **Step 8: 跑测试验证 PASS**

```bash
pytest tests/unit/test_parser_markdown.py tests/unit/test_parser_txt.py tests/unit/test_parser_html.py tests/unit/test_dispatcher.py -v
```
Expected: 全部 passed

- [ ] **Step 9: Commit**

```bash
git add backend/ingestion/parser/markdown_parser.py backend/ingestion/parser/txt_parser.py backend/ingestion/parser/html_parser.py backend/ingestion/tests/unit/test_parser_markdown.py backend/ingestion/tests/unit/test_parser_txt.py backend/ingestion/tests/unit/test_parser_html.py
git commit -m "feat(ingestion/parser): markdown, txt, html parsers"
```

---

## Task 10: parser/pdf（PyMuPDF + PaddleOCR 降级）

**Files:**
- Create: `backend/ingestion/parser/pdf_parser.py`
- Create: `backend/ingestion/tests/fixtures/sample.pdf`（生成一个 1 页 PDF）
- Test: `backend/ingestion/tests/unit/test_parser_pdf.py`

- [ ] **Step 1: 写脚本生成 fixture sample.pdf**

```bash
cd backend/ingestion/tests/fixtures
python -c "
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((50, 100), 'Hello PDF World', fontsize=14)
page.insert_text((50, 130), '这是一段中文。', fontsize=14)
doc.save('sample.pdf')
doc.close()
"
ls -la sample.pdf
```
Expected: 文件存在 ~1KB

- [ ] **Step 2: 写失败测试**

`backend/ingestion/tests/unit/test_parser_pdf.py`：
```python
import pytest
from backend.ingestion.parser.pdf_parser import parse


@pytest.mark.asyncio
async def test_parse_pdf_text(fixtures_dir):
    pdf = fixtures_dir / "sample.pdf"
    result = await parse(pdf)
    assert "Hello PDF World" in result.raw_text
    assert result.content_type == "document"
    assert result.metadata.get("pdf_pages") == 1


@pytest.mark.asyncio
async def test_parse_pdf_chinese(fixtures_dir):
    pdf = fixtures_dir / "sample.pdf"
    result = await parse(pdf)
    assert "中文" in result.raw_text


@pytest.mark.asyncio
async def test_parse_pdf_scanned_falls_back_to_ocr(monkeypatch, fixtures_dir):
    """文字提取为空时降级 OCR（mock 掉真实 OCR 调用）。"""
    from backend.ingestion.parser import pdf_parser

    async def fake_ocr(path):
        return "OCR fallback text"

    monkeypatch.setattr(pdf_parser, "_ocr_pdf", fake_ocr)
    monkeypatch.setattr(pdf_parser, "_extract_text_pymupdf",
                        lambda p: ("", 1))  # 空文本模拟扫描版
    result = await parse(fixtures_dir / "sample.pdf")
    assert result.raw_text == "OCR fallback text"
    assert result.metadata.get("pdf_is_scanned") is True
```

- [ ] **Step 3: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_parser_pdf.py -v
```
Expected: FAIL

- [ ] **Step 4: 实现 `backend/ingestion/parser/pdf_parser.py`**

```python
"""PDF 解析器。

主路径：PyMuPDF 提取文字
降级路径：文字为空时调 PaddleOCR
"""
from pathlib import Path
import fitz  # PyMuPDF
from backend.ingestion.parser.types import ParseResult


def _extract_text_pymupdf(path: Path) -> tuple[str, int]:
    """返回 (文本, 页数)。"""
    doc = fitz.open(path)
    pages = doc.page_count
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n\n".join(parts), pages


async def _ocr_pdf(path: Path) -> str:
    """调 PaddleOCR 识别。CPU 模式可跑，但慢。"""
    from paddleocr import PaddleOCR
    import asyncio

    def _run():
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        doc = fitz.open(path)
        all_text = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            result = ocr.ocr(img_bytes, cls=True)
            page_text = "\n".join(
                line[1][0] for block in (result or []) for line in (block or [])
            )
            all_text.append(page_text)
        doc.close()
        return "\n\n".join(all_text)

    return await asyncio.to_thread(_run)


async def parse(path: Path) -> ParseResult:
    text, pages = _extract_text_pymupdf(path)
    is_scanned = len(text.strip()) == 0
    if is_scanned:
        text = await _ocr_pdf(path)
    return ParseResult(
        raw_text=text,
        title_tree=[],   # PDF 不抽 heading（MVP）
        content_type="document",
        metadata={"pdf_pages": pages, "pdf_is_scanned": is_scanned},
    )
```

- [ ] **Step 5: 跑测试验证 PASS**

```bash
pytest tests/unit/test_parser_pdf.py -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/parser/pdf_parser.py backend/ingestion/tests/fixtures/sample.pdf backend/ingestion/tests/unit/test_parser_pdf.py
git commit -m "feat(ingestion/parser): pdf parser with PaddleOCR fallback

- PyMuPDF for text-based PDFs
- PaddleOCR for scanned PDFs (when text extraction empty)"
```

---

## Task 11: parser/docx + xlsx + pptx

**Files:**
- Create: `backend/ingestion/parser/docx_parser.py`
- Create: `backend/ingestion/parser/xlsx_parser.py`
- Create: `backend/ingestion/parser/pptx_parser.py`
- Create: 3 个 fixture 文件
- Test: 3 个 test 文件

- [ ] **Step 1: 生成 fixture 文件**

```bash
cd backend/ingestion/tests/fixtures
python -c "
from docx import Document
d = Document()
d.add_heading('DocX Title', level=1)
d.add_paragraph('First paragraph')
d.add_heading('Sub', level=2)
d.add_paragraph('Sub content')
d.save('sample.docx')
"

python -c "
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.title = 'Sheet1'
ws['A1'] = 'Header'
ws['A2'] = 'Value'
wb.save('sample.xlsx')
"

python -c "
from pptx import Presentation
p = Presentation()
slide = p.slides.add_slide(p.slide_layouts[5])
slide.shapes.title.text = 'Slide One'
p.save('sample.pptx')
"

ls -la sample.docx sample.xlsx sample.pptx
```

- [ ] **Step 2: 写 3 个失败测试**

`backend/ingestion/tests/unit/test_parser_docx.py`：
```python
import pytest
from backend.ingestion.parser.docx_parser import parse


@pytest.mark.asyncio
async def test_parse_docx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.docx")
    assert "DocX Title" in result.raw_text
    assert "First paragraph" in result.raw_text
    assert any(t.text == "DocX Title" for t in result.title_tree)
```

`backend/ingestion/tests/unit/test_parser_xlsx.py`：
```python
import pytest
from backend.ingestion.parser.xlsx_parser import parse


@pytest.mark.asyncio
async def test_parse_xlsx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.xlsx")
    assert "Header" in result.raw_text
    assert "Value" in result.raw_text
    assert "Sheet1" in result.metadata.get("sheet_names", [])
```

`backend/ingestion/tests/unit/test_parser_pptx.py`：
```python
import pytest
from backend.ingestion.parser.pptx_parser import parse


@pytest.mark.asyncio
async def test_parse_pptx(fixtures_dir):
    result = await parse(fixtures_dir / "sample.pptx")
    assert "Slide One" in result.raw_text
```

- [ ] **Step 3: 跑测试验证 FAIL**

```bash
pytest tests/unit/test_parser_docx.py tests/unit/test_parser_xlsx.py tests/unit/test_parser_pptx.py -v
```
Expected: FAIL

- [ ] **Step 4: 实现 `backend/ingestion/parser/docx_parser.py`**

```python
"""DOCX 解析器。"""
from pathlib import Path
from docx import Document
from backend.ingestion.parser.types import ParseResult, TitleNode
from backend.ingestion.parser.markdown_parser import _build_tree


async def parse(path: Path) -> ParseResult:
    doc = Document(path)
    parts = []
    headings = []
    cursor = 0
    for para in doc.paragraphs:
        text = para.text
        if not text.strip():
            cursor += 1
            continue
        style = para.style.name if para.style else ""
        if style.startswith("Heading"):
            try:
                level = int(style.replace("Heading ", ""))
            except ValueError:
                level = 1
            headings.append(TitleNode(level=level, text=text, char_offset=cursor))
        parts.append(text)
        cursor += len(text) + 2
    raw = "\n\n".join(parts)
    return ParseResult(
        raw_text=raw,
        title_tree=_build_tree(headings),
        content_type="document",
    )
```

- [ ] **Step 5: 实现 `backend/ingestion/parser/xlsx_parser.py`**

```python
"""XLSX 解析器。每 sheet → markdown 表格段。"""
from pathlib import Path
from openpyxl import load_workbook
from backend.ingestion.parser.types import ParseResult


async def parse(path: Path) -> ParseResult:
    wb = load_workbook(path, data_only=True, read_only=True)
    sheet_names = []
    parts = []
    for ws in wb.worksheets:
        sheet_names.append(ws.title)
        parts.append(f"## Sheet: {ws.title}\n")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        for row in rows:
            cells = [str(c) if c is not None else "" for c in row]
            parts.append(" | ".join(cells))
        parts.append("")
    return ParseResult(
        raw_text="\n".join(parts),
        title_tree=[],
        content_type="document",
        metadata={"sheet_names": sheet_names},
    )
```

- [ ] **Step 6: 实现 `backend/ingestion/parser/pptx_parser.py`**

```python
"""PPTX 解析器。每 slide → 一个段落。"""
from pathlib import Path
from pptx import Presentation
from backend.ingestion.parser.types import ParseResult


async def parse(path: Path) -> ParseResult:
    p = Presentation(path)
    slide_texts = []
    for i, slide in enumerate(p.slides):
        chunks = [f"### Slide {i + 1}"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if text:
                        chunks.append(text)
        slide_texts.append("\n".join(chunks))
    return ParseResult(
        raw_text="\n\n".join(slide_texts),
        title_tree=[],
        content_type="document",
        metadata={"slide_count": len(p.slides)},
    )
```

- [ ] **Step 7: 跑测试验证 PASS**

```bash
pytest tests/unit/test_parser_docx.py tests/unit/test_parser_xlsx.py tests/unit/test_parser_pptx.py -v
```
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add backend/ingestion/parser/docx_parser.py backend/ingestion/parser/xlsx_parser.py backend/ingestion/parser/pptx_parser.py backend/ingestion/tests/fixtures/sample.docx backend/ingestion/tests/fixtures/sample.xlsx backend/ingestion/tests/fixtures/sample.pptx backend/ingestion/tests/unit/test_parser_docx.py backend/ingestion/tests/unit/test_parser_xlsx.py backend/ingestion/tests/unit/test_parser_pptx.py
git commit -m "feat(ingestion/parser): docx, xlsx, pptx parsers"
```

---

## Task 12: sync/file_lock + sync/pipeline

**Files:**
- Create: `backend/ingestion/sync/file_lock.py`
- Create: `backend/ingestion/sync/pipeline.py`
- Test: `backend/ingestion/tests/unit/test_file_lock.py`
- Test: `backend/ingestion/tests/unit/test_pipeline.py`

- [ ] **Step 1: 写 file_lock 失败测试**

`backend/ingestion/tests/unit/test_file_lock.py`：
```python
import asyncio
import pytest
from backend.ingestion.sync.file_lock import file_lock, _locks


@pytest.mark.asyncio
async def test_same_path_serializes():
    seq = []

    async def worker(name):
        async with file_lock("a.md"):
            seq.append(f"{name}-start")
            await asyncio.sleep(0.05)
            seq.append(f"{name}-end")

    await asyncio.gather(worker("A"), worker("B"))
    # A 必须完整跑完才到 B（或反之），不能交错
    assert seq in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    )


@pytest.mark.asyncio
async def test_different_paths_parallel():
    """不同 file_path 锁互不干扰。"""
    seq = []

    async def worker(path, name):
        async with file_lock(path):
            seq.append(f"{name}-start")
            await asyncio.sleep(0.05)
            seq.append(f"{name}-end")

    await asyncio.gather(worker("a.md", "A"), worker("b.md", "B"))
    # 能交错 = 没串行
    starts = [s for s in seq if s.endswith("-start")]
    assert starts == ["A-start", "B-start"] or starts == ["B-start", "A-start"]
```

- [ ] **Step 2: 实现 `backend/ingestion/sync/file_lock.py`**

```python
"""文件级 asyncio 锁池。"""
import asyncio
from contextlib import asynccontextmanager

_locks: dict[str, asyncio.Lock] = {}
_lock_creation_lock = asyncio.Lock()


async def _get_lock(file_path: str) -> asyncio.Lock:
    async with _lock_creation_lock:
        if file_path not in _locks:
            _locks[file_path] = asyncio.Lock()
        return _locks[file_path]


@asynccontextmanager
async def file_lock(file_path: str):
    lock = await _get_lock(file_path)
    async with lock:
        yield
```

- [ ] **Step 3: 跑 file_lock 测试 PASS**

```bash
pytest tests/unit/test_file_lock.py -v
```
Expected: 2 passed

- [ ] **Step 4: 写 pipeline 失败测试**

`backend/ingestion/tests/unit/test_pipeline.py`：
```python
"""测试 index_pipeline 主流程（mock embedding 避免真实模型）。"""
import asyncio
from unittest.mock import patch
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import get_document
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import index_pipeline


@pytest.fixture
def setup(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    # 用 patch 替换默认 DB 路径与 raw 目录
    monkeypatch.setattr(
        "backend.ingestion.sync.pipeline.DB_PATH", tmp_db_path
    )
    monkeypatch.setattr(
        "backend.ingestion.sync.pipeline.RAW_DIR", tmp_raw_dir
    )
    return tmp_db_path, tmp_raw_dir


@pytest.mark.asyncio
async def test_index_md_file_writes_chunks(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("# Title\n\n" + ("body text. " * 20), encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        result = await index_pipeline("test.md")

    assert result["status"] == "indexed"
    assert result["chunk_count"] >= 1

    conn = get_connection(db_path)
    assert count_chunks(conn) == result["chunk_count"]
    doc = get_document(conn, "test.md")
    assert doc["index_status"] == "indexed"
    conn.close()


@pytest.mark.asyncio
async def test_unchanged_file_returns_unchanged(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("# T\n\n" + ("hello world. " * 10), encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        await index_pipeline("test.md")
        result = await index_pipeline("test.md")

    assert result["status"] == "unchanged"


@pytest.mark.asyncio
async def test_modified_file_replaces_chunks(setup):
    db_path, raw = setup
    f = raw / "test.md"
    f.write_text("v1 content " * 30, encoding="utf-8")

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        await index_pipeline("test.md")
        first_count = count_chunks(get_connection(db_path))

        f.write_text("v2 different content " * 30, encoding="utf-8")
        await index_pipeline("test.md")
        second_count = count_chunks(get_connection(db_path))

    # 旧 chunks 应该被删干净
    conn = get_connection(db_path)
    rows = conn.execute("SELECT DISTINCT file_hash FROM chunks").fetchall()
    assert len(rows) == 1   # 只有新 hash
    conn.close()


@pytest.mark.asyncio
async def test_file_not_found_raises(setup):
    with pytest.raises(FileNotFoundError):
        await index_pipeline("does_not_exist.md")
```

- [ ] **Step 5: 实现 `backend/ingestion/sync/pipeline.py`**

```python
"""index_pipeline：路径 A 和路径 B 共用入口。

Spec: §5 写入 Pipeline
"""
import hashlib
from datetime import datetime
from pathlib import Path
from backend.ingestion.common.embedding import batch_embed
from backend.ingestion.common.errors import (
    IngestionError, ParseError, EmbeddingError, DBError,
)
from backend.ingestion.common.logger import get_logger
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import (
    upsert_document, get_document, update_status, delete_document,
)
from backend.ingestion.db.chunks_repo import (
    insert_chunks, delete_chunks_by_file,
)
from backend.ingestion.parser.dispatcher import parse_document
from backend.ingestion.chunker.document_splitter import split_document
from backend.ingestion.sync.file_lock import file_lock

DB_PATH = Path("backend/storage/index/knowledge.db")
RAW_DIR = Path("backend/storage/raw")
INDEX_VERSION = "v1"   # MVP 固定
LOG_FILE = Path("backend/ingestion/logs/ingestion.log")

logger = get_logger("ingestion.pipeline", log_file=LOG_FILE)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_under_raw(file_path: str) -> Path:
    """把相对 file_path 解析成绝对路径，并校验不逃逸 RAW_DIR。"""
    base = RAW_DIR.resolve()
    abs_path = (base / file_path).resolve()
    if not str(abs_path).startswith(str(base)):
        raise ValueError(f"file_path 逃逸 RAW_DIR: {file_path}")
    return abs_path


async def index_pipeline(file_path: str) -> dict:
    """主流程：解析 → 切 chunk → embed → 写 DB。"""
    abs_path = _resolve_under_raw(file_path)
    if not abs_path.exists():
        raise FileNotFoundError(file_path)

    init_db(DB_PATH)

    async with file_lock(file_path):
        new_hash = _sha256_of_file(abs_path)

        conn = get_connection(DB_PATH)
        try:
            old_doc = get_document(conn, file_path)
            if old_doc and old_doc["file_hash"] == new_hash:
                logger.info("unchanged", extra={"file_path": file_path})
                return {"status": "unchanged"}

            upsert_document(
                conn,
                file_path=file_path,
                file_name=abs_path.name,
                file_hash=new_hash,
                file_size=abs_path.stat().st_size,
                format=abs_path.suffix.lstrip("."),
                index_version=INDEX_VERSION,
                last_modified=datetime.utcnow(),
                index_status="pending",
            )

            try:
                parse_result = await parse_document(abs_path)
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"解析失败: {e}")
                raise ParseError(str(e))

            chunks = split_document(
                parse_result,
                file_path=file_path,
                file_hash=new_hash,
                index_version=INDEX_VERSION,
            )

            try:
                embeddings = await batch_embed([c.content for c in chunks])
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"embedding 失败: {e}")
                raise EmbeddingError(str(e))

            for c, emb in zip(chunks, embeddings):
                c.embedding = emb

            try:
                delete_chunks_by_file(conn, file_path)
                insert_chunks(conn, [c.to_dict() for c in chunks])
                update_status(
                    conn, file_path,
                    index_status="indexed",
                    chunk_count=len(chunks),
                    indexed_at=datetime.utcnow(),
                )
            except Exception as e:
                update_status(conn, file_path, index_status="error",
                              error_detail=f"DB 写入失败: {e}")
                raise DBError(str(e))

            logger.info("indexed", extra={
                "file_path": file_path, "chunks": len(chunks),
            })
            return {
                "status": "indexed",
                "chunk_count": len(chunks),
                "file_hash": new_hash,
            }
        finally:
            conn.close()


async def handle_file_delete(file_path: str) -> dict:
    """删文件时同步删 documents（CASCADE 删 chunks）。"""
    init_db(DB_PATH)
    async with file_lock(file_path):
        conn = get_connection(DB_PATH)
        try:
            doc = get_document(conn, file_path)
            if doc is None:
                return {"status": "not_found"}
            chunk_count = doc["chunk_count"]
            delete_document(conn, file_path)
            logger.info("deleted", extra={"file_path": file_path})
            return {"status": "deleted", "deleted_chunks": chunk_count}
        finally:
            conn.close()
```

- [ ] **Step 6: 跑 pipeline 测试 PASS**

```bash
pytest tests/unit/test_pipeline.py -v
```
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/sync/file_lock.py backend/ingestion/sync/pipeline.py backend/ingestion/tests/unit/test_file_lock.py backend/ingestion/tests/unit/test_pipeline.py
git commit -m "feat(ingestion/sync): file_lock + index_pipeline (path A/B shared)

- File-level asyncio.Lock pool prevents A/B race
- Pipeline: hash-skip → upsert pending → parse → chunk → embed → write
- Errors update documents.error_detail before raising"
```

---

## Task 13: sync/watchdog_runner（路径 B）

**Files:**
- Create: `backend/ingestion/sync/watchdog_runner.py`
- Test: `backend/ingestion/tests/unit/test_watchdog_runner.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_watchdog_runner.py`：
```python
"""测试 watchdog observer + debounce。"""
import asyncio
from unittest.mock import patch, AsyncMock
import pytest
from backend.ingestion.sync.watchdog_runner import RawDirHandler


@pytest.mark.asyncio
async def test_handler_debounces_rapid_events(tmp_raw_dir, monkeypatch):
    pipeline_calls = []

    async def fake_pipeline(path):
        pipeline_calls.append(path)
        return {"status": "indexed"}

    handler = RawDirHandler(
        raw_dir=tmp_raw_dir,
        debounce_seconds=0.1,
        on_index=fake_pipeline,
        on_delete=AsyncMock(),
        loop=asyncio.get_event_loop(),
    )

    f = tmp_raw_dir / "a.md"
    f.write_text("content")

    # 模拟连续 3 次 modified 事件
    handler._schedule(str(f), "create_or_modify")
    handler._schedule(str(f), "create_or_modify")
    handler._schedule(str(f), "create_or_modify")

    await asyncio.sleep(0.3)
    assert len(pipeline_calls) == 1   # debounce 合成一次


@pytest.mark.asyncio
async def test_handler_calls_delete_on_deleted(tmp_raw_dir):
    delete_calls = []

    async def fake_delete(path):
        delete_calls.append(path)
        return {"status": "deleted"}

    handler = RawDirHandler(
        raw_dir=tmp_raw_dir,
        debounce_seconds=0.1,
        on_index=AsyncMock(),
        on_delete=fake_delete,
        loop=asyncio.get_event_loop(),
    )

    f = tmp_raw_dir / "a.md"
    handler._schedule(str(f), "delete")
    await asyncio.sleep(0.2)
    assert delete_calls == ["a.md"]
```

- [ ] **Step 2: 实现 `backend/ingestion/sync/watchdog_runner.py`**

```python
"""路径 B：watchdog 监听 raw/ 目录，debounce 1s 后触发 pipeline。

Spec: §10 5min SLA / 路径 B
"""
import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from backend.ingestion.common.logger import get_logger

logger = get_logger("ingestion.watchdog")


class RawDirHandler(FileSystemEventHandler):
    """监听 raw/ 目录变化，debounce 后调对应 pipeline。"""

    def __init__(
        self,
        raw_dir: Path,
        debounce_seconds: float = 1.0,
        on_index: Callable[[str], Awaitable] = None,
        on_delete: Callable[[str], Awaitable] = None,
        loop: asyncio.AbstractEventLoop = None,
    ):
        self.raw_dir = Path(raw_dir).resolve()
        self.debounce = debounce_seconds
        self.on_index = on_index
        self.on_delete = on_delete
        self.loop = loop or asyncio.get_event_loop()
        self._pending: dict[str, tuple[float, str]] = {}

    def _make_relative(self, abs_path: str) -> str:
        try:
            return str(Path(abs_path).resolve().relative_to(self.raw_dir))
        except ValueError:
            return abs_path

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_deleted(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "delete")

    def _schedule(self, abs_path: str, action: str) -> None:
        self._pending[abs_path] = (time.time(), action)
        self.loop.call_later(
            self.debounce + 0.05,
            lambda: asyncio.ensure_future(self._fire_if_settled(abs_path)),
        )

    async def _fire_if_settled(self, abs_path: str) -> None:
        entry = self._pending.get(abs_path)
        if entry is None:
            return
        last_time, action = entry
        if time.time() - last_time < self.debounce:
            return
        del self._pending[abs_path]
        rel = self._make_relative(abs_path)
        try:
            if action == "delete" and self.on_delete:
                await self.on_delete(rel)
            elif self.on_index:
                await self.on_index(rel)
        except Exception as e:
            logger.error("watchdog fire failed", extra={
                "path": rel, "action": action, "error": str(e),
            })


def start_observer(raw_dir: Path, on_index, on_delete) -> Observer:
    """启动 observer 并返回（调用方负责 .stop() / .join()）。"""
    handler = RawDirHandler(
        raw_dir=raw_dir,
        on_index=on_index,
        on_delete=on_delete,
        loop=asyncio.get_event_loop(),
    )
    observer = Observer()
    observer.schedule(handler, str(raw_dir), recursive=True)
    observer.start()
    return observer
```

- [ ] **Step 3: 跑测试验证 PASS**

```bash
pytest tests/unit/test_watchdog_runner.py -v
```
Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add backend/ingestion/sync/watchdog_runner.py backend/ingestion/tests/unit/test_watchdog_runner.py
git commit -m "feat(ingestion/sync): watchdog runner with 1s debounce

- create/modify/delete events
- Debounce coalesces rapid events for same file
- Errors logged but don't crash observer"
```

---

## Task 14: sync/gc

**Files:**
- Create: `backend/ingestion/sync/gc.py`
- Test: `backend/ingestion/tests/unit/test_gc.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_gc.py`：
```python
"""测试启动扫描 + 孤儿 chunk GC。"""
from datetime import datetime
from unittest.mock import patch, AsyncMock
import pytest
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import insert_chunks, count_chunks
from backend.ingestion.sync.gc import initial_scan, gc_orphan_chunks


@pytest.mark.asyncio
async def test_initial_scan_indexes_new_files(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.RAW_DIR", tmp_raw_dir)

    (tmp_raw_dir / "new.md").write_text("# T\n\nbody")

    indexed = []

    async def fake_index(p):
        indexed.append(p)

    async def fake_delete(p):
        pass

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    assert indexed == ["new.md"]


@pytest.mark.asyncio
async def test_initial_scan_deletes_missing_files(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.gc.RAW_DIR", tmp_raw_dir)

    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="ghost.md", file_name="ghost.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.utcnow())
    conn.close()

    deleted = []

    async def fake_index(p): pass
    async def fake_delete(p): deleted.append(p)

    await initial_scan(on_index=fake_index, on_delete=fake_delete)
    assert deleted == ["ghost.md"]


def test_gc_orphan_chunks_removes_chunks_without_doc(tmp_db_path):
    init_db(tmp_db_path)
    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="a.md", file_name="a.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.utcnow())
    insert_chunks(conn, [{
        "chunk_id": "c1", "file_path": "a.md", "file_hash": "h",
        "index_version": "v1", "content": "x", "anchor_id": "a.md#0",
        "title_path": None, "char_offset_start": 0, "char_offset_end": 1,
        "char_count": 1, "chunk_index": 0,
    }])
    # 故意删 documents（绕过 CASCADE 用 raw SQL 关闭 fk）
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM documents WHERE file_path='a.md'")
    conn.commit()
    assert count_chunks(conn) == 1   # 孤儿存在
    conn.close()

    gc_orphan_chunks(tmp_db_path)

    conn = get_connection(tmp_db_path)
    assert count_chunks(conn) == 0
    conn.close()
```

- [ ] **Step 2: 实现 `backend/ingestion/sync/gc.py`**

```python
"""启动扫描 + 每小时孤儿 chunk GC。

Spec: §10 GC
"""
import asyncio
from pathlib import Path
from typing import Awaitable, Callable
from backend.ingestion.common.logger import get_logger
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.documents_repo import list_all_paths

DB_PATH = Path("backend/storage/index/knowledge.db")
RAW_DIR = Path("backend/storage/raw")

logger = get_logger("ingestion.gc")


def _walk_raw() -> set[str]:
    if not RAW_DIR.exists():
        return set()
    return {
        str(p.relative_to(RAW_DIR))
        for p in RAW_DIR.rglob("*")
        if p.is_file()
    }


async def initial_scan(
    on_index: Callable[[str], Awaitable],
    on_delete: Callable[[str], Awaitable],
) -> None:
    """启动时对比磁盘与 documents 表，找差异并补齐。"""
    disk = _walk_raw()
    conn = get_connection(DB_PATH)
    try:
        db_paths = set(list_all_paths(conn))
    finally:
        conn.close()

    for new_path in disk - db_paths:
        logger.info("initial_scan: index new", extra={"file_path": new_path})
        await on_index(new_path)

    for missing in db_paths - disk:
        logger.info("initial_scan: delete ghost", extra={"file_path": missing})
        await on_delete(missing)


def gc_orphan_chunks(db_path: Path = DB_PATH) -> int:
    """删 chunks 表里没有对应 document 的孤儿 chunk。返回删除数。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute("""
            DELETE FROM chunks
            WHERE file_path NOT IN (SELECT file_path FROM documents)
        """)
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.warning("gc orphan chunks", extra={"deleted": deleted})
        return deleted
    finally:
        conn.close()


async def hourly_gc_loop(on_index, on_delete, interval_seconds: int = 3600) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await initial_scan(on_index, on_delete)
            gc_orphan_chunks()
        except Exception as e:
            logger.error("hourly gc failed", extra={"error": str(e)})
```

- [ ] **Step 3: 跑测试验证 PASS**

```bash
pytest tests/unit/test_gc.py -v
```
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add backend/ingestion/sync/gc.py backend/ingestion/tests/unit/test_gc.py
git commit -m "feat(ingestion/sync): initial scan + hourly orphan chunk GC"
```

---

## Task 15: api/server + api/routes_index

**Files:**
- Create: `backend/ingestion/api/server.py`
- Create: `backend/ingestion/api/routes_index.py`
- Test: `backend/ingestion/tests/unit/test_routes_index.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_routes_index.py`：
```python
"""测试写入侧 HTTP 路由。"""
from unittest.mock import patch, AsyncMock
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_post_index_success(client, monkeypatch):
    async def fake_pipeline(file_path):
        return {"status": "indexed", "chunk_count": 5, "file_hash": "h"}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "a.md"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "indexed"
    assert body["chunk_count"] == 5


@pytest.mark.asyncio
async def test_post_index_file_not_found(client, monkeypatch):
    async def fake_pipeline(file_path):
        raise FileNotFoundError(file_path)

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "missing.md"})
    assert resp.status_code == 404
    assert resp.json()["error_type"] == "file_not_found"


@pytest.mark.asyncio
async def test_post_index_parse_error(client, monkeypatch):
    from backend.ingestion.common.errors import ParseError

    async def fake_pipeline(file_path):
        raise ParseError("PDF 加密")

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.index_pipeline", fake_pipeline
    )
    resp = await client.post("/index", json={"file_path": "a.pdf"})
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "parse_failed"


@pytest.mark.asyncio
async def test_delete_files(client, monkeypatch):
    async def fake_delete(file_path):
        return {"status": "deleted", "deleted_chunks": 3}

    monkeypatch.setattr(
        "backend.ingestion.api.routes_index.handle_file_delete", fake_delete
    )
    resp = await client.request("DELETE", "/files", json={"file_path": "a.md"})
    assert resp.status_code == 200
    assert resp.json()["deleted_chunks"] == 3
```

- [ ] **Step 2: 实现 `backend/ingestion/api/routes_index.py`**

```python
"""写入侧路由：POST /index, DELETE /files, GET /stats, /health。

Spec: §4.1
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.ingestion.common.errors import (
    IngestionError, ParseError, EmbeddingError, DBError,
    UnsupportedFormatError,
)
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import count_documents
from backend.ingestion.db.chunks_repo import count_chunks
from backend.ingestion.sync.pipeline import (
    index_pipeline, handle_file_delete, DB_PATH,
)

router = APIRouter()


class IndexRequest(BaseModel):
    file_path: str


class DeleteRequest(BaseModel):
    file_path: str


@router.post("/index")
async def post_index(req: IndexRequest):
    try:
        result = await index_pipeline(req.file_path)
        return result
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"status": "error", "error_type": "file_not_found",
                    "detail": req.file_path},
        )
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except ParseError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except (EmbeddingError, DBError) as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except IngestionError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.delete("/files")
async def delete_files(req: DeleteRequest):
    return await handle_file_delete(req.file_path)


@router.get("/stats")
async def get_stats():
    init_db(DB_PATH)
    conn = get_connection(DB_PATH)
    try:
        size_mb = (DB_PATH.stat().st_size / 1024 / 1024) if DB_PATH.exists() else 0
        return {
            "documents": count_documents(conn),
            "chunks": count_chunks(conn),
            "index_size_mb": round(size_mb, 2),
        }
    finally:
        conn.close()


@router.get("/health")
async def get_health():
    init_db(DB_PATH)
    return {
        "status": "ok",
        "db_writable": DB_PATH.exists(),
        "embedding_model_loaded": False,  # 懒加载，启动时未加载
    }
```

- [ ] **Step 3: 实现 `backend/ingestion/api/server.py`**

```python
"""FastAPI app 入口 + uvicorn 启动。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.ingestion.api.routes_index import router as index_router

PORT = 3003


def create_app() -> FastAPI:
    app = FastAPI(title="Ingestion Service", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(index_router)
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
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_routes_index.py -v
```
Expected: 5 passed

- [ ] **Step 5: 手动启服务 smoke 测试**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python -m backend.ingestion.api.server &
sleep 2
curl -s http://localhost:3003/health
curl -s http://localhost:3003/stats
kill %1
```
Expected: health 返回 `{"status":"ok",...}`，stats 返回数字

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/api/server.py backend/ingestion/api/routes_index.py backend/ingestion/tests/unit/test_routes_index.py
git commit -m "feat(ingestion/api): server + index routes (POST /index, DELETE /files, GET /stats, /health)"
```

---

## Task 16: api/routes_search

**Files:**
- Create: `backend/ingestion/api/routes_search.py`
- Modify: `backend/ingestion/api/server.py`（注册新 router）
- Test: `backend/ingestion/tests/unit/test_routes_search.py`

- [ ] **Step 1: 写失败测试**

`backend/ingestion/tests/unit/test_routes_search.py`：
```python
"""测试检索侧 HTTP 路由（被海军调）。"""
from datetime import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app
from backend.ingestion.db.connection import init_db, get_connection
from backend.ingestion.db.documents_repo import upsert_document
from backend.ingestion.db.chunks_repo import insert_chunks


@pytest.fixture
async def client_with_data(tmp_db_path, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr(
        "backend.ingestion.api.routes_search.DB_PATH", tmp_db_path
    )

    conn = get_connection(tmp_db_path)
    upsert_document(conn, file_path="api/auth.md", file_name="auth.md",
                    file_hash="h", file_size=10, format="md",
                    index_version="v1", last_modified=datetime.utcnow())
    insert_chunks(conn, [{
        "chunk_id": "c1", "file_path": "api/auth.md", "file_hash": "h",
        "index_version": "v1",
        "content": "OAuth2 token refresh requires Authorization header",
        "anchor_id": "api/auth.md#0", "title_path": "Auth > OAuth2",
        "char_offset_start": 0, "char_offset_end": 50, "char_count": 50,
        "chunk_index": 0, "embedding": [1.0] + [0.0] * 1023,
    }, {
        "chunk_id": "c2", "file_path": "api/auth.md", "file_hash": "h",
        "index_version": "v1",
        "content": "Installation guide for the system",
        "anchor_id": "api/auth.md#100", "title_path": "Install",
        "char_offset_start": 100, "char_offset_end": 130, "char_count": 30,
        "chunk_index": 1, "embedding": [0.0, 1.0] + [0.0] * 1022,
    }])
    conn.close()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_vector_search_returns_top_k(client_with_data):
    resp = await client_with_data.post(
        "/chunks/vector-search",
        json={"embedding": [1.0] + [0.0] * 1023, "top_k": 1},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    r = body["results"][0]
    assert r["chunk_id"] == "c1"
    assert r["metadata"]["file_path"] == "api/auth.md"
    assert r["metadata"]["title_path"] == "Auth > OAuth2"
    assert r["metadata"]["anchor_id"] == "api/auth.md#0"


@pytest.mark.asyncio
async def test_text_search_finds_oauth(client_with_data):
    resp = await client_with_data.post(
        "/chunks/text-search",
        json={"query": "OAuth2", "top_k": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    r = body["results"][0]
    assert r["chunk_id"] == "c1"
    assert "bm25_rank" in r


@pytest.mark.asyncio
async def test_get_chunk_by_id(client_with_data):
    resp = await client_with_data.get("/chunks/c1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_id"] == "c1"
    assert body["content"].startswith("OAuth2")
    assert len(body["embedding"]) == 1024


@pytest.mark.asyncio
async def test_get_chunk_404(client_with_data):
    resp = await client_with_data.get("/chunks/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: 实现 `backend/ingestion/api/routes_search.py`**

```python
"""检索侧路由：vector-search / text-search / by-id。

Spec: §4.2
"""
import json
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.ingestion.db.connection import get_connection
from backend.ingestion.db.chunks_repo import (
    vector_search, text_search, get_chunk,
)

router = APIRouter()
DB_PATH = Path("backend/storage/index/knowledge.db")


class VectorSearchRequest(BaseModel):
    embedding: list[float]
    top_k: int = 50
    filters: Optional[dict] = None


class TextSearchRequest(BaseModel):
    query: str
    top_k: int = 50
    filters: Optional[dict] = None


def _row_to_metadata(row: dict) -> dict:
    return {
        "file_path": row["file_path"],
        "anchor_id": row["anchor_id"],
        "title_path": row["title_path"],
        "char_offset_start": row["char_offset_start"],
        "char_offset_end": row["char_offset_end"],
        "is_truncated": bool(row["is_truncated"]),
        "content_type": row["content_type"],
        "language": row["language"],
        "last_modified": None,  # MVP 暂不 JOIN documents
    }


def _format_result(row: dict, include_bm25: bool = False) -> dict:
    out = {
        "chunk_id": row["chunk_id"],
        "content": row["content"],
        "score": float(row.get("score", 0.0)),
        "metadata": _row_to_metadata(row),
    }
    if include_bm25 and "bm25_rank" in row:
        out["bm25_rank"] = row["bm25_rank"]
    return out


@router.post("/chunks/vector-search")
async def post_vector_search(req: VectorSearchRequest):
    if len(req.embedding) != 1024:
        raise HTTPException(400, "embedding must be 1024-dim")
    conn = get_connection(DB_PATH)
    try:
        results = vector_search(conn, req.embedding, top_k=req.top_k)
        return {
            "results": [_format_result(r) for r in results],
            "total": len(results),
        }
    finally:
        conn.close()


@router.post("/chunks/text-search")
async def post_text_search(req: TextSearchRequest):
    conn = get_connection(DB_PATH)
    try:
        results = text_search(conn, req.query, top_k=req.top_k)
        return {
            "results": [_format_result(r, include_bm25=True) for r in results],
            "total": len(results),
        }
    finally:
        conn.close()


@router.get("/chunks/{chunk_id}")
async def get_chunk_by_id(chunk_id: str):
    conn = get_connection(DB_PATH)
    try:
        row = get_chunk(conn, chunk_id)
        if row is None:
            raise HTTPException(404, f"chunk {chunk_id} not found")
        d = dict(row)
        return {
            "chunk_id": d["chunk_id"],
            "content": d["content"],
            "embedding": json.loads(d["embedding"]) if d["embedding"] else None,
            "metadata": _row_to_metadata(d),
        }
    finally:
        conn.close()
```

- [ ] **Step 3: 在 `server.py` 注册 search router**

修改 `backend/ingestion/api/server.py`，在 `from backend.ingestion.api.routes_index ...` 下面加：
```python
from backend.ingestion.api.routes_search import router as search_router
```
在 `app.include_router(index_router)` 后加：
```python
    app.include_router(search_router)
```

- [ ] **Step 4: 跑测试验证 PASS**

```bash
pytest tests/unit/test_routes_search.py tests/unit/test_routes_index.py -v
```
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/api/routes_search.py backend/ingestion/api/server.py backend/ingestion/tests/unit/test_routes_search.py
git commit -m "feat(ingestion/api): search routes (vector-search, text-search, by-id)

- vector-search: 1024-dim embedding required
- text-search: returns score + bm25_rank for RRF
- by-id: returns full chunk including raw embedding"
```

---

## Task 17: 集成测试 + SLA 验收

**Files:**
- Create: `backend/ingestion/tests/integration/test_e2e_index.py`
- Create: `backend/ingestion/tests/integration/test_sla.py`

- [ ] **Step 1: 写端到端集成测试**

`backend/ingestion/tests/integration/test_e2e_index.py`：
```python
"""端到端：上传 sample 文件 → POST /index → 查 chunks → 检索。

注意：这个测试用 mock embedding 跑，不加载真实 bge-m3 模型。
"""
import shutil
from unittest.mock import patch
import pytest
from httpx import AsyncClient, ASGITransport
from backend.ingestion.api.server import create_app
from backend.ingestion.db.connection import init_db


@pytest.fixture
async def e2e_client(tmp_path, monkeypatch, fixtures_dir):
    db_path = tmp_path / "knowledge.db"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    init_db(db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.DB_PATH", db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.RAW_DIR", raw_dir)
    monkeypatch.setattr("backend.ingestion.api.routes_search.DB_PATH", db_path)
    monkeypatch.setattr("backend.ingestion.api.routes_index.DB_PATH", db_path)

    # 拷贝 fixture 到 raw/
    shutil.copy(fixtures_dir / "sample.md" if (fixtures_dir / "sample.md").exists()
                else fixtures_dir / "sample.pdf", raw_dir / "sample.md")
    if not (raw_dir / "sample.md").exists():
        (raw_dir / "sample.md").write_text(
            "# Title\n\nOAuth2 token refresh requires Authorization header.\n\n"
            "Installation guide for the system."
        )

    async def fake_embed(texts, concurrency=8):
        # 简单确定性 embedding：第一维放 hash 模 100 / 100
        return [[(hash(t) % 100) / 100.0] + [0.0] * 1023 for t in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_full_flow_index_then_search(e2e_client):
    # 1. POST /index
    resp = await e2e_client.post("/index", json={"file_path": "sample.md"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "indexed"
    assert body["chunk_count"] >= 1

    # 2. GET /stats
    resp = await e2e_client.get("/stats")
    assert resp.json()["chunks"] == body["chunk_count"]

    # 3. POST /chunks/text-search
    resp = await e2e_client.post(
        "/chunks/text-search",
        json={"query": "OAuth2", "top_k": 5},
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert "OAuth2" in results[0]["content"]


@pytest.mark.asyncio
async def test_unchanged_skips(e2e_client):
    await e2e_client.post("/index", json={"file_path": "sample.md"})
    resp = await e2e_client.post("/index", json={"file_path": "sample.md"})
    assert resp.json()["status"] == "unchanged"


@pytest.mark.asyncio
async def test_delete_removes_chunks(e2e_client):
    await e2e_client.post("/index", json={"file_path": "sample.md"})
    resp = await e2e_client.request(
        "DELETE", "/files", json={"file_path": "sample.md"}
    )
    assert resp.status_code == 200
    stats = (await e2e_client.get("/stats")).json()
    assert stats["chunks"] == 0
```

- [ ] **Step 2: 写 sample.md fixture**

```bash
cat > backend/ingestion/tests/fixtures/sample.md << 'EOF'
# Sample Document

## Authentication

OAuth2 token refresh requires the `Authorization: Bearer {refresh_token}` header.
Token has a 7-day default expiry.

## Installation

1. Clone the repo
2. Run `npm install`
3. Set environment variables in `.env`

## API Reference

The system exposes REST endpoints at port 3002.
EOF
```

- [ ] **Step 3: 跑端到端集成测试**

```bash
cd backend/ingestion
pytest tests/integration/test_e2e_index.py -v
```
Expected: 3 passed

- [ ] **Step 4: 写 SLA 性能测试**

`backend/ingestion/tests/integration/test_sla.py`：
```python
"""SLA 性能基线（用 mock embedding，只测自身处理速度）。

Spec: §13 风险表 - 100 页 PDF 端到端 < 30s
"""
import time
from unittest.mock import patch
import pytest
from backend.ingestion.db.connection import init_db
from backend.ingestion.sync.pipeline import index_pipeline


@pytest.fixture
def setup(tmp_db_path, tmp_raw_dir, monkeypatch):
    init_db(tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.DB_PATH", tmp_db_path)
    monkeypatch.setattr("backend.ingestion.sync.pipeline.RAW_DIR", tmp_raw_dir)
    return tmp_db_path, tmp_raw_dir


@pytest.mark.asyncio
async def test_small_md_under_5s(setup):
    """10KB markdown < 5s（不含真实 embedding）。"""
    _, raw = setup
    f = raw / "small.md"
    f.write_text("# T\n\n" + ("body sentence. " * 500))

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        t0 = time.time()
        await index_pipeline("small.md")
        elapsed = time.time() - t0

    assert elapsed < 5.0, f"小文件超时: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_medium_md_under_30s(setup):
    """100KB markdown < 30s。"""
    _, raw = setup
    f = raw / "medium.md"
    f.write_text("# T\n\n" + ("paragraph content " * 5000))

    async def fake_embed(texts, concurrency=8):
        return [[0.1] * 1024 for _ in texts]

    with patch("backend.ingestion.sync.pipeline.batch_embed", side_effect=fake_embed):
        t0 = time.time()
        await index_pipeline("medium.md")
        elapsed = time.time() - t0

    assert elapsed < 30.0, f"中文件超时: {elapsed:.2f}s"
```

- [ ] **Step 5: 跑 SLA 测试**

```bash
pytest tests/integration/test_sla.py -v
```
Expected: 2 passed

- [ ] **Step 6: 全套测试一遍**

```bash
pytest tests/ -v
```
Expected: 全部 passed（除非有真实模型加载/网络的测试被 skip）

- [ ] **Step 7: 真实 embedding smoke test（手动）**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python -m backend.ingestion.api.server &
sleep 5

# 准备 raw 文件
cp backend/ingestion/tests/fixtures/sample.md backend/storage/raw/

# 真实 index（首次会加载 bge-m3 模型 ~10s）
curl -s -X POST http://localhost:3003/index \
     -H "Content-Type: application/json" \
     -d '{"file_path": "sample.md"}'
echo
curl -s http://localhost:3003/stats
echo
curl -s -X POST http://localhost:3003/chunks/text-search \
     -H "Content-Type: application/json" \
     -d '{"query": "OAuth2", "top_k": 3}'
echo

kill %1
```
Expected: index 返回 indexed + chunk_count > 0，stats 同步，text-search 找到 OAuth2 chunk

- [ ] **Step 8: Commit**

```bash
git add backend/ingestion/tests/integration backend/ingestion/tests/fixtures/sample.md
git commit -m "test(ingestion): e2e integration + SLA baseline tests

- E2E: index → stats → text-search → delete full flow
- SLA: small md < 5s, medium md < 30s (mock embed)
- Smoke validated with real bge-m3 model"
```

---

## 完成验收

- [ ] **整套测试一遍**

```bash
cd backend/ingestion
pytest tests/ -v --tb=short
```
Expected: 50+ tests passed

- [ ] **服务启动 smoke**

```bash
python -m backend.ingestion.api.server
# 另一终端：
curl http://localhost:3003/health
curl http://localhost:3003/stats
```

- [ ] **跟同事联调对接确认**

- 给陈一赓：让他在 `entrance/upload.ts` multer 完成后追加 `await fetch('http://localhost:3003/index', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ file_path: filename }) })`，超时设 5 min
- 给海军：他改 retrieval.py，把 LangChain SQLiteVec 那部分换成调 `POST :3003/chunks/vector-search`（embedding 他算）+ `/chunks/text-search`（query 字符串）+ `GET /chunks/{id}`

- [ ] **最终 commit + 标记完成**

```bash
git log --oneline | head -20
git tag layer1-mvp-v0.1
```

---

## 自检（writing-plans skill 要求）

**1. Spec coverage check**：

| Spec 节 | 对应 Task |
|---|---|
| §1 模块定位 + §1.1 子目录 | Task 0 |
| §3 Schema | Task 3 |
| §4.1 写入接口 | Task 15 |
| §4.2 检索接口 | Task 16 |
| §5 Pipeline | Task 12 |
| §6 解析器分派 | Task 8-11 |
| §7 chunk 切分 | Task 6-7 |
| §8 Embedding | Task 2 |
| §9 增量同步 | Task 12 (file_hash skip) + Task 14 (GC) |
| §10 5min SLA / watchdog | Task 13 |
| §11 错误码 + 日志 | Task 1 |
| §12 测试策略 | Task 17 |
| §13 风险与兜底 | Task 17 SLA + 各 task 错误处理 |
| §14 协作边界 | Task 17 完成验收 |

**所有 spec 节都被覆盖** ✓

**2. Placeholder scan**: 全文搜过，无 TODO/TBD/"implement later"/"add validation" ✓

**3. Type consistency**: `Chunk` / `ParseResult` / `TitleNode` 在所有引用 task 中签名一致 ✓
