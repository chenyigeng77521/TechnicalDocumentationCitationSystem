PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    file_path        TEXT PRIMARY KEY,
    file_name        TEXT NOT NULL,
    file_hash        TEXT NOT NULL,
    file_size        INTEGER NOT NULL,
    format           TEXT NOT NULL,
    language         TEXT,
    index_version    TEXT NOT NULL,
    index_status     TEXT DEFAULT 'pending',
    error_detail     TEXT,
    chunk_count      INTEGER DEFAULT 0,
    last_modified    TIMESTAMP NOT NULL,
    indexed_at       TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          TEXT PRIMARY KEY,
    file_path         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,
    index_version     TEXT NOT NULL,
    content           TEXT NOT NULL,
    anchor_id         TEXT NOT NULL,
    title_path        TEXT,
    char_offset_start INTEGER NOT NULL,
    char_offset_end   INTEGER NOT NULL,
    char_count        INTEGER NOT NULL,
    chunk_index       INTEGER NOT NULL,
    is_truncated      INTEGER DEFAULT 0,
    content_type      TEXT NOT NULL DEFAULT 'document',
    language          TEXT,
    embedding         TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_path) REFERENCES documents(file_path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_file    ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_version ON chunks(index_version);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    content,
    title_path,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
    INSERT INTO chunks_fts(chunk_id, content, title_path)
    VALUES (new.chunk_id, new.content, new.title_path);
END;
