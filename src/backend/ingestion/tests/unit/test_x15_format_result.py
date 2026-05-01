"""_format_result_x15 单元测试。

Spec: docs/superpowers/specs/2026-04-30-x15-rigorous-design.md §2.5
"""
import pytest
from pathlib import Path
from backend.ingestion.api.x15 import (
    _format_result_x15,
    _read_raw_file,
    clear_section_range_cache,
)
from backend.ingestion.api import x15
from backend.ingestion.db.connection import get_connection
from backend.ingestion.api.routes_search import _row_to_metadata

DB_PATH = Path(__file__).parents[4] / "backend/storage/index/knowledge.db"
_RAW_DIR_ABS = Path(__file__).parents[4] / "backend" / "storage" / "raw"


@pytest.fixture(autouse=True)
def patch_raw_dir(monkeypatch):
    """将 x15.RAW_DIR 替换为绝对路径，避免 CWD 依赖。"""
    monkeypatch.setattr(x15, "RAW_DIR", _RAW_DIR_ABS)


@pytest.fixture(autouse=True)
def reset_caches():
    _read_raw_file.cache_clear()
    clear_section_range_cache()
    yield
    _read_raw_file.cache_clear()
    clear_section_range_cache()


@pytest.fixture
def conn():
    c = get_connection(DB_PATH)
    yield c
    c.close()


def _real_section_chunk(conn):
    """从 DB 拿一个真实有 title_path 的 chunk。"""
    return dict(conn.execute(
        """SELECT * FROM chunks
        WHERE title_path IS NOT NULL AND title_path != ''
        LIMIT 1"""
    ).fetchone())


# 测什么行为：SECTION 路径返回 content = title_path + raw_slice
# 输入：真实 chunk + 它的 title_path
# 期望：content 含 title_path 字符串，长度 >= 单 chunk 长度
# 为什么必须测：核心 X1.5 行为
def test_section_path_with_title_and_window(conn):
    chunk = _real_section_chunk(conn)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], chunk["title_path"], metadata_x0)
    assert chunk["title_path"] in result["content"]
    assert len(result["content"]) >= len(chunk["content"])


# 测什么行为：UNTITLED 路径不加 title prefix（content 不含 title_path）
# 输入：title_path=""
# 期望：result content 不含 title_path（因为没有），但走 X1.5 化路径
# 为什么必须测：UNTITLED 路径独立处理（fix Task 8）
def test_untitled_path_no_title_prefix(conn):
    row = conn.execute("""SELECT * FROM chunks
        WHERE title_path IS NULL OR title_path = '' LIMIT 1""").fetchone()
    if row is None:
        pytest.skip("no UNTITLED chunks in DB")
    chunk = dict(row)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], "", metadata_x0)
    # UNTITLED 路径用 group offset union 切片
    # content 应该是 raw_slice 不带 title prefix
    assert not result["content"].startswith("\n\n")  # 没有空 title 后接 \n\n


# 测什么行为：源文件不存在时 fallback 退回单 chunk content
# 输入：fake chunk file_path 不存在
# 期望：result content == chunk content（X0 行为）
# 为什么必须测：保 API 永不挂的核心契约
def test_fallback_on_missing_file(conn):
    fake_chunk = {
        "chunk_id": "fake_chunk_id",
        "file_path": "DOES_NOT_EXIST.md",
        "title_path": "Some/Title",
        "char_offset_start": 0,
        "char_offset_end": 100,
        "score": 0.5,
        "content": "fake original content",
        "chunk_index": 0,
    }
    metadata_fake = {"file_path": "DOES_NOT_EXIST.md", "is_x15_truncated": False}
    result = _format_result_x15(conn, [fake_chunk], "Some/Title", metadata_fake)
    assert result["content"] == "fake original content"


# 测什么行为：section 边界查不到时 fallback
# 输入：title_path 不存在于 DB
# 期望：fallback 退回单 chunk content
# 为什么必须测：DB drift 防御
def test_fallback_on_no_section(conn):
    # 用真实文件 + 不存在的 title_path → get_section_full_range 抛 ValueError
    real_file = "add-react-to-an-existing-project.md"
    chunk = {
        "chunk_id": "x", "file_path": real_file,
        "title_path": "NOT_EXIST_TITLE_xyz",
        "char_offset_start": 0, "char_offset_end": 100, "score": 0.5,
        "content": "original", "chunk_index": 0,
    }
    metadata_x0 = {"file_path": real_file, "is_x15_truncated": False}
    result = _format_result_x15(conn, [chunk], "NOT_EXIST_TITLE_xyz", metadata_x0)
    assert result["content"] == "original"


# 测什么行为：raw_slice 空白时 fallback（mock get_section_full_range 返回越界）
def test_fallback_on_empty_slice(conn, monkeypatch):
    def fake_range(conn_arg, fp, tp):
        return (99999999, 100000000)
    monkeypatch.setattr(x15, "get_section_full_range", fake_range)
    chunk = {
        "chunk_id": "x", "file_path": "add-react-to-an-existing-project.md",
        "title_path": "XX", "char_offset_start": 99999999, "char_offset_end": 100000000,
        "score": 0.5, "content": "original", "chunk_index": 0,
    }
    result = _format_result_x15(conn, [chunk], "XX", {"is_x15_truncated": False})
    assert result["content"] == "original"


# 测什么行为：X1.5 路径下 metadata.is_x15_truncated 反映实际是否截断
# 输入：长 section（已知 > 2000 字符）
# 期望：is_x15_truncated=True
# 为什么必须测：metadata 字段语义对外 contract
def test_metadata_is_x15_truncated_set(conn):
    row = conn.execute("""
        SELECT file_path, title_path, MAX(char_offset_end)-MIN(char_offset_start) AS span
        FROM chunks
        WHERE title_path IS NOT NULL AND title_path != ''
        GROUP BY file_path, title_path
        HAVING span > 2500
        LIMIT 1
    """).fetchone()
    if row is None:
        pytest.skip("no long section in DB")
    long_chunk = dict(conn.execute(
        "SELECT * FROM chunks WHERE file_path=? AND title_path=? LIMIT 1",
        (row["file_path"], row["title_path"])
    ).fetchone())
    metadata_x0 = _row_to_metadata(long_chunk)
    result = _format_result_x15(conn, [long_chunk], row["title_path"], metadata_x0)
    assert result["metadata"]["is_x15_truncated"] is True


# 测什么行为：X1.5 路径下 char_offset_start/end + anchor_id 跟随 window 范围
# 输入：长 section 命中
# 期望：metadata.anchor_id == f"{file_path}#{char_offset_start}"
# 为什么必须测：spec §3 字段契约
def test_metadata_offset_follows_window(conn):
    chunk = _real_section_chunk(conn)
    metadata_x0 = _row_to_metadata(chunk)
    result = _format_result_x15(conn, [chunk], chunk["title_path"], metadata_x0)
    md = result["metadata"]
    expected_anchor = f"{chunk['file_path']}#{md['char_offset_start']}"
    assert md["anchor_id"] == expected_anchor


# 测什么行为：组内多 chunks 时 chunk_id 是 score 最高那个的真 DB 主键（group_chunks[0]）
# 输入：3 chunks 已按 score 降序，group_chunks[0]="winner"
# 期望：result["chunk_id"] == "winner"
# 为什么必须测：spec §1.1a chunk_id 契约
def test_chunk_id_is_max_score_representative(conn):
    members = [
        {"chunk_id": "winner", "file_path": "add-react-to-an-existing-project.md",
         "title_path": "X", "char_offset_start": 100, "char_offset_end": 200,
         "score": 0.9, "content": "high", "chunk_index": 0},
        {"chunk_id": "loser", "file_path": "add-react-to-an-existing-project.md",
         "title_path": "X", "char_offset_start": 300, "char_offset_end": 400,
         "score": 0.5, "content": "low", "chunk_index": 1},
    ]
    metadata_fake = {"file_path": "add-react-to-an-existing-project.md", "is_x15_truncated": False}
    result = _format_result_x15(conn, members, "X", metadata_fake)
    # 即使 fallback（title 不存在），chunk_id 仍取 group_chunks[0]
    assert result["chunk_id"] == "winner"
