/**
 * Question Filter 问题过滤服务客户端
 * 用于调用 question_filter 服务过滤无效问题和实时类问题
 * 调用链条：Web 层 → Question Filter (3005) → Category Classifier (3004)
 */
export type FilterCategory = 'VALID' | 'INVALID' | 'REALTIME' | 'PERSONAL' | 'OFFTOPIC' | 'CHAT' | 'SELF_INRO';
export interface FilterResult {
    success: boolean;
    question: string;
    category: FilterCategory;
    confidence: number;
    description: string;
    reason?: string;
    error?: string;
}
/**
 * 过滤用户问题
 * @param question 用户问题
 * @returns 过滤结果
 */
export declare function filterQuestion(question: string): Promise<FilterResult>;
/**
 * 获取过滤类型列表
 * @returns 过滤类型及其描述
 */
export declare function getFilterTypes(): Promise<Record<string, string>>;
/**
 * 批量过滤问题
 * @param questions 问题列表
 * @returns 过滤结果列表
 */
export declare function batchFilterQuestions(questions: string[]): Promise<FilterResult[]>;
/**
 * 获取实时类关键词列表
 * @returns 实时类关键词
 */
export declare function getRealtimeKeywords(): Promise<string[]>;
/**
 * 检查是否需要进一步分类
 * @param category 过滤分类
 * @returns 是否需要调用分类服务
 */
export declare function needsClassification(category: FilterCategory): boolean;
/**
 * 获取过滤响应消息
 * @param category 过滤分类
 * @returns 响应消息
 */
export declare function getFilterResponse(category: FilterCategory): string | null;
/**
 * 检查过滤类型
 * @param category 过滤分类
 * @returns 是否有效分类
 */
export declare function isValidFilterCategory(category: string): category is FilterCategory;
//# sourceMappingURL=question-filter-client.d.ts.map