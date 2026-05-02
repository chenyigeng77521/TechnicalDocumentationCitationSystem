# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Technical Documentation Citation System — a multi-service RAG application for indexing technical docs (Word, Excel, PDF, PowerPoint, Markdown, AsciiDoc, code, txt) and answering questions with citations traced back to source paragraphs (with anchor links).

This is **not a monolith**. It is a polyglot stack: a TypeScript gateway, several Python FastAPI services, and a Next.js frontend. The team uses a **Layer 1 / Layer 2 / Layer 3** vocabulary that maps to specific subdirectories — when reading code or specs, that framing matters more than the directory name.

## Service Topology

| Port | Service | Path | Stack | Role |
|---|---|---|---|---|
| 3000 | frontend | `frontend/` | Next.js 16 + React 19 + Tailwind 4 + Zustand 5 | UI (chat, upload, file dashboard) |
| 3002 | entrance | `backend/entrance/` | TypeScript / Express (ESM) | API gateway — fronts upload + Q&A, fans out to firstlayer + ingestion + reasoning |
| 3003 | ingestion (Layer 1) | `backend/ingestion/` | Python / FastAPI | Parse → chunk → embed (bge-m3) → SQLite (FTS5 + vector). Owns `backend/storage/` |
| 3004 | category_classifier | `backend/firstlayer/category_classifier/` | Python / FastAPI | Question category routing |
| 3005 | question_filter | `backend/firstlayer/question_filter/` | Python / FastAPI | Pre-filter (block out-of-scope questions) |
| 3006 | context_memory | `backend/firstlayer/context_memory/` | Python / FastAPI | Last-30 Q&A session memory |
| —    | LLM / retrieval (Layer 2) | `backend/LLM/retrieval.py` | Python module | Hybrid retrieval: vector + BM25 (RRF) + reranker. Calls ingestion's `/chunks/*` HTTP API |
| 8001 | reasoning (Layer 3) | `backend/reasoning/` | Python / FastAPI | LLM answer generation with structured citations; calls `retrieval.pipeline()` directly |

**Request flow (typical Q&A)**: frontend → entrance (gates with question_filter / category_classifier) → reasoning → retrieval (LLM/) → ingestion (`/chunks/vector-search` + `/chunks/text-search`).

**Request flow (upload)**: frontend → entrance `/api/upload` → writes to `backend/storage/raw/` → calls ingestion `/index`.

## Commands

### Local dev (full stack, native processes — NOT Docker)
```bash
./startAll.sh     # builds + starts nginx + all backend services + frontend
./stopAll.sh      # stops everything started by startAll.sh
./buildAll.sh     # invoked by startAll.sh; builds frontend + entrance
./devStart.sh     # dev variant
./dev.sh          # entrance (3002) + frontend (3000) only — fastest loop, skips Python services
```

`startAll.sh` orchestrates Python services with `nohup python3.12 app.py` and writes per-service logs to `logs/`. It does NOT use Docker; all processes run on the host.

### Entrance (TypeScript gateway)
```bash
cd backend/entrance
npm install
npm run dev       # tsx hot reload on :3002
npm run build     # tsc → dist/
npm start         # node dist/server.js
```

Note: `backend/entrance/src/server.ts` resolves `.env` at `../.env` (i.e. `backend/.env`), then dynamically imports `./config.js` so dotenv loads before any module reads `process.env`. **Don't reorder these imports.**

### Ingestion (Python, Layer 1)
```bash
conda activate sqllineage     # paddleocr/paddlepaddle pin requires this env
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
python -m backend.ingestion.api.server     # foreground
# or:
backend/ingestion/start.sh --bg            # background, PID at backend/ingestion/logs/server.pid

# Tests (pytest, asyncio_mode=auto, pythonpath=../..):
cd backend/ingestion && pytest tests/unit -v
cd backend/ingestion && pytest tests/integration -v
cd backend/ingestion && pytest tests/unit/test_routes_upload.py::test_specific_case -v
```

The `/upload` endpoint on this service is feature-flagged for joint testing only — set `INGESTION_UPLOAD_ENABLED=true` before `start.sh` to register it. In production, upload goes through entrance, not here.

### FirstLayer services
Each (`category_classifier/`, `question_filter/`, `context_memory/`) has its own `start.sh` and `requirements.txt`. They are **invoked with a hardcoded interpreter path**: `/usr/local/Homebrew/Cellar/python@3.12/3.12.13_1/bin/python3.12`. If you're not on this machine, edit the start scripts or run `python3.12 app.py` directly.

### Reasoning (Python, Layer 3)
```bash
cd backend/reasoning
pip install -r requirements.txt
python main.py                # uvicorn on :8001
```
Uses an OpenAI-compatible LLM (default DeepSeek). Configure via `backend/reasoning/.env` (`LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`).

### Frontend
```bash
cd frontend
npm install
npm run dev       # Next.js dev on :3000
npm run build
npm run lint
```

## Architecture Notes

### Embedding & retrieval
- Model: **`BAAI/bge-m3`**, dim = **1024**, must be normalized (`normalize_embeddings=True`) on **both** index and query side. Old code/config referencing OpenAI `text-embedding-3-large` (1536 dim) is stale.
- The query-side embedding is computed in `backend/LLM/retrieval.py` (Layer 2), not in ingestion. Ingestion exposes `/chunks/vector-search` that takes a 1024-float array — caller is responsible for the embedding.
- BM25 is via SQLite FTS5 with `unicode61` tokenizer + **application-side jieba pre-tokenization** registered as a SQLite UDF (`jieba_tokenize`) in `db/connection.py`. Trigger writes pre-tokenized text into `chunks_fts` on insert. This is intentional — it fixes long-Chinese-query 0-recall and short-English 3-gram bias.
- Hybrid fusion is RRF (Reciprocal Rank Fusion) over the two result lists; use `bm25_rank` (FTS5 raw, negative) for rank-based fusion, NOT the `score` field.

### Database
- Single SQLite DB owned by ingestion (`backend/storage/index/...`). Schema in `backend/ingestion/db/schema.sql`. Created idempotently on startup (`CREATE TABLE IF NOT EXISTS`); **no migration tool**.
- Tables: `documents` (file metadata, hashes, index_version), `chunks` (content + metadata + JSON-text embedding), `chunks_fts` (FTS5 virtual). FK from chunks → documents with `ON DELETE CASCADE`.
- The `chunks.embedding` column is JSON text, not a binary vector — vector search currently does Python-side full-table cosine (~100ms for <10k chunks). sqlite-vec upgrade is on the roadmap.
- `chunks.markdown_anchor` is the section anchor (`#section-id` or `#top`) used by frontend deep-linking.

### File-path convention (critical)
In ingestion's API and DB, `file_path` is **relative to `backend/storage/raw/`, without the `raw/` prefix**. Example: a file at `backend/storage/raw/api/auth.md` is stored as `file_path = "api/auth.md"`. `anchor_id = "{file_path}#{char_offset_start}"`.

### Storage layout (`backend/storage/`)
- `raw/` — uploaded source files (entrance writes here; ingestion reads)
- `docs/` — converted markdown (some pipelines emit here)
- `index/` — SQLite DB lives here

### Entrance gateway gating
`backend/entrance/src/config.ts` exposes runtime-resolved getters for downstream service URLs. Two flags toggle whether the gateway calls the firstlayer services at all:
- `ENABLE_QUESTION_CLASSIFICATION` — default off (must be `'true'`)
- `ENABLE_QUESTION_FILTER` — default **on** (only off when set to `'false'`)

When developing entrance without the Python services running, set both to `false` to avoid timeout failures.

### Cross-service contract
The canonical interface contract for ingestion is **`backend/ingestion/INTERFACE.md`**. It defines the field shapes Layer 2 / 3 expect (`metadata.file_path`, `anchor_id`, `title_path`, etc.) and the alignment with `backend/reasoning/interfaces.py::ChunkMetadata`. Read it before changing any HTTP shape touching `/chunks/*`, `/index`, `/files`.

## Project Conventions

### Plans and specs (superpowers workflow)
This repo follows the superpowers brainstorming → plan → execution workflow. Documents live under:
- `docs/superpowers/specs/` — design specs (one per feature, dated)
- `docs/superpowers/plans/` — implementation plans
- `docs/superpowers/progress/` — execution progress logs
- `docs/superpowers/reports/` — review / postmortem reports

Plans use a **白话 (plain-Chinese)** style — see the `brainstorming`, `writing-plans`, `executing-plans`, and `subagent-driven-development` skills available in this session. They override the default superpowers skills for this user.

### What's legacy
- `backend/back/chunking-rag/` and `backend/back/chunking-rag-py/` — earlier monolithic implementations of the chunking + RAG pipeline. Not wired into the current service mesh. Don't add to them; the work has moved to `backend/ingestion/`.

### Module style
- TypeScript backend (entrance) is **ESM**: `import`/`export`, target ES2022, `"type": "module"`. Imports of compiled output use `.js` suffix even when the source is `.ts`.
- Frontend is Next.js 16.2.4 + React 19 — note that some Next 15-era APIs have moved/changed. The `frontend/node_modules/next/dist/docs/` tree is checked for migration notes when modifying frontend.
- Python services are FastAPI + Pydantic v2; ingestion uses `pythonpath=../..` so imports look like `backend.ingestion.api.server`.

### Deployment quirk (offline judge env)
The production target is x86 Linux **without internet**. Both `BAAI/bge-m3` (~2 GB, HuggingFace) and `PP-OCR-v5` (~200 MB, Baidu BOS) must be pre-downloaded and baked into the Docker image at build time, or the first request crashes. See `backend/ingestion/README.md` for the pre-download script.

## Environment

Two `.env` files matter:
- `backend/.env` — read by entrance (gateway). Sets `PORT`, `HOST`, downstream service URLs (`FIRSTLAYER_URL`, `QUESTION_FILTER_URL`, `INGESTION_URL`), and feature flags.
- `backend/reasoning/.env` — read by Layer 3 only. Sets `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`, `LLM_TIMEOUT`.

Frontend uses `frontend/.env.local`; in production it points at `/api` (relative, behind nginx).

## Health checks

Each service exposes `/health`:
- entrance: `http://localhost:3002/health`
- ingestion: `http://localhost:3003/health` (`embedding_model_loaded` flips true after first `/index` triggers bge-m3 lazy load, ~15s)
- firstlayer / reasoning: same convention on their respective ports