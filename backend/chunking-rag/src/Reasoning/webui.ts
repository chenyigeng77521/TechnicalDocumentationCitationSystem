/**
 * 推理与引用层 - WebUI 接口
 * 为 WebUI 提供 REST API 和 WebSocket 接口
 */

import { Router, Request, Response } from 'express';
import { WebSocket, WebSocketServer } from 'ws';
import { Server } from 'http';
import {
  ReasoningPipeline,
  ReasoningPipelineConfig,
  createReasoningPipeline,
} from './reasoning_pipeline.js';
import {
  RetrievedChunk,
  ReasoningRequest,
  ReasoningResponse,
  CitationSource,
  VerificationResult,
  RERANKER_SCORE_THRESHOLD,
} from './types.js';
import { DatabaseManager } from '../database/index.js';

/**
 * WebUI 请求类型
 */
export interface AskRequest {
  question: string;
  topK?: number;
  strictMode?: boolean;
  enableAsyncVerification?: boolean;
}

/**
 * WebUI 响应类型
 */
export interface AskResponse {
  success: boolean;
  answer: string;
  citations: CitationSource[];
  noEvidence: boolean;
  maxScore: number;
  confidence: number;
  contextTruncated: boolean;
  rejectedReason?: string;
  query: string;
  debugInfo?: string;
}

/**
 * 推理与引用层 WebUI 服务
 */
export class ReasoningWebUI {
  private pipeline: ReasoningPipeline;
  private db: DatabaseManager | null = null;
  private wss: WebSocketServer | null = null;
  private clients: Map<string, WebSocket> = new Map();
  private clientIdCounter = 0;

  constructor(config: ReasoningPipelineConfig = {}) {
    this.pipeline = createReasoningPipeline(config);
  }

  /**
   * 设置数据库管理器
   */
  setDatabase(db: DatabaseManager): void {
    this.db = db;
  }

  /**
   * 设置 WebSocket 服务器
   */
  setWebSocketServer(server: Server): void {
    this.wss = new WebSocketServer({ server, path: '/ws/reasoning' });
    
    this.wss.on('connection', (ws: WebSocket) => {
      const clientId = `client_${++this.clientIdCounter}`;
      this.clients.set(clientId, ws);
      console.log(`🔌 WebSocket 客户端连接: ${clientId}`);

      ws.on('close', () => {
        this.clients.delete(clientId);
        console.log(`🔌 WebSocket 客户端断开: ${clientId}`);
      });

      ws.on('message', (message: string) => {
        try {
          const data = JSON.parse(message.toString());
          this.handleWebSocketMessage(clientId, ws, data);
        } catch (err) {
          console.error('❌ WebSocket 消息解析失败:', err);
        }
      });

      // 发送连接确认
      ws.send(JSON.stringify({ type: 'connected', clientId }));
    });
  }

  /**
   * 处理 WebSocket 消息
   */
  private async handleWebSocketMessage(
    clientId: string,
    ws: WebSocket,
    data: any
  ): Promise<void> {
    if (data.type === 'ask') {
      try {
        const response = await this.askInternal(data.question, data.options);
        
        ws.send(JSON.stringify({
          type: 'response',
          requestId: data.requestId,
          ...response,
        }));
      } catch (err: any) {
        ws.send(JSON.stringify({
          type: 'error',
          requestId: data.requestId,
          message: err.message,
        }));
      }
    }
  }

  /**
   * 创建 Express Router
   */
  createRouter(): Router {
    const router = Router();

    // POST /api/reasoning/ask - 问答接口
    router.post('/ask', async (req: Request, res: Response) => {
      try {
        const { question, topK, strictMode, enableAsyncVerification } = req.body as AskRequest;
        
        if (!question || question.trim().length === 0) {
          return res.status(400).json({
            success: false,
            error: '问题不能为空',
          });
        }

        const response = await this.askInternal(question, {
          topK,
          strictMode,
          enableAsyncVerification,
        });

        res.json({
          success: true,
          ...response,
        });
      } catch (err: any) {
        console.error('❌ 问答请求失败:', err);
        res.status(500).json({
          success: false,
          error: err.message || '内部错误',
        });
      }
    });

    // POST /api/reasoning/ask-stream - 流式问答接口（SSE）
    router.post('/ask-stream', async (req: Request, res: Response) => {
      try {
        const { question, topK, strictMode, enableAsyncVerification } = req.body as AskRequest;
        
        if (!question || question.trim().length === 0) {
          return res.status(400).json({
            success: false,
            error: '问题不能为空',
          });
        }

        // 设置 SSE 头
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('X-Accel-Buffering', 'no');

        // 获取 chunks
        const chunks = await this.retrieveChunks(question, topK || 5);
        
        // 构建请求
        const request: ReasoningRequest = {
          query: question,
          chunks,
          strictMode,
          enableAsyncVerification,
        };

        // 流式推理
        for await (const event of this.pipeline.streamReason(request)) {
          switch (event.type) {
            case 'token':
              res.write(`data: ${JSON.stringify({ answer: event.content })}\n\n`);
              res.flush();
              break;
            
            case 'citation':
              res.write(`data: ${JSON.stringify({ citation: event.citation })}\n\n`);
              res.flush();
              break;
            
            case 'verification':
              res.write(`data: ${JSON.stringify({ verification: event.result })}\n\n`);
              res.flush();
              break;
            
            case 'done':
              res.write(`data: ${JSON.stringify({ sources: event.response.citations })}\n\n`);
              break;
            
            case 'error':
              res.write(`data: ${JSON.stringify({ error: event.message })}\n\n`);
              break;
          }
        }

        res.write('data: [DONE]\n\n');
        res.end();
      } catch (err: any) {
        console.error('❌ 流式问答失败:', err);
        res.status(500).json({
          success: false,
          error: err.message || '内部错误',
        });
      }
    });

    // GET /api/reasoning/health - 健康检查
    router.get('/health', (_req: Request, res: Response) => {
      res.json({
        status: 'ok',
        service: 'reasoning-layer',
        version: '1.0.0',
      });
    });

    return router;
  }

  /**
   * 内部问答处理
   */
  private async askInternal(
    question: string,
    options: {
      topK?: number;
      strictMode?: boolean;
      enableAsyncVerification?: boolean;
    } = {}
  ): Promise<AskResponse> {
    // 1. 检索相关 chunks
    const chunks = await this.retrieveChunks(question, options.topK || 5);

    // 2. 执行推理
    const response = await this.pipeline.reason({
      query: question,
      chunks,
      strictMode: options.strictMode,
      enableAsyncVerification: options.enableAsyncVerification,
    });

    return {
      success: true,
      answer: response.answer,
      citations: response.citations,
      noEvidence: response.noEvidence,
      maxScore: response.maxScore,
      confidence: response.confidence,
      contextTruncated: response.contextTruncated,
      rejectedReason: response.rejectedReason,
      query: question,
    };
  }

  /**
   * 从数据库检索 chunks
   * 这里复用现有的检索逻辑
   */
  private async retrieveChunks(
    query: string,
    topK: number
  ): Promise<RetrievedChunk[]> {
    if (!this.db) {
      console.warn('⚠️ 数据库未配置，返回空 chunks');
      return [];
    }

    // 复用现有检索逻辑
    const searchResults = await this.search(query, topK);
    
    // 转换为 RetrievedChunk 格式
    return searchResults.map((result, index) => ({
      chunkId: `retrieved_${index}`,
      filePath: result.fileId,
      fileHash: '',
      content: result.content,
      anchorId: `${result.fileId}#${index * 1000}`,
      titlePath: result.citations[0]?.paragraph || null,
      charOffsetStart: index * 1000,
      charOffsetEnd: index * 1000 + result.content.length,
      charCount: result.content.length,
      isTruncated: false,
      chunkIndex: index,
      contentType: 'document' as const,
      rerankerScore: result.score,
      rawText: result.content,
    }));
  }

  /**
   * 搜索（复用现有 retriever）
   */
  private async search(query: string, topK: number): Promise<any[]> {
    if (!this.db) return [];

    try {
      // 简单关键词搜索
      const chunks = this.db.searchChunks(query);
      
      return chunks
        .slice(0, topK)
        .map(chunk => ({
          fileId: chunk.file_id,
          fileName: this.getFileName(chunk.file_id),
          content: chunk.content,
          score: 0.5, // 默认分数
          citations: [{
            documentPath: this.getFileName(chunk.file_id),
            paragraph: chunk.content.substring(0, 50),
            originalFile: this.getFileName(chunk.file_id),
            originalLines: [],
            mdLines: [chunk.start_line, chunk.end_line],
          }],
        }));
    } catch (err) {
      console.error('❌ 搜索失败:', err);
      return [];
    }
  }

  /**
   * 获取文件名
   */
  private getFileName(fileId: string): string {
    if (!this.db) return '未知文件';
    
    const file = this.db.getFile(fileId);
    return file?.original_name || '未知文件';
  }

  /**
   * 推送更新到 WebSocket 客户端
   */
  pushUpdate(clientId: string, data: any): void {
    const client = this.clients.get(clientId);
    if (client && client.readyState === WebSocket.OPEN) {
      client.send(JSON.stringify(data));
    }
  }

  /**
   * 广播消息到所有客户端
   */
  broadcast(type: string, data: any): void {
    const message = JSON.stringify({ type, ...data });
    for (const client of this.clients.values()) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(message);
      }
    }
  }

  /**
   * 更新 LLM 配置
   */
  updateLLMConfig(config: ReasoningPipelineConfig['llm']): void {
    this.pipeline.updateLLMConfig(config || {});
  }

  /**
   * 设置拒答阈值
   */
  setScoreThreshold(threshold: number): void {
    this.pipeline.setScoreThreshold(threshold);
  }
}

/**
 * 创建推理 WebUI 服务
 */
export function createReasoningWebUI(
  config?: ReasoningPipelineConfig
): ReasoningWebUI {
  return new ReasoningWebUI(config);
}
