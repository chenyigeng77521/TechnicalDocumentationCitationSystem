/**
 * 文件上传相关类型
 */
export interface FileUploadRequest {
  files: Express.Multer.File[];
  metadata: {
    title?: string;
    category?: string;
    tags?: string[];
  };
}

export interface FileUploadResponse {
  success: boolean;
  files: FileInfo[];
  message?: string;
}

export interface FileInfo {
  id: string;
  originalName: string;
  originalPath: string;
  convertedPath: string;
  format: FileFormat;
  size: number;
  uploadTime: string;
  status: FileStatus;
  category?: string;
  tags?: string[];
}

export type FileFormat = 'docx' | 'xlsx' | 'pptx' | 'pdf' | 'md';
export type FileStatus = 'pending' | 'converting' | 'completed' | 'failed';

/**
 * 文档转换相关类型
 */
export interface ConversionResult {
  mdContent: string;
  lineMappings: LineMapping[];
  convertedPath: string;
  originalFile: string;
  originalPath: string;
}

export interface LineMapping {
  mdLine: number;
  originalLine: number;
  content: string;
  context: string;
}

/**
 * 文档索引相关类型
 */
export interface DocumentIndex {
  fileId: string;
  originalFile: string;
  mdPath: string;
  chunks: Chunk[];
  vectorIndex: VectorIndex;
}

export interface Chunk {
  id: string;
  content: string;
  startLine: number;
  endLine: number;
  originalLines: number[];
  vector: number[];
  metadata: {
    fileId: string;
    fileName: string;
    section?: string;
  };
}

export interface VectorIndex {
  id: string;
  vectors: number[][];
  metadata: any[];
}

/**
 * 检索相关类型
 */
export interface SearchRequest {
  query: string;
  topK: number;
  filters?: {
    fileId?: string;
    category?: string;
    dateRange?: { start: string; end: string };
  };
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
}

export interface SearchResult {
  fileId: string;
  fileName: string;
  content: string;
  score: number;
  citations: Citation[];
}

export interface Citation {
  documentPath: string;
  paragraph: string;
  originalFile: string;
  originalLines: number[];
  mdLines: number[];
}

/**
 * 问答相关类型
 */
export interface QARequest {
  question: string;
  topK?: number;
  strictMode?: boolean;
}

export interface QAResponse {
  answer: string;
  citations: Citation[];
  confidence: number;
  noEvidence: boolean;
  query: string;
}

/**
 * 数据库表结构
 */
export interface FileRecord {
  id: string;
  original_name: string;
  original_path: string;
  converted_path: string;
  format: string;
  size: number;
  upload_time: string;
  category: string;
  status: string;
  tags?: string;
}

export interface ChunkRecord {
  id: string;
  file_id: string;
  content: string;
  start_line: number;
  end_line: number;
  original_lines: string;  // JSON 字符串
  vector: string;          // JSON 字符串
}

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
