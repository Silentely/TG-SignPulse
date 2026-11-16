from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.task_config_io import (
    TaskConfigConflict,
    create_task_config,
    locked_task_paths,
    update_task_config,
    verify_single_writer_environment,
)
from tg_signer.semantic.models import config_revision


def test_create_task_config_and_conflict_on_existing(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = {"sign_at": "08:00", "chats": []}

    def validate(c):
        assert "sign_at" in c

    created = create_task_config(path, cfg, validate=validate)
    assert created["sign_at"] == "08:00"
    assert path.exists()

    # 重复创建抛 FileExistsError
    with pytest.raises(FileExistsError):
        create_task_config(path, cfg, validate=validate)


def test_partial_update_preserves_latest_runtime_metadata(tmp_path: Path):
    path = tmp_path / "config.json"
    initial = {"sign_at": "08:00", "chats": [], "last_run": {"run_id": "run_initial"}}
    path.write_text(json.dumps(initial), encoding="utf-8")

    def validate(config):
        assert config["sign_at"] in {"08:00", "09:00"}

    saved = update_task_config(
        path,
        lambda current: {**current, "sign_at": "09:00"},
        validate=validate,
    )
    assert saved["sign_at"] == "09:00"
    assert saved["last_run"]["run_id"] == "run_initial"


def test_update_task_config_detects_revision_conflict(tmp_path: Path):
    path = tmp_path / "config.json"
    initial = {"sign_at": "08:00", "chats": []}
    path.write_text(json.dumps(initial), encoding="utf-8")
    rev_before = config_revision(initial)

    # 外部写入修改配置
    path.write_text(json.dumps({"sign_at": "10:00", "chats": []}), encoding="utf-8")

    # 携带旧的 expected_revision 进行更新，抛出 TaskConfigConflict
    with pytest.raises(TaskConfigConflict):
        update_task_config(
            path,
            lambda current: {**current, "sign_at": "09:00"},
            validate=lambda c: None,
            expected_revision=rev_before,
        )


def test_locked_task_paths_deadlock_prevention(tmp_path: Path):
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"

    # 重复与无序路径入参，锁管理器规范排序去重
    with locked_task_paths([p2, p1, p2, p1]):
        pass


def test_verify_single_writer_environment(monkeypatch, caplog):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with caplog.at_level("WARNING"):
        verify_single_writer_environment()
    assert any(
        "单写" in record.message or "WEB_CONCURRENCY" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "worker_key", ["WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS", "WORKERS"]
)
@pytest.mark.parametrize("workers", [None, "1", "2"])
async def test_startup_checks_single_writer_before_initialization(
    monkeypatch, caplog, worker_key, workers
):
    import backend.main as main

    for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS", "WORKERS"):
        monkeypatch.delenv(key, raising=False)
    if workers is not None:
        monkeypatch.setenv(worker_key, workers)

    class InitializationReached(Exception):
        pass

    def stop_initialization(settings):
        raise InitializationReached

    monkeypatch.setattr(main, "_configure_backend_logging", lambda: None)
    monkeypatch.setattr(main, "ensure_data_dirs", stop_initialization)
    with caplog.at_level("WARNING", logger="backend.services.task_config_io"):
        with pytest.raises(InitializationReached):
            await main.on_startup()

    warnings = [
        record
        for record in caplog.records
        if record.name == "backend.services.task_config_io" and "单写" in record.message
    ]
    assert len(warnings) == (1 if workers == "2" else 0)
    if warnings:
        assert f"{worker_key}=2" in warnings[0].message
