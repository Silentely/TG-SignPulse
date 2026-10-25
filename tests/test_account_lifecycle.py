"""Offline lifecycle transactions; no Telegram connections."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.config import get_settings
from backend.services import account_lifecycle as lifecycle
from backend.utils.tg_session import (
    _account_store_cache,
    get_account_profile,
    set_account_profile,
)


@pytest.fixture
def resources(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    _account_store_cache.clear()
    session = tmp_path / "sessions"
    session.mkdir()
    (session / "alice.session").write_bytes(b"fake")
    signs = tmp_path / "signs"
    task = signs / "alice" / "daily"
    task.mkdir(parents=True)
    (task / "config.json").write_text(
        json.dumps(
            {
                "account_name": "alice",
                "account_names": ["alice"],
                "execution_mode": "listen",
            }
        )
    )
    history = tmp_path / "history"
    history.mkdir()
    (history / "alice__daily.json").write_text('[{"account_name":"alice"}]')
    set_account_profile("alice", remark="keep")
    telegram = SimpleNamespace(
        session_dir=session,
        _accounts_cache=None,
        _rename_pending_login_records=lambda *a: None,
    )
    tasks = SimpleNamespace(
        signs_dir=signs,
        run_history_dir=history,
        _active_tasks={},
        _background_run_tasks={},
        _run_statuses={},
        _refresh_tasks_cache_after_write=lambda: None,
    )
    monitor = SimpleNamespace(
        _rules=[], stop=AsyncMock(), restart_from_tasks=AsyncMock()
    )
    monkeypatch.setattr(
        lifecycle, "_services", lambda: (telegram, tasks, monitor, None)
    )
    monkeypatch.setattr("tg_signer.core.close_client_by_name", AsyncMock())
    monkeypatch.setattr(lifecycle, "_sync_runtime", AsyncMock())
    yield tmp_path, telegram, tasks
    get_settings.cache_clear()
    _account_store_cache.clear()


@pytest.mark.asyncio
async def test_preview_delete_retains_history_removes_runnable_resources(resources):
    root, _, _ = resources
    plan = await lifecycle.build_account_change_plan("alice", "delete")
    assert plan.affected_tasks[0]["name"] == "daily"
    assert plan.affected_monitors == ["alice/daily"]
    assert plan.history_policy == "retain"
    assert plan.history_paths
    assert "shared" in " ".join(plan.warnings).lower()
    json.dumps(asdict(plan))
    result = await lifecycle.apply_account_change_plan(plan)
    assert result["success"]
    assert not (root / "signs/alice").exists()
    assert not (root / "sessions/alice.session").exists()
    assert (root / "history/alice__daily.json").exists()


@pytest.mark.asyncio
async def test_stale_and_tampered_plan_rejected(resources):
    root, _, _ = resources
    plan = await lifecycle.build_account_change_plan("alice", "delete")
    with pytest.raises(ValueError, match="STALE"):
        await lifecycle.apply_account_change_plan(replace(plan, affected_tasks=[]))
    (root / "signs/alice/daily/config.json").write_text(
        '{"account_name":"alice","enabled":false}'
    )
    with pytest.raises(ValueError, match="STALE"):
        await lifecycle.apply_account_change_plan(plan)
    assert (root / "sessions/alice.session").exists()


@pytest.mark.asyncio
async def test_rename_failure_restores_sessions_profile_and_configs(
    resources, monkeypatch
):
    root, _, _ = resources
    plan = await lifecycle.build_account_change_plan("alice", "rename", "bob")
    monkeypatch.setattr(
        lifecycle,
        "_validate_applied",
        lambda *args: (_ for _ in ()).throw(RuntimeError("injected")),
    )
    with pytest.raises(RuntimeError, match="injected"):
        await lifecycle.apply_account_change_plan(plan)
    assert (root / "sessions/alice.session").exists()
    assert not (root / "sessions/bob.session").exists()
    assert (
        json.loads((root / "signs/alice/daily/config.json").read_text())["account_name"]
        == "alice"
    )
    assert get_account_profile("alice")["remark"] == "keep"
    assert get_account_profile("bob") == {}


@pytest.mark.asyncio
async def test_rename_success_and_active_run_guard(resources):
    root, _, tasks = resources
    tasks._active_tasks[("alice", "daily")] = object()
    with pytest.raises(ValueError, match="ACCOUNT_BUSY"):
        await lifecycle.build_account_change_plan("alice", "rename", "bob")
    tasks._active_tasks.clear()
    plan = await lifecycle.build_account_change_plan("alice", "rename", "bob")
    await lifecycle.apply_account_change_plan(plan)
    assert (root / "sessions/bob.session").exists()
    assert (
        json.loads((root / "signs/bob/daily/config.json").read_text())["account_name"]
        == "bob"
    )
    assert get_account_profile("bob")["remark"] == "keep"


@pytest.mark.asyncio
async def test_preview_tracks_scheduler_jobs_and_history_delete(resources, monkeypatch):
    root, telegram, tasks = resources
    jobs = [
        SimpleNamespace(id="sign-alice-daily", args=["alice", "daily"], kwargs={}),
        SimpleNamespace(id="sign-other-daily", args=["other", "daily"], kwargs={}),
    ]
    scheduler = SimpleNamespace(
        get_jobs=lambda: jobs,
        remove_job=lambda job_id: jobs.__setitem__(
            slice(None), [j for j in jobs if j.id != job_id]
        ),
    )
    monitor = SimpleNamespace(
        _rules=[], stop=AsyncMock(), restart_from_tasks=AsyncMock()
    )
    monkeypatch.setattr(
        lifecycle, "_services", lambda: (telegram, tasks, monitor, scheduler)
    )
    plan = await lifecycle.build_account_change_plan(
        "alice", "delete", history_policy="delete"
    )
    assert plan.affected_jobs == ["sign-alice-daily"]
    await lifecycle.apply_account_change_plan(plan)
    assert [job.id for job in jobs] == ["sign-other-daily"]
    assert not (root / "history/alice__daily.json").exists()


@pytest.mark.asyncio
async def test_rename_updates_other_task_references_and_retains_unknown_fields(
    resources,
):
    root, _, _ = resources
    sibling = root / "signs/other/task"
    sibling.mkdir(parents=True)
    (sibling / "config.json").write_text(
        json.dumps(
            {
                "account_name": "other",
                "account_names": ["other", "alice"],
                "extension": {"future": True},
            }
        )
    )
    plan = await lifecycle.build_account_change_plan("alice", "rename", "bob")
    await lifecycle.apply_account_change_plan(plan)
    config = json.loads((sibling / "config.json").read_text())
    assert config["account_names"] == ["other", "bob"]
    assert config["extension"] == {"future": True}


@pytest.mark.asyncio
async def test_runtime_sync_failure_rolls_back(resources, monkeypatch):
    root, _, _ = resources
    plan = await lifecycle.build_account_change_plan("alice", "delete")
    monkeypatch.setattr(
        lifecycle,
        "_sync_runtime",
        AsyncMock(side_effect=[RuntimeError("sync fail"), None]),
    )
    with pytest.raises(RuntimeError, match="sync fail"):
        await lifecycle.apply_account_change_plan(plan)
    assert (root / "sessions/alice.session").exists()
    assert (root / "signs/alice/daily/config.json").exists()
    assert get_account_profile("alice")["remark"] == "keep"


@pytest.mark.asyncio
async def test_false_active_entry_does_not_block_completed_account(resources):
    _, _, tasks = resources
    tasks._active_tasks[("alice", "daily")] = False
    plan = await lifecycle.build_account_change_plan("alice", "delete")
    assert plan.old_name == "alice"


@pytest.mark.asyncio
async def test_history_inventory_treats_glob_characters_literally(resources):
    root, _, _ = resources
    history = root / "history"
    (root / "sessions" / "*.session").write_bytes(b"fake")
    (history / "alice__daily.json").write_text('[{"account_name":"alice"}]')
    (history / "bob__daily.json").write_text('[{"account_name":"bob"}]')
    (history / "*__daily.json").write_text('[{"account_name":"*"}]')

    plan = await lifecycle.build_account_change_plan("*", "delete")

    assert [Path(path).name for path in plan.history_paths] == ["*__daily.json"]
