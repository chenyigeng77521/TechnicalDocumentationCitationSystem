/**
 * FirstLayer 问题分类服务客户端
 * 用于调用 firstlayer 服务进行问题分类
 */
export type QuestionCategory = 'FACT' | 'PROC' | 'EXPL' | 'COMP' | 'META' | 'UNKNOWN';
export interface ClassificationResult {
    success: boolean;
    question: string;
    category: QuestionCategory;
    confidence: number;
    description: string;
    error?: string;
}
/**
 * 对问题进行分类
 * @param question 用户问题
 * @returns 分类结果
 */
export declare function classifyQuestion(question: string): Promise<ClassificationResult>;
/**
 * 获取问题分类类型列表
 * @returns 分类类型及其描述
 */
export declare function getQuestionTypes(): Promise<Record<string, string>>;
/**
 * 根据分类类型获取检索策略
 * @param category 问题分类
 * @returns 检索策略描述
 */
export declare function getSearchStrategy(category: QuestionCategory): string;
/**
 * 检查分类类型
 * @param category 问题分类
 * @returns 是否有效分类
 */
export declare function isValidCategory(category: string): category is QuestionCategory;
//# sourceMappingURL=firstlayer-client.d.ts.map