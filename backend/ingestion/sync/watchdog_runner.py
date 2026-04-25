"""路径 B：watchdog 监听 raw/ 目录，debounce 1s 后触发 pipeline。

Spec: docs/superpowers/specs/2026-04-25-data-layer-design.md §10
"""
import asyncio
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from backend.ingestion.common.logger import get_logger

logger = get_logger("ingestion.watchdog")


class RawDirHandler(FileSystemEventHandler):
    """监听 raw/ 目录变化，debounce 后调对应 pipeline。"""

    def __init__(
        self,
        raw_dir: Path,
        debounce_seconds: float = 1.0,
        on_index: Optional[Callable[[str], Awaitable]] = None,
        on_delete: Optional[Callable[[str], Awaitable]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.raw_dir = Path(raw_dir).resolve()
        self.debounce = debounce_seconds
        self.on_index = on_index
        self.on_delete = on_delete
        self.loop = loop or asyncio.get_event_loop()
        self._pending: dict[str, tuple[float, str]] = {}

    def _make_relative(self, abs_path: str) -> str:
        try:
            return str(Path(abs_path).resolve().relative_to(self.raw_dir))
        except ValueError:
            return abs_path

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "create_or_modify")

    def on_deleted(self, event):
        if not event.is_directory:
            self._schedule(event.src_path, "delete")

    def _schedule(self, abs_path: str, action: str) -> None:
        self._pending[abs_path] = (time.time(), action)
        self.loop.call_later(
            self.debounce + 0.05,
            lambda: asyncio.ensure_future(self._fire_if_settled(abs_path)),
        )

    async def _fire_if_settled(self, abs_path: str) -> None:
        entry = self._pending.get(abs_path)
        if entry is None:
            return
        last_time, action = entry
        if time.time() - last_time < self.debounce:
            return
        del self._pending[abs_path]
        rel = self._make_relative(abs_path)
        try:
            if action == "delete" and self.on_delete:
                await self.on_delete(rel)
            elif self.on_index:
                await self.on_index(rel)
        except Exception as e:
            logger.error("watchdog fire failed", extra={
                "path": rel, "action": action, "error": str(e),
            })


def start_observer(raw_dir: Path, on_index, on_delete) -> Observer:
    """启动 observer 并返回（调用方负责 .stop() / .join()）。"""
    handler = RawDirHandler(
        raw_dir=raw_dir,
        on_index=on_index,
        on_delete=on_delete,
        loop=asyncio.get_event_loop(),
    )
    observer = Observer()
    observer.schedule(handler, str(raw_dir), recursive=True)
    observer.start()
    return observer
