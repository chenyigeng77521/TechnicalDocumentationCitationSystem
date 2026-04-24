/**
 * 提示词构建器
 * 核心要求 4: 边界严控（拒答）- 构建严格的提示词，确保模型只基于上下文回答
 */

import { ContextBlock } from './types.js';

/**
 * 系统提示词模板
 */
const SYSTEM_PROMPT = `你是一个严格的技术文档问答助手。

【核心规则】
1. 仅根据下方提供的 Context 回答，严禁使用任何外部知识或猜测。
2. 每个事实性陈述句末必须标注来源，格式为 [n]（n 为对应 Chunk 的 ID）。
3. 如果 Context 中不包含回答所需信息，直接回复："根据现有文档无法回答此问题。"
4. 如果 Context 标注了"内容已截断"，可说明信息不足并建议查阅原文。
5. 不得合并多个 Chunk 的内容进行推断，每条引用必须有直接支撑。
6. 保持回答简洁准确，不要添加冗余解释。

【引用规则】
- 每个句子的引用必须是直接的、一一对应的
- 避免泛泛而谈，每个观点都需要具体引用支撑
- 数字、版本号、配置项等关键信息必须标注来源`;

/**
 * 用户提示词模板
 */
const USER_PROMPT_TEMPLATE = `【Context】
{context}

---

【问题】
{query}

---

【回答要求】
请严格基于 Context 回答，每个事实陈述后标注引用。`;

/**
 * 拒答提示词（当检索得分过低时）
 */
const REJECTION_PROMPT = `根据现有文档无法回答此问题。

提示：当前检索得分（{maxScore:.2f}）低于系统阈值，无法确保回答准确性。
建议：
1. 尝试重新表述问题
2. 上传更多相关文档
3. 确认文档中确实包含此信息`;

/**
 * 无 LLM 模式提示词
 */
const NO_LLM_PROMPT = `【问题】
{query}

【检索到的相关文档】
{context}

---
根据上述检索结果，以下是相关信息汇总：

{summary}`;

/**
 * 提示词构建器
 */
export class PromptBuilder {
  private systemPrompt: string;

  constructor(systemPrompt?: string) {
    this.systemPrompt = systemPrompt || SYSTEM_PROMPT;
  }

  /**
   * 构建完整的推理提示词
   */
  build(
    query: string,
    contextBlocks: ContextBlock[],
    contextTruncated: boolean = false
  ): { system: string; user: string } {
    const context = this.formatContext(contextBlocks);
    
    let extendedSystemPrompt = this.systemPrompt;
    
    // 如果上下文被截断，添加警告
    if (contextTruncated) {
      extendedSystemPrompt += '\n\n⚠️ 警告：以下 Context 因长度限制被截断，可能不包含完整信息。';
    }

    const userPrompt = USER_PROMPT_TEMPLATE
      .replace('{context}', context)
      .replace('{query}', query);

    return {
      system: extendedSystemPrompt,
      user: userPrompt,
    };
  }

  /**
   * 构建拒答提示词
   */
  buildRejection(maxScore: number): { system: string; user: string } {
    return {
      system: this.systemPrompt,
      user: REJECTION_PROMPT.replace('{maxScore}', maxScore.toFixed(2)),
    };
  }

  /**
   * 构建无 LLM 模式提示词（仅返回检索结果）
   */
  buildNoLLM(
    query: string,
    contextBlocks: ContextBlock[]
  ): { system: string; user: string } {
    const context = this.formatContext(contextBlocks);
    const summary = this.summarizeResults(contextBlocks);

    return {
      system: '你是一个信息检索助手，负责汇总检索结果。',
      user: NO_LLM_PROMPT
        .replace('{query}', query)
        .replace('{context}', context)
        .replace('{summary}', summary),
    };
  }

  /**
   * 格式化上下文块
   */
  private formatContext(blocks: ContextBlock[]): string {
    if (blocks.length === 0) {
      return '（无相关文档）';
    }

    return blocks
      .map(block => {
        let formatted = `[ID: ${block.id}, Source: ${block.source}]\n`;
        formatted += block.content;
        if (block.isTruncated) {
          formatted += '\n[此段内容已截断，建议查阅原文]';
        }
        return formatted;
      })
      .join('\n\n---\n\n');
  }

  /**
   * 汇总检索结果（无 LLM 模式）
   */
  private summarizeResults(blocks: ContextBlock[]): string {
    return blocks
      .map((block, idx) => `${idx + 1}. ${block.content.substring(0, 200)}${block.content.length > 200 ? '...' : ''}`)
      .join('\n');
  }

  /**
   * 从 LLM 回答中提取引用 ID
   */
  extractCitationIds(answer: string): number[] {
    const regex = /\[(\d+)\]/g;
    const ids: number[] = [];
    let match;

    while ((match = regex.exec(answer)) !== null) {
      const id = parseInt(match[1], 10);
      if (!ids.includes(id)) {
        ids.push(id);
      }
    }

    return ids;
  }

  /**
   * 构建用于流式生成的单条消息
   */
  buildStreamMessage(
    query: string,
    contextBlocks: ContextBlock[],
    contextTruncated: boolean = false
  ): string {
    const context = this.formatContext(contextBlocks);
    
    let prompt = `【Context】\n${context}\n\n`;
    
    if (contextTruncated) {
      prompt += `⚠️ 注意：Context 因长度限制被截断，以下回答可能不完整。\n\n`;
    }
    
    prompt += `【问题】${query}\n\n`;
    prompt += `请严格基于 Context 回答，每个事实陈述后标注 [引用ID]。`;

    return prompt;
  }
}

/**
 * 创建提示词构建器
 */
export function createPromptBuilder(systemPrompt?: string): PromptBuilder {
  return new PromptBuilder(systemPrompt);
}
