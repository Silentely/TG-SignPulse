"""会话存储 open() 补丁测试。

覆盖 kurigram 存储类迁移（2.2.10 起 file_storage.FileStorage -> sqlite_storage.SQLiteStorage）
导致的补丁静默失效回归：补丁必须真实安装在当前安装版本上，否则文件会话会退回
上游的 PRAGMA journal_mode=DELETE + VACUUM（独占锁）行为。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pathlib

import pytest

from tg_signer.compat import MemoryStorage
from tg_signer.core import client as client_module
from tg_signer.core.client import (
    _STORAGE_CLASS_CANDIDATES,
    _install_storage_open_patch,
)


def _resolve_storage_classes():
    classes = []
    for module_path, class_name in _STORAGE_CLASS_CANDIDATES:
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        cls = getattr(module, class_name, None)
        if cls is not None:
            classes.append(cls)
    return classes


def test_storage_open_patch_is_installed_on_current_runtime():
    """补丁必须落在当前安装版本的存储类上，而非因模块改名而静默失效。"""
    classes = _resolve_storage_classes()
    assert classes, "未定位到任何会话存储类，补丁必然未生效"

    for cls in classes:
        assert cls.open.__module__ == client_module.__name__, (
            f"{cls.__name__}.open 未被补丁覆盖，WAL/busy_timeout 优化实际未生效"
        )


@pytest.mark.asyncio
async def test_file_storage_open_enables_wal_and_busy_timeout(tmp_path: pathlib.Path):
    storage_cls = _resolve_storage_classes()[0]
    storage = storage_cls("probe", workdir=tmp_path)

    await storage.open()
    try:
        journal_mode = storage.conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = storage.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        # 补丁前上游为 DELETE（use_wal 默认 False），无法承受同账号多客户端并发
        assert str(journal_mode).lower() == "wal"
        assert busy_timeout == 30000
        # 生命周期方法在 2.2.10+ 为协程，补丁必须 await 后才算真正建表
        assert await storage.version() == storage_cls.VERSION
    finally:
        await storage.close()

    assert (tmp_path / "probe.session").is_file()


@pytest.mark.asyncio
async def test_in_memory_storage_open_delegates_to_upstream():
    """内存存储（string 会话模式）不得被文件补丁影响。"""
    storage = MemoryStorage("probe", session_string=None, workdir=None)

    await storage.open()
    try:
        assert storage.database == ":memory:"
        assert await storage.version() == storage.VERSION
    finally:
        await storage.close()


def test_storage_open_patch_warns_when_no_candidate_resolves(monkeypatch, caplog):
    """候选全部失效时必须显式告警，避免补丁静默降级。"""
    monkeypatch.setattr(
        client_module,
        "_STORAGE_CLASS_CANDIDATES",
        (("pyrogram.storage.not_exist", "NotExist"),),
    )

    with caplog.at_level(logging.WARNING, logger="tg-signer"):
        assert _install_storage_open_patch() is False

    assert any("会话存储类" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_storage_open_patch_is_idempotent_across_reinstall(tmp_path):
    """重复安装不得破坏文件会话生命周期。"""
    _install_storage_open_patch()

    storage_cls = _resolve_storage_classes()[0]
    storage = storage_cls("probe", workdir=tmp_path)
    await storage.open()
    try:
        assert (
            str(storage.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            == "wal"
        )
        await storage.user_id(12345)
        await storage.save()
        assert await storage.user_id() == 12345
    finally:
        await storage.close()

    # 关闭后 WAL 边车文件应被清理，保证会话文件可单独复制/导出
    assert sorted(p.name for p in tmp_path.iterdir()) == ["probe.session"]


@pytest.mark.asyncio
async def test_concurrent_file_sessions_do_not_deadlock(tmp_path: pathlib.Path):
    """同一会话文件的并发打开在 busy_timeout 下不应直接抛 database is locked。"""
    storage_cls = _resolve_storage_classes()[0]

    first = storage_cls("probe", workdir=tmp_path)
    await first.open()
    try:
        second = storage_cls("probe", workdir=tmp_path)
        await asyncio.wait_for(second.open(), timeout=20)
        try:
            assert await second.version() == storage_cls.VERSION
        finally:
            await second.close()
    finally:
        await first.close()
