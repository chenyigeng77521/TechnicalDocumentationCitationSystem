# src/ — 技术文档引用系统源码目录

> 本目录包含系统全部前后端源码、构建脚本及运行时配置。  
> 项目根目录的 `data/docs/` 存放原始技术文档，`eval/` 存放评测与批量结果。

---

## 目录结构

```text
src/
├── backend/           # 后端服务集群
│   ├── entrance/      # 入口网关层 (Express, :3002)
│   ├── firstlayer/    # 第一层智能服务
│   │   ├── category_classifier/   # 问题分类 (:3004)
│   │   ├── context_memory/        # 上下文记忆 (:3006)
│   │   └── question_filter/       # 问题过滤 (:3005)
│   ├── ingestion/     # 数据处理与索引层 (FastAPI, :3003)
│   ├── reasoning/     # RAG 推理问答层 (FastAPI, :8001)
│   ├── retrieval/     # 双路混合检索模块 (被 reasoning 调用)
│   └── storage/       # 持久化存储目录 (索引、结果、批量测试)
├── frontend/          # 前端应用 (Next.js, :3000)
├── logs/              # 运行时日志
├── .env               # 运行时环境变量
├── .env.example       # 环境变量模板
├── .env.aigw.example  # AIGW 网关配置模板
├── nginx.conf         # Nginx 反向代理配置
├── buildAll.sh        # 全量构建脚本
└── devStart.sh        # 开发环境一键启动脚本
```

---

## 架构概览

```
上传 / 文件系统
       │
       ▼
┌─────────────────────────────────────────────────┐
│              数据处理层（Layer 1）                 │
│                                                  │
│  entrance 上传       外部 cp 文件到 raw/           │
│      │                      │                   │
│      └──────┬───────────────┘                   │
│             ▼  (watchdog debounce 1s)           │
│       index_pipeline（asyncio.Lock 文件级互斥锁）   │
│             │                                    │
│    ┌────────▼────────┐                           │
│    │  文档解析        │  ← 全 Python              │
│    │  parse_document │    PyMuPDF / python-docx  │
│    └────────┬────────┘    / openpyxl             │
│             │                                    │
│    ┌────────▼────────┐                           │
│    │  Chunker         │  MVP: document 三级 fallback│
│    │  (MVP)           │  code/structured_data → P1│
│    └────────┬────────┘                           │
│             │                                    │
│    MVP: 全删重写              P1: chunk-level diff │
│             │                                    │
│    batch embed（concurrency=8，本地 bge-m3）       │
│    （无 rate limit，MVP 固定并发）                  │
│             │                                    │
│    ┌────────▼────────────────────────────┐       │
│    │         SQLite                       │       │
│    │  chunks 表 + FTS5（BM25）+ 向量列     │       │
│    │  documents 元数据表（index_version）  │       │
│    └────────────────────────────────────┘       │
│                                                  │
│    WebSocket 进度推送（P1，MVP 同步等返回）          │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│              检索增强层（Layer 2）                │
│                                                 │
│    LLM 同义变体 + Bing 英译 + 每变体独立检索       │
│                         │                       │
│    双路召回（HTTP API → ingestion）               │
│    POST /chunks/vector-search（bge-m3 本地 embed）│
│    POST /chunks/text-search（BM25 / FTS5）       │
│                         │                       │
│    合并去重（_merge_results，保留双路分数）         │
│                         │                       │
│    Reranker 精排（bge-reranker-v2-m3）           │
│    API / 本地 CrossEncoder 双模式                │
│    Sigmoid 映射到 (0,1) + 相邻 chunk 上下文扩展   │
│                         │            a         │
│    ┌────────────────────┴──────────────┐        │
│    │     max_score < 0.4？             │        │
│   YES                                NO         │
│    │                                  │         │
│  直接拒答                     进入 LLM 推理        │
└─────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│              推理与引用层（Layer 3）               │
│                                                 │
│         上下文注入 → LLM 推理 → 引用验证            │
│                                                 │            
└─────────────────────────────────────────────────┘
                         │
                         ▼
              返回响应 + WebUI 展示（Layer 4）
```

### 请求流向说明

| 层级 | 模块 | 调用关系 |
|------|------|----------|
| Layer 4 | frontend | → entrance (`:3002`) |
| Layer 0 | entrance | → question_filter (`:3005`) → reasoning (`:8001`) |
| Layer 0 | entrance | → category_classifier (`:3004`) / context_memory (`:3006`) / NLU Pipeline (`:3004`)（可选） |
| Layer 0 | entrance | → ingestion (`:3003`) 文件索引/删除/查询 |
| Layer 3 | reasoning | → retrieval（`sys.path` 动态导入，内部调用 ingestion 检索 API） |
| Layer 2 | retrieval | → ingestion (`:3003`) `/chunks/vector-search` + `/chunks/text-search` |
| Layer 1 | ingestion | → SQLite (`knowledge.db`) 读写 |

---

## 各模块说明

### backend/entrance — 入口网关层
- **技术栈**：Express 4 + TypeScript 5.3
- **端口**：`:3002`
- **核心职责**：
  - 接收前端 HTTP / SSE 请求
  - 文件上传、下载、删除（联动 ingestion 索引一致性）
  - 批量测试文件接收与结果管理
  - 流式日志推送 (`/api/logs/stream`)
  - 向下游服务（firstlayer / reasoning）转发并编排调用链

### backend/firstlayer — 第一层智能服务
包含三个独立微服务，均可独立启停：

| 子模块 | 端口 | 技术栈 | 职责 |
|--------|------|--------|------|
| `category_classifier` | `:3004` | Python + FastAPI | 问题分类、NLU 指代消解、查询重写 |
| `question_filter` | `:3005` | Python + FastAPI | 无效问题过滤、完整性检查 |
| `context_memory` | `:3006` | Python + FastAPI | 多轮会话历史管理、上下文记忆 |

### backend/ingestion — 数据处理与索引层 (Layer 1)
- **技术栈**：Python + FastAPI + SQLite(FTS5)
- **端口**：`:3003`
- **数据库**：`backend/storage/index/knowledge.db`（统一进 `backend/storage/`，跟 raw 平级）
- **监听目录**：`backend/storage/raw/`（与 entrance 共用，entrance 上传后调 `POST /index`）
- **代码组织**：
  - `parser/` — 9 种格式解析器（md / txt / html / pdf / docx / xlsx / pptx / adoc / pdf扫描）
  - `chunker/` — 文本切块（三级 fallback：标题 → 段落 → 句子 → 硬切）
  - `db/` — SQLite 读写（连接 `backend/storage/index/knowledge.db`）
  - `sync/` — 增量同步 + 5min SLA（pipeline / file_lock / watchdog / gc）
  - `api/` — FastAPI 路由（写入侧 + 检索侧）
  - `common/` — 共享工具（embedding / errors / logger）
- **核心职责**：
  - 按扩展名分派解析器，扫描 PDF 降级 PaddleOCR
  - 文本三级 fallback 切块（`MAX_CHARS=1000`，相邻块 `OVERLAP=200`，过滤 `< 30 char`）
  - `bge-m3` 向量化写入（`normalize_embeddings=True`，懒加载，batch 8）
  - 对外暴露写入接口（`POST /index`、`DELETE /files`）与检索接口（`POST /chunks/vector-search`、`POST /chunks/text-search`、`GET /chunks/{id}`）
  - X1.5 section 合并策略（同章节命中内容聚合，可开关 `INGESTION_X15_ENABLED`）
- **增量同步（MVP 简化版）**：
  - 路径 A：entrance 上传后主动调 `POST /index`
  - 路径 B：watchdog 监听 `raw/` 目录，debounce 1s 兜底
  - hash 没变 → 返回 `unchanged`；hash 变了 → 删旧 chunks 全删重写（不做 chunk-level diff）
  - 启动时全扫 GC + 每小时定时清理孤儿 chunks
- **对外契约**：见 `backend/ingestion/INTERFACE.md`

### backend/reasoning — RAG 推理问答层
- **技术栈**：Python + FastAPI + OpenAI 兼容接口
- **端口**：`:8001`
- **核心职责**：
  - 单条问答 (`POST /api/qa`) 与批量问答 (`POST /api/qa/batch`)
  - 4 步推理 Pipeline：可回答性判定 → Context 构建 → LLM 推理 → 引用校验
  - 引用 ID 合法性校验，拒绝 LLM 幻觉编造
  - 拒答机制（低分 / 空检索 / JSON 解析失败等场景自动降级）
- **依赖下游**：动态导入 `backend/retrieval/retrieval.py`

### backend/retrieval — 双路混合检索模块
- **技术栈**：Python + LangChain + SentenceTransformers
- **调用方式**：被 reasoning 层通过 `sys.path` 动态导入，**无独立端口**
- **核心职责**：
  - 向量检索（Cosine）+ BM25 全文检索混合去重
  - 查询扩展（LLM 生成变体 + 中译英）
  - CrossEncoder / API 重排序 + 上下文扩展
  - 自适应 TopK 动态截断

### backend/storage — 存储目录
- `index/` — 索引相关持久化数据
- `batch/` / `batchtest/` — 批量测试上传与结果
- `result/` — 评测结果文件

### frontend — 前端应用
- **技术栈**：Next.js 14 + React + TypeScript + Tailwind CSS
- **端口**：`:3000`
- **核心页面**：
  - 智能问答页（SSE 流式输出、引用溯源）
  - 文件管理页（上传、下载、在线编辑、删除）
  - 批量测试页（文件上传、结果下载）
- **API 代理**：开发期通过 Next.js rewrites 指向 entrance (`:3002`)，生产环境走 Nginx

---

## 环境变量

全局配置位于 `src/.env`，各模块也有独立 `.env`。关键变量：

| 变量 | 作用域 | 说明 |
|------|--------|------|
| `INGESTION_X15_ENABLED` | ingestion | X1.5 section 合并开关 |
| `LLM_API_KEY` / `LLM_API_BASE` | reasoning | 大模型 API 密钥与地址 |
| `VECTOR_API_URL` | retrieval | 向量库服务地址 |
| `AIGW_API_KEY` | embedding | AIGW 平台网关密钥（可选） |

完整模板参见：
- `src/.env.example` — 通用模板
- `src/.env.aigw.example` — AIGW 网关专用模板

---

## 快速开始

### 1. 安装依赖

```bash
# 前端
cd src/frontend && npm install

# ingestion 层
cd src/backend/ingestion
pip install -r requirements.txt

# reasoning 层
cd src/backend/reasoning
pip install -r requirements.txt

# retrieval 层（依赖与 reasoning 共用，或单独安装）
cd src/backend/retrieval
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制模板并填写真实密钥
cp src/.env.example src/.env
cp src/.env.aigw.example src/.env.aigw
```

### 3. 启动服务

```bash
# 方式一：开发一键启动（项目根目录执行）
bash src/devStart.sh

# 方式二：手动逐个启动
cd src/backend/ingestion && bash start.sh --bg
cd src/backend/reasoning && python main.py
cd src/backend/entrance && npm run dev
cd src/frontend && npm run dev
```

### 4. 验证

| 服务 | 健康检查地址 | 预期响应 |
|------|-------------|---------|
| entrance | `http://localhost:3002/health` | `{"status":"ok"}` |
| ingestion | `http://localhost:3003/health` | `{"status":"ok","db_writable":true}` |
| reasoning | `http://localhost:8001/health` | `{"status":"ok","service":"layer3-reasoning"}` |

### 5. 内网访问入口
```
http://10.1.235.73
```
---

## 构建与部署

```bash
# 全量构建（前端 + entrance）
bash src/buildAll.sh

# 生产启动 entrance
cd src/backend/entrance && npm start

# Nginx 反向代理（生产环境）
# 配置参考 src/nginx.conf
```

---

## 端口一览

| 服务 | 端口 | 协议 |
|------|------|------|
| frontend (Next.js) | `3000` | HTTP |
| entrance (Express) | `3002` | HTTP + SSE |
| ingestion (FastAPI) | `3003` | HTTP |
| category_classifier | `3004` | HTTP |
| question_filter | `3005` | HTTP |
| context_memory | `3006` | HTTP |
| reasoning (FastAPI) | `8001` | HTTP |

---

## 相关文档

| 文档 | 路径 | 内容 |
|------|------|------|
| ingestion 接口契约 | `backend/ingestion/INTERFACE.md` | 对外 HTTP API 详细说明 |
| ingestion README | `backend/ingestion/README.md` | 数据层设计决策与快速上手 |
| reasoning README | `backend/reasoning/README.md` | 推理 Pipeline 与配置说明 |
| retrieval README | `backend/retrieval/README.md` | 检索模块功能与使用示例 |
| entrance README | `backend/entrance/README.md` | 网关路由与下游依赖说明 |
| 架构设计 | `docs/layer1-design-v2.md` | 系统总体架构设计 |
| 评测报告 | `自测报告/latest_evaluation_metrics.md` | 最新评测指标 |
