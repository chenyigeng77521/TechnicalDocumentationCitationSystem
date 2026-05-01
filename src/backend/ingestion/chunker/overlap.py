"""overlap 拼接：把前一个 chunk 末尾 200 char 拼到下一个 chunk 前。

Spec: §7 overlap 200 char
"""
from backend.ingestion.chunker.types import Chunk

OVERLAP_CHARS = 200


def apply_overlap(chunks: list[Chunk]) -> list[Chunk]:
    """对 chunk 列表应用 overlap。第一个 chunk 不变；后续每个 chunk 前面
    拼上前一个的末尾 OVERLAP_CHARS 个字符。is_truncated chunk 不加。
    """
    if len(chunks) <= 1:
        return chunks

    out = [chunks[0]]
    for prev, curr in zip(chunks, chunks[1:]):
        if curr.is_truncated:
            out.append(curr)
            continue
        tail = prev.content[-OVERLAP_CHARS:]
        new_content = tail + curr.content
        new_chunk = Chunk(
            chunk_id=curr.chunk_id,
            file_path=curr.file_path,
            file_hash=curr.file_hash,
            index_version=curr.index_version,
            content=new_content,
            anchor_id=curr.anchor_id,
            title_path=curr.title_path,
            char_offset_start=curr.char_offset_start,
            char_offset_end=curr.char_offset_end,
            char_count=len(new_content),
            chunk_index=curr.chunk_index,
            is_truncated=curr.is_truncated,
            content_type=curr.content_type,
            language=curr.language,
        )
        out.append(new_chunk)
    return out
