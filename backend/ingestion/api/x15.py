"""X1.5 search 接口 section 全量化辅助函数。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md
"""
import functools
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RAW_DIR = Path("backend/storage/raw")
DEFAULT_MAX_CHARS = 2000


@functools.lru_cache(maxsize=200)
def _read_raw_file(file_path: str) -> str:
    """读源 markdown 文件，CRLF 归一化（跟 chunker 入口一致）。

    file_path 是 DB 里存的相对路径（不含 raw/ 前缀）。
    LRU 缓存上限 200，覆盖当前 164 文件且对未来扩到 10K+ 文件也稳定（自动淘汰冷文件）。
    测试 fixture 必须显式调 _read_raw_file.cache_clear() 防跨测污染。
    """
    abs_path = RAW_DIR / file_path
    text = abs_path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


# 进程级 section 边界缓存（key 不能用 conn，所以单独 dict）
# section 总数 ~1600，全装内存可忽略；测试 fixture 显式 clear
_section_range_cache: dict[tuple[str, str], tuple[int, int]] = {}


def get_section_full_range(conn, file_path: str, title_path: str) -> tuple[int, int]:
    """查同 section 全部 chunks（含未命中的）的 offset union 范围。

    关键设计点：必须查全部 chunks 的 union，不能只看召回的命中。
    否则 section 内只有 1 个 chunk 被命中时，"section 全量" 退化成单 chunk 大小。
    """
    cache_key = (file_path, title_path or "")
    if cache_key in _section_range_cache:
        return _section_range_cache[cache_key]

    row = conn.execute(
        """SELECT MIN(char_offset_start) AS s, MAX(char_offset_end) AS e
           FROM chunks
           WHERE file_path = ?
             AND COALESCE(title_path, '') = COALESCE(?, '')""",
        (file_path, title_path or ""),
    ).fetchone()
    if row is None or row["s"] is None:
        raise ValueError(f"no chunks for ({file_path}, {title_path!r})")

    result = (row["s"], row["e"])
    _section_range_cache[cache_key] = result
    return result


def clear_section_range_cache():
    """测试用，清空 section 边界缓存。"""
    _section_range_cache.clear()


def make_window(
    section_start: int,
    section_end: int,
    hits: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[int, int, bool]:
    """居中截窗口算法。返回 (win_start, win_end, is_truncated)。

    3 档策略：
    - Case 1: section 长度 ≤ max_chars → 整 section 全保
    - Case 2: 命中点 union 跨度 ≤ max_chars → 命中点 union 居中
    - Case 3: 命中点跨度 > max_chars → 取分最高命中点居中（罕见）

    边界回弹：window 撞 section 边界时把空间补给另一边，保证 win_end - win_start = max_chars。
    """
    section_len = section_end - section_start
    if section_len <= max_chars:
        return section_start, section_end, False  # Case 1

    hit_min = min(h["char_offset_start"] for h in hits)
    hit_max = max(h["char_offset_end"] for h in hits)

    if hit_max - hit_min <= max_chars:
        # Case 2: 命中点 union 装得下
        center = (hit_min + hit_max) // 2
    else:
        # Case 3: 跨度过大，按最高分居中
        top_hit = max(hits, key=lambda h: h.get("score", 0))
        center = (top_hit["char_offset_start"] + top_hit["char_offset_end"]) // 2

    half = max_chars // 2
    win_start = max(section_start, center - half)
    win_end = min(section_end, center + half)

    # 边界回弹：一边碰壁就把空间补给另一边
    if win_end - win_start < max_chars:
        if win_start == section_start:
            win_end = min(section_end, win_start + max_chars)
        else:
            win_start = max(section_start, win_end - max_chars)

    return win_start, win_end, True


GroupKey = tuple  # ('SINGLE', chunk_id) 或 ('SECTION', file_path, title_path)


def assign_group_key(chunk: dict) -> GroupKey:
    """决定 chunk 属于 SINGLE 还是 SECTION 路径。

    title_path 空 ≡ markdown_anchor=#top（数据验证 100% 对应），走 SINGLE 退化避免跨文件误并。
    """
    title_path = chunk.get("title_path") or ""
    if not title_path:
        return ("SINGLE", chunk["chunk_id"])
    return ("SECTION", chunk["file_path"], title_path)


def group_results(results: list[dict]) -> dict[GroupKey, list[dict]]:
    """把 search 返回的 rows 按 group_key 分组，组内按 score 降序排。

    输出顺序由调用方按"组内最高分"再排（这里只做分组）。
    """
    groups: dict[GroupKey, list[dict]] = defaultdict(list)
    for r in results:
        groups[assign_group_key(r)].append(r)
    for k in groups:
        groups[k].sort(key=lambda c: -c.get("score", 0))
    return groups


def _format_result_x15(
    conn,
    group_chunks: list[dict],
    title_path: str,
    metadata_x0: dict,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict:
    """X1.5 化主函数。每组返回 1 个 result。

    Args:
        conn: SQLite connection（用于 get_section_full_range）
        group_chunks: 已按 score 降序的命中 chunks
        title_path: SECTION 路径的标题路径；'' 触发 SINGLE 退化
        metadata_x0: 由调用方用 _row_to_metadata(group_chunks[0]) 算好传入

    Returns:
        result dict 含 chunk_id / content / score / metadata
    """
    representative = group_chunks[0]

    if not title_path:
        # SINGLE 退化路径：原 chunk content，metadata 不变
        return {
            "chunk_id": representative["chunk_id"],
            "content": representative["content"],
            "score": representative.get("score", 0.0),
            "metadata": metadata_x0,
        }

    # SECTION 合并路径
    file_path = representative["file_path"]
    try:
        section_start, section_end = get_section_full_range(conn, file_path, title_path)
        win_start, win_end, is_truncated = make_window(
            section_start, section_end, group_chunks, max_chars=max_chars
        )
        raw_slice = _read_raw_file(file_path)[win_start:win_end]
        if not raw_slice.strip():
            raise ValueError("empty raw_slice")
        content = f"{title_path}\n\n{raw_slice}"
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as e:
        logger.warning(
            "x15 fallback for %s (title=%s): %s", file_path, title_path, e
        )
        # 退回 X0 行为：单 chunk 原 content，metadata 不变
        return {
            "chunk_id": representative["chunk_id"],
            "content": representative["content"],
            "score": representative.get("score", 0.0),
            "metadata": metadata_x0,
        }

    # X1.5 成功路径：metadata 跟着 content 走
    metadata = dict(metadata_x0)
    metadata["is_x15_truncated"] = is_truncated
    metadata["char_offset_start"] = win_start
    metadata["char_offset_end"] = win_end
    metadata["anchor_id"] = f"{file_path}#{win_start}"
    return {
        "chunk_id": representative["chunk_id"],
        "content": content,
        "score": representative.get("score", 0.0),
        "metadata": metadata,
    }
