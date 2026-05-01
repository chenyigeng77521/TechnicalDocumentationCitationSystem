"""文件级 asyncio 锁池。"""
import asyncio
from contextlib import asynccontextmanager

_locks: dict[str, asyncio.Lock] = {}
_lock_creation_lock = asyncio.Lock()


async def _get_lock(file_path: str) -> asyncio.Lock:
    async with _lock_creation_lock:
        if file_path not in _locks:
            _locks[file_path] = asyncio.Lock()
        return _locks[file_path]


@asynccontextmanager
async def file_lock(file_path: str):
    lock = await _get_lock(file_path)
    async with lock:
        yield
