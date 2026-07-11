"""backend.utils.async_io.AsyncFileManager 单元测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.utils.async_io import AsyncFileManager


@pytest.mark.asyncio
async def test_write_read_text(tmp_path: Path):
    mgr = AsyncFileManager()
    target = tmp_path / "nested" / "note.txt"
    await mgr.write_text(target, "hello")
    assert await mgr.exists(target) is True
    assert await mgr.read_text(target) == "hello"


@pytest.mark.asyncio
async def test_write_read_json(tmp_path: Path):
    mgr = AsyncFileManager()
    target = tmp_path / "cfg.json"
    payload = {"name": "任务", "enabled": True}
    await mgr.write_json(target, payload)
    assert await mgr.read_json(target) == payload


@pytest.mark.asyncio
async def test_delete_missing_and_existing(tmp_path: Path):
    mgr = AsyncFileManager()
    missing = tmp_path / "nope.txt"
    assert await mgr.delete(missing) is False
    existing = tmp_path / "yes.txt"
    await mgr.write_text(existing, "x")
    assert await mgr.delete(existing) is True
    assert await mgr.exists(existing) is False


@pytest.mark.asyncio
async def test_read_missing_raises(tmp_path: Path):
    mgr = AsyncFileManager()
    with pytest.raises(FileNotFoundError):
        await mgr.read_text(tmp_path / "missing.txt")
