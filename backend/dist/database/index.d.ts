/**
 * 数据库模块
 * 使用 SQLite 存储文件和文档块信息
 */
import { FileRecord, ChunkRecord } from '../types.js';
export declare class DatabaseManager {
    private db;
    private dbPath;
    constructor(dbPath?: string);
    /**
     * 确保数据库目录存在
     */
    private ensureDirectory;
    /**
     * 初始化数据库 schema
     */
    private initializeSchema;
    /**
     * 插入文件记录
     */
    insertFile(file: Omit<FileRecord, 'id'> & {
        id?: string;
    }): string;
    /**
     * 获取文件记录
     */
    getFile(fileId: string): FileRecord | null;
    /**
     * 更新文件状态
     */
    updateFileStatus(fileId: string, status: string): void;
    /**
     * 删除文件记录
     */
    deleteFile(fileId: string): void;
    /**
     * 获取所有文件
     */
    getAllFiles(filters?: {
        format?: string;
        category?: string;
        status?: string;
    }): FileRecord[];
    /**
     * 插入文档块
     */
    insertChunk(chunk: Omit<ChunkRecord, 'id'> & {
        id?: string;
    }): string;
    /**
     * 获取文档块
     */
    getChunk(chunkId: string): ChunkRecord | null;
    /**
     * 获取文件的所有文档块
     */
    getFileChunks(fileId: string): ChunkRecord[];
    /**
     * 搜索文档块（基于内容关键词）
     */
    searchChunks(query: string, fileId?: string): ChunkRecord[];
    /**
     * 批量插入文档块
     */
    insertChunks(chunks: (Omit<ChunkRecord, 'id'> & {
        id?: string;
    })[]): string[];
    /**
     * 更新文档块向量
     */
    updateChunkVector(chunkId: string, vector: number[]): void;
    /**
     * 删除文件的所有文档块
     */
    deleteFileChunks(fileId: string): void;
    /**
     * 关闭数据库连接
     */
    close(): void;
    /**
     * 获取数据库统计信息
     */
    getStats(): {
        fileCount: number;
        chunkCount: number;
    };
}
//# sourceMappingURL=index.d.ts.map