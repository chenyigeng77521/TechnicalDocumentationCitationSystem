/**
 * 项目配置文件
 */
export const config = {
    // 上传配置
    upload: {
        uploadDir: '../storage/raw', // 上传文件存储目录（相对于 entrance/ 目录）
        maxFileSize: 300, // 单个文件最大大小（MB）
        allowedFormats: [
            '.json', '.yaml', '.yml', '.cpp', '.java', '.py', '.xml', '.sql',
            '.html', '.md', '.txt', '.ppt', '.pptx', '.xls', '.xlsx',
            '.doc', '.docx', '.pdf'
        ], // 允许的文件格式
        maxFiles: 30, // 最多同时上传文件数
    },
    // 服务器配置
    server: {
        port: parseInt(process.env.PORT || '3002'),
        host: process.env.HOST || '0.0.0.0',
    },
};
export default config;
//# sourceMappingURL=config.js.map