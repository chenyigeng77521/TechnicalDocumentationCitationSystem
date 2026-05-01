"""_read_raw_file 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.4
"""
from pathlib import Path

import pytest
from backend.ingestion.api.x15 import _read_raw_file
from backend.ingestion.api import x15

# 真实 raw 目录绝对路径（pytest 从 backend/ingestion/ 跑，相对路径不可用）
_RAW_DIR_ABS = Path(__file__).parents[4] / "backend" / "storage" / "raw"


@pytest.fixture(autouse=True)
def clear_cache():
    """每个测试前后清缓存，防跨测污染。"""
    _read_raw_file.cache_clear()
    yield
    _read_raw_file.cache_clear()


@pytest.fixture(autouse=True)
def patch_raw_dir(monkeypatch):
    """将 x15.RAW_DIR 替换为绝对路径，避免 CWD 依赖。"""
    monkeypatch.setattr(x15, "RAW_DIR", _RAW_DIR_ABS)


# 测什么行为：能读真实存在的 markdown 文件
# 输入：当前语料里任一平铺文件名（DB file_path 平铺，无子目录）
# 期望：返回非空字符串
# 为什么必须测：核心读文件能力
def test_read_real_file():
    text = _read_raw_file("add-react-to-an-existing-project.md")
    assert isinstance(text, str)
    assert len(text) > 0


# 测什么行为：文件不存在时抛 FileNotFoundError（让 _format_result_x15 catch 走 fallback）
# 输入：不存在的 file_path
# 期望：raise FileNotFoundError
# 为什么必须测：fallback 路径依赖这个异常
def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        _read_raw_file("DOES_NOT_EXIST.md")


# 测什么行为：第二次读同文件命中缓存（不再调 read_text）
# 输入：连续两次读
# 期望：cache_info hits 增加
# 为什么必须测：避免性能回归（缓存失效会让单 query 30 次重复 IO）
def test_cache_hit():
    _read_raw_file("add-react-to-an-existing-project.md")
    info1 = _read_raw_file.cache_info()
    _read_raw_file("add-react-to-an-existing-project.md")
    info2 = _read_raw_file.cache_info()
    assert info2.hits == info1.hits + 1


# 测什么行为：cache_clear 后重新读会触发 miss
# 输入：read → clear → read
# 期望：第二次 misses 增加
# 为什么必须测：测试 fixture 用 cache_clear 隔离测试，必须可靠
def test_cache_clear():
    _read_raw_file("add-react-to-an-existing-project.md")
    _read_raw_file.cache_clear()
    info_before = _read_raw_file.cache_info()
    _read_raw_file("add-react-to-an-existing-project.md")
    info_after = _read_raw_file.cache_info()
    assert info_after.misses == info_before.misses + 1


# 测什么行为：CRLF (\r\n) 和单独 \r 都被归一化成 \n
# 输入：tmp_path 下放一个含 \r\n 的文件，patch RAW_DIR 指向 tmp_path
# 期望：返回的字符串里没有 \r
# 为什么必须测：跟 chunker 入口一致是必要前提，否则 char_offset 算错位置
def test_crlf_normalized(tmp_path, monkeypatch):
    test_file = tmp_path / "test.md"
    test_file.write_bytes(b"line1\r\nline2\rline3\nline4")

    monkeypatch.setattr(x15, "RAW_DIR", tmp_path)
    _read_raw_file.cache_clear()

    text = _read_raw_file("test.md")
    assert "\r" not in text
    assert text == "line1\nline2\nline3\nline4"
