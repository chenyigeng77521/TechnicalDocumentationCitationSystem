/**
 * 智能问答路由
 * 调用链条：Web 层 → Entrance → Reasoning Service (8001)
 */

import { Router, Request, Response } from 'express';
import * as fs from 'fs';
import * as path from 'path';
import crypto from 'crypto';
import { config } from '../config.js';
import {
  classifyQuestion,
  getQuestionTypes,
  getSearchStrategy,
  ClassificationResult
} from '../services/firstlayer-client.js';
import {
  filterQuestion,
  getFilterTypes,
  getFilterResponse,
  needsClassification,
  FilterResult,
  FilterCategory
} from '../services/question-filter-client.js';

const router = Router();

// 获取上传目录
function getUploadDir(): string {
  return path.resolve(config.upload.uploadDir);
}

/**
 * POST /api/qa/ask
 * 智能问答接口（同步版本）
 * 调用链条：Question Filter → Category Classifier
 */
router.post('/ask', async (req: Request, res: Response) => {
  try {
    const { question } = req.body;

    if (!question || typeof question !== 'string') {
      return res.status(400).json({
        success: false,
        message: '问题不能为空'
      });
    }

    console.log(`✅ 1.收到问题：${question}`);

    // 1. 调用 Question Filter 进行问题过滤
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`✅ 4.过滤结果：${filterResult.category} (置信度：${filterResult.confidence})`);

    // 2. 检查是否需要进一步分类
    if (!needsClassification(filterResult.category)) {
      // 不需要分类，直接返回过滤结果
      const responseMsg = getFilterResponse(filterResult.category);
      console.log(`⚠️  问题被过滤：${filterResult.category}`);

      return res.json({
        success: true,
        question,
        filter: {
          category: filterResult.category,
          confidence: filterResult.confidence,
          description: filterResult.description,
          reason: filterResult.reason
        },
        answer: responseMsg,
        sources: []
      });
    }

    // 3. 需要分类，调用 FirstLayer
    console.log(`✅ 9.问题有效，调用分类服务...`);
    const classification: ClassificationResult = await classifyQuestion(question);

    // 检查是否语言错误
    if (!classification.success || classification.error) {
      console.log(`✅ 语言错误：${classification.error}`);
      return res.status(400).json({
        success: false,
        message: classification.error || '请用中文提问，系统暂不支持其他语言'
      });
    }

    console.log(`✅ 分类结果：${classification.category} (置信度：${classification.confidence})`);
    console.log(`🎯 9.检索策略：${getSearchStrategy(classification.category)}`);

    // 4. 返回响应
    res.json({
      success: true,
      question,
      filter: {
        category: filterResult.category,
        confidence: filterResult.confidence,
        description: filterResult.description
      },
      classification: {
        category: classification.category,
        confidence: classification.confidence,
        description: classification.description
      },
      searchStrategy: getSearchStrategy(classification.category),
      // TODO: 添加实际回答
      answer: '这是一个测试响应。问题已通过过滤和分类，正在检索相关知识...',
      sources: []
    });

  } catch (error: any) {
    console.error('✅ 问答失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '问答失败'
    });
  }
});

/**
 * POST /api/qa/ask-stream
 * 智能问答接口（流式版本）
 * 调用链条：Question Filter → Category Classifier
 */
router.post('/ask-stream', async (req: Request, res: Response) => {
  const { question, session_id } = req.body;

  if (!question || typeof question !== 'string') {
    return res.status(400).json({
      success: false,
      message: '问题不能为空'
    });
  }

  console.log(`✅ 收到问题: ${question}, session_id: ${session_id || 'none'}`);

  // 设置 SSE 响应头
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  try {
    // 发送开始事件
    res.write(`data: ${JSON.stringify({
      type: 'start',
      message: '正在处理您的问题...'
    })}\n\n`);

    // 生成唯一 ID
    const qid = crypto.randomUUID();

    // ========== ① Question Filter 问题过滤 ==========
    console.log(`✅ 调用 Question Filter...`);
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`✅ 过滤结果: ${filterResult.category} (置信度: ${filterResult.confidence})`);

    // 如果不是有效问题，直接返回过滤提示
    if (!needsClassification(filterResult.category)) {
      const responseMsg = getFilterResponse(filterResult.category);
      console.log(`✅  问题被过滤: ${filterResult.category}`);
      console.log('✅  过滤问题，跳过上下文记录');

      res.write(`data: ${JSON.stringify({
        type: 'answer',
        answer: responseMsg || '抱歉，您的问题无法处理。',
        sources: []
      })}\n\n`);
      res.write(`data: ${JSON.stringify({
        type: 'end',
        filter: filterResult.category,
        sourcesCount: 0
      })}\n\n`);
      res.end();
      return;
    }

    // ========== ② NLU 处理（优先调用 NLU 管道服务，失败则使用本地规则） ==========
    res.write(`data: ${JSON.stringify({
      type: 'processing',
      message: '正在进行 NLU 预处理...'
    })}\n\n`);

    let processedQuestion = question;
    let pronounResolved = false;
    let queryRewritten = false;
    let completenessChecked = false;
    let nluUsed = '本地规则';  // 记录使用了什么 NLU 方案

    // 尝试调用 NLU 管道服务
    const nluUrl = config.nlu.pipelineUrl;
    console.log(`✅ NLU 尝试调用服务: ${nluUrl}`);
    try {
      const nluResp = await fetch(nluUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: session_id || null }),
        signal: AbortSignal.timeout(15000),
      });
      if (nluResp.ok) {
        const nluResult: any = await nluResp.json();
        if (nluResult.success && nluResult.processing_steps) {
          const steps = nluResult.processing_steps;
          pronounResolved = steps.pronoun_resolved || false;
          queryRewritten = steps.query_rewritten || false;
          completenessChecked = steps.completeness_check?.passed !== false;
          processedQuestion = steps.resolved_question || question;
          nluUsed = 'NLU 管道服务';
          console.log(`✅ NLU 服务返回: pronounResolved=${pronounResolved}, queryRewritten=${queryRewritten}, completeness=${completenessChecked}`);
        }
      }
    } catch (err: any) {
      console.log(`✅ NLU 服务调用失败: ${err.message}，切换到本地规则`);
    }

    // 如果 NLU 服务没有处理（未调用或失败），使用本地规则
    if (nluUsed === '本地规则') {
      // 指代词检测
      const pronounPattern = /它|它们|这个|那个|这些|那些|此|该|其|上述|前述|他|她|他们|她们/g;
      const hasPronoun = pronounPattern.test(question);
      console.log(`✅ 本地规则-指代检测: ${hasPronoun ? '有指代词' : '无指代词'}`);

      // 有指代词且 session 有效时，加载上下文做指代替换
      if (hasPronoun && session_id && config.contextMemory.enabled) {
        console.log(`✅ 本地规则-加载上下文: session_id=${session_id}`);
        try {
          const historyResp = await fetch(
            `${config.contextMemory.url}/api/context/get-latest-conversations/${session_id}?limit=5`,
            { signal: AbortSignal.timeout(config.contextMemory.timeout) }
          );
          if (historyResp.ok) {
            const historyData: any = await historyResp.json();
            if (historyData.success && historyData.conversations?.length > 0) {
              console.log(`✅ 本地规则-上下文: 找到 ${historyData.conversations.length} 条历史`);
              for (const conv of historyData.conversations.reverse()) {
                const userMsg = conv.user_message || '';
                const entities = userMsg.match(/[\u4e00-\u9fff]{2,8}/g) || [];
                if (entities.length > 0) {
                  processedQuestion = question.replace(pronounPattern, entities[0]);
                  pronounResolved = true;
                  console.log(`✅ 本地规则-指代替换: "${entities[0]}"`);
                  break;
                }
              }
            }
          }
        } catch (err: any) {
          console.log(`✅ 本地规则-上下文加载失败: ${err.message}`);
        }
      }
      queryRewritten = processedQuestion !== question;
      completenessChecked = true;  // 本地规则默认通过
    }

    console.log(`✅ NLU (${nluUsed}): "${question}" → "${processedQuestion}"`);

    // ========== ③ Category Classifier 问题分类（使用处理后的问题） ==========
    console.log(`✅ 调用 Category Classifier...`);
    res.write(`data: ${JSON.stringify({
      type: 'processing',
      message: '正在进行问题分类...'
    })}\n\n`);

    const classification: ClassificationResult = await classifyQuestion(processedQuestion);
    if (!classification.success || classification.error) {
      console.log(`✅ 分类失败: ${classification.error}`);
      res.write(`data: ${JSON.stringify({
        type: 'error',
        message: classification.error || '问题分类失败'
      })}\n\n`);
      res.end();
      return;
    }
    console.log(`✅ 分类结果: ${classification.category} (置信度: ${classification.confidence})`);

    // 发送分类事件
    res.write(`data: ${JSON.stringify({
      type: 'classification',
      category: classification.category,
      confidence: classification.confidence,
      description: classification.description,
      searchStrategy: getSearchStrategy(classification.category)
    })}\n\n`);

    // ========== ③ 调用推理层服务 ==========
    const reasoningUrl = 'http://172.25.178.31:8001/api/qa';
    console.log(`✅ [问答] 请求地址: ${reasoningUrl}`);
    console.log(`✅ [问答] 请求参数: ${JSON.stringify({ id: qid, question: question.substring(0, 50), category: classification.category })}`);

    res.write(`data: ${JSON.stringify({
      type: 'processing',
      message: '正在检索知识库...'
    })}\n\n`);

    const response = await fetch(reasoningUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: qid, question: processedQuestion, category: classification.category }),
      signal: AbortSignal.timeout(120000),
    });

    if (!response.ok) {
      throw new Error(`推理层返回 ${response.status}`);
    }

    const result: any = await response.json();
    console.log(`✅ [问答] 请求远程地址 http://172.25.178.31:8001/api/qa 返回结果: ${JSON.stringify(result)}`);

    // 解析引用来源
    let answer = result.answer || '';
    let sources: string[] = [];

    if (result.citations && Array.isArray(result.citations) && result.citations.length > 0) {
      sources = result.citations.map((c: any) => {
        if (c.anchor) {
          return `${c.doc_path}#${c.anchor}`;
        }
        return c.doc_path || '';
      }).filter((s: string) => s);
    }

    // 如果拒绝回答或失败，返回预设消息
    if (result.is_refusal || !answer) {
      answer = '抱歉，我无法从提供的文档中找到答案。';
    }

    // 发送完整答案事件（包含 sources）
    res.write(`data: ${JSON.stringify({
      type: 'answer',
      answer: answer,
      sources: sources
    })}\n\n`);

    // 发送来源事件
    if (sources.length > 0) {
      res.write(`data: ${JSON.stringify({
        type: 'sources',
        sources: sources
      })}\n\n`);
    }

    // ========== ④ 记录到 context memory（仅记录正常回答的问题和答案） ==========
    const shouldRecord = session_id && config.contextMemory.enabled && !result.is_refusal && result.answer;
    if (shouldRecord) {
      try {
        await fetch(`${config.contextMemory.url}/api/context/add-user-message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: question })
        });
        await fetch(`${config.contextMemory.url}/api/context/add-assistant-message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: answer })
        });
        console.log('✅ 上下文已记录');
      } catch (err) {
        console.error('✅ 记录上下文失败:', err);
      }
    } else {
      const skipReasons: string[] = [];
      if (!session_id) skipReasons.push('无session');
      else if (!config.contextMemory.enabled) skipReasons.push('contextMemory未启用');
      else if (result.is_refusal) skipReasons.push('is_refusal=true');
      else if (!result.answer) skipReasons.push('无有效答案');
      console.log(`✅  跳过上下文记录（${skipReasons.join(', ') || '未知'}）`);
    }

    // 发送结束事件
    res.write(`data: ${JSON.stringify({
      type: 'end',
      filter: filterResult.category,
      classification: classification.category,
      sourcesCount: sources.length
    })}\n\n`);

    res.end();

  } catch (error: any) {
    console.error('✅ 问答失败:', error);
    res.write(`data: ${JSON.stringify({
      type: 'error',
      message: error.message || '问答失败'
    })}\n\n`);
    res.end();
  }
});
/**
 * GET /api/qa/types
 * 获取问题分类类型列表
 */
router.get('/types', async (req: Request, res: Response) => {
  try {
    const types = await getQuestionTypes();

    res.json({
      success: true,
      types,
      enabled: config.firstlayer.enabled,
      serviceUrl: config.firstlayer.url
    });
  } catch (error: any) {
    console.error('✅ 获取分类类型失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * GET /api/qa/files
 * 获取已上传文件列表
 */
router.get('/files', (req: Request, res: Response) => {
  try {
    const uploadDir = getUploadDir();

    if (!fs.existsSync(uploadDir)) {
      return res.json({
        success: true,
        files: [],
        total: 0
      });
    }

    const files = fs.readdirSync(uploadDir).map(filename => {
      const filePath = path.join(uploadDir, filename);
      const stats = fs.statSync(filePath);

      let originalName = filename.replace(/^[a-f0-9-]{36}_/, '');
      const ext = path.extname(originalName).replace('.', '');

      return {
        id: filename,
        name: originalName,
        format: ext || 'unknown',
        size: stats.size,
        uploadTime: stats.birthtime.toISOString(),
        category: ''
      };
    });

    res.json({
      success: true,
      files,
      total: files.length
    });

  } catch (error: any) {
    console.error('✅ 获取文件列表失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * GET /api/qa/stats
 * 获取系统统计信息
 */
router.get('/stats', (req: Request, res: Response) => {
  try {
    const dataRoot = path.resolve(config.dataRoot.path);
    let fileCount = 0;
    let totalSize = 0;

    // 递归统计 data/ 目录下所有文件
    if (fs.existsSync(dataRoot)) {
      function walkAndCount(dir: string): void {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const fullPath = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            walkAndCount(fullPath);
          } else if (entry.isFile()) {
            fileCount++;
            totalSize += fs.statSync(fullPath).size;
          }
        }
      }
      walkAndCount(dataRoot);
    }

    res.json({
      success: true,
      totalFiles: fileCount,
      stats: {
        fileCount,
        totalSize,
        uploadDir: config.dataRoot.path
      },
      firstlayer: {
        enabled: config.firstlayer.enabled,
        url: config.firstlayer.url
      }
    });

  } catch (error: any) {
    console.error('✅ 获取统计信息失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * DELETE /api/qa/files/:filename
 * 删除指定文件
 */
router.delete('/files/:filename', (req: Request, res: Response) => {
  try {
    const { filename } = req.params;
    const uploadDir = getUploadDir();
    const filePath = path.join(uploadDir, filename);

    if (!fs.existsSync(filePath)) {
      return res.status(404).json({
        success: false,
        message: '文件不存在'
      });
    }

    fs.unlinkSync(filePath);

    res.json({
      success: true,
      message: '文件已删除'
    });

  } catch (error: any) {
    console.error('✅ 删除文件失败:', error);
    res.status(500).json({
      success: false,
      message: error.message
    });
  }
});

/**
 * POST /api/qa/batch-classify
 * 批量分类问题
 */
router.post('/batch-classify', async (req: Request, res: Response) => {
  try {
    const { questions } = req.body;

    if (!questions || !Array.isArray(questions)) {
      return res.status(400).json({
        success: false,
        message: '请提供问题数组'
      });
    }

    console.log(`✅ 收到批量分类请求：${questions.length} 个问题`);

    // 调用 FirstLayer 批量分类
    const results = await Promise.all(
      questions.map(async (question: string) => {
        try {
          const classification = await classifyQuestion(question);

          // 检查是否语言错误
          if (!classification.success || classification.error) {
            return {
              success: false,
              question,
              category: null,
              confidence: 0.0,
              description: null,
              error: classification.error || '请用中文提问，系统暂不支持其他语言'
            };
          }

          return {
            success: true,
            question,
            category: classification.category,
            confidence: classification.confidence,
            description: classification.description,
            error: null
          };
        } catch (error: any) {
          return {
            success: false,
            question,
            category: null,
            confidence: 0.0,
            description: null,
            error: error.message || '分类失败'
          };
        }
      })
    );

    res.json({
      success: true,
      total: results.length,
      results
    });

  } catch (error: any) {
    console.error('✅ 批量分类失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '批量分类失败'
    });
  }
});

export default router;
