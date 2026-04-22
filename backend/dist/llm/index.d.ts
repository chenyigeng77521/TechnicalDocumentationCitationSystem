import { RetrievedChunk } from '../types';
/**
 * 流式生成回答
 * 返回异步生成器，每次 yield 一部分文本
 */
export declare function generateAnswer(prompt: string, question: string, chunks: RetrievedChunk[]): AsyncGenerator<string, void, unknown>;
/**
 * 非流式生成回答（用于兼容旧 API）
 */
export declare function generateAnswerSync(prompt: string, question: string, chunks: RetrievedChunk[]): Promise<string>;
//# sourceMappingURL=index.d.ts.map