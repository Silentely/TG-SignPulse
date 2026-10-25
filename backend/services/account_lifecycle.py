"""Reviewable account changes with stale-plan checks and staged file rollback.

Plans are descriptive: apply always resolves paths and resources again. Shared
chat/plugin namespaces have no account owner and are deliberately retained.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from backend.core.config import get_settings
from backend.utils import tg_session
from backend.utils.names import validate_storage_name

_change_lock = asyncio.Lock()
_SESSION_SUFFIXES = (
    ".session",
    ".session-journal",
    ".session-shm",
    ".session-wal",
    ".session_string",
)


@dataclass
class AccountChangePlan:
    operation: Literal["delete", "rename"]
    old_name: str
    new_name: str | None
    affected_tasks: list[dict[str, Any]]
    affected_jobs: list[str]
    affected_monitors: list[str]
    history_policy: Literal["retain", "delete"]
    reversible_steps: list[str]
    warnings: list[str]
    history_paths: list[str]
    plugin_namespaces: list[str]
    revision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _services():
    from backend import scheduler
    from backend.services.keyword_monitor import get_keyword_monitor_service
    from backend.services.sign_tasks import get_sign_task_service
    from backend.services.telegram import get_telegram_service

    return (
        get_telegram_service(),
        get_sign_task_service(),
        get_keyword_monitor_service(),
        scheduler.scheduler,
    )


def _assert_idle(tasks, name):
    for mapping_name in ("_active_tasks", "_background_run_tasks"):
        for key, value in getattr(tasks, mapping_name, {}).items():
            if isinstance(key, tuple) and key[0] == name:
                if value and (not hasattr(value, "done") or not value.done()):
                    raise ValueError(
                        "ACCOUNT_BUSY: finish or cancel active runs before changing the account"
                    )
    for key, value in getattr(tasks, "_run_statuses", {}).items():
        if isinstance(key, tuple) and key[0] == name and isinstance(value, dict):
            if value.get("state", value.get("status")) in (
                "running",
                "unknown",
            ) or value.get("side_effect_unknown"):
                raise ValueError("ACCOUNT_BUSY: unresolved side-effect attempt")


def _inventory(telegram, tasks, name):
    """Read strictly: malformed configs must not disappear during migration."""
    configs = []
    for path in sorted(tasks.signs_dir.glob("**/config.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError(f"Invalid task config: {path}")
        owned = path.parent.parent == tasks.signs_dir / name
        legacy = (
            path.parent.parent == tasks.signs_dir and cfg.get("account_name") == name
        )
        referenced = cfg.get("account_name") == name or name in (
            cfg.get("account_names") or []
        )
        if owned or legacy or referenced:
            configs.append((path, cfg, owned or legacy))
    from backend.services.sign_task_history_store import SignTaskHistoryStore

    safe_name = SignTaskHistoryStore.safe_history_key(name)
    history = sorted(set(tasks.run_history_dir.glob(f"{safe_name}__*.json")))
    files = [telegram.session_dir / f"{name}{ext}" for ext in _SESSION_SUFFIXES]
    files += [
        get_settings().resolve_workdir() / "avatars" / f"{name}{ext}"
        for ext in (".jpg", ".no_avatar")
    ]
    return configs, history, [p for p in files if p.exists()]


def _history_destination(path: Path, new_name: str) -> Path:
    from backend.services.sign_task_history_store import SignTaskHistoryStore

    return path.with_name(
        f"{SignTaskHistoryStore.safe_history_key(new_name)}__{path.name.split('__', 1)[1]}"
    )


async def build_account_change_plan(
    account_name: str,
    operation: Literal["delete", "rename"],
    new_name: str | None = None,
    history_policy: Literal["retain", "delete"] = "retain",
    *,
    telegram_service=None,
) -> AccountChangePlan:
    name = validate_storage_name(account_name, field_name="account_name")
    if operation not in ("delete", "rename") or history_policy not in (
        "retain",
        "delete",
    ):
        raise ValueError("Invalid lifecycle operation or history policy")
    if operation == "rename":
        new_name = validate_storage_name(new_name or "", field_name="new_account_name")
        if new_name == name:
            raise ValueError("Account names must differ")
    else:
        new_name = None
    telegram, tasks, monitor, scheduler = _services()
    telegram = telegram_service or telegram
    _assert_idle(tasks, name)
    configs, history, files = _inventory(telegram, tasks, name)
    if not files and name not in tg_session.list_account_names():
        raise ValueError("ACCOUNT_NOT_FOUND")
    if operation == "rename":
        destinations = [
            telegram.session_dir / f"{new_name}{ext}" for ext in _SESSION_SUFFIXES
        ]
        destinations += [tasks.signs_dir / new_name]
        destinations += [_history_destination(p, new_name) for p in history]
        destinations += [
            p.with_name(f"{new_name}{p.suffix}")
            for p in files
            if p.parent.name == "avatars"
        ]
        if new_name in tg_session.list_account_names() or any(
            p.exists() for p in destinations
        ):
            raise ValueError("ACCOUNT_ALREADY_EXISTS")
    task_items = [
        {"name": p.parent.name, "path": str(p), "owned": owned}
        for p, _, owned in configs
    ]
    jobs = []
    if scheduler is not None:
        for job in scheduler.get_jobs():
            args = getattr(job, "args", ())
            if (args and args[0] == name) or getattr(job, "kwargs", {}).get(
                "account_name"
            ) == name:
                jobs.append(job.id)
    monitors = sorted(
        {
            f"{name}/{p.parent.name}"
            for p, cfg, _ in configs
            if cfg.get("execution_mode") == "listen"
        }
        | {
            f"{name}/{r.task_name}"
            for r in getattr(monitor, "_rules", [])
            if r.account_name == name
        }
    )
    hashes = [
        (str(p), hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(set(files + history + [p for p, _, _ in configs]))
    ]
    hashes.append(
        (
            "profile",
            hashlib.sha256(
                json.dumps(
                    tg_session._load_account_store()["accounts"].get(name),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        )
    )
    revision = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return AccountChangePlan(
        operation,
        name,
        new_name,
        task_items,
        sorted(jobs),
        monitors,
        history_policy,
        [
            "pause scheduling and monitors",
            "stage original files",
            "migrate references and profile",
            "validate destinations",
            "resume scheduling and monitors",
        ],
        [
            "Session removal requires login again."
            if operation == "delete"
            else "A failed migration restores original files and profile.",
            "Shared chat/plugin namespaces have no account ownership; retained for other accounts.",
            "History is retained."
            if history_policy == "retain"
            else "History deletion is irreversible after apply.",
            "Staging is local rollback, not a backup.",
        ],
        [str(p) for p in history],
        ["shared chat/plugin namespaces (retained)"],
        revision,
    )


def _validate_applied(plan, telegram, tasks):
    if (tasks.signs_dir / plan.old_name).exists():
        raise RuntimeError("Old runnable task directory remains")
    if any(
        (telegram.session_dir / f"{plan.old_name}{ext}").exists()
        for ext in _SESSION_SUFFIXES
    ):
        raise RuntimeError("Old session remains")
    for path in tasks.signs_dir.glob("**/config.json"):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("account_name") == plan.old_name or plan.old_name in (
            cfg.get("account_names") or []
        ):
            raise RuntimeError("Old account reference remains")


async def _sync_runtime(monitor):
    from backend.scheduler import sync_jobs

    await sync_jobs()
    await monitor.restart_from_tasks()


async def apply_account_change_plan(
    plan: AccountChangePlan, *, telegram_service=None
) -> dict[str, Any]:
    from backend.services.sign_task_config_build import apply_account_rename_to_config
    from backend.services.telegram.sessions import (
        _login_sessions,
        _qr_login_sessions,
        _release_login_session,
    )
    from backend.utils.account_locks import acquire_multi_account_locks
    from tg_signer.core import close_client_by_name

    async with (
        _change_lock,
        acquire_multi_account_locks([plan.old_name, plan.new_name or plan.old_name]),
    ):
        fresh = await build_account_change_plan(
            plan.old_name,
            plan.operation,
            plan.new_name,
            plan.history_policy,
            telegram_service=telegram_service,
        )
        if asdict(fresh) != asdict(plan):
            raise ValueError("ACCOUNT_PLAN_STALE: refresh the impact preview")
        telegram, tasks, monitor, scheduler = _services()
        telegram = telegram_service or telegram
        configs, history, files = _inventory(telegram, tasks, plan.old_name)
        original_profile = copy.deepcopy(
            tg_session._load_account_store()["accounts"].get(plan.old_name)
        )
        snapshots: dict[Path, Path] = {}
        created: list[Path] = []
        staging_root = get_settings().resolve_workdir() / ".account-lifecycle"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="change-", dir=staging_root))
        staging.chmod(0o700)

        def snapshot(path):
            if path.exists() and path not in snapshots:
                dst = staging / str(len(snapshots))
                if path.is_dir():
                    shutil.copytree(path, dst)
                else:
                    shutil.copy2(path, dst)
                snapshots[path] = dst

        def move(path, dest):
            snapshot(path)
            if dest.exists():
                raise ValueError(f"Destination exists: {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            created.append(dest)
            path.rename(dest)

        try:
            if scheduler is not None:
                for job_id in fresh.affected_jobs:
                    scheduler.remove_job(job_id)
            await monitor.stop()
            await close_client_by_name(plan.old_name, workdir=telegram.session_dir)
            _assert_idle(tasks, plan.old_name)
            for path in files:
                if plan.operation == "rename":
                    move(
                        path,
                        path.with_name(
                            path.name.replace(plan.old_name, plan.new_name, 1)
                        ),
                    )
                else:
                    snapshot(path)
                    path.unlink()
            for path, cfg, owned in configs:
                snapshot(path.parent if owned else path)
                if plan.operation == "delete" and owned:
                    shutil.rmtree(path.parent)
                    continue
                if plan.operation == "rename":
                    apply_account_rename_to_config(cfg, plan.old_name, plan.new_name)
                else:
                    cfg["account_names"] = [
                        n for n in cfg.get("account_names", []) if n != plan.old_name
                    ]
                    if cfg.get("account_name") == plan.old_name:
                        cfg["account_name"] = next(iter(cfg["account_names"]), "")
                        if not cfg["account_name"]:
                            cfg["enabled"] = False
                path.write_text(
                    json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            old_dir = tasks.signs_dir / plan.old_name
            if old_dir.exists():
                if plan.operation == "rename":
                    # Config backups are already staged; preserve the whole directory too.
                    move(old_dir, tasks.signs_dir / plan.new_name)
                elif not any(old_dir.iterdir()):
                    old_dir.rmdir()
                else:
                    snapshot(old_dir)
                    shutil.rmtree(old_dir)
            for path in history:
                if plan.operation == "rename":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    dest = _history_destination(path, plan.new_name)
                    move(path, dest)
                    entries = payload if isinstance(payload, list) else [payload]
                    for entry in entries:
                        if (
                            isinstance(entry, dict)
                            and entry.get("account_name") == plan.old_name
                        ):
                            entry["account_name"] = plan.new_name
                    dest.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                elif plan.history_policy == "delete":
                    snapshot(path)
                    path.unlink()
            if plan.operation == "rename":
                tg_session.rename_account_entry(plan.old_name, plan.new_name)
            else:
                tg_session.delete_account_session_string(plan.old_name)
            _validate_applied(plan, telegram, tasks)
            from backend.services.sign_task_history_index import (
                INDEX_FILENAME,
                rebuild_index_from_history_files,
            )

            index_path = tasks.run_history_dir / INDEX_FILENAME
            if index_path.exists():
                snapshot(index_path)
            else:
                created.append(index_path)
            rebuild_index_from_history_files(tasks.run_history_dir)
            tasks._refresh_tasks_cache_after_write()
            await _sync_runtime(monitor)
        except BaseException:
            for path in reversed(created):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            # Parent snapshots restore before children, whose originals predate config edits.
            for path, saved in sorted(
                snapshots.items(), key=lambda item: len(item[0].parts)
            ):
                if path.exists() and path.is_dir():
                    shutil.rmtree(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if saved.is_dir():
                    shutil.copytree(saved, path)
                else:
                    shutil.copy2(saved, path)
            store = tg_session._load_account_store()
            if plan.new_name:
                store["accounts"].pop(plan.new_name, None)
            if original_profile is not None:
                store["accounts"][plan.old_name] = original_profile
            tg_session._save_account_store(store)
            telegram._accounts_cache = None
            tasks._refresh_tasks_cache_after_write()
            try:
                await _sync_runtime(monitor)
            except Exception:
                # Keep the staged recovery copy if resynchronization also fails.
                raise RuntimeError(
                    f"Account rollback restored files; runtime resync failed. Recovery: {staging}"
                )
            shutil.rmtree(staging)
            raise
        telegram._accounts_cache = None
        if plan.operation == "rename":
            telegram._rename_pending_login_records(plan.old_name, plan.new_name)
        else:
            for store in (_login_sessions, _qr_login_sessions):
                for key, value in list(store.items()):
                    if (
                        str(value.get("account_name") or "").lower()
                        == plan.old_name.lower()
                    ):
                        store.pop(key, None)
                        try:
                            await _release_login_session(value)
                        except Exception:
                            logging.getLogger(__name__).warning(
                                "Pending login cleanup failed after account deletion",
                                exc_info=True,
                            )
        for mapping_name in (
            "_run_statuses",
            "_active_logs",
            "_account_last_run_end",
            "_account_locks",
        ):
            mapping = getattr(tasks, mapping_name, {})
            for key in list(mapping):
                if key == plan.old_name or (
                    isinstance(key, tuple) and key[0] == plan.old_name
                ):
                    value = mapping.pop(key)
                    if plan.operation == "rename":
                        mapping[
                            (plan.new_name, *key[1:])
                            if isinstance(key, tuple)
                            else plan.new_name
                        ] = value
        shutil.rmtree(staging)
        return {
            "success": True,
            "account_name": plan.new_name or plan.old_name,
            "history_policy": plan.history_policy,
        }
