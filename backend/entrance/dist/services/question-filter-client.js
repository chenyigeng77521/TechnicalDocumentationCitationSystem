/**
 * Question Filter 问题过滤服务客户端
 * 用于调用 question_filter 服务过滤无效问题和实时类问题
 * 调用链条：Web 层 → Question Filter (3005) → Category Classifier (3004)
 */
import axios from 'axios';
import config from '../config.js';
/**
 * 过滤用户问题
 * @param question 用户问题
 * @returns 过滤结果
 */
export async function filterQuestion(question) {
    // 如果未启用过滤服务，直接返回 VALID
    if (!config.questionFilter.enabled) {
        console.log('⚠️  问题过滤服务未启用，跳过过滤');
        return {
            success: true,
            question,
            category: 'VALID',
            confidence: 0.5,
            description: '问题过滤服务未启用'
        };
    }
    try {
        console.log(`🔍 正在过滤问题：${question.substring(0, 50)}...`);
        const response = await axios.post(`${config.questionFilter.url}/api/filter`, { question }, {
            timeout: config.questionFilter.timeout,
            headers: {
                'Content-Type': 'application/json'
            }
        });
        const result = response.data;
        console.log(`✅ 过滤完成：${result.category} (置信度：${result.confidence})`);
        return result;
    }
    catch (error) {
        console.error(`❌ 问题过滤失败:`, error.message);
        // 如果过滤服务不可用，返回 VALID 但不报错（降级处理）
        return {
            success: true,
            question,
            category: 'VALID',
            confidence: 0.5,
            description: '无法连接到过滤服务，默认视为有效问题'
        };
    }
}
/**
 * 获取过滤类型列表
 * @returns 过滤类型及其描述
 */
export async function getFilterTypes() {
    if (!config.questionFilter.enabled) {
        return {
            VALID: '有效问题 - 可以继续处理',
            INVALID: '无效问题 - 无法回答的问题',
            REALTIME: '实时类问题 - 需要实时数据的问题',
            PERSONAL: '个人隐私 - 涉及个人隐私的问题',
            OFFTOPIC: '偏离主题 - 恶意/敏感/广告等问题',
            CHAT: '友好闲聊 - 日常问候，可适度回应',
            SELF_INRO: '自我介绍 - 询问 AI 身份/能力的问题'
        };
    }
    try {
        const response = await axios.get(`${config.questionFilter.url}/api/filter/types`, { timeout: config.questionFilter.timeout });
        return response.data.types || {};
    }
    catch (error) {
        console.error('❌ 获取过滤类型失败:', error.message);
        // 返回默认分类
        return {
            VALID: '有效问题 - 可以继续处理',
            INVALID: '无效问题 - 无法回答的问题',
            REALTIME: '实时类问题 - 需要实时数据的问题',
            PERSONAL: '个人隐私 - 涉及个人隐私的问题',
            OFFTOPIC: '偏离主题 - 恶意/敏感/广告等问题',
            CHAT: '友好闲聊 - 日常问候，可适度回应'
        };
    }
}
/**
 * 批量过滤问题
 * @param questions 问题列表
 * @returns 过滤结果列表
 */
export async function batchFilterQuestions(questions) {
    if (!config.questionFilter.enabled) {
        return questions.map(q => ({
            success: true,
            question: q,
            category: 'VALID',
            confidence: 0.5,
            description: '问题过滤服务未启用'
        }));
    }
    try {
        const response = await axios.post(`${config.questionFilter.url}/api/filter/batch`, { questions }, {
            timeout: config.questionFilter.timeout,
            headers: {
                'Content-Type': 'application/json'
            }
        });
        return response.data.results || [];
    }
    catch (error) {
        console.error('❌ 批量过滤失败:', error.message);
        // 降级处理
        return questions.map(q => ({
            success: true,
            question: q,
            category: 'VALID',
            confidence: 0.5,
            description: '无法连接到过滤服务，默认视为有效问题'
        }));
    }
}
/**
 * 获取实时类关键词列表
 * @returns 实时类关键词
 */
export async function getRealtimeKeywords() {
    if (!config.questionFilter.enabled) {
        return [];
    }
    try {
        const response = await axios.get(`${config.questionFilter.url}/api/filter/keywords`, { timeout: config.questionFilter.timeout });
        return response.data.keywords || [];
    }
    catch (error) {
        console.error('❌ 获取实时关键词失败:', error.message);
        return [];
    }
}
/**
 * 检查是否需要进一步分类
 * @param category 过滤分类
 * @returns 是否需要调用分类服务
 */
export function needsClassification(category) {
    // 只有 VALID 类型的问题需要进一步分类
    return category === 'VALID';
}
/**
 * 获取过滤响应消息
 * @param category 过滤分类
 * @returns 响应消息
 */
export function getFilterResponse(category) {
    const responses = {
        VALID: null, // 有效问题，继续处理
        INVALID: '抱歉，您的问题不够清晰或无法识别。请重新表述您的问题。',
        REALTIME: '抱歉，这是一个需要实时数据的问题（如天气、新闻、股价等），本系统无法提供实时信息。请问一个与知识库相关的问题。',
        PERSONAL: '抱歉，这个问题涉及个人隐私，建议不要询问此类问题。',
        OFFTOPIC: '抱歉，这个问题似乎与我们的知识库无关。请询问关于公司制度、产品使用、技术文档等相关问题。',
        CHAT: '您好！😊 我是知识库助手，主要帮您解答公司制度、产品使用、技术文档等方面的问题。如果您有相关问题，欢迎随时提问！',
        SELF_INRO: '您好！😊 我是知识库助手，主要帮您解答公司制度、产品使用、技术文档等方面的问题。如果您有相关问题，欢迎随时提问！'
    };
    return responses[category];
}
/**
 * 检查过滤类型
 * @param category 过滤分类
 * @returns 是否有效分类
 */
export function isValidFilterCategory(category) {
    const validCategories = ['VALID', 'INVALID', 'REALTIME', 'PERSONAL', 'OFFTOPIC', 'CHAT', 'SELF_INRO'];
    return validCategories.includes(category);
}
//# sourceMappingURL=question-filter-client.js.map