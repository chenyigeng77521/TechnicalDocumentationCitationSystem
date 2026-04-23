/**
 * 数据库模块
 * 使用 SQLite 存储文件和文档块信息
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { v4 as uuidv4 } from 'uuid';
import { FileRecord, ChunkRecord, ChunkInsertInput } from '../types.js';

export class DatabaseManager {
  private db: Database.Database;
  private dbPath: string;

  constructor(dbPath: string = './storage/knowledge.db') {
    this.dbPath = dbPath;
    this.ensureDirectory();
    this.db = new Database(dbPath);
    this.initializeSchema();
  }

  /**
   * 确保数据库目录存在
   */
  private ensureDirectory(): void {
    const dir = path.dirname(this.dbPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  /**
   * 初始化数据库 schema
   */
  private initializeSchema(): void {
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
  insertFile(file: Omit<FileRecord, 'id'> & { id?: string }): string {
    const id = file.id || uuidv4();
    const tagsJson = file.tags ? JSON.stringify(file.tags) : null;

    const stmt = this.db.prepare(`
      INSERT INTO files (id, original_name, original_path, converted_path, format, size, upload_time, category, status, tags)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      file.original_name,
      file.original_path,
      file.converted_path,
      file.format,
      file.size,
      file.upload_time,
      file.category || '',
      file.status,
      tagsJson
    );

    return id;
  }

  /**
   * 获取文件记录
   */
  getFile(fileId: string): FileRecord | null {
    const stmt = this.db.prepare('SELECT * FROM files WHERE id = ?');
    return stmt.get(fileId) as FileRecord | null;
  }

  /**
   * 更新文件状态
   */
  updateFileStatus(fileId: string, status: string): void {
    const stmt = this.db.prepare('UPDATE files SET status = ? WHERE id = ?');
    stmt.run(status, fileId);
  }

  /**
   * 删除文件记录
   */
  deleteFile(fileId: string): void {
    const stmt = this.db.prepare('DELETE FROM files WHERE id = ?');
    stmt.run(fileId);
  }

  /**
   * 获取所有文件
   */
  getAllFiles(filters?: {
    format?: string;
    category?: string;
    status?: string;
  }): FileRecord[] {
    let query = 'SELECT * FROM files WHERE 1=1';
    const params: any[] = [];

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
    return stmt.all(...params) as FileRecord[];
  }

  /**
   * 插入文档块
   */
  insertChunk(chunk: ChunkInsertInput): string {
    const id = chunk.id || uuidv4();
    const originalLinesJson = JSON.stringify(chunk.original_lines);
    const vectorJson = chunk.vector ? JSON.stringify(chunk.vector) : null;

    const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    stmt.run(
      id,
      chunk.file_id,
      chunk.content,
      chunk.start_line,
      chunk.end_line,
      originalLinesJson,
      vectorJson
    );

    return id;
  }

  /**
   * 获取文档块
   */
  getChunk(chunkId: string): ChunkRecord | null {
    const stmt = this.db.prepare('SELECT * FROM chunks WHERE id = ?');
    const result = stmt.get(chunkId) as ChunkRecord | null;
    
    if (result) {
      (result as any).original_lines = JSON.parse(result.original_lines);
      if (result.vector) {
        (result as any).vector = JSON.parse(result.vector);
      }
    }
    
    return result;
  }

  /**
   * 获取文件的所有文档块
   */
  getFileChunks(fileId: string): ChunkRecord[] {
    const stmt = this.db.prepare('SELECT * FROM chunks WHERE file_id = ?');
    const results = stmt.all(fileId) as (ChunkRecord & { 
      original_lines: string; 
      vector?: string 
    })[];

    return results.map(r => ({
      ...r,
      original_lines: JSON.parse(r.original_lines),
      vector: r.vector ? JSON.parse(r.vector) : []
    }));
  }

  /**
   * 搜索文档块（基于内容关键词）
   */
  searchChunks(query: string, fileId?: string): ChunkRecord[] {
    let sql = 'SELECT * FROM chunks WHERE content LIKE ?';
    const params: any[] = [`%${query}%`];

    if (fileId) {
      sql += ' AND file_id = ?';
      params.push(fileId);
    }

    const stmt = this.db.prepare(sql);
    const results = stmt.all(...params) as (ChunkRecord & { 
      original_lines: string; 
      vector?: string 
    })[];

    return results.map(r => ({
      ...r,
      original_lines: JSON.parse(r.original_lines),
      vector: r.vector ? JSON.parse(r.vector) : []
    }));
  }

  /**
   * 批量插入文档块
   */
  insertChunks(chunks: ChunkInsertInput[]): string[] {
    const ids: string[] = [];

    const stmt = this.db.prepare(`
      INSERT INTO chunks (id, file_id, content, start_line, end_line, original_lines, vector)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    const insert = this.db.transaction((chunkList: ChunkInsertInput[]) => {
      for (const chunk of chunkList) {
        const id = chunk.id || uuidv4();
        ids.push(id);
        
        stmt.run(
          id,
          chunk.file_id,
          chunk.content,
          chunk.start_line,
          chunk.end_line,
          JSON.stringify(chunk.original_lines),
          chunk.vector ? JSON.stringify(chunk.vector) : null
        );
      }
    });

    insert(chunks);
    return ids;
  }

  /**
   * 更新文档块向量
   */
  updateChunkVector(chunkId: string, vector: number[]): void {
    const stmt = this.db.prepare(`
      UPDATE chunks SET vector = ? WHERE id = ?
    `);
    stmt.run(JSON.stringify(vector), chunkId);
  }

  /**
   * 删除文件的所有文档块
   */
  deleteFileChunks(fileId: string): void {
    const stmt = this.db.prepare('DELETE FROM chunks WHERE file_id = ?');
    stmt.run(fileId);
  }

  /**
   * 关闭数据库连接
   */
  close(): void {
    this.db.close();
    console.log('✅ 数据库连接已关闭');
  }

  /**
   * 获取数据库统计信息
   * fileCount 只计 status='completed' 的记录，和 getAllFiles({status:'completed'}) 返回结果长度一致
   * （避免 /stats.totalFiles 和 /files 列表长度不同步）
   */
  getStats(): { fileCount: number; chunkCount: number } {
    const fileCount = this.db.prepare("SELECT COUNT(*) as count FROM files WHERE status = 'completed'").get() as { count: number };
    const chunkCount = this.db.prepare('SELECT COUNT(*) as count FROM chunks').get() as { count: number };

    return {
      fileCount: fileCount.count,
      chunkCount: chunkCount.count
    };
  }
}
