# backend/ingestion/ — Layer 1 数据处理层

> **一句话**：把 `data/` 下的各种格式文档（md / pdf / docx / xlsx / pptx / html / adoc / txt）解析、切块、向量化，落库到 SQLite + FTS5，对外暴露 HTTP 检索接口。
>
> **端口**：`:3003` ｜ **服务名**：Ingestion Service ｜ **owner**：涂祎豪
> **对外接口契约**：见同目录 [`INTERFACE.md`](./INTERFACE.md)（573 行，给海军/陈一赓的对接文档，本 README 不重复）

---

## 1. 在系统里的位置

```
        ┌───────────┐
        │  frontend │  :3000
        └─────┬─────┘
              │
        ┌─────▼─────┐
        │  entrance │  :3002  (Express 网关)
        └─────┬─────┘
              │
   ┌──────────┼──────────────────────┐
   │          │                      │
┌──▼───┐  ┌──▼──────┐         ┌──────▼──────┐
│first │  │reasoning│ :8001 ──┤  retrieval  │  (Layer 2，海军)
│layer │  │(Layer 3)│         │  双路检索    │
│:3004+│  └─────────┘         └──────┬──────┘
└──────┘                             │ HTTP
                                     │
                              ┌──────▼──────────────┐
                              │  ingestion (本模块)  │  :3003
                              │  Layer 1 数据处理层   │
                              └──────┬──────────────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  │                  │                  │
            ┌─────▼─────┐    ┌───────▼──────┐    ┌──────▼──────┐
            │  data/    │    │ knowledge.db │    │ bge-m3 模型  │
            │  源文件    │    │ SQLite+FTS5  │    │ ~/.cache/hf │
            └───────────┘    └──────────────┘    └─────────────┘
```

- **写入侧调用方**：陈一赓的 entrance（`POST /index?add=...`）
- **读取侧调用方**：冷海军的 retrieval（`POST /chunks/vector-search` + `POST /chunks/text-search`）
- **不直连 DB**：上层一律走 HTTP，DB schema/路径变更对外透明

---

## 2. 内部数据流

```
┌─────────────────────────────────────────────────────────────────┐
│  POST /index?add=docs/react/foo.md                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │  parser/dispatcher.py          │   按扩展名分派
            │  .md → markdown_parser         │
            │  .pdf → pdf_parser (扫描走 OCR)│
            │  .docx → docx_parser           │
            │  .xlsx → xlsx_parser           │
            │  .pptx → pptx_parser           │
            │  .html → html_parser           │
            │  .adoc → adoc_parser           │
            │  .txt → txt_parser             │
            └────────────────┬───────────────┘
                             │ ParseResult(text, title_tree)
                             ▼
            ┌────────────────────────────────┐
            │  chunker/document_splitter.py  │   三级 fallback：
            │                                │   段落 → 句号 → 硬切
            │  chunker/quality_filter.py     │   过滤：太短 / 乱码 / 重复
            │  chunker/overlap.py            │   chunk 间重叠拼接
            └────────────────┬───────────────┘
                             │ List[Chunk]
                             ▼
            ┌────────────────────────────────┐
            │  common/embedding.py           │   batch_embed
            │  → bge-m3 (1024 维, normalize) │
            └────────────────┬───────────────┘
                             │ embedding 写回 chunk
                             ▼
            ┌────────────────────────────────┐
            │  db/connection.py + WAL        │
            │  db/documents_repo.py          │   upsert documents
            │  db/chunks_repo.py             │   insert chunks + FTS5
            └────────────────────────────────┘

入口在 sync/pipeline.py 的 index_pipeline()，被 routes_index.py 调
```

检索路径短得多：HTTP 进 → `routes_search.py` → 查 DB（向量全表 cosine / FTS5 BM25）→ X1.5 section 合并（`api/x15.py`）→ 返回。

---

## 3. 子目录速查

| 目录 | 干啥的 | 关键文件 |
|---|---|---|
| `api/` | FastAPI 路由 + uvicorn 入口 | `server.py`（端口 3003 入口）、`routes_index.py`（写入）、`routes_search.py`（检索）、`routes_upload.py`（联调用，开关控制）、`x15.py`（X1.5 section 合并） |
| `parser/` | 9 种格式解析器 | `dispatcher.py`（按扩展名分派）、`markdown_parser.py`（含 K8s `{#xxx}` / React `{/*xxx*/}` trailing anchor）、`adoc_parser.py`（**regex 手写适配 `[[xxx]]` 显式锚点 + `=` 标题，不用 asciidoctor**）、其它 `*_parser.py`、`types.py`（`ParseResult` / `TitleNode` 数据结构） |
| `chunker/` | 文本切块 | `document_splitter.py`（三级 fallback 主逻辑，`MAX_CHARS=1000`）、`quality_filter.py`（3 条过滤规则）、`overlap.py`、`types.py` |
| `db/` | SQLite 操作 | `schema.sql`（documents + chunks + FTS5 三表）、`connection.py`（WAL）、`documents_repo.py`、`chunks_repo.py` |
| `sync/` | 写入侧编排 | `pipeline.py`（`index_pipeline` 主函数）、`file_lock.py`（同文件并发锁）、`gc.py`（孤儿 chunk 回收）、`watchdog_runner.py`（路径 B 文件监听，预留） |
| `common/` | 工具层 | `embedding.py`（bge-m3 加载 + batch）、`errors.py`（统一错误类型）、`logger.py` |
| `scripts/` | 一次性 / 调试脚本 | `reindex_all.py`、`sanity_check.py`、`eval_x15_baseline.py`、`test_x15_poc.py` 等（**不是生产代码**，跑实验和回归用） |
| `tests/` | pytest | `unit/`（纯函数）、`integration/`（DB + HTTP 端到端）、`fixtures/`、`gen_fixtures.py` |
| `backend/` | ⚠️ 历史遗留 | 内层是 `ingestion/storage/`，**已废弃，不要往里写** |

---

## 4. 关键技术决策（为什么这么选）

### 为什么 SQLite + FTS5，不上 Milvus / PG / ES？
- 评委环境 **x86 Linux + 无外网 + Docker 单机**，多进程数据库部署成本不可控
- 数据规模 **164 文件 / ~5K chunks**，SQLite + WAL 单文件性能完全够（向量全表 cosine ~100ms / 万 chunk）
- FTS5 自带 BM25 + unicode61 分词，中文用 jieba 预切词解决（修 BM25 长 query / 短英文召回）
- 单文件 DB 方便备份、迁移、清空重建（`knowledge.db.bak.0506` 就是手动备份）

### 为什么 bge-m3 + `normalize_embeddings=True`
- 多语言（赛题中英混合），1024 维，HuggingFace 官方权重稳定
- normalize 后 cosine 落 [0, 1]，写入侧和查询侧都必须开，**否则 score 不可比，召回乱**
- 懒加载：进程启动不加载，首次 `/index` 调用才载（~15s），避免开发期反复重启慢

### 为什么 PaddleOCR 而不是 Tesseract
- 中文 OCR PaddleOCR 准确率显著高于 Tesseract
- 锁 `paddleocr 3.x` + `paddlepaddle 3.x`：3.x 起 API 大改（`use_angle_cls` / `show_log` 等参数删了），降级会炸
- GPU 部署把 `paddlepaddle` 换 `paddlepaddle-gpu`，10x 提速；CPU 也能跑

### X1.5 section 全量化（X0 → X1.5）
- **问题**：单 chunk 切太碎，LLM 上下文不够，召回准但答不对
- **方案**：检索命中后，把同 `(file_path, title_path)` 内多个命中合并为 1 个 result，`content` 扩展为 "title prefix + 居中截 max_chars=3500" 的整段
- **效果**：+13 题增益（baseline → X1.5）
- 应急回滚：env `INGESTION_X15_ENABLED=false` 重启
- 详见 spec：[`docs/superpowers/specs/2026-04-30-x15-rigorous-design.md`](../../../docs/superpowers/specs/2026-04-30-x15-rigorous-design.md)

### 为什么 .adoc 用 regex 手写而不是 asciidoctor
- Spring 文档大量用 `[[xxx]]` 显式声明 anchor + `=` 系列标题，是 .adoc 子集
- 用通用 markdown 解析跑 .adoc → 把 `==` 当成 H2 但漏掉前一行的 `[[anchor-id]]` → **anchor 全错**
- asciidoctor / asciidoc3 库重 + 依赖 Ruby/JVM，无外网部署成本高
- 我们手写 regex 只识别 `=` 标题 + `[[xxx]]` 锚点，覆盖赛题 Spring .adoc 的全部用法（高级语法 include / conditional / attributes 暂不支持，作普通正文）
- React / K8s 走 `markdown_parser.py`（识别 trailing `{#xxx}` / `{/*xxx*/}`）

### 增量索引必须支持 add / modify / delete（评分硬要求）
- 评委评测时**当场**新增 / 修改 / 删除一篇文档，5 分钟内提问验证
- **build-once 模式直接 0 分**——必须实现增量
- 实现：`POST /index?add=<path>` / `?modify=<path>` / `?delete=<path>`，三选一互斥（详见 INTERFACE.md `/index`）
- 单文件 SLA：典型 < 1 秒（模型已加载）；首次进程启动加载 SentenceTransformer 约 15 秒
- 写入侧路径：`routes_index.py` → `sync/pipeline.py:index_pipeline()`，`file_hash` 自动判 indexed / replaced / unchanged
- 路径 B（`sync/watchdog_runner.py` 监听 raw/ 目录）已实现但默认不启用，HTTP 增量是默认链路

---

## 5. 4 个 ID 一图说清

```
file_path        docs/react/incremental-adoption.md
                 └─ 相对项目根 data/ 的路径（含 docs/<domain>/ 前缀）
                    与赛题 gold_sources[].doc_path 完全一致

chunk_id         sha256(file_path | chunk_index | content[:100]) 的 hex
                 └─ DB 主键，跨进程稳定可重算

anchor_id        docs/react/incremental-adoption.md#38
                 └─ {file_path}#{char_offset_start}，旧版前端跳转锚点

markdown_anchor  #data-fetching            (英文标题，slug)
                 #本地临时存储的配额          (中文标题，原文保留)
                 #top                       (无 heading 时)
                 └─ 章节级锚点，✨ 赛题判分按这个字段
                    Layer 2 必须把 metadata.markdown_anchor 透传到 reasoning

                 ⚠️ 中文 anchor 编码规则（统一口径，跟赛题 gold anchor 对齐）：
                    ✅ 原始中文保留（如 #本地临时存储的配额）
                    ✅ 标题里有空格 → 转 -（如 "API 发起驱逐" → #api-发起驱逐）
                    ✅ 全转小写（英文部分）
                    ❌ 不拼音化（不要 #ben-di-lin-shi-cun-chu-de-pei-e）
                    ❌ 不 punycode（不要 #xn--fiqu...）
                    ❌ 不丢空格信息（"a b" 必须出 "a-b"，不能压成 "ab"）
                    实现：parser/adoc_parser.py:_slugify() 的 regex `[^\w一-鿿-]+` 保留中文 Unicode
```

写入侧三个全自动算；查询侧海军的 retrieval 透传整个 metadata，reasoning 层取 `markdown_anchor` 优先（详见 INTERFACE.md 末尾"Layer 2 映射建议"）。

---

## 6. 快速上手

```bash
# 1. conda env（项目硬性约定，不要起 venv）
conda activate sqllineage

# 2. 装依赖（只需第一次）
pip install -r src/backend/ingestion/requirements.txt

# 3. 配 AIGW key（embedding 走平台网关时需要，本地用 HF 直连可跳过）
# 参考 src/.env.aigw.example，写 AIGW_API_KEY=sk-xxx 到 src/.env.aigw

# 4. 启动（项目根执行）
bash src/backend/ingestion/start.sh --bg

# 5. 健康检查
curl http://localhost:3003/health
# {"status":"ok","db_writable":true,"embedding_model_loaded":false}

# 6. 索引一条样本（首次会加载 bge-m3，~15s）
curl -X POST 'http://localhost:3003/index?add=docs/react/sample.md'

# 7. 全文搜验证
curl -X POST http://localhost:3003/chunks/text-search \
  -H "Content-Type: application/json" \
  -d '{"query":"OAuth2","top_k":3}'
```

停止：`bash src/backend/ingestion/stop.sh`

完整启停 / 联调步骤：见 [`INTERFACE.md` §快速上手](./INTERFACE.md#快速上手) 和 [§联调步骤](./INTERFACE.md#联调步骤推荐你按这个顺序测)。

---

## 7. 配置与环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `INGESTION_X15_ENABLED` | `true` | X1.5 section 合并开关。设 `false` 重启 → 30 秒回滚到 X0 行为 |
| `INGESTION_UPLOAD_ENABLED` | `false` | 是否注册 `POST /upload` 联调端点。生产/默认关闭 |
| `PYTHON_BIN` | 自动探测 | 显式指定解释器路径（生产 venv / 多 Python 环境用） |
| `AIGW_API_KEY` | — | 走亚信 AIGW 平台网关 embedding 时必填，从 `src/.env.aigw` 加载 |

启动脚本 `start.sh` 用 `which python` 探测，所以 **conda env 必须先 activate**，否则 PATH 里 python 指向系统 Python，依赖找不到。

---

## 8. 测试

```bash
cd src/backend/ingestion

# 单元测试（纯函数，~秒级）
pytest tests/unit -v

# 集成测试（含 DB / HTTP，~分钟级）
pytest tests/integration -v

# 跑单个文件 / 单个用例
pytest tests/unit/test_chunker.py -v
pytest tests/unit/test_chunker.py::test_paragraph_split -v

# 生成测试 fixture（更新参考样本时用）
python tests/gen_fixtures.py
```

`pytest.ini` 里 `pythonpath=../..`，所以测试里 import 写 `from backend.ingestion.xxx import ...`（不是相对 import）。

`scripts/` 下还有一批端到端验证脚本（`sanity_check_api.py` / `eval_x15_baseline.py` 等），**那是开发期跑实验用的**，不是 pytest 套件，单独 `python scripts/xxx.py` 跑。

---

## 9. 部署到评委环境（无外网）

评委环境是 **x86 Linux + 无外网**。两个模型默认从公网下载，**必须在打 Docker 镜像时预先下载并打包进镜像**，否则首次启动直接崩。

### 模型来源 + 大小

| 模型 | 用途 | 大小 | 下载源 | 缓存目录 |
|---|---|---|---|---|
| `BAAI/bge-m3` | embedding（写入+查询）| ~2 GB | HuggingFace | `~/.cache/huggingface/` |
| `PP-OCR-v5` | 扫描 PDF OCR 降级 | ~200 MB | 百度 BOS | `~/.paddlex/` |

### Dockerfile 关键片段

```dockerfile
# 在 RUN pip install -r requirements.txt 之后追加
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_textline_orientation=True, lang='ch')"
# 模型现在在镜像 layer 里，无网也能跑
```

### GPU 注意

部署环境有 NVIDIA GPU 时，把 `paddlepaddle` 替换成 `paddlepaddle-gpu`（同版本 `>=3.3.1,<4.0.0`），速度 ~10x。CPU 版默认能跑。

bge-m3 的 GPU 加速通过 `torch` 自动启用，无需改依赖（前提是 `torch` 装的是 cuda 版）。

---

## 10. 相关文档索引

| 文档 | 内容 |
|---|---|
| [`INTERFACE.md`](./INTERFACE.md) | 对外 HTTP 接口契约（必读，海军 / 陈一赓对接看这个）|
| [`docs/superpowers/specs/2026-04-25-data-layer-design.md`](../../../docs/superpowers/specs/2026-04-25-data-layer-design.md) | 数据层总设计 spec（架构起点）|
| [`docs/superpowers/specs/2026-04-30-x15-rigorous-design.md`](../../../docs/superpowers/specs/2026-04-30-x15-rigorous-design.md) | X1.5 section 全量化设计 |
| [`docs/superpowers/specs/2026-04-27-chunk-quality-filter-design.md`](../../../docs/superpowers/specs/2026-04-27-chunk-quality-filter-design.md) | chunk 质量过滤 3 条规则 |
| [`docs/superpowers/specs/2026-04-27-upload-endpoint-design.md`](../../../docs/superpowers/specs/2026-04-27-upload-endpoint-design.md) | `/upload` 两阶段分离设计 |
| [`docs/superpowers/specs/2026-04-28-fts5-jieba-tokenizer-design.md`](../../../docs/superpowers/specs/2026-04-28-fts5-jieba-tokenizer-design.md) | FTS5 + jieba 中文分词 |
| `docs/superpowers/specs/2026-04-28-adoc-parser-design.md` | adoc parser 设计 |
| `docs/superpowers/specs/2026-04-28-vector-search-min-score-design.md` | 向量检索 min_score 阈值 |
| `docs/superpowers/specs/2026-04-29-group-a-anchor-html-strip-design.md` | anchor HTML strip 处理 |
| `../../../ISSUES.md` | 项目级 BUG / MISSING / STALE 跟踪（按 P0/P1/P2 优先级）|

---

## 11. 联系方式

接口字段需要调整、有 bug、有性能问题，直接告诉涂祎豪。改动会同步更新 `INTERFACE.md` 和本 README。
