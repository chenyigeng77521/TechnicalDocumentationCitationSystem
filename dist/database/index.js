/**
 * 数据库模块
 * 使用 SQLite 存储文件和文档块信息
 */
import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
export class DatabaseManager {
    db;
    dbPath;
    constructor(dbPath = './storage/knowledge.db') {
        this.dbPath = dbPath;
        this.ensureDirectory();
        this.db = new Database(dbPath);
        this.initializeSchema();
    }
    /**
     * 确保数据库目录存在
     */
    ensureDirectory() {
        const dir = path.dirname(this.dbPath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
    }
    /**
     * 初始化数据库 schema
     */
    initializeSchema() {
        // 文件表
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        original_name TEXT NOT NULL,
        original_path TEXT NOT NULL,
        converted_path TEXT NOT NULL,
        format TEXT NOT NULL,
        size INTEGER NOT NULL,
        upload_time TEXT NOT NULL,
        category TEXT DEFAULT '',
        status TEXT NOT NULL,
        tags TEXT
      )
    `);
        // 文档块表
        this.db.exec(`
      CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        content TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        original_lines TEXT NOT NULL,
        vector TEXT,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
      )
    `);
        // 创建索引
        this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
      CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
      CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
    `);
        console.log('✅ 数据库 schema 初始化完成');
    }
    /**
     * 插入文件记录
     */
    insertFile(file) {
        const id = file.id;
        const tagsJson = file.tags ? JSON.stringify(file.tags) : null;
        const stmt = this.db.prepare(`
      INSERT INTO files (id, original_name, original_path, converted_path, format, size, upload_time, category, status, tags)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
        stmt.run(id, file.original_name, file.original_path, file.converted_path, file.format, file.size, file.upload_time, file.category || '', file.status, tagsJson);
        return id;
    }
    /**
     * 获取文件记录
     */
    getFile(fileId) {
        const stmt = this.db.prepare('SELECT * FROM files WHERE id = ?');
        return stmt.get(fileId);
    }
    /**
     * 更新文件状态
     */
    updateFileStatus(fileId, status) {
        const stmt = this.db.prepare('UPDATE files SET status = ? WHERE id = ?');
        stmt.run(status, fileId);
    }
    /**
     * 删除文件记录
     */
    deleteFile(fileId) {
        const stmt = this.db.prepare('DELETE FROM files WHERE id = ?');
        stmt.run(fileId);
    }
    /**
     * 获取所有文件
     */
    getAllFiles(filters) {
        let query = 'SELECT * FROM files WHERE 1=1';
        const params = [];
        if (filters?.format) {
            query += ' AND format = ?';
            params.push(filters.format);
        }
        if (filters?.category) {
            query += ' AND category = ?';
            params.push(filters.category);
        }
        if (filters?.status) {
            query += ' AND status = ?';
            params.push(filters.status);
        }
        const stmt = this.db.prepare(query);
        return stmt.all(...params);
    }
    /**
     * 插入文档块
     */
    insertChunk(chunk) {
        const id = chunk.id;
        const originalLinesJson = JSON.stringify(chunk.original_lines);
        const vectorJson = chunk.vector ? JSON.stringify(chunk.vector) : null;
        const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
        stmt.run(id, chunk.file_id, chunk.content, chunk.start_line, chunk.end_line, originalLinesJson, vectorJson);
        return id;
    }
    /**
     * 获取文档块
     */
    getChunk(chunkId) {
        const stmt = this.db.prepare('SELECT * FROM chunks WHERE id = ?');
        const result = stmt.get(chunkId);
        if (result) {
            result.original_lines = JSON.parse(result.original_lines);
            if (result.vector) {
                result.vector = JSON.parse(result.vector);
            }
        }
        return result;
    }
    /**
     * 获取文件的所有文档块
     */
    getFileChunks(fileId) {
        const stmt = this.db.prepare('SELECT * FROM chunks WHERE file_id = ?');
        const results = stmt.all(fileId);
        return results.map(r => ({
            ...r,
            original_lines: JSON.parse(r.original_lines),
            vector: r.vector ? JSON.parse(r.vector) : []
        }));
    }
    /**
     * 搜索文档块（基于内容关键词）
     */
    searchChunks(query, fileId) {
        let sql = 'SELECT * FROM chunks WHERE content LIKE ?';
        const params = [`%${query}%`];
        if (fileId) {
            sql += ' AND file_id = ?';
            params.push(fileId);
        }
        const stmt = this.db.prepare(sql);
        const results = stmt.all(...params);
        return results.map(r => ({
            ...r,
            original_lines: JSON.parse(r.original_lines),
            vector: r.vector ? JSON.parse(r.vector) : []
        }));
    }
    /**
     * 批量插入文档块
     */
    insertChunks(chunks) {
        const ids = [];
        const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
        const insert = this.db.transaction((chunkList) => {
            for (const chunk of chunkList) {
                const id = chunk.id;
                ids.push(id);
                stmt.run(id, chunk.file_id, chunk.content, chunk.start_line, chunk.end_line, JSON.stringify(chunk.original_lines), chunk.vector ? JSON.stringify(chunk.vector) : null);
            }
        });
        insert(chunks);
        return ids;
    }
    /**
     * 删除文件的所有文档块
     */
    deleteFileChunks(fileId) {
        const stmt = this.db.prepare('DELETE FROM chunks WHERE file_id = ?');
        stmt.run(fileId);
    }
    /**
     * 关闭数据库连接
     */
    close() {
        this.db.close();
        console.log('✅ 数据库连接已关闭');
    }
    /**
     * 获取数据库统计信息
     */
    getStats() {
        const fileCount = this.db.prepare('SELECT COUNT(*) as count FROM files').get();
        const chunkCount = this.db.prepare('SELECT COUNT(*) as count FROM chunks').get();
        return {
            fileCount: fileCount.count,
            chunkCount: chunkCount.count
        };
    }
}
//# sourceMappingURL=index.js.map