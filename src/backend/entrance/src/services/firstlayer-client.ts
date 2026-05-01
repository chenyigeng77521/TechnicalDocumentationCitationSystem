/**
 * FirstLayer 问题分类服务客户端
 * 用于调用 firstlayer 服务进行问题分类
 */

import axios from 'axios';
import config from '../config.js';

// FirstLayer 分类类型
export type QuestionCategory = 'FACT' | 'PROC' | 'EXPL' | 'COMP' | 'META' | 'UNKNOWN';

// 分类结果
export interface ClassificationResult {
  success: boolean;
  question: string;
  category: QuestionCategory;
  confidence: number;
  description: string;
  error?: string;
}

// 分类请求
interface ClassifyRequest {
  question: string;
}

/**
 * 对问题进行分类
 * @param question 用户问题
 * @returns 分类结果
 */
export async function classifyQuestion(question: string): Promise<ClassificationResult> {
  // 如果未启用分类服务，直接返回未知类型
  if (!config.firstlayer.enabled) {
    console.log('⚠️  问题分类服务未启用，跳过分类');
    return {
      success: true,
      question,
      category: 'UNKNOWN',
      confidence: 0.5,
      description: '问题分类服务未启用'
    };
  }

  try {
    console.log(`🔄 正在对问题分类：${question.substring(0, 50)}...`);
    
    const response = await axios.post(
      `${config.firstlayer.url}/api/classify`,
      { question },
      {
        timeout: config.firstlayer.timeout,
        headers: {
          'Content-Type': 'application/json'
        }
      }
    );

    const result: ClassificationResult = response.data;
    
    console.log(`✅ 分类完成：${result.category} (置信度：${result.confidence})`);
    
    return result;

  } catch (error: any) {
    console.error(`❌ 问题分类失败:`, error.message);
    
    // 如果 firstlayer 服务不可用，返回未知类型但不报错
    return {
      success: true,
      question,
      category: 'UNKNOWN',
      confidence: 0.5,
      description: '无法连接到分类服务，使用默认处理'
    };
  }
}

/**
 * 获取问题分类类型列表
 * @returns 分类类型及其描述
 */
export async function getQuestionTypes(): Promise<Record<string, string>> {
  if (!config.firstlayer.enabled) {
    return {
      FACT: '事实型问题 - 询问具体事实、数据、定义等',
      PROC: '过程型问题 - 询问步骤、流程、操作方法等',
      EXPL: '解释型问题 - 询问原因、原理、机制等',
      COMP: '比较型问题 - 询问对比、差异、区别等',
      META: '元认知型问题 - 询问学习方法、思考过程等',
      UNKNOWN: '未知类型'
    };
  }

  try {
    const response = await axios.get(
      `${config.firstlayer.url}/api/classify/types`,
      { timeout: config.firstlayer.timeout }
    );
    
    return response.data.types || {};
  } catch (error: any) {
    console.error('❌ 获取分类类型失败:', error.message);
    
    // 返回默认分类
    return {
      FACT: '事实型问题 - 询问具体事实、数据、定义等',
      PROC: '过程型问题 - 询问步骤、流程、操作方法等',
      EXPL: '解释型问题 - 询问原因、原理、机制等',
      COMP: '比较型问题 - 询问对比、差异、区别等',
      META: '元认知型问题 - 询问学习方法、思考过程等',
      UNKNOWN: '未知类型'
    };
  }
}

/**
 * 根据分类类型获取检索策略
 * @param category 问题分类
 * @returns 检索策略描述
 */
export function getSearchStrategy(category: QuestionCategory): string {
  const strategies: Record<QuestionCategory, string> = {
    FACT: '精确匹配 - 查找具体事实、数据、定义',
    PROC: '流程匹配 - 查找操作步骤、流程文档',
    EXPL: '原理匹配 - 查找原因说明、原理机制',
    COMP: '对比匹配 - 查找对比分析、差异说明',
    META: '学习匹配 - 查找学习方法、技巧建议',
    UNKNOWN: '通用匹配 - 使用默认检索策略'
  };
  
  return strategies[category] || strategies.UNKNOWN;
}

/**
 * 检查分类类型
 * @param category 问题分类
 * @returns 是否有效分类
 */
export function isValidCategory(category: string): category is QuestionCategory {
  const validCategories: QuestionCategory[] = ['FACT', 'PROC', 'EXPL', 'COMP', 'META', 'UNKNOWN'];
  return validCategories.includes(category as QuestionCategory);
}
