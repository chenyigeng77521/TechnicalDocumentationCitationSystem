/**
 * 智能问答路由
 * 集成 Question Filter + FirstLayer 问题分类系统
 * 调用链条：Web 层 → Question Filter (3005) → Category Classifier (3004)
 */

import { Router, Request, Response } from 'express';
import * as fs from 'fs';
import * as path from 'path';
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

    console.log(`📥 收到问题：${question}`);

    // 1. 调用 Question Filter 进行问题过滤
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`🔍 过滤结果：${filterResult.category} (置信度：${filterResult.confidence})`);

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
    console.log(`🔄 问题有效，调用分类服务...`);
    const classification: ClassificationResult = await classifyQuestion(question);

    // 检查是否语言错误
    if (!classification.success || classification.error) {
      console.log(`❌ 语言错误：${classification.error}`);
      return res.status(400).json({
        success: false,
        message: classification.error || '请用中文提问，系统暂不支持其他语言'
      });
    }

    console.log(`📊 分类结果：${classification.category} (置信度：${classification.confidence})`);
    console.log(`🎯 检索策略：${getSearchStrategy(classification.category)}`);

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
    console.error('❌ 问答失败:', error);
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
  const { question } = req.body;

  if (!question || typeof question !== 'string') {
    return res.status(400).json({
      success: false,
      message: '问题不能为空'
    });
  }

  console.log(`📥 收到问题（流式）: ${question}`);

  // 设置 SSE 响应头
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  try {
    // 1. 先进行语言检测（在调用 Question Filter 之前）
    const chineseCount = (question.match(/[\u4e00-\u9fff]/g) || []).length;
    const chineseRatio = chineseCount / question.length;
    
    if (question.length > 0 && chineseRatio < 0.3) {
      // 中文比例低于 30%，认为是非中文问题
      console.log(`❌ 语言错误：中文比例 ${Math.round(chineseRatio * 100)}% < 30%`);
      res.write(`data: ${JSON.stringify({ 
        type: 'error',
        message: '请用中文提问，系统暂不支持其他语言'
      })}\n\n`);
      res.end();
      return;
    }

    // 2. 发送开始事件
    res.write(`data: ${JSON.stringify({ 
      type: 'start',
      message: '正在处理您的问题...' 
    })}\n\n`);

    // 3. 调用 Question Filter 进行问题过滤
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`🔍 过滤结果：${filterResult.category} (置信度：${filterResult.confidence})`);

    // 4. 检查是否需要进一步分类
    if (!needsClassification(filterResult.category)) {
      // 不需要分类，直接返回过滤结果
      const responseMsg = getFilterResponse(filterResult.category);
      console.log(`⚠️  问题被过滤：${filterResult.category}`);
      
      res.write(`data: ${JSON.stringify({ 
        type: 'filter',
        category: filterResult.category,
        confidence: filterResult.confidence,
        description: filterResult.description,
        reason: filterResult.reason,
        message: responseMsg
      })}\n\n`);
      
      res.write(`data: ${JSON.stringify({ 
        type: 'answer',
        text: responseMsg || ''
      })}\n\n`);
      
      res.write(`data: ${JSON.stringify({ 
        type: 'end',
        filter: filterResult.category
      })}\n\n`);
      
      res.end();
      return;
    }

    // 5. 需要分类，调用 FirstLayer
    console.log(`🔄 问题有效，调用分类服务...`);
    res.write(`data: ${JSON.stringify({ 
      type: 'processing',
      message: '问题已通过过滤，正在进行分类...' 
    })}\n\n`);

    const classification: ClassificationResult = await classifyQuestion(question);

    // 检查是否语言错误（备用检查）
    if (!classification.success || classification.error) {
      console.log(`❌ 语言错误：${classification.error}`);
      res.write(`data: ${JSON.stringify({ 
        type: 'error',
        message: classification.error || '请用中文提问，系统暂不支持其他语言'
      })}\n\n`);
      res.end();
      return;
    }

    // 6. 发送分类结果
    res.write(`data: ${JSON.stringify({ 
      type: 'classification',
      filterCategory: filterResult.category,
      category: classification.category,
      confidence: classification.confidence,
      description: classification.description,
      searchStrategy: getSearchStrategy(classification.category)
    })}\n\n`);

    // 7. 模拟流式回答（TODO: 替换为真实的 LLM 回答）
    const answer = `根据您的提问（${classification.category}类型），我将为您查找相关知识...\n\n`;
    const words = answer.split('');
    
    for (const word of words) {
      res.write(`data: ${JSON.stringify({ 
        type: 'answer',
        text: word
      })}\n\n`);
      // 模拟打字机效果
      await new Promise(resolve => setTimeout(resolve, 30));
    }

    // 8. 发送结束事件
    res.write(`data: ${JSON.stringify({ 
      type: 'end',
      filter: filterResult.category,
      classification: classification.category
    })}\n\n`);

    res.end();

  } catch (error: any) {
    console.error('❌ 流式问答失败:', error);
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
    console.error('❌ 获取分类类型失败:', error);
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
    console.error('❌ 获取文件列表失败:', error);
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
    const uploadDir = getUploadDir();
    let fileCount = 0;
    let totalSize = 0;
    
    if (fs.existsSync(uploadDir)) {
      const files = fs.readdirSync(uploadDir);
      fileCount = files.length;
      
      for (const file of files) {
        const filePath = path.join(uploadDir, file);
        const stats = fs.statSync(filePath);
        totalSize += stats.size;
      }
    }

    res.json({
      success: true,
      totalFiles: fileCount,
      stats: {
        fileCount,
        totalSize,
        uploadDir: config.upload.uploadDir
      },
      firstlayer: {
        enabled: config.firstlayer.enabled,
        url: config.firstlayer.url
      }
    });

  } catch (error: any) {
    console.error('❌ 获取统计信息失败:', error);
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
    console.error('❌ 删除文件失败:', error);
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

    console.log(`📥 收到批量分类请求：${questions.length} 个问题`);

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
    console.error('❌ 批量分类失败:', error);
    res.status(500).json({
      success: false,
      message: error.message || '批量分类失败'
    });
  }
});

export default router;
