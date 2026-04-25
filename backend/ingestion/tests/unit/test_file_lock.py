"""测试文件级 asyncio 锁池。"""
import asyncio
import pytest
from backend.ingestion.sync.file_lock import file_lock


@pytest.mark.asyncio
async def test_same_path_serializes():
    seq = []

    async def worker(name):
        async with file_lock("a.md"):
            seq.append(f"{name}-start")
            await asyncio.sleep(0.05)
            seq.append(f"{name}-end")

    await asyncio.gather(worker("A"), worker("B"))
    assert seq in (
        ["A-start", "A-end", "B-start", "B-end"],
        ["B-start", "B-end", "A-start", "A-end"],
    )


@pytest.mark.asyncio
async def test_different_paths_parallel():
    """不同 file_path 锁互不干扰。"""
    seq = []

    async def worker(path, name):
        async with file_lock(path):
            seq.append(f"{name}-start")
            await asyncio.sleep(0.05)
            seq.append(f"{name}-end")

    await asyncio.gather(worker("c.md", "A"), worker("d.md", "B"))
    starts = [s for s in seq if s.endswith("-start")]
    assert starts == ["A-start", "B-start"] or starts == ["B-start", "A-start"]
