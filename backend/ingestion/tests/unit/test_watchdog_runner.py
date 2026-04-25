"""测试 watchdog observer + debounce。"""
import asyncio
from unittest.mock import AsyncMock
import pytest
from backend.ingestion.sync.watchdog_runner import RawDirHandler


@pytest.mark.asyncio
async def test_handler_debounces_rapid_events(tmp_raw_dir):
    pipeline_calls = []

    async def fake_pipeline(path):
        pipeline_calls.append(path)
        return {"status": "indexed"}

    handler = RawDirHandler(
        raw_dir=tmp_raw_dir,
        debounce_seconds=0.1,
        on_index=fake_pipeline,
        on_delete=AsyncMock(),
        loop=asyncio.get_event_loop(),
    )

    f = tmp_raw_dir / "a.md"
    f.write_text("content")

    handler._schedule(str(f), "create_or_modify")
    handler._schedule(str(f), "create_or_modify")
    handler._schedule(str(f), "create_or_modify")

    await asyncio.sleep(0.4)
    assert len(pipeline_calls) == 1


@pytest.mark.asyncio
async def test_handler_calls_delete_on_deleted(tmp_raw_dir):
    delete_calls = []

    async def fake_delete(path):
        delete_calls.append(path)
        return {"status": "deleted"}

    handler = RawDirHandler(
        raw_dir=tmp_raw_dir,
        debounce_seconds=0.1,
        on_index=AsyncMock(),
        on_delete=fake_delete,
        loop=asyncio.get_event_loop(),
    )

    f = tmp_raw_dir / "a.md"
    handler._schedule(str(f), "delete")
    await asyncio.sleep(0.3)
    assert delete_calls == ["a.md"]
