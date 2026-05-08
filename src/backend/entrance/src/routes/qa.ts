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
 * 智能问答接口（非流式版本，普通 HTTP）
 * 调用链条：Question Filter → NLU → Category Classifier → Reasoning
 */
router.post('/ask-stream', async (req: Request, res: Response) => {
  const { question, session_id } = req.body;

  if (!question || typeof question !== 'string') {
    return res.status(400).json({
      success: false,
      message: '问题不能为空'
    });
  }

  console.log(`✅ [ask] 收到问题: ${question}, session_id: ${session_id || 'none'}`);

  try {
    const qid = crypto.randomUUID();

    // ① Question Filter
    console.log(`✅ [ask] 调用 Question Filter...`);
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`✅ [ask] 过滤结果: ${filterResult.category} (置信度: ${filterResult.confidence})`);

    if (!needsClassification(filterResult.category)) {
      const responseMsg = getFilterResponse(filterResult.category);
      console.log(`✅ [ask] 问题被过滤: ${filterResult.category}`);
      return res.json({
        success: true,
        question,
        filter: { category: filterResult.category, confidence: filterResult.confidence, description: filterResult.description },
        answer: responseMsg,
        sources: [],
        classification: null,
      });
    }

    // ② NLU 处理
    console.log(`✅ [ask] 进行 NLU 预处理...`);
    let processedQuestion = question;
    let nluUsed = '本地规则';

    try {
      const nluResp = await fetch(config.nlu.pipelineUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: session_id || null }),
        signal: AbortSignal.timeout(15000),
      });
      if (nluResp.ok) {
        const nluResult: any = await nluResp.json();
        if (nluResult.success && nluResult.processing_steps) {
          const steps = nluResult.processing_steps;
          processedQuestion = steps.resolved_question || question;
          nluUsed = 'NLU 管道服务';
        }
      }
    } catch (err: any) {
      console.log(`✅ [ask] NLU 服务调用失败: ${err.message}，切换到本地规则`);
    }

    if (nluUsed === '本地规则') {
      const pronounPattern = /它|它们|这个|那个|这些|那些|此|该|其|上述|前述|他|她|他们|她们/g;
      const hasPronoun = pronounPattern.test(question);
      if (hasPronoun && session_id && config.contextMemory.enabled) {
        try {
          const historyResp = await fetch(
            `${config.contextMemory.url}/api/context/get-latest-conversations/${session_id}?limit=5`,
            { signal: AbortSignal.timeout(config.contextMemory.timeout) }
          );
          if (historyResp.ok) {
            const historyData: any = await historyResp.json();
            if (historyData.success && historyData.conversations?.length > 0) {
              for (const conv of historyData.conversations.reverse()) {
                const userMsg = conv.user_message || '';
                const entities = userMsg.match(/[\u4e00-\u9fa5]{2,8}/g) || [];
                if (entities.length > 0) {
                  processedQuestion = question.replace(pronounPattern, entities[0]);
                  break;
                }
              }
            }
          }
        } catch {}
      }
    }

    console.log(`✅ [ask] NLU (${nluUsed}): "${question}" → "${processedQuestion}"`);

    // ③ Category Classifier
    console.log(`✅ [ask] 调用 Category Classifier...`);
    const classification: ClassificationResult = await classifyQuestion(processedQuestion);
    if (!classification.success || classification.error) {
      console.log(`✅ [ask] 分类失败: ${classification.error}`);
      return res.status(400).json({
        success: false,
        message: classification.error || '问题分类失败'
      });
    }
    console.log(`✅ [ask] 分类结果: ${classification.category}`);

    // ④ 调用推理层
    const reasoningUrl = 'http://localhost:8001/api/qa';
    console.log(`✅ [ask] 请求推理层: ${reasoningUrl}`);
    const response = await fetch(reasoningUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: qid, question: processedQuestion, category: classification.category }),
      signal: AbortSignal.timeout(600000),
    });

    if (!response.ok) throw new Error(`推理层返回 ${response.status}`);

    const result: any = await response.json();
    console.log(`✅ [ask] 推理层返回（8001原始数据）:`, JSON.stringify(result, null, 2));
    console.log(`✅ [ask] 推理层返回，answer长度: ${(result.answer || '').length}`);

    // 解析来源
    let answer = result.answer || '';
    let sources: string[] = [];
    if (result.citations && Array.isArray(result.citations) && result.citations.length > 0) {
      sources = result.citations.map((c: any) => {
        if (c.anchor) return `${c.doc_path}#${c.anchor}`;
        return c.doc_path || '';
      }).filter((s: string) => s);
    }
    if (result.is_refusal) sources = ['拒绝回答'];

    // ⑤ 记录 Context Memory
    if (session_id && config.contextMemory.enabled && !result.is_refusal && result.answer) {
      try {
        await fetch(`${config.contextMemory.url}/api/context/add-user-message`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: question }),
        });
        await fetch(`${config.contextMemory.url}/api/context/add-assistant-message`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: answer }),
        });
        console.log('✅ [ask] 上下文已记录');
      } catch (err) { console.error('✅ [ask] 记录上下文失败:', err); }
    }

    // ⑥ 一次性返回
    console.log(`✅ [ask] 返回完整结果`);
    return res.json({
      success: true,
      question,
      answer,
      sources,
      classification: {
        category: classification.category,
        confidence: classification.confidence,
        description: classification.description,
        searchStrategy: getSearchStrategy(classification.category),
      },
    });

  } catch (error: any) {
    console.error('✅ [ask] 问答失败:', error);
    return res.status(500).json({
      success: false,
      message: error.message || '问答失败'
    });
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
            // 跳过 batchtest 目录
            if (entry.name === 'batchtest') {
              continue;
            }
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
