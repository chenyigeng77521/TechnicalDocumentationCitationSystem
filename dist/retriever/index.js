/**
 * 检索引擎模块
 * 支持语义检索和关键词检索
 */
import { OpenAI } from 'openai';
export class Retriever {
    db;
    openai = null;
    embeddingModel;
    embeddingDimension;
    topKDefault;
    constructor(db, config = {}) {
        this.db = db;
        this.embeddingModel = config.embeddingModel || 'text-embedding-3-large';
        this.embeddingDimension = config.embeddingDimension || 1536;
        this.topKDefault = config.topKDefault || 5;
        // 初始化 OpenAI 客户端（如果提供了 API Key）
        if (config.llmApiKey) {
            this.openai = new OpenAI({
                apiKey: config.llmApiKey,
                baseURL: config.llmBaseUrl
            });
            console.log('✅ 检索引擎初始化完成（支持语义检索）');
        }
        else {
            console.log('⚠️ 检索引擎初始化完成（仅支持关键词检索）');
        }
    }
    /**
     * 计算文本向量
     */
    async embed(text) {
        if (!this.openai) {
            throw new Error('未配置 LLM API Key，无法计算向量');
        }
        const response = await this.openai.embeddings.create({
            model: this.embeddingModel,
            input: text,
            dimensions: this.embeddingDimension
        });
        return response.data[0].embedding;
    }
    /**
     * 计算余弦相似度
     */
    cosineSimilarity(vec1, vec2) {
        if (vec1.length !== vec2.length) {
            throw new Error('向量维度不匹配');
        }
        let dotProduct = 0;
        let norm1 = 0;
        let norm2 = 0;
        for (let i = 0; i < vec1.length; i++) {
            dotProduct += vec1[i] * vec2[i];
            norm1 += vec1[i] * vec1[i];
            norm2 += vec2[i] * vec2[i];
        }
        return dotProduct / (Math.sqrt(norm1) * Math.sqrt(norm2));
    }
    /**
     * 检索相关文档块
     */
    async search(request) {
        const topK = request.topK || this.topKDefault;
        let candidates = [];
        // 方式 1：语义检索（如果有向量）
        if (this.openai) {
            try {
                console.log(`🔍 语义检索：${request.query}`);
                const queryVector = await this.embed(request.query);
                // 获取所有带向量的文档块
                const allChunks = this.db.getAllFiles().flatMap(file => this.db.getFileChunks(file.id).filter(c => c.vector && c.vector.length > 0));
                // 计算相似度
                candidates = allChunks
                    .map(chunk => ({
                    ...chunk,
                    score: this.cosineSimilarity(queryVector, chunk.vector)
                }))
                    .sort((a, b) => (b.score || 0) - (a.score || 0))
                    .slice(0, topK * 2); // 取更多候选用于重排序
                console.log(`✅ 语义检索完成，找到 ${candidates.length} 个候选`);
            }
            catch (error) {
                console.error('❌ 语义检索失败，降级为关键词检索:', error.message);
                candidates = [];
            }
        }
        // 方式 2：关键词检索（兜底）
        if (candidates.length === 0) {
            console.log(`🔍 关键词检索：${request.query}`);
            let chunks = this.db.searchChunks(request.query);
            // 应用过滤器
            if (request.filters?.fileId) {
                chunks = chunks.filter(c => c.file_id === request.filters.fileId);
            }
            // 简单评分：基于关键词匹配度
            candidates = chunks
                .map(chunk => ({
                ...chunk,
                score: this.keywordScore(chunk.content, request.query)
            }))
                .sort((a, b) => (b.score || 0) - (a.score || 0))
                .slice(0, topK);
            console.log(`✅ 关键词检索完成，找到 ${candidates.length} 个结果`);
        }
        // 构建搜索结果
        const results = candidates.slice(0, topK).map(chunk => ({
            fileId: chunk.file_id,
            fileName: this.getFileName(chunk.file_id),
            content: chunk.content,
            score: chunk.score || 0,
            citations: this.buildCitations(chunk)
        }));
        return {
            results,
            total: results.length,
            query: request.query
        };
    }
    /**
     * 关键词评分
     */
    keywordScore(content, query) {
        const queryWords = query.toLowerCase().split(/\s+/).filter(w => w.length > 2);
        const contentLower = content.toLowerCase();
        let score = 0;
        for (const word of queryWords) {
            const count = (contentLower.match(new RegExp(word, 'g')) || []).length;
            score += count;
        }
        // 归一化
        return score / queryWords.length;
    }
    /**
     * 获取文件名
     */
    getFileName(fileId) {
        const file = this.db.getFile(fileId);
        return file?.original_name || '未知文件';
    }
    /**
     * 构建引用信息
     */
    buildCitations(chunk) {
        const file = this.db.getFile(chunk.file_id);
        return [{
                documentPath: file?.original_name || '未知文件',
                paragraph: this.extractParagraphAnchor(chunk),
                originalFile: file?.original_name || '未知文件',
                originalLines: chunk.original_lines,
                mdLines: [chunk.start_line, chunk.end_line]
            }];
    }
    /**
     * 提取段落锚点
     */
    extractParagraphAnchor(chunk) {
        const lines = chunk.content.split('\n');
        // 查找标题或首句
        for (const line of lines) {
            if (line.trim().startsWith('#')) {
                return line.trim();
            }
        }
        // 返回首句（前 50 字符）
        const firstSentence = lines[0]?.trim().substring(0, 50) || '无标题';
        return firstSentence + (lines[0]?.length > 50 ? '...' : '');
    }
    /**
     * 为文档块计算向量并存储
     */
    async indexChunks(fileId) {
        if (!this.openai) {
            console.log('⚠️ 未配置 LLM API Key，跳过向量化');
            return;
        }
        const chunks = this.db.getFileChunks(fileId);
        console.log(`📊 开始向量化：${chunks.length} 个文档块`);
        for (const chunk of chunks) {
            try {
                const vector = await this.embed(chunk.content);
                // 更新数据库
                const stmt = this.db.db.prepare(`
          UPDATE chunks SET vector = ? WHERE id = ?
        `);
                stmt.run(JSON.stringify(vector), chunk.id);
                console.log(`✅ 向量化完成：${chunk.id}`);
            }
            catch (error) {
                console.error(`❌ 向量化失败：${chunk.id}`, error.message);
            }
        }
        console.log(`✅ 文件 ${fileId} 向量化完成`);
    }
    /**
     * 批量向量化所有文件
     */
    async indexAllFiles() {
        const files = this.db.getAllFiles({ status: 'completed' });
        console.log(`📚 开始批量向量化：${files.length} 个文件`);
        for (const file of files) {
            await this.indexChunks(file.id);
        }
        console.log('✅ 批量向量化完成');
    }
}
//# sourceMappingURL=index.js.map