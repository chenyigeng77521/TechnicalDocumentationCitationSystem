/**
 * 推理管道
 * 核心：retrieval.py → 上下文注入 → LLM 推理 → 引用验证 Pipeline
 */

import { OpenAI } from 'openai';
import {
  RetrievedChunk,
  ReasoningRequest,
  ReasoningResponse,
  ReasoningStreamEvent,
  CitationSource,
  VerificationResult,
  ClaimedCitation,
  RERANKER_SCORE_THRESHOLD,
  DEFAULT_MAX_TOKENS,
} from './types.js';
import { ContextInjector, createContextInjector } from './context_injector.js';
import { PromptBuilder, createPromptBuilder } from './prompt_builder.js';
import { CitationVerifier, createCitationVerifier } from './citation_verifier.js';
import { RejectionGuard, createRejectionGuard, RejectionReason } from './rejection_guard.js';
import { ContextGovernor, createContextGovernor } from './context_governance.js';

/**
 * LLM 配置
 */
export interface LLMConfig {
  apiKey?: string;
  baseUrl?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
}

/**
 * 推理管道配置
 */
export interface ReasoningPipelineConfig {
  llm?: LLMConfig;
  scoreThreshold?: number;
  maxContextTokens?: number;
  enableAsyncVerification?: boolean;
  enableGovernance?: boolean;
}

/**
 * 推理管道
 * 编排整个推理流程
 */
export class ReasoningPipeline {
  private injector: ContextInjector;
  private promptBuilder: PromptBuilder;
  private verifier: CitationVerifier;
  private rejectionGuard: RejectionGuard;
  private governor: ContextGovernor;
  private openai: OpenAI | null = null;
  private llmConfig: LLMConfig;
  private enableAsyncVerification: boolean;
  private enableGovernance: boolean;

  constructor(config: ReasoningPipelineConfig = {}) {
    // 初始化各组件
    this.injector = createContextInjector({
      maxContextTokens: config.maxContextTokens || DEFAULT_MAX_TOKENS,
    });
    
    this.promptBuilder = createPromptBuilder();
    this.verifier = createCitationVerifier();
    this.rejectionGuard = createRejectionGuard(
      config.scoreThreshold || RERANKER_SCORE_THRESHOLD
    );
    this.governor = createContextGovernor();
    
    this.llmConfig = config.llm || {};
    this.enableAsyncVerification = config.enableAsyncVerification ?? true;
    this.enableGovernance = config.enableGovernance ?? true;

    // 初始化 LLM
    if (this.llmConfig.apiKey) {
      this.openai = new OpenAI({
        apiKey: this.llmConfig.apiKey,
        baseURL: this.llmConfig.baseUrl,
      });
    }
  }

  /**
   * 执行推理
   */
  async reason(request: ReasoningRequest): Promise<ReasoningResponse> {
    const { query, chunks, strictMode, enableAsyncVerification } = request;
    const useAsyncVerification = enableAsyncVerification ?? this.enableAsyncVerification;

    // ========== 阶段 1: 拒答守卫 ==========
    const rejectionResult = this.rejectionGuard.evaluate(query, chunks);
    
    if (rejectionResult.shouldReject) {
      return this.buildRejectionResponse(rejectionResult);
    }

    // ========== 阶段 2: 动态治理 ==========
    let processedChunks = chunks;
    if (this.enableGovernance) {
      const governanceResult = this.governor.govern(chunks);
      processedChunks = governanceResult.chunks;
      console.log(`📋 治理完成: ${governanceResult.stats.originalCount} → ${governanceResult.stats.finalCount} chunks`);
    }

    // ========== 阶段 3: 上下文注入 ==========
    const maxTokens = request.maxTokens || DEFAULT_MAX_TOKENS;
    const { blocks, truncated } = this.injector.inject(processedChunks, maxTokens);

    // ========== 阶段 4: LLM 推理 ==========
    let answer: string;
    
    if (this.openai) {
      const prompt = this.promptBuilder.buildStreamMessage(query, blocks, truncated);
      answer = await this.generateWithLLM(prompt);
    } else {
      // 无 LLM 模式：返回检索结果摘要
      answer = this.buildNoLLMResponse(blocks);
    }

    // ========== 阶段 5: 同步引用验证 ==========
    const claimedIds = this.promptBuilder.extractCitationIds(answer);
    const syncResult = this.verifier.syncVerify(claimedIds, blocks);
    
    // 清理回答中的无效引用
    if (syncResult.invalidCitations.length > 0) {
      answer = this.verifier.cleanAnswer(
        answer,
        syncResult.validCitations,
        syncResult.invalidCitations
      );
      console.log(`⚠️ 移除无效引用: [${syncResult.invalidCitations.join(', ')}]`);
    }

    // 构建来源列表
    const citations: CitationSource[] = syncResult.verifiedSources;

    // ========== 阶段 6: 异步引用验证（不阻塞响应）==========
    let verificationResults: VerificationResult[] = [];
    
    if (useAsyncVerification && syncResult.validCitations.length > 0) {
      // 后台执行异步验证
      this.runAsyncVerification(answer, citations, processedChunks);
    }

    // ========== 构建响应 ==========
    return {
      answer,
      citations,
      noEvidence: false,
      maxScore: rejectionResult.maxScore || 0,
      confidence: this.calculateConfidence(syncResult.validCitations.length, blocks.length),
      contextTruncated: truncated,
    };
  }

  /**
   * 流式推理
   */
  async *streamReason(
    request: ReasoningRequest
  ): AsyncGenerator<ReasoningStreamEvent, void, unknown> {
    const { query, chunks, enableAsyncVerification } = request;
    const useAsyncVerification = enableAsyncVerification ?? this.enableAsyncVerification;

    // ========== 阶段 1: 拒答守卫 ==========
    const rejectionResult = this.rejectionGuard.evaluate(query, chunks);
    
    if (rejectionResult.shouldReject) {
      const message = this.rejectionGuard.generateRejectionMessage(rejectionResult);
      yield { type: 'error', message };
      yield { 
        type: 'done', 
        response: this.buildRejectionResponse(rejectionResult) 
      };
      return;
    }

    // ========== 阶段 2: 动态治理 ==========
    let processedChunks = chunks;
    if (this.enableGovernance) {
      const governanceResult = this.governor.govern(chunks);
      processedChunks = governanceResult.chunks;
    }

    // ========== 阶段 3: 上下文注入 ==========
    const maxTokens = request.maxTokens || DEFAULT_MAX_TOKENS;
    const { blocks, truncated } = this.injector.inject(processedChunks, maxTokens);

    // ========== 阶段 4: 流式 LLM 推理 + 同步验证 ==========
    const citations: CitationSource[] = [];
    let fullAnswer = '';

    if (this.openai) {
      const prompt = this.promptBuilder.buildStreamMessage(query, blocks, truncated);
      
      for await (const token of this.streamGenerate(prompt)) {
        fullAnswer += token;
        yield { type: 'token', content: token };

        // 实时检查是否出现新引用
        const currentIds = this.promptBuilder.extractCitationIds(fullAnswer);
        for (const id of currentIds) {
          if (!citations.some(c => c.id === id)) {
            const block = blocks.find(b => b.id === id);
            if (block) {
              const citation: CitationSource = {
                id: block.id,
                anchorId: block.anchorId,
                titlePath: block.titlePath,
                score: block.rerankerScore,
                verificationStatus: 'pending',
                filePath: this.extractFilePath(block.anchorId),
                snippet: block.content.substring(0, 100),
              };
              citations.push(citation);
              yield { type: 'citation', citation };
            }
          }
        }
      }
    } else {
      // 无 LLM 模式
      fullAnswer = this.buildNoLLMResponse(blocks);
      yield { type: 'token', content: fullAnswer };
    }

    // ========== 阶段 5: 清理无效引用 ==========
    const claimedIds = this.promptBuilder.extractCitationIds(fullAnswer);
    const syncResult = this.verifier.syncVerify(claimedIds, blocks);
    
    if (syncResult.invalidCitations.length > 0) {
      fullAnswer = this.verifier.cleanAnswer(
        fullAnswer,
        syncResult.validCitations,
        syncResult.invalidCitations
      );
    }

    // ========== 阶段 6: 异步验证 ==========
    if (useAsyncVerification && citations.length > 0) {
      this.runAsyncVerification(fullAnswer, citations, processedChunks, (result) => {
        // 注意：这里无法 yield 到流中，因为 async generator 不能在后台任务中 yield
        // 验证结果会在后续通过 WebSocket 推送
      });
    }

    // ========== 完成 ==========
    yield {
      type: 'done',
      response: {
        answer: fullAnswer,
        citations,
        noEvidence: false,
        maxScore: rejectionResult.maxScore || 0,
        confidence: this.calculateConfidence(syncResult.validCitations.length, blocks.length),
        contextTruncated: truncated,
      },
    };
  }

  /**
   * 使用 LLM 生成回答
   */
  private async generateWithLLM(prompt: string): Promise<string> {
    if (!this.openai) {
      throw new Error('LLM 未配置');
    }

    const response = await this.openai.chat.completions.create({
      model: this.llmConfig.model || 'gpt-4-turbo',
      messages: [
        {
          role: 'system',
          content: '你是一个严格的技术文档问答助手。',
        },
        {
          role: 'user',
          content: prompt,
        },
      ],
      temperature: this.llmConfig.temperature || 0.1,
      max_tokens: this.llmConfig.maxTokens || 2000,
    });

    return response.choices[0].message.content || '';
  }

  /**
   * 流式生成
   */
  private async *streamGenerate(
    prompt: string
  ): AsyncGenerator<string, void, unknown> {
    if (!this.openai) {
      throw new Error('LLM 未配置');
    }

    const stream = await this.openai.chat.completions.create({
      model: this.llmConfig.model || 'gpt-4-turbo',
      messages: [
        {
          role: 'system',
          content: '你是一个严格的技术文档问答助手。',
        },
        {
          role: 'user',
          content: prompt,
        },
      ],
      temperature: this.llmConfig.temperature || 0.1,
      max_tokens: this.llmConfig.maxTokens || 2000,
      stream: true,
    });

    for await (const chunk of stream) {
      const content = chunk.choices[0]?.delta?.content || '';
      if (content) {
        yield content;
      }
    }
  }

  /**
   * 后台执行异步验证
   */
  private runAsyncVerification(
    answer: string,
    citations: CitationSource[],
    chunks: RetrievedChunk[],
    onProgress?: (result: VerificationResult) => void
  ): void {
    // 提取引用声明
    const claimedCitations = this.extractClaimedCitations(answer, citations);
    
    // 后台执行验证
    this.verifier.asyncVerify(answer, claimedCitations, chunks, onProgress)
      .then(results => {
        console.log(`✅ 异步验证完成: ${results.length} 个引用`);
        
        // 更新 citations 的验证状态（通过 WebSocket 推送）
        for (const result of results) {
          const citation = citations.find(c => c.id === result.citationId);
          if (citation) {
            citation.verificationStatus = result.status;
          }
        }
      })
      .catch(err => {
        console.error('❌ 异步验证失败:', err);
      });
  }

  /**
   * 提取引用声明
   */
  private extractClaimedCitations(
    answer: string,
    citations: CitationSource[]
  ): ClaimedCitation[] {
    const claimed: ClaimedCitation[] = [];
    const usedIds = new Set<number>();

    // 提取所有 [n] 引用
    const regex = /\[(\d+)\]/g;
    let match;

    while ((match = regex.exec(answer)) !== null) {
      const id = parseInt(match[1], 10);
      
      if (!usedIds.has(id) && citations.some(c => c.id === id)) {
        usedIds.add(id);
        
        // 提取引用前后的关键内容
        const beforeMatch = answer.substring(Math.max(0, match.index - 50), match.index);
        const afterMatch = answer.substring(match.index + match[0].length, match.index + match[0].length + 50);
        const claimText = beforeMatch + match[0] + afterMatch;
        
        claimed.push({
          citationId: id,
          claimText,
          keyTokens: this.verifier.extractKeyTokens(claimText),
        });
      }
    }

    return claimed;
  }

  /**
   * 构建拒答响应
   */
  private buildRejectionResponse(result: { reason?: RejectionReason; maxScore?: number }): ReasoningResponse {
    const message = this.rejectionGuard.generateRejectionMessage(result as any);
    const debugInfo = this.rejectionGuard.getDebugInfo(result as any);

    return {
      answer: message + debugInfo,
      citations: [],
      noEvidence: true,
      maxScore: result.maxScore || 0,
      confidence: 0,
      contextTruncated: false,
      rejectedReason: result.reason,
    };
  }

  /**
   * 构建无 LLM 响应
   */
  private buildNoLLMResponse(blocks: { content: string; source: string }[]): string {
    if (blocks.length === 0) {
      return '未检索到相关文档。';
    }

    const summaries = blocks.map((block, idx) => {
      return `[${idx + 1}] ${block.content.substring(0, 200)}${block.content.length > 200 ? '...' : ''}`;
    }).join('\n\n');

    return `根据检索结果，以下是相关信息：\n\n${summaries}\n\n（请配置 LLM API 以启用智能问答功能）`;
  }

  /**
   * 计算置信度
   */
  private calculateConfidence(validCount: number, totalCount: number): number {
    if (totalCount === 0) return 0;
    
    const coverage = validCount / totalCount;
    const baseScore = Math.min(coverage * 1.5, 1);
    
    return Math.round(baseScore * 100) / 100;
  }

  /**
   * 从 anchorId 提取文件路径
   */
  private extractFilePath(anchorId: string): string {
    const parts = anchorId.split('#');
    return parts[0] || anchorId;
  }

  /**
   * 更新 LLM 配置
   */
  updateLLMConfig(config: Partial<LLMConfig>): void {
    this.llmConfig = { ...this.llmConfig, ...config };
    
    if (config.apiKey) {
      this.openai = new OpenAI({
        apiKey: config.apiKey,
        baseURL: config.baseUrl,
      });
    }
  }

  /**
   * 设置拒答阈值
   */
  setScoreThreshold(threshold: number): void {
    this.rejectionGuard.setThreshold(threshold);
  }
}

/**
 * 创建推理管道
 */
export function createReasoningPipeline(
  config?: ReasoningPipelineConfig
): ReasoningPipeline {
  return new ReasoningPipeline(config);
}
