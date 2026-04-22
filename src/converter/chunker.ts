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
