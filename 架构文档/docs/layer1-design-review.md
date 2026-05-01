# Layer 1 数据处理层 · 设计优化备忘

> **对象**：开发团队  
> **起草**：2026-04-22  
> **基于文档**：`技术文档智能问答与引用溯源系统.md` §1.1-§1.5  
> **用途**：基于评测框架实测 + 技术细节审视，对 Layer 1 设计提出优化建议，供讨论对齐。  
> **不是**：推翻重设计。整体架构方向没问题，这里只点出**可能翻车的边界 case**。

---

## TL;DR（一句话版本）

设计文档**整体扎实**（anchor 双字段、双路径增量、文件锁都是对的），但**边界场景覆盖不足**。建议修 **7 个 P0 风险**（每处 3-30 行代码，总计 ~200 行），避免提交时翻车。另有 6 个 P1 优化项，有时间再做。

> 🗒️ **对非技术背景队员**：每个问题我都用"大白话+代码例子"讲，不懂的术语查文末【术语表】。真看不懂的请标记出来，讨论时当面讲。

---

## 评测实测：系统当前状态

通过 `eval/` 评测框架跑 1 道题，暴露：

1. **[ISSUE-001] chunkCount = 0**：文档上传后没切分，检索无数据 → 所有问题都拒答
2. **[ISSUE-003] 文件名编码 bug**：中文文件名存成 `\u00e6\u00b9\u0096...` 乱码

详见 `ISSUES.md`。

---

## P0 风险（7 条，强烈建议 Layer 1 实现时一次性修掉）

### P0-1. Tokenizer 不对齐 → 引用到一半没了

**现象**：设计说"chunk 大小 512 tokens"，但**没明确用哪个 tokenizer 算**。

**为什么是问题**（大白话）：  
"token" 是 AI 模型数"字"的单位，**不同模型数法不一样**：
- OpenAI 的 tokenizer（tiktoken）：1 个中文 ≈ 1.5-2 tokens
- bge-m3 的 tokenizer：1 个中文 ≈ 1 token

用 A 模型数 "500 tokens" 的 chunk，交给 B 模型，可能 B 数出来 **800 tokens**。如果 B 的上限是 512，**后面 300 tokens 直接被砍掉**。

**实际后果**：
- 切分时 chunk 结尾是"……设置 timeout 为 30 秒"
- 向量化时这句话被截断到"……设置 timeout 为"
- 用户问超时配置 → 召回这个 chunk → 显示引用 → 但引用内容对不上原文末尾
- **引用准确率直接崩**

**修复**：
```python
# 错误做法：用 tiktoken
from tiktoken import encoding_for_model
tokenizer = encoding_for_model("gpt-4")
token_count = len(tokenizer.encode(text))

# 正确做法：用 embedding 模型自己的 tokenizer
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
token_count = len(tokenizer.encode(text))

# 且预留余量（不要刚好 512，用 480 留点缓冲）
MAX_TOKENS = 480  # 不是 512
```

**工作量**：1-3 行代码变更。

---

### P0-2. 先删后写，中间挂了数据就丢了

**现象**：§1.4 的伪代码：
```python
chunks = parse_and_chunk(file_path)
es.delete_by_file(file_path)    # 第 1 步：删老的
es.bulk_index(chunks)           # 第 2 步：写新的
db.update(...)                  # 第 3 步：更新状态
```

**为什么是问题**（大白话）：  
如果第 2 步**挂了**（ES 暂时连不上、内存爆、网络抖动），老数据已经删了，新数据没写进去。结果：
- 这个文件从索引里**消失**
- 评委问它的内容 → 系统拒答
- 但 UI 可能还显示 `indexed_at` 是最近时间 → 假象"已索引"

**修复**：**先写后删（数据库的 transaction 思想）**：
```python
# 给每批新数据一个版本号
new_version = str(uuid.uuid4())

# 第 1 步：先写新数据（带新版本号）
es.bulk_index([{**c, "version": new_version} for c in chunks])

# 第 2 步：更新主记录指向新版本
db.update(file_path, version=new_version)  # ← 这一步是"原子切换"

# 第 3 步：成功后才删老版本（失败了也没事，下次 GC 清理）
es.delete_by_version(file_path, old_version)
```

这样即使第 2、3 步失败，**老数据还在**，系统不会"消失"。

**工作量**：5-10 行代码变更。

---

### P0-3. 编辑器保存会触发 watchdog 事件风暴

**现象**：§1.4 假设 watchdog 检测到 `modified` 事件就调 `index_pipeline`。

**为什么是问题**（大白话）：  
不同编辑器保存文件的方式**不一样**：
- **Vim / IDEA**：先删原文件 → 创建新文件（`rename`），触发 `deleted` + `created`，不是 `modified`
- **VSCode / macOS**：直接写文件，触发 `modified` 事件**2-3 次**
- **编辑器 autosave**：每 5-10 秒触发一次

结果：5 分钟内可能触发同一文件 **20 次** index_pipeline。虽然设计里 hash 一致会提前 return，但：
- 每次还是要算一遍 SHA-256（大文件可能几百 ms）
- 文件锁竞争，互相阻塞
- 日志刷爆，真实修改淹没在噪声里

**修复**：加 **debounce（抖动抑制）**——一个文件 1 秒内的重复事件只处理最后一次：
```python
from collections import defaultdict
import asyncio

_pending_tasks = {}

async def debounced_index(file_path: str, delay: float = 1.0):
    # 取消该文件的上一个待处理任务
    if file_path in _pending_tasks:
        _pending_tasks[file_path].cancel()
    
    # 延迟 delay 秒后执行
    async def delayed():
        await asyncio.sleep(delay)
        del _pending_tasks[file_path]
        index_pipeline(file_path)
    
    _pending_tasks[file_path] = asyncio.create_task(delayed())

# watchdog 事件处理
def on_file_event(event):
    asyncio.run(debounced_index(event.src_path))
```

**工作量**：10-20 行代码。

---

### P0-4. 超长段落切分会丢内容

**现象**：§1.2 说"优先在段落边界处切分"，但**没说段落本身 > 512 token 怎么办**。

**为什么是问题**（大白话）：  
技术文档里**长段落很常见**：
- 一大段 YAML 配置（整屏 80 行）
- 连续的中文说明（无分段）
- 一段冗长的代码块

如果一个"段落"就超过 512 token，你的切分器"找不到段落边界"→ 可能**直接跳过这个段落**，或者**报错卡死**。

**修复**：**三级降级策略**：
```python
def chunk_text(text: str, max_tokens: int = 480) -> list[str]:
    # 第 1 级：段落边界
    paragraphs = text.split("\n\n")
    result = []
    for para in paragraphs:
        if token_count(para) <= max_tokens:
            result.append(para)
        else:
            # 第 2 级：句子边界
            sentences = split_sentences(para)  # 按 。！？. ! ? 切
            for sent in sentences:
                if token_count(sent) <= max_tokens:
                    result.append(sent)
                else:
                    # 第 3 级：硬切（并注明被截断）
                    result.extend(hard_split(sent, max_tokens, marker="[TRUNCATED]"))
    return result
```

**关键**：硬切的 chunk 要带 `is_truncated` 标记，在 Layer 3 注入 context 时告诉 LLM"这段可能不完整"。

**工作量**：20-30 行代码。

---

### P0-5. 文件级增量太粗，浪费 embedding 额度

**现象**：§1.4 的增量是"文件级"——文件变了就**全文重 chunk + 重 embed**。

**为什么是问题**（大白话）：  
评委可能上传一个**大文档后只改一小段**：
```
100 MB 文档 → 1000 个 chunks
用户改了 1 段 → 只影响 2 个 chunks
```

**现在的做法**：1000 次 embedding API 调用（把整个文档重新向量化）  
**合理做法**：2 次 embedding API 调用（只算改的那 2 个）

**差 500 倍成本 + 500 倍时间**。而且统一 LLM 网关有 **rate limit**（额度限制），可能直接被拉黑。

**修复**：**chunk 级 diff（差量识别）**：
```python
def chunk_level_diff(file_path: str) -> tuple[list, list]:
    new_chunks = parse_and_chunk(file_path)
    old_chunks = db.get_chunks(file_path)
    
    # 用稳定 ID 比对
    new_ids = {c.id: c for c in new_chunks}
    old_ids = {c.id: c for c in old_chunks}
    
    to_add    = [c for id, c in new_ids.items() if id not in old_ids]
    to_delete = [c for id, c in old_ids.items() if id not in new_ids]
    # 交集的 chunks 内容一致，直接复用老 embedding，不动
    
    return to_add, to_delete
```

**前提**：chunk 必须有**稳定 ID**：
```python
# 基于内容的 hash（内容变 → ID 变）
chunk_id = sha256(f"{file_path}::{chunk_index}::{content[:100]}")
```

**工作量**：30 行代码，但**省一大笔 embedding 钱**。

---

### P0-6. 孤儿 chunks：文件删了但索引还在

**现象**：§1.4 说"watchdog 监听到 deleted 事件时，调用 es.delete_by_file"。

**为什么是问题**（大白话）：  
现实中 watchdog **会漏事件**：
- 服务挂了的时候用户删了文件
- Linux inotify 队列满会丢事件（高频改动时常见）
- 批量 rm -rf 一次删 100 个文件，watchdog 可能接到 30 个就卡了

**结果**：文件删了但 ES 里 chunks 还在。查询时会：
- 返回一个"已不存在的文件"的引用
- 用户点击引用 → 找不到原文 → 系统显示 404
- 评委眼里就是 bug

**修复**：**启动时 + 定时 GC（垃圾回收）**：
```python
def gc_orphan_chunks():
    """清理索引里存在但文件系统里不存在的 chunks"""
    indexed_files = es.get_distinct("file_path")  # 所有索引过的文件
    for fp in indexed_files:
        if not os.path.exists(fp):
            log.warn(f"文件已删除但索引还在，清理: {fp}")
            es.delete_by_file(fp)
            db.delete(fp)

# 调用时机
# 1. 服务启动时跑一次
# 2. 每 1 小时跑一次（定时任务）
```

**工作量**：20 行代码。

---

### P0-7. 5 分钟 SLA 在大文档 + 并发时会翻车

**现象**：§1.5 的时间表：
```
小文档（< 50 页）：~30s
中等（50-200 页）：~2min  
大文档（> 200 页）：~3-4min
```

**为什么是问题**（大白话）：  
这个时间表**只考虑了"一个人传一个文档"**。现实场景：
- **多个评委同时传文档** → 网关 rate limit 被撞满
- **大文档 + OCR 扫描版 PDF** → 实测可能 10+ 分钟
- **Python GIL 限制** → 8 worker 并发其实达不到 8x 速度

**结果**：评委现场上传 200 页 PDF 等 10 分钟，**印象崩了**。

**修复**：
1. **分级 SLA**：小 < 1min、中 < 3min、大**允许异步完成**但 UI 进度条流畅
2. **并发上限** 跟网关 rate limit 联动：
   ```python
   semaphore = asyncio.Semaphore(min(8, gateway_qps - 2))  # 给其他请求留点额度
   ```
3. **指数退避重试**：
   ```python
   @retry(wait=wait_exponential(min=1, max=60), stop=stop_after_attempt(5))
   async def embed_with_retry(text): ...
   ```
4. **UI 进度条**：显示当前阶段（解析中 / 切分中 / 向量化中 X%）+ 剩余时间

**工作量**：30-50 行代码 + UI 小改。

---

## ⚠️ P1 优化（影响质量，有时间建议做）

### P1-1. Python 依赖要明确写进架构

设计文档选的 **Docling / Unstructured / PaddleOCR** 全是 Python 库。意味着：
- **Layer 1 必须起 Python 微服务**（不能纯 Node）
- 或者退而求其次用 Node 的 pdf-parse、mammoth（效果差一截）

**建议**：在架构文档里**明确写**"Layer 1 用 Python 微服务"，让赓哥预期对齐，不要等他写到一半发现要切栈。

### P1-2. Embedding 模型硬编码 bge-m3 风险大

设计里写死 bge-m3（1024 维）。但**统一 LLM 网关可能不支持** bge-m3：
- 网关可能只给 OpenAI `text-embedding-3-large`（3072 维）
- 如果本地跑 bge-m3，需要单独部署 + GPU 加速

**建议**：embedding 模型 + 维度在 config 里可配置：
```python
# config.py
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
```

Schema 建表时读配置。**先确认网关支持什么再选定**。

### P1-3. ColBERT Sparse 建议先砍掉

§2.2 的三路召回里 **ColBERT 多向量**成本巨高：
- 一个 chunk 512 token → ColBERT 每 token 一个向量 = 512 个向量
- 比单向量存储**大几十倍**
- 50 MB 语料 × 10 倍 chunk 膨胀 × 30 倍 sparse 增幅 = **可能 10+ GB 存储**

**建议**：**先只做 BM25 + Dense kNN 两路**。如果评测发现短查询召回差再加 ColBERT，**不要一上来就做**。

### P1-4. title_path 提取对 PDF 不靠谱

PDF 没有结构化 heading，靠**字体大小 / 位置**猜。Docling 和 Unstructured 实测准确率**60-80%**。错误的 title_path 会让 UI 显示**错误章节**，比没有更糟。

**建议**：加置信度字段，低置信时 `title_path: null`，**不显示章节**，引用只显示 `file_path#char_offset`。

### P1-5. documents 表字段不够用

当前 schema：
```sql
CREATE TABLE documents (
    file_path   TEXT PRIMARY KEY,
    file_hash   TEXT NOT NULL,
    index_status TEXT DEFAULT 'pending',
    error_detail TEXT,
    indexed_at  TIMESTAMP,
    chunk_count INT
);
```

**缺**：
- `file_size`（UI 展示 "1.2 MB"）
- `language`（多语言文档过滤）
- `last_modified`（文件时间戳，排序用）
- `format`（md / pdf / docx，UI 显示图标）
- `upload_user`（审计，如果有登录）

**建议**：schema 补齐。

### P1-6. chunk 质量过滤缺失

切分产生的"**垃圾 chunk**"会污染检索：
- "## 第 1 章"（5 token，只是标题）
- "---"（纯分隔符）
- "本页目录"（重复多次的噪声）

**建议**：入库前过滤：
```python
def is_meaningful_chunk(chunk):
    if chunk.token_count < 30: return False  # 太短
    if not re.search(r'[a-zA-Z\u4e00-\u9fa5]', chunk.content): return False  # 无字母无中文
    if chunk.content.count("\n") > len(chunk.content) / 10: return False  # 换行过多
    return True
```

---

## 💡 P2 加分项（可选）

时间允许再做：
- **重命名识别**：用 inode / 内容 hash 判断是 rename 不是 delete+create
- **索引版本化**：多 version 并存，支持回滚到上一个索引状态
- **索引健康仪表板**：看板显示成功率、延迟分布、错误类型
- **领域术语保护**：专业词典防止 "Kubernetes" 被切成 "Kuber" + "netes"

---

## 对讨论的建议

按 P0 → P1 → P2 顺序过一遍，**P0 里有没有理解有歧义 / 不同意的，当场讨论**。P1 和 P2 可以标个 ✅（要做）/ ❌（不做）/ ❓（待定）。

过完形成一份 **"Layer 1 v2"** 的共识设计。

---

## 附：术语表（给非技术背景队员）

| 术语 | 通俗解释 |
|---|---|
| **Tokenizer** | 把文字切成"模型能数的单位"（token）的工具。英文单词、中文字都是 token，不同模型切法不一样。 |
| **Token** | AI 模型处理文字的最小单位。"Hello" 是 1 token，"H-e-l-l-o" 在某些 tokenizer 里是 5 tokens。中文大约 1 字 1 token。 |
| **Chunk** | 把长文档切成的"小段"，便于检索。每段一般 300-500 字。 |
| **Embedding / 向量化** | 把一段文字变成一串数字（比如 1024 个小数），数学上意思相近的文字向量相似度高。AI 靠这个做"语义搜索"。 |
| **bge-m3** | 一个开源的 embedding 模型，中文效果好。 |
| **Reranker** | 第二轮打分器，对召回的候选 chunks 重新排序，比 embedding 单独用更准。 |
| **BM25** | 传统关键词检索算法，匹配字面词。ES、SQLite FTS5 都有原生实现。 |
| **kNN / Dense kNN** | 基于向量相似度的近邻检索。K 是要返回几个最相似的。 |
| **ColBERT** | 一种多向量检索算法，每个 token 一个向量，精度高但存储大。 |
| **RRF（Reciprocal Rank Fusion）** | 把多路召回结果融合成一个排序的算法，简单有效。 |
| **Elasticsearch / ES** | 一个专业的全文检索 + 向量检索引擎，工业界用的比较多。 |
| **SQLite FTS5** | SQLite 内置的全文检索模块，不如 ES 强但零配置。 |
| **Anchor** | "锚点"，指向文档某个具体位置的定位信息（如 "pods.md 第 4821 字节"）。 |
| **char_offset** | 字符偏移量，"这段内容从第几个字符开始"。比行号更精确。 |
| **title_path** | 标题路径，"大章 > 中章 > 小节" 的面包屑导航。 |
| **Watchdog** | Python 的文件系统监听库，文件变了会通知你。Node 对应的叫 chokidar。 |
| **inotify** | Linux 内核级的文件监听机制，watchdog 底层用这个。 |
| **Debounce / 抖动抑制** | 短时间内多次触发只算一次，防噪声。 |
| **Idempotent / 幂等** | 同样操作执行多次和执行一次效果一样。防重试时重复做事。 |
| **Hash (SHA-256)** | 把一段内容"摘要"成 64 位十六进制字符串，内容变 → hash 变，用来判断"内容是否相同"。 |
| **GC（Garbage Collection）** | 垃圾回收，清理无用的历史数据。 |
| **Rate Limit** | 速率限制，"每秒最多 10 次请求"之类。超了被拒绝。 |
| **Semaphore / 信号量** | 并发控制的"令牌"，同时最多 N 个任务能拿到令牌跑。 |
| **transaction / 事务** | 数据库里的"要么全做，要么不做"的操作组。 |
| **GIL** | Python 的全局解释器锁，多线程无法真正并行 CPU 密集任务。 |

---

## 更新历史

- **2026-04-22 初版**：通过评测框架实测 + 设计审视，提出 P0×7, P1×6, P2×4 共 17 条优化。
