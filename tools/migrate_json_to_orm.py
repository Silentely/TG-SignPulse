from __future__ import annotations

import argparse
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from backend.core.config import get_settings
from backend.core.database import Base, get_session_local
from backend.models.sign_task import (
    SignTaskModel,
    StorageMigrationItemModel,
    StorageMigrationRunModel,
)

logger = logging.getLogger("tools.migrate_json_to_orm")


def run_migration(signs_dir: Path, dry_run: bool = True) -> Dict[str, Any]:
    signs_dir = Path(signs_dir)
    scanned = 0
    migrated = 0
    failed = 0
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    if not signs_dir.exists():
        return {
            "run_id": run_id,
            "scanned_count": 0,
            "migrated_count": 0,
            "failed_count": 0,
            "dry_run": dry_run,
        }

    session_local = get_session_local()
    engine = session_local().get_bind()
    Base.metadata.create_all(bind=engine)

    tasks_to_insert = []
    for acc_dir in signs_dir.iterdir():
        if not acc_dir.is_dir():
            continue
        for task_dir in acc_dir.iterdir():
            if not task_dir.is_dir():
                continue
            config_file = task_dir / "config.json"
            if not config_file.exists():
                continue

            scanned += 1
            try:
                content = config_file.read_text(encoding="utf-8")
                raw_cfg = json.loads(content)
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                tasks_to_insert.append(
                    {
                        "account_name": acc_dir.name,
                        "task_name": task_dir.name,
                        "is_wildcard": bool(raw_cfg.get("is_wildcard", False)),
                        "cron_expr": raw_cfg.get("cron"),
                        "random_window": raw_cfg.get("random_window"),
                        "enabled": bool(raw_cfg.get("enabled", True)),
                        "config_json": content,
                        "sha256": sha,
                    }
                )
            except Exception as e:
                failed += 1
                logger.error("解析 %s 失败: %s", config_file, e)

    if not dry_run and tasks_to_insert:
        now = datetime.now(timezone.utc)
        with session_local() as db:
            for item in tasks_to_insert:
                existing = (
                    db.query(SignTaskModel)
                    .filter_by(
                        account_name=item["account_name"],
                        task_name=item["task_name"],
                    )
                    .first()
                )
                if not existing:
                    task = SignTaskModel(
                        account_name=item["account_name"],
                        task_name=item["task_name"],
                        is_wildcard=item["is_wildcard"],
                        cron_expr=item["cron_expr"],
                        random_window=item["random_window"],
                        enabled=item["enabled"],
                        config_json=item["config_json"],
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(task)
                    migrated_item = StorageMigrationItemModel(
                        run_id=run_id,
                        account_name=item["account_name"],
                        task_name=item["task_name"],
                        source_sha256=item["sha256"],
                    )
                    db.add(migrated_item)
                    migrated += 1

            journal = StorageMigrationRunModel(
                run_id=run_id,
                status="COMPLETED",
                scanned_count=scanned,
                migrated_count=migrated,
                created_at=now,
            )
            db.add(journal)
            db.commit()

    return {
        "run_id": run_id,
        "scanned_count": scanned,
        "migrated_count": migrated,
        "failed_count": failed,
        "dry_run": dry_run,
    }


def rollback_migration(run_id: str) -> Dict[str, Any]:
    session_local = get_session_local()
    with session_local() as db:
        journal = db.query(StorageMigrationRunModel).filter_by(run_id=run_id).first()
        if not journal or journal.status != "COMPLETED":
            return {
                "status": "error",
                "message": "未找到已完成的对应迁移批次",
            }

        # 精确按批次明细记录撤销对应 (account_name, task_name)
        items = db.query(StorageMigrationItemModel).filter_by(run_id=run_id).all()
        deleted_count = 0
        for it in items:
            # 仅删除该批次导入且未被业务并发修改过的记录 (revision=1)
            del_rows = (
                db.query(SignTaskModel)
                .filter_by(
                    account_name=it.account_name,
                    task_name=it.task_name,
                    revision=1,
                )
                .delete()
            )
            deleted_count += del_rows

        journal.status = "ROLLED_BACK"
        db.commit()
        return {"status": "success", "rolled_back_count": deleted_count}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TG-SignPulse JSON to ORM Migration Tool"
    )
    parser.add_argument("--dry-run", action="store_true", help="只读预检，不写入数据库")
    parser.add_argument("--execute", action="store_true", help="正式执行数据迁移")
    parser.add_argument("--rollback", type=str, help="指定 run_id 撤销指定批次迁移")
    args = parser.parse_args()

    if args.rollback:
        res = rollback_migration(run_id=args.rollback)
        print(f"回滚结果: {res}")
    else:
        settings = get_settings()
        signs_path = settings.resolve_workdir() / "signs"
        print(f"正在定位源任务存储目录: {signs_path}")
        res = run_migration(signs_dir=signs_path, dry_run=not args.execute)
        print(f"迁移执行完毕: {res}")
