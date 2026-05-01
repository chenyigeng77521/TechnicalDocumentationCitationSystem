/**
 * 智能问答路由
 * 集成 Question Filter + category_classifier 问题分类系统
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

    console.log(`📥 1.收到问题：${question}`);

    // 1. 调用 Question Filter 进行问题过滤
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`🔍 4.过滤结果：${filterResult.category} (置信度：${filterResult.confidence})`);

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
    console.log(`🔄 9.问题有效，调用分类服务...`);
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
  const { question, session_id } = req.body;

  if (!question || typeof question !== 'string') {
    return res.status(400).json({
      success: false,
      message: '问题不能为空'
    });
  }

  console.log(`📥 1.收到问题（流式）: ${question}, session_id: ${session_id || 'none'}`);

  // 设置 SSE 响应头
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  try {
    // 1. 先进行语言检测（在调用 Question Filter 之前）
    // const chineseCount = (question.match(/[\u4e00-\u9fff]/g) || []).length;
    // const chineseRatio = chineseCount / question.length;

    // 取消中文访问限制，支持多语言提问
    // if (question.length > 0 && chineseRatio < 0.3) {
    //   // 中文比例低于 30%，认为是非中文问题
    //   console.log(`❌ 语言错误：中文比例 ${Math.round(chineseRatio * 100)}% < 30%`);
    //
    //   // 记录到 context memory（如果提供了 session_id）
    //   if (session_id && config.contextMemory.enabled) {
    //     try {
    //       await fetch(`${config.contextMemory.url}/api/context/add-user-message`, {
    //         method: 'POST',
    //         headers: { 'Content-Type': 'application/json' },
    //         body: JSON.stringify({ session_id, content: question })
    //       });
    //     } catch (err) {
    //       console.error('❌ 记录用户消息失败:', err);
    //     }
    //   }
    //
    //   res.write(`data: ${JSON.stringify({
    //     type: 'error',
    //     message: '请用中文提问，系统暂不支持其他语言'
    //   })}\n\n`);
    //   res.end();
    //   return;
    // }

    // 2. 发送开始事件
    res.write(`data: ${JSON.stringify({
      type: 'start',
      message: '正在处理您的问题...'
    })}\n\n`);

    // 3. 调用 Question Filter 进行问题过滤
    const filterResult: FilterResult = await filterQuestion(question);
    console.log(`🔍 4.过滤结果：${filterResult.category} (置信度：${filterResult.confidence})`);

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

      // 问题被过滤，不记录到上下文记忆层
      console.log('⏭️  问题被过滤，跳过上下文记录');

      res.end();
      return;
    }

    // 5. NLU 处理流水线（在分类之前）
    console.log(`🔄 5.问题有效，开始 NLU 处理...`);
    res.write(`data: ${JSON.stringify({
      type: 'processing',
      message: '正在进行 NLU 处理...'
    })}\n\n`);

    // Step 2.4.1: 指代判断
    let processedQuestion = question;
    let hasPronoun = false;
    let contextHistory: any[] = [];
    let pronounResolved = false;
    let queryRewritten = false;
    let completenessChecked = false;

    // 检测是否包含指代词
    const pronounPattern = /它 | 它们 | 这个 | 那 | 那个 | 这些 | 那些 | 此 | 该 | 其 | 上述 | 前述 | 上文 | 下面 | 他 | 她 | 他们 | 她们 | 自己 | 本人 | 该问题 | 该文档 | 该文件 | 这个功能 | 那个功能 | 此功能/;
    hasPronoun = pronounPattern.test(question);
    console.log(`🔍 6.NLU-指代判断：${hasPronoun ? '有指代词' : '无指代词'}`);

    if (hasPronoun && session_id && config.contextMemory.enabled) {
      // Step 2.4.2: 加载上下文记忆
      console.log(`📚 NLU-加载上下文：session_id=${session_id}`);
      try {
        const historyResp = await fetch(`${config.contextMemory.url}/api/context/get-latest-conversations/${session_id}`, {
          signal: AbortSignal.timeout(config.contextMemory.timeout)
        });
        if (historyResp.ok) {
          const historyData: any = await historyResp.json();
          if (historyData.success && historyData.conversations && historyData.conversations.length > 0) {
            contextHistory = historyData.conversations;
            console.log(`📚 NLU-上下文：找到 ${contextHistory.length} 条历史记录`);

            // Step 2.4.3: 指代替换（简单规则实现，实际应调用 RexUniNLU 模型）
            console.log(`🔧 NLU-指代替换：开始替换`);
            for (const conv of contextHistory.reverse()) {
              const userMsg = conv.user_message || '';
              // 提取实体（简单规则：提取中文词语）
              const entities = userMsg.match(/[\u4e00-\u9fff]{2,6}/g) || [];
              if (entities.length > 0) {
                const entity = entities[0];
                processedQuestion = processedQuestion.replace(pronounPattern, entity);
                pronounResolved = true;
                console.log(`✅ NLU-指代替换："${entity}"`);
                break;
              }
            }
          } else {
            console.log(`ℹ️ NLU-上下文：无历史记录，跳过指代替换`);
          }
        } else {
          console.log(`⚠️ NLU-上下文：获取失败，跳过指代替换`);
        }
      } catch (err: any) {
        console.log(`❌ NLU-上下文：${err.message}`);
      }
    } else {
      console.log(`ℹ️ NLU-指代判断：${!hasPronoun ? '无指代词' : '无 session_id 或 contextMemory 未启用'}`);
    }

    // Step 2.4.4: 查询改写（占位符，实际应调用 SlimPLM 模型）
    console.log(`✍️ NLU-查询改写：${processedQuestion === question ? '跳过' : '已改写'}`);
    queryRewritten = processedQuestion !== question;

    // Step 2.4.5: 完整性检查（占位符，实际应调用 TurnSense 模型）
    console.log(`✅ 7.NLU-完整性检查：通过`);
    completenessChecked = true;

    console.log(`🔄 8.NLU 处理完成：原始="${question}" → 处理后="${processedQuestion}"`);

    // 6. 问题分类（使用 NLU 处理后的问题）
    console.log(`🔄 9.调用分类服务...`);
    res.write(`data: ${JSON.stringify({
      type: 'processing',
      message: '正在进行问题分类...'
    })}\n\n`);

    const classification: ClassificationResult = await classifyQuestion(processedQuestion);

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
    // res.write(`data: ${JSON.stringify({
    //   type: 'classification',
    //   filterCategory: filterResult.category,
    //   category: classification.category,
    //   confidence: classification.confidence,
    //   description: classification.description,
    //   searchStrategy: getSearchStrategy(classification.category)
    // })}\n\n`);

    console.log(`📊 分类结果：${classification.category} (置信度：${classification.confidence})`);
    console.log(`🎯 检索策略：${getSearchStrategy(classification.category)}`);

    // 7. 调用检索层（如果配置了）
    let answer = '';
    let sources: any[] = [];
    let retrievalHasResults = false;  // 标记检索是否有结果

    if (config.retrieval.enabled) {
      console.log(`🔍 10.调用检索层：${config.retrieval.url}`);
      res.write(`data: ${JSON.stringify({
        type: 'processing',
        message: '正在检索知识库...'
      })}\n\n`);

      try {
        const retrievalResp = await fetch(config.retrieval.url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: question,
            top_k: 5,
            category: classification.category
          }),
          signal: AbortSignal.timeout(config.retrieval.timeout)
        });

        if (retrievalResp.ok) {
          const retrievalData: any = await retrievalResp.json();
          console.log(`✅ 检索结果：`, retrievalData);

          // 构建回答
          answer = `根据您的提问（${classification.category}类型），我为您找到以下相关知识：\n\n`;

          if (retrievalData.results && retrievalData.results.length > 0) {
            sources = retrievalData.results;
            retrievalData.results.forEach((item: any, idx: number) => {
              answer += `【${idx + 1}】${item.content || item.text || '文档内容'}\n`;
              answer += `来源：${item.source || item.document || '未知'}\n\n`;
            });
            retrievalHasResults = true;  // 检索有结果
            console.log(`📚 检索成功，找到 ${sources.length} 个相关文档`);
          } else {
            answer += '未找到相关文档，请您尝试其他提问方式。\n';
            retrievalHasResults = false;  // 检索成功但无结果，不记录
            console.log(`📚 检索成功但无结果`);
          }
        } else {
          console.log(`⚠️  检索层返回错误，使用默认回答`);
          //answer = `根据您的提问（${classification.category}类型），我将为您查找相关知识...\n\n（检索服务暂时不可用）`;
          answer = `检索服务暂时不可用`;
          retrievalHasResults = false;  // 检索失败，不记录
        }
      } catch (err: any) {
        console.log(`❌ 检索层调用失败：${err.message}`);
        //answer = `根据您的提问（${classification.category}类型），我将为您查找相关知识...\n\n（检索服务暂时不可用）`;
        answer = `检索服务暂时不可用`;
        retrievalHasResults = false;  // 检索失败，不记录
      }
    } else {
      console.log(`ℹ️  检索层未启用，使用默认回答`);
      //answer = `根据您的提问（${classification.category}类型），我将为您查找相关知识...\n\n（检索服务未配置）`;
      answer = `检索服务暂时不可用`;
      retrievalHasResults = false;  // 检索未启用，不记录
    }

    // 8. 流式返回回答
    const words = answer.split('');
    for (const word of words) {
      res.write(`data: ${JSON.stringify({
        type: 'answer',
        text: word
      })}\n\n`);
      await new Promise(resolve => setTimeout(resolve, 30));
    }

    // 9. 发送结束事件
    res.write(`data: ${JSON.stringify({
      type: 'end',
      filter: filterResult.category,
      classification: classification.category,
      sourcesCount: sources.length
    })}\n\n`);

    // 10. 记录到 context memory（如果提供了 session_id 且检索有结果）
    if (session_id && config.contextMemory.enabled && retrievalHasResults) {
      try {
        // 先记录用户问题
        await fetch(`${config.contextMemory.url}/api/context/add-user-message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: question })
        });
        console.log('✅ 用户问题已记录到 context memory');
        
        // 再记录助手回答
        await fetch(`${config.contextMemory.url}/api/context/add-assistant-message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id, content: answer })
        });
        console.log('✅ 助手回答已记录到 context memory');
      } catch (err) {
        console.error('❌ 记录上下文失败:', err);
      }
    } else if (session_id && config.contextMemory.enabled && !retrievalHasResults) {
      console.log('⏭️  检索无结果，跳过上下文记录');
    }

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
