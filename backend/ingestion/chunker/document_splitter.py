"""document 类型三级 fallback 切分。

Spec: §7 chunk 切分策略
"""
import hashlib
import re
from typing import Optional
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.parser.types import ParseResult, TitleNode

MAX_CHARS = 1000
MIN_CHARS = 5
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*")


def _make_chunk_id(file_path: str, chunk_index: int, content: str) -> str:
    h = hashlib.sha256(f"{file_path}|{chunk_index}|{content[:100]}".encode("utf-8"))
    return h.hexdigest()


def _flatten_titles(tree: list[TitleNode]) -> list[TitleNode]:
    """把树平铺成按 char_offset 排序的列表。"""
    result = []

    def _walk(nodes, ancestors):
        for n in nodes:
            n.ancestors = ancestors[:]
            result.append(n)
            _walk(n.children or [], ancestors + [n])

    _walk(tree, [])
    return sorted(result, key=lambda n: n.char_offset)


def _title_path_at_offset(titles: list[TitleNode], offset: int) -> Optional[str]:
    """找 offset 之前最近的 title，拼接祖先链。"""
    last = None
    for t in titles:
        if t.char_offset <= offset:
            last = t
        else:
            break
    if last is None:
        return None
    chain = [t.text for t in last.ancestors] + [last.text]
    return " > ".join(chain)


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def _split_paragraph(text: str) -> list[tuple[str, bool]]:
    """单段 → list[(chunk_text, is_truncated)]，按句号 → 硬切。"""
    if len(text) <= MAX_CHARS:
        return [(text, False)]

    sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s]
    out: list[tuple[str, bool]] = []
    buf = ""
    for sent in sentences:
        if len(sent) > MAX_CHARS:
            if buf:
                out.append((buf, False))
                buf = ""
            for piece in _hard_split(sent, MAX_CHARS):
                out.append((piece, True))
        elif len(buf) + len(sent) <= MAX_CHARS:
            buf += sent
        else:
            if buf:
                out.append((buf, False))
            buf = sent
    if buf:
        out.append((buf, False))
    return out


def split_document(
    parse_result: ParseResult,
    *,
    file_path: str,
    file_hash: str,
    index_version: str,
) -> list[Chunk]:
    """三级 fallback 切分。"""
    raw = parse_result.raw_text
    titles = _flatten_titles(parse_result.title_tree or [])

    # 第 1 级：按段落 \n\n 切分
    paragraphs = raw.split("\n\n")

    chunks: list[Chunk] = []
    cursor = 0
    chunk_index = 0

    for para in paragraphs:
        if not para.strip():
            cursor += len(para) + 2
            continue

        for piece, is_truncated in _split_paragraph(para):
            if not piece:
                continue
            offset = raw.find(piece, cursor) if piece in raw[cursor:] else cursor
            title_path = _title_path_at_offset(titles, offset)
            chunk_id = _make_chunk_id(file_path, chunk_index, piece)
            chunks.append(Chunk(
                chunk_id=chunk_id,
                file_path=file_path,
                file_hash=file_hash,
                index_version=index_version,
                content=piece,
                anchor_id=f"{file_path}#{offset}",
                title_path=title_path,
                char_offset_start=offset,
                char_offset_end=offset + len(piece),
                char_count=len(piece),
                chunk_index=chunk_index,
                is_truncated=is_truncated,
                content_type="document",
                language=parse_result.language,
            ))
            chunk_index += 1
            cursor = offset + len(piece)

        cursor += 2  # 跳过 \n\n

    # 过滤过短 chunk（除非 is_truncated）
    chunks = [c for c in chunks if c.char_count >= MIN_CHARS or c.is_truncated]
    # 重新编号 chunk_index
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.chunk_id = _make_chunk_id(file_path, i, c.content)

    from backend.ingestion.chunker.overlap import apply_overlap
    chunks = apply_overlap(chunks)
    return chunks
