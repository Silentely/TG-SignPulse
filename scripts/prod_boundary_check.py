#!/usr/bin/env python3
"""生产上线边界自查脚本（本地只读检查，不连真实 TG）。"""
from __future__ import annotations

import os
import sys

# 避免误写真实数据目录
os.environ.setdefault("APP_DATA_DIR", "/tmp/tg-signpulse-prod-check")
os.environ.setdefault("APP_SECRET_KEY", "prod-check-secret-key-not-for-prod")
os.environ.setdefault("SIGN_TASK_FORCE_IN_MEMORY", "1")
os.environ.setdefault("APP_LEGACY_TASKS_READONLY", "1")


def main() -> int:
    errors: list[str] = []

    # 1) 核心 import 与 Client 单例一致性
    from tg_signer.core import Client, UserMonitor, UserSigner, get_client
    from tg_signer.core import client as client_mod
    from tg_signer.core import runtime as runtime_mod

    if client_mod.Client is not Client:
        errors.append("Client class identity mismatch client vs package")
    if runtime_mod.get_client is not get_client:
        errors.append("get_client identity mismatch runtime vs package")
    if client_mod._CLIENT_INSTANCES is not runtime_mod._CLIENT_INSTANCES:
        errors.append("_CLIENT_INSTANCES not shared between client and runtime")

    # 2) 服务层
    from backend.services.keyword_monitor import get_keyword_monitor_service
    from backend.services.sign_tasks import get_sign_task_service
    from backend.services.telegram import TelegramService, get_telegram_service

    for name in (
        "start_login",
        "verify_login",
        "start_qr_login",
        "get_qr_login_status",
        "list_accounts",
        "delete_account",
        "list_account_devices",
        "check_account_status",
    ):
        if not hasattr(TelegramService, name):
            errors.append(f"TelegramService missing method {name}")

    get_telegram_service()
    get_sign_task_service()
    get_keyword_monitor_service()

    # 3) 路由存在性
    from backend.main import app

    paths = {getattr(r, "path", None) for r in app.routes}
    for need in (
        "/api/batch/sign-tasks",
        "/api/ops/scheduled-jobs",
        "/api/ops/backup/status",
        "/api/ops/backup/export",
        "/api/ops/memory",
        "/api/events/sign-history",
        "/api/events/logs",
        "/api/tasks/legacy-status",
        "/api/sign-tasks",
        "/api/accounts",
        "/health",
        "/readyz",
    ):
        if need not in paths:
            errors.append(f"missing route {need}")

    # 4) 旧任务默认只读
    from backend.api.routes.tasks import _legacy_writes_allowed

    os.environ.pop("APP_LEGACY_TASKS_READONLY", None)
    # re-read with default: function reads env each call
    os.environ["APP_LEGACY_TASKS_READONLY"] = "1"
    if _legacy_writes_allowed():
        errors.append("legacy writes should be denied when READONLY=1")
    os.environ["APP_LEGACY_TASKS_READONLY"] = "0"
    if not _legacy_writes_allowed():
        errors.append("legacy writes should be allowed when READONLY=0")

    # 5) 分片边界
    from backend.services.keyword_monitor.sharding import account_in_monitor_scope

    if not account_in_monitor_scope("acc1", shard=(0, 1)):
        errors.append("shard 0/1 should include all accounts")
    if account_in_monitor_scope("acc1", allowlist={"other"}):
        errors.append("allowlist should exclude acc1")

    # 6) DB URL 解析
    from backend.core import config as config_module

    config_module.get_settings.cache_clear()
    os.environ["APP_DATA_DIR"] = "/tmp/tg-signpulse-prod-check"
    os.environ.pop("APP_DATABASE_URL", None)
    os.environ.pop("DATABASE_URL", None)
    s = config_module.Settings.from_environment()
    if not s.is_sqlite:
        errors.append("default database should be sqlite")
    os.environ["APP_DATABASE_URL"] = "postgresql+psycopg2://u:p@localhost/db"
    config_module.get_settings.cache_clear()
    s2 = config_module.Settings.from_environment()
    if s2.is_sqlite:
        errors.append("override DATABASE_URL should not be sqlite")

    # 7) 调度锁可获取/释放（同进程）
    from backend.scheduler.instance_lock import (
        has_scheduler_lock,
        release_scheduler_lock,
        try_acquire_scheduler_lock,
    )

    release_scheduler_lock()
    os.environ["APP_SCHEDULER_LOCK"] = "1"
    config_module.get_settings.cache_clear()
    ok = try_acquire_scheduler_lock()
    if not ok or not has_scheduler_lock():
        errors.append("failed to acquire scheduler lock in single process")
    release_scheduler_lock()
    if has_scheduler_lock():
        errors.append("scheduler lock not released")

    if errors:
        print("FAIL:")
        for e in errors:
            print(" -", e)
        return 1
    print("PASS: production boundary smoke checks ok")
    print("  Client shared instances:", id(client_mod._CLIENT_INSTANCES))
    print("  UserSigner/UserMonitor:", UserSigner, UserMonitor)
    print("  routes checked:", len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
