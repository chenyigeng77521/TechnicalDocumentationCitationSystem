# chunking-rag Service

完整 RAG 服务：文档切分 + SQLite 存储 + 关键词/语义检索 + LLM 问答 + 三阶段 upload 状态机。

基于 `feature/chunking-mvp` 分支的 v1 代码改造而来，服务于 `frontend/` 的问答界面。

## 架构关系

```
项目根/
├── backend/                            ← 同事的文件管理 demo（端口 3002）
├── frontend/                           ← 硬编码连 localhost:3002
└── backend/chunking-rag/         ← 本服务（端口 3002，完整 RAG）
    └── storage/                        ← 服务自包含存储
        ├── raw/                        上传文件
        ├── converted/                  转换后 markdown
        ├── mappings/                   行号映射
        └── knowledge.db                SQLite
```

**团队约定**：每人独立目录，互不依赖对方代码。本服务所有状态（上传文件 + DB + 转换产物）都在 `backend/chunking-rag/storage/` 里自包含；同事 backend 用自己的 `backend/storage/raw/`。两套数据池互相不可见。

**端口冲突**：`backend/` 和本服务都绑 3002，同一时刻只能一个在跑。约定为"谁演示谁启动"。

## 启动

```bash
# 先确保 3002 没被占
lsof -ti:3002 | xargs kill -9 2>/dev/null

cd backend/chunking-rag
cp .env.example .env     # 首次；配 LLM_API_KEY 可选
npm install              # 首次
npm run dev              # tsx hot reload
```

前端：
```bash
cd frontend
npm run dev              # port 3000
```

浏览器打开 http://localhost:3000。

## 端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /api/upload` | 文件上传（自动转换 + 切分 + 入库 + 三阶段状态机） |
| `GET /api/upload/raw-files?page=N&limit=M` | `storage/raw/` 分页列表 |
| `GET /api/qa/files` | 已切分文件列表，返回 `{name, size, mtime, id, format, uploadTime, category}` |
| `GET /api/qa/stats` | 统计（`totalFiles`, `stats.fileCount`, `stats.chunkCount`, `stats.indexedCount`） |
| `POST /api/qa/ask-stream` | SSE 流式问答，发 `data: {answer}` token + 最后 `data: {sources}` |
| `POST /api/qa/ask` | 非流式问答（v1 遗留） |
| `POST /api/qa/search` | 仅检索（v1 遗留） |
| `POST /api/qa/index` | 触发批量向量化（v1 遗留，空库返回 warning） |
| `DELETE /api/qa/files/:filename` | 级联删除（raw + DB + converted/mappings sidecar），`:filename` 是磁盘文件名（= D2b 约束下的 DB original_name） |

## 环境变量

见 `.env.example`。关键项：
- `PORT=3002`（与 frontend 硬编码一致）
- `UPLOAD_DIR=./storage/raw`（服务私有，相对 cwd）
- `DB_PATH=./storage/knowledge.db`（服务私有）
- `LLM_API_KEY=...`（可选；不配置时走拒答 + 关键词检索路径）
- `EMBEDDING_MODEL`、`EMBEDDING_DIMENSION` —— 向量化模型
- `STRICT_MODE=true` —— 严格模式，只基于文档回答

## 测试 & 构建

```bash
# Node 20 必需（通过 nvm 管理）
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm test     # 14 个 chunker 单测
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build # TS 编译，2 个 pre-existing 错误容忍
```

`npm run build` 会报 2 个 pre-existing TS 错误（`converter/index.ts:208` Buffer 类型、`llm/index.ts:2` 缺失导出）—— 从 v1 继承来，tsx 运行时不受影响。

## 与同事 backend 的关系

- **完全独立**：不读不写同事目录，同事代码也一行没改（按团队约定"每人独立目录"）
- **功能差异**：同事 backend 只做文件管理（上传+列表+删除），本服务功能是其超集 + 完整 RAG（切分/检索/LLM 问答）
- **前端共用**：同事 frontend 硬编码 `localhost:3002`，所以演示时两服务二选一启动，前端无需修改

## 设计文档

- [2026-04-23 chunking-rag service integration design](../../docs/superpowers/specs/2026-04-23-chunking-rag-service-design.md)
- [Implementation plan](../../docs/superpowers/plans/2026-04-23-chunking-rag-service.md)
- [E2E test baseline (2026-04-23)](../../docs/superpowers/plans/chunking-rag-e2e-2026-04-23.txt)
- [v1 chunking MVP spec](../../docs/superpowers/specs/2026-04-22-chunking-mvp-design.md)
