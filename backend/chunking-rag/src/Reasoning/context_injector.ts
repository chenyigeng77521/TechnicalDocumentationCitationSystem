/**
 * 上下文注入器
 * 核心要求 1: 精准注入（转化）- 将检索到的"最小充分信息集合"封装并注入模型
 */

import {
  RetrievedChunk,
  ContextBlock,
  GovernanceConfig,
  DEFAULT_GOVERNANCE_CONFIG,
} from './types.js';

/**
 * 上下文注入器
 * 负责将检索到的 chunks 转化为模型可消费的上下文格式
 */
export class ContextInjector {
  private config: GovernanceConfig;

  constructor(config: Partial<GovernanceConfig> = {}) {
    this.config = { ...DEFAULT_GOVERNANCE_CONFIG, ...config };
  }

  /**
   * 将检索到的 chunks 注入为上下文块
   * @param chunks 检索到的文档块
   * @param maxTokens 最大 token 数限制
   * @returns 上下文块列表 + 是否截断
   */
  inject(
    chunks: RetrievedChunk[],
    maxTokens: number = this.config.maxContextTokens
  ): { blocks: ContextBlock[]; truncated: boolean; totalChars: number } {
    // 按 reranker 得分降序排列
    const sortedChunks = [...chunks].sort(
      (a, b) => (b.rerankerScore || 0) - (a.rerankerScore || 0)
    );

    // 去重：移除高度相似的 chunk
    const deduplicated = this.deduplicate(sortedChunks);

    // 截断：确保不超过最大 token 数
    const { blocks, totalChars, wasTruncated } = this.truncate(
      deduplicated,
      maxTokens
    );

    // 分配 ID
    const idAssignedBlocks = blocks.map((chunk, index) => ({
      id: index + 1,
      source: this.formatSource(chunk),
      content: chunk.content,
      isTruncated: chunk.isTruncated,
      anchorId: chunk.anchorId,
      titlePath: chunk.titlePath,
      rerankerScore: chunk.rerankerScore || 0,
    }));

    return {
      blocks: idAssignedBlocks,
      truncated: wasTruncated,
      totalChars,
    };
  }

  /**
   * 格式化为带来源的字符串
   */
  private formatSource(chunk: RetrievedChunk): string {
    const path = chunk.anchorId;
    const title = chunk.titlePath ? ` | ${chunk.titlePath}` : '';
    return `${path}${title}`;
  }

  /**
   * 去重：移除高度相似的 chunk
   */
  private deduplicate(chunks: RetrievedChunk[]): RetrievedChunk[] {
    const result: RetrievedChunk[] = [];
    
    for (const chunk of chunks) {
      const isDuplicate = result.some(existing => 
        this.cosineSimilarity(
          this.getTokenVector(chunk.content),
          this.getTokenVector(existing.content)
        ) >= this.config.deduplicationThreshold
      );

      if (!isDuplicate) {
        result.push(chunk);
      }
    }

    return result;
  }

  /**
   * 简单的 token 向量化（用于去重）
   */
  private getTokenVector(text: string): Map<string, number> {
    const tokens = text.toLowerCase()
      .split(/[\s,.!?;:()\[\]{}]+/)
      .filter(t => t.length > 2);
    
    const vector = new Map<string, number>();
    for (const token of tokens) {
      vector.set(token, (vector.get(token) || 0) + 1);
    }
    return vector;
  }

  /**
   * 计算余弦相似度
   */
  private cosineSimilarity(vec1: Map<string, number>, vec2: Map<string, number>): number {
    const keys = new Set([...vec1.keys(), ...vec2.keys()]);
    
    let dotProduct = 0;
    let norm1 = 0;
    let norm2 = 0;

    for (const key of keys) {
      const v1 = vec1.get(key) || 0;
      const v2 = vec2.get(key) || 0;
      dotProduct += v1 * v2;
      norm1 += v1 * v1;
      norm2 += v2 * v2;
    }

    if (norm1 === 0 || norm2 === 0) return 0;
    return dotProduct / (Math.sqrt(norm1) * Math.sqrt(norm2));
  }

  /**
   * 截断：确保不超过最大 token 数
   */
  private truncate(
    chunks: RetrievedChunk[],
    maxTokens: number
  ): { blocks: RetrievedChunk[]; totalChars: number; wasTruncated: boolean } {
    const result: RetrievedChunk[] = [];
    let totalChars = 0;
    const maxChars = maxTokens * 4; // 粗略估算：1 token ≈ 4 chars

    for (const chunk of chunks) {
      const newTotal = totalChars + chunk.charCount;
      
      if (newTotal > maxChars && result.length > 0) {
        // 标记最后一个 chunk 为截断
        const lastChunk = result[result.length - 1];
        lastChunk.isTruncated = true;
        return { blocks: result, totalChars, wasTruncated: true };
      }
      
      result.push(chunk);
      totalChars = newTotal;
    }

    return { blocks: result, totalChars, wasTruncated: false };
  }

  /**
   * 将上下文块转换为可读字符串格式
   * 用于注入 LLM prompt
   */
  formatForPrompt(blocks: ContextBlock[]): string {
    return blocks
      .map(block => {
        let formatted = `[ID: ${block.id}, Source: ${block.source}]\n`;
        formatted += block.content;
        if (block.isTruncated) {
          formatted += '\n[此段内容已截断，建议查阅原文]';
        }
        return formatted;
      })
      .join('\n\n---\n\n');
  }
}

/**
 * 创建默认上下文注入器
 */
export function createContextInjector(
  config?: Partial<GovernanceConfig>
): ContextInjector {
  return new ContextInjector(config);
}
