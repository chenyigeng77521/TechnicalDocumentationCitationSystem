/**
 * 问答服务模块
 * 基于检索结果生成回答，严格引用出处
 */
import { OpenAI } from 'openai';
export class QAAgent {
    db;
    retriever;
    openai = null;
    llmModel;
    strictModeDefault;
    constructor(db, retriever, config = {}) {
        this.db = db;
        this.retriever = retriever;
        this.llmModel = config.llmModel || 'gpt-4-turbo';
        this.strictModeDefault = config.strictModeDefault ?? true;
        // 初始化 OpenAI 客户端
        if (config.llmApiKey) {
            this.openai = new OpenAI({
                apiKey: config.llmApiKey,
                baseURL: config.llmBaseUrl
            });
            console.log('✅ 问答服务初始化完成');
        }
        else {
            console.log('⚠️ 问答服务初始化完成（无 LLM，仅返回检索结果）');
        }
    }
    /**
     * 回答问题
     */
    async answer(request) {
        const topK = request.topK || 5;
        const strictMode = request.strictMode ?? this.strictModeDefault;
        console.log(`❓ 问题：${request.question}`);
        console.log(`📊 检索数量：${topK}, 严格模式：${strictMode}`);
        // 1. 检索相关文档
        const searchResults = await this.retriever.search({
            query: request.question,
            topK
        });
        // 2. 检查是否有足够证据
        if (searchResults.results.length === 0) {
            return this.noEvidenceResponse(request.question);
        }
        // 3. 判断是否需要 LLM
        if (!this.openai || !strictMode) {
            return this.simpleResponse(searchResults);
        }
        // 4. LLM 生成回答
        try {
            const prompt = this.buildPrompt(request.question, searchResults.results, strictMode);
            const llmResponse = await this.generateWithLLM(prompt);
            // 5. 解析并验证引用
            const parsed = this.parseCitations(llmResponse, searchResults.results);
            return {
                answer: parsed.answer,
                citations: parsed.citations,
                confidence: this.calculateConfidence(parsed),
                noEvidence: false,
                query: request.question
            };
        }
        catch (error) {
            console.error('❌ LLM 生成失败，降级为简单响应:', error.message);
            return this.simpleResponse(searchResults);
        }
    }
    /**
     * 无据拒答响应
     */
    noEvidenceResponse(question) {
        return {
            answer: '根据现有文档，我无法回答这个问题。',
            citations: [],
            confidence: 0,
            noEvidence: true,
            query: question
        };
    }
    /**
     * 简单响应（无 LLM）
     */
    simpleResponse(searchResults) {
        const answer = searchResults.results
            .map((r, idx) => {
            const citation = r.citations[0];
            const docName = citation?.documentPath || '未知文档';
            const para = citation?.paragraph || '无段落信息';
            return `${idx + 1}. [${docName} - ${para}]\n${r.content}`;
        })
            .join('\n\n');
        const citations = searchResults.results.flatMap(r => r.citations);
        return {
            answer,
            citations,
            confidence: 0.5,
            noEvidence: false,
            query: ''
        };
    }
    /**
     * 构建提示词
     */
    buildPrompt(question, results, strictMode) {
        const context = results.map((r, idx) => {
            const citation = r.citations[0];
            const docName = citation?.documentPath || '未知文档';
            const para = citation?.paragraph || '无段落信息';
            return `[文档 ${idx + 1}: ${docName}]\n` +
                `段落：${para}\n` +
                `内容：${r.content}\n` +
                `引用格式：（文档路径：${docName}，段落：${para}）`;
        }).join('\n---\n');
        const strictRules = strictMode ? `
【严格规则】
1. 只能根据参考文档内容回答，严禁使用外部知识
2. 每个判断或结论必须附带至少一条出处
3. 如果文档中没有答案，只回复："根据现有文档，我无法回答这个问题。"
4. 不要编造答案或添加额外解释
` : `
【回答规则】
1. 优先根据参考文档内容回答
2. 重要判断应附带出处
3. 如果文档中没有答案，说明情况
`;
        return `你是一名严谨的技术问答助手。

【参考文档片段】
${context}

【用户问题】
${question}

${strictRules}

【你的回答】
`;
    }
    /**
     * LLM 生成回答
     */
    async generateWithLLM(prompt) {
        if (!this.openai) {
            throw new Error('未配置 LLM');
        }
        const response = await this.openai.chat.completions.create({
            model: this.llmModel,
            messages: [
                {
                    role: 'system',
                    content: '你是一名严谨的技术问答助手，只能根据提供的文档回答问题，必须严格引用出处。'
                },
                {
                    role: 'user',
                    content: prompt
                }
            ],
            temperature: 0.1, // 低温度保证稳定性
            max_tokens: 2000
        });
        return response.choices[0].message.content || '';
    }
    /**
     * 解析引用
     */
    parseCitations(llmResponse, results) {
        const citations = [];
        let answer = llmResponse;
        // 提取所有引用格式：（文档路径：xxx，段落：xxx）
        const citationRegex = /（文档路径：([^，]+)，段落：([^）]+)）/g;
        let match;
        while ((match = citationRegex.exec(llmResponse)) !== null) {
            const docPath = match[1].trim();
            const paragraph = match[2].trim();
            // 查找匹配的搜索结果
            const matchingResult = results.find(r => r.citations.some(c => c.documentPath === docPath && c.paragraph === paragraph));
            if (matchingResult) {
                citations.push(matchingResult.citations[0]);
            }
        }
        return { answer, citations };
    }
    /**
     * 计算置信度
     */
    calculateConfidence(parsed) {
        if (parsed.citations.length === 0)
            return 0;
        // 基于引用数量和回答长度计算置信度
        const citationScore = Math.min(parsed.citations.length / 3, 1) * 0.6;
        const lengthScore = Math.min(parsed.answer.length / 200, 1) * 0.4;
        return Math.round((citationScore + lengthScore) * 100) / 100;
    }
    /**
     * 获取所有可用文件列表
     */
    getAvailableFiles() {
        const files = this.db.getAllFiles({ status: 'completed' });
        return files.map(f => ({
            id: f.id,
            name: f.original_name,
            format: f.format
        }));
    }
}
//# sourceMappingURL=index.js.map