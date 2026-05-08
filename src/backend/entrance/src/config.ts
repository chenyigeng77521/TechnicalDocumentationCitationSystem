/**
 * 项目配置文件
 * 所有配置通过 getter 延迟读取环境变量
 */

export const config = {
  // 服务器配置（运行时读取）
  get server() {
    return {
      port: parseInt(process.env.PORT || '3002'),
      host: process.env.HOST || '0.0.0.0',
    };
  },
  // 上传配置（运行时读取）
  get upload() {
    return {
      uploadDir: process.env.UPLOAD_DIR || '../../../data/documents',
      batchTestDir: '../storage/batchtest',
      maxFileSize: 300,
      allowedFormats: [
        '.json', '.yaml', '.yml', '.cpp', '.java', '.py', '.xml', '.sql',
        '.html', '.md', '.txt', '.ppt', '.pptx',
        '.doc', '.docx', '.pdf', '.xlsx', '.adoc', '.jsonl'
      ],
      maxFiles: 100,
    };
  },
  // 数据根目录（用于知识库文件列表递归扫描）
  get dataRoot() {
    return {
      // 从 entrance 到 data/ 目录的路径
      path: process.env.DATA_ROOT || '../../../data',
    };
  },
  // category_classifier 配置（运行时读取）
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
      enabled: process.env.ENABLE_QUESTION_FILTER !== 'false',  // 默认启用
      timeout: parseInt(process.env.FILTER_TIMEOUT || '5000'),
    };
  },
  // Context Memory 配置（运行时读取）
  get contextMemory() {
    return {
      url: process.env.CONTEXT_MEMORY_URL || 'http://localhost:3006',
      enabled: process.env.ENABLE_CONTEXT_MEMORY !== 'false',  // 默认启用
      timeout: parseInt(process.env.CONTEXT_MEMORY_TIMEOUT || '5000'),
    };
  },
  // 检索层配置（运行时读取）
  get retrieval() {
    return {
      url: process.env.RETRIEVAL_URL || 'http://localhost:8001/api/qa',
      enabled: !!process.env.RETRIEVAL_URL,  // 配置了 URL 就启用
      timeout: parseInt(process.env.HTTP_TIMEOUT || '600000'),
      // 批量查询接口地址
      batchQueryUrl: process.env.BATCH_QUERY_URL || 'http://localhost:8001/api/qa/batch',
    };
  },
  // NLU 配置（运行时读取）
  get nlu() {
    return {
      enabled: process.env.ENABLE_NLU === 'true',  // 默认不启用
      pipelineUrl: process.env.NLU_PIPELINE_URL || 'http://localhost:3004/api/nlu/process',
    };
  },
  // 存储配置
  get storage() {
    return {
      // 结果文件目录（可通过环境变量 RESULT_DIR 覆盖）
      resultDir: process.env.RESULT_DIR || '../../../eval',
    };
  },
};

export default config;
