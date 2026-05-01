"""chunker dataclass。"""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Chunk:
    chunk_id: str
    file_path: str
    file_hash: str
    index_version: str
    content: str
    anchor_id: str
    title_path: Optional[str]
    char_offset_start: int
    char_offset_end: int
    char_count: int
    chunk_index: int
    is_truncated: bool = False
    content_type: str = "document"
    language: Optional[str] = None
    embedding: Optional[list[float]] = None
    markdown_anchor: Optional[str] = None  # 比赛口径锚点（#xxx 或 #top），W2 chunker 改造时填

    def to_dict(self) -> dict:
        return asdict(self)
