# Chunking MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 ISSUE-001 (P0) — 上传文件后自动按格式切分并写入 `chunks` 表，解锁 eval 评测。

**Architecture:** 新增 `src/converter/chunker.ts` 按格式（md/docx、xlsx、pdf、pptx）分派策略；`upload.ts` 用 `converting → completed / failed` 三阶段状态机集成；顺带修 ISSUE-002 的 `/api/qa/index` 空 chunks 守卫。不改 DB schema；types.ts 新增 `ChunkInsertInput` 输入类型以消除运行时/类型层的不一致。

**Tech Stack:** TypeScript (ES2022, strict off), Node.js ESM, Express, better-sqlite3, tsx, Node 内置 `node:test`（通过 tsx 执行）。

**Spec:** [2026-04-22-chunking-mvp-design.md](../specs/2026-04-22-chunking-mvp-design.md)

---

## File Structure

| 路径 | 操作 | 职责 |
|---|---|---|
| `src/types.ts` | 修改 | 新增 `ChunkInsertInput` 接口 |
| `src/database/index.ts` | 修改 | `insertChunk` / `insertChunks` 签名改用 `ChunkInsertInput` |
| `src/converter/chunker.ts` | 新增 | 按格式分派的切分逻辑，导出 `chunkDocument(input)` |
| `src/converter/chunker.test.ts` | 新增 | Node `node:test` 单元测试 |
| `src/routes/upload.ts` | 修改 | 加入切分步骤 + 三阶段状态机 |
| `src/routes/qa.ts` | 修改 | `/api/qa/index` 空 chunks 守卫 |
| `package.json` | 修改 | `test` 脚本改为 `tsx --test`，移除 jest 依赖声明 |

---

## Task 1: 新增 ChunkInsertInput 类型并适配 DB 层签名

**Files:**
- Modify: `src/types.ts`（末尾追加）
- Modify: `src/database/index.ts:160-181`（`insertChunk`）
- Modify: `src/database/index.ts:245-272`（`insertChunks`）

- [ ] **Step 1: 在 types.ts 末尾追加 ChunkInsertInput 类型**

打开 `src/types.ts`，在文件末尾追加：

```typescript
/**
 * 插入 chunk 时使用的输入类型。
 * 与 ChunkRecord 的区别：original_lines / vector 是运行时的数组，
 * 由 DB 层在写入时 JSON.stringify。ChunkRecord 反映的是 DB 中存储的 JSON 字符串。
 */
export interface ChunkInsertInput {
  id?: string;
  file_id: string;
  content: string;
  start_line: number;
  end_line: number;
  original_lines: number[];
  vector?: number[] | null;
}
```

- [ ] **Step 2: 修改 database/index.ts 的 import**

在 `src/database/index.ts` 顶部 import 行改成：

```typescript
import { FileRecord, ChunkRecord, ChunkInsertInput } from '../types.js';
```

- [ ] **Step 3: 改 insertChunk 签名与实现**

把 [src/database/index.ts:160-181](../../../src/database/index.ts) 的 `insertChunk` 整体替换为：

```typescript
  insertChunk(chunk: ChunkInsertInput): string {
    const id = chunk.id || uuidv4();
    const originalLinesJson = JSON.stringify(chunk.original_lines);
    const vectorJson = chunk.vector ? JSON.stringify(chunk.vector) : null;

    const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      chunk.file_id,
      chunk.content,
      chunk.start_line,
      chunk.end_line,
      originalLinesJson,
      vectorJson
    );

    return id;
  }
```

- [ ] **Step 4: 改 insertChunks 签名**

把 [src/database/index.ts:245-272](../../../src/database/index.ts) 的 `insertChunks` 签名 `chunks: (Omit<ChunkRecord, 'id'> & { id?: string })[]` 改成 `chunks: ChunkInsertInput[]`，函数体内其余保持不变：

```typescript
  insertChunks(chunks: ChunkInsertInput[]): string[] {
    const ids: string[] = [];

    const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    const insert = this.db.transaction((chunkList: ChunkInsertInput[]) => {
      for (const chunk of chunkList) {
        const id = chunk.id || uuidv4();
        ids.push(id);

        stmt.run(
          id,
          chunk.file_id,
          chunk.content,
          chunk.start_line,
          chunk.end_line,
          JSON.stringify(chunk.original_lines),
          chunk.vector ? JSON.stringify(chunk.vector) : null
        );
      }
    });

    insert(chunks);
    return ids;
  }
```

- [ ] **Step 5: 验证 TypeScript 编译**

Run: `npm run build`
Expected: PASS（无 TS 错误，生成 `dist/`）

- [ ] **Step 6: Commit**

```bash
git add src/types.ts src/database/index.ts
git commit -m "feat(types): add ChunkInsertInput for chunker → db boundary"
```

---

## Task 2: 切换测试运行器到 Node 内置 test + tsx

**Files:**
- Modify: `package.json`
- Create: `src/converter/chunker.test.ts`（先放一个 sanity 测试占位）

- [ ] **Step 1: 修改 package.json 的 test 脚本**

把 [package.json:11](../../../package.json) 的 `"test": "jest"` 改为：

```json
    "test": "tsx --test src/converter/chunker.test.ts"
```

> 说明：避免用 `src/**/*.test.ts` 通配，防止 shell/tsx 之间的 glob 解析歧义。未来如新增其他 test 文件，直接在此列出即可。

- [ ] **Step 2: 创建 chunker.test.ts sanity 测试**

创建文件 `src/converter/chunker.test.ts`：

```typescript
import { test } from 'node:test';
import assert from 'node:assert';

test('test runner sanity', () => {
  assert.strictEqual(1 + 1, 2);
});
```

- [ ] **Step 3: 运行测试验证基础设施就绪**

Run: `npm test`
Expected: PASS — 看到 `# pass 1` 输出

- [ ] **Step 4: Commit**

```bash
git add package.json src/converter/chunker.test.ts
git commit -m "chore(test): switch to node:test via tsx"
```

---

## Task 3: chunker 骨架 + 确定性 chunkId + 空输入处理（TDD）

**Files:**
- Create: `src/converter/chunker.ts`
- Modify: `src/converter/chunker.test.ts`

- [ ] **Step 1: 写空输入与 deterministic ID 测试**

把 `src/converter/chunker.test.ts` 替换为：

```typescript
import { test } from 'node:test';
import assert from 'node:assert';
import { chunkDocument } from './chunker.js';

test('returns empty array for empty content', () => {
  const result = chunkDocument({
    fileId: 'f1',
    format: 'md',
    mdContent: '',
    lineMappings: []
  });
  assert.strictEqual(result.length, 0);
});

test('generates deterministic chunk IDs for same input', () => {
  const input = {
    fileId: 'f1',
    format: 'md' as const,
    mdContent: '# Title\n\nSome content.',
    lineMappings: []
  };
  const r1 = chunkDocument(input);
  const r2 = chunkDocument(input);
  assert.deepStrictEqual(r1.map(c => c.id), r2.map(c => c.id));
  assert.ok(r1.length > 0, 'should produce at least one chunk');
});

test('different fileId yields different chunk IDs', () => {
  const base = { format: 'md' as const, mdContent: '# A\n\nx', lineMappings: [] };
  const a = chunkDocument({ ...base, fileId: 'f1' });
  const b = chunkDocument({ ...base, fileId: 'f2' });
  assert.notStrictEqual(a[0].id, b[0].id);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test`
Expected: FAIL — `Cannot find module './chunker.js'`

- [ ] **Step 3: 创建 chunker.ts 骨架**

创建 `src/converter/chunker.ts`：

```typescript
/**
 * 文档切分模块
 * 按格式分派：md/docx、xlsx、pdf、pptx
 */

import { createHash } from 'crypto';
import { FileFormat, LineMapping, ChunkInsertInput } from '../types.js';

export interface ChunkInput {
  fileId: string;
  format: FileFormat;
  mdContent: string;
  lineMappings: LineMapping[];
}

interface RawChunk {
  content: string;
  startLine: number;
  endLine: number;
}

export function chunkDocument(input: ChunkInput): ChunkInsertInput[] {
  if (!input.mdContent || input.mdContent.trim() === '') {
    return [];
  }

  let rawChunks: RawChunk[];
  switch (input.format) {
    case 'md':
    case 'docx':
      rawChunks = chunkMarkdown(input.mdContent);
      break;
    case 'xlsx':
      rawChunks = chunkXlsx(input.mdContent);
      break;
    case 'pdf':
      rawChunks = chunkPdf(input.mdContent);
      break;
    case 'pptx':
      rawChunks = [{
        content: input.mdContent,
        startLine: 1,
        endLine: input.mdContent.split('\n').length
      }];
      break;
    default:
      rawChunks = [];
  }

  return rawChunks.map((rc, index) => ({
    id: chunkId(input.fileId, index, rc.content),
    file_id: input.fileId,
    content: rc.content,
    start_line: rc.startLine,
    end_line: rc.endLine,
    original_lines: mapToOriginalLines(rc.startLine, rc.endLine, input.lineMappings),
    vector: null
  }));
}

function chunkId(fileId: string, index: number, content: string): string {
  return createHash('sha256')
    .update(`${fileId}|${index}|${content.slice(0, 100)}`)
    .digest('hex')
    .slice(0, 16);
}

function mapToOriginalLines(
  startLine: number,
  endLine: number,
  lineMappings: LineMapping[]
): number[] {
  if (!lineMappings || lineMappings.length === 0) {
    return [startLine, endLine];
  }
  const set = new Set<number>();
  for (const m of lineMappings) {
    if (m.mdLine >= startLine && m.mdLine <= endLine) {
      set.add(m.originalLine);
    }
  }
  if (set.size === 0) return [startLine, endLine];
  return Array.from(set).sort((a, b) => a - b);
}

// 下面的函数在后续 task 实现
function chunkMarkdown(mdContent: string): RawChunk[] {
  // TASK 4 会实现
  return [{
    content: mdContent,
    startLine: 1,
    endLine: mdContent.split('\n').length
  }];
}

function chunkXlsx(mdContent: string): RawChunk[] {
  // TASK 5 会实现
  return [{
    content: mdContent,
    startLine: 1,
    endLine: mdContent.split('\n').length
  }];
}

function chunkPdf(mdContent: string): RawChunk[] {
  // TASK 6 会实现
  return [{
    content: mdContent,
    startLine: 1,
    endLine: mdContent.split('\n').length
  }];
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `npm test`
Expected: PASS — 3 个测试全通过

- [ ] **Step 5: Commit**

```bash
git add src/converter/chunker.ts src/converter/chunker.test.ts
git commit -m "feat(chunker): skeleton + deterministic chunkId + empty handling"
```

---

## Task 4: md/docx 切分策略（TDD）

**Files:**
- Modify: `src/converter/chunker.test.ts`（追加测试）
- Modify: `src/converter/chunker.ts`（实现 `chunkMarkdown`）

- [ ] **Step 1: 追加 md/docx 测试**

在 `src/converter/chunker.test.ts` 末尾追加：

```typescript
test('md: short section becomes single chunk with prepended heading', () => {
  const mdContent = '# Section A\n\nShort body.';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 1);
  assert.ok(result[0].content.startsWith('# Section A'));
  assert.ok(result[0].content.includes('Short body.'));
});

test('md: section >800 chars is split; each sub-chunk prepends heading', () => {
  const para = 'x'.repeat(400);
  const mdContent = `# Big\n\n${para}\n\n${para}\n\n${para}`;
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.ok(result.length >= 2, `expected >=2 chunks, got ${result.length}`);
  for (const c of result) {
    assert.ok(c.content.startsWith('# Big'), 'each chunk should prepend heading');
  }
});

test('md: content before first heading is its own chunk without prepend', () => {
  const mdContent = 'Intro text.\n\n# Later\n\nBody.';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  const intro = result.find(c => c.content.includes('Intro text.'));
  assert.ok(intro, 'intro chunk should exist');
  assert.ok(!intro!.content.startsWith('#'), 'intro chunk has empty section');
});

test('md: original_lines maps via lineMappings, not shifted by prepend', () => {
  const mdContent = '# Title\n\nBody line.';
  const lineMappings = [
    { mdLine: 1, originalLine: 100, content: '# Title', context: '' },
    { mdLine: 3, originalLine: 102, content: 'Body line.', context: '' }
  ];
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings
  });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].start_line, 1);
  assert.strictEqual(result[0].end_line, 3);
  assert.deepStrictEqual(result[0].original_lines, [100, 102]);
});

test('md: multiple sections produce multiple chunks', () => {
  const mdContent = '# A\n\nbody A\n\n# B\n\nbody B';
  const result = chunkDocument({
    fileId: 'f1', format: 'md', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2);
  assert.ok(result[0].content.includes('body A'));
  assert.ok(result[1].content.includes('body B'));
});
```

- [ ] **Step 2: 运行测试确认新测试失败**

Run: `npm test`
Expected: FAIL — 至少有测试不通过（骨架 `chunkMarkdown` 把整个文档当 1 个 chunk）

- [ ] **Step 3: 实现 chunkMarkdown**

把 `src/converter/chunker.ts` 里 `chunkMarkdown` 的整个函数体替换为：

```typescript
function chunkMarkdown(mdContent: string): RawChunk[] {
  const lines = mdContent.split('\n');
  const chunks: RawChunk[] = [];

  // Step 1: 按 heading 切成 sections
  interface Section {
    heading: string | null;  // null = 第一个 heading 之前的内容
    startLine: number;       // heading 行（1-indexed）
    endLine: number;         // 下一个 heading 行 - 1
    bodyLines: string[];     // 不含 heading 行本身
  }

  const sections: Section[] = [];
  let currentHeading: string | null = null;
  let currentStart = 1;
  let currentBody: string[] = [];

  const flushSection = (endLine: number) => {
    if (currentHeading === null && currentBody.every(l => l.trim() === '')) return;
    if (currentBody.length === 0 && currentHeading === null) return;
    sections.push({
      heading: currentHeading,
      startLine: currentStart,
      endLine,
      bodyLines: currentBody
    });
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^#{1,6}\s/.test(line)) {
      flushSection(i); // 到当前 heading 行的前一行（1-indexed: i）
      currentHeading = line;
      currentStart = i + 1;
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  flushSection(lines.length);

  // Step 2: 每个 section 生成 chunk
  const MAX_SINGLE = 800;
  const TARGET_MIN = 300;
  const TARGET_MAX = 600;

  for (const sec of sections) {
    const bodyText = sec.bodyLines.join('\n').trim();
    if (bodyText === '' && sec.heading === null) continue;

    const fullText = sec.heading
      ? (bodyText === '' ? sec.heading : `${sec.heading}\n\n${bodyText}`)
      : bodyText;

    // 若整 section ≤ 800 字符，整体作 1 个 chunk
    if (fullText.length <= MAX_SINGLE) {
      chunks.push({
        content: fullText,
        startLine: sec.startLine,
        endLine: sec.endLine
      });
      continue;
    }

    // >800：按空行切，贪婪累积到 TARGET_MAX
    const paragraphs = bodyText.split(/\n\s*\n/);
    let buf: string[] = [];
    let bufLen = 0;

    const flushBuf = () => {
      if (buf.length === 0) return;
      const body = buf.join('\n\n');
      const content = sec.heading ? `${sec.heading}\n\n${body}` : body;
      chunks.push({
        content,
        startLine: sec.startLine,
        endLine: sec.endLine
      });
      buf = [];
      bufLen = 0;
    };

    for (const p of paragraphs) {
      if (bufLen + p.length > TARGET_MAX && bufLen >= TARGET_MIN) {
        flushBuf();
      }
      buf.push(p);
      bufLen += p.length + 2; // +2 for \n\n
    }
    flushBuf();
  }

  return chunks;
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `npm test`
Expected: PASS — 所有已有测试 + 5 个新测试都通过

- [ ] **Step 5: Commit**

```bash
git add src/converter/chunker.ts src/converter/chunker.test.ts
git commit -m "feat(chunker): md/docx heading-aware strategy with section prepend"
```

---

## Task 5: xlsx 切分策略（TDD）

**Files:**
- Modify: `src/converter/chunker.test.ts`（追加测试）
- Modify: `src/converter/chunker.ts`（实现 `chunkXlsx`）

- [ ] **Step 1: 追加 xlsx 测试**

在 `src/converter/chunker.test.ts` 末尾追加：

```typescript
test('xlsx: groups 20 data rows per chunk, prepends sheet + header', () => {
  const rows = Array.from({ length: 25 }, (_, i) => `| v${i} | ${i} |`).join('\n');
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n${rows}\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2, `expected 2 chunks for 25 rows, got ${result.length}`);
  assert.ok(result[0].content.startsWith('## Sheet1'));
  assert.ok(result[0].content.includes('| 列 | 数据 |'));
  assert.strictEqual(
    (result[0].content.match(/\| v\d+ \|/g) || []).length,
    20,
    'first chunk should have 20 data rows'
  );
  assert.strictEqual(
    (result[1].content.match(/\| v\d+ \|/g) || []).length,
    5,
    'second chunk should have 5 data rows'
  );
});

test('xlsx: multiple sheets produce separate chunks', () => {
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n| a | 1 |\n\n## Sheet2\n\n| 列 | 数据 |\n|----|------|\n| b | 2 |\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2);
  assert.ok(result[0].content.startsWith('## Sheet1'));
  assert.ok(result[1].content.startsWith('## Sheet2'));
});

test('xlsx: prepended header does not count toward 20-row quota', () => {
  // 精确 20 行数据 → 应该只产出 1 个 chunk（不是 2 个）
  const rows = Array.from({ length: 20 }, (_, i) => `| v${i} | ${i} |`).join('\n');
  const mdContent = `## Sheet1\n\n| 列 | 数据 |\n|----|------|\n${rows}\n`;
  const result = chunkDocument({
    fileId: 'f1', format: 'xlsx', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 1);
});
```

- [ ] **Step 2: 运行测试确认新测试失败**

Run: `npm test`
Expected: FAIL — 骨架 `chunkXlsx` 产出单个 chunk，分组数不对

- [ ] **Step 3: 实现 chunkXlsx**

把 `src/converter/chunker.ts` 里 `chunkXlsx` 的整个函数体替换为：

```typescript
function chunkXlsx(mdContent: string): RawChunk[] {
  const ROWS_PER_CHUNK = 20;
  const lines = mdContent.split('\n');
  const chunks: RawChunk[] = [];

  interface SheetBlock {
    heading: string;       // 如 "## Sheet1"
    headerLines: string[]; // 通常 2 行: "| 列 | 数据 |" 和 "|----|------|"
    dataRows: { line: string; mdLine: number }[];
    startLine: number;     // heading 所在的 1-indexed 行
  }

  const sheets: SheetBlock[] = [];
  let current: SheetBlock | null = null;
  let state: 'heading-seek' | 'header-seek' | 'data' = 'heading-seek';
  let pendingHeaderLines: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;

    if (line.startsWith('## ')) {
      if (current) sheets.push(current);
      current = {
        heading: line,
        headerLines: [],
        dataRows: [],
        startLine: lineNum
      };
      state = 'header-seek';
      pendingHeaderLines = [];
      continue;
    }

    if (!current) continue;

    if (state === 'header-seek') {
      // 收集前两行非空的表格行作为表头
      if (line.trim().startsWith('|')) {
        pendingHeaderLines.push(line);
        if (pendingHeaderLines.length === 2) {
          current.headerLines = pendingHeaderLines;
          state = 'data';
        }
      }
      continue;
    }

    if (state === 'data') {
      if (line.trim().startsWith('|')) {
        current.dataRows.push({ line, mdLine: lineNum });
      }
      // 非表格行（如空行或 ---）忽略
    }
  }
  if (current) sheets.push(current);

  // 每个 sheet 按 20 行数据分组
  for (const sheet of sheets) {
    if (sheet.dataRows.length === 0) {
      chunks.push({
        content: [sheet.heading, '', ...sheet.headerLines].join('\n'),
        startLine: sheet.startLine,
        endLine: sheet.startLine + 1 + sheet.headerLines.length
      });
      continue;
    }
    for (let i = 0; i < sheet.dataRows.length; i += ROWS_PER_CHUNK) {
      const group = sheet.dataRows.slice(i, i + ROWS_PER_CHUNK);
      const content = [
        sheet.heading,
        '',
        ...sheet.headerLines,
        ...group.map(r => r.line)
      ].join('\n');
      chunks.push({
        content,
        startLine: group[0].mdLine,
        endLine: group[group.length - 1].mdLine
      });
    }
  }

  return chunks;
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `npm test`
Expected: PASS — 所有已有测试 + 3 个新测试都通过

- [ ] **Step 5: Commit**

```bash
git add src/converter/chunker.ts src/converter/chunker.test.ts
git commit -m "feat(chunker): xlsx 20-row grouping with sheet+header prepend"
```

---

## Task 6: pdf 切分策略（TDD）

**Files:**
- Modify: `src/converter/chunker.test.ts`（追加测试）
- Modify: `src/converter/chunker.ts`（实现 `chunkPdf`）

- [ ] **Step 1: 追加 pdf 测试**

在 `src/converter/chunker.test.ts` 末尾追加：

```typescript
test('pdf: each page becomes its own chunk when short', () => {
  const mdContent = '## 第 1 页\n\nPage one text.\n\n## 第 2 页\n\nPage two text.';
  const result = chunkDocument({
    fileId: 'f1', format: 'pdf', mdContent, lineMappings: []
  });
  assert.strictEqual(result.length, 2);
  assert.ok(result[0].content.includes('Page one'));
  assert.ok(result[0].content.startsWith('## 第 1 页'));
  assert.ok(result[1].content.includes('Page two'));
  assert.ok(result[1].content.startsWith('## 第 2 页'));
});

test('pdf: long page splits with sliding window and prepends page heading', () => {
  // 生成一个带换行的 2000 字符 page body
  const bodyChars: string[] = [];
  for (let i = 0; i < 2000; i++) {
    bodyChars.push(i > 0 && i % 80 === 0 ? '\n' : 'a');
  }
  const body = bodyChars.join('');
  const mdContent = `## 第 1 页\n\n${body}`;
  const result = chunkDocument({
    fileId: 'f1', format: 'pdf', mdContent, lineMappings: []
  });
  assert.ok(result.length >= 4, `expected >=4 chunks for 2000-char body, got ${result.length}`);
  for (const c of result) {
    assert.ok(c.content.startsWith('## 第 1 页'), 'each chunk prepends page heading');
  }
});
```

- [ ] **Step 2: 运行测试确认新测试失败**

Run: `npm test`
Expected: FAIL — 骨架把整个 mdContent 当 1 个 chunk

- [ ] **Step 3: 实现 chunkPdf**

把 `src/converter/chunker.ts` 里 `chunkPdf` 的整个函数体替换为：

```typescript
function chunkPdf(mdContent: string): RawChunk[] {
  const WINDOW = 400;
  const MIN_CUT = 300;
  const MAX_CUT = 500;

  const lines = mdContent.split('\n');
  const chunks: RawChunk[] = [];

  interface PageBlock {
    heading: string;
    body: string;
    startLine: number;
    endLine: number;
  }

  const pages: PageBlock[] = [];
  let current: PageBlock | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;
    if (/^## 第 \d+ 页/.test(line)) {
      if (current) {
        current.endLine = lineNum - 1;
        pages.push(current);
      }
      current = {
        heading: line,
        body: '',
        startLine: lineNum,
        endLine: lineNum
      };
    } else if (current) {
      current.body += (current.body ? '\n' : '') + line;
      current.endLine = lineNum;
    }
  }
  if (current) pages.push(current);

  for (const page of pages) {
    const body = page.body.trim();
    if (body === '') {
      chunks.push({
        content: page.heading,
        startLine: page.startLine,
        endLine: page.endLine
      });
      continue;
    }

    // 滑窗切分
    let offset = 0;
    while (offset < body.length) {
      const remaining = body.length - offset;
      let cut: number;

      if (remaining <= MAX_CUT) {
        cut = remaining;
      } else {
        // 在 [MIN_CUT, MAX_CUT] 窗口内找最近的 '\n'
        const searchStart = offset + MIN_CUT;
        const searchEnd = Math.min(offset + MAX_CUT, body.length);
        const lastNewline = body.lastIndexOf('\n', searchEnd);
        if (lastNewline >= searchStart) {
          cut = lastNewline - offset;
        } else {
          cut = WINDOW;
        }
      }

      const slice = body.slice(offset, offset + cut);
      chunks.push({
        content: `${page.heading}\n\n${slice}`,
        startLine: page.startLine,
        endLine: page.endLine
      });
      offset += cut;
      // 跳过切点上的 '\n' 防止下一 chunk 以 '\n' 开头
      while (offset < body.length && body[offset] === '\n') offset++;
    }
  }

  return chunks;
}
```

- [ ] **Step 4: 运行测试验证通过**

Run: `npm test`
Expected: PASS — 所有已有测试 + 2 个新测试都通过

- [ ] **Step 5: Commit**

```bash
git add src/converter/chunker.ts src/converter/chunker.test.ts
git commit -m "feat(chunker): pdf per-page sliding window with page heading prepend"
```

---

## Task 7: upload.ts 集成 — 三阶段状态机

**Files:**
- Modify: `src/routes/upload.ts`

- [ ] **Step 1: 在 upload.ts 顶部 import chunker**

在 [src/routes/upload.ts:10](../../../src/routes/upload.ts)（`DocumentConverter` 那行下方）追加：

```typescript
import { chunkDocument } from '../converter/chunker.js';
```

- [ ] **Step 2: 替换文件处理循环里的核心逻辑**

把 [src/routes/upload.ts:71-125](../../../src/routes/upload.ts) 的 `for (const file of files)` 循环体（从 `try {` 到 `catch (error: any) {` 之前）整段替换为：

```typescript
      try {
        const fileId = uuidv4();
        const format = converter.detectFormat(file.path);

        console.log(`📤 开始处理文件：${file.originalname}`);

        // 1. 转换文件
        const conversionResult = await converter.convert(file.path, file.originalname);

        // 2. 先写父表（status='converting'，防止出现 completed + chunks=0 灰态）
        const uploadTime = new Date().toISOString();
        db.insertFile({
          id: fileId,
          original_name: file.originalname,
          original_path: conversionResult.originalPath,
          converted_path: conversionResult.convertedPath,
          format,
          size: file.size,
          upload_time: uploadTime,
          category: category || '',
          status: 'converting',
          tags: tags ? (typeof tags === 'string' ? tags.split(',') : tags) : []
        });

        // 3. 切分并写子表
        try {
          const chunks = chunkDocument({
            fileId,
            format,
            mdContent: conversionResult.mdContent,
            lineMappings: conversionResult.lineMappings
          });
          db.insertChunks(chunks);
          console.log(`✅ 切分完成：${chunks.length} 个 chunk`);

          // 4. 切分成功后标记 completed
          db.updateFileStatus(fileId, 'completed');
        } catch (chunkErr: any) {
          db.updateFileStatus(fileId, 'failed');
          throw chunkErr;
        }

        uploadedFiles.push({
          id: fileId,
          originalName: file.originalname,
          originalPath: conversionResult.originalPath,
          convertedPath: conversionResult.convertedPath,
          format,
          size: file.size,
          uploadTime,
          status: 'completed' as FileStatus,
          category,
          tags
        });

        console.log(`✅ 文件处理完成：${file.originalname}`);

        // 删除临时文件
        fs.unlinkSync(file.path);

      } catch (error: any) {
        console.error(`❌ 文件处理失败：${file.originalname}`, error.message);

        // 记录失败文件
        uploadedFiles.push({
          id: uuidv4(),
          originalName: file.originalname,
          error: error.message,
          status: 'failed' as FileStatus
        });
      }
```

- [ ] **Step 3: 编译验证**

Run: `npm run build`
Expected: PASS — 无 TS 错误

- [ ] **Step 4: 集成验证（手动）**

清空旧数据并上传一个 md 文件：

```bash
rm -f storage/knowledge.db
rm -rf storage/original storage/converted storage/mappings
npm run dev &
SERVER_PID=$!
sleep 3

# 上传一份样本 md 文件
curl -s -F "files=@docs/layer1-design-v2.md" http://localhost:3002/api/upload | head -c 500
echo ""

# 检查统计
curl -s http://localhost:3002/api/qa/stats
echo ""

kill $SERVER_PID
```

Expected:
- upload 响应含 `"status":"completed"`
- stats 响应含 `"chunkCount": <大于 0 的数>` 和 `"fileCount": 1`

- [ ] **Step 5: Commit**

```bash
git add src/routes/upload.ts
git commit -m "feat(upload): integrate chunker with converting→completed/failed state machine"
```

---

## Task 8: 修 ISSUE-002 — `/api/qa/index` 空 chunks 守卫

**Files:**
- Modify: `src/routes/qa.ts:187-212`

- [ ] **Step 1: 改 /api/qa/index 加空 chunks 守卫**

把 [src/routes/qa.ts:187-212](../../../src/routes/qa.ts) 的整个 `router.post('/index', ...)` 块替换为：

```typescript
/**
 * POST /api/qa/index
 * 触发向量化索引
 */
router.post('/index', async (req: Request, res: Response) => {
  try {
    const db = new DatabaseManager();

    // 守卫：无可索引 chunks 时直接返回 warning，避免误报成功
    const stats = db.getStats();
    if (stats.chunkCount === 0) {
      db.close();
      return res.json({
        success: false,
        warning: '数据库中无可索引的 chunks，请先上传并切分文档'
      });
    }

    const retriever = new Retriever(db, {
      llmApiKey: process.env.LLM_API_KEY,
      llmBaseUrl: process.env.LLM_BASE_URL
    });

    console.log('📚 开始批量向量化...');
    await retriever.indexAllFiles();

    db.close();

    res.json({
      success: true,
      message: '向量化索引完成'
    });

  } catch (error: any) {
    console.error('❌ 向量化失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});
```

- [ ] **Step 2: 编译验证**

Run: `npm run build`
Expected: PASS

- [ ] **Step 3: 集成验证（手动）**

空库场景：

```bash
rm -f storage/knowledge.db
npm run dev &
SERVER_PID=$!
sleep 3

curl -s -X POST http://localhost:3002/api/qa/index
echo ""

kill $SERVER_PID
```

Expected: 返回 `{"success":false,"warning":"数据库中无可索引的 chunks，请先上传并切分文档"}`

- [ ] **Step 4: Commit**

```bash
git add src/routes/qa.ts
git commit -m "fix(qa): guard /api/qa/index against empty chunks (ISSUE-002)"
```

---

## Task 9: 最终验证 + 拿 eval 基线

**Files:** 无代码改动，只做端到端验证

- [ ] **Step 1: 清理存储，重启服务**

```bash
rm -f storage/knowledge.db
rm -rf storage/original storage/converted storage/mappings
npm run dev &
SERVER_PID=$!
sleep 3
```

- [ ] **Step 2: 上传 eval fixtures 里的样本文档**

```bash
for f in eval/fixtures/*.md; do
  curl -s -F "files=@${f}" http://localhost:3002/api/upload > /dev/null
done
curl -s http://localhost:3002/api/qa/stats
echo ""
```

Expected: `fileCount > 0` 且 `chunkCount > 0`。

- [ ] **Step 3: 触发向量化（如果配置了 LLM_API_KEY）**

```bash
curl -s -X POST http://localhost:3002/api/qa/index
echo ""
```

Expected: 配置了 key → `success: true`；未配置 → retriever 内部静默跳过，不报错（见 [retriever/index.ts:220-224](../../../src/retriever/index.ts)）。

- [ ] **Step 4: 跑 eval，记录基线**

```bash
cd eval
python run.py --limit 5 | tee ../docs/superpowers/plans/eval-baseline-2026-04-22.txt
cd ..
```

Expected: 非拒答题至少有 1 题**拿到非零分**（而不是全部回"无法回答"）。记录分数。

- [ ] **Step 5: 停服务**

```bash
kill $SERVER_PID
```

- [ ] **Step 6: 更新 ISSUES.md 标记 ISSUE-001 和 ISSUE-002 完成**

打开 `ISSUES.md`，在 ISSUE-001 和 ISSUE-002 的标题行前加 ✅，并在各自描述末尾追加一行：

```markdown
> **已于 2026-04-22 解决**，详见 `docs/superpowers/plans/2026-04-22-chunking-mvp.md` 和 eval 基线记录。
```

- [ ] **Step 7: 最终 commit**

```bash
git add ISSUES.md docs/superpowers/plans/eval-baseline-2026-04-22.txt
git commit -m "docs: close ISSUE-001/002 with chunking MVP + eval baseline"
```

---

## 完成标志

- [ ] `npm test` 全绿（不少于 13 个测试）
- [ ] `npm run build` 无 TS 错误
- [ ] 上传文件后 `/api/qa/stats` 返回 `chunkCount > 0`
- [ ] `/api/qa/index` 在空库时返回 warning 而非 success
- [ ] `eval/run.py --limit 5` 非拒答题至少 1 题拿到非零分
- [ ] ISSUES.md 标记 ISSUE-001 / ISSUE-002 完成
