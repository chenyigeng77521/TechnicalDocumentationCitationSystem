import OpenAI from 'openai';
const openai = new OpenAI({
    baseURL: process.env.LLM_BASE_URL || 'https://api.openai.com/v1',
    apiKey: process.env.LLM_API_KEY || 'dummy-key',
});
const MODEL = process.env.LLM_MODEL || 'gpt-4-turbo';
/**
 * 流式生成回答
 * 返回异步生成器，每次 yield 一部分文本
 */
export async function* generateAnswer(prompt, question, chunks) {
    try {
        // 检查是否有 LLM API Key
        if (!process.env.LLM_API_KEY || process.env.LLM_API_KEY === 'your_openai_api_key') {
            // 降级为关键词检索模式，返回基于文档的简单回答
            yield '抱歉，当前系统未配置 LLM API 密钥，无法生成智能回答。\n\n';
            yield '但根据检索到的文档，以下是相关信息：\n\n';
            for (const chunk of chunks) {
                yield `【${chunk.documentPath}】\n`;
                yield `${chunk.content.substring(0, 200)}...\n\n`;
            }
            yield '(请配置 LLM_API_KEY 以启用完整的智能问答功能)';
            return;
        }
        const stream = await openai.chat.completions.create({
            model: MODEL,
            messages: [
                {
                    role: 'system',
                    content: '你是一个基于文档的智能问答助手。只能根据提供的文档内容回答，严禁编造或使用外部知识。每个回答必须引用文档出处。'
                },
                {
                    role: 'user',
                    content: prompt
                }
            ],
            stream: true,
            temperature: 0.3, // 较低的温度使回答更稳定
            max_tokens: 2000,
        });
        // 流式处理响应
        for await (const chunk of stream) {
            const content = chunk.choices[0]?.delta?.content || '';
            if (content) {
                yield content;
            }
        }
    }
    catch (error) {
        console.error('LLM 生成错误:', error);
        // 降级处理：直接返回文档内容
        yield '抱歉，LLM 服务调用失败，以下是检索到的相关文档内容：\n\n';
        for (const chunk of chunks) {
            yield `【${chunk.documentPath}】\n`;
            yield `${chunk.content}\n\n`;
        }
    }
}
/**
 * 非流式生成回答（用于兼容旧 API）
 */
export async function generateAnswerSync(prompt, question, chunks) {
    let fullAnswer = '';
    for await (const chunk of generateAnswer(prompt, question, chunks)) {
        fullAnswer += chunk;
    }
    return fullAnswer;
}
//# sourceMappingURL=index.js.map