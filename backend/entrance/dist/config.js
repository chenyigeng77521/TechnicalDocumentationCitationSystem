/**
 * 项目配置文件
 * 所有配置通过 getter 延迟读取环境变量
 */
export const config = {
    // 上传配置（静态）
    upload: {
        uploadDir: '../storage/raw',
        maxFileSize: 300,
        allowedFormats: [
            '.json', '.yaml', '.yml', '.cpp', '.java', '.py', '.xml', '.sql',
            '.html', '.md', '.txt', '.ppt', '.pptx',
            '.doc', '.docx', '.pdf'
        ],
        maxFiles: 30,
    },
    // 服务器配置（运行时读取）
    get server() {
        return {
            port: parseInt(process.env.PORT || '3002'),
            host: process.env.HOST || '0.0.0.0',
        };
    },
    // FirstLayer 配置（运行时读取）
    get firstlayer() {
        return {
            url: process.env.FIRSTLAYER_URL || 'http://localhost:3004',
            enabled: process.env.ENABLE_QUESTION_CLASSIFICATION === 'true',
            timeout: parseInt(process.env.CLASSIFY_TIMEOUT || '5000'),
        };
    },
    // Question Filter 配置（运行时读取）
    get questionFilter() {
        return {
            url: process.env.QUESTION_FILTER_URL || 'http://localhost:3005',
            enabled: process.env.ENABLE_QUESTION_FILTER !== 'false', // 默认启用
            timeout: parseInt(process.env.FILTER_TIMEOUT || '5000'),
        };
    },
};
export default config;
//# sourceMappingURL=config.js.map