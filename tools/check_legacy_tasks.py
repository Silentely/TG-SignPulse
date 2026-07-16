#!/usr/bin/env python3
"""
检查旧版 ORM 任务存量，并输出迁移到 sign-tasks 的建议。

用法（项目根目录）::

    python tools/check_legacy_tasks.py
    APP_DATA_DIR=./data python tools/check_legacy_tasks.py --json

不修改任何数据；生产默认 APP_LEGACY_TASKS_READONLY=1 时写接口已关闭。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 保证可从仓库根导入 backend
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="检查旧版 ORM /api/tasks 存量")
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出",
    )
    args = parser.parse_args()

    # 延迟 import，先吃环境变量
    from sqlalchemy.orm import joinedload

    from backend.core.config import get_settings
    from backend.core.database import get_session_local, init_engine
    from backend.models.task import Task
    from backend.services.sign_tasks import get_sign_task_service

    get_settings.cache_clear()
    init_engine()
    db = get_session_local()()

    try:
        orm_tasks = (
            db.query(Task)
            .options(joinedload(Task.account))
            .order_by(Task.id.asc())
            .all()
        )
        rows = []
        for t in orm_tasks:
            account_name = None
            if getattr(t, "account", None) is not None:
                account_name = getattr(t.account, "account_name", None) or getattr(
                    t.account, "name", None
                )
            rows.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "cron": t.cron,
                    "enabled": bool(t.enabled),
                    "account_id": t.account_id,
                    "account_name": account_name,
                    "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                }
            )

        sign_service = get_sign_task_service()
        sign_tasks = sign_service.list_tasks(force_refresh=True, aggregate=True)
        sign_names = {str(x.get("name") or "") for x in sign_tasks}

        only_orm = [r for r in rows if r["name"] not in sign_names]
        readonly = os.getenv("APP_LEGACY_TASKS_READONLY", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

        enabled_orm = sum(1 for r in rows if r.get("enabled"))
        ready_for_removal = (
            readonly and len(rows) == 0 and len(only_orm) == 0
        )
        if ready_for_removal:
            removal_stage = "ready"
            removal_hint = (
                "ORM 无存量且只读已开启，可在后续版本评估删除 /api/tasks 写路径与 ORM Task 表。"
            )
        elif readonly and len(only_orm) == 0:
            removal_stage = "readonly_with_shared_names"
            removal_hint = (
                "仅存在名称重叠或 ORM 可迁移项已对齐；保持只读，确认无外部脚本后进入 ready。"
            )
        elif not readonly:
            removal_stage = "writable_compat"
            removal_hint = (
                "当前 APP_LEGACY_TASKS_READONLY=0（可写兼容）。生产应改回 1 并迁移到 sign-tasks。"
            )
        else:
            removal_stage = "needs_migration"
            removal_hint = (
                f"仍有 {len(only_orm)} 个仅 ORM 任务，请在面板用 sign-tasks 重建后复检。"
            )

        report = {
            "data_dir": str(get_settings().resolve_base_dir()),
            "legacy_readonly": readonly,
            "orm_task_count": len(rows),
            "orm_enabled_count": enabled_orm,
            "sign_task_count": len(sign_tasks),
            "orm_only_count": len(only_orm),
            "orm_tasks": rows,
            "orm_only_names": [r["name"] for r in only_orm],
            "preferred_api": "/api/sign-tasks",
            "removal_stage": removal_stage,
            "ready_for_route_removal": ready_for_removal,
            "migration_hint": (
                "旧 ORM 任务仅有 name/cron/account，不含完整动作序列。"
                "请在面板用 sign-tasks 重建流程，或从配置导出 JSON 导入。"
                "确认无外部写 /api/tasks 后保持 APP_LEGACY_TASKS_READONLY=1。"
            ),
            "removal_hint": removal_hint,
        }

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        print("=== 旧版 ORM 任务检查 ===")
        print(f"数据目录: {report['data_dir']}")
        print(f"旧 API 只读: {report['legacy_readonly']}")
        print(f"ORM 任务数: {report['orm_task_count']} (enabled={enabled_orm})")
        print(f"sign-tasks 数: {report['sign_task_count']}")
        print(f"仅存在于 ORM 的任务: {report['orm_only_count']}")
        print(f"下线阶段: {removal_stage}")
        print(f"可评估删除旧路由: {ready_for_removal}")
        if rows:
            print("\nORM 任务列表:")
            for r in rows:
                flag = " [仅ORM]" if r["name"] not in sign_names else ""
                print(
                    f"  #{r['id']} {r['name']} cron={r['cron']} "
                    f"enabled={r['enabled']} account={r['account_name'] or r['account_id']}{flag}"
                )
        else:
            print("\n无 ORM 任务，可安心保持默认只读。")
        print(f"\n建议: {report['migration_hint']}")
        print(f"下线: {removal_hint}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
