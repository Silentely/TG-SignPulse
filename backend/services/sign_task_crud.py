"""
签到任务 CRUD（从 SignTaskService 抽出的 Mixin）

含 create / clone / update / rename_account / delete。
门面 SignTaskService 继承本 Mixin，保持公开 API 不变。
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.names import validate_storage_name
from backend.services.sign_task_history_index import rebuild_index_from_history_files

_logger = logging.getLogger("backend.sign_task_crud")


class SignTaskCrudMixin:
    """依赖 SignTaskService 实例属性：signs_dir, run_history_dir 及各类 helper。"""

    def create_task(
        self,
        task_name: str,
        sign_at: str,
        chats: List[Dict[str, Any]],
        random_seconds: int = 0,
        sign_interval: Optional[int] = None,
        account_name: str = "",
        account_names: Optional[List[str]] = None,
        execution_mode: str = "fixed",
        range_start: str = "",
        range_end: str = "",
        notify_on_failure: bool = True,
        notify_on_success: bool = True,
        retry_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a sign task that can be shared by multiple accounts."""
        from backend.services.config import get_config_service

        task_name = validate_storage_name(task_name, field_name="task_name")
        target_accounts = self._normalize_account_names(account_names, account_name)
        if not target_accounts:
            raise ValueError("必须指定至少一个账号名称")

        # Preserve the original list (may contain "*") for config storage
        stored_account_names = list(target_accounts)
        # Expand wildcard for actual directory creation and scheduling
        target_accounts = self._expand_account_names(target_accounts)
        if not target_accounts:
            raise ValueError("没有可用的账号")

        if sign_interval is None:
            config_service = get_config_service()
            global_settings = config_service.get_global_settings()
            sign_interval = global_settings.get("sign_interval")

        if sign_interval is None:
            sign_interval = 1

        from backend.services.sign_task_config_build import (
            build_sign_task_config,
            create_task_group_id,
            pick_task_write_response,
            resolve_schedule_plan,
        )

        task_group_id = create_task_group_id(len(target_accounts))
        schedule_plan = resolve_schedule_plan(
            execution_mode, sign_at=sign_at, range_start=range_start
        )
        should_schedule = schedule_plan["should_schedule"]
        trigger_cron = schedule_plan["trigger_cron"]

        for current_account in target_accounts:
            account_dir = self.signs_dir / current_account
            account_dir.mkdir(parents=True, exist_ok=True)

            task_dir = account_dir / task_name
            task_dir.mkdir(parents=True, exist_ok=True)

            config = build_sign_task_config(
                account_name=current_account,
                account_names=stored_account_names,
                task_group_id=task_group_id,
                sign_at=sign_at,
                random_seconds=random_seconds,
                sign_interval=int(sign_interval),
                chats=chats,
                execution_mode=execution_mode,
                range_start=range_start,
                range_end=range_end,
                notify_on_failure=notify_on_failure,
                notify_on_success=notify_on_success,
                retry_count=retry_count if retry_count is not None else 3,
                enabled=True,
            )

            with open(task_dir / "config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        self._refresh_tasks_cache_after_write()

        try:
            from backend.scheduler import (
                add_or_update_sign_task_job,
                remove_sign_task_job,
            )

            for current_account in target_accounts:
                if should_schedule:
                    add_or_update_sign_task_job(
                        current_account,
                        task_name,
                        trigger_cron,
                        enabled=True,
                    )
                else:
                    remove_sign_task_job(current_account, task_name)
        except Exception as e:
            _logger.debug("更新调度任务失败: %s", e)

        related = self._find_related_task_infos(task_name, target_accounts[0])
        return pick_task_write_response(
            related,
            target_accounts=target_accounts,
            aggregate_fn=self._aggregate_tasks,
            get_task_fn=lambda acc: self.get_task(task_name, account_name=acc),
            not_found_message=f"任务 {task_name} 创建后无法读取",
        )

    def clone_task(
        self,
        task_name: str,
        new_name: str,
        account_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """克隆签到任务为新名称（清除运行态字段）。"""
        new_name = validate_storage_name(new_name, field_name="new_name")
        src = self.get_task(task_name, account_name=account_name)
        if not src:
            raise ValueError("源任务不存在")
        # 任一账号目录下已存在同名任务则拒绝，避免 create 静默覆盖
        if self._find_related_task_infos(new_name):
            raise ValueError("目标任务名已存在")

        chats = src.get("chats") or []
        if not isinstance(chats, list):
            chats = []
        account_names = src.get("account_names") or []
        if not isinstance(account_names, list):
            account_names = []
        primary = account_name or src.get("account_name") or (
            account_names[0] if account_names else ""
        )
        if not primary and not account_names:
            raise ValueError("源任务缺少账号信息，无法克隆")
        try:
            random_seconds = int(src.get("random_seconds") or 0)
        except (TypeError, ValueError):
            random_seconds = 0
        return self.create_task(
            task_name=new_name,
            sign_at=str(src.get("sign_at") or "08:00"),
            chats=[dict(c) for c in chats if isinstance(c, dict)],
            random_seconds=random_seconds,
            sign_interval=src.get("sign_interval"),
            account_name=str(primary or ""),
            account_names=list(account_names) if account_names else [str(primary)],
            execution_mode=str(src.get("execution_mode") or "fixed"),
            range_start=str(src.get("range_start") or ""),
            range_end=str(src.get("range_end") or ""),
            notify_on_failure=bool(src.get("notify_on_failure", True)),
            notify_on_success=bool(src.get("notify_on_success", True)),
            retry_count=src.get("retry_count"),
        )

    def update_task(
        self,
        task_name: str,
        sign_at: Optional[str] = None,
        chats: Optional[List[Dict[str, Any]]] = None,
        random_seconds: Optional[int] = None,
        sign_interval: Optional[int] = None,
        account_name: Optional[str] = None,
        account_names: Optional[List[str]] = None,
        execution_mode: Optional[str] = None,
        range_start: Optional[str] = None,
        range_end: Optional[str] = None,
        notify_on_failure: Optional[bool] = None,
        notify_on_success: Optional[bool] = None,
        retry_count: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update one task and fan out the config to all linked accounts."""
        task_name = validate_storage_name(task_name, field_name="task_name")

        # Normalize account_name: skip wildcard, resolve to real account
        if account_name == "*":
            account_name = None

        existing = self.get_task(
            task_name,
            account_name=account_name,
            aggregate=account_name is None,
        )
        related_tasks = self._find_related_task_infos(task_name, account_name)
        if not existing or not related_tasks:
            raise ValueError(f"任务 {task_name} 不存在")

        existing_accounts = self._normalize_account_names(
            existing.get("account_names"), existing.get("account_name")
        )
        target_accounts = (
            self._normalize_account_names(account_names)
            if account_names is not None
            else existing_accounts
        )
        if not target_accounts:
            raise ValueError("任务至少需要保留一个账号")

        # Preserve original list (may contain "*") for config storage
        stored_account_names = list(target_accounts)
        # Expand wildcard "*" to actual account names for directory creation
        target_accounts = self._expand_account_names(target_accounts)
        if not target_accounts:
            raise ValueError("没有可用的账号")
        # Also expand existing_accounts for proper diff calculation
        existing_accounts = self._expand_account_names(existing_accounts)

        from backend.services.sign_task_config_build import (
            build_sign_task_config,
            last_run_map_from_related,
            next_task_group_id,
            pick_task_write_response,
            removed_accounts_diff,
            resolve_schedule_plan,
            resolve_update_field_values,
        )

        next_group_id = next_task_group_id(
            str(existing.get("task_group_id") or ""),
            len(target_accounts),
        )
        fields = resolve_update_field_values(
            existing,
            sign_at=sign_at,
            chats=chats,
            random_seconds=random_seconds,
            sign_interval=sign_interval,
            execution_mode=execution_mode,
            range_start=range_start,
            range_end=range_end,
            notify_on_failure=notify_on_failure,
            notify_on_success=notify_on_success,
            retry_count=retry_count,
            enabled=enabled,
        )
        next_sign_at = fields["sign_at"]
        next_random_seconds = fields["random_seconds"]
        next_sign_interval = fields["sign_interval"]
        next_chats = fields["chats"]
        next_execution_mode = fields["execution_mode"]
        next_range_start = fields["range_start"]
        next_range_end = fields["range_end"]
        next_notify_on_failure = fields["notify_on_failure"]
        next_notify_on_success = fields["notify_on_success"]
        next_enabled = fields["enabled"]
        next_retry_count = fields["retry_count"]
        schedule_plan = resolve_schedule_plan(
            next_execution_mode,
            sign_at=next_sign_at,
            range_start=next_range_start,
        )
        should_schedule = schedule_plan["should_schedule"]
        trigger_cron = schedule_plan["trigger_cron"]

        existing_dirs = dict(self._iter_task_dirs(task_name, existing_accounts))
        existing_last_run_map = last_run_map_from_related(related_tasks)
        removed_accounts = removed_accounts_diff(existing_accounts, target_accounts)

        import shutil

        from backend.scheduler import add_or_update_sign_task_job, remove_sign_task_job

        for removed_account in removed_accounts:
            removed_dir = existing_dirs.get(removed_account)
            if removed_dir and removed_dir.exists():
                shutil.rmtree(removed_dir)
            remove_sign_task_job(removed_account, task_name)

        for current_account in target_accounts:
            desired_dir = self.signs_dir / current_account / task_name
            desired_dir.mkdir(parents=True, exist_ok=True)

            config = build_sign_task_config(
                account_name=current_account,
                account_names=stored_account_names,
                task_group_id=next_group_id,
                sign_at=next_sign_at,
                random_seconds=next_random_seconds,
                sign_interval=next_sign_interval,
                chats=next_chats,
                execution_mode=next_execution_mode,
                range_start=next_range_start,
                range_end=next_range_end,
                notify_on_failure=next_notify_on_failure,
                notify_on_success=next_notify_on_success,
                retry_count=next_retry_count,
                enabled=next_enabled,
                last_run=existing_last_run_map.get(current_account),
            )

            with open(desired_dir / "config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            previous_dir = existing_dirs.get(current_account)
            if (
                previous_dir is not None
                and previous_dir != desired_dir
                and previous_dir.exists()
            ):
                shutil.rmtree(previous_dir)

            if should_schedule:
                add_or_update_sign_task_job(
                    current_account,
                    task_name,
                    trigger_cron,
                    enabled=next_enabled,
                )
            else:
                remove_sign_task_job(current_account, task_name)

        self._refresh_tasks_cache_after_write()
        self._append_scheduler_log(
            "scheduler_update.log",
            f"{datetime.now()}: Updated task {task_name} for {','.join(target_accounts)}",
        )

        related = self._find_related_task_infos(task_name, target_accounts[0])
        return pick_task_write_response(
            related,
            target_accounts=target_accounts,
            aggregate_fn=self._aggregate_tasks,
            get_task_fn=lambda acc: self.get_task(task_name, account_name=acc),
            not_found_message=f"任务 {task_name} 更新后无法读取",
        )

    def rename_account_references(
        self,
        old_account_name: str,
        new_account_name: str,
    ) -> None:
        old_account_name = validate_storage_name(
            old_account_name,
            field_name="account_name",
        )
        new_account_name = validate_storage_name(
            new_account_name,
            field_name="account_name",
        )
        if old_account_name == new_account_name:
            return

        old_account_dir = self.signs_dir / old_account_name
        new_account_dir = self.signs_dir / new_account_name

        if old_account_dir.exists():
            self._move_storage_path(old_account_dir, new_account_dir)

        from backend.services.sign_task_config_build import apply_account_rename_to_config

        for config_path in self.signs_dir.glob("*/*/config.json"):
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
                continue
            if not isinstance(config, dict):
                continue

            if not apply_account_rename_to_config(config, old_account_name, new_account_name):
                continue

            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        safe_old = self._safe_history_key(old_account_name)
        safe_new = self._safe_history_key(new_account_name)
        for history_file in self.run_history_dir.glob(f"{safe_old}__*.json"):
            target_file = self.run_history_dir / history_file.name.replace(
                f"{safe_old}__",
                f"{safe_new}__",
                1,
            )
            try:
                raw_data = json.loads(history_file.read_text(encoding="utf-8"))
            except Exception:
                raw_data = None

            if isinstance(raw_data, list):
                for item in raw_data:
                    if (
                        isinstance(item, dict)
                        and str(item.get("account_name") or "").strip() == old_account_name
                    ):
                        item["account_name"] = new_account_name
                history_file.write_text(
                    json.dumps(raw_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            elif (
                isinstance(raw_data, dict)
                and str(raw_data.get("account_name") or "").strip() == old_account_name
            ):
                raw_data["account_name"] = new_account_name
                history_file.write_text(
                    json.dumps(raw_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            self._move_storage_path(history_file, target_file)

        for mapping_name in ("_active_logs", "_active_tasks", "_cleanup_tasks"):
            mapping = getattr(self, mapping_name)
            for key in list(mapping.keys()):
                account_name, task_name = key
                if account_name != old_account_name:
                    continue
                mapping[(new_account_name, task_name)] = mapping.pop(key)

        last_run_value = self._account_last_run_end.pop(old_account_name, None)
        if last_run_value is not None:
            self._account_last_run_end[new_account_name] = last_run_value

        try:
            rebuild_index_from_history_files(self.run_history_dir)
        except Exception as exc:
            _logger.debug("账号重命名后重建历史索引失败: %s", exc)

        self._refresh_tasks_cache_after_write()

    def delete_task(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        """Delete one task or one shared multi-account task set."""
        task_name = validate_storage_name(task_name, field_name="task_name")
        related_tasks = self._find_related_task_infos(task_name, account_name)
        if not related_tasks:
            return False

        task_dirs = self._iter_task_dirs(
            task_name,
            [str(task.get("account_name") or "") for task in related_tasks],
        )
        if not task_dirs:
            return False

        import shutil

        from backend.scheduler import remove_sign_task_job

        removed_paths: set[str] = set()
        for current_account, task_dir in task_dirs:
            resolved = str(task_dir.resolve())
            if resolved in removed_paths:
                continue
            if task_dir.exists():
                shutil.rmtree(task_dir)
            removed_paths.add(resolved)
            if current_account:
                remove_sign_task_job(current_account, task_name)

        self._refresh_tasks_cache_after_write()
        return True

