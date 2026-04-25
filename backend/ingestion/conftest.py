"""pytest 共享 fixture。"""
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """临时 SQLite 文件，每个测试独立。"""
    return tmp_path / "test_knowledge.db"


@pytest.fixture
def tmp_raw_dir(tmp_path):
    """临时 raw/ 目录，模拟 backend/storage/raw/。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    return raw


@pytest.fixture
def fixtures_dir():
    """tests/fixtures/ 绝对路径。"""
    return Path(__file__).parent / "tests" / "fixtures"
