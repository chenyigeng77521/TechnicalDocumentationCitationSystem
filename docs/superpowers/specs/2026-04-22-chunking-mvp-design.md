# Chunking MVP 设计文档

**日期**：2026-04-22
**关联 Issue**：[ISSUE-001](../../../ISSUES.md) — 切分（Chunking）尚未实现（P0）
**策略**：方案 C — 先 MVP 跑通评测拿基线，再根据 eval 结果决定是否升级到 token-aware 版本

---

## 背景

- `DatabaseManager.insertChunks` 和 `chunks` 表已就绪，但从未被调用。
- `/api/qa/stats` 永远返回 `chunkCount: 0`，导致所有 Q&A 拒答。
- 阻塞下游：引用验证、拒答机制、增量更新都依赖 chunks 存在。

---

## 目标与非目标

### 目标
1. 上传文件后自动切分并写入 `chunks` 表。
2. 切分结果对三种主要格式（md/docx、xlsx、pdf）各有合理策略。
3. Chunk ID 在**单次上传内可重复生成**（幂等切分）；真正的内容稳定 ID 留给 ISSUE-009。
4. 行号映射正确，保证引用能回溯到原文。
5. `eval/run.py` 非拒答题准确率 > 0%，拿到基线。

### 非目标（留给后续 task）
- Token 精确计数（tiktoken）
- Overlap 滑动窗口
- `char_offset` anchor（ISSUE-011）
- 文件级并发 / embedding batch
- Embedding 自动触发

---

## 架构

新增单个文件 `src/converter/chunker.ts`。`upload.ts` 在 `converter.convert()` 之后先 `db.insertFile()` 写父记录，再调 chunker 并 `db.insertChunks()`。**不改 DB schema；types.ts 可能需要微调**（见下方"类型一致性"）。

```
upload.ts (POST /api/upload)
  └─ converter.convert()     // 已存在
       → { mdContent, lineMappings }
  └─ db.insertFile()         // 已存在，必须先执行（外键父表）
  └─ chunkDocument()         // 新增
       → ChunkRecord[]
  └─ db.insertChunks()       // 已存在，必须在 insertFile 之后
```

**外键顺序**：`chunks.file_id` 是 `files.id` 的外键（虽然 SQLite 默认不强制，但顺序必须正确，以防后续打开 `PRAGMA foreign_keys = ON`）。

---

## 核心接口

```typescript
// src/converter/chunker.ts
import { FileFormat, LineMapping, ChunkInsertInput } from '../types.js';

export interface ChunkInput {
  fileId: string;
  format: FileFormat;
  mdContent: string;
  lineMappings: LineMapping[];
}

export function chunkDocument(input: ChunkInput): ChunkInsertInput[];
```

返回已填好 `id / file_id / content / start_line / end_line / original_lines`、`vector = null` 的 `ChunkInsertInput[]`（见"类型一致性"一节）。

---

## 格式分派（方案 C：按格式分派）

| 格式 | 策略 | 目标尺寸 |
|---|---|---|
| `md`, `docx` | 按 heading 切；超过 800 字符的段再按空行细切 | 300-600 字符 |
| `xlsx` | 每 **20 个数据行**（不含表头）一组，chunk 开头**另外前置** `## SheetName` + 表头 | 按行数 |
| `pdf` | 每页独立，页内按 400 字符滑窗（无 overlap） | 400 字符 |
| `pptx` | 直接用整个 mdContent 做 1 个 chunk（converter 未完善） | — |

### md/docx 细节

1. 按 `^#{1,6}\s` 正则把文档切成 "heading section"（heading 行 + 其后直到下一个 heading 的内容）。
2. 每个 section 如果 **≤ 800 字符**：直接作为 1 个 chunk。
3. **> 800 字符**：按 `\n\n`（空行）进一步切分，每 300-600 字符一个 chunk；每个子 chunk **开头前置最近的 heading**（提供检索上下文）。
4. 第一个 heading 之前的内容单独成 chunk（section = 空）。

**单一阈值 800**：不留中间区间，避免实现者在 601-800 之间猜规则。

### xlsx 细节

converter 产出形如：
```
## SheetName
| 列 | 数据 |
|----|------|
| row1 | ... |
| row2 | ... |
...
```
策略：检测 `## ` 行作为分组边界，每个 sheet 内**每 20 个表格数据行（不含表头、分隔线）** 一个 chunk。chunk 开头**另外前置** `## SheetName\n| 列 | 数据 |\n|----|------|\n`（属于 Section 上下文，不计入 20 行配额）。

### pdf 细节

converter 产出形如：
```
## 第 1 页

pageText...

## 第 2 页

pageText...
```
策略：按 `## 第 N 页` 切分，每页内用 400 字符滑窗。具体对齐：从当前位置向后找 400 字符处，在 `[300, 500]` 字符窗口内找最近的 `\n` 作为切点；若无换行符则按 400 硬切。页号信息前置到每个 chunk 内容。

---

## Chunk ID 生成（MVP 阶段）

```typescript
import { createHash } from 'crypto';

function chunkId(fileId: string, index: number, content: string): string {
  return createHash('sha256')
    .update(`${fileId}|${index}|${content.slice(0, 100)}`)
    .digest('hex')
    .slice(0, 16);
}
```

**诚实说明**：

- ✅ **MVP 内可重复生成**：同一次上传里，给定 fileId/index/content，ID 是确定的。满足单次 chunking 的幂等性。
- ❌ **不是内容稳定 ID**：因为当前 `fileId` 是 [upload.ts:73](../../../src/routes/upload.ts) 用 `uuidv4()` 现场生成的，**同一个文件重新上传一次，fileId 变，所有 chunk ID 也变**。

**对 ISSUE-009（增量更新）的含义**：这个公式**不够**。真正的增量更新需要 ID 与"是否是同一份文档的同一段内容"挂钩，而不是与某次上传的 UUID 挂钩。

**升级路径**（留给 ISSUE-009 task）：
1. 把 `fileId` 改成基于原文路径 + 内容 hash（例如 `sha256(originalPath + fileContentHash)`），让同一份文档的 fileId 跨上传稳定。
2. 或让 chunk ID 完全脱离 fileId：`sha256(content + contextHeading)`，只看内容本身。

本 MVP 不处理这两件事——先解锁评测拿基线。

---

## 行号映射

Chunker 在切分时记录每个 chunk 的 `mdLine` 范围（起止行号）：

```typescript
{ startLine: 12, endLine: 28 }
```

从传入的 `lineMappings`（`[{ mdLine, originalLine, ... }]`）查出这段范围内的原文行号集合，去重后填入 `original_lines`。

**兜底**：如果 `lineMappings` 为空或不覆盖该范围，`original_lines = [startLine, endLine]`（用 md 行号假装成原文行号，至少不会崩）。

---

## Section 上下文内嵌

Chunk `content` 字段格式（md/docx/xlsx）：
```
## 最近的 heading

实际段落内容...
```

好处：
- 检索命中时 LLM 能看到 section 标题，生成答案更准。
- 不需要改 schema 加 `section` 列。

pdf 的 `## 第 N 页` 天然就是 section，同样前置。

**关键规则：前置 heading 只是检索/显示上下文，不计入 chunk 的源行号范围。**

即：
- `start_line` / `end_line` / `original_lines` 都指向**实际切片内容**在原 md 中的行号，不包含"为了上下文而复制进来的那行 heading"。
- 否则同一个 heading 行会被映射到 N 个 chunk 的源行号里，引用回溯时会产生幻影行号。
- Chunker 实现：先确定切片的源行号范围 → 查出 `original_lines` → **最后一步**才在 content 前拼 heading 字符串。拼接操作只影响 `content` 字段，不回写行号。

---

## 类型一致性（types.ts 需要微调）

**现状**：[types.ts:152-160](../../../src/types.ts) 的 `ChunkRecord` 把 `original_lines` 和 `vector` 都声明为 `string`（"JSON 字符串"），但 [database/index.ts:162-177, 245-266](../../../src/database/index.ts) 的 `insertChunk` / `insertChunks` 在运行时对这两字段调 `JSON.stringify()`——也就是说**实际传入应该是数组/对象，类型声明却是 string**。这是已有的不一致。

**后果**：chunker 想返回 `original_lines: number[]` 时 TS 会报错。

**最小修法**：新增一个专门的"插入输入"类型，不动原 `ChunkRecord` 的"数据库行"语义：

```typescript
// types.ts 追加
export interface ChunkInsertInput {
  id?: string;
  file_id: string;
  content: string;
  start_line: number;
  end_line: number;
  original_lines: number[];  // 运行时是数组，DB 层 JSON.stringify
  vector?: number[] | null;
}
```

然后把 `insertChunk` / `insertChunks` 签名改用 `ChunkInsertInput`。Chunker 的返回类型用 `ChunkInsertInput[]`。

这样既保留 `ChunkRecord` 反映"DB 里存的是 JSON 字符串"的事实，又让应用层拿到类型正确的数组。改动面：types.ts 加 10 行、database/index.ts 改 2 处签名。

---

## upload.ts 改动

在 [upload.ts:79](../../../src/routes/upload.ts) 的 `converter.convert()` 之后，用**三阶段状态机**：`converting` → `completed` / `failed`。

```typescript
const conversionResult = await converter.convert(file.path, file.originalname);

// 阶段 1：先写父表，标记为 converting（不是 completed）
db.insertFile({
  id: fileId,
  original_name: file.originalname,
  original_path: conversionResult.originalPath,
  converted_path: conversionResult.convertedPath,
  format,
  size: file.size,
  upload_time: uploadTime,
  category: category || '',
  status: 'converting',  // ← 关键：不要直接写 completed
  tags: tags ? (typeof tags === 'string' ? tags.split(',') : tags) : []
});

// 阶段 2：切分并写子表
try {
  const chunks = chunkDocument({
    fileId,
    format,
    mdContent: conversionResult.mdContent,
    lineMappings: conversionResult.lineMappings
  });
  db.insertChunks(chunks);
  console.log(`✅ 切分完成：${chunks.length} 个 chunk`);

  // 阶段 3a：全部成功，标记 completed
  db.updateFileStatus(fileId, 'completed');
} catch (err) {
  // 阶段 3b：切分失败，标记 failed（保留 file 记录便于排查）
  db.updateFileStatus(fileId, 'failed');
  throw err;  // 冒泡到外层 try/catch，走"失败文件"分支
}
```

**状态机明确定义**：

| status | 含义 |
|---|---|
| `converting` | file 已入库，chunks 未写入（中间态，不对外可见） |
| `completed` | file + chunks 都就绪，可检索 |
| `failed` | 切分失败，chunks 为 0，排查用 |

**好处**：
- 消除"file completed + chunks 0"的灰态。
- `getAllFiles({ status: 'completed' })`（[qa.ts:128](../../../src/routes/qa.ts)、[retriever/index.ts:249](../../../src/retriever/index.ts)）**自动不会**返回未切分完成的文件，无需额外改动。
- 如果服务在切分中途崩溃，下次启动看到 `converting` 的孤儿，可以手动清理或重跑（MVP 不自动恢复，留给后续）。

---

## 顺带修 ISSUE-002

在 `/api/qa/index`（[qa.ts:187](../../../src/routes/qa.ts)）加守卫：

```typescript
const stats = db.getStats();
if (stats.chunkCount === 0) {
  db.close();
  return res.json({
    success: false,
    warning: '数据库中无可索引的 chunks，请先上传并切分文档'
  });
}
```

---

## 错误处理

- 空 mdContent → 返回空数组，upload 正常完成（文件入库但 chunkCount 不变）。
- chunker 抛异常 → 冒泡到 upload 的 try/catch，文件标记 failed。
- 单个 chunk 超长（超过 2000 字符）→ 强制按字符切，避免生成病态数据。

---

## 测试策略

### 单元测试 `src/converter/chunker.test.ts`

- `chunks md with multiple headings into expected count`
- `chunks long paragraph by blank lines`
- `prepends section heading to content`
- `chunks xlsx by 20-row groups per sheet`
- `chunks pdf by page then sliding window`
- `generates deterministic chunk IDs for same input` (注意：deterministic ≠ content-stable，详见 Chunk ID 章节)
- `maps md lines to original lines via lineMappings`
- `returns empty array for empty content`

用简单 md/xlsx-converted/pdf-converted 字符串做 fixture，不依赖真实文件。

### 集成验证

1. 启动 `npm run dev`
2. `curl -F "files=@docs/layer1-design-v2.md" http://localhost:3002/api/upload`
3. `curl http://localhost:3002/api/qa/stats` → 断言 `chunkCount > 0`
4. `curl -X POST http://localhost:3002/api/qa/ask -d '{"question":"..."}'` → 返回答案而非拒答

### 评测验证

`python eval/run.py --limit 5` → 非拒答题准确率 > 0%。记录基线分数，决定是否升级到方案 B。

---

## 实施步骤建议

1. 写 `chunker.ts` + 单元测试（TDD）
2. 改 `upload.ts` 集成
3. 改 `qa.ts` 修 ISSUE-002
4. 清空 `storage/knowledge.db`，重新上传样本文件
5. 跑 eval，记录基线
