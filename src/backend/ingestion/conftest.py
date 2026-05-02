"""pytest 共享 fixture。"""
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """临时 SQLite 文件，每个测试独立。"""
    return tmp_path / "test_knowledge.db"


@pytest.fixture
def tmp_raw_dir(tmp_path):
    """临时 storage/ 根目录，模拟 backend/storage/。

    历史命名沿用：值已改成 storage 根（不再是 raw/ 子目录），但 fixture 名保留
    以兼容现有测试。新 file_path 约定形如 ``docs/<domain>/<basename>``，相对此目录。
    """
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture
def fixtures_dir():
    """tests/fixtures/ 绝对路径。"""
    return Path(__file__).parent / "tests" / "fixtures"
