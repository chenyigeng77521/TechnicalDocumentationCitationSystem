# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

技术文档智能问答与引用溯源系统（Asiainfo 比赛项目）。多服务 RAG 系统，4 层架构：
- **Layer 0** firstlayer/ — 问题过滤、分类、上下文记忆（独立 FastAPI 服务）
- **Layer 1** ingestion/ — 文档解析 + chunking + embedding 入库 + 检索接口（FastAPI :3003）
- **Layer 2** retrieval/ — 双路混合检索（向量 + BM25）+ 查询扩展 + 重排序
- **Layer 3** reasoning/ — RAG 推理 + 引用溯源（FastAPI :8001）
- **entrance** — Express 网关，编排所有下游（:3002）
- **frontend** — Next.js 16 / React 19（:3000）

实际服务实现在 `src/backend/<module>/`，**不是**根目录的 `backend/`（`backend/ingestion/logs/` 是空遗留）。

## 端口分配（不要混淆）

| 端口 | 服务 |
|---|---|
| 80 | Nginx 反代（生产）|
| 3000 | frontend (Next.js) |
| 3002 | entrance (Express) |
| 3003 | ingestion (Layer 1) |
| 3004 | category_classifier |
| 3005 | question_filter |
| 3006 | context_memory |
| 8001 | reasoning (Layer 3) |

## 常用命令

### 一键启停（推荐）
```bash
bash scripts/startAll.sh   # 全栈启动（含 nginx + 6 个服务 + 前后端）
bash scripts/stopAll.sh    # 全栈停止（按端口 kill）
```
启动前先 `conda activate sqllineage`（让 PATH 里 `python` 指向 env）。`startAll.sh` 内部用 `which python`，不会自动激活 conda。

### 单模块启停
```bash
bash src/backend/ingestion/start.sh --bg   # ingestion 单独启动
bash src/backend/ingestion/stop.sh
bash src/backend/reasoning/start.sh --bg
```

### 测试
```bash
# Ingestion 测试（pytest，pythonpath 在 src/backend/ingestion/pytest.ini 已配）
cd src/backend/ingestion && pytest tests/unit -v
cd src/backend/ingestion && pytest tests/integration -v
cd src/backend/ingestion && pytest tests/unit/test_chunker.py::test_xxx -v   # 单测

# Entrance（Jest）
cd src/backend/entrance && npm test

# Eval（端到端 RAG 评分，调 LLM 判分）
cd eval && python score.py --gold ../docs/Public_Test_Set.jsonl \
  --results ../src/backend/reasoning/storage/result/result_react_001.jsonl \
  --out reports/<run_id>
```

### 构建 / dev
```bash
bash src/buildAll.sh                       # 编译 frontend + entrance（tsc + next build）
cd src/backend/entrance && npm run dev     # tsx 热重载
cd src/frontend && npm run dev             # Next dev
```

`./dev.sh`（项目根）是**老脚本**，只起 entrance + frontend（端口仍是 3002/3000），不带 ingestion / reasoning / firstlayer，调试 RAG 链路时不要用。

## Python 环境

- **conda env: `sqllineage` (Python 3.12.4)** —— 全部 Python 工作都在这里跑，不起 venv / uv
- 关键依赖：`paddleocr 3.x` + `paddlepaddle 3.x`（OCR 降级），`sentence-transformers` + `BAAI/bge-m3`（embedding，1024 维，**必须 `normalize_embeddings=True`**），`jieba`（FTS5 分词），`fastapi`
- `requirements.txt` 分模块在 `src/backend/<mod>/requirements.txt`
- bge-m3 模型懒加载（首次 `/index` 调用 ~15 秒）

## 关键约定

| 项 | 值 |
|---|---|
| Embedding | `BAAI/bge-m3` / 1024 维 / normalize=True |
| `file_path` 格式 | 相对项目根 `data/` 的路径，含 `docs/<domain>/` 前缀，例：`docs/react/incremental-adoption.md`（必须与赛题 jsonl `gold_sources[].doc_path` 对齐）|
| `chunk_id` | `sha256(file_path|chunk_index|content[:100])` hex |
| `anchor_id` | `{file_path}#{char_offset_start}` — 旧版前端跳转锚点 |
| `markdown_anchor` | 章节级锚点，**赛题判分按这个字段**，例：`#data-fetching` / `#本地临时存储的配额` / `#api-发起驱逐` / `#top`（无 heading 时） |
| 中文 anchor 规则 | 原文中文保留 ✅ ／ 空格转 `-` ✅ ／ 英文部分小写 ✅ ／ ❌ 不拼音化 ／ ❌ 不 punycode ／ ❌ 不丢空格信息 |
| Score | 向量 cosine ∈ [0,1]，BM25 归一化 ∈ (0,1] |

## Ingestion API（外部主调）

- `POST /chunks/vector-search` — 调用方传入 query embedding（bge-m3+normalize），返 top_k
- `POST /chunks/text-search` — FTS5 BM25 全文检索（jieba 预分词）
- `POST /index?add=<path>` / `?modify=` / `?delete=` — 增量索引（**评分硬要求**：评委评测当场新增/改/删文档 5 分钟内提问验证，build-once 模式直接 0 分）
- `GET /chunks/{chunk_id}` / `GET /stats` / `GET /health`

完整文档见 `src/backend/ingestion/INTERFACE.md`。

## 仓库布局陷阱

- 真正的源码在 `src/`，根目录 `backend/` 仅含一个空 `ingestion/logs/`（无视）
- 数据库文件 `src/backend/database/knowledge.db`（SQLite + WAL + FTS5）
- 测试数据：`docs/Public_Test_Set.jsonl`（200 题黄金集）/ `docs/Public_Test_Sample10.jsonl`
- 评测结果：`src/backend/reasoning/storage/result/`，评测报告：`eval/reports/`
- 设计 spec / plan：`docs/superpowers/{specs,plans,progress,reports}/`（不是 `架构文档/`）
- 老 `backend/` 目录不要新建文件进去；新代码一律写到 `src/backend/<module>/`

## 部署到无外网评委环境

bge-m3 (~2GB, HuggingFace) 和 PP-OCR-v5 (~200MB, 百度 BOS) 必须在镜像构建阶段预下载（`~/.cache/huggingface/` 和 `~/.paddlex/`），否则首启崩。详见 `src/backend/ingestion/README.md` 的 Docker 段。

## 已知架构特性

- ingestion `parser/` 按文件类型分发（pdf/docx/pptx/xlsx/html/md/adoc/txt），扫描 PDF 走 PaddleOCR 降级
- **Spring `.adoc` 走 regex 手写解析**（识别 `=` 标题 + `[[xxx]]` 显式锚点），**不用 asciidoctor / asciidoc3**（重 + 依赖 Ruby/JVM，无外网部署成本高）；React/K8s `.md` 走 markdown_parser（识别 trailing `{#xxx}` / `{/*xxx*/}`）。改 .adoc 别用通用 markdown 解析跑——会把 `==` 当 H2 但漏 `[[anchor-id]]`，anchor 全错
- chunker 含 `quality_filter`（过滤低质量 chunk）+ `overlap`（句号正则，注意有空格列表粘连 bug，参考 `docs/superpowers/specs/2026-04-29-*`）
- retrieval 走 ingestion 的 HTTP 接口，不直连 DB；reasoning 通过 `sys.path` 动态 import retrieval
- entrance 流式问答走 SSE：`POST /api/qa/ask-stream` → question_filter → category_classifier → reasoning(:8001)
- 评测 `eval/score.py` 会用 AIGW（`src/.env.aigw` 里 `AIGW_API_KEY`）调 DeepSeek 当裁判，结果缓存到 `eval/cache/<sha>.json`

## 已知问题清单

`ISSUES.md` 在跟踪 BUG / MISSING / STALE，按 P0/P1/P2 优先级排。改动前先扫一眼避免重复发现。
