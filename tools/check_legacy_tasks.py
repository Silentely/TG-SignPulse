#!/usr/bin/env python3
"""
检查数据目录中是否仍残留旧版 ORM 任务表（tasks / task_logs）。

模型与 HTTP 路由均已移除；本工具仅用 SQL 探测残留表，便于运维决定是否手工 DROP。

用法（项目根目录）::

    python tools/check_legacy_tasks.py
    APP_DATA_DIR=./data python tools/check_legacy_tasks.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _table_exists(conn, name: str) -> bool:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        row = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    # 通用信息架构
    row = conn.exec_driver_sql(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :n",
        {"n": name},
    ).fetchone()
    return row is not None


def _count_rows(conn, table: str) -> int | None:
    try:
        row = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="检查旧版 ORM tasks 表残留")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    from backend.core.config import get_settings
    from backend.core.database import get_engine, init_engine

    get_settings.cache_clear()
    init_engine()
    engine = get_engine()
    settings = get_settings()

    tables = {}
    with engine.connect() as conn:
        for name in ("tasks", "task_logs"):
            exists = _table_exists(conn, name)
            count = _count_rows(conn, name) if exists else 0
            tables[name] = {"exists": exists, "row_count": count}

    residual = any(v["exists"] and (v["row_count"] or 0) > 0 for v in tables.values())
    any_table = any(v["exists"] for v in tables.values())
    report = {
        "data_dir": str(settings.resolve_base_dir()),
        "models_removed": True,
        "routes_removed": True,
        "preferred_api": "/api/sign-tasks",
        "tables": tables,
        "has_residual_tables": any_table,
        "has_residual_rows": residual,
        "ready_for_table_drop": any_table,
        "hint": (
            "HTTP 与 ORM 模型已移除。若 tables.*.exists=true，可在备份后手工 "
            "DROP TABLE tasks; DROP TABLE task_logs;（SQLite 亦可用）。"
            if any_table
            else "未发现 tasks/task_logs 表，遗留清理完成。"
        ),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=== 旧版 ORM 任务表残留检查 ===")
    print(f"数据目录: {report['data_dir']}")
    print(f"模型已移除: {report['models_removed']}")
    print(f"路由已移除: {report['routes_removed']}")
    for name, info in tables.items():
        print(
            f"  {name}: exists={info['exists']} rows={info['row_count']}"
        )
    print(f"建议: {report['hint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
