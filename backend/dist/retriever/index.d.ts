/**
 * 检索引擎模块
 * 支持语义检索和关键词检索
 */
import { DatabaseManager } from '../database/index.js';
import { SearchRequest, SearchResponse } from '../types.js';
export declare class Retriever {
    private db;
    private openai;
    private embeddingModel;
    private embeddingDimension;
    private topKDefault;
    constructor(db: DatabaseManager, config?: {
        llmApiKey?: string;
        llmBaseUrl?: string;
        embeddingModel?: string;
        embeddingDimension?: number;
        topKDefault?: number;
    });
    /**
     * 计算文本向量
     */
    private embed;
    /**
     * 计算余弦相似度
     */
    private cosineSimilarity;
    /**
     * 检索相关文档块
     */
    search(request: SearchRequest): Promise<SearchResponse>;
    /**
     * 关键词评分
     */
    private keywordScore;
    /**
     * 获取文件名
     */
    private getFileName;
    /**
     * 构建引用信息
     */
    private buildCitations;
    /**
     * 提取段落锚点
     */
    private extractParagraphAnchor;
    /**
     * 为文档块计算向量并存储
     */
    indexChunks(fileId: string): Promise<void>;
    /**
     * 批量向量化所有文件
     */
    indexAllFiles(): Promise<void>;
}
//# sourceMappingURL=index.d.ts.map