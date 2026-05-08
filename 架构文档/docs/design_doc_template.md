# 技术文档智能问答与引用溯源系统 — 设计文档

> **版本**：v1.0  
> **日期**：2026-05-08  
> **队伍**：PAK智锚

---

## 1. 系统架构

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

---

## 2. 技术选型

| 组件       | 选型                  | 原因                                                      |
| -------- | ------------------- | ------------------------------------------------------- |
| **存储**   | SQLite + FTS5       | 小 chunks 规模 SQLite 够用（向量 cosine ~100ms）                 |
| **向量模型** | `bge-m3`            | 多语言，1024 维，`normalize_embeddings=True` 保证 score 可比      |
| **解析器**  | 全 Python（自研）        | 9 种格式；`.adoc` 用 regex 手写适配 `[[anchor]]` 显式锚点，避免通用解析器漏锚点 |
| **LLM**  | OpenAI 兼容接口         | `temperature=0.0` 严格模式；支持任意兼容接口切换                       |
| **增量同步** | watchdog + HTTP 双路径 | 路径 A：上传触发；路径 B：目录监听；均走 `index_pipeline`                 |
| **前端**   | Next.js             | 端口 `:3000`，引用跳转                                         |

---

## 3. 关键设计

### 3.1 文档解析与切分

#### 3.1.1 解析器分派

```
扩展名检测 → dispatcher.py → 对应 parser
  .md/.txt/.html  → markdown_parser / txt_parser / html_parser
  .pdf（文字）     → PyMuPDF
  .docx           → python-docx
  .xlsx           → openpyxl
  .pptx           → python-pptx
  .adoc           → adoc_parser（regex 手写）
```

#### 3.1.2 .adoc 锚点解析

```python
# adoc_parser.py — 识别 Spring .adoc 显式锚点
#   匹配模式：
#   [[anchor-id]]      ← 显式锚点（优先）
#   == Title          ← 标题层级
#   忽略 asciidoctor 高级语法（include / conditional）
```

**锚点编码规则**：

- 英文：`slugify("API Changes")` → `#api-changes`
- 中文：原文保留 + 空格替换为 `-` → `#本地临时存储的配额`
- 不拼音化 ,不 punycode ,不压缩空格

#### 3.1.3 切分策略（三级 fallback）

```
第 1 级：按标题（title_tree）切
  → 段落 ≤ 1000 char → 直接 chunk

第 2 级：按段落边界（\n\n）切
  → 段落 ≤ 1000 char → 直接 chunk

第 3 级：按句子边界（。！？. ! ?）切
  → 单句仍 > 1000 char → 硬切（is_truncated: true）

OVERLAP = 200 char（相邻 chunk 拼接）
质量过滤：< 30 char 丢弃
```

### 3.2 检索与拒答

#### 3.2.1 双路混合检索

```
用户查询
    │
    ▼
┌─────────────────────┐
│  LLM 同义变体 + 英译  │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
向量检索        BM25 检索
(/chunks/       (/chunks/
 vector-search)  text-search)
    │             │
    └──────┬──────┘
           ▼
    _merge_results 去重
    保留双路分数
           │
           ▼
    CrossEncoder Reranker
    Sigmoid (0,1) 映射
    相邻 chunk 上下文扩展
           │
           ▼
    自适应 TopK [5, 25]
```

#### 3.2.2 拒答机制

| 阶段               | 触发条件                             | 动作               |
| ---------------- | -------------------------------- | ---------------- |
| **Step 1 规则**    | `max_score < 0.4` 或无 chunk > 0.5 | 拒答，不进 LLM        |
| **Step 1.5 LLM** | 规则判定不可答                          | LLM 生成原因（≤ 80 字） |
| **Step 3 LLM**   | `refuse: true` JSON              | 拒答 + trap_type   |
| **Step 4 校验**    | citation_ids 全非法                 | 拒答               |

**trap_type 枚举**（8 种）：

```
fake_api / future_version / overgeneralization / parameter_mismatch /
cross_domain / concept_confusion / procedure_step / non_existent_attribute
```

**防误拒策略**：

- 检索分 < 0.4 才进拒答，非 0.6/0.7 高阈值
- LLM 主动拒答时才输出 trap_type（规则拒答不输出）
- 答案引用 ≥ 1 条时允许正常回答

### 3.3 增量更新与引用

#### 3.3.1 增量索引

```
路径 A：前端上传 → entrance → POST :3003/index
路径 B：watchdog 监听 raw/ → debounce 1s → :3003/index

同一文件 hash 没变 → 返回 unchanged
hash 变了 → 删旧 chunks → 全量重写（MVP）
               │
启动时全扫 GC + 每小时孤儿清理
```

**SLA 保证**：

- 小文件（< 20 页）：< 30s
- 中文件（20-100 页）：< 2min
- 大文件（100-500 页）：< 5min

#### 3.3.2 引用 anchor 处理

```
LLM 输出 citation_ids [1, 2]
    │
    ▼ validate_citations()
合法范围校验（1 ~ used_chunks 数量）
    │
    ├─ 非法 ID → 剔除 + warning
    └─ 全部非法 → 拒答
    │
    ▼ build_citations()
映射为 Citation(doc_path, anchor)
    │
    ▼
优先使用 metadata.markdown_anchor
（如 "#cleaning-up-an-effect"）
fallback：title_path 自动推断
```

**anchor 格式**：`#章节标题`（中文原文 + 空格变 `-`）

---

## 4. 性能指标

### 4.1 检索延迟

| 阶段        | 指标       | 说明                                 |
| --------- | -------- | ---------------------------------- |
| 向量检索      | < 400ms  | bge-m3 cosine 全表 ~100ms（5K chunks） |
| BM25 检索   | < 100ms  | FTS5 unicode61 + jieba 分词          |
| Reranker  | < 600ms  | CrossEncoder 本地推理，batch=8          |
| **端到端检索** | **< 2s** | 含网络开销、上下文扩展                        |

### 4.2 端到端延迟（问→答）

| 场景       | P50  | P95   | 说明            |
| -------- | ---- | ----- | ------------- |
| 简单事实题    | 2-3s | 5s    | 单轮检索 + LLM    |
| 复杂综合题    | 5-8s | 15s   | 多 chunk + 长推理 |
| 批量 100 题 | —    | 20min | 并发 4，LLM 限速   |

### 4.3 增量更新时延

| 场景              | 延迟   | 说明               |
| --------------- | ---- | ---------------- |
| 上传触发            | < 2s | HTTP 调用链路        |
| 文件监听            | 4-8s | debounce 1s + 处理 |
| **评测 5min SLA** | ✅    | 小文件 < 30s，预热后满足  |

---

## 5. 创新点

| 编号  | 创新点                   | 说明                                                           |
| --- | --------------------- | ------------------------------------------------------------ |
| ①   | **.adoc regex 锚点解析**  | 针对 Spring `[[anchor]]` 显式锚点手写 regex，覆盖率 > 95%，避免通用解析器漏锚点     |
| ②   | **X1.5 section 全量化**  | 同章节多个命中 chunk 合并为 1 个 section，+13 题实测增益，可一键回滚                |
| ③   | **双路混合去重 + Reranker** | 向量 + BM25 按 chunk_id 去重，CrossEncoder Sigmoid 归一化，阈值 0.4 语义一致 |
| ④   | **MVP 简化增量同步**        | HTTP 主动触发 + watchdog 兜底，hash 判 unchanged，全删重写保一致性            |

**外部依赖（已声明）**：

- LLM API：`https://aigw.asiainfo.com/v1`（OpenAI 兼容）
- 模型：`bge-m3`、`bge-reranker-v2-m3`（HuggingFace，本地推理）
- 翻译：`translators`（Bing，异常静默忽略）

---

## 6. 复现性声明

### 6.1 系统依赖

| 依赖                 | 版本     | 来源          | 用途           |
| ------------------ | ------ | ----------- | ------------ |
| Python             | ≥ 3.10 | 系统          | 运行时          |
| SQLite             | 3.x    | 系统          | 存储引擎         |
| bge-m3             | latest | HuggingFace | 向量 embedding |
| bge-reranker-v2-m3 | latest | HuggingFace | 重排序          |

### 6.2 Python 包依赖

| 类别             | 包名与版本                                                                                                                                                                                                                 | 来源   | 用途                    |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---- | --------------------- |
| Web 框架         | fastapi≥0.111.0, uvicorn[standard]≥0.29.0, pydantic≥2.7.0, httpx≥0.27.0, requests==2.32.5                                                                                                                             | PyPI | HTTP 服务与数据校验          |
| 文档解析           | pymupdf≥1.23.0, python-docx≥1.1.0, openpyxl≥3.1.0, python-pptx≥0.6.23, markdown≥3.5, beautifulsoup4≥4.12.0, markdownify≥0.11.6, chardet≥5.2.0, python-magic≥0.4.27, paddleocr≥3.5.0,<4.0.0, paddlepaddle≥3.3.1,<4.0.0 | PyPI | 多格式文档解析与 OCR          |
| Embedding / ML | sentence-transformers≥2.7.0, torch≥2.2.0, numpy==1.26.4                                                                                                                                                               | PyPI | 向量嵌入与深度学习推理           |
| LangChain 生态   | langchain-community==0.4.1, langchain-core==1.3.0, langchain-huggingface==1.2.2                                                                                                                                       | PyPI | LLM 应用框架组件            |
| 大模型 API        | openai==2.9.0                                                                                                                                                                                                         | PyPI | OpenAI 兼容接口调用         |
| 测试工具           | pytest≥8.0.0, pytest-asyncio≥0.23.0, pytest-benchmark≥4.0.0                                                                                                                                                           | PyPI | 单元测试与性能基准             |
| 工具库            | aiofiles≥23.2.0, watchdog≥4.0.0, jieba≥0.42.1, python-dotenv==1.2.1, translators==6.0.4                                                                                                                               | PyPI | 异步 IO、文件监控、分词、环境变量、翻译 |

### 6.3 复现步骤

```bash
# 1. 拉取代码
git clone <repo>
cd TechnicalDocumentationCitationSystem

# 2. 安装依赖
pip install -r src/backend/ingestion/requirements.txt
pip install -r src/backend/reasoning/requirements.txt
pip install -r src/backend/retrieval/requirements.txt
cd src/frontend && npm install

# 3. 下载模型（首次启动自动懒加载，或手动）
python -c "from sentence_transformers import SentenceTransformer; \
  SentenceTransformer('BAAI/bge-m3')"
python -c "from sentence_transformers import CrossEncoder; \
  CrossEncoder('BAAI/bge-reranker-v2-m3')"

# 4. 配置环境变量
cp src/.env.example src/.env
# 填入 LLM_API_KEY 等

# 5. 启动服务
bash src/devStart.sh

# 6. 索引文档
curl -X POST 'http://localhost:3003/index?add=docs/react/sample.md'

# 7. 验证
curl http://localhost:8001/health
curl -X POST http://localhost:8001/api/qa \
  -H "Content-Type: application/json" \
  -d '{"id":"test","question":"useEffect 何时执行？"}'
```
