import { Router, Request, Response } from 'express';
import { DatabaseManager } from '../database/index.js';
import { generateAnswer } from '../llm/index.js';

const router = Router();
const db = new DatabaseManager(process.env.DB_PATH || './storage/knowledge.db');

interface AskRequest {
  question: string;
  topK?: number;
  strictMode?: boolean;
}

router.post('/ask-stream', async (req: Request, res: Response) => {
  try {
    const { question, topK = 5 }: AskRequest = req.body;

    if (!question || typeof question !== 'string') {
      res.status(400).json({ error: '问题不能为空' });
      return;
    }

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    // 前端约定：data: {answer: string} 或 data: {sources: string[]}
    const sendData = (payload: any) => {
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
    };

    // 1. 检索
    const chunks = db.searchChunks(question).slice(0, topK);

    if (chunks.length === 0) {
      sendData({ answer: '抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。' });
      sendData({ sources: [] });
      res.end();
      return;
    }

    // 2. 构建 prompt
    const contextText = chunks.map((chunk, idx) =>
      `【文档 ${idx + 1}】${chunk.content.substring(0, 500)}`
    ).join('\n\n---\n\n');

    const prompt = `请根据以下【参考文档片段】回答问题。

【用户问题】
${question}

【参考文档片段】
${contextText}

【回答要求】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 如果文档中没有相关信息，请明确说明无法回答
3. 答案应直接、完整，避免额外无关解释

请开始回答：`;

    // 3. LLM 流式生成，每个 token 发一次 {answer}
    for await (const token of generateAnswer(prompt, question, chunks)) {
      sendData({ answer: token });
    }

    // 4. 发 sources（一次性）
    const sources = chunks.map(c => {
      const file = db.getFile(c.file_id);
      return file?.original_name || '未知文件';
    });
    sendData({ sources: Array.from(new Set(sources)) });  // 去重

    res.end();
  } catch (error: any) {
    console.error('❌ 流式问答失败:', error);
    try {
      res.write(`data: ${JSON.stringify({ answer: `\n\n（服务器错误：${error.message}）` })}\n\n`);
    } catch {
      // connection may have closed
    }
    res.end();
  }
});

export default router;
