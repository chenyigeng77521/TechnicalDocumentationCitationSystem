# Chunking RAG 独立服务集成设计

**日期**：2026-04-23
**关联**：
- 上游 v1 实现：`feature/chunking-mvp` 分支（已完成 ISSUE-001 + ISSUE-002）
- 同事重构后的 main：`backend/` 是文件管理 demo，砍掉了所有 RAG 链路
- 团队 v2 设计：`技术文档智能问答与引用溯源系统(1).md`（多服务架构 + 内容类型分派 + char_offset anchor）

---

> ⚠️ **2026-04-23 晚更新（team convention 调整）**：
> 团队约定变更为"每人独立目录，互不影响"（见群聊）。因此本 spec 里 D2 节关于
> "共享 `/storage/raw/` + 改同事 config" 的方案**已作废**，实际代码采用：
>
> - 服务目录从 `services/` 改名到 `services-tuyh/`（owner-tagged）
> - 存储完全自包含：`UPLOAD_DIR=./storage/raw`（相对 `services-tuyh/chunking-rag/` cwd）
> - 项目根 `/storage/raw/` 已删除，不再作为跨服务共享池
> - `backend/src/config.ts` 那 1 行改动已 revert 回原样
>
> 契约对齐（6 个前端端点）+ chunker 实现 + 所有 e2e 断言都**不受影响**——仅存储拓扑私有化。
> 下方 D2/D2b 关于"共享"的描述保留作设计过程记录，不代表当前实现。

---

## 背景与目标

### 问题
- 同事在 main 上把 backend 简化成纯文件管理服务（无 converter / DB / retriever / qa / llm）
- 但 frontend `page.tsx` 仍硬编码 `localhost:3002` 调用 RAG 端点（`/api/qa/ask-stream`、`/api/qa/stats` 含 `totalFiles` 字段）
- 我们 v1 完整 RAG 链路（含 chunker、SQLite chunks 表、关键词+语义检索、LLM 问答）尚不能直接 plug 到现状

### 目标
1. **不动同事代码**：`backend/`、`frontend/` 一行不改
2. **完整对接前端**：前端 0 修改即可完整使用上传 + 问答功能
3. **保留 v1 切分工作**：v1 的 chunker、状态机、空 chunks 守卫等增强功能完整带过来
4. **独立目录**：所有新代码在 `services-tuyh/chunking-rag/`，与同事 `backend/` 平级

### 非目标
- v2 设计的 char_offset、reranker、查询扩展、增量更新等高级功能（留给后续迭代）
- 重写 frontend 或同事 backend
- 长期的两服务并存方案（短期靠"谁先启动占 3002"约定，赛题演示时停掉同事 backend）

---

## 架构

```
项目根/
├── storage/                    ⬅ **跨服务共享**的上传文件目录
│   └── raw/                    用户上传的原文件（前端列表 + 删除都认这个）
├── backend/                    ⬅ 同事的（文件管理 demo，端口 3002）
│   └── src/config.ts           需要改一行：uploadDir: '../storage/raw'（原 './storage/raw'）
├── frontend/                   ⬅ 同事的（硬编码连 3002）
├── docs/                       ⬅ 设计文档
└── services/
    └── chunking-rag/           ⬅ 我们的新服务（端口 3002，与 backend 二选一启动）
        ├── package.json        独立依赖
        ├── tsconfig.json
        ├── .env.example        端口、LLM key、UPLOAD_DIR 默认 ../../storage/raw
        ├── README.md           启动说明 + 与同事 backend 的关系
        ├── src/
        │   ├── server.ts       Express，监听 3002
        │   ├── types.ts        v1 类型 + 适配前端契约的字段
        │   ├── converter/      v1 converter + 我们的 chunker.ts
        │   ├── database/       v1 SQLite + chunks 表
        │   ├── retriever/      v1 关键词+语义检索
        │   ├── qa/             v1 问答 orchestration
        │   ├── llm/            v1 LLM 集成
        │   └── routes/
        │       ├── upload.ts   v1（含三阶段状态机）+ 新增 /raw-files 子路由
        │       ├── qa.ts       v1（含空 chunks 守卫）+ 新增 DELETE /files/:name + 调整 /stats
        │       └── qa-stream.ts 改写 SSE 协议匹配前端
        └── storage/            **服务私有**（chunker pipeline 内部状态，别的服务不该读）
            ├── converted/      转换后 markdown
            ├── mappings/       行号映射 JSON
            └── knowledge.db    SQLite 主存储
```

**关键约束**：
1. 3002 端口同时只能一个服务监听。约定"谁演示谁启动"，不上反向代理。
2. **存储分层**：`/storage/raw/`（项目根）是跨服务共享的上传文件池；每个服务自己的 `storage/` 是内部状态（DB、derived artifacts）。原则："共享数据在顶层，服务状态在服务里"。
3. 同事 backend 的 `config.upload.uploadDir` 需要从 `./storage/raw` 改成 `../storage/raw`——这是让他也能用共享 raw 的必要最小改动。提交这一行改动时打个招呼。

---

## 前端 → 后端契约对齐

| 端点 | 前端期望 | v1 现状 | 适配动作 |
|---|---|---|---|
| `GET /api/qa/stats` | `{success, totalFiles, ...}` | `{success, stats: {fileCount, chunkCount}}` | 添加 `totalFiles` 字段（值 = `fileCount`），保留 `stats` 嵌套以兼容老接口 |
| `GET /api/upload/raw-files?page=N&limit=10` | `{success, files: [{name, path, size, createdAt, modifiedAt}], total, page, limit, totalPages}` | ❌ 不存在 | 新增端点，按 `storage/raw/` 目录列文件并分页 |
| `POST /api/upload` | 上传 + 返回 `{success, files: [{id, originalName, ...}], message}` | 已有 v1 实现（含转换+切分+三阶段状态机） | 落点改成 `storage/raw/`；文件名 sanitize 而非 UUID（D2b）；保留三阶段状态机；响应字段对齐 |
| `POST /api/qa/ask-stream` | SSE `data: {answer: '...', sources: [...]}` | SSE `data: {type, content: {...}}` | 改写 SSE 事件 schema：每个 chunk 直接发 `{answer: <增量文本>}`，结束前发一次 `{sources: [...]}` |
| `GET /api/qa/files` | `{success, files: [{name, size, mtime, ...}], total}` ([前端 files/page.tsx:9](../../../frontend/app/files/page.tsx) 类型声明 `{name, size, mtime}`) | 返回 `{id, original_name, format, size, upload_time, category}`——**字段名不对** | **必改：返回的每个 file 含 `name`（= 磁盘文件名 = D2b 的 sanitize 名）+ `size` + `mtime`（取自 `fs.statSync(rawPath).mtime`）+ 兼容字段 `id, format, uploadTime, category`** |
| `DELETE /api/qa/files/:filename` | `{success, message}` | ❌ 不存在 | 新增端点，从 `storage/raw/` 删文件 + 从 DB 级联删 chunks |

---

## 关键设计决策

### D1. v1 代码原样搬，不重构成 v2 设计
- v1 已经是 working state（节省时间）
- v2 设计（char_offset、content_type 三类切分、200 char overlap、句子级 fallback）需要 ~1 天重写，赛题没这个预算
- v2 元素（reranker、查询扩展）作为后续 task 列入 ISSUES.md 的 v2 升级路径

### D2. 上传落点 = 项目根 `/storage/raw/`（跨服务共享），砍掉服务内 `original/` 目录

- **共享 `/storage/raw/`**：项目根级目录，前端上传 + 列表 + 删除都以此为准；两个服务（同事的 backend、我们的 chunking-rag）都指向这里，消除数据孤岛
- 我们服务通过 env var 配置：`.env.example` 加 `UPLOAD_DIR=../../storage/raw`（相对 `services-tuyh/chunking-rag/` cwd）
- 同事 backend 需要一行 config 改动：`./storage/raw` → `../storage/raw`（相对 `backend/` cwd）——**这是 B 方案唯一对同事代码的改动**
- v1 流程是 multer → 临时目录 → converter copy 到 `original/`：现在改成 multer 直接落到共享 `/storage/raw/`，converter 从那里读取，**不再 copy 到服务内 `original/`**（消除冗余）
- DB 里 `original_path` 字段含义变更：从 `storage/original/<uuid>.ext` 改成 `/storage/raw/<sanitized_name>`（绝对或相对都行，取 env var 解析的路径）
- **数据迁移风险**：无。同事砍掉了 RAG 链路后 main 上 chunks 表本来就是空的；根级 `/storage/` 当前不存在（我们刚删了 v1 残留），从零开始建
- **服务内只保留** `converted/`、`mappings/`、`knowledge.db`——chunker pipeline 的内部状态，同事 backend 不会读

### D2b. multer 文件名策略 + DB `original_name` 含义统一

**关键约束：让磁盘文件名 = DB 里的 `original_name` 字段 = 前端展示和删除用的 key。一处生成，处处一致。**

否则会出现：磁盘里叫 `foo_1.md`，DB 里 `original_name='foo.md'`，前端 DELETE 传 `foo_1.md`，DB 找不到，孤儿数据。



v1 用 `${uuid}${ext}`，UUID 前缀对前端不友好。同事用 `sanitizeFileName(fixEncoding(originalname))`——保留原名清非法字符。

我们对齐成同事的策略：

```typescript
function safeFilename(originalname: string, uploadDir: string): string {
  const fixed = fixEncoding(originalname);              // 修 latin1 → utf8 中文乱码
  const sanitized = sanitizeFileName(fixed);            // 清非法字符
  // 冲突保护
  let candidate = sanitized;
  let i = 1;
  while (fs.existsSync(path.join(uploadDir, candidate))) {
    const ext = path.extname(sanitized);
    const base = path.basename(sanitized, ext);
    candidate = `${base}_${i}${ext}`;
    i++;
  }
  return candidate;
}
```

- `fixEncoding` / `sanitizeFileName` 实现直接抄同事 [backend/src/routes/upload.ts:23-114](../../../backend/src/routes/upload.ts) 的同名函数（避免重新发明）
- 同名冲突自动加 `_1`、`_2` 后缀
- **`db.insertFile({ original_name: safeFilename(...), ... })`**——存进 DB 的 `original_name` 就是磁盘文件名，和 `:filename` 路径参数一致，DELETE 反查零歧义
- 副作用：用户上传 `foo bar.md` 会变成 `foo_bar.md` 显示——可接受（同事的实现也是这个行为）

### D3. DELETE /files/:filename — 文件名做主键，反查 file_id 后级联删

`:filename` 是 `raw/` 下的实际文件名（sanitize 后的原名，可能带 `_1` 后缀）。流程：

```typescript
router.delete('/files/:filename', (req, res) => {
  const { filename } = req.params;
  const filePath = path.join(rawDir, filename);

  // 1. 查 DB：同名 original_name 的所有记录（理论上唯一，防御性写成数组）
  const allFiles = db.getAllFiles();
  const matches = allFiles.filter(f => f.original_name === filename);

  // 2. 级联删 chunks + 删 file 记录
  for (const f of matches) {
    db.deleteFileChunks(f.id);
    db.deleteFile(f.id);
  }

  // 3. 删 raw/ 物理文件
  if (fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  } else if (matches.length === 0) {
    return res.status(404).json({ success: false, message: '文件不存在' });
  }

  // 4. 也删 converted/ 和 mappings/ 里对应文件（用 file.id 找）
  for (const f of matches) {
    const convPath = path.join(convertedDir, `${f.id}.md`);
    const mapPath = path.join(mappingsDir, `${f.id}.json`);
    if (fs.existsSync(convPath)) fs.unlinkSync(convPath);
    if (fs.existsSync(mapPath)) fs.unlinkSync(mapPath);
  }

  res.json({ success: true, message: '文件已删除' });
});
```

**边界情况**：
- 如果文件在 raw/ 但 DB 里没有（比如手工 cp 进去的，没经过 upload）：只删文件，不报错
- 如果 DB 里有但 raw/ 没有（不一致）：删 DB 记录 + chunks，但响应改成 `{success: true, message: '文件不存在但清理了 DB 记录'}`

**原子性策略：best-effort + 日志，不做事务回滚**

承认一个工程现实：SQLite + 文件系统跨原子操作不可能，强行模拟事务会让 DELETE 路径复杂到不可读。规则：

1. **失败顺序**：先 DB（`deleteFileChunks` + `deleteFile`，单个 SQLite 事务），再 raw 文件，再 sidecar（converted/mappings）
2. **DB 删除失败**：直接 throw，整个 DELETE 返回 500，不动文件
3. **raw 文件删除失败**：`console.warn` 记录，**继续**删 sidecar，最终响应仍 `success: true` 带 `warning` 字段提示用户手动清理
4. **sidecar 删除失败**：同上，warn 但不影响主流程
5. **不一致兜底**：每天/启动时跑一次 GC（扫描 raw/ 找无 DB 记录的文件 + 扫描 DB 找无 raw 文件的记录），打印日志——**MVP 不实现**，列入后续 task

理由：raw 文件删除失败的概率极低（基本只有权限问题或磁盘满）；如果发生，DB 已经一致（chunks 没了，检索不会再用），剩下个孤儿物理文件不影响功能，比"DB 还在但文件没了"或者"事务一半"好处理。

### D4. SSE 协议对齐前端解析逻辑
- 前端代码（`page.tsx:215-225`）：
  ```js
  if (data.answer) answer += data.answer;
  if (data.sources) sources = data.sources;
  ```
- 我们的 stream 必须只发 `{answer: '...'}` 或 `{sources: [...]}`，不能用 `{type, content: {...}}` 嵌套
- 改写 `qa-stream.ts` 的 `sendEvent` 简化为 `res.write(\`data: ${JSON.stringify(payload)}\n\n\`)`

**已知风险（不在本次解决）**：前端 `chunk.split('\n')` 不做跨 chunk buffer，理论上 TCP 分帧切到 SSE event 中间会让 JSON.parse 失败被静默吞掉。

实务评估：单 event payload ~50 字节（answer token 增量 + JSON 包装），远小于 TCP MSS 1460 字节，绝大多数情况一个 TCP 包能放数十个 event。MVP 演示场景概率很低，不预先工程化 buffer。

**缓解措施（如果实测出现问题再做）**：
- 短期：服务端每个 event 后 `res.flush()` 强制 flush，且让 event 之间有明显 `\n\n` 边界
- 长期：前端加跨 chunk buffer（违反"前端 0 修改"，需要改 [page.tsx:201-225](../../../frontend/app/page.tsx)）

### D5. /api/qa/stats 同时支持新旧字段
```json
{
  "success": true,
  "totalFiles": 5,           // 前端用这个
  "stats": {
    "fileCount": 5,          // v1 兼容
    "chunkCount": 142,       // v1 兼容
    "indexedCount": 142
  }
}
```

### D6. 端口冲突的约定
- README 明确写 "启动前先停掉同事的 backend"（`lsof -ti:3002 | xargs kill`）
- 不引入反向代理（增加复杂度，赛题用不上）
- 长期方案是统一架构（v2 重写），现在不解决

---

## 测试策略

### 单元测试（沿用 v1）
- `src/converter/chunker.test.ts` 14 个测试全部带过来，应该一个不变全绿

### 集成测试（手工走一遍）
1. `cd services-tuyh/chunking-rag && npm install && npm run dev`
2. `cd frontend && npm run dev`（默认 3000）
3. 浏览器打开 http://localhost:3000
4. 上传一份 md → 看 stats 数字 → 在文件列表里能看到 → 提问 → 流式答案出现
5. 删除文件 → DB chunks 被清掉

### 兼容性验证
- `cd services-tuyh/chunking-rag && PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm test` → `# pass 14 / # fail 0`（v1 的 chunker 测试一个不变全过）
- `cd services-tuyh/chunking-rag && PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l` → `2`（仅保留 v1 的 2 个 pre-existing TS 错误：`converter/index.ts:208` Buffer 类型问题、`llm/index.ts:2` RetrievedChunk 未导出。**不允许引入第 3 个**）
- `tsc --noEmit` 同上检测口径

---

## 不在本次范围

- v2 char_offset anchor 重构
- v2 三类内容感知切分
- bge-m3 / reranker 接入
- 增量更新 5min SLA pipeline
- 反向代理双服务并存
- 修复 v1 残留的两个 pre-existing TS 错误（converter/index.ts:208、llm/index.ts:2）

这些都列入 v2 升级路径，本次先 ship 集成版。
