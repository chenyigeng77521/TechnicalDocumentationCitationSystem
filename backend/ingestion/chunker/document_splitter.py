"""document 类型三级 fallback 切分。

Spec: §7 chunk 切分策略
"""
import hashlib
import re
from typing import Optional
from backend.ingestion.chunker.types import Chunk
from backend.ingestion.chunker.quality_filter import filter_quality
from backend.ingestion.parser.types import ParseResult, TitleNode

MAX_CHARS = 1000
SENTENCE_END_RE = re.compile(r"[。！？.!?]")
# heading-only 段（如 "## Installation"），信息已在 title_tree，跳过避免 chunk 污染
HEADING_ONLY_RE = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)


def _is_heading_only(text: str) -> bool:
    """判断段落是否只含 markdown heading 行（一行或多行连续标题）。"""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    return all(HEADING_ONLY_RE.match(ln.strip()) for ln in lines)


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


def _anchor_at_offset(titles: list[TitleNode], offset: int) -> str:
    """找 offset 之前最近的 title，返回它的 anchor。

    如果 offset 在第一个 title 之前 / 没有 title / 最近 title 没填 anchor → 返回 #top。
    """
    last = None
    for t in titles:
        if t.char_offset <= offset:
            last = t
        else:
            break
    if last is None or last.anchor is None:
        return "#top"
    return last.anchor


def _is_list_marker_at(text: str, dot_pos: int) -> bool:
    """判断 text[dot_pos] 这个 '.' 是不是 markdown 列表标记的一部分。

    规则：
    - 必须是英文 '.'，中文 '。' 不需要保护（中文文档没有 '1. ' 列表语法）
    - dot_pos 所在行的行首到 dot_pos 之前必须是 \\s*\\d+（行首空白 + 纯数字）
    - dot_pos 后必须紧跟空白（' ' '\\t' '\\n'）或行尾——防 'Python 3.12.' 这种伪列表被错保护

    例:
    - '1. The Pod' 中的 '.' (pos=1) → True (line_prefix='1', after=' ')
    - 'Python 3.12.' 中的 '.' (pos=11) → False (line_prefix='Python 3.12'，不匹配 \\d+$)
    - '   3. Item' 中的 '.' (pos=4) → True (line_prefix='   3', after=' ')
    """
    if dot_pos < 0 or dot_pos >= len(text) or text[dot_pos] != '.':
        return False
    line_start = text.rfind('\n', 0, dot_pos) + 1
    line_prefix = text[line_start:dot_pos]
    if not re.match(r'^\s*\d+$', line_prefix):
        return False
    after = text[dot_pos + 1:dot_pos + 2]
    return after in (' ', '\t', '\n', '')


def _split_paragraph(text: str) -> list[tuple[str, bool]]:
    """单段 → list[(chunk_text, is_truncated)]。

    关键不变量：所有产出片段拼接 == 原文（一字不差）。
    实现：扫所有句末标点位置作为候选边界，按 MAX_CHARS 贪心切原文 substring。
    无可用边界时硬切并标记 is_truncated=True。
    """
    if len(text) <= MAX_CHARS:
        return [(text, False)]

    # 收集所有合法句末标点位置（过滤掉列表标记）
    candidates: list[int] = []
    for m in SENTENCE_END_RE.finditer(text):
        if _is_list_marker_at(text, m.start()):
            continue
        candidates.append(m.end())  # 边界 = 标点之后

    pieces: list[tuple[str, bool]] = []
    cursor = 0
    while cursor < len(text):
        target = cursor + MAX_CHARS
        # 找 cursor < c <= target 范围内最大的 c（贪心吃满 MAX_CHARS）
        boundary = None
        for c in candidates:
            if c <= cursor:
                continue
            if c > target:
                break
            boundary = c

        if boundary is None:
            # 无可用边界 → 硬切到 target
            end = min(cursor + MAX_CHARS, len(text))
            pieces.append((text[cursor:end], True))
            cursor = end
        else:
            pieces.append((text[cursor:boundary], False))
            cursor = boundary

    return pieces


def _para_fully_inside_comment(start: int, length: int, ranges: list[tuple[int, int]]) -> bool:
    """段落 [start, start+length) 是否**完全**在某个 HTML 注释 (s, e) 范围内。

    ranges 按 start 升序——线性扫早退出。

    设计：跨边界段（起点在注释内，但终点超出）**不算**完全在内——因为这种段
    通常是「英文注释 --> 中文段」混合（注释和中文之间没 \\n\\n 分隔），
    全跳会丢掉中文。组 A 范围内的折中：保留这种段（接受英文污染），
    P1 chunker D 的 block-aware 阶段再做更精细的段内注释剥离。
    """
    end = start + length
    for s, e in ranges:
        if s <= start and end <= e:
            return True
        if s > start:
            break
    return False


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
    comment_ranges = parse_result.comment_ranges or []

    # 第 1 级：按段落 \n\n 切分
    paragraphs = raw.split("\n\n")

    chunks: list[Chunk] = []
    cursor = 0
    chunk_index = 0

    for para in paragraphs:
        if not para.strip():
            cursor += len(para) + 2
            continue

        # 跳过 heading-only 段（标题信息已在 title_tree / title_path）
        if _is_heading_only(para):
            cursor += len(para) + 2
            continue

        # 跳过**完全**在 HTML 注释范围内的段（K8s 双语对照英文翻译源）
        # 跨边界段（起点在内但终点超出）保留——见 _para_fully_inside_comment 注释
        if _para_fully_inside_comment(cursor, len(para), comment_ranges):
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
                markdown_anchor=_anchor_at_offset(titles, offset),
            ))
            chunk_index += 1
            cursor = offset + len(piece)

        cursor += 2  # 跳过 \n\n

    # 质量过滤（太短 / 字母数字占比 / 同文档去重）
    chunks = filter_quality(chunks)
    # 重新编号 chunk_index + 重算 chunk_id
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.chunk_id = _make_chunk_id(file_path, i, c.content)

    # MVP: 不应用 overlap。
    # 三级 fallback 已按段落/句子边界切分，有自然分隔；apply_overlap 会让
    # content 含 overlap 后 char_offset_*/anchor_id 失真（前端跳转出错）。
    # overlap.py 保留，未来若发现 chunk 间语义断裂再启用并同步重算 anchor。
    return chunks
