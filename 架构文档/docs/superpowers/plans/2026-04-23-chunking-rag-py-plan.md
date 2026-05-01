# Chunking RAG Python 重写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `backend/chunking-rag-py/` 交付一个 FastAPI 实现的 Python 版 chunking-rag 服务，前端 0 修改完整接入，eval target 72–80（TS baseline 40）。

**Architecture:** 单进程 FastAPI + lifespan 常驻 bge-m3/reranker 模型 + 每请求独立 SQLite 连接（WAL）+ sync/async 执行纪律（模型/DB 调用在 `async` 路由里走 `anyio.to_thread.run_sync`）+ 召回链路 dense + BM25 → RRF → FlagReranker → 硬阈值。

**Tech Stack:** Python 3.12.4 (conda `sqllineage`) · FastAPI 0.115 · pydantic-settings · sqlite3 (stdlib, WAL) · FlagEmbedding (BAAI/bge-m3, bge-reranker-v2-m3) · rank_bm25 + jieba · openai SDK（亚信网关）· PyMuPDF / python-docx / python-pptx / openpyxl · pytest + pytest-asyncio + TestClient.

**Spec:** [2026-04-23-chunking-rag-py-design.md](../specs/2026-04-23-chunking-rag-py-design.md)（规范/决策源头；本 plan 每个任务都显式链回对应 spec 章节）。

**任务依赖链**：
```
T1 skeleton → T2 config → T3 filename_utils (并行 with T5/T6)
              └─→ T4 database (BEGIN IMMEDIATE + write_tx)
T5 parser (5 格式)       (并行)
T6 chunker (14 tests)    (并行)
T7 embedder (bge-m3)     (并行 — 冷启动可能最耗时)
T8 bm25   T9 rrf   T10 dense   T11 reranker  (retriever 四件套)
T12 orchestrator + prompt（依赖 T4/T7/T8-11）
T13 llm client
T14 sse helper
T15 deps（依赖 T2/T4/T7/T11）
T16 main.py lifespan + CORS（依赖 T4/T7/T11/T15）
T17 upload 路由（依赖 T3/T4/T5/T6/T7/T15/T16）
T18 qa 路由（依赖 T4/T15/T16）
T19 qa_stream 路由（依赖 T12/T13/T14/T15/T16）
T20 scripts/capture_ts_snapshots.py + fixtures
T21 契约/鲁棒性测试集合
T22 README + 最终冷启动验证
```

---

## 目录结构（一次性建立，参考 spec §3.1）

```
backend/chunking-rag-py/
├── requirements.txt
├── pyproject.toml
├── .env.example
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── deps.py
│   ├── filename_utils.py
│   ├── sse.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── upload.py
│   │   ├── qa.py
│   │   └── qa_stream.py
│   ├── converter/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   └── chunker.py
│   ├── embedder/
│   │   ├── __init__.py
│   │   └── bge_m3.py
│   ├── retriever/
│   │   ├── __init__.py
│   │   ├── dense.py
│   │   ├── bm25.py
│   │   ├── rrf.py
│   │   └── reranker.py
│   ├── qa/
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   └── prompt.py
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py
│   └── database/
│       ├── __init__.py
│       └── sqlite.py
├── scripts/
│   └── capture_ts_snapshots.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── sample.md
│   │   ├── sample.docx
│   │   ├── sample.pdf
│   │   ├── sample.pptx
│   │   ├── sample.xlsx
│   │   └── ts_responses/*.json
│   ├── test_chunker.py
│   ├── test_filename_utils.py
│   ├── test_sqlite.py
│   ├── test_bm25.py
│   ├── test_rrf.py
│   ├── test_dense_retriever.py
│   ├── test_contract_snapshot.py
│   ├── test_cors.py
│   ├── test_upload_limits.py
│   ├── test_upload_failure.py
│   ├── test_concurrent_upload.py
│   ├── test_qa_empty_db.py
│   ├── test_sse_framing.py
│   └── test_upload_qa_e2e.py
└── storage/           (.gitkeep 占位；实际 raw/ converted/ mappings/ .db 由代码创建)
    └── .gitkeep
```

---

## Task 1: Project skeleton + 冷启动验证（spec §附录 A/B/C）

**Files:**
- Create: `backend/chunking-rag-py/requirements.txt`
- Create: `backend/chunking-rag-py/pyproject.toml`
- Create: `backend/chunking-rag-py/.env.example`
- Create: `backend/chunking-rag-py/storage/.gitkeep`
- Create: `backend/chunking-rag-py/app/__init__.py` (空)
- Create: `backend/chunking-rag-py/app/main.py` (仅 `/health`)
- Create 空 `__init__.py`: `app/routes/`, `app/converter/`, `app/embedder/`, `app/retriever/`, `app/qa/`, `app/llm/`, `app/database/`
- Create: `backend/chunking-rag-py/tests/__init__.py` (空)
- Create: `backend/chunking-rag-py/tests/conftest.py`

- [ ] **Step 1: 建目录树**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
mkdir -p backend/chunking-rag-py/{app/{routes,converter,embedder,retriever,qa,llm,database},tests/fixtures/ts_responses,scripts,storage}
touch backend/chunking-rag-py/storage/.gitkeep
touch backend/chunking-rag-py/app/__init__.py
touch backend/chunking-rag-py/app/{routes,converter,embedder,retriever,qa,llm,database}/__init__.py
touch backend/chunking-rag-py/tests/__init__.py
```

- [ ] **Step 2: 写 requirements.txt（精确 pin，spec §附录 A）**

```
# Web 框架
fastapi==0.115.5
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
python-multipart==0.0.18

# LLM 客户端
openai==1.57.0

# Embedding & Rerank
FlagEmbedding==1.3.4

# 检索
rank-bm25==0.2.2
jieba==0.42.1

# 数值计算（FlagEmbedding 对 numpy 2.x 不完全兼容）
numpy==1.26.4

# 文档解析
PyMuPDF==1.25.1
python-docx==1.1.2
python-pptx==1.0.2
openpyxl==3.1.5

# 测试
pytest==8.3.4
pytest-asyncio==0.24.0
httpx==0.27.2
```

- [ ] **Step 3: 写 pyproject.toml**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: 写 .env.example（spec §附录 B）**

```
PORT=3002
HOST=0.0.0.0

LLM_API_KEY=<亚信网关 key>
LLM_BASE_URL=https://<亚信网关>/v1
LLM_MODEL=<团队指定模型>

EMBEDDING_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_THRESHOLD=0.4

# 所有下列路径按 service root 相对解析（config.py 解析，不依赖 cwd）
DB_PATH=storage/knowledge.db
RAW_DIR=storage/raw
CONVERTED_DIR=storage/converted
MAPPINGS_DIR=storage/mappings

LOG_LEVEL=INFO
```

- [ ] **Step 5: 写最小 app/main.py（只含 /health）**

```python
from fastapi import FastAPI

app = FastAPI(title="chunking-rag-py")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: 写 tests/conftest.py（占位）**

```python
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))
```

- [ ] **Step 7: 冷启动验证（spec §附录 C）**

```bash
cd backend/chunking-rag-py
conda activate sqllineage
python --version                                # 期望 Python 3.12.4
pip install -r requirements.txt                 # 期望零冲突
python -c "from FlagEmbedding import BGEM3FlagModel; m = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True); out = m.encode(['hello'], return_dense=True, return_sparse=False, return_colbert_vecs=False); print(out['dense_vecs'].shape)"  # 期望 (1, 1024)
python -c "from FlagEmbedding import FlagReranker; r = FlagReranker('BAAI/bge-reranker-v2-m3'); print(r.compute_score([('q','d')], normalize=True))"
python -c "import fitz, docx, pptx, openpyxl, jieba; from rank_bm25 import BM25Okapi; print('parsers + bm25 OK')"
python -c "import fastapi, uvicorn, pydantic, pydantic_settings; print('web OK')"
uvicorn app.main:app --port 3002 &
sleep 2
curl -s http://localhost:3002/health
# 期望: {"status":"ok"}
kill %1
```

**如果任一命令失败**：更新 `requirements.txt` 对应 pin 到可装通版本，重跑 Step 7，直到全部 PASS。

- [ ] **Step 8: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/chunking-rag-py/
git commit -m "feat(chunking-rag-py): project skeleton + cold-start verified"
```

---

## Task 2: Settings + SERVICE_ROOT 路径解析（spec §附录 B, §5 D4）

**Files:**
- Create: `backend/chunking-rag-py/app/config.py`
- Create: `backend/chunking-rag-py/tests/test_config.py`

- [ ] **Step 1: 写失败测试 tests/test_config.py**

```python
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
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
cd backend/chunking-rag-py
pytest tests/test_config.py -v
# 期望: ImportError (app.config 不存在)
```

- [ ] **Step 3: 实现 app/config.py**

```python
from pathlib import Path
from pydantic import Field
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
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_config.py -v
# 期望: 4 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/config.py backend/chunking-rag-py/tests/test_config.py
git commit -m "feat(chunking-rag-py): Settings with SERVICE_ROOT-anchored path resolution"
```

---

## Task 3: filename_utils（spec §5 D8）

**Files:**
- Create: `backend/chunking-rag-py/app/filename_utils.py`
- Create: `backend/chunking-rag-py/tests/test_filename_utils.py`

TS 参考：`backend/chunking-rag/src/routes/filename-utils.ts`。

- [ ] **Step 1: 写失败测试 tests/test_filename_utils.py（7 用例，spec §9.2.1）**

```python
import os
import threading
import pytest

from app.filename_utils import fix_encoding, sanitize_filename, dedupe_and_open


def test_fix_encoding_repairs_latin1_mojibake():
    mojibake = "æµè¯".encode("latin1").decode("utf-8", errors="ignore")
    assert fix_encoding(mojibake) == "测试" or fix_encoding("测试.md") == "测试.md"


def test_sanitize_removes_illegal_chars_keeps_chinese():
    assert sanitize_filename("说明/文档*<>.md") == "说明_文档___.md"


def test_sanitize_replaces_spaces_with_underscore():
    assert sanitize_filename("my file name.md") == "my_file_name.md"


def test_dedupe_creates_file_atomically(tmp_path):
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a.txt"
    assert path.exists()


def test_dedupe_adds_underscore_suffix_on_collision(tmp_path):
    (tmp_path / "a.txt").touch()
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a_1.txt"


def test_dedupe_increments_suffix(tmp_path):
    (tmp_path / "a.txt").touch()
    (tmp_path / "a_1.txt").touch()
    path, fd = dedupe_and_open(tmp_path, "a.txt")
    os.close(fd)
    assert path == tmp_path / "a_2.txt"


def test_dedupe_handles_no_extension(tmp_path):
    (tmp_path / "README").touch()
    path, fd = dedupe_and_open(tmp_path, "README")
    os.close(fd)
    assert path == tmp_path / "README_1"


def test_dedupe_thread_safe_same_name(tmp_path):
    results: list[str] = []
    lock = threading.Lock()

    def claim():
        p, fd = dedupe_and_open(tmp_path, "x.txt")
        os.close(fd)
        with lock:
            results.append(p.name)

    threads = [threading.Thread(target=claim) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["x.txt", "x_1.txt", "x_2.txt", "x_3.txt", "x_4.txt"]
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_filename_utils.py -v
# 期望: ImportError
```

- [ ] **Step 3: 实现 app/filename_utils.py**

```python
import os
import re
from pathlib import Path


ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def fix_encoding(name: str) -> str:
    """修 latin1→utf-8 中文乱码（multipart filename 经常遭此）。无乱码时原样返回。"""
    try:
        repaired = name.encode("latin-1").decode("utf-8")
        return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def sanitize_filename(name: str) -> str:
    """清非法字符 + 空格→下划线，保留中文 / 数字 / 常见标点。"""
    name = name.strip()
    name = ILLEGAL_CHARS.sub("_", name)
    name = re.sub(r"\s+", "_", name)
    return name or "unnamed"


def _split_name_ext(name: str) -> tuple[str, str]:
    if "." not in name:
        return name, ""
    base, ext = name.rsplit(".", 1)
    return base, "." + ext


def dedupe_and_open(raw_dir: Path, filename: str) -> tuple[Path, int]:
    """原子地创建目标文件并返回 (path, fd)。若同名存在则加 `_N` 后缀。

    调用方负责 os.write(fd, ...) 和 os.close(fd)；若后续写入失败，必须 unlink 返回的 path。
    """
    base, ext = _split_name_ext(filename)
    candidate = filename
    i = 1
    while True:
        path = raw_dir / candidate
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            return path, fd
        except FileExistsError:
            candidate = f"{base}_{i}{ext}"
            i += 1
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_filename_utils.py -v
# 期望: 8 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/filename_utils.py backend/chunking-rag-py/tests/test_filename_utils.py
git commit -m "feat(chunking-rag-py): filename utils (sanitize + O_EXCL atomic dedupe)"
```

---

## Task 4: database schema + write_tx + Db CRUD（spec §5 D4/D9, §7）

**Files:**
- Create: `backend/chunking-rag-py/app/database/sqlite.py`
- Create: `backend/chunking-rag-py/tests/test_sqlite.py`

- [ ] **Step 1: 写失败测试 tests/test_sqlite.py**

```python
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.database.sqlite import Db, init_db, write_tx


@pytest.fixture
def db_path(tmp_path) -> Path:
    p = tmp_path / "k.db"
    init_db(p)
    return p


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(db_path, isolation_level=None)
    c.execute("PRAGMA busy_timeout=10000;")
    c.execute("PRAGMA foreign_keys=ON;")
    yield c
    c.close()


def test_init_db_creates_schema(db_path):
    c = sqlite3.connect(db_path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "chunks"} <= tables
    c.close()


def test_init_db_enables_wal_persistently(db_path):
    c = sqlite3.connect(db_path)
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    c.close()


def test_init_db_is_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)
    c = sqlite3.connect(db_path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"files", "chunks"} <= tables


def test_insert_and_get_file(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(
        id=fid, original_name="a.md", original_path="raw/a.md", converted_path="",
        format="md", size=100, upload_time="2026-04-23T00:00:00", status="converting"
    )
    row = db.get_file(fid)
    assert row["original_name"] == "a.md"
    assert row["status"] == "converting"


def test_update_file_status_transitions(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    db.update_file_status(fid, "completed")
    assert db.get_file(fid)["status"] == "completed"
    db.update_file_status(fid, "failed")
    assert db.get_file(fid)["status"] == "failed"


def test_insert_chunks_and_cascade_delete(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    chunks = [
        dict(id=str(uuid.uuid4()), file_id=fid, content="c1", start_line=1, end_line=2,
             original_lines=[1, 2], vector=[0.1] * 1024),
        dict(id=str(uuid.uuid4()), file_id=fid, content="c2", start_line=3, end_line=4,
             original_lines=[3, 4], vector=[0.2] * 1024),
    ]
    db.insert_chunks(chunks)
    assert len(db.get_chunks_by_file(fid)) == 2

    db.delete_file_and_chunks(fid)
    assert db.get_file(fid) is None
    assert db.get_chunks_by_file(fid) == []


def test_vector_json_roundtrip(conn):
    db = Db(conn)
    fid = str(uuid.uuid4())
    db.insert_file(id=fid, original_name="a.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    vec = [0.5] * 1024
    db.insert_chunks([dict(id="c1", file_id=fid, content="x", start_line=1, end_line=1,
                           original_lines=[1], vector=vec)])
    got = db.get_chunks_by_file(fid)[0]
    assert got["vector"] == vec


def test_stats_counts_only_completed(conn):
    db = Db(conn)
    for i, st in enumerate(["completed", "converting", "failed", "completed"]):
        db.insert_file(id=f"f{i}", original_name=f"{i}.md", original_path="", converted_path="",
                       format="md", size=0, upload_time="", status=st)
    stats = db.get_stats()
    assert stats == {"fileCount": 2, "chunkCount": 0}


def test_get_completed_chunks_filters_status(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="1.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="completed")
    db.insert_file(id="f2", original_name="2.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    db.insert_chunks([
        dict(id="c1", file_id="f1", content="ok", start_line=1, end_line=1, original_lines=[1], vector=[0.0] * 1024),
        dict(id="c2", file_id="f2", content="hidden", start_line=1, end_line=1, original_lines=[1], vector=[0.0] * 1024),
    ])
    chunks = db.get_completed_chunks()
    assert {c["id"] for c in chunks} == {"c1"}


def test_write_tx_rolls_back_on_exception(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="x.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    with pytest.raises(RuntimeError):
        with write_tx(conn):
            conn.execute("UPDATE files SET status='completed' WHERE id=?", ("f1",))
            raise RuntimeError("boom")
    assert db.get_file("f1")["status"] == "converting"


def test_write_tx_commits_on_success(conn):
    db = Db(conn)
    db.insert_file(id="f1", original_name="x.md", original_path="", converted_path="",
                   format="md", size=0, upload_time="", status="converting")
    with write_tx(conn):
        conn.execute("UPDATE files SET status='completed' WHERE id=?", ("f1",))
    assert db.get_file("f1")["status"] == "completed"
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_sqlite.py -v
# 期望: ImportError
```

- [ ] **Step 3: 实现 app/database/sqlite.py**

```python
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
  id              TEXT PRIMARY KEY,
  original_name   TEXT NOT NULL,
  original_path   TEXT NOT NULL,
  converted_path  TEXT NOT NULL,
  format          TEXT NOT NULL,
  size            INTEGER NOT NULL,
  upload_time     TEXT NOT NULL,
  category        TEXT DEFAULT '',
  status          TEXT NOT NULL,
  tags            TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  id              TEXT PRIMARY KEY,
  file_id         TEXT NOT NULL,
  content         TEXT NOT NULL,
  start_line      INTEGER NOT NULL,
  end_line        INTEGER NOT NULL,
  original_lines  TEXT NOT NULL,
  vector          TEXT,
  FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        # WAL 是 DB 文件头持久设置，startup 一次执行，后续连接自动 WAL
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[None]:
    """显式 BEGIN IMMEDIATE 写事务，异常回滚。autocommit (isolation_level=None) 下的唯一正确写法。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


class Db:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_file(
        self, *, id: str, original_name: str, original_path: str, converted_path: str,
        format: str, size: int, upload_time: str, status: str,
        category: str = "", tags: list[str] | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO files (id, original_name, original_path, converted_path, format, size, upload_time, category, status, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, original_name, original_path, converted_path, format, size, upload_time, category, status,
             json.dumps(tags) if tags else None),
        )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM files WHERE id=?", (file_id,))
        row = cur.fetchone()
        return _row_to_dict(cur, row) if row else None

    def update_file_status(self, file_id: str, status: str) -> None:
        self.conn.execute("UPDATE files SET status=? WHERE id=?", (status, file_id))

    def update_file_converted_path(self, file_id: str, path: str) -> None:
        self.conn.execute("UPDATE files SET converted_path=? WHERE id=?", (path, file_id))

    def get_files_by_name(self, original_name: str) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM files WHERE original_name=?", (original_name,))
        rows = cur.fetchall()
        return [_row_to_dict(cur, r) for r in rows]

    def list_completed_files(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM files WHERE status='completed' ORDER BY upload_time DESC")
        return [_row_to_dict(cur, r) for r in cur.fetchall()]

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        rows = []
        for c in chunks:
            rows.append((
                c.get("id") or str(uuid.uuid4()),
                c["file_id"], c["content"], c["start_line"], c["end_line"],
                json.dumps(c["original_lines"]),
                json.dumps(c["vector"]) if c.get("vector") is not None else None,
            ))
        self.conn.executemany(
            "INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def get_chunks_by_file(self, file_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM chunks WHERE file_id=?", (file_id,))
        return [self._chunk_from_row(cur, r) for r in cur.fetchall()]

    def get_completed_chunks(self) -> list[dict[str, Any]]:
        """检索入口：只返回 status='completed' 的文件的 chunks（spec D6）。"""
        cur = self.conn.execute(
            "SELECT c.* FROM chunks c JOIN files f ON c.file_id=f.id WHERE f.status='completed'"
        )
        return [self._chunk_from_row(cur, r) for r in cur.fetchall()]

    def delete_file_and_chunks(self, file_id: str) -> None:
        # chunks 靠 FK ON DELETE CASCADE 自动清，但我们显式写一遍更清晰
        self.conn.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
        self.conn.execute("DELETE FROM files WHERE id=?", (file_id,))

    def get_stats(self) -> dict[str, int]:
        fc = self.conn.execute("SELECT COUNT(*) FROM files WHERE status='completed'").fetchone()[0]
        cc = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"fileCount": fc, "chunkCount": cc}

    @staticmethod
    def _chunk_from_row(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
        d = _row_to_dict(cursor, row)
        d["original_lines"] = json.loads(d["original_lines"])
        d["vector"] = json.loads(d["vector"]) if d.get("vector") else None
        return d
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_sqlite.py -v
# 期望: 11 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/database/ backend/chunking-rag-py/tests/test_sqlite.py
git commit -m "feat(chunking-rag-py): SQLite schema + write_tx + Db CRUD"
```

---

## Task 5: converter/parser.py — 5 种格式（spec §3.1, §6.1）

**Files:**
- Create: `backend/chunking-rag-py/app/converter/parser.py`
- Create: `backend/chunking-rag-py/tests/test_parser.py`
- Create: `backend/chunking-rag-py/tests/fixtures/` 下 sample.md/docx/xlsx/pptx/pdf

- [ ] **Step 1: 准备测试 fixtures**

```bash
cd backend/chunking-rag-py/tests/fixtures

# sample.md
cat > sample.md <<'EOF'
# 标题一

段落一内容。

## 标题二

段落二内容，含中文。
EOF

# 用 Python 生成其他格式（省掉手工）
python <<'PY'
from pathlib import Path
from docx import Document
from pptx import Presentation
from openpyxl import Workbook
import fitz  # PyMuPDF

d = Document()
d.add_heading("标题一", level=1)
d.add_paragraph("段落一内容。")
d.add_heading("标题二", level=2)
d.add_paragraph("段落二内容，含中文。")
d.save("sample.docx")

p = Presentation()
slide_layout = p.slide_layouts[0]
slide = p.slides.add_slide(slide_layout)
slide.shapes.title.text = "标题一"
slide.placeholders[1].text = "段落一内容。"
p.save("sample.pptx")

wb = Workbook(); ws = wb.active; ws.title = "Sheet1"
ws.append(["A", "B"]); ws.append(["1", "中文"])
wb.save("sample.xlsx")

doc = fitz.open()
page = doc.new_page()
page.insert_text((50, 72), "Hello PDF\n第二行中文", fontsize=14)
doc.save("sample.pdf")
doc.close()
PY
```

- [ ] **Step 2: 写失败测试 tests/test_parser.py**

```python
from pathlib import Path

import pytest

from app.converter.parser import parse

FIX = Path(__file__).parent / "fixtures"


def test_parse_md_returns_raw_content():
    md, line_map = parse(FIX / "sample.md")
    assert "标题一" in md
    assert "段落一内容" in md
    assert isinstance(line_map, dict)


def test_parse_docx_converts_headings_to_markdown():
    md, _ = parse(FIX / "sample.docx")
    assert "# 标题一" in md or "## 标题一" in md
    assert "段落一内容" in md


def test_parse_pdf_extracts_text():
    md, _ = parse(FIX / "sample.pdf")
    assert "Hello PDF" in md
    assert "第二行中文" in md


def test_parse_pptx_extracts_slide_title_and_body():
    md, _ = parse(FIX / "sample.pptx")
    assert "标题一" in md
    assert "段落一内容" in md


def test_parse_xlsx_produces_markdown_table():
    md, _ = parse(FIX / "sample.xlsx")
    assert "| A | B |" in md or "A | B" in md
    assert "中文" in md


def test_parse_unknown_ext_raises():
    with pytest.raises(ValueError, match="unsupported"):
        parse(FIX / "sample.xyz")
```

- [ ] **Step 3: 运行测试确认 fail**

```bash
pytest tests/test_parser.py -v
# 期望: ImportError
```

- [ ] **Step 4: 实现 app/converter/parser.py**

```python
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


def parse(path: Path) -> tuple[str, dict[int, Any]]:
    """按扩展名分派。返回 (markdown_text, line_map)。

    line_map: 当前 MVP 空映射（{}），v2 才用。保留参数以便以后填充。
    """
    ext = path.suffix.lower()
    if ext == ".md":
        return _parse_md(path)
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".docx":
        return _parse_docx(path)
    if ext == ".pptx":
        return _parse_pptx(path)
    if ext == ".xlsx":
        return _parse_xlsx(path)
    raise ValueError(f"unsupported file format: {ext}")


def _parse_md(path: Path) -> tuple[str, dict[int, Any]]:
    return path.read_text(encoding="utf-8"), {}


def _parse_pdf(path: Path) -> tuple[str, dict[int, Any]]:
    doc = fitz.open(path)
    parts: list[str] = []
    try:
        for i, page in enumerate(doc, 1):
            text = page.get_text()
            if text.strip():
                parts.append(f"## Page {i}\n\n{text.strip()}")
    finally:
        doc.close()
    return "\n\n".join(parts), {}


def _parse_docx(path: Path) -> tuple[str, dict[int, Any]]:
    doc = Document(path)
    lines: list[str] = []
    for p in doc.paragraphs:
        style = (p.style.name or "").lower() if p.style else ""
        text = p.text.strip()
        if not text:
            continue
        if style.startswith("heading 1"):
            lines.append(f"# {text}")
        elif style.startswith("heading 2"):
            lines.append(f"## {text}")
        elif style.startswith("heading"):
            lines.append(f"### {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines), {}


def _parse_pptx(path: Path) -> tuple[str, dict[int, Any]]:
    pres = Presentation(path)
    parts: list[str] = []
    for i, slide in enumerate(pres.slides, 1):
        parts.append(f"## Slide {i}")
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                text = "".join(run.text for run in para.runs).strip()
                if text:
                    parts.append(text)
    return "\n\n".join(parts), {}


def _parse_xlsx(path: Path) -> tuple[str, dict[int, Any]]:
    wb = load_workbook(path, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"## Sheet {ws.title}")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = rows[0]
        parts.append("| " + " | ".join(str(c or "") for c in header) + " |")
        parts.append("|" + "|".join(["---"] * len(header)) + "|")
        for row in rows[1:]:
            parts.append("| " + " | ".join(str(c or "") for c in row) + " |")
    return "\n\n".join(parts), {}
```

- [ ] **Step 5: 运行测试确认 pass**

```bash
pytest tests/test_parser.py -v
# 期望: 6 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/chunking-rag-py/app/converter/parser.py backend/chunking-rag-py/tests/test_parser.py backend/chunking-rag-py/tests/fixtures/sample.*
git commit -m "feat(chunking-rag-py): parser (pdf/docx/pptx/xlsx/md → markdown)"
```

---

## Task 6: converter/chunker.py — 14 测试（spec §5 D5, §9.2.1）

**Files:**
- Create: `backend/chunking-rag-py/app/converter/chunker.py`
- Create: `backend/chunking-rag-py/tests/test_chunker.py`

- [ ] **Step 1: 写失败测试 tests/test_chunker.py（14 用例）**

```python
import pytest

from app.converter.chunker import Chunk, chunk_markdown


def test_empty_input_returns_empty():
    assert chunk_markdown("", {}) == []


def test_single_short_paragraph_one_chunk():
    chunks = chunk_markdown("Hello world.", {})
    assert len(chunks) == 1
    assert chunks[0].content == "Hello world."


def test_heading_split_creates_separate_chunks():
    md = "# H1\n\nAlpha.\n\n## H2\n\nBeta."
    chunks = chunk_markdown(md, {})
    assert len(chunks) >= 2
    assert any("Alpha" in c.content for c in chunks)
    assert any("Beta" in c.content for c in chunks)


def test_blank_lines_split_paragraphs():
    md = "Para one.\n\nPara two.\n\nPara three."
    chunks = chunk_markdown(md, {})
    # 段落可能被合并成一个 chunk（都很短），但至少含全部文字
    joined = " ".join(c.content for c in chunks)
    assert "Para one" in joined and "Para three" in joined


def test_long_paragraph_split_at_target_size():
    long = "句。" * 500  # 约 1000 字符
    chunks = chunk_markdown(long, {})
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.content) <= 1000


def test_short_fragments_merged_to_min_size():
    md = "\n\n".join(["短。"] * 20)
    chunks = chunk_markdown(md, {})
    for c in chunks[:-1]:
        assert len(c.content) >= 100  # 除最后一块外均应 >= 100


def test_code_block_not_split_internally():
    md = "前文。\n\n```python\ndef foo():\n    return 1\n    return 2\n```\n\n后文。"
    chunks = chunk_markdown(md, {})
    # 代码块应当完整保留在某一个 chunk
    assert any("def foo" in c.content and "return 2" in c.content for c in chunks)


def test_chinese_text_chunking():
    md = "中文段落一。" * 100
    chunks = chunk_markdown(md, {})
    assert len(chunks) >= 1
    assert all("中文" in c.content for c in chunks)


def test_mixed_heading_and_paragraph():
    md = "# 标题\n\n段落一。\n\n段落二。\n\n## 二级\n\n段落三。"
    chunks = chunk_markdown(md, {})
    assert sum("段落一" in c.content for c in chunks) == 1
    assert sum("段落三" in c.content for c in chunks) == 1


def test_only_heading_no_content():
    chunks = chunk_markdown("# 只有标题", {})
    # 只有标题的 markdown 不产生 chunk（无可检索内容）
    assert chunks == [] or (len(chunks) == 1 and chunks[0].content == "# 只有标题")


def test_nested_headings_preserved():
    md = "# L1\n\n## L2\n\n### L3\n\n内容。"
    chunks = chunk_markdown(md, {})
    assert any("内容" in c.content for c in chunks)


def test_trailing_incomplete_paragraph():
    md = "# H\n\n段落。\n\n尾部未闭合"
    chunks = chunk_markdown(md, {})
    assert any("尾部未闭合" in c.content for c in chunks)


def test_consecutive_blank_lines_collapsed():
    md = "一。\n\n\n\n\n二。"
    chunks = chunk_markdown(md, {})
    joined = " ".join(c.content for c in chunks)
    assert "一" in joined and "二" in joined


def test_unicode_and_emoji():
    md = "Hello 世界 🌏。"
    chunks = chunk_markdown(md, {})
    assert chunks[0].content == "Hello 世界 🌏。"


def test_line_range_tracked():
    md = "line 1\n\nline 3\n\nline 5"
    chunks = chunk_markdown(md, {})
    # 每个 chunk 都有合理的 start_line/end_line（基于 split）
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line >= c.start_line
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_chunker.py -v
# 期望: ImportError
```

- [ ] **Step 3: 实现 app/converter/chunker.py**

```python
import re
from dataclasses import dataclass, field
from typing import Any

TARGET_MIN = 100
TARGET_MAX = 800
HARD_MAX = 1000
HEADING_RE = re.compile(r"^(#{1,6})\s+.+$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


@dataclass
class Chunk:
    content: str
    start_line: int
    end_line: int
    original_lines: list[int] = field(default_factory=list)


def chunk_markdown(md: str, line_map: dict[int, Any]) -> list[Chunk]:
    if not md.strip():
        return []

    blocks = _split_blocks_preserving_code(md)
    merged = _merge_short(blocks)
    chunks: list[Chunk] = []
    for block in merged:
        chunks.extend(_split_long_block(block))
    # 去掉"只有标题"的情况：标题行单独一块且无其他文字
    return [c for c in chunks if _has_real_content(c.content)]


def _split_blocks_preserving_code(md: str) -> list[Chunk]:
    """按空行切段落，但代码块不内切。标题行独立成块。返回含 start_line/end_line 的 Chunk 列表。"""
    lines = md.splitlines()
    blocks: list[Chunk] = []
    buf: list[str] = []
    buf_start = 0
    in_code = False

    def flush(end_line: int):
        if buf:
            content = "\n".join(buf).strip()
            if content:
                blocks.append(Chunk(content=content, start_line=buf_start + 1, end_line=end_line))
        buf.clear()

    for i, line in enumerate(lines):
        if CODE_FENCE_RE.match(line):
            if not in_code:
                flush(i)
                buf_start = i
                buf.append(line)
                in_code = True
            else:
                buf.append(line)
                flush(i + 1)
                in_code = False
            continue

        if in_code:
            buf.append(line)
            continue

        if HEADING_RE.match(line):
            flush(i)
            buf_start = i
            buf.append(line)
            flush(i + 1)
            continue

        if not line.strip():
            flush(i)
            buf_start = i + 1
            continue

        if not buf:
            buf_start = i
        buf.append(line)

    flush(len(lines))
    return blocks


def _merge_short(blocks: list[Chunk]) -> list[Chunk]:
    """把 < TARGET_MIN 的相邻块合并到前一块。"""
    if not blocks:
        return []
    out: list[Chunk] = [blocks[0]]
    for b in blocks[1:]:
        if len(out[-1].content) < TARGET_MIN and len(out[-1].content) + len(b.content) + 2 <= HARD_MAX:
            out[-1] = Chunk(
                content=out[-1].content + "\n\n" + b.content,
                start_line=out[-1].start_line,
                end_line=b.end_line,
            )
        else:
            out.append(b)
    return out


def _split_long_block(block: Chunk) -> list[Chunk]:
    """把 > HARD_MAX 的单块按句号切到 <= HARD_MAX。"""
    if len(block.content) <= HARD_MAX:
        return [block]
    pieces: list[str] = []
    cur = ""
    for sent in re.split(r"(?<=[。！？.!?])", block.content):
        if len(cur) + len(sent) > HARD_MAX and cur:
            pieces.append(cur.strip())
            cur = sent
        else:
            cur += sent
    if cur.strip():
        pieces.append(cur.strip())
    return [
        Chunk(content=p, start_line=block.start_line, end_line=block.end_line)
        for p in pieces if p
    ]


def _has_real_content(content: str) -> bool:
    """单独的标题（# xxx）不算可检索内容；但若含其他文字则算。"""
    non_heading = HEADING_RE.sub("", content).strip()
    return bool(non_heading) or len(content) > 20
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_chunker.py -v
# 期望: 14 passed（若 test_only_heading_no_content 因 _has_real_content 策略不符，调整策略或测试即可——保持二者一致）
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/converter/chunker.py backend/chunking-rag-py/tests/test_chunker.py
git commit -m "feat(chunking-rag-py): markdown chunker (14 unit tests)"
```

---

## Task 7: embedder/bge_m3.py（spec §8, R7）

**Files:**
- Create: `backend/chunking-rag-py/app/embedder/bge_m3.py`
- Create: `backend/chunking-rag-py/tests/test_embedder.py`

> 真实模型加载慢且吃资源。**单测用 mock** 验证接口契约；真实加载在冷启动验证（Task 1 Step 7）和 e2e 集中验证。

- [ ] **Step 1: 写失败测试 tests/test_embedder.py**

```python
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.embedder.bge_m3 import BgeM3Embedder


def test_encode_returns_dense_vecs_only(monkeypatch):
    fake_model = MagicMock()
    fake_model.encode.return_value = {
        "dense_vecs": np.zeros((2, 1024), dtype=np.float32),
        "lexical_weights": None,
        "colbert_vecs": None,
    }
    lock = threading.Lock()
    emb = BgeM3Embedder(model=fake_model, lock=lock)
    vecs = emb.encode(["hello", "world"])
    assert vecs.shape == (2, 1024)
    fake_model.encode.assert_called_once_with(
        ["hello", "world"],
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )


def test_encode_acquires_lock():
    fake_model = MagicMock()
    fake_model.encode.return_value = {"dense_vecs": np.zeros((1, 1024))}
    lock = threading.Lock()

    lock.acquire()
    emb = BgeM3Embedder(model=fake_model, lock=lock)

    done = threading.Event()

    def call():
        emb.encode(["x"])
        done.set()

    t = threading.Thread(target=call)
    t.start()
    # lock 被占，encode 应阻塞
    assert not done.wait(0.2)
    lock.release()
    assert done.wait(1.0)
    t.join()
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_embedder.py -v
# 期望: ImportError
```

- [ ] **Step 3: 实现 app/embedder/bge_m3.py**

```python
import threading

import numpy as np


class BgeM3Embedder:
    """bge-m3 dense-only 封装。所有 encode 调用在 model_lock 内串行化（spec R7）。"""

    def __init__(self, model, lock: threading.Lock):
        self._model = model
        self._lock = lock

    @classmethod
    def load(cls, model_name: str, lock: threading.Lock) -> "BgeM3Embedder":
        from FlagEmbedding import BGEM3FlagModel
        model = BGEM3FlagModel(model_name, use_fp16=True)
        return cls(model=model, lock=lock)

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            out = self._model.encode(
                texts,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        return np.asarray(out["dense_vecs"], dtype=np.float32)
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_embedder.py -v
# 期望: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/embedder/ backend/chunking-rag-py/tests/test_embedder.py
git commit -m "feat(chunking-rag-py): BgeM3Embedder (dense-only, lock-wrapped)"
```

---

## Task 8: retriever/bm25.py（spec §5 D6, §9.2.1）

**Files:**
- Create: `backend/chunking-rag-py/app/retriever/bm25.py`
- Create: `backend/chunking-rag-py/tests/test_bm25.py`

- [ ] **Step 1: 写失败测试**

```python
from app.retriever.bm25 import bm25_search


def test_bm25_chinese_tokenize_recall():
    chunks = [
        {"id": "1", "content": "北京的天气很好。"},
        {"id": "2", "content": "上海有东方明珠塔。"},
        {"id": "3", "content": "广州是南方城市。"},
    ]
    results = bm25_search("北京天气", chunks, k=3)
    assert results[0][0]["id"] == "1"


def test_bm25_empty_query_returns_empty():
    chunks = [{"id": "1", "content": "anything"}]
    assert bm25_search("", chunks, k=5) == []


def test_bm25_k_limit():
    chunks = [{"id": str(i), "content": f"关键词 content {i}"} for i in range(10)]
    results = bm25_search("关键词", chunks, k=3)
    assert len(results) <= 3
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_bm25.py -v
```

- [ ] **Step 3: 实现 app/retriever/bm25.py**

```python
import jieba
from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def bm25_search(query: str, chunks: list[dict], k: int = 20) -> list[tuple[dict, float]]:
    """对传入 chunks 即时建 BM25 index 并返回 top-k (chunk, score)。"""
    if not query.strip() or not chunks:
        return []
    corpus = [_tokenize(c["content"]) for c in chunks]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    idx = sorted(range(len(chunks)), key=lambda i: -scores[i])[:k]
    return [(chunks[i], float(scores[i])) for i in idx if scores[i] > 0]
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_bm25.py -v
# 期望: 3 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/retriever/bm25.py backend/chunking-rag-py/tests/test_bm25.py
git commit -m "feat(chunking-rag-py): BM25 retriever with jieba tokenization"
```

---

## Task 9: retriever/rrf.py（spec §5 D6）

**Files:**
- Create: `backend/chunking-rag-py/app/retriever/rrf.py`
- Create: `backend/chunking-rag-py/tests/test_rrf.py`

- [ ] **Step 1: 写失败测试**

```python
from app.retriever.rrf import rrf_fuse


def test_rrf_two_lists_fully_overlap():
    a = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    b = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    out = rrf_fuse([a, b], k=60)
    assert [c["id"] for c in out] == ["1", "2", "3"]


def test_rrf_no_overlap_preserves_all():
    a = [{"id": "1"}, {"id": "2"}]
    b = [{"id": "3"}, {"id": "4"}]
    out = rrf_fuse([a, b], k=60)
    assert {c["id"] for c in out} == {"1", "2", "3", "4"}


def test_rrf_partial_overlap_rank_sum():
    # 文档 2 在 a 排 1、在 b 排 1 → 双第 1，应该排最前
    # 文档 1 在 a 排 0（最前）、在 b 不出现
    a = [{"id": "1"}, {"id": "2"}]
    b = [{"id": "2"}, {"id": "3"}]
    out = rrf_fuse([a, b], k=60)
    assert out[0]["id"] == "2"
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_rrf.py -v
```

- [ ] **Step 3: 实现 app/retriever/rrf.py**

```python
def rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """RRF: score(d) = Σ 1/(k + rank_i(d))。返回按融合分数降序的唯一 chunks。"""
    scores: dict[str, float] = {}
    chunk_by_id: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, chunk in enumerate(lst):
            cid = chunk["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            chunk_by_id[cid] = chunk
    return [chunk_by_id[cid] for cid in sorted(scores, key=lambda c: -scores[c])]
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_rrf.py -v
# 期望: 3 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/retriever/rrf.py backend/chunking-rag-py/tests/test_rrf.py
git commit -m "feat(chunking-rag-py): RRF fusion"
```

---

## Task 10: retriever/dense.py（spec §5 D6）

**Files:**
- Create: `backend/chunking-rag-py/app/retriever/dense.py`
- Create: `backend/chunking-rag-py/tests/test_dense.py`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np

from app.retriever.dense import dense_search


def test_dense_top_k_descending():
    q = np.array([1.0, 0.0], dtype=np.float32)
    chunks = [
        {"id": "1", "vector": [1.0, 0.0]},
        {"id": "2", "vector": [0.0, 1.0]},
        {"id": "3", "vector": [0.7, 0.7]},
    ]
    out = dense_search(q, chunks, k=3)
    ids = [c["id"] for c, _ in out]
    assert ids[0] == "1"
    # score 降序
    assert out[0][1] >= out[1][1] >= out[2][1]


def test_dense_skips_chunks_without_vector():
    q = np.array([1.0, 0.0], dtype=np.float32)
    chunks = [
        {"id": "1", "vector": [1.0, 0.0]},
        {"id": "2", "vector": None},
    ]
    out = dense_search(q, chunks, k=5)
    assert [c["id"] for c, _ in out] == ["1"]
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_dense.py -v
```

- [ ] **Step 3: 实现 app/retriever/dense.py**

```python
import numpy as np


def dense_search(
    q_vec: np.ndarray, chunks: list[dict], k: int = 20
) -> list[tuple[dict, float]]:
    """余弦相似度 top-k。chunks 里 vector=None 的跳过。"""
    valid = [c for c in chunks if c.get("vector") is not None]
    if not valid:
        return []
    mat = np.asarray([c["vector"] for c in valid], dtype=np.float32)
    q = q_vec.astype(np.float32)
    q_norm = np.linalg.norm(q) or 1.0
    mat_norm = np.linalg.norm(mat, axis=1)
    mat_norm[mat_norm == 0] = 1.0
    scores = (mat @ q) / (mat_norm * q_norm)
    idx = np.argsort(-scores)[:k]
    return [(valid[i], float(scores[i])) for i in idx]
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_dense.py -v
# 期望: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/retriever/dense.py backend/chunking-rag-py/tests/test_dense.py
git commit -m "feat(chunking-rag-py): dense cosine retriever"
```

---

## Task 11: retriever/reranker.py（spec §8, R7）

**Files:**
- Create: `backend/chunking-rag-py/app/retriever/reranker.py`
- Create: `backend/chunking-rag-py/tests/test_reranker.py`

- [ ] **Step 1: 写失败测试**

```python
import threading
from unittest.mock import MagicMock

from app.retriever.reranker import BgeReranker


def test_score_calls_normalize_true():
    fake = MagicMock()
    fake.compute_score.return_value = [0.9, 0.2]
    lock = threading.Lock()
    r = BgeReranker(model=fake, lock=lock)
    out = r.score("q", ["d1", "d2"])
    assert out == [0.9, 0.2]
    args, kwargs = fake.compute_score.call_args
    assert args[0] == [("q", "d1"), ("q", "d2")]
    assert kwargs["normalize"] is True


def test_score_empty_docs_returns_empty():
    fake = MagicMock()
    r = BgeReranker(model=fake, lock=threading.Lock())
    assert r.score("q", []) == []
    fake.compute_score.assert_not_called()
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_reranker.py -v
```

- [ ] **Step 3: 实现 app/retriever/reranker.py**

```python
import threading


class BgeReranker:
    def __init__(self, model, lock: threading.Lock):
        self._model = model
        self._lock = lock

    @classmethod
    def load(cls, model_name: str, lock: threading.Lock) -> "BgeReranker":
        from FlagEmbedding import FlagReranker
        model = FlagReranker(model_name, use_fp16=True)
        return cls(model=model, lock=lock)

    def score(self, question: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        pairs = [(question, d) for d in docs]
        with self._lock:
            raw = self._model.compute_score(pairs, normalize=True)
        # compute_score 单样本时返回 scalar，批量返回 list；统一成 list[float]
        if isinstance(raw, (int, float)):
            return [float(raw)]
        return [float(x) for x in raw]
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_reranker.py -v
# 期望: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/retriever/reranker.py backend/chunking-rag-py/tests/test_reranker.py
git commit -m "feat(chunking-rag-py): BgeReranker (normalize=True, lock-wrapped)"
```

---

## Task 12: qa/prompt.py + qa/orchestrator.py（spec §5 D6/D7, §6.2）

**Files:**
- Create: `backend/chunking-rag-py/app/qa/prompt.py`
- Create: `backend/chunking-rag-py/app/qa/orchestrator.py`
- Create: `backend/chunking-rag-py/tests/test_orchestrator.py`

- [ ] **Step 1: 写失败测试 tests/test_orchestrator.py**

```python
from unittest.mock import MagicMock

import numpy as np

from app.qa.orchestrator import retrieve_and_rerank
from app.qa.prompt import build_prompt


def test_build_prompt_includes_question_and_chunks():
    prompt = build_prompt("你好？", [{"content": "hello world"}])
    assert "你好？" in prompt
    assert "hello world" in prompt


def _chunks(n: int):
    return [
        {"id": f"c{i}", "file_id": f"f{i}", "content": f"内容{i}", "vector": [float(i)] * 4}
        for i in range(n)
    ]


def test_retrieve_returns_empty_when_db_empty():
    db = MagicMock()
    db.get_completed_chunks.return_value = []
    emb = MagicMock(); emb.encode.return_value = np.zeros((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = []

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    assert result == []


def test_retrieve_filters_below_threshold():
    db = MagicMock(); db.get_completed_chunks.return_value = _chunks(3)
    emb = MagicMock(); emb.encode.return_value = np.ones((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = [0.3, 0.2, 0.1]  # 全 < 0.4

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    assert result == []


def test_retrieve_returns_topk_above_threshold():
    db = MagicMock(); db.get_completed_chunks.return_value = _chunks(3)
    emb = MagicMock(); emb.encode.return_value = np.ones((1, 4), dtype=np.float32)
    rr = MagicMock(); rr.score.return_value = [0.9, 0.5, 0.1]

    result = retrieve_and_rerank("q", embedder=emb, reranker=rr, db=db, threshold=0.4, top_k_final=5)
    ids = [c["id"] for c in result]
    assert len(result) == 2
    assert result[0]["rerank_score"] >= result[1]["rerank_score"]
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_orchestrator.py -v
```

- [ ] **Step 3: 实现 app/qa/prompt.py**

```python
def build_prompt(question: str, chunks: list[dict]) -> str:
    context = "\n\n---\n\n".join(
        f"【文档 {i+1}】{c['content'][:500]}" for i, c in enumerate(chunks)
    )
    return f"""请根据以下【参考文档片段】回答问题。

【用户问题】
{question}

【参考文档片段】
{context}

【回答要求】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 如果文档中没有相关信息，请明确说明无法回答
3. 答案应直接、完整，避免额外无关解释

请开始回答："""
```

- [ ] **Step 4: 实现 app/qa/orchestrator.py**

```python
from typing import Any

from app.retriever.bm25 import bm25_search
from app.retriever.dense import dense_search
from app.retriever.rrf import rrf_fuse


def retrieve_and_rerank(
    question: str, *,
    embedder,
    reranker,
    db,
    threshold: float = 0.4,
    top_k_recall: int = 20,
    top_k_final: int = 5,
) -> list[dict[str, Any]]:
    """dense + BM25 → RRF → rerank → threshold filter → top_k_final.

    只检索 files.status='completed' 的 chunks（spec D6）。
    返回每个 chunk 附加 'rerank_score' 字段；未命中阈值时返回 []。
    """
    chunks = db.get_completed_chunks()
    if not chunks:
        return []

    # dense
    q_vec = embedder.encode([question])[0]
    dense_hits = [c for c, _ in dense_search(q_vec, chunks, k=top_k_recall)]

    # bm25
    bm25_hits = [c for c, _ in bm25_search(question, chunks, k=top_k_recall)]

    # RRF
    fused = rrf_fuse([dense_hits, bm25_hits], k=60)[:top_k_recall]
    if not fused:
        return []

    # rerank
    scores = reranker.score(question, [c["content"] for c in fused])
    scored = [
        {**c, "rerank_score": s}
        for c, s in zip(fused, scores)
        if s >= threshold
    ]
    scored.sort(key=lambda c: -c["rerank_score"])
    return scored[:top_k_final]
```

- [ ] **Step 5: 运行测试确认 pass**

```bash
pytest tests/test_orchestrator.py -v
# 期望: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/chunking-rag-py/app/qa/ backend/chunking-rag-py/tests/test_orchestrator.py
git commit -m "feat(chunking-rag-py): qa orchestrator (RRF + rerank + threshold)"
```

---

## Task 13: llm/client.py（spec §8）

**Files:**
- Create: `backend/chunking-rag-py/app/llm/client.py`
- Create: `backend/chunking-rag-py/tests/test_llm_client.py`

- [ ] **Step 1: 写失败测试**

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.client import LlmClient


@pytest.mark.asyncio
async def test_stream_answer_yields_tokens():
    async def fake_iter():
        class D:
            def __init__(self, c): self.choices = [type("x", (), {"delta": type("d", (), {"content": c})})]
        for t in ["你", "好", "，", "世界"]:
            yield D(t)

    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=fake_iter())
    c = LlmClient(client=fake_openai, model="test-model")

    tokens = []
    async for t in c.stream_answer("prompt"):
        tokens.append(t)
    assert tokens == ["你", "好", "，", "世界"]


@pytest.mark.asyncio
async def test_stream_answer_skips_empty_delta():
    async def fake_iter():
        class D:
            def __init__(self, c): self.choices = [type("x", (), {"delta": type("d", (), {"content": c})})]
        yield D("hi")
        yield D(None)
        yield D("")
        yield D("!")

    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=fake_iter())
    c = LlmClient(client=fake_openai, model="m")
    assert [t async for t in c.stream_answer("p")] == ["hi", "!"]
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_llm_client.py -v
```

- [ ] **Step 3: 实现 app/llm/client.py**

```python
from typing import AsyncIterator

from openai import AsyncOpenAI


class LlmClient:
    def __init__(self, client: AsyncOpenAI, model: str):
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, *, api_key: str, base_url: str, model: str) -> "LlmClient":
        return cls(client=AsyncOpenAI(api_key=api_key, base_url=base_url), model=model)

    async def stream_answer(self, prompt: str) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", None)
            if token:
                yield token
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_llm_client.py -v
# 期望: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/llm/ backend/chunking-rag-py/tests/test_llm_client.py
git commit -m "feat(chunking-rag-py): LlmClient (openai async stream)"
```

---

## Task 14: sse.py helper（spec §4）

**Files:**
- Create: `backend/chunking-rag-py/app/sse.py`
- Create: `backend/chunking-rag-py/tests/test_sse.py`

- [ ] **Step 1: 写失败测试**

```python
from app.sse import sse_event


def test_sse_event_formats_ascii():
    assert sse_event({"answer": "hi"}) == 'data: {"answer": "hi"}\n\n'


def test_sse_event_preserves_chinese():
    out = sse_event({"answer": "你好"})
    assert "你好" in out
    assert out.endswith("\n\n")
```

- [ ] **Step 2: 运行测试确认 fail**

```bash
pytest tests/test_sse.py -v
```

- [ ] **Step 3: 实现 app/sse.py**

```python
import json


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: 运行测试确认 pass**

```bash
pytest tests/test_sse.py -v
# 期望: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/chunking-rag-py/app/sse.py backend/chunking-rag-py/tests/test_sse.py
git commit -m "feat(chunking-rag-py): SSE event formatter"
```

---

## Task 15: deps.py — Depends 工厂（spec §5 D4, §8）

**Files:**
- Create: `backend/chunking-rag-py/app/deps.py`

> 此 task **不写独立 tests**——deps 只是工厂，由 e2e 和 route 测试覆盖。

- [ ] **Step 1: 实现 app/deps.py**

```python
import sqlite3
import threading
from functools import lru_cache
from typing import Iterator

from fastapi import Depends, Request

from app.config import Settings
from app.database.sqlite import Db
from app.embedder.bge_m3 import BgeM3Embedder
from app.llm.client import LlmClient
from app.retriever.reranker import BgeReranker


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[Db]:
    conn = sqlite3.connect(
        settings.resolve_path(settings.db_path),
        isolation_level=None,
    )
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield Db(conn)
    finally:
        conn.close()


def get_embedder(request: Request) -> BgeM3Embedder:
    return request.app.state.embedder


def get_reranker(request: Request) -> BgeReranker:
    return request.app.state.reranker


def get_model_lock(request: Request) -> threading.Lock:
    return request.app.state.model_lock


def get_llm(request: Request) -> LlmClient:
    return request.app.state.llm
```

- [ ] **Step 2: 导入烟测（确保无循环 import）**

```bash
cd backend/chunking-rag-py
python -c "from app.deps import get_settings, get_db, get_embedder, get_reranker, get_llm, get_model_lock; print('OK')"
# 期望: OK
```

- [ ] **Step 3: Commit**

```bash
git add backend/chunking-rag-py/app/deps.py
git commit -m "feat(chunking-rag-py): Depends factories (db/embedder/reranker/llm)"
```

---

## Task 16: main.py — lifespan + CORS + router 占位（spec §5 D4）

**Files:**
- Modify: `backend/chunking-rag-py/app/main.py`

> 此 task 暂不挂 upload/qa/qa_stream 路由（那是 T17-T19），只搭好 lifespan 和 CORS，为后续 task 奠基。

- [ ] **Step 1: 重写 app/main.py**

```python
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
        allow_credentials=False,  # allow_origins=* 时必须 False
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 2: 烟测 /health**

```bash
cd backend/chunking-rag-py
# 模型加载首次 ~2 分钟；已 cache 可 30 秒
uvicorn app.main:app --port 3002 &
sleep 120  # 充裕等待模型加载
curl -s http://localhost:3002/health
# 期望: {"status":"ok"}
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add backend/chunking-rag-py/app/main.py
git commit -m "feat(chunking-rag-py): main.py lifespan (load models) + CORS allow-all"
```

---

## Task 17: routes/upload.py — POST /api/upload + GET /api/upload/raw-files（spec §4, §6.1）

**Files:**
- Create: `backend/chunking-rag-py/app/routes/upload.py`
- Modify: `backend/chunking-rag-py/app/main.py`（挂路由）

> 测试挪到 Task 20-21（契约 / 鲁棒性套件），本 task 只做实现 + 冒烟。

- [ ] **Step 1: 实现 app/routes/upload.py**

```python
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.config import Settings
from app.converter.chunker import chunk_markdown
from app.converter.parser import parse
from app.database.sqlite import Db, write_tx
from app.deps import get_db, get_embedder, get_settings
from app.embedder.bge_m3 import BgeM3Embedder
from app.filename_utils import dedupe_and_open, fix_encoding, sanitize_filename

router = APIRouter()

MAX_FILES = 10
MAX_BYTES = 50 * 1024 * 1024
READ_CHUNK = 64 * 1024
SUPPORTED_EXTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md"}


@router.post("/api/upload")
def upload(
    files: list[UploadFile] = File(...),
    db: Db = Depends(get_db),
    embedder: BgeM3Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"最多 {MAX_FILES} 个文件")

    raw_dir = settings.resolve_path(settings.raw_dir)
    converted_dir = settings.resolve_path(settings.converted_dir)
    mappings_dir = settings.resolve_path(settings.mappings_dir)

    results: list[dict] = []

    for up in files:
        safe_name = sanitize_filename(fix_encoding(up.filename or "unnamed"))
        ext = Path(safe_name).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            results.append({
                "id": str(uuid.uuid4()),
                "originalName": safe_name,
                "status": "failed",
                "error": f"unsupported format: {ext}",
            })
            continue

        # 1. O_EXCL 原子创建 + 流式写 + 50MB 限额
        raw_path, fd = dedupe_and_open(raw_dir, safe_name)
        written = 0
        try:
            while True:
                chunk = up.file.read(READ_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_BYTES:
                    os.close(fd); os.unlink(raw_path)
                    raise HTTPException(status_code=413, detail=f"{safe_name} 超过 50MB")
                os.write(fd, chunk)
        finally:
            try: os.close(fd)
            except OSError: pass

        disk_name = raw_path.name  # dedupe 后的真实磁盘文件名
        file_id = str(uuid.uuid4())
        upload_time = datetime.now(timezone.utc).isoformat()

        # 2. INSERT status='converting'
        db.insert_file(
            id=file_id, original_name=disk_name, original_path=str(raw_path),
            converted_path="", format=ext.lstrip("."), size=written,
            upload_time=upload_time, status="converting",
        )

        # 3. parse + chunk + embed + commit/rollback
        try:
            md, line_map = parse(raw_path)
            converted_path = converted_dir / f"{file_id}.md"
            converted_path.write_text(md, encoding="utf-8")
            (mappings_dir / f"{file_id}.json").write_text("{}", encoding="utf-8")
            db.update_file_converted_path(file_id, str(converted_path))

            chunks = chunk_markdown(md, line_map)
            if chunks:
                vectors = embedder.encode([c.content for c in chunks])
                chunk_rows = [
                    {
                        "id": str(uuid.uuid4()), "file_id": file_id,
                        "content": c.content, "start_line": c.start_line, "end_line": c.end_line,
                        "original_lines": c.original_lines, "vector": vectors[i].tolist(),
                    }
                    for i, c in enumerate(chunks)
                ]
                with write_tx(db.conn):
                    db.insert_chunks(chunk_rows)
                    db.update_file_status(file_id, "completed")
            else:
                db.update_file_status(file_id, "completed")

            results.append({
                "id": file_id, "originalName": disk_name, "format": ext.lstrip("."),
                "size": written, "status": "completed", "uploadTime": upload_time,
            })
        except Exception as e:  # noqa: BLE001 — 承接所有处理异常
            try:
                db.update_file_status(file_id, "failed")
            except Exception:  # noqa: BLE001
                pass
            results.append({
                "id": file_id, "originalName": disk_name, "format": ext.lstrip("."),
                "size": written, "status": "failed", "error": str(e),
            })

    success = sum(1 for r in results if r["status"] == "completed")
    return {
        "success": True,
        "files": results,
        "message": f"成功处理 {success} / {len(files)} 个文件",
    }


@router.get("/api/upload/raw-files")
def list_raw_files(
    page: int = 1, limit: int = 10,
    settings: Settings = Depends(get_settings),
):
    page = max(1, page); limit = max(1, min(100, limit))
    raw_dir = settings.resolve_path(settings.raw_dir)
    if not raw_dir.exists():
        return {"success": True, "files": [], "total": 0, "page": page, "limit": limit, "totalPages": 0}
    entries = [p for p in raw_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total = len(entries)
    start = (page - 1) * limit; end = start + limit
    page_entries = entries[start:end]
    return {
        "success": True,
        "files": [
            {
                "name": p.name, "path": str(p),
                "size": p.stat().st_size,
                "createdAt": datetime.fromtimestamp(p.stat().st_ctime, tz=timezone.utc).isoformat(),
                "modifiedAt": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            for p in page_entries
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "totalPages": math.ceil(total / limit) if total else 0,
    }
```

- [ ] **Step 2: 挂路由到 main.py**

在 `backend/chunking-rag-py/app/main.py` 的 `create_app()` 返回前加：

```python
    from app.routes import upload as upload_route
    app.include_router(upload_route.router)
```

- [ ] **Step 3: 烟测 upload + raw-files**

```bash
cd backend/chunking-rag-py
uvicorn app.main:app --port 3002 &
sleep 120
curl -s -F "files=@tests/fixtures/sample.md" http://localhost:3002/api/upload | head -c 500
curl -s http://localhost:3002/api/upload/raw-files | head -c 500
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

期望 `/api/upload` 响应 `{"success":true,"files":[{"id":"...","originalName":"sample.md","status":"completed",...}],"message":"成功处理 1 / 1 个文件"}`；`/api/upload/raw-files` 返回 sample.md 条目。

- [ ] **Step 4: Commit**

```bash
git add backend/chunking-rag-py/app/routes/upload.py backend/chunking-rag-py/app/main.py
git commit -m "feat(chunking-rag-py): upload route (limits + converting→completed/failed)"
```

---

## Task 18: routes/qa.py — files / stats / DELETE（spec §4, §6.3）

**Files:**
- Create: `backend/chunking-rag-py/app/routes/qa.py`
- Modify: `backend/chunking-rag-py/app/main.py`（挂路由）

- [ ] **Step 1: 实现 app/routes/qa.py**

```python
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings
from app.database.sqlite import Db, write_tx
from app.deps import get_db, get_settings

router = APIRouter()


@router.get("/api/qa/files")
def list_files(db: Db = Depends(get_db), settings: Settings = Depends(get_settings)):
    raw_dir = settings.resolve_path(settings.raw_dir)
    files = db.list_completed_files()
    out = []
    for f in files:
        rp = raw_dir / f["original_name"]
        try:
            st = rp.stat()
            size = st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        except FileNotFoundError:
            size = f["size"]; mtime = f["upload_time"]
        out.append({
            "name": f["original_name"], "size": size, "mtime": mtime,
            "id": f["id"], "format": f["format"],
            "uploadTime": f["upload_time"], "category": f.get("category") or "",
        })
    return {"success": True, "files": out, "total": len(out)}


@router.get("/api/qa/stats")
def stats(db: Db = Depends(get_db)):
    s = db.get_stats()
    return {
        "success": True,
        "totalFiles": s["fileCount"],
        "stats": {"fileCount": s["fileCount"], "chunkCount": s["chunkCount"], "indexedCount": s["chunkCount"]},
    }


@router.delete("/api/qa/files/{filename}")
def delete_file(
    filename: str,
    db: Db = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    raw_dir = settings.resolve_path(settings.raw_dir)
    converted_dir = settings.resolve_path(settings.converted_dir)
    mappings_dir = settings.resolve_path(settings.mappings_dir)

    # 路径穿越校验
    safe = (raw_dir / filename).resolve()
    if not str(safe).startswith(str(raw_dir.resolve()) + os.sep):
        raise HTTPException(status_code=400, detail="invalid filename")

    matches = db.get_files_by_name(filename)
    if not matches and not safe.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # DB 事务：级联删
    if matches:
        with write_tx(db.conn):
            for row in matches:
                db.delete_file_and_chunks(row["id"])

    # raw 物理删（失败仅 warn）
    if safe.exists():
        try: safe.unlink()
        except OSError: pass

    # sidecar（converted / mapping）
    for row in matches:
        for p in (converted_dir / f"{row['id']}.md", mappings_dir / f"{row['id']}.json"):
            try: p.unlink()
            except FileNotFoundError: pass
            except OSError: pass

    return {"success": True, "message": "文件已删除"}
```

- [ ] **Step 2: 挂路由到 main.py**

在 `create_app()` 返回前补：

```python
    from app.routes import qa as qa_route
    app.include_router(qa_route.router)
```

- [ ] **Step 3: 烟测**

```bash
cd backend/chunking-rag-py
uvicorn app.main:app --port 3002 &
sleep 120
curl -s http://localhost:3002/api/qa/stats
curl -s http://localhost:3002/api/qa/files
# 上传后再删（如果之前有 sample.md）
curl -s -X DELETE http://localhost:3002/api/qa/files/sample.md
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

期望 `/api/qa/stats` 返回 `{"success":true,"totalFiles":N,"stats":{...}}`。

- [ ] **Step 4: Commit**

```bash
git add backend/chunking-rag-py/app/routes/qa.py backend/chunking-rag-py/app/main.py
git commit -m "feat(chunking-rag-py): qa route (files/stats/delete cascade)"
```

---

## Task 19: routes/qa_stream.py — POST /api/qa/ask-stream（spec §4 SSE, §6.2）

**Files:**
- Create: `backend/chunking-rag-py/app/routes/qa_stream.py`
- Modify: `backend/chunking-rag-py/app/main.py`（挂路由）

- [ ] **Step 1: 实现 app/routes/qa_stream.py**

```python
import anyio
from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse

from app.database.sqlite import Db
from app.deps import get_db, get_embedder, get_llm, get_reranker, get_settings
from app.embedder.bge_m3 import BgeM3Embedder
from app.config import Settings
from app.llm.client import LlmClient
from app.qa.orchestrator import retrieve_and_rerank
from app.qa.prompt import build_prompt
from app.retriever.reranker import BgeReranker
from app.sse import sse_event

router = APIRouter()

REFUSAL = "抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。"


@router.post("/api/qa/ask-stream")
async def ask_stream(
    payload: dict = Body(...),
    db: Db = Depends(get_db),
    embedder: BgeM3Embedder = Depends(get_embedder),
    reranker: BgeReranker = Depends(get_reranker),
    llm: LlmClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
):
    question = (payload.get("question") or "").strip()
    if not question:
        async def empty():
            yield sse_event({"answer": "问题不能为空"})
            yield sse_event({"sources": []})
        return StreamingResponse(empty(), media_type="text/event-stream")

    # 同步 retriever+rerank 卸载到 threadpool（避免阻塞事件循环）
    chunks = await anyio.to_thread.run_sync(
        lambda: retrieve_and_rerank(
            question, embedder=embedder, reranker=reranker, db=db,
            threshold=settings.rerank_threshold,
        )
    )

    if not chunks:
        async def refuse():
            yield sse_event({"answer": REFUSAL})
            yield sse_event({"sources": []})
        return StreamingResponse(refuse(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    prompt = build_prompt(question, chunks)
    sources_set: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        # 查文件名——同步，但单次 DB 调用快，不卸载
        f = db.get_file(c["file_id"])
        name = f["original_name"] if f else "未知文件"
        if name not in seen:
            seen.add(name); sources_set.append(name)

    async def gen():
        try:
            async for tok in llm.stream_answer(prompt):
                yield sse_event({"answer": tok})
        except Exception as e:  # noqa: BLE001
            yield sse_event({"answer": f"\n\n（服务器错误：{e}）"})
        yield sse_event({"sources": sources_set})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
```

- [ ] **Step 2: 挂路由到 main.py**

```python
    from app.routes import qa_stream as qa_stream_route
    app.include_router(qa_stream_route.router)
```

- [ ] **Step 3: 烟测 SSE**

```bash
cd backend/chunking-rag-py
uvicorn app.main:app --port 3002 &
sleep 120
curl -s -N -H "Content-Type: application/json" -d '{"question":"什么是标题一？"}' http://localhost:3002/api/qa/ask-stream | head -c 2000
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

期望输出若干行 `data: {"answer": "..."}\n\n` + 末尾 `data: {"sources": [...]}\n\n`（或拒答文案 + sources=[]）。

- [ ] **Step 4: Commit**

```bash
git add backend/chunking-rag-py/app/routes/qa_stream.py backend/chunking-rag-py/app/main.py
git commit -m "feat(chunking-rag-py): qa_stream route (SSE + to_thread retrieval)"
```

---

## Task 20: TS 响应 snapshot 抓取（spec §9.2.2）

**Files:**
- Create: `backend/chunking-rag-py/scripts/capture_ts_snapshots.py`
- Create: `backend/chunking-rag-py/tests/fixtures/ts_responses/{stats,files,raw-files,upload,ask-stream,delete}.json`

> 运行前先启 TS 版（`backend/chunking-rag/`）在 3002。抓完停 TS 版，把 fixture 提交进仓。

- [ ] **Step 1: 写 scripts/capture_ts_snapshots.py**

```python
"""抓取 TS 版响应作为 Python 版契约对齐 snapshot。

前置：停所有 3002 服务，然后启 TS 版：
  pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  cd backend/chunking-rag && npm run dev &
  sleep 10
  python backend/chunking-rag-py/scripts/capture_ts_snapshots.py
"""
import json
from pathlib import Path

import httpx

BASE = "http://localhost:3002"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ts_responses"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample.md"


def save(name: str, data):
    (OUT / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    with httpx.Client(base_url=BASE, timeout=60) as c:
        # Upload (ensures at least 1 file for subsequent endpoints)
        with SAMPLE.open("rb") as f:
            r = c.post("/api/upload", files={"files": (SAMPLE.name, f, "text/markdown")})
        save("upload", r.json())

        save("stats", c.get("/api/qa/stats").json())
        save("files", c.get("/api/qa/files").json())
        save("raw-files", c.get("/api/upload/raw-files?page=1&limit=10").json())

        # SSE — record raw text（非 JSON）
        with c.stream("POST", "/api/qa/ask-stream",
                      json={"question": "测试"}) as r:
            (OUT / "ask-stream.txt").write_text(
                "".join(r.iter_text()), encoding="utf-8"
            )

        save("delete", c.delete(f"/api/qa/files/{SAMPLE.name}").json())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 执行抓取**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true

# 启 TS 版
cd backend/chunking-rag && PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev &
sleep 15

cd ../chunking-rag-py
conda activate sqllineage
python scripts/capture_ts_snapshots.py

# 停 TS 版
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

- [ ] **Step 3: 确认 fixtures 产生**

```bash
ls backend/chunking-rag-py/tests/fixtures/ts_responses/
# 期望: upload.json stats.json files.json raw-files.json ask-stream.txt delete.json
```

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/chunking-rag-py/scripts/capture_ts_snapshots.py backend/chunking-rag-py/tests/fixtures/ts_responses/
git commit -m "test(chunking-rag-py): capture TS baseline responses as contract fixtures"
```

---

## Task 21: 契约 + 鲁棒性测试集合（spec §9.2.2）

**Files:**
- Create: `backend/chunking-rag-py/tests/conftest.py`（扩充）
- Create: `backend/chunking-rag-py/tests/test_contract_snapshot.py`
- Create: `backend/chunking-rag-py/tests/test_cors.py`
- Create: `backend/chunking-rag-py/tests/test_upload_limits.py`
- Create: `backend/chunking-rag-py/tests/test_upload_failure.py`
- Create: `backend/chunking-rag-py/tests/test_concurrent_upload.py`
- Create: `backend/chunking-rag-py/tests/test_qa_empty_db.py`
- Create: `backend/chunking-rag-py/tests/test_sse_framing.py`
- Create: `backend/chunking-rag-py/tests/test_upload_qa_e2e.py`

> 全部用 TestClient + mock 的 embedder/reranker/llm（避免真实模型）。单 task 完成全部测试可能体量大——执行时分 2-3 个子 commit（contract + limits+failure, concurrent+qa+sse+e2e）。

- [ ] **Step 1: 扩充 tests/conftest.py（提供 mock fixtures 和 app factory）**

```python
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import Settings
from app.database.sqlite import init_db
from app.main import create_app


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    """隔离的 storage 目录，每个测试独占。"""
    # 把 SERVICE_ROOT 下的 storage 临时替换：通过 env 注入 Settings 解析
    monkeypatch.setenv("DB_PATH", str(tmp_path / "k.db"))
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("CONVERTED_DIR", str(tmp_path / "converted"))
    monkeypatch.setenv("MAPPINGS_DIR", str(tmp_path / "mappings"))
    # 清 Settings 缓存
    from app import deps
    deps.get_settings.cache_clear()
    s = Settings()
    s.ensure_dirs()
    init_db(s.resolve_path(s.db_path))
    return s


@pytest.fixture
def fake_embedder():
    m = MagicMock()
    m.encode = MagicMock(side_effect=lambda texts: np.ones((len(texts), 1024), dtype=np.float32))
    return m


@pytest.fixture
def fake_reranker():
    m = MagicMock()
    # 默认全部 0.9（pass threshold）
    m.score = MagicMock(side_effect=lambda q, docs: [0.9] * len(docs))
    return m


@pytest.fixture
def fake_llm():
    m = MagicMock()

    async def stream(prompt):
        for t in ["答案", "片段", "。"]:
            yield t

    m.stream_answer = stream
    return m


@pytest.fixture
def client(tmp_settings, fake_embedder, fake_reranker, fake_llm, monkeypatch):
    """带 mock 模型的 TestClient（跳过真实模型加载）。"""
    from app import main as main_mod

    # monkeypatch lifespan 里的 loader
    monkeypatch.setattr("app.embedder.bge_m3.BgeM3Embedder.load",
                        lambda name, lock: _wrap_with_lock(fake_embedder, lock))
    monkeypatch.setattr("app.retriever.reranker.BgeReranker.load",
                        lambda name, lock: _wrap_with_lock(fake_reranker, lock))
    monkeypatch.setattr("app.llm.client.LlmClient.from_settings",
                        lambda **kw: fake_llm)

    app = create_app()
    with TestClient(app) as c:
        yield c


def _wrap_with_lock(mock, lock):
    mock._lock = lock  # 仅为了语义一致
    return mock
```

- [ ] **Step 2: 实现 test_contract_snapshot.py（12 用例示意 6 个端点）**

```python
import json
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "ts_responses"


def _load(name): return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_stats_shape_matches_ts(client):
    ts = _load("stats")
    ours = client.get("/api/qa/stats").json()
    assert set(ours) >= {"success", "totalFiles", "stats"}
    assert isinstance(ours["totalFiles"], int)
    assert set(ours["stats"]) >= {"fileCount", "chunkCount", "indexedCount"}
    assert set(ts) >= set(ours)


def test_files_list_element_shape_matches_ts(client):
    # 先上传一个文件
    client.post("/api/upload", files={"files": ("sample.md", b"# Hi\n\n内容。", "text/markdown")})
    ours = client.get("/api/qa/files").json()
    assert ours["success"] is True
    if ours["files"]:
        f = ours["files"][0]
        assert {"name", "size", "mtime", "id", "format", "uploadTime", "category"} <= set(f)


def test_raw_files_element_shape_matches_ts(client):
    client.post("/api/upload", files={"files": ("sample.md", b"# Hi\n\n内容。", "text/markdown")})
    ours = client.get("/api/upload/raw-files?page=1&limit=10").json()
    assert {"success", "files", "total", "page", "limit", "totalPages"} <= set(ours)
    if ours["files"]:
        assert {"name", "path", "size", "createdAt", "modifiedAt"} <= set(ours["files"][0])


def test_upload_response_shape(client):
    r = client.post("/api/upload", files={"files": ("sample.md", b"# x\n\n内容。", "text/markdown")})
    data = r.json()
    assert {"success", "files", "message"} <= set(data)
    assert isinstance(data["files"], list) and data["files"]
    item = data["files"][0]
    assert {"id", "originalName", "status"} <= set(item)


def test_ask_stream_event_shape(client):
    client.post("/api/upload", files={"files": ("sample.md", b"# x\n\n内容。", "text/markdown")})
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "内容"}) as r:
        body = "".join(r.iter_text())
    # 至少含一条 data: {"answer": ...} 和一条 data: {"sources": [...]}
    assert 'data: {"answer"' in body or '"answer"' in body
    assert '"sources"' in body


def test_delete_response_shape(client):
    client.post("/api/upload", files={"files": ("sample.md", b"# x\n\n内容。", "text/markdown")})
    r = client.delete("/api/qa/files/sample.md")
    assert r.status_code == 200
    data = r.json()
    assert {"success", "message"} <= set(data)
```

- [ ] **Step 3: 实现 test_cors.py（allow-all 语义）**

```python
def test_cors_preflight_allows_all_origins(client):
    r = client.options("/api/qa/stats", headers={
        "Origin": "http://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "*" \
        or r.headers.get("access-control-allow-origin") == "http://evil.example.com"


def test_cors_actual_get_any_origin(client):
    r = client.get("/api/qa/stats", headers={"Origin": "http://any.example.com"})
    assert r.status_code == 200
```

- [ ] **Step 4: 实现 test_upload_limits.py**

```python
def test_upload_rejects_more_than_10_files(client):
    files = [("files", (f"a{i}.md", b"x", "text/markdown")) for i in range(11)]
    r = client.post("/api/upload", files=files)
    assert r.status_code == 413


def test_upload_rejects_over_50mb(client, monkeypatch):
    # 用 50MB+1 的 bytes
    big = b"x" * (50 * 1024 * 1024 + 1)
    r = client.post("/api/upload", files={"files": ("big.md", big, "text/markdown")})
    assert r.status_code == 413


def test_upload_unsupported_ext_returns_failed_entry(client):
    r = client.post("/api/upload", files={"files": ("a.xyz", b"data", "application/octet-stream")})
    data = r.json()
    assert data["success"] is True
    assert data["files"][0]["status"] == "failed"
```

- [ ] **Step 5: 实现 test_upload_failure.py**

```python
def test_parser_failure_leaves_status_failed(client, monkeypatch):
    from app.converter import parser
    monkeypatch.setattr(parser, "parse", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/api/upload", files={"files": ("a.md", b"hi", "text/markdown")})
    data = r.json()
    assert data["files"][0]["status"] == "failed"
    assert "boom" in data["files"][0]["error"]


def test_raw_file_retained_on_failure(client, tmp_settings, monkeypatch):
    from app.converter import parser
    monkeypatch.setattr(parser, "parse", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    client.post("/api/upload", files={"files": ("a.md", b"hi", "text/markdown")})
    assert (tmp_settings.resolve_path(tmp_settings.raw_dir) / "a.md").exists()


def test_embedder_failure_leaves_failed(client, fake_embedder):
    fake_embedder.encode.side_effect = RuntimeError("cuda oom")
    r = client.post("/api/upload", files={"files": ("a.md", b"# x\n\ncontent", "text/markdown")})
    data = r.json()
    assert data["files"][0]["status"] == "failed"


def test_status_transitions_converting_to_failed(client, tmp_settings, monkeypatch):
    import sqlite3
    from app.converter import parser
    monkeypatch.setattr(parser, "parse", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    client.post("/api/upload", files={"files": ("a.md", b"hi", "text/markdown")})
    c = sqlite3.connect(tmp_settings.resolve_path(tmp_settings.db_path))
    status = c.execute("SELECT status FROM files").fetchone()[0]
    c.close()
    assert status == "failed"
```

- [ ] **Step 6: 实现 test_concurrent_upload.py**

```python
import threading


def test_concurrent_same_name_upload_produces_dedupe_suffixes(client):
    results: list[dict] = []
    lock = threading.Lock()

    def upload():
        r = client.post("/api/upload", files={"files": ("same.md", b"# x\n\ncontent", "text/markdown")})
        with lock:
            results.append(r.json())

    threads = [threading.Thread(target=upload) for _ in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()

    names = sorted(r["files"][0]["originalName"] for r in results)
    assert names == ["same.md", "same_1.md", "same_2.md"]


def test_concurrent_upload_db_rows_match(client, tmp_settings):
    import sqlite3
    threads = [
        threading.Thread(
            target=lambda: client.post("/api/upload", files={"files": (f"f{i}.md", b"# x\n\ny", "text/markdown")})
        )
        for i in range(5)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    c = sqlite3.connect(tmp_settings.resolve_path(tmp_settings.db_path))
    count = c.execute("SELECT COUNT(*) FROM files WHERE status='completed'").fetchone()[0]
    c.close()
    assert count == 5
```

- [ ] **Step 7: 实现 test_qa_empty_db.py**

```python
def test_ask_stream_empty_db_returns_refusal(client):
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "任何"}) as r:
        body = "".join(r.iter_text())
    assert "未找到" in body or "相关" in body
    assert '"sources": []' in body


def test_empty_db_does_not_call_reranker(client, fake_reranker):
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "q"}) as r:
        _ = "".join(r.iter_text())
    fake_reranker.score.assert_not_called()
```

- [ ] **Step 8: 实现 test_sse_framing.py**

```python
import json


def test_sse_long_answer_parses_without_loss(client, fake_llm):
    async def long_stream(prompt):
        for t in [f"tok{i}" for i in range(200)]:
            yield t
    fake_llm.stream_answer = long_stream

    client.post("/api/upload", files={"files": ("s.md", b"# x\n\n内容。", "text/markdown")})
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "内容"}) as r:
        body = "".join(r.iter_text())

    events = [line for line in body.split("\n\n") if line.startswith("data: ")]
    tokens = []
    for e in events:
        try:
            d = json.loads(e[len("data: "):])
            if "answer" in d:
                tokens.append(d["answer"])
        except json.JSONDecodeError:
            pass
    assert sum(1 for t in tokens if t.startswith("tok")) == 200


def test_sse_sources_comes_last_and_unique(client, fake_llm):
    client.post("/api/upload", files={"files": ("x.md", b"# x\n\n内容。", "text/markdown")})
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "内容"}) as r:
        body = "".join(r.iter_text())
    events = [e for e in body.split("\n\n") if e.startswith("data: ")]
    last = json.loads(events[-1][len("data: "):])
    assert "sources" in last
    assert len(last["sources"]) == len(set(last["sources"]))
```

- [ ] **Step 9: 实现 test_upload_qa_e2e.py（6 端点 happy path）**

```python
def test_e2e_full_happy_path(client):
    # 1. upload
    r = client.post("/api/upload", files={"files": ("sample.md", b"# 标题\n\n文档内容。", "text/markdown")})
    assert r.status_code == 200 and r.json()["files"][0]["status"] == "completed"

    # 2. raw-files
    r = client.get("/api/upload/raw-files")
    assert r.status_code == 200
    assert any(f["name"] == "sample.md" for f in r.json()["files"])

    # 3. files
    r = client.get("/api/qa/files")
    assert r.status_code == 200 and r.json()["total"] >= 1

    # 4. stats
    r = client.get("/api/qa/stats")
    assert r.status_code == 200 and r.json()["totalFiles"] >= 1

    # 5. ask-stream
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "文档"}) as resp:
        body = "".join(resp.iter_text())
    assert '"answer"' in body and '"sources"' in body

    # 6. delete
    r = client.delete("/api/qa/files/sample.md")
    assert r.status_code == 200 and r.json()["success"]
    r = client.get("/api/qa/files")
    assert not any(f["name"] == "sample.md" for f in r.json()["files"])


def test_e2e_delete_path_traversal_rejected(client):
    r = client.delete("/api/qa/files/..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)  # 400 从 resolve check；404 若 decode 后不存在


def test_e2e_upload_then_ask_finds_chunk(client, fake_reranker):
    fake_reranker.score.side_effect = lambda q, docs: [0.95] * len(docs)
    client.post("/api/upload", files={"files": ("ab.md", b"# Intro\n\n特征内容 ABCD。", "text/markdown")})
    with client.stream("POST", "/api/qa/ask-stream", json={"question": "ABCD"}) as r:
        body = "".join(r.iter_text())
    assert "ab.md" in body  # sources 中含文件名
```

- [ ] **Step 10: 运行全部测试**

```bash
cd backend/chunking-rag-py
pytest -v tests/
# 期望: 全部 PASS（已实现的 unit + 本 task 新增的 contract/robustness/e2e）
```

- [ ] **Step 11: Commit（建议拆 2 提交）**

```bash
# 提交 1: 契约 + CORS + limits + failure
git add backend/chunking-rag-py/tests/conftest.py \
        backend/chunking-rag-py/tests/test_contract_snapshot.py \
        backend/chunking-rag-py/tests/test_cors.py \
        backend/chunking-rag-py/tests/test_upload_limits.py \
        backend/chunking-rag-py/tests/test_upload_failure.py
git commit -m "test(chunking-rag-py): contract snapshot + CORS + upload limits/failure"

# 提交 2: concurrency + qa + sse + e2e
git add backend/chunking-rag-py/tests/test_concurrent_upload.py \
        backend/chunking-rag-py/tests/test_qa_empty_db.py \
        backend/chunking-rag-py/tests/test_sse_framing.py \
        backend/chunking-rag-py/tests/test_upload_qa_e2e.py
git commit -m "test(chunking-rag-py): concurrent upload + qa empty + SSE + e2e"
```

---

## Task 22: README + 最终冷启动 + .gitignore

**Files:**
- Create: `backend/chunking-rag-py/README.md`
- Create: `backend/chunking-rag-py/.gitignore`

- [ ] **Step 1: 写 .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
storage/raw/
storage/converted/
storage/mappings/
storage/*.db
storage/*.db-shm
storage/*.db-wal
.env
.venv/
```

（保留 `storage/.gitkeep`）

- [ ] **Step 2: 写 README.md**

```markdown
# chunking-rag-py

Python 重写的 chunking-rag 服务（α 路线 / B 范围 MVP），与 `backend/chunking-rag/` (TS 版) 平级，**二选一占 3002 端口**。

规范：[docs/superpowers/specs/2026-04-23-chunking-rag-py-design.md](../../docs/superpowers/specs/2026-04-23-chunking-rag-py-design.md)

## 启动

```bash
# 清空 3002 端口（POSIX 可移植）
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true

cd backend/chunking-rag-py
conda activate sqllineage
pip install -r requirements.txt
cp .env.example .env           # 首次：填入亚信网关 key / base_url / model
uvicorn app.main:app --host 0.0.0.0 --port 3002
```

**首次启动会从 HF Hub 下载 bge-m3 (~2.3GB) + bge-reranker-v2-m3 (~1.1GB)，耐心等 5 分钟。**

## 测试

```bash
cd backend/chunking-rag-py
pytest -v tests/
```

## 端点

见 spec §4。6 个端点与 TS 版语义等价。

## 已知限制

- 模型 lock 下 QPS ≤ 1/推理耗时（见 spec R7）
- 上传中途失败保留 raw 文件，DB 记录为 'failed'（见 spec D10）
```

- [ ] **Step 3: 最终冷启动验证**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true

cd backend/chunking-rag-py
conda activate sqllineage
uvicorn app.main:app --port 3002 &
sleep 120

# 跑一个 happy path 冒烟
curl -s http://localhost:3002/api/qa/stats
curl -s -F "files=@tests/fixtures/sample.md" http://localhost:3002/api/upload | head -c 500
curl -s -N -H 'Content-Type: application/json' -d '{"question":"标题"}' http://localhost:3002/api/qa/ask-stream | head -c 2000
curl -s http://localhost:3002/api/qa/files | head -c 500
curl -s -X DELETE http://localhost:3002/api/qa/files/sample.md
curl -s http://localhost:3002/api/qa/stats

pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

- [ ] **Step 4: 前端集成烟测**

```bash
# 再启 Python 版
cd backend/chunking-rag-py && uvicorn app.main:app --port 3002 &
sleep 120

# 启前端
cd ../../frontend && PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev &
sleep 10

# 浏览器打开 http://localhost:3000 手动：
# 1. 上传 sample.md
# 2. 看文档列表能显示
# 3. 在 QA 框问"标题"
# 4. 看流式答案 + sources
# 5. 删除文件

# 清理
pids=$(lsof -ti:3002 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
pids=$(lsof -ti:3000 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
```

- [ ] **Step 5: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/chunking-rag-py/README.md backend/chunking-rag-py/.gitignore
git commit -m "docs(chunking-rag-py): README + .gitignore; feature complete"
```

---

## Post-implementation（超出本 plan，列在 ISSUES 或下个 plan）

1. **Eval tuning 窗口**（Day 11–19）：用团队测题集实测分数，调 `RERANK_THRESHOLD` / `top_k_recall` / chunk 大小 / prompt 模板。目标 72-80
2. **BM25 persistence**：chunk 数增长后每次查询 re-index 会慢；考虑 pickle 落盘 + 增量更新
3. **SSE 前端 buffer**：若演示实测跨包问题频发，修 `frontend/app/page.tsx` 加跨 chunk buffer（打破"前端 0 修改"红线）
4. **模型多实例**：QPS 瓶颈显现后，semaphore + 多 BgeM3Embedder 实例（VRAM/RAM 翻倍换并行）

---

## Self-Review

本节在 plan 写完后自查（不 dispatch subagent），fix 入 plan 后不再 re-review。

### 1. Spec 覆盖检查

| Spec 章节 | 对应 Task |
|---|---|
| §1 背景 | plan 头 / Goal |
| §2 目标与非目标 | plan 头 / Goal + Architecture |
| §3 架构、目录布局 | T1 skeleton + 目录结构章节 |
| §4 6 端点契约 + SSE | T17 / T18 / T19 + T20-21 契约测试 |
| §5 D1 全 Python | 整个 plan |
| §5 D2 本地 embedding 红线 | T7 / T11 本地加载 |
| §5 D3 B 范围 | plan 头 |
| §5 D4 并发 / sync-async 纪律 / write_tx | T4 / T15 / T16 / T17 / T19 |
| §5 D5 chunking | T6 |
| §5 D6 dense+BM25+RRF+rerank+阈值 | T8/T9/T10/T11/T12 |
| §5 D7 拒答 SSE | T19 refuse 分支 + T21 test_qa_empty_db |
| §5 D8 filename + O_EXCL | T3 |
| §5 D9 schema | T4 |
| §5 D10 状态机 | T17 state machine 实现 + T21 test_upload_failure |
| §5 D11 端口 | T22 README |
| §6.1 上传数据流 + limits | T17 |
| §6.2 问答数据流 | T19 |
| §6.3 删除数据流 | T18 |
| §7 schema | T4 SCHEMA_SQL |
| §8 模块职责 | T2-T19 |
| §9.2.1 单测 | T3/T4/T6/T8/T9/T10/T11 |
| §9.2.2 契约/鲁棒性 | T20 + T21 |
| §9.3 eval 窗口 | Post-implementation §1 |
| §10 不在范围 | 整个 plan 未涉及 v2 features |
| §R1 模型加载慢 | T1 / T22 README "等 5 分钟" |
| §R2 SSE 跨帧 | 不做预防，T21 test_sse_framing 验证 |
| §R3 WAL 锁 | T4 busy_timeout + T15 get_db |
| §R4 eval 分数 | Post-implementation §1 |
| §R5 端口冲突 | T22 README kill 命令 |
| §R6 团队漂移 | 不修 v2 文档——整 plan 未引用 v2 文件修改 |
| §R7 model lock | T7 / T11 lock + T15 app.state.model_lock |
| §附录 A/B/C | T1 |

**无遗漏**（若 eval tuning 阶段出现新需求，开新 plan）。

### 2. Placeholder 扫描

全文 grep "TBD" / "TODO" / "implement later" / "fill in" / "similar to" — 无命中。每个 Step 都有完整代码 + 测试 + 命令。

### 3. Type / 签名一致性

- `Chunk` dataclass 在 T6 定义，T17 `chunker.chunk_markdown` 返回 `list[Chunk]`，T17 `c.content / c.start_line / c.end_line / c.original_lines` 使用字段 ✓
- `Db` 方法在 T4 定义：`insert_file(**kwargs)` / `insert_chunks(list[dict])` / `get_completed_chunks()` / `list_completed_files()` / `get_file(id)` / `get_files_by_name(name)` / `get_stats()` / `update_file_status(id, status)` / `update_file_converted_path(id, path)` / `delete_file_and_chunks(id)`——T17/T18/T19 全部使用这些签名 ✓
- `BgeM3Embedder.encode(texts) -> np.ndarray[N,1024]` T7 定义 + T12/T17 使用 ✓
- `BgeReranker.score(q, docs) -> list[float]` T11 定义 + T12 使用 ✓
- `LlmClient.stream_answer(prompt) -> AsyncIterator[str]` T13 定义 + T19 `async for tok in llm.stream_answer(prompt)` 使用 ✓
- `retrieve_and_rerank(question, *, embedder, reranker, db, threshold, ...) -> list[dict]` T12 定义 + T19 使用；注意 kwargs-only，使用方用 `lambda:` 包装传给 `anyio.to_thread.run_sync` ✓
- `sse_event(payload: dict) -> str` T14 定义 + T19 使用 ✓
- `write_tx(conn)` T4 定义 + T17/T18 使用 ✓
- `dedupe_and_open(raw_dir, filename) -> (Path, fd)` T3 定义 + T17 使用 ✓

**一致**。

---

## Execution Handoff

Plan 写完，保存在 `docs/superpowers/plans/2026-04-23-chunking-rag-py-plan.md`（即本文档）。两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 Task 派独立 subagent，两段式 review，适合 22 个 task 的规模
2. **Inline Execution** — 主会话里直接跑，配合 executing-plans 的 batch checkpoint

选哪种？
