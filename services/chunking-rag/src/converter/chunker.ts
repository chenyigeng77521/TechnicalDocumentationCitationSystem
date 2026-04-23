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
  const HARD_CAP = 2000;

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
      // 硬切超长段落，防止产生病态 chunk（spec §错误处理）
      if (p.length > HARD_CAP) {
        flushBuf();
        for (let off = 0; off < p.length; off += HARD_CAP) {
          const slice = p.slice(off, off + HARD_CAP);
          const content = sec.heading ? `${sec.heading}\n\n${slice}` : slice;
          chunks.push({
            content,
            startLine: sec.startLine,
            endLine: sec.endLine
          });
        }
        continue;
      }
      buf.push(p);
      bufLen += p.length + 2; // +2 for \n\n
    }
    flushBuf();
  }

  return chunks;
}

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
