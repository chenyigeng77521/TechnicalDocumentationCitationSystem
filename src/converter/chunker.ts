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
