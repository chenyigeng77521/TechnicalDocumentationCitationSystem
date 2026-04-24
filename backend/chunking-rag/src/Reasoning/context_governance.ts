/**
 * 动态治理器
 * 核心要求 3: 动态治理（清理）- 实时剔除冗余或冲突信息
 */

import {
  RetrievedChunk,
  ContextBlock,
  GovernanceConfig,
  DEFAULT_GOVERNANCE_CONFIG,
} from './types.js';

/**
 * 治理结果
 */
export interface GovernanceResult {
  chunks: RetrievedChunk[];           // 治理后的 chunks
  removed: {
    duplicates: RetrievedChunk[];    // 被去重的
    conflicts: RetrievedChunk[];     // 冲突的
    lowScore: RetrievedChunk[];       // 低分的
  };
  stats: {
    originalCount: number;
    finalCount: number;
    removalRatio: number;
  };
}

/**
 * 上下文治理器
 * 负责动态清理和优化上下文
 */
export class ContextGovernor {
  private config: GovernanceConfig;
  private minScoreThreshold: number;

  constructor(
    config: Partial<GovernanceConfig> = {},
    minScoreThreshold: number = 0.1
  ) {
    this.config = { ...DEFAULT_GOVERNANCE_CONFIG, ...config };
    this.minScoreThreshold = minScoreThreshold;
  }

  /**
   * 治理检索结果
   * 1. 去重（移除高度相似的 chunk）
   * 2. 解决冲突（同主题的不同说法）
   * 3. 过滤低分
   */
  govern(chunks: RetrievedChunk[]): GovernanceResult {
    const originalCount = chunks.length;
    const removed = {
      duplicates: [] as RetrievedChunk[],
      conflicts: [] as RetrievedChunk[],
      lowScore: [] as RetrievedChunk[],
    };

    // 按得分降序
    let filtered = [...chunks].sort(
      (a, b) => (b.rerankerScore || 0) - (a.rerankerScore || 0)
    );

    // 1. 去重
    const deduplicated: RetrievedChunk[] = [];
    for (const chunk of filtered) {
      const isDuplicate = deduplicated.some(existing =>
        this.computeSimilarity(chunk, existing) >= this.config.deduplicationThreshold
      );

      if (isDuplicate) {
        removed.duplicates.push(chunk);
      } else {
        deduplicated.push(chunk);
      }
    }
    filtered = deduplicated;

    // 2. 冲突解决
    const resolved: RetrievedChunk[] = [];
    for (const chunk of filtered) {
      const conflict = this.findConflict(chunk, resolved);
      
      if (conflict) {
        // 根据策略解决冲突
        if (this.config.conflictResolution === 'keep_higher_score') {
          if ((chunk.rerankerScore || 0) > (conflict.rerankerScore || 0)) {
            removed.conflicts.push(conflict);
            resolved.push(chunk);
          } else {
            removed.conflicts.push(chunk);
          }
        } else {
          // keep_both 或 merge - 保留两者
          resolved.push(chunk);
        }
      } else {
        resolved.push(chunk);
      }
    }
    filtered = resolved;

    // 3. 过滤低分
    const final: RetrievedChunk[] = [];
    for (const chunk of filtered) {
      if ((chunk.rerankerScore || 0) >= this.minScoreThreshold) {
        final.push(chunk);
      } else {
        removed.lowScore.push(chunk);
      }
    }

    return {
      chunks: final,
      removed,
      stats: {
        originalCount,
        finalCount: final.length,
        removalRatio: (originalCount - final.length) / originalCount,
      },
    };
  }

  /**
   * 计算两个 chunk 的相似度
   */
  private computeSimilarity(a: RetrievedChunk, b: RetrievedChunk): number {
    // 使用简单的 token 重叠度
    const tokensA = this.tokenize(a.content);
    const tokensB = this.tokenize(b.content);

    const setA = new Set(tokensA);
    const setB = new Set(tokensB);

    let intersection = 0;
    for (const token of setA) {
      if (setB.has(token)) {
        intersection++;
      }
    }

    const union = setA.size + setB.size - intersection;
    return union === 0 ? 0 : intersection / union;
  }

  /**
   * 分词
   */
  private tokenize(text: string): string[] {
    return text
      .toLowerCase()
      .split(/[\s,.!?;:()\[\]{}]+/)
      .filter(t => t.length > 2);
  }

  /**
   * 查找冲突（同主题的不同说法）
   */
  private findConflict(
    chunk: RetrievedChunk,
    existing: RetrievedChunk[]
  ): RetrievedChunk | null {
    // 简化的冲突检测：相同文件 + 相邻位置 = 可能冲突
    for (const ex of existing) {
      if (ex.filePath === chunk.filePath) {
        const offsetDiff = Math.abs(
          ex.charOffsetStart - chunk.charOffsetStart
        );
        // 如果位置很近且内容相似度高，认为是冲突
        if (offsetDiff < 500 && this.computeSimilarity(ex, chunk) > 0.7) {
          return ex;
        }
      }
    }
    return null;
  }

  /**
   * 合并冲突信息（当策略为 merge 时）
   */
  mergeConflicts(chunks: RetrievedChunk[]): RetrievedChunk[] {
    const merged: RetrievedChunk[] = [];
    const processed = new Set<string>();

    for (const chunk of chunks) {
      const key = `${chunk.filePath}:${chunk.chunkIndex}`;
      
      if (processed.has(key)) continue;
      processed.add(key);

      // 查找可合并的冲突
      const mergeable = chunks.filter(c =>
        c !== chunk &&
        c.filePath === chunk.filePath &&
        Math.abs(c.charOffsetStart - chunk.charOffsetStart) < 200 &&
        !processed.has(`${c.filePath}:${c.chunkIndex}`)
      );

      if (mergeable.length > 0) {
        // 合并内容
        const allContent = [chunk, ...mergeable]
          .map(c => c.content)
          .join('\n\n');
        
        merged.push({
          ...chunk,
          content: allContent,
          charOffsetEnd: Math.max(...[chunk, ...mergeable].map(c => c.charOffsetEnd)),
        });

        mergeable.forEach(m => 
          processed.add(`${m.filePath}:${m.chunkIndex}`)
        );
      } else {
        merged.push(chunk);
      }
    }

    return merged;
  }

  /**
   * 更新配置
   */
  updateConfig(config: Partial<GovernanceConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * 设置最小分阈值
   */
  setMinScoreThreshold(threshold: number): void {
    this.minScoreThreshold = threshold;
  }
}

/**
 * 创建上下文治理器
 */
export function createContextGovernor(
  config?: Partial<GovernanceConfig>,
  minScoreThreshold?: number
): ContextGovernor {
  return new ContextGovernor(config, minScoreThreshold);
}
