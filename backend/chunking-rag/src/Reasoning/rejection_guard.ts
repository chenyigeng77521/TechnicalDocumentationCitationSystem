/**
 * 拒答守卫
 * 核心要求 4: 边界严控（拒答）- 严格限制推理范围
 */

import { RetrievedChunk, RERANKER_SCORE_THRESHOLD } from './types.js';

/**
 * 拒答原因
 */
export enum RejectionReason {
  NO_CHUNKS = 'no_chunks',                      // 无检索结果
  LOW_SCORE = 'low_score',                       // 检索得分过低
  EMPTY_QUERY = 'empty_query',                  // 空查询
  CONTEXT_EXCEEDS_LIMIT = 'context_exceeds_limit', // 上下文超限
}

/**
 * 拒答结果
 */
export interface RejectionResult {
  shouldReject: boolean;
  reason?: RejectionReason;
  message?: string;
  maxScore?: number;
  debugInfo?: {
    topScores: number[];
    threshold: number;
    chunkCount: number;
  };
}

/**
 * 拒答守卫
 * 在进入 LLM 推理之前进行多重检查
 */
export class RejectionGuard {
  private scoreThreshold: number;

  constructor(scoreThreshold: number = RERANKER_SCORE_THRESHOLD) {
    this.scoreThreshold = scoreThreshold;
  }

  /**
   * 检查是否应该拒答
   */
  evaluate(
    query: string,
    chunks: RetrievedChunk[]
  ): RejectionResult {
    // 1. 空查询检查
    if (!query || query.trim().length === 0) {
      return {
        shouldReject: true,
        reason: RejectionReason.EMPTY_QUERY,
        message: '查询内容为空',
        debugInfo: {
          topScores: [],
          threshold: this.scoreThreshold,
          chunkCount: 0,
        },
      };
    }

    // 2. 无检索结果检查
    if (!chunks || chunks.length === 0) {
      return {
        shouldReject: true,
        reason: RejectionReason.NO_CHUNKS,
        message: '未检索到相关文档',
        debugInfo: {
          topScores: [],
          threshold: this.scoreThreshold,
          chunkCount: 0,
        },
      };
    }

    // 3. 检索得分检查
    const scores = chunks.map(c => c.rerankerScore || 0);
    const maxScore = Math.max(...scores);

    if (maxScore < this.scoreThreshold) {
      return {
        shouldReject: true,
        reason: RejectionReason.LOW_SCORE,
        message: `检索得分（${maxScore.toFixed(2)}）低于系统阈值（${this.scoreThreshold}）`,
        maxScore,
        debugInfo: {
          topScores: scores.slice(0, 5),
          threshold: this.scoreThreshold,
          chunkCount: chunks.length,
        },
      };
    }

    // 4. 通过所有检查
    return {
      shouldReject: false,
      maxScore,
      debugInfo: {
        topScores: scores.slice(0, 5),
        threshold: this.scoreThreshold,
        chunkCount: chunks.length,
      },
    };
  }

  /**
   * 生成拒答消息
   */
  generateRejectionMessage(result: RejectionResult): string {
    switch (result.reason) {
      case RejectionReason.NO_CHUNKS:
        return '根据现有文档无法回答此问题。\n\n提示：未检索到相关文档，请尝试：\n1. 使用不同的关键词\n2. 确认文档中包含相关信息\n3. 上传更多相关文档';

      case RejectionReason.LOW_SCORE:
        return `根据现有文档无法回答此问题。\n\n提示：当前检索得分（${result.maxScore?.toFixed(2)}）低于系统阈值（${this.scoreThreshold}），无法确保回答准确性。\n建议：\n1. 尝试重新表述问题\n2. 使用更具体的关键词\n3. 确认文档中包含此信息`;

      case RejectionReason.EMPTY_QUERY:
        return '请输入有效的问题';

      case RejectionReason.CONTEXT_EXCEEDS_LIMIT:
        return '问题过于复杂，请简化后重试';

      default:
        return '根据现有文档无法回答此问题';
    }
  }

  /**
   * 获取调试信息（供评委验证检索质量）
   */
  getDebugInfo(result: RejectionResult): string {
    if (!result.debugInfo) return '';

    const { topScores, threshold, chunkCount } = result.debugInfo;
    
    let info = `\n\n--- 调试信息（供评委验证）---\n`;
    info += `最高检索得分: ${result.maxScore?.toFixed(2) || 'N/A'}\n`;
    info += `系统阈值: ${threshold}\n`;
    info += `检索到的文档块数: ${chunkCount}\n`;
    info += `Top 5 得分: [${topScores.map(s => s.toFixed(2)).join(', ')}]\n`;
    info += `--------------------------------`;

    return info;
  }

  /**
   * 设置得分阈值
   */
  setThreshold(threshold: number): void {
    this.scoreThreshold = threshold;
  }

  /**
   * 获取当前阈值
   */
  getThreshold(): number {
    return this.scoreThreshold;
  }
}

/**
 * 创建拒答守卫
 */
export function createRejectionGuard(
  scoreThreshold?: number
): RejectionGuard {
  return new RejectionGuard(scoreThreshold);
}
