# Session Handoff — Layer 1 实施前置状态快照

> **写入时间**：2026-04-22 晚  
> **目的**：Claude 换 session 时从这个文件快速续上，不用重读上万行历史  
> **下一步**：写 Day 1 最小 chunker，解锁评测基线

---

## ⚡ TL;DR

- ✅ **设计文档已定稿到 v2.5.2**（`docs/layer1-design-v2.md`）——经 6 轮 reviewer 审视，问题密度从 11 条收敛到工艺级
- ✅ **评测框架已搭建并跑通**（`eval/`）——第一次基线跑分暴露系统级 bug
- ✅ **已知 bug 归档**（`ISSUES.md`）——ISSUE-001（chunker 未实现）是阻塞一切的 P0
- 🟡 **2 个 ❓ 待团队拍板**（Q1 embedding 模型，Q2 rag-service owner）
- 🔴 **下一步**：写最小 markdown chunker，让 `chunkCount > 0`，eval 拿到真实基线

---

## 📖 新 session 先读这些（按顺序）

| 文件 | 读的重点 | 时间 |
|---|---|---|
| **本文件** | 整体状态（你正在看） | 2 min |
| `docs/layer1-design-v2.md` | §2 核心决策 + §4.2.1 document chunking + §4.4 Pipeline | 10 min |
| `ISSUES.md` | ISSUE-001（为什么 chunkCount = 0） | 2 min |
| `eval/README.md` | 评测怎么跑 | 3 min |
| `CLAUDE.md`（项目根） | 项目整体结构 | 3 min |

**总共 20 分钟**能完全跟上。

---

## 🏗️ 项目角色定位

**用户**：团队成员之一，自领 **Layer 1（数据处理层）**  
**队友**：
- `赓哥 (陈一赓)`：已搭 TS/Node + Express + Next.js 骨架，会继续做前端 + 存储
- `海军 (冷海军)`：倾向 Layer 2 / RAG 核心 / reranker

**用户风格**：
- 中文母语，非深度技术背景（很多专业术语需要讲解释）
- 不喜欢过度概括——说 "这次只是小比赛，别当成通用方法论"
- 喜欢简短但有结构的回答，大白话 + 具体例子优先

---

## 🎯 比赛约束（死线，不可移动）

- **交付死线**：2026-05-10 18:00
- **今日**：2026-04-22（已消耗 1 天用于设计 + 评测框架）
- **剩余**：19 个自然日，其中 10 天开发 + 4 天联调 + 3 天评委语料适配 + 2 天提交收尾
- **评委语料发放**：2026-05-07（Day 16）
- **Feature Freeze**：2026-05-01（Day 10）

---

## ✅ 已做的技术决策（别再讨论，直接按这个干）

| 决策点 | 选定方案 |
|---|---|
| 存储 | **SQLite + FTS5**，**不切 ES**（时间不够，决赛再考虑） |
| Chunking 语言 | **Node (TypeScript)**，跑在 Express 主服务内 |
| 重活语言 | **Python 微服务 `rag-service`**（embedding / reranker / OCR） |
| 部署拓扑 | Docker Compose，Node 和 Python 共享 volume（传路径不传二进制） |
| 支持格式 | 文档类 10 种 + 代码类 8 种（含旧版 Office 用 LibreOffice 转） |
| Chunking 策略 | 按 `content_type` 三分派：document / code / structured_data |
| Chunking 粒度 | 1500 char max，document 加 200 char overlap，代码不加 |
| chunk_id 公式 | `sha256(file_path + content[:500] + occurrence_seq)` |
| anchor_id 格式 | `file_path#chunk_id`（computed，不存储） |
| Schema | 三表分层：`chunks`（内容）+ `chunk_versions`（版本相关）+ `chunks_fts` |
| 版本切换 | `documents.index_version` 作为原子切换开关 |
| 增量粒度 | **chunk 级 diff**（不是文件级） |
| 文件监听 | `chokidar` + 1s debounce + 文件级 mutex |
| 中文分词 | 应用层 `nodejieba` 预分词 + FTS5 unicode61 |
| API 兼容 | 保留旧端点 `/api/qa/*` 作为 alias |

**所有细节都在 `docs/layer1-design-v2.md`**，按这个照着写就行。

---

## ❓ 开放问题（有答案再动）

### Q1：Embedding 模型走网关还是本地？⚠️ P0

**已知**：统一 LLM 网关支持聊天模型 `glm5 / kimi / minimax / qwen 3.6`，embedding 未明说  
**决策树**：
- 网关有 embedding API → 走网关（默认首选）
- 网关无 embedding 但允许本地 → 本地跑 bge-m3
- 网关强硬要求全走 → 找组委会申请例外

**Day 1 必须问清楚**（或默认用网关，写成可配置，等 Q1 答案再切模型名）。

### Q2：rag-service 谁写？

建议海军主导（他懂 RAG），用户协助 glue code。

### Q3-Q6（次要）
- PaddleOCR 做不做？看评委语料有没有扫描件
- LibreOffice 要不要打进 rag-service 镜像？看评委语料有没有旧 Office
- sqlite-vec 升级不升级？50MB 语料先不急
- HTML / XML 的"源码 vs 文档"判定启发式

详见设计文档 §7。

---

## 🔴 已知阻塞 bug（开干前必须修）

### ISSUE-001：chunker 未实现 → chunkCount = 0 → 所有查询必拒答

- 评测跑第一次得 40/100（其中 30 是 vacuous refusal score，实际能力约 0）
- 所有上层（reranker、引用、增量）都依赖 chunks 存在
- **Day 1 任务就是修这个**

### ISSUE-003：中文文件名双重编码

- `"湖南CRM..."` 被存成 `"\u00e6\u00b9\u0096..."`
- `src/routes/upload.ts` 里 `Buffer.from(file.originalname, 'latin1').toString('utf8')` 修复

---

## 🚀 Day 1 具体任务

**目标**：让 `GET /api/qa/stats` 返回 `chunkCount > 0`，eval 拿到真实基线

### 步骤 1：最小 markdown chunker（Node / TS）

位置：`src/chunker/index.ts`

```typescript
// 必须实现的入口
export function chunkDocument(parseResult: ParseResult): Chunk[];
```

**最小可行版本**（先不用管 code / structured_data，只支持 document）：

1. 按 markdown heading 层级找 title_tree
2. `splitDocument()` 三级 fallback：
   - 段落（`\n\n+`）
   - 句子（`。！？.!?`）
   - 硬切（`is_truncated: true`）
3. chunk_id 用 `sha256(file_path + content[:500] + occurrence_seq)`
4. 质量过滤：长度 < 30 char 丢弃、全符号丢弃

详见设计文档 §4.2.1。

### 步骤 2：接入 upload flow

位置：`src/routes/upload.ts`

- 文件保存后调 `chunkDocument()`
- 调用 `db.insertChunks(chunks)` 和 `db.insertChunkVersions(...)`
- **注意**：Schema 要先迁移到 v2（看设计文档 §4.3.1）——但 **Day 1 可以先用老 schema** 把 chunks 跑起来，Day 3 再迁 Schema

### 步骤 3：验证链路

```bash
npm run dev                               # 起后端
curl -X POST .../upload -F "files=@eval/fixtures/pods.md"
curl .../stats                             # 应看到 chunkCount > 0
python3 eval/run.py --limit 1              # 应答对 q001
```

**验收**：eval 第一次真实基线分数（预估 40-65，看 embedding 是否配好）。

---

## 📊 评测框架使用

评测集已建：`eval/testset.jsonl`（5 题）  
Fixtures 已建：`eval/fixtures/`（4 个 md）  
脚本已写：`eval/run.py` + `eval/judge.py`

**核心命令**：
```bash
python3 eval/run.py --limit 1         # smoke test
python3 eval/run.py                    # 全量
python3 eval/judge.py                  # judge 逻辑自测
```

**判定方式**（对 Layer 1 开发很重要）：
- 关键词组匹配（`keywords_all_groups`）
- 拒答字符串匹配（`should_refuse`）
- 引用交集（`expected_citations`）

---

## 🗂️ 目录清单（当前状态）

```
TechnicalDocumentationCitationSystem/
├── CLAUDE.md                        ← 项目说明
├── ISSUES.md                        ← bug 清单
├── 技术文档智能问答与引用溯源系统.md ← 原架构文档（L1 部分已被 layer1-design-v2.md 替代）
├── docs/
│   ├── SESSION-HANDOFF.md           ← 本文件
│   ├── layer1-design-review.md      ← Layer 1 设计审视（P0-P2 清单）
│   └── layer1-design-v2.md          ← Layer 1 定稿设计 (v2.5.2)
├── eval/
│   ├── testset.jsonl                ← 5 题评测集
│   ├── judge.py                     ← 判定函数（有自测）
│   ├── run.py                       ← 评测主脚本
│   ├── README.md
│   └── fixtures/                    ← 4 个 md 文件
├── src/
│   ├── converter/                   ← 解析（已有 mammoth/xlsx/pdf/md）
│   ├── database/                    ← SQLite (schema 是 v1，需要迁到 v2)
│   ├── retriever/                   ← 向量 + 关键词 fallback（无 reranker）
│   ├── qa/                          ← LLM 问答 + 严格模式
│   ├── llm/                         ← LLM 调用
│   ├── routes/                      ← upload + qa + stream
│   └── server.ts
├── frontend/                        ← Next.js UI（已有）
├── storage/                         ← SQLite + 原文件 + 转换产物
└── docker-compose.yml               ← 已有基础，需要加 rag-service
```

---

## 🎯 新 session 的第一句话该说什么

**给 Claude 的建议 prompt**：

```
读一下 docs/SESSION-HANDOFF.md，然后按 Day 1 步骤开始写最小 markdown chunker。
Q1 网关 embedding 的问题我还没问清楚，先按可配置写，默认模型名用环境变量 EMBEDDING_MODEL 占位。
```

---

## ⚠️ 重要的"不要做"（避免踩坑）

1. **不要重新讨论技术栈**——SQLite / Node chunker / Python rag-service 已定
2. **不要重新设计 schema**——三表分层（chunks / chunk_versions / chunks_fts）已定
3. **不要改 chunk_id 公式**——`sha256(file_path + content[:500] + occurrence_seq)`
4. **不要忘记 anchor_id 是 computed 不存储**
5. **不要直连 OpenAI**——必须走统一 LLM 网关（`LLM_BASE_URL` 环境变量）
6. **不要把切分的 title_path 存进 chunks 表**——必须存进 chunk_versions（跨版本可变）

---

## 📝 关键设计决策的"为什么"（万一新 session 质疑）

- **为什么不用 ES？** 时间不够，50MB 语料 SQLite + FTS5 能扛
- **为什么 chunking 用 Node 不用 Python？** 和 Express 深度集成，Python 留给真正需要生态的 embed/rerank/OCR
- **为什么 chunk_id 去掉 chunk_index？** 文档头部插入会让所有 chunk_index +1，导致所有 chunk_id 连锁变，增量复用失效
- **为什么 char_offset / title_path 放 chunk_versions 不放 chunks？** 跨版本会变（插入章节、重构 heading），放内容表会让 INSERT OR IGNORE 场景下显示老数据
- **为什么 chunks_fts 要加 index_version？** title_path 版本相关，不加版本 FTS 会搜到过期标题

---

## 🏁 最终状态确认

✅ 设计定稿  
✅ 评测框架可用  
✅ bug 已归档  
🟡 团队对齐未最终确认（已发文档，等反馈）  
🔴 代码尚未开写（Day 1 任务待执行）

**新 session 直接进入"写代码"模式即可，不需要再做规划层面的工作**。
