/**
 * 推理与引用层类型定义
 * Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline
 */

import { SearchResult, Citation } from '../types.js';

/**
 * 检索到的文档块（带完整元数据）
 */
export interface RetrievedChunk {
  chunkId: string;                    // 唯一标识：sha256(file_path + chunk_index + content[:100])
  filePath: string;                  // 文件路径
  fileHash: string;                  // 文件哈希
  content: string;                   // 块内容
  anchorId: string;                  // 锚点 ID：file_path#char_offset_start
  titlePath: string | null;          // 可读标题路径：Authentication > OAuth2 > Token Refresh
  charOffsetStart: number;           // 字符偏移开始
  charOffsetEnd: number;             // 字符偏移结束
  charCount: number;                 // 字符数
  isTruncated: boolean;              // 是否被截断
  chunkIndex: number;                // 块索引
  contentType: 'document' | 'code' | 'structured_data';
  language?: string;                // 编程语言（代码类）
  embedding?: number[];             // 向量
  rerankerScore?: number;            // Reranker 打分
  rawText?: string;                  // 原始文本（用于验证）
}

/**
 * 上下文块（注入格式）
 * 每个 Chunk 包装为带 ID 和来源信息的格式
 */
export interface ContextBlock {
  id: number;                        // 从 1 开始的序号
  source: string;                    // Source: file_path | title_path
  content: string;                   // 块内容
  isTruncated: boolean;              // 是否截断
  anchorId: string;                  // 锚点 ID
  titlePath: string | null;          // 可读标题路径
  rerankerScore: number;             // 检索得分
}

/**
 * 引用来源（用于前端展示）
 */
export interface CitationSource {
  id: number;                        // 引用 ID（与 ContextBlock.id 对应）
  anchorId: string;                  // 锚点 ID
  titlePath: string | null;          // 可读标题路径
  score: number;                     // 检索得分
  verificationStatus: VerificationStatus;  // 验证状态
  filePath: string;                  // 文件路径
  snippet: string;                   // 内容摘要（前 100 字符）
}

/**
 * 引用验证状态
 */
export type VerificationStatus = 
  | 'pending'    // 待验证
  | 'verified'    // 已验证通过
  | 'uncertain'   // 验证不确定
  | 'failed';    // 验证失败

/**
 * 验证结果
 */
export interface VerificationResult {
  citationId: number;
  keyTokens: string[];               // 关键 token（名词、数字、版本号）
  matchedTokens: string[];           // 匹配到的 token
  matchRatio: number;                 // 匹配率
  status: VerificationStatus;
}

/**
 * 声称的引用（从 LLM 回答中提取）
 */
export interface ClaimedCitation {
  citationId: number;                // 引用的 [n] ID
  claimText: string;                 // 声称的内容
  keyTokens: string[];               // 关键 token
}

/**
 * 推理请求
 */
export interface ReasoningRequest {
  query: string;                     // 用户问题
  chunks: RetrievedChunk[];          // 检索到的 chunks
  maxTokens?: number;                // 最大 token 数
  strictMode?: boolean;              // 严格模式（必须引用）
  enableAsyncVerification?: boolean; // 启用异步验证
}

/**
 * 推理响应
 */
export interface ReasoningResponse {
  answer: string;                    // 回答内容
  citations: CitationSource[];       // 引用的来源列表
  noEvidence: boolean;               // 是否无证据拒答
  maxScore: number;                  // 最高检索得分
  confidence: number;                // 置信度
  contextTruncated: boolean;         // 上下文是否被截断
  rejectedReason?: string;           // 拒答原因（如果有）
  verificationResults?: VerificationResult[]; // 验证结果（同步）
}

/**
 * 流式推理事件
 */
export type ReasoningStreamEvent = 
  | { type: 'token'; content: string }
  | { type: 'citation'; citation: CitationSource }
  | { type: 'verification'; result: VerificationResult }
  | { type: 'done'; response: ReasoningResponse }
  | { type: 'error'; message: string };

/**
 * 上下文治理配置
 */
export interface GovernanceConfig {
  maxContextTokens: number;          // 最大上下文 token 数
  conflictResolution: 'keep_both' | 'keep_higher_score' | 'merge';
  deduplicationThreshold: number;   // 去重阈值（余弦相似度）
}

/**
 * 默认配置
 */
export const DEFAULT_GOVERNANCE_CONFIG: GovernanceConfig = {
  maxContextTokens: 6000,
  conflictResolution: 'keep_higher_score',
  deduplicationThreshold: 0.95,
};

/**
 * Reranker 得分阈值
 * 低于此阈值直接拒答
 */
export const RERANKER_SCORE_THRESHOLD = 0.4;

/**
 * 最大上下文 token 数
 */
export const DEFAULT_MAX_TOKENS = 6000;
