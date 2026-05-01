"""分组逻辑单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.1
"""
from backend.ingestion.api.x15 import assign_group_key, group_results


def _chunk(chunk_id, file_path, title_path, score, chunk_index=0):
    return {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "title_path": title_path,
        "score": score,
        "chunk_index": chunk_index,
    }


# 测什么行为：同 (file_path, title_path) 的 chunks 合并到 1 组
# 输入：3 个 chunks 同 file 同 title
# 期望：groups 长度 = 1，组内 3 个 chunks
# 为什么必须测：核心合并行为，spec §2.1 主路径
def test_section_path_merge():
    chunks = [
        _chunk("a", "k.md", "X/Y", 0.9, 1),
        _chunk("b", "k.md", "X/Y", 0.7, 2),
        _chunk("c", "k.md", "X/Y", 0.5, 3),
    ]
    g = group_results(chunks)
    assert len(g) == 1
    key = ("SECTION", "k.md", "X/Y")
    assert key in g
    assert len(g[key]) == 3


# 测什么行为：title_path 空走 UNTITLED 路径，assign_group_key 返回 ("UNTITLED", file_path)
# 输入：title_path=""
# 期望：group_key 是 ('UNTITLED', file_path)
# 为什么必须测：避免跨文件误并基础（4% chunks 走这路径）
def test_empty_title_to_untitled():
    chunk = _chunk("c1", "k.md", "", 0.5)
    assert assign_group_key(chunk) == ("UNTITLED", "k.md")


# 测什么行为：title_path 为 None 时也走 UNTITLED 路径
def test_none_title_to_untitled():
    chunk = _chunk("c2", "k.md", None, 0.5)
    assert assign_group_key(chunk) == ("UNTITLED", "k.md")


# 测什么行为：results 为空时返回空 dict
# 输入：[]
# 期望：{}
# 为什么必须测：避免函数 crash 在边界值
def test_empty_results():
    assert group_results([]) == {}


# 测什么行为：不同 file_path 的同 title_path chunks 不合并
def test_different_files_not_merged():
    chunks = [
        _chunk("a", "a.md", "X", 0.9, 1),
        _chunk("b", "b.md", "X", 0.7, 1),
    ]
    g = group_results(chunks)
    assert len(g) == 2


# 测什么行为：同 file 不同 title 不合并
def test_same_file_diff_title_not_merged():
    chunks = [
        _chunk("a", "k.md", "X", 0.9, 1),
        _chunk("b", "k.md", "Y", 0.7, 5),
    ]
    g = group_results(chunks)
    assert len(g) == 2


# 测什么行为：组内 chunks 按 score 降序排
# 输入：score=[0.3, 0.9, 0.5] 同 group
# 期望：组内顺序 [0.9, 0.5, 0.3]
# 为什么必须测：spec §2.5 _format_result_x15 取 group_chunks[0] 作为 representative，必须是分最高的
def test_group_sorted_by_score_desc():
    chunks = [
        _chunk("a", "k.md", "X", 0.3, 1),
        _chunk("b", "k.md", "X", 0.9, 2),
        _chunk("c", "k.md", "X", 0.5, 3),
    ]
    g = group_results(chunks)
    members = g[("SECTION", "k.md", "X")]
    assert [m["score"] for m in members] == [0.9, 0.5, 0.3]


# 测什么行为：UNTITLED chunks 同 file_path 内按 chunk_index 物理连续切段
# 输入：同 file 4 个 UNTITLED chunks，chunk_index = [0, 1, 2, 33]（前 3 连续，第 4 跳跃）
# 期望：切成 2 个 UNTITLED_SEG 段：[0,1,2] 和 [33]
# 为什么必须测：fix Task 8 的核心改动，避免跨文件位置误并（数据：46% #top 组不连续）
def test_untitled_chunks_split_by_chunk_index_segments():
    chunks = [
        _chunk("a", "k.md", "", 0.9, 0),
        _chunk("b", "k.md", "", 0.8, 1),
        _chunk("c", "k.md", "", 0.7, 2),
        _chunk("d", "k.md", "", 0.6, 33),  # 跳跃，不连续
    ]
    g = group_results(chunks)
    # 应该切成 2 段
    untitled_keys = [k for k in g.keys() if k[0] == "UNTITLED_SEG"]
    assert len(untitled_keys) == 2

    # 第一段 [a, b, c]，第二段 [d]
    sizes = sorted([len(g[k]) for k in untitled_keys])
    assert sizes == [1, 3]


# 测什么行为：UNTITLED 段内 chunks 按 score 降序
def test_untitled_seg_sorted_by_score():
    chunks = [
        _chunk("a", "k.md", "", 0.3, 0),
        _chunk("b", "k.md", "", 0.9, 1),
        _chunk("c", "k.md", "", 0.5, 2),
    ]
    g = group_results(chunks)
    untitled_keys = [k for k in g.keys() if k[0] == "UNTITLED_SEG"]
    assert len(untitled_keys) == 1
    members = g[untitled_keys[0]]
    assert [m["score"] for m in members] == [0.9, 0.5, 0.3]
