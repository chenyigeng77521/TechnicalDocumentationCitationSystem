# Chunking RAG Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v1 `feature/chunking-mvp` 分支的完整 RAG 链路（converter + chunker + SQLite + retriever + LLM + 三阶段 upload 状态机）打包成独立服务 `services/chunking-rag/`，监听 port 3002，让前端 `frontend/app/page.tsx`（硬编码连 `localhost:3002`）零修改即可使用上传 + 切分 + 问答 + 删除全功能。

**Architecture:** 目录平级架构——`backend/`（同事的文件管理 demo，RAG 链路已砍）、`services/chunking-rag/`（我们的完整 RAG 服务）、`frontend/`（共用）。`/storage/raw/` 在项目根作为**跨服务共享**上传文件池；各服务内部 `storage/` 是私有状态（DB、converted、mappings）。3002 端口两服务二选一启动。

**Tech Stack:** TypeScript ESM, Node 20 (via nvm), Express, multer, better-sqlite3, openai SDK, mammoth/xlsx/pdf-parse, tsx, node:test。直接复用 v1 的依赖集。

**Spec:** [2026-04-23-chunking-rag-service-design.md](../specs/2026-04-23-chunking-rag-service-design.md)

## 执行方式约定

- **直接工作在 main 分支**（用户指示，不走 feature branch）
- **subagent 只负责 commit，不负责 push**。每个 task 的"Commit"步骤只执行 `git add` + `git commit`
- **controller（控制节点）在每个 task 通过 spec + code review 后执行 `git pull --rebase origin main && git push ...`**，避免 token 进入 subagent prompt
- Commit message 里不加 `🤖 Generated...` 之类的脚注；保留 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` 行

## File Structure

| 路径 | 操作 | 职责 |
|---|---|---|
| `services/chunking-rag/package.json` | 创建 | 独立依赖声明（express, multer, better-sqlite3, openai, mammoth, xlsx, pdf-parse, uuid, cors, dotenv + dev: tsx, typescript） |
| `services/chunking-rag/tsconfig.json` | 创建 | ES2022 + ESM + outDir `./dist` |
| `services/chunking-rag/.env.example` | 创建 | `PORT=3002`, `UPLOAD_DIR=../../storage/raw`, `DB_PATH=./storage/knowledge.db`, LLM 配置 |
| `services/chunking-rag/.gitignore` | 创建 | `node_modules/`, `dist/`, `storage/` |
| `services/chunking-rag/README.md` | 创建 | 启动方式、同事 backend 共存说明 |
| `services/chunking-rag/src/server.ts` | 复制改 | v1 server.ts，监听 3002，加载 .env |
| `services/chunking-rag/src/types.ts` | 复制 | v1 完整类型（含 ChunkInsertInput） |
| `services/chunking-rag/src/converter/index.ts` | 复制改 | v1 + 去掉 `original/` 目录写入逻辑 |
| `services/chunking-rag/src/converter/chunker.ts` | 复制 | v1 chunker（md/docx/xlsx/pdf + 2000-char 硬切） |
| `services/chunking-rag/src/converter/chunker.test.ts` | 复制 | v1 的 14 个测试 |
| `services/chunking-rag/src/database/index.ts` | 复制 | v1 DatabaseManager |
| `services/chunking-rag/src/retriever/index.ts` | 复制 | v1 Retriever |
| `services/chunking-rag/src/qa/index.ts` | 复制 | v1 QAAgent |
| `services/chunking-rag/src/llm/index.ts` | 复制 | v1 LLM streaming |
| `services/chunking-rag/src/routes/upload.ts` | 复制改 | v1 + multer 落 raw/ + safeFilename + 新增 /raw-files 子路由 |
| `services/chunking-rag/src/routes/qa.ts` | 复制改 | v1 + /stats 加 totalFiles + /files 字段对齐 + DELETE /files/:name |
| `services/chunking-rag/src/routes/qa-stream.ts` | 复制改 | v1 + SSE 协议简化为 {answer} / {sources} |
| `storage/raw/.gitkeep` | 创建 | 项目根共享上传目录占位 |
| `backend/src/config.ts` | 修改 | `uploadDir: './storage/raw'` → `'../storage/raw'`（让同事也用共享目录） |

---

## Task 1: 初始化服务目录骨架

**Files:**
- Create: `services/chunking-rag/package.json`
- Create: `services/chunking-rag/tsconfig.json`
- Create: `services/chunking-rag/.gitignore`
- Create: `services/chunking-rag/.env.example`
- Create: `storage/raw/.gitkeep`

- [ ] **Step 1: 创建 services/chunking-rag/ 目录结构**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
mkdir -p services/chunking-rag/src/{converter,database,retriever,qa,llm,routes}
mkdir -p services/chunking-rag/storage/{converted,mappings}
mkdir -p storage/raw
touch storage/raw/.gitkeep
```

- [ ] **Step 2: 创建 package.json**

写入 `services/chunking-rag/package.json`：

```json
{
  "name": "chunking-rag",
  "version": "1.0.0",
  "description": "RAG service with chunking, retrieval, and Q&A for Technical Documentation Citation System",
  "main": "dist/server.js",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "start": "node dist/server.js",
    "dev": "tsx src/server.ts",
    "test": "tsx --test src/converter/chunker.test.ts"
  },
  "dependencies": {
    "express": "^4.18.2",
    "multer": "^1.4.5-lts.1",
    "mammoth": "^1.6.0",
    "xlsx": "^0.18.5",
    "pdf-parse": "^1.1.1",
    "openai": "^4.28.0",
    "uuid": "^9.0.0",
    "cors": "^2.8.5",
    "dotenv": "^16.3.1",
    "better-sqlite3": "^9.4.3"
  },
  "devDependencies": {
    "@types/express": "^4.17.21",
    "@types/multer": "^1.4.11",
    "@types/pdf-parse": "^1.1.4",
    "@types/uuid": "^9.0.8",
    "@types/cors": "^2.8.17",
    "@types/better-sqlite3": "^7.6.9",
    "typescript": "^5.3.3",
    "tsx": "^4.7.1"
  }
}
```

- [ ] **Step 3: 创建 tsconfig.json**

写入 `services/chunking-rag/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "node",
    "lib": ["ES2022"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": false,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 4: 创建 .gitignore**

写入 `services/chunking-rag/.gitignore`：

```
node_modules/
dist/
storage/
.env
```

- [ ] **Step 5: 创建 .env.example**

写入 `services/chunking-rag/.env.example`：

```
# ==================== 服务器配置 ====================
PORT=3002
HOST=0.0.0.0

# ==================== 存储配置 ====================
# 共享上传目录（项目根级 /storage/raw），路径相对 services/chunking-rag/ cwd
UPLOAD_DIR=../../storage/raw

# 服务私有 SQLite 存储
DB_PATH=./storage/knowledge.db

# ==================== LLM API 配置（可选） ====================
# 如果配置了 LLM API，将启用语义检索 + 生成答案
# 否则使用关键词检索（兜底模式）
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo

EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=1536

# ==================== 系统配置 ====================
STRICT_MODE=true
```

- [ ] **Step 6: 安装依赖**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm install
```

Expected: 安装成功，生成 `node_modules/`，无 error 级别输出。

- [ ] **Step 7: 验证目录结构**

Run: `ls services/chunking-rag/`
Expected: 看到 `package.json`, `tsconfig.json`, `.gitignore`, `.env.example`, `node_modules/`, `src/`, `storage/`

- [ ] **Step 8: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/package.json services/chunking-rag/tsconfig.json services/chunking-rag/.gitignore services/chunking-rag/.env.example storage/raw/.gitkeep
git commit -m "feat(chunking-rag): scaffold service directory and config files"
# controller 会在 review 通过后 push
```


---

## Task 2: 从 feature/chunking-mvp 搬 v1 全部代码

**Files:**
- Create: `services/chunking-rag/src/server.ts`
- Create: `services/chunking-rag/src/types.ts`
- Create: `services/chunking-rag/src/converter/index.ts`
- Create: `services/chunking-rag/src/converter/chunker.ts`
- Create: `services/chunking-rag/src/converter/chunker.test.ts`
- Create: `services/chunking-rag/src/database/index.ts`
- Create: `services/chunking-rag/src/retriever/index.ts`
- Create: `services/chunking-rag/src/qa/index.ts`
- Create: `services/chunking-rag/src/llm/index.ts`
- Create: `services/chunking-rag/src/routes/upload.ts`
- Create: `services/chunking-rag/src/routes/qa.ts`
- Create: `services/chunking-rag/src/routes/qa-stream.ts`

- [ ] **Step 1: 从 feature/chunking-mvp 分支提取所有 src 文件**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem

# 从 feature/chunking-mvp 分支一次性 checkout src/ 到服务目录
git show feature/chunking-mvp:src/types.ts > services/chunking-rag/src/types.ts
git show feature/chunking-mvp:src/server.ts > services/chunking-rag/src/server.ts
git show feature/chunking-mvp:src/converter/index.ts > services/chunking-rag/src/converter/index.ts
git show feature/chunking-mvp:src/converter/chunker.ts > services/chunking-rag/src/converter/chunker.ts
git show feature/chunking-mvp:src/converter/chunker.test.ts > services/chunking-rag/src/converter/chunker.test.ts
git show feature/chunking-mvp:src/database/index.ts > services/chunking-rag/src/database/index.ts
git show feature/chunking-mvp:src/retriever/index.ts > services/chunking-rag/src/retriever/index.ts
git show feature/chunking-mvp:src/qa/index.ts > services/chunking-rag/src/qa/index.ts
git show feature/chunking-mvp:src/llm/index.ts > services/chunking-rag/src/llm/index.ts
git show feature/chunking-mvp:src/routes/upload.ts > services/chunking-rag/src/routes/upload.ts
git show feature/chunking-mvp:src/routes/qa.ts > services/chunking-rag/src/routes/qa.ts
git show feature/chunking-mvp:src/routes/qa-stream.ts > services/chunking-rag/src/routes/qa-stream.ts
```

- [ ] **Step 2: 编译验证（应出现 2 个 pre-existing TS 错误，不允许更多）**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | tee /tmp/ts-errors.txt
wc -l /tmp/ts-errors.txt
```

Expected:
```
src/converter/index.ts(208,33): error TS2345: Argument of type 'string' is not assignable to parameter of type 'Buffer<ArrayBufferLike>'.
src/llm/index.ts(2,10): error TS2305: Module '"../types"' has no exported member 'RetrievedChunk'.
       2 /tmp/ts-errors.txt
```

如果 `wc -l` 显示 3 或更多，报 BLOCKED。

- [ ] **Step 3: 运行 v1 单元测试验证（14 个全绿）**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm test 2>&1 | tail -10
```

Expected: `# pass 14 / # fail 0`

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/
git commit -m "feat(chunking-rag): import v1 RAG pipeline from feature/chunking-mvp"
# controller 会在 review 通过后 push
```

---

## Task 3: 改造 multer 落点到共享 /storage/raw/，砍掉 original/ 冗余

**Files:**
- Modify: `services/chunking-rag/src/routes/upload.ts` — multer dest 用 env var
- Modify: `services/chunking-rag/src/converter/index.ts` — 去掉 `original/` 目录写入

- [ ] **Step 1: 修改 upload.ts multer destination**

在 `services/chunking-rag/src/routes/upload.ts` 顶部 import 后加：

```typescript
import * as dotenv from 'dotenv';
dotenv.config();
```

找到现有的 multer storage 配置块（`const storage = multer.diskStorage({ ... })`），把 destination 部分改成：

```typescript
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const uploadDir = process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw');
    const resolvedDir = path.resolve(uploadDir);
    if (!fs.existsSync(resolvedDir)) {
      fs.mkdirSync(resolvedDir, { recursive: true });
    }
    cb(null, resolvedDir);
  },
  filename: (req, file, cb) => {
    // 文件名策略在 Task 4 处理；此步仍用 UUID 作为过渡
    const uniqueName = `${uuidv4()}${path.extname(file.originalname)}`;
    cb(null, uniqueName);
  }
});
```

- [ ] **Step 2: 修改 converter/index.ts 去掉 original/ 目录写入**

找到 `ensureDirectories()`（约 lines 25-37），删除 `path.join(this.storagePath, 'original')` 的条目：

```typescript
private ensureDirectories(): void {
  const dirs = [
    path.join(this.storagePath, 'converted'),
    path.join(this.storagePath, 'mappings')
  ];

  for (const dir of dirs) {
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }
}
```

在 `convert()` 函数末尾（约 lines 101-106），删除复制原文件的逻辑：

```typescript
// 删除以下 4 行：
// const ext = path.extname(originalFileName);
// const originalPath = path.join(this.storagePath, 'original', `${fileId}${ext}`);
// // @ts-ignore - 类型检查问题，实际运行正常
// fs.copyFileSync(filePath, originalPath);
```

并把返回的 `originalPath` 改为直接用入参 `filePath`：

```typescript
return {
  mdContent,
  lineMappings,
  convertedPath,
  originalFile: originalFileName,
  originalPath: filePath  // 原文件已经在 /storage/raw/，不再复制
};
```

- [ ] **Step 3: 编译 + 测试**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm test 2>&1 | tail -5
```

Expected:
- grep | wc -l: `       1`（之前的 `converter/index.ts:208` Buffer 错误在改动中消失，因为我们删掉了 copyFileSync 那行！只剩 `llm/index.ts:2` RetrievedChunk 错误）
- npm test: `# pass 14`

**关键**：本 task 意外修复了一个 pre-existing 错误。更新后续 task 的验证口径从"2 个 pre-existing"改成"1 个"。

- [ ] **Step 4: 手工启动服务验证上传落点**

```bash
cd services/chunking-rag
lsof -ti:3002 | xargs kill -9 2>/dev/null
cp .env.example .env
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task3-server.log 2>&1 &
SERVER_PID=$!
sleep 5

# 上传一个小 md 文件
echo "# Test\n\nHello from task 3" > /tmp/test-task3.md
curl -s -F "files=@/tmp/test-task3.md" http://localhost:3002/api/upload | head -c 300
echo ""

# 验证文件在共享 /storage/raw/
ls -la /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem/storage/raw/ | head -5

kill $SERVER_PID 2>/dev/null
```

Expected: `/storage/raw/` 里出现一个 UUID 命名的 .md 文件（`.gitkeep` 之外）。

- [ ] **Step 5: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/upload.ts services/chunking-rag/src/converter/index.ts
git commit -m "feat(chunking-rag): upload to shared /storage/raw, drop original/ duplication"
# controller 会在 review 通过后 push
```

---

## Task 4: multer 文件名策略 safeFilename + DB original_name 对齐

**Files:**
- Create: `services/chunking-rag/src/routes/filename-utils.ts`
- Modify: `services/chunking-rag/src/routes/upload.ts`

- [ ] **Step 1: 从同事 backend 抄 fixEncoding + sanitizeFileName 实现**

创建 `services/chunking-rag/src/routes/filename-utils.ts`：

```typescript
/**
 * 文件名处理工具
 * 从 backend/src/routes/upload.ts 抄过来，保持两服务一致
 */
import * as fs from 'fs';
import * as path from 'path';

export function fixEncoding(filename: string): string {
  try {
    const buffer = Buffer.from(filename, 'latin1');
    const decoded = buffer.toString('utf8');
    const hasChinese = /[\u4e00-\u9fa5]/.test(decoded);
    const hasGarbage = /[^\x00-\x7F]/.test(filename);
    if (hasGarbage && hasChinese) return decoded;
    return filename;
  } catch {
    return filename;
  }
}

export function sanitizeFileName(fileName: string): string {
  let cleanName = fixEncoding(fileName);
  const illegalChars = /[<>:"/\\|?*\x00-\x1f]/g;
  cleanName = cleanName.replace(illegalChars, '_').trim();
  cleanName = cleanName.replace(/^\.+|\.+$/g, '');
  cleanName = cleanName.replace(/[/\\]/g, '_');

  const lastDotIndex = cleanName.lastIndexOf('.');
  if (lastDotIndex > 0) {
    const name = cleanName.substring(0, lastDotIndex);
    const ext = cleanName.substring(lastDotIndex);
    cleanName = name.replace(/\./g, '_') + ext;
  }

  return cleanName || 'unnamed_file';
}

/**
 * 生成磁盘安全文件名，含同名冲突自动加后缀
 */
export function safeFilename(originalname: string, uploadDir: string): string {
  const sanitized = sanitizeFileName(originalname);
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

- [ ] **Step 2: 修改 upload.ts multer filename + insertFile**

在 `services/chunking-rag/src/routes/upload.ts` 顶部加 import：

```typescript
import { safeFilename, fixEncoding } from './filename-utils.js';
```

把 multer filename 回调改成：

```typescript
  filename: (req, file, cb) => {
    const uploadDir = process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw');
    const resolvedDir = path.resolve(uploadDir);
    const safeName = safeFilename(file.originalname, resolvedDir);
    cb(null, safeName);
  }
```

找到 `db.insertFile({...})` 调用（在三阶段状态机的 Stage 1，约 `status: 'converting'` 那里），修改 `original_name` 字段：

```typescript
db.insertFile({
  id: fileId,
  original_name: path.basename(file.path),  // 已被 multer 保存为 sanitize + 冲突后的最终文件名
  original_path: conversionResult.originalPath,
  // ... 其余不变
});
```

**设计不变性**：这里 `path.basename(file.path)` 就是 multer 写盘用的 safeFilename 结果（含可能的 `_1`、`_2` 后缀）。DB `original_name` = 磁盘文件名 = 前端 DELETE 传的 key，三者一致。

- [ ] **Step 3: 编译 + 测试**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm test 2>&1 | tail -3
```

Expected: `       1`（仍只有 llm/index.ts:2 那个）+ `# pass 14`

- [ ] **Step 4: 手工集成测试**

```bash
cd services/chunking-rag
rm -f storage/knowledge.db
rm -f ../../storage/raw/*.md ../../storage/raw/*.txt 2>/dev/null
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task4-server.log 2>&1 &
SERVER_PID=$!
sleep 5

# 上传中文名文件
cp /tmp/test-task3.md "/tmp/测试中文.md"
curl -s -F "files=@/tmp/测试中文.md" http://localhost:3002/api/upload | head -c 400
echo ""

# 验证 raw/ 里是清理过的文件名，而不是 UUID
ls ../../storage/raw/ | head -5

# 验证 DB original_name 匹配磁盘文件名
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH node -e "
import Database from 'better-sqlite3';
const db = new Database('./storage/knowledge.db');
const rows = db.prepare('SELECT original_name, original_path FROM files').all();
console.log(rows);
" 2>&1

kill $SERVER_PID 2>/dev/null
```

Expected:
- raw/ 下有 `测试中文.md`（不是 UUID.md）
- DB `original_name` 字段 = `测试中文.md`

- [ ] **Step 5: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/filename-utils.ts services/chunking-rag/src/routes/upload.ts
git commit -m "feat(chunking-rag): sanitize filename and align DB original_name to disk name"
# controller 会在 review 通过后 push
```

---

## Task 5: GET /api/qa/files 字段对齐前端契约

**Files:**
- Modify: `services/chunking-rag/src/routes/qa.ts` — `/files` 路由返回字段

- [ ] **Step 1: 修改 /files 路由返回结构**

在 `services/chunking-rag/src/routes/qa.ts` 找到 `router.get('/files', ...)`，把 `files.map(...)` 的转换修改为：

```typescript
router.get('/files', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const files = db.getAllFiles({ status: 'completed' });

    const uploadDir = path.resolve(process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw'));

    const responseFiles = files.map(f => {
      // mtime 从磁盘读（raw/<original_name>）
      let mtime = f.upload_time;  // fallback 用 upload_time
      try {
        const rawPath = path.join(uploadDir, f.original_name);
        if (fs.existsSync(rawPath)) {
          mtime = fs.statSync(rawPath).mtime.toISOString();
        }
      } catch {
        // best-effort
      }

      return {
        // 前端 page.tsx 和 files/page.tsx 都需要的字段
        name: f.original_name,
        size: f.size,
        mtime,
        // 兼容字段
        id: f.id,
        format: f.format,
        uploadTime: f.upload_time,
        category: f.category
      };
    });

    db.close();

    res.json({
      success: true,
      files: responseFiles,
      total: responseFiles.length
    });
  } catch (error: any) {
    console.error('❌ 获取文件列表失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});
```

确保顶部已 import `fs`、`path`：

```typescript
import * as fs from 'fs';
import * as path from 'path';
```

- [ ] **Step 2: 编译**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
```

Expected: `       1`

- [ ] **Step 3: 集成测试**

```bash
cd services/chunking-rag
# 假设上一 task 留下了数据
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task5-server.log 2>&1 &
SERVER_PID=$!
sleep 5

curl -s http://localhost:3002/api/qa/files | python3 -m json.tool

kill $SERVER_PID 2>/dev/null
```

Expected: 返回结构里每个 file 对象同时包含 `name`, `size`, `mtime`, `id`, `format`, `uploadTime`, `category`。

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/qa.ts
git commit -m "feat(chunking-rag): align /api/qa/files response to frontend contract (name/size/mtime)"
# controller 会在 review 通过后 push
```

---

## Task 6: GET /api/upload/raw-files 新端点（分页）

**Files:**
- Modify: `services/chunking-rag/src/routes/upload.ts` — 在文件末尾 `export default router` 前加新路由

- [ ] **Step 1: 添加 /raw-files 路由**

在 `services/chunking-rag/src/routes/upload.ts` 的 `export default router;` 之前，添加：

```typescript
/**
 * GET /api/upload/raw-files?page=N&limit=M
 * 列出共享 /storage/raw/ 下的文件（分页）
 * 契约：与同事 backend 的同名端点完全一致
 */
router.get('/raw-files', (req: Request, res: Response) => {
  try {
    const uploadDir = path.resolve(process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw'));
    const page = parseInt(req.query.page as string) || 1;
    const limit = parseInt(req.query.limit as string) || 10;
    const skip = (page - 1) * limit;

    if (!fs.existsSync(uploadDir)) {
      return res.json({
        success: true,
        files: [],
        total: 0,
        page,
        limit,
        totalPages: 0
      });
    }

    const files = fs.readdirSync(uploadDir)
      .filter(file => {
        if (file === '.gitkeep') return false;  // 跳过 git 占位符
        const p = path.join(uploadDir, file);
        try {
          return fs.statSync(p).isFile();
        } catch {
          return false;
        }
      })
      .map(file => {
        const filePath = path.join(uploadDir, file);
        const stats = fs.statSync(filePath);
        return {
          name: file,
          path: filePath,
          size: stats.size,
          createdAt: stats.birthtime,
          modifiedAt: stats.mtime
        };
      })
      .sort((a, b) => b.modifiedAt.getTime() - a.modifiedAt.getTime());

    const total = files.length;
    const paginatedFiles = files.slice(skip, skip + limit);

    res.json({
      success: true,
      files: paginatedFiles,
      total,
      page,
      limit,
      totalPages: Math.ceil(total / limit)
    });
  } catch (error: any) {
    console.error('❌ 获取 raw 文件列表失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});
```

- [ ] **Step 2: 编译**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
```

Expected: `       1`

- [ ] **Step 3: 集成测试**

```bash
cd services/chunking-rag
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task6-server.log 2>&1 &
SERVER_PID=$!
sleep 5

curl -s "http://localhost:3002/api/upload/raw-files?page=1&limit=10" | python3 -m json.tool

kill $SERVER_PID 2>/dev/null
```

Expected: 响应含 `files`, `total`, `page`, `limit`, `totalPages` 字段；`files` 里的每项有 `name`, `path`, `size`, `createdAt`, `modifiedAt`。

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/upload.ts
git commit -m "feat(chunking-rag): add GET /api/upload/raw-files paginated endpoint"
# controller 会在 review 通过后 push
```

---

## Task 7: GET /api/qa/stats 加 totalFiles 字段

**Files:**
- Modify: `services/chunking-rag/src/routes/qa.ts` — `/stats` 路由响应

- [ ] **Step 1: 修改 /stats 路由响应 JSON**

找到 `router.get('/stats', ...)` 块，把 `res.json({...})` 改为：

```typescript
router.get('/stats', (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();
    const stats = db.getStats();

    db.close();

    res.json({
      success: true,
      // 前端 page.tsx 期望的字段
      totalFiles: stats.fileCount,
      // 兼容 v1 老字段
      stats: {
        fileCount: stats.fileCount,
        chunkCount: stats.chunkCount,
        indexedCount: stats.chunkCount
      }
    });
  } catch (error: any) {
    console.error('❌ 获取统计信息失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});
```

- [ ] **Step 2: 编译 + 测试**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
```

Expected: `       1`

- [ ] **Step 3: 集成测试**

```bash
cd services/chunking-rag
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task7-server.log 2>&1 &
SERVER_PID=$!
sleep 5

curl -s http://localhost:3002/api/qa/stats | python3 -m json.tool

kill $SERVER_PID 2>/dev/null
```

Expected: 响应含 `totalFiles`（顶层）+ `stats.fileCount` + `stats.chunkCount`。

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/qa.ts
git commit -m "feat(chunking-rag): add totalFiles field to /api/qa/stats response"
# controller 会在 review 通过后 push
```

---

## Task 8: DELETE /api/qa/files/:filename 新端点

**Files:**
- Modify: `services/chunking-rag/src/routes/qa.ts`

- [ ] **Step 1: 添加 DELETE 路由**

在 `services/chunking-rag/src/routes/qa.ts` 的 `export default router;` 之前，添加：

```typescript
/**
 * DELETE /api/qa/files/:filename
 * 删除单个文件：raw/ + DB file 记录 + chunks + converted/mappings sidecar
 * Best-effort 策略（见 spec D3）
 */
router.delete('/files/:filename', (req: Request, res: Response) => {
  const { filename } = req.params;
  const db = new DatabaseManager();
  const uploadDir = path.resolve(process.env.UPLOAD_DIR || path.join(process.cwd(), '..', '..', 'storage', 'raw'));
  const convertedDir = './storage/converted';
  const mappingsDir = './storage/mappings';

  const rawPath = path.join(uploadDir, filename);
  const rawExists = fs.existsSync(rawPath);

  // 1. 查 DB：同名 original_name 的记录（理论上 0 或 1 条）
  const allFiles = db.getAllFiles();
  const matches = allFiles.filter(f => f.original_name === filename);

  if (!rawExists && matches.length === 0) {
    db.close();
    return res.status(404).json({
      success: false,
      message: '文件不存在'
    });
  }

  let warning: string | undefined;

  // 2. DB 删除：放在 try/catch，失败直接 500
  try {
    for (const f of matches) {
      db.deleteFileChunks(f.id);
      db.deleteFile(f.id);
    }
  } catch (dbErr: any) {
    db.close();
    console.error('❌ DB 删除失败:', dbErr);
    return res.status(500).json({
      success: false,
      message: `DB 删除失败: ${dbErr.message}`
    });
  }

  // 3. raw 文件删除：失败 warn 不报错
  if (rawExists) {
    try {
      fs.unlinkSync(rawPath);
    } catch (rawErr: any) {
      console.warn(`⚠️ raw 文件删除失败: ${rawErr.message}`);
      warning = `DB 已清理，但 raw 文件未能删除：${rawErr.message}`;
    }
  }

  // 4. sidecar 删除（converted + mappings）：失败 warn 不报错
  for (const f of matches) {
    for (const sidecarDir of [convertedDir, mappingsDir]) {
      const ext = sidecarDir === convertedDir ? '.md' : '.json';
      const sidecarPath = path.join(sidecarDir, `${f.id}${ext}`);
      if (fs.existsSync(sidecarPath)) {
        try {
          fs.unlinkSync(sidecarPath);
        } catch (sideErr: any) {
          console.warn(`⚠️ sidecar 删除失败 ${sidecarPath}: ${sideErr.message}`);
        }
      }
    }
  }

  db.close();

  const response: any = {
    success: true,
    message: !rawExists && matches.length > 0
      ? '文件不存在但清理了 DB 记录'
      : '文件已删除'
  };
  if (warning) response.warning = warning;

  res.json(response);
});
```

- [ ] **Step 2: 编译 + 测试**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
```

Expected: `       1`

- [ ] **Step 3: 集成测试 — 正常删除**

```bash
cd services/chunking-rag
rm -f storage/knowledge.db
rm -f ../../storage/raw/*.md ../../storage/raw/*.txt 2>/dev/null
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task8-server.log 2>&1 &
SERVER_PID=$!
sleep 5

# 上传 → 删除 → 验证
echo "# Delete test" > /tmp/to-delete.md
UPLOAD_RESP=$(curl -s -F "files=@/tmp/to-delete.md" http://localhost:3002/api/upload)
echo "Upload: $UPLOAD_RESP" | head -c 300
echo ""

# 列出 raw 确认
ls ../../storage/raw/ | grep delete

# 删除
curl -s -X DELETE "http://localhost:3002/api/qa/files/to-delete.md"
echo ""

# 验证都清了
ls ../../storage/raw/ | grep delete | wc -l  # should be 0
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH node -e "
import Database from 'better-sqlite3';
const db = new Database('./storage/knowledge.db');
console.log('files count:', db.prepare('SELECT COUNT(*) as c FROM files').get().c);
console.log('chunks count:', db.prepare('SELECT COUNT(*) as c FROM chunks').get().c);
" 2>&1

kill $SERVER_PID 2>/dev/null
```

Expected:
- Upload 返回 success
- `ls | grep delete | wc -l` = `0`
- DB: files count=0, chunks count=0

- [ ] **Step 4: 集成测试 — 不存在的文件**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task8b-server.log 2>&1 &
SERVER_PID=$!
sleep 5

curl -s -w "\nHTTP %{http_code}\n" -X DELETE "http://localhost:3002/api/qa/files/nonexistent.md"

kill $SERVER_PID 2>/dev/null
```

Expected: `HTTP 404` + `{"success":false,"message":"文件不存在"}`

- [ ] **Step 5: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/qa.ts
git commit -m "feat(chunking-rag): add DELETE /api/qa/files/:filename with cascade cleanup"
# controller 会在 review 通过后 push
```

---

## Task 9: POST /api/qa/ask-stream SSE 协议简化

**Files:**
- Modify: `services/chunking-rag/src/routes/qa-stream.ts`

- [ ] **Step 1: 改写 sendEvent 发送格式**

找到 `src/routes/qa-stream.ts` 里的 `const sendEvent = ...` 定义（约 line 30-32），并且找到所有调用 `sendEvent(...)` 的位置。

把整个 handler 结构简化。直接替换整个 `router.post('/ask-stream', ...)` 块为：

```typescript
router.post('/ask-stream', async (req: Request, res: Response) => {
  try {
    const { question, topK = 5 }: AskRequest = req.body;

    if (!question || typeof question !== 'string') {
      res.status(400).json({ error: '问题不能为空' });
      return;
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    // 前端约定：data: {answer: string} 或 data: {sources: string[]}
    const sendData = (payload: any) => {
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    };

    // 1. 检索
    const chunks = db.searchChunks(question).slice(0, topK);

    if (chunks.length === 0) {
      sendData({ answer: '抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。' });
      sendData({ sources: [] });
      res.end();
      return;
    }

    // 2. 构建 prompt
    const contextText = chunks.map((chunk, idx) =>
      `【文档 ${idx + 1}】${chunk.content.substring(0, 500)}`
    ).join('\n\n---\n\n');

    const prompt = `请根据以下【参考文档片段】回答问题。

【用户问题】
${question}

【参考文档片段】
${contextText}

【回答要求】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 如果文档中没有相关信息，请明确说明无法回答
3. 答案应直接、完整，避免额外无关解释

请开始回答：`;

    // 3. LLM 流式生成，每个 token 发一次 {answer}
    for await (const token of generateAnswer(prompt, question, chunks)) {
      sendData({ answer: token });
    }

    // 4. 发 sources（一次性）
    const sources = chunks.map(c => {
      const file = db.getFile(c.file_id);
      return file?.original_name || '未知文件';
    });
    sendData({ sources: Array.from(new Set(sources)) });  // 去重

    res.end();
  } catch (error: any) {
    console.error('❌ 流式问答失败:', error);
    // 前端解析 data:... 失败会静默吞；这里只能写一个 answer token 表示错误
    try {
      res.write(`data: ${JSON.stringify({ answer: `\n\n（服务器错误：${error.message}）` })}\n\n`);
    } catch {
      // connection may have closed
    }
    res.end();
  }
});
```

- [ ] **Step 2: 编译**

```bash
cd services/chunking-rag
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run build 2>&1 | grep "error TS" | wc -l
```

Expected: `       1`

- [ ] **Step 3: 集成测试 — 无 LLM Key 的拒答路径**

```bash
cd services/chunking-rag
rm -f storage/knowledge.db
rm -f ../../storage/raw/*.md 2>/dev/null
lsof -ti:3002 | xargs kill -9 2>/dev/null
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/task9-server.log 2>&1 &
SERVER_PID=$!
sleep 5

# 空库问答 → 应该返回拒答
curl -sN -X POST http://localhost:3002/api/qa/ask-stream \
  -H "Content-Type: application/json" \
  -d '{"question":"什么是 Kubernetes Pod?"}' \
  --max-time 15 | head -c 800

kill $SERVER_PID 2>/dev/null
```

Expected:
- 流式输出形如 `data: {"answer":"抱歉，在文档库中未找到..."}\n\ndata: {"sources":[]}\n\n`
- **关键**：JSON 里只含 `answer` 或 `sources` 顶层字段，**没有**嵌套 `{type, content:...}` 结构

- [ ] **Step 4: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/src/routes/qa-stream.ts
git commit -m "feat(chunking-rag): simplify SSE protocol to {answer}/{sources} for frontend compat"
# controller 会在 review 通过后 push
```

---

## Task 10: 同事 backend config 一行改动

**Files:**
- Modify: `backend/src/config.ts`

- [ ] **Step 1: 把 uploadDir 指向项目根 storage/raw/**

打开 `backend/src/config.ts`，找到 `uploadDir: './storage/raw'`，改为 `uploadDir: '../storage/raw'`。

完整修改后该部分应该是：

```typescript
export const config = {
  upload: {
    uploadDir: '../storage/raw',  // 项目根共享，相对 backend/ cwd
    maxFileSize: 300,
    allowedFormats: [
      '.json', '.yaml', '.yml', '.cpp', '.java', '.py', '.xml', '.sql',
      '.html', '.md', '.txt', '.ppt', '.pptx', '.xls', '.xlsx',
      '.doc', '.docx', '.pdf'
    ],
    maxFiles: 30,
  },
  // ...其余不变
};
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add backend/src/config.ts
git commit -m "$(cat <<'EOF'
chore(backend): point uploadDir to shared /storage/raw

同事 backend 的 config 路径从 ./storage/raw 改到 ../storage/raw，
让 backend 和 services/chunking-rag 共享同一个上传文件池。

这是 2026-04-23 chunking-rag service 集成方案（docs/superpowers/specs/）
要求的唯一对 backend 的改动。详见 D2 节。
EOF
)"
# controller 会在 review 通过后 push
```

---

## Task 11: 端到端集成测试（前端 + 我们的服务）

**Files:** 无代码改动，只做验证

- [ ] **Step 1: 清理环境**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
rm -f services/chunking-rag/storage/knowledge.db
rm -rf services/chunking-rag/storage/converted services/chunking-rag/storage/mappings
rm -f storage/raw/*.md storage/raw/*.txt storage/raw/*.pdf 2>/dev/null
lsof -ti:3002 | xargs kill -9 2>/dev/null
```

- [ ] **Step 2: 启动 chunking-rag 服务**

```bash
cd services/chunking-rag
cp .env.example .env
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/e2e-rag-server.log 2>&1 &
RAG_PID=$!
sleep 5

curl -s http://localhost:3002/health
echo ""
```

Expected: `{"status":"ok","timestamp":"...","version":"1.0.0"}`

- [ ] **Step 3: 启动前端**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem/frontend
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm install 2>&1 | tail -3
PATH=~/.nvm/versions/node/v20.20.2/bin:$PATH npm run dev > /tmp/e2e-frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 15  # Next.js 首次启动慢
```

- [ ] **Step 4: API 层 e2e 断言**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem

# 上传 eval 里一个样本
SAMPLE=$(ls eval/fixtures/*.md 2>/dev/null | head -1)
echo "Using: $SAMPLE"
curl -s -F "files=@${SAMPLE}" http://localhost:3002/api/upload | head -c 400
echo ""

# 查 stats
echo "--- stats ---"
curl -s http://localhost:3002/api/qa/stats
echo ""

# 查 raw-files
echo "--- raw-files ---"
curl -s "http://localhost:3002/api/upload/raw-files?page=1&limit=10" | head -c 500
echo ""

# 查 files
echo "--- files ---"
curl -s http://localhost:3002/api/qa/files | head -c 500
echo ""

# 问答（空 LLM key 走拒答路径）
echo "--- ask-stream ---"
curl -sN -X POST http://localhost:3002/api/qa/ask-stream \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Kubernetes?"}' \
  --max-time 15 | head -c 500
echo ""
```

所有断言：
- ✅ upload 返回 `"status":"completed"`
- ✅ stats `totalFiles >= 1`
- ✅ raw-files 里能看到上传的文件（`name` 字段）
- ✅ files 里每条含 `name/size/mtime/id/format/uploadTime/category`
- ✅ ask-stream 输出 `data: {"answer":...}` 和 `data: {"sources":[...]}` 行（无 `{type, content}` 嵌套）

- [ ] **Step 5: 手工打开浏览器验证前端渲染**

浏览器访问 http://localhost:3000，验证：
- 首页显示"文档数：1"
- 提问框输入 "What is Kubernetes?"，回答正常流式出现
- 点击"文件管理"，看到上传的文件，带时间和大小
- 点删除按钮，文件消失，首页文档数变为 0

**如果在无头环境无法手工测**：跳过 Step 5，只靠 Step 4 的 API 断言就够了。

- [ ] **Step 6: 停服务**

```bash
kill $RAG_PID 2>/dev/null
kill $FRONTEND_PID 2>/dev/null
```

- [ ] **Step 7: 记录 e2e 结果**

创建 `docs/superpowers/plans/chunking-rag-e2e-2026-04-23.txt`，把 Step 4 的所有 curl 响应粘进去，并写上:

```
Date: 2026-04-23
Branch: main (post chunking-rag integration)

Commit SHAs: <此次提交的 HEAD>

E2E Assertions:
[x] health: {"status":"ok"}
[x] upload: status=completed, file in /storage/raw/
[x] stats: totalFiles=1
[x] raw-files: paginated list with the uploaded file
[x] files: returns {name, size, mtime, id, format, uploadTime, category}
[x] ask-stream: emits {answer:...} and {sources:[...]} tokens, no nested {type, content}

Browser UI (if manually verified):
[ ] Homepage shows document count
[ ] Ask question streams answer
[ ] File management page lists files with time/size
[ ] Delete works
```

- [ ] **Step 8: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add docs/superpowers/plans/chunking-rag-e2e-2026-04-23.txt
git commit -m "docs: record chunking-rag service e2e integration test results"
# controller 会在 review 通过后 push
```

---

## Task 12: README + 最终扫尾

**Files:**
- Create: `services/chunking-rag/README.md`

- [ ] **Step 1: 写 README**

创建 `services/chunking-rag/README.md`：

```markdown
# chunking-rag Service

完整 RAG 服务：文档切分 + SQLite 存储 + 关键词/语义检索 + LLM 问答 + 三阶段 upload 状态机。

基于 `feature/chunking-mvp` 分支的 v1 代码改造而来，服务于 `frontend/` 的问答界面。

## 架构关系

```
项目根/
├── storage/raw/          ← 跨服务共享上传文件池
├── backend/              ← 同事的文件管理 demo（端口 3002，功能子集）
├── frontend/             ← 硬编码连 localhost:3002
└── services/chunking-rag/  ← 本服务（端口 3002，完整 RAG）
```

**端口冲突**：`backend/` 和本服务都绑 3002，同一时刻只能一个在跑。

## 启动

```bash
# 先确保 3002 没被占
lsof -ti:3002 | xargs kill -9 2>/dev/null

cd services/chunking-rag
cp .env.example .env   # 首次
npm install
npm run dev            # tsx hot reload
```

前端：
```bash
cd frontend
npm run dev            # port 3000
```

浏览器打开 http://localhost:3000。

## 端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /api/upload` | 文件上传（自动转换 + 切分 + 入库） |
| `GET /api/upload/raw-files?page=N&limit=M` | raw 目录分页列表 |
| `POST /api/qa/ask-stream` | SSE 流式问答，发 `{answer}` + `{sources}` |
| `GET /api/qa/stats` | 统计（`totalFiles`, `stats.fileCount`, `stats.chunkCount`） |
| `GET /api/qa/files` | 已切分文件列表 |
| `DELETE /api/qa/files/:filename` | 级联删除（raw + DB + sidecar） |

## 环境变量

见 `.env.example`。关键项：
- `PORT=3002`（与 frontend 硬编码一致）
- `UPLOAD_DIR=../../storage/raw`（相对 cwd，指向项目根共享目录）
- `DB_PATH=./storage/knowledge.db`（服务私有）
- `LLM_API_KEY=...`（可选；不配置时走拒答/关键词路径）

## 设计文档

- [2026-04-23 chunking-rag service integration design](../../docs/superpowers/specs/2026-04-23-chunking-rag-service-design.md)
- [Implementation plan](../../docs/superpowers/plans/2026-04-23-chunking-rag-service.md)
- [v1 chunking MVP spec](../../docs/superpowers/specs/2026-04-22-chunking-mvp-design.md)
```

- [ ] **Step 2: Commit**

```bash
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
git add services/chunking-rag/README.md
git commit -m "docs(chunking-rag): add service README with architecture and runbook"
# controller 会在 review 通过后 push
```

---

## 完成标志

- [ ] `services/chunking-rag/` 目录完整：config + src + storage 骨架 + README
- [ ] `cd services/chunking-rag && npm run build` 编译产出仅 1 个 pre-existing TS error（`llm/index.ts:2` RetrievedChunk）
- [ ] `cd services/chunking-rag && npm test` → `# pass 14 / # fail 0`
- [ ] 启动服务 + 前端，执行上传 → 问答 → 删除全流程，API 断言全绿
- [ ] `backend/src/config.ts` 已更新为共享 `/storage/raw/`
- [ ] main 分支每个 task 独立 commit，push 到 origin/main
