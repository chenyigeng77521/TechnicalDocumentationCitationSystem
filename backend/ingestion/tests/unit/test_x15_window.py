"""make_window 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.2
"""
import pytest
from backend.ingestion.api.x15 import make_window


def _hit(start, end, score=0.5):
    return {"char_offset_start": start, "char_offset_end": end, "score": score}


# 测什么行为：section 长度 < max_chars 时整 section 全保，不截
# 输入：section [0, 500]，命中 chunk [100, 200]，max_chars=2000
# 期望：返回 (0, 500, False)，is_truncated 为 False
# 为什么必须测：这是 Case 1 主路径，70% 真实 section 走这条路（数据：1598 sections P50=1278 < 2000）
def test_short_section_no_truncate():
    s, e, t = make_window(0, 500, [_hit(100, 200)], max_chars=2000)
    assert (s, e, t) == (0, 500, False)


# 测什么行为：section 长度恰好等于 max_chars 时也走 Case 1（不截）
# 输入：section [0, 2000]，max_chars=2000
# 期望：(0, 2000, False)
# 为什么必须测：边界值 == 容易写成 < 漏掉等号
def test_section_equal_max_chars():
    s, e, t = make_window(0, 2000, [_hit(500, 600)], max_chars=2000)
    assert (s, e, t) == (0, 2000, False)


# 测什么行为：长 section + 单点命中，命中点居中切 max_chars 窗口
# 输入：section [0, 5000]，命中 [2400, 2600] (中点 2500)，max_chars=2000
# 期望：window [1500, 3500]，is_truncated=True
# 为什么必须测：Case 2 主路径，覆盖大部分需要截断的 section
def test_long_section_single_hit_center():
    s, e, t = make_window(0, 5000, [_hit(2400, 2600)], max_chars=2000)
    assert (s, e, t) == (1500, 3500, True)


# 测什么行为：多个命中点 union 装得下 max_chars 时按 union 居中
# 输入：section [0, 5000]，命中 [1500, 1600] 和 [2400, 2500]，union [1500, 2500] 跨度 1000
# 期望：union 中点 = 2000，window [1000, 3000]
# 为什么必须测：Case 2 多命中场景
def test_case2_hit_union_center():
    s, e, t = make_window(
        0, 5000,
        [_hit(1500, 1600, 0.9), _hit(2400, 2500, 0.7)],
        max_chars=2000,
    )
    assert (s, e, t) == (1000, 3000, True)


# 测什么行为：命中点跨度 > max_chars 时退回 Case 3 用最高分居中
# 输入：section [0, 10000]，命中 [500, 600] (score 0.9) 和 [8000, 8100] (score 0.7)，跨度 7600 > 2000
# 期望：以 max_score 命中点 [500, 600] 中点 550 居中 → 左碰壁回弹到 [0, 2000]
# 为什么必须测：Case 3 罕见但必须正确
def test_case3_max_score_center():
    s, e, t = make_window(
        0, 10000,
        [_hit(500, 600, 0.9), _hit(8000, 8100, 0.7)],
        max_chars=2000,
    )
    assert (s, e, t) == (0, 2000, True)


# 测什么行为：命中点靠近 section 起点时左边回弹
# 输入：section [0, 5000]，命中 [100, 200]（中点 150），max_chars=2000
# 期望：本应 [-850, 1150]，左碰 0 → 回弹 [0, 2000]
# 为什么必须测：边界 case
def test_boundary_rebound_left():
    s, e, t = make_window(0, 5000, [_hit(100, 200)], max_chars=2000)
    assert (s, e, t) == (0, 2000, True)


# 测什么行为：命中点靠近 section 末尾时右边回弹
# 输入：section [0, 5000]，命中 [4800, 4900] (中点 4850)，max_chars=2000
# 期望：本应 [3850, 5850]，右碰 5000 → 回弹 [3000, 5000]
# 为什么必须测：边界 case 对称
def test_boundary_rebound_right():
    s, e, t = make_window(0, 5000, [_hit(4800, 4900)], max_chars=2000)
    assert (s, e, t) == (3000, 5000, True)


# 测什么行为：is_truncated 标记跟实际是否截断一致
# 输入：两个 case，一截一不截
# 期望：短 section is_truncated=False，长 section True
# 为什么必须测：metadata.is_x15_truncated 字段值依赖这个 flag
def test_is_truncated_flag():
    _, _, t1 = make_window(0, 500, [_hit(100, 200)], max_chars=2000)
    _, _, t2 = make_window(0, 5000, [_hit(2400, 2600)], max_chars=2000)
    assert t1 is False
    assert t2 is True
