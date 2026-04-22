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

// SSE 流式问答接口
router.post('/ask-stream', async (req: Request, res: Response) => {
  try {
    const { question, topK = 5, strictMode = true }: AskRequest = req.body;

    if (!question || typeof question !== 'string') {
      res.status(400).json({ error: '问题不能为空' });
      return;
    }

    // 设置 SSE 响应头
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');

    // 发送 SSE 事件
    const sendEvent = (type: string, data: any) => {
      res.write(`data: ${JSON.stringify({ type, content: data })}\n\n`);
    };

    // 1. 开始检索
    sendEvent('searching', { message: '正在检索文档库...' });

    // 检索相关文档块（关键词检索）
    const query = question;
    const chunks = db.searchChunks(query).slice(0, topK);
    
    if (chunks.length === 0) {
      sendEvent('analyzing', { message: '未找到相关文档...' });
      sendEvent('answer', { 
        content: '抱歉，在文档库中未找到与您问题相关的内容。请尝试重新表述您的问题，或确保已上传相关文档。' 
      });
      sendEvent('complete', { success: true });
      res.end();
      return;
    }

    // 2. 分析内容
    sendEvent('analyzing', { 
      message: `找到 ${chunks.length} 个相关文档片段，正在分析...` 
    });

    // 3. 生成回答（流式）
    sendEvent('answer', { content: '' });

    // 构建提示词
    const contextText = chunks.map((chunk, idx) => 
      `【文档 ${idx + 1}】${chunk.content.substring(0, 200)}...`
    ).join('\n\n---\n\n');

    const prompt = `请根据以下【参考文档片段】回答问题。

【用户问题】
${question}

【参考文档片段】
${contextText}

【回答要求】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 每个判断或结论必须附上出处，格式为（文档路径：xxx，段落：xxx）
3. 如果文档中没有相关信息，请明确说明无法回答
4. 答案应直接、完整，避免额外无关解释

请开始回答：`;

    // 调用 LLM 流式生成
    let fullAnswer = '';

    for await (const chunk of generateAnswer(prompt, question, chunks)) {
      fullAnswer += chunk;
      sendEvent('answer', { content: chunk });
    }

    // 4. 发送引用信息
    const citationInfo = chunks.map(c => {
      const file = db.getFile(c.file_id);
      return {
        documentPath: file?.original_name || '未知文件',
        paragraph: `第 ${c.start_line}-${c.end_line} 行`,
        score: 0.8
      };
    });

    sendEvent('citations', citationInfo);
    sendEvent('complete', { success: true });

    res.end();
  } catch (error: any) {
    console.error('流式问答错误:', error);
    
    res.write(`data: ${JSON.stringify({ 
      type: 'error', 
      content: error.message || '问答失败' 
    })}\n\n`);
    
    res.end();
  }
});

export default router;
