import re
from dataclasses import dataclass, field
from typing import Any

TARGET_MIN = 100
TARGET_MAX = 800
HARD_MAX = 1000
HEADING_RE = re.compile(r"^(#{1,6})\s+.+$")
CODE_FENCE_RE = re.compile(r"^```")


@dataclass
class Chunk:
    content: str
    start_line: int
    end_line: int
    original_lines: list[int] = field(default_factory=list)


def chunk_markdown(md: str, line_map: dict[int, Any]) -> list[Chunk]:
    if not md.strip():
        return []

    blocks = _split_blocks_preserving_code(md)
    merged = _merge_short(blocks)
    chunks: list[Chunk] = []
    for block in merged:
        chunks.extend(_split_long_block(block))
    return [c for c in chunks if _has_real_content(c.content)]


def _split_blocks_preserving_code(md: str) -> list[Chunk]:
    lines = md.splitlines()
    blocks: list[Chunk] = []
    buf: list[str] = []
    buf_start = 0
    in_code = False

    def flush(end_line: int) -> None:
        if buf:
            content = "\n".join(buf).strip()
            if content:
                blocks.append(Chunk(content=content, start_line=buf_start + 1, end_line=end_line))
        buf.clear()

    for i, line in enumerate(lines):
        if CODE_FENCE_RE.match(line):
            if not in_code:
                flush(i)
                buf_start = i
                buf.append(line)
                in_code = True
            else:
                buf.append(line)
                flush(i + 1)
                in_code = False
            continue

        if in_code:
            buf.append(line)
            continue

        if HEADING_RE.match(line):
            flush(i)
            buf_start = i
            buf.append(line)
            flush(i + 1)
            continue

        if not line.strip():
            flush(i)
            buf_start = i + 1
            continue

        if not buf:
            buf_start = i
        buf.append(line)

    flush(len(lines))
    return blocks


def _merge_short(blocks: list[Chunk]) -> list[Chunk]:
    if not blocks:
        return []
    out: list[Chunk] = [blocks[0]]
    for b in blocks[1:]:
        prev_is_heading = bool(HEADING_RE.match(out[-1].content.strip()))
        cur_is_heading = bool(HEADING_RE.match(b.content.strip()))
        can_merge = (
            len(out[-1].content) < TARGET_MIN
            and not prev_is_heading
            and not cur_is_heading
            and len(out[-1].content) + len(b.content) + 2 <= HARD_MAX
        )
        if can_merge:
            out[-1] = Chunk(
                content=out[-1].content + "\n\n" + b.content,
                start_line=out[-1].start_line,
                end_line=b.end_line,
            )
        else:
            out.append(b)
    return out


def _split_long_block(block: Chunk) -> list[Chunk]:
    if len(block.content) <= HARD_MAX:
        return [block]
    pieces: list[str] = []
    cur = ""
    for sent in re.split(r"(?<=[。！？.!?])", block.content):
        if len(cur) + len(sent) > HARD_MAX and cur:
            pieces.append(cur.strip())
            cur = sent
        else:
            cur += sent
    if cur.strip():
        pieces.append(cur.strip())
    return [
        Chunk(content=p, start_line=block.start_line, end_line=block.end_line)
        for p in pieces if p
    ]


def _has_real_content(content: str) -> bool:
    """单独的标题行不算可检索；但带其他文字或长度 > 20 字符则保留。"""
    non_heading_lines = [l for l in content.splitlines() if not HEADING_RE.match(l.strip())]
    non_heading = "\n".join(non_heading_lines).strip()
    return bool(non_heading) or len(content) > 20
