/**
 * 推理与引用层路由
 * 集成 Layer 3: 上下文注入 → LLM 推理 → 引用验证 Pipeline
 */

import { Router, Request, Response } from 'express';
import { createReasoningWebUI, ReasoningWebUI } from '../Reasoning/index.js';
import { DatabaseManager } from '../database/index.js';
import { RetrievedChunk } from '../Reasoning/types.js';

const router = Router();

/**
 * 创建推理 WebUI 实例
 */
function createReasoningRouter(db: DatabaseManager): { router: Router; webUI: ReasoningWebUI } {
  const webUI = createReasoningWebUI({
    llm: {
      apiKey: process.env.LLM_API_KEY,
      baseUrl: process.env.LLM_BASE_URL,
      model: process.env.LLM_MODEL || 'gpt-4-turbo',
      temperature: 0.1,
      maxTokens: 2000,
    },
    scoreThreshold: parseFloat(process.env.SCORE_THRESHOLD || '0.4'),
    maxContextTokens: parseInt(process.env.MAX_CONTEXT_TOKENS || '6000', 10),
    enableAsyncVerification: process.env.ENABLE_ASYNC_VERIFICATION !== 'false',
    enableGovernance: process.env.ENABLE_GOVERNANCE !== 'false',
  });

  webUI.setDatabase(db);

  const reasoningRouter = webUI.createRouter();

  // 添加检索 chunks 的辅助方法
  (reasoningRouter as any).db = db;

  return { router: reasoningRouter, webUI };
}

/**
 * 获取检索 chunks 的辅助函数
 */
async function retrieveChunks(
  db: DatabaseManager,
  query: string,
  topK: number
): Promise<RetrievedChunk[]> {
  try {
    const chunks = db.searchChunks(query);

    return chunks
      .slice(0, topK)
      .map((chunk, index) => {
        const file = db.getFile(chunk.file_id);
        const fileName = file?.original_name || '未知文件';

        return {
          chunkId: chunk.id,
          filePath: chunk.file_id,
          fileHash: '',
          content: chunk.content,
          anchorId: `${fileName}#${chunk.start_line}`,
          titlePath: chunk.content.substring(0, 50),
          charOffsetStart: chunk.start_line * 100,
          charOffsetEnd: chunk.end_line * 100,
          charCount: chunk.content.length,
          isTruncated: false,
          chunkIndex: index,
          contentType: 'document' as const,
          rerankerScore: 0.5,
          rawText: chunk.content,
        };
      });
  } catch (err) {
    console.error('❌ 检索 chunks 失败:', err);
    return [];
  }
}

/**
 * 直接使用 Reasoning Pipeline 的端点
 * POST /api/reasoning/direct
 */
router.post('/direct', async (req: Request, res: Response) => {
  try {
    const { question, topK = 5 } = req.body;

    if (!question || question.trim().length === 0) {
      return res.status(400).json({
        success: false,
        error: '问题不能为空',
      });
    }

    const db = (router as any).db as DatabaseManager;
    const chunks = await retrieveChunks(db, question, topK);

    // 导入并使用 ReasoningPipeline
    const { createReasoningPipeline } = await import('../Reasoning/index.js');

    const pipeline = createReasoningPipeline({
      llm: {
        apiKey: process.env.LLM_API_KEY,
        baseUrl: process.env.LLM_BASE_URL,
        model: process.env.LLM_MODEL || 'gpt-4-turbo',
        temperature: 0.1,
        maxTokens: 2000,
      },
      scoreThreshold: parseFloat(process.env.SCORE_THRESHOLD || '0.4'),
    });

    const response = await pipeline.reason({
      query: question,
      chunks,
      strictMode: true,
      enableAsyncVerification: true,
    });

    res.json({
      success: true,
      answer: response.answer,
      citations: response.citations,
      noEvidence: response.noEvidence,
      maxScore: response.maxScore,
      confidence: response.confidence,
      contextTruncated: response.contextTruncated,
      rejectedReason: response.rejectedReason,
      query: question,
    });
  } catch (err: any) {
    console.error('❌ 直接推理失败:', err);
    res.status(500).json({
      success: false,
      error: err.message || '内部错误',
    });
  }
});

/**
 * 流式推理端点
 * POST /api/reasoning/stream
 */
router.post('/stream', async (req: Request, res: Response) => {
  try {
    const { question, topK = 5 } = req.body;

    if (!question || question.trim().length === 0) {
      return res.status(400).json({
        success: false,
        error: '问题不能为空',
      });
    }

    const db = (router as any).db as DatabaseManager;
    const chunks = await retrieveChunks(db, question, topK);

    // 设置 SSE 头
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    // 导入并使用 ReasoningPipeline
    const { createReasoningPipeline } = await import('../Reasoning/index.js');

    const pipeline = createReasoningPipeline({
      llm: {
        apiKey: process.env.LLM_API_KEY,
        baseUrl: process.env.LLM_BASE_URL,
        model: process.env.LLM_MODEL || 'gpt-4-turbo',
        temperature: 0.1,
        maxTokens: 2000,
      },
      scoreThreshold: parseFloat(process.env.SCORE_THRESHOLD || '0.4'),
    });

    for await (const event of pipeline.streamReason({
      query: question,
      chunks,
      strictMode: true,
      enableAsyncVerification: true,
    })) {
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
    console.error('❌ 流式推理失败:', err);
    res.status(500).json({
      success: false,
      error: err.message || '内部错误',
    });
  }
});

export { createReasoningRouter };
export default router;
