"""
backend.services.sign_task_history_ops (DEPRECATED):
向后兼容薄代理层。核心历史逻辑已全部迁移并深化至 SignTaskHistoryStore。
保留 SignTaskHistoryMixin 及相关重导出以兼容存量测试与外部引用，消除跨边界状态侵入。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.sign_task_history_format import (
    clamp_limit,
    normalize_and_trim_flow_logs,
)
from backend.services.sign_task_history_index import (
    ensure_index as ensure_history_index,
)
from backend.services.sign_task_history_index import (
    list_recent_from_index,
)
from backend.services.sign_task_history_io import (
    count_history_entries,
    load_history_entries,
    load_history_payload_from_file,
    patch_tasks_cache_last_run,
    safe_history_key,
)
from backend.services.sign_task_history_query import (
    collect_formatted_history_items,
    sort_history_items_desc,
)
from backend.services.sign_task_history_store import SignTaskHistoryStore
from backend.utils.atomic_io import (
    path_write_lock,
    read_json_safe,
    write_json_atomic,
)
from backend.utils.names import validate_storage_name
from backend.utils.task_logs import extract_last_target_message

_logger = logging.getLogger("backend.sign_task_history_ops")


class SignTaskHistoryMixin:
    """历史相关方法向后兼容 Mixin；历史领域业务委托至 SignTaskHistoryStore。"""

    @property
    def history_store(self) -> SignTaskHistoryStore:
        store = getattr(self, "_history_store_instance", None)
        if store is None or getattr(store, "history_dir", None) != getattr(
            self, "run_history_dir", None
        ):
            signs_dir = getattr(self, "signs_dir", None)
            store = SignTaskHistoryStore(
                self.run_history_dir,
                signs_dir,
                max_entries_per_file=getattr(self, "_history_max_entries", 50),
                max_flow_lines=getattr(self, "_history_max_flow_lines", 200),
                max_line_chars=getattr(self, "_history_max_line_chars", 500),
            )
            self._history_store_instance = store
        return store

    def _normalize_flow_logs(
        self, flow_logs: Optional[List[str]]
    ) -> tuple[List[str], bool, int]:
        return normalize_and_trim_flow_logs(
            flow_logs,
            repair=getattr(self, "_repair_mojibake", lambda s: s),
            max_lines=getattr(self, "_history_max_flow_lines", 200),
            max_line_chars=getattr(self, "_history_max_line_chars", 500),
        )

    def _load_history_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        return load_history_entries(
            self.run_history_dir, task_name, account_name=account_name
        )

    def _resolve_existing_history_file(
        self, task_name: str, account_name: str = ""
    ) -> Optional[Path]:
        return self.history_store.resolve_history_file(account_name, task_name)

    def _legacy_history_candidates(
        self, task_name: str, account_name: str
    ) -> List[Path]:
        return self.history_store.legacy_history_candidates(account_name, task_name)

    @staticmethod
    def _load_history_payload_from_file(history_file: Path) -> List[Any]:
        return load_history_payload_from_file(history_file)

    @staticmethod
    def _count_history_entries(data: Any) -> int:
        return count_history_entries(data)

    def _safe_history_key(self, name: str) -> str:
        return safe_history_key(name)

    def _history_file_path(self, task_name: str, account_name: str = "") -> Path:
        return self.history_store.get_history_file_path(account_name, task_name)

    def _set_task_last_run_metadata(
        self,
        task_name: str,
        account_name: str = "",
        last_run: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            task_dir = self._resolve_task_dir(task_name, account_name or None)
        except Exception:
            task_dir = None

        if task_dir is not None:
            config_file = task_dir / "config.json"
            if config_file.exists():
                try:
                    with path_write_lock(config_file):
                        config = read_json_safe(config_file, default=None)
                        if isinstance(config, dict):
                            if last_run:
                                config["last_run"] = last_run
                            else:
                                config.pop("last_run", None)
                            write_json_atomic(config_file, config)
                except Exception as exc:
                    _logger.warning(
                        "回写任务元数据 last_run 失败: %s (%s)", config_file, exc
                    )

        tasks_cache = getattr(self, "_tasks_cache", None)
        if tasks_cache is not None:
            for task in tasks_cache:
                if not isinstance(task, dict):
                    continue
                if (
                    task.get("name") != task_name
                    or task.get("account_name") != account_name
                ):
                    continue
                if last_run:
                    task["last_run"] = last_run
                else:
                    task.pop("last_run", None)
                break

    def _clear_task_last_run_metadata(
        self, task_name: str, account_name: str = ""
    ) -> None:
        try:
            task_dir = self._resolve_task_dir(task_name, account_name or None)
        except Exception:
            task_dir = None

        if task_dir is None:
            return

        config_file = task_dir / "config.json"
        if not config_file.exists():
            return

        try:
            config = read_json_safe(config_file, default=None)
            if not isinstance(config, dict) or "last_run" not in config:
                return
            del config["last_run"]
            write_json_atomic(config_file, config)
        except Exception as exc:
            _logger.debug("清理 last_run 元数据失败: %s (%s)", config_file, exc)

    def _get_last_run_info(
        self, task_dir: Path, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        history_file = self.history_store.resolve_history_file(
            account_name, task_dir.name
        )
        if history_file is None:
            return None
        try:
            data = read_json_safe(history_file, default=None)
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            return None
        except Exception:
            return None

    def _save_run_info(
        self,
        task_name: str,
        success: bool,
        message: str = "",
        account_name: str = "",
        flow_logs: Optional[List[str]] = None,
        workflow_path: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        store = self.history_store
        if hasattr(self, "_history_max_entries"):
            store.max_entries_per_file = self._history_max_entries
        if hasattr(self, "_history_max_flow_lines"):
            store.max_flow_lines = self._history_max_flow_lines
        if hasattr(self, "_history_max_line_chars"):
            store.max_line_chars = self._history_max_line_chars

        entry_payload = {
            "success": success,
            "message": message,
            "flow_logs": flow_logs,
            "workflow_path": workflow_path,
        }
        run_entry = store.record_run(
            account=account_name,
            task=task_name,
            entry=entry_payload,
            publish_event=True,
        )

        self._set_task_last_run_metadata(task_name, account_name, run_entry)

        patch_tasks_cache_last_run(
            getattr(self, "_tasks_cache", None),
            task_name=task_name,
            account_name=account_name,
            last_run=run_entry,
        )
        sync_fn = getattr(self, "_sync_tasks_list_ttl", None)
        if callable(sync_fn):
            sync_fn()
        return run_entry

    def get_recent_history_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = clamp_limit(limit, minimum=1, maximum=200)
        try:
            ensure_history_index(self.run_history_dir)
            indexed = list_recent_from_index(
                self.run_history_dir,
                limit=limit,
                prefer_memory=True,
            )
            if indexed is not None:
                return [
                    {
                        **item,
                        "created_at": item.get("created_at") or item.get("time") or "",
                        "flow_logs": item.get("flow_logs") or [],
                        "flow_truncated": bool(item.get("flow_truncated", False)),
                        "flow_line_count": int(item.get("flow_line_count") or 0),
                        "last_target_message": str(
                            item.get("last_target_message") or ""
                        ),
                        "bot_message": str(item.get("message") or ""),
                    }
                    for item in indexed
                ]
        except Exception as exc:
            _logger.debug("历史索引读取失败，回退全量扫描: %s", exc)

        recent: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        list_tasks = getattr(self, "list_tasks", None)
        tasks = (
            list_tasks(force_refresh=False, aggregate=False)
            if callable(list_tasks)
            else []
        )
        for task in tasks:
            task_name = str(task.get("name") or "").strip()
            account_name = str(task.get("account_name") or "").strip()
            if not task_name or not account_name:
                continue
            pair = (account_name, task_name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            history = self._load_history_entries(task_name, account_name=account_name)
            recent.extend(
                collect_formatted_history_items(
                    history[:limit],
                    task_name=task_name,
                    account_name=account_name,
                    repair=getattr(self, "_repair_mojibake", lambda s: s),
                    extract_last_target=extract_last_target_message,
                )
            )
        return sort_history_items_desc(recent, limit=limit)

    def get_filtered_history_logs(
        self,
        account_name: Optional[str] = None,
        date: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        limit = clamp_limit(limit, minimum=1, maximum=1000)
        normalized_account = (
            validate_storage_name(account_name, field_name="account_name")
            if account_name
            else None
        )
        normalized_date = str(date or "").strip()[:10]
        try:
            ensure_history_index(self.run_history_dir)
            prefer_memory = not normalized_account and not normalized_date
            indexed = list_recent_from_index(
                self.run_history_dir,
                limit=limit,
                account_name=normalized_account,
                date_prefix=normalized_date,
                prefer_memory=prefer_memory,
            )
            if indexed is not None:
                return [
                    {
                        **item,
                        "created_at": item.get("created_at") or item.get("time") or "",
                        "flow_logs": item.get("flow_logs") or [],
                        "flow_truncated": bool(item.get("flow_truncated", False)),
                        "flow_line_count": int(item.get("flow_line_count") or 0),
                        "last_target_message": str(
                            item.get("last_target_message") or ""
                        ),
                        "bot_message": str(item.get("message") or ""),
                    }
                    for item in indexed
                ]
        except Exception as exc:
            _logger.debug("历史索引按条件读取失败，回退全量扫描: %s", exc)

        recent: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()
        list_tasks = getattr(self, "list_tasks", None)
        tasks = (
            list_tasks(account_name=normalized_account)
            if normalized_account and callable(list_tasks)
            else list_tasks(force_refresh=False, aggregate=False)
            if callable(list_tasks)
            else []
        )
        for task in tasks:
            task_name = str(task.get("name") or "").strip()
            item_account = str(task.get("account_name") or "").strip()
            if not task_name or not item_account:
                continue
            pair = (item_account, task_name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            history = self._load_history_entries(task_name, account_name=item_account)
            recent.extend(
                collect_formatted_history_items(
                    history,
                    task_name=task_name,
                    account_name=item_account,
                    repair=getattr(self, "_repair_mojibake", lambda s: s),
                    extract_last_target=extract_last_target_message,
                    date_prefix=normalized_date,
                )
            )
        return sort_history_items_desc(recent, limit=limit)

    def get_account_history_logs(self, account_name: str) -> List[Dict[str, Any]]:
        return self.history_store.query_history(account=account_name)

    def get_history(
        self,
        account: Optional[str] = None,
        task: Optional[str] = None,
        limit: int = 50,
        date_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.history_store.query_history(
            account=account, task=task, limit=limit, date_filter=date_filter
        )

    def get_history_page(
        self,
        account: Optional[str] = None,
        task: Optional[str] = None,
        limit: int = 50,
        date_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.get_history(
            account=account, task=task, limit=limit, date_filter=date_filter
        )

    def get_task_history(
        self,
        task_name: str,
        account_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self.history_store.query_history(
            account=account_name, task=task_name, limit=limit
        )

    def get_history_log_detail(
        self, account_name: str, task_name: str, created_at: str
    ) -> Optional[Dict[str, Any]]:
        return self.history_store.get_history_entry(
            account=account_name, task=task_name, created_at=created_at
        )

    def get_history_detail(
        self, account: str, task: str, created_at: str
    ) -> Optional[Dict[str, Any]]:
        return self.history_store.get_history_entry(
            account=account, task=task, created_at=created_at
        )

    def delete_history_log(
        self, account_name: str, task_name: str, created_at: str
    ) -> bool:
        deleted = self.history_store.delete_history_entry(
            account=account_name, task=task_name, created_at=created_at
        )
        if deleted:
            latest = self.history_store.query_history(
                account=account_name, task=task_name, limit=1
            )
            latest_entry = latest[0] if latest else None
            self._set_task_last_run_metadata(task_name, account_name, latest_entry)
        return deleted

    def delete_history_item(self, account: str, task: str, created_at: str) -> bool:
        return self.delete_history_log(account, task, created_at)

    def clear_all_history_logs(self) -> Dict[str, int]:
        res = self.history_store.clear_history()
        list_tasks = getattr(self, "list_tasks", None)
        if callable(list_tasks):
            for t in list_tasks():
                t_name = str(t.get("name") or "")
                acc = str(t.get("account_name") or "")
                if t_name:
                    self._clear_task_last_run_metadata(t_name, acc)
        return res

    def clear_account_history_logs(self, account_name: str) -> Dict[str, int]:
        res = self.history_store.clear_history(account=account_name)
        list_tasks = getattr(self, "list_tasks", None)
        if callable(list_tasks):
            for t in list_tasks(account_name=account_name):
                t_name = str(t.get("name") or "")
                if t_name:
                    self._clear_task_last_run_metadata(t_name, account_name)
        return res

    def clear_task_history(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Dict[str, int]:
        res = self.history_store.clear_history(account=account_name, task=task_name)
        self._clear_task_last_run_metadata(task_name, account_name or "")
        return res

    def get_history_trends(self, days: int = 7) -> Dict[str, Any]:
        return self.history_store.get_history_trends(days=days)

    def _cleanup_old_logs(self):
        try:
            days = (
                self._history_max_age_days()
                if callable(getattr(self, "_history_max_age_days", None))
                else int(getattr(self, "_history_max_age_days", 30))
            )
        except Exception:
            days = 30
        return self.history_store.cleanup_expired(max_age_days=days)
