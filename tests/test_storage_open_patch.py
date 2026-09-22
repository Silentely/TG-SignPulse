"""会话存储 open() 补丁测试。

覆盖 kurigram 存储类迁移（2.2.10 起 file_storage.FileStorage -> sqlite_storage.SQLiteStorage）
导致的补丁静默失效回归：补丁必须真实安装在当前安装版本上，否则文件会话会退回
上游的 PRAGMA journal_mode=DELETE + VACUUM（独占锁）行为。

另覆盖既有用户旧版（V6）会话库的就地无损迁移，以及内存会话（string 模式）
走 kurigram 原生 SQLiteStorage(in_memory=True) 的委托路径。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pathlib
import sqlite3

import pytest

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
    """内存存储（string 会话模式）走 kurigram 原生 in_memory，不得被文件补丁影响。"""
    from pyrogram.storage.sqlite_storage import SQLiteStorage

    storage = SQLiteStorage("probe", workdir=pathlib.Path("."), in_memory=True)

    await storage.open()
    try:
        assert storage.database == ":memory:"
        assert await storage.version() == SQLiteStorage.VERSION
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_legacy_v6_session_file_migrates_in_place(tmp_path: pathlib.Path):
    """既有用户旧版（V6）会话库必须就地无损迁移到当前 schema。

    复现 kurigram update() 的 6 -> 7 迁移（补 server_address/port 列），
    断言 auth_key/dc_id/user_id 等授权数据不脱钩——这是「升级不影响现有用户」的核心保证。
    """
    storage_cls = _resolve_storage_classes()[0]

    # 构造 V6 旧库：sessions 表无 server_address/port，version=6
    session_file = tmp_path / "legacy.session"
    conn = sqlite3.connect(str(session_file))
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE sessions
                (
                    dc_id INTEGER PRIMARY KEY,
                    api_id INTEGER,
                    test_mode INTEGER,
                    auth_key BLOB,
                    date INTEGER NOT NULL,
                    user_id INTEGER,
                    is_bot INTEGER
                );
                CREATE TABLE peers
                (
                    id INTEGER PRIMARY KEY,
                    access_hash INTEGER,
                    type INTEGER NOT NULL,
                    phone_number TEXT,
                    last_update_on INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE version (number INTEGER PRIMARY KEY);
                INSERT INTO version VALUES (6);
                """
            )
            auth_key = bytes(range(256))
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (2, 123456, 0, auth_key, 1700000000, 777000, 0),
            )
    finally:
        conn.close()

    storage = storage_cls("legacy", workdir=tmp_path)
    await storage.open()
    try:
        assert await storage.version() == storage_cls.VERSION
        # 授权数据必须原样保留
        assert await storage.dc_id() == 2
        assert await storage.user_id() == 777000
        assert bytes(await storage.auth_key()) == auth_key
        # 迁移必须补齐连接地址，否则 DC2 以外的旧会话将无法连通
        assert await storage.server_address()
        assert await storage.port()
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
