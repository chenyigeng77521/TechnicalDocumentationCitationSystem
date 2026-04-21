/**
 * 问答服务模块
 * 基于检索结果生成回答，严格引用出处
 */
import { DatabaseManager } from '../database/index.js';
import { Retriever } from '../retriever/index.js';
import { QARequest, QAResponse } from '../types.js';
export declare class QAAgent {
    private db;
    private retriever;
    private openai;
    private llmModel;
    private strictModeDefault;
    constructor(db: DatabaseManager, retriever: Retriever, config?: {
        llmApiKey?: string;
        llmBaseUrl?: string;
        llmModel?: string;
        strictModeDefault?: boolean;
    });
    /**
     * 回答问题
     */
    answer(request: QARequest): Promise<QAResponse>;
    /**
     * 无据拒答响应
     */
    private noEvidenceResponse;
    /**
     * 简单响应（无 LLM）
     */
    private simpleResponse;
    /**
     * 构建提示词
     */
    private buildPrompt;
    /**
     * LLM 生成回答
     */
    private generateWithLLM;
    /**
     * 解析引用
     */
    private parseCitations;
    /**
     * 计算置信度
     */
    private calculateConfidence;
    /**
     * 获取所有可用文件列表
     */
    getAvailableFiles(): Array<{
        id: string;
        name: string;
        format: string;
    }>;
}
//# sourceMappingURL=index.d.ts.map