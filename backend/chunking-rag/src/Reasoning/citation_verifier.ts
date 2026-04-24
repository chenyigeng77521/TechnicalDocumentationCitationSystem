/**
 * 引用验证器
 * 核心要求 2: 双重溯源（验证）- 同步 + 异步验证机制
 */

import {
  RetrievedChunk,
  ContextBlock,
  CitationSource,
  VerificationResult,
  ClaimedCitation,
  VerificationStatus,
} from './types.js';

/**
 * 同步验证结果
 */
export interface SyncVerificationResult {
  validCitations: number[];           // 有效的引用 ID
  invalidCitations: number[];         // 无效的引用 ID
  verifiedSources: CitationSource[];  // 验证通过的来源
}

/**
 * 引用验证器
 */
export class CitationVerifier {
  /**
   * 同步验证：检查引用的 ID 是否真实存在于 chunks 列表中
   * 这是阻塞响应链路的快速检查（< 10ms）
   */
  syncVerify(
    claimedIds: number[],
    contextBlocks: ContextBlock[]
  ): SyncVerificationResult {
    const validIds = new Set<number>();
    const invalidIds: number[] = [];
    const verifiedSources: CitationSource[] = [];

    for (const id of claimedIds) {
      const block = contextBlocks.find(b => b.id === id);
      
      if (block) {
        validIds.add(id);
        verifiedSources.push({
          id: block.id,
          anchorId: block.anchorId,
          titlePath: block.titlePath,
          score: block.rerankerScore,
          verificationStatus: 'pending', // 等待异步验证
          filePath: this.extractFilePath(block.anchorId),
          snippet: block.content.substring(0, 100),
        });
      } else {
        invalidIds.push(id);
      }
    }

    return {
      validCitations: Array.from(validIds),
      invalidCitations: invalidIds,
      verifiedSources,
    };
  }

  /**
   * 异步验证：Token 级匹配验证
   * 不阻塞响应链路，后台执行
   */
  async asyncVerify(
    answer: string,
    claimedCitations: ClaimedCitation[],
    chunks: RetrievedChunk[],
    onProgress?: (result: VerificationResult) => void
  ): Promise<VerificationResult[]> {
    const results: VerificationResult[] = [];

    for (const claimed of claimedCitations) {
      const chunk = chunks.find(c => {
        // 匹配：可以通过 chunkIndex + 1 或通过 anchorId
        const contextBlock = this.findContextBlock(claimed.citationId, chunks);
        return contextBlock && contextBlock.chunkId === c.chunkId;
      });

      const result = await this.verifyClaim(claimed, chunk);
      results.push(result);

      // 进度回调
      if (onProgress) {
        onProgress(result);
      }
    }

    return results;
  }

  /**
   * 验证单个声称的引用
   */
  private async verifyClaim(
    claimed: ClaimedCitation,
    chunk: RetrievedChunk | undefined
  ): Promise<VerificationResult> {
    if (!chunk) {
      return {
        citationId: claimed.citationId,
        keyTokens: claimed.keyTokens,
        matchedTokens: [],
        matchRatio: 0,
        status: 'failed',
      };
    }

    const rawText = chunk.rawText || chunk.content;
    const matchedTokens: string[] = [];
    
    // Token 级匹配
    for (const token of claimed.keyTokens) {
      if (rawText.includes(token)) {
        matchedTokens.push(token);
      }
    }

    const matchRatio = claimed.keyTokens.length > 0 
      ? matchedTokens.length / claimed.keyTokens.length 
      : 0;

    let status: VerificationStatus;
    if (matchRatio >= 0.8) {
      status = 'verified';
    } else if (matchRatio >= 0.5) {
      status = 'uncertain';
    } else if (matchRatio > 0) {
      status = 'uncertain';
    } else {
      status = 'failed';
    }

    return {
      citationId: claimed.citationId,
      keyTokens: claimed.keyTokens,
      matchedTokens,
      matchRatio,
      status,
    };
  }

  /**
   * 从 anchorId 提取文件路径
   */
  private extractFilePath(anchorId: string): string {
    const parts = anchorId.split('#');
    return parts[0] || anchorId;
  }

  /**
   * 查找上下文块
   */
  private findContextBlock(
    id: number,
    chunks: RetrievedChunk[]
  ): RetrievedChunk | undefined {
    // 通过 chunkIndex + 1 匹配 ID
    return chunks.find(c => {
      const contextId = c.chunkIndex + 1;
      return contextId === id;
    });
  }

  /**
   * 从回答中提取关键 token（名词、数字、版本号）
   */
  extractKeyTokens(text: string): string[] {
    const tokens: string[] = [];

    // 版本号：v1.0, 2.0.0, 2024, etc.
    const versionRegex = /\bv?\d+\.\d+(?:\.\d+)*\b/g;
    const versions = text.match(versionRegex);
    if (versions) {
      tokens.push(...versions);
    }

    // 数字 + 单位
    const numberWithUnit = /\d+\s*(MB|GB|KB|ms|s|min|小时|分钟|秒|天|年|版本|版)/g;
    const numbers = text.match(numberWithUnit);
    if (numbers) {
      tokens.push(...numbers);
    }

    // 专有名词（连续大写字母或驼峰）
    const properNouns = /\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b|\b[A-Z]{2,}\b/g;
    const nouns = text.match(properNouns);
    if (nouns) {
      tokens.push(...nouns);
    }

    // 关键配置项
    const configItems = /`[^`]+`/g;
    const configs = text.match(configItems);
    if (configs) {
      tokens.push(...configs.map(c => c.replace(/`/g, '')));
    }

    // 特定关键词
    const keywords = [
      'API', 'SDK', 'CLI', 'GUI', 'JSON', 'XML', 'YAML', 'HTTP',
      'REST', 'GraphQL', 'gRPC', 'OAuth', 'JWT', 'Token',
    ];
    for (const keyword of keywords) {
      if (text.includes(keyword)) {
        tokens.push(keyword);
      }
    }

    return [...new Set(tokens)];
  }

  /**
   * 验证引用 ID 是否有效
   */
  isValidCitationId(id: number, contextBlocks: ContextBlock[]): boolean {
    return contextBlocks.some(b => b.id === id);
  }

  /**
   * 清理回答中的无效引用
   * 将无效引用标记替换为注释
   */
  cleanAnswer(
    answer: string,
    validIds: number[],
    invalidIds: number[]
  ): string {
    let cleaned = answer;

    for (const id of invalidIds) {
      // 将 [id] 替换为灰色注释
      cleaned = cleaned.replace(
        new RegExp(`\\[${id}\\]`, 'g'),
        `[${id}❓]` // 标记为可疑引用
      );
    }

    return cleaned;
  }
}

/**
 * 创建引用验证器
 */
export function createCitationVerifier(): CitationVerifier {
  return new CitationVerifier();
}
