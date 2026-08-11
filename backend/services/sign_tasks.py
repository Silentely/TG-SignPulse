"""
签到任务服务层
提供签到任务的 CRUD 操作和执行功能
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from backend.core.config import get_settings
from backend.services.sign_task_backend import BackendUserSigner, TaskLogHandler
from backend.services.sign_task_config_inspect import (
    task_has_keyword_monitor,
    task_requires_updates,
)
from backend.services.sign_task_crud import SignTaskCrudMixin
from backend.services.sign_task_failure import (
    message_indicates_strong_failure,
)
from backend.services.sign_task_history_format import (
    clamp_limit,
)
from backend.services.sign_task_history_io import (
    cleanup_old_history_files,
)
from backend.services.sign_task_history_io import (
    history_file_path as history_file_path_io,
)
from backend.services.sign_task_history_io import (
    safe_history_key as safe_history_key_io,
)
from backend.services.sign_task_history_ops import SignTaskHistoryMixin
from backend.services.sign_task_history_query import (
    collect_formatted_history_items,
    sort_history_items_desc,
)
from backend.services.sign_task_message import (
    format_target_message_summary,
    message_matches_thread,
)
from backend.services.sign_task_run_status import (
    PHASE_STARTING,
    RUN_STATE_CANCELLED,
    RUN_STATE_FINISHED,
    RUN_STATE_RUNNING,
    RUN_STATE_TIMEOUT,
    build_run_status,
    build_runner_failure_result,
    idle_running_placeholder,
    is_timeout_error_message,
    make_task_key,
    resolve_stored_run_status,
    resolve_terminal_failure_category,
    summarize_active_run,
)
from backend.services.sign_task_text import repair_mojibake
from backend.utils.atomic_io import write_json_atomic
from backend.utils.cache import TTLCache
from backend.utils.names import validate_storage_name
from backend.utils.task_logs import extract_last_target_message
from backend.utils.tg_session import (
    list_account_names,
    resolve_effective_proxy,
)
from backend.utils.time import utc_now_iso
from tg_signer.async_utils import create_logged_task
from tg_signer.context_vars import (
    task_retry_count_var as _task_retry_count_var,  # noqa: F401
)
from tg_signer.utils import read_positive_int_env

settings = get_settings()

_service_logger = logging.getLogger("backend.sign_tasks")

# 向后兼容：外部若 from sign_tasks import BackendUserSigner / TaskLogHandler
__all__ = [
    "BackendUserSigner",
    "TaskLogHandler",
    "SignTaskService",
    "get_sign_task_service",
]


class SignTaskService(SignTaskHistoryMixin, SignTaskCrudMixin):
    """签到任务服务类（历史见 SignTaskHistoryMixin，CRUD 见 SignTaskCrudMixin）"""

    def __init__(self):
        from backend.core.config import get_settings

        settings = get_settings()
        self.workdir = settings.resolve_workdir()
        self.signs_dir = self.workdir / "signs"
        self.run_history_dir = self.workdir / "history"
        self.signs_dir.mkdir(parents=True, exist_ok=True)
        self.run_history_dir.mkdir(parents=True, exist_ok=True)
        _service_logger.info(
            "SignTaskService initialized, signs_dir=%s", self.signs_dir
        )
        self._active_logs: Dict[tuple[str, str], List[str]] = {}  # (account, task) -> logs
        self._active_tasks: Dict[tuple[str, str], bool] = {}  # (account, task) -> running
        self._cleanup_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._run_statuses: Dict[tuple[str, str], Dict[str, Any]] = {}
        self._run_status_cleanup_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._background_run_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._tasks_cache = None  # 兼容旧引用：list 或 None
        self._cache_refresh_deferred = 0  # >0 时挂起写后全量缓存刷新（批量写优化）
        self._cache_refresh_dirty = False  # defer 期间确有写后刷新被抑制时置 True
        self._cache_refresh_lock = threading.Lock()  # 保护计数器与脏位，兼容线程池路由并发
        # TTL 列表缓存（与 _tasks_cache 同步），避免长时间持有过期扫描结果
        list_ttl = float(os.getenv("SIGN_TASK_LIST_CACHE_TTL", "30") or "30")
        self._tasks_list_ttl = TTLCache(maxsize=2, ttl=max(list_ttl, 1.0))
        self._account_locks: Dict[str, asyncio.Lock] = {}  # 账号锁
        self._account_last_run_end: Dict[str, float] = {}  # 账号最后一次结束时间
        # 冷却/历史天数通过 property 读 runtime_settings（面板可覆盖 env）
        self._history_max_entries = read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_ENTRIES", 100, 10
        )
        self._history_max_flow_lines = read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_FLOW_LINES", 5000, 20
        )
        self._history_max_line_chars = read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_LINE_CHARS", 2000, 80
        )
        self._max_account_last_run_entries = 100  # Bound account tracking
        self._cleanup_old_logs()

    @property
    def _account_cooldown_seconds(self) -> int:
        from backend.services.runtime_settings import get_account_cooldown

        return get_account_cooldown()

    @property
    def _history_max_age_days(self) -> int:
        from backend.services.runtime_settings import get_history_max_age_days

        return get_history_max_age_days()

    def _prune_stale_entries(self) -> None:
        """Remove stale entries from internal tracking dicts to prevent memory growth."""
        # Prune _active_tasks entries that are False (task completed)
        stale_keys = [k for k, v in self._active_tasks.items() if not v]
        for key in stale_keys:
            self._active_tasks.pop(key, None)

        # Prune _active_logs for tasks that are no longer running and have no cleanup pending
        for key in list(self._active_logs.keys()):
            if not self._active_tasks.get(key, False) and key not in self._cleanup_tasks:
                self._active_logs.pop(key, None)

        # Prune completed background run tasks
        done_keys = [k for k, t in self._background_run_tasks.items() if t.done()]
        for key in done_keys:
            self._background_run_tasks.pop(key, None)

        # Prune completed cleanup tasks
        done_cleanup = [k for k, t in self._cleanup_tasks.items() if t.done()]
        for key in done_cleanup:
            self._cleanup_tasks.pop(key, None)

        done_status_cleanup = [k for k, t in self._run_status_cleanup_tasks.items() if t.done()]
        for key in done_status_cleanup:
            self._run_status_cleanup_tasks.pop(key, None)

        # 终态 run status：若已无 active/background，尽快释放（保留 cleanup 定时器负责延迟删除时跳过）
        from backend.services.sign_task_run_status import is_terminal_run_state

        for key, status in list(self._run_statuses.items()):
            if key in self._run_status_cleanup_tasks:
                continue
            if self._active_tasks.get(key, False):
                continue
            if key in self._background_run_tasks:
                continue
            if is_terminal_run_state(str((status or {}).get("state") or "")):
                # 终态已落盘历史后可保留一小段供前端轮询；此处仅在无 cleanup 挂接时清理孤儿
                finished_at = str((status or {}).get("finished_at") or "")
                if not finished_at:
                    self._run_statuses.pop(key, None)

        # Bound _account_last_run_end to prevent unbounded growth
        if len(self._account_last_run_end) > self._max_account_last_run_entries:
            # Keep only the most recent entries
            sorted_entries = sorted(
                self._account_last_run_end.items(), key=lambda x: x[1], reverse=True
            )
            self._account_last_run_end = dict(
                sorted_entries[: self._max_account_last_run_entries]
            )

    @staticmethod
    def _task_requires_updates(task_config: Optional[Dict[str, Any]]) -> bool:
        return task_requires_updates(task_config)

    @staticmethod
    def _task_has_keyword_monitor(task_config: Optional[Dict[str, Any]]) -> bool:
        return task_has_keyword_monitor(task_config)

    @staticmethod
    def _message_matches_thread(message: Any, chat_config: Dict[str, Any]) -> bool:
        return message_matches_thread(message, chat_config)

    @staticmethod
    def _format_target_message_summary(message: Any) -> str:
        return format_target_message_summary(message)

    @classmethod
    def _message_indicates_strong_failure(cls, text: str) -> bool:
        return message_indicates_strong_failure(text)

    def invalidate_tasks_cache(self) -> None:
        """主动失效任务列表缓存（配置导入/批量变更后调用）。"""
        self._tasks_cache = None
        try:
            self._tasks_list_ttl.clear()
        except Exception as exc:
            _service_logger.debug("清除任务列表 TTL 缓存失败: %s", exc)

    def _sync_tasks_list_ttl(self) -> None:
        """将当前 _tasks_cache 写回 TTL 槽，避免只清 list 却残留 TTL 旧值。"""
        if self._tasks_cache is None:
            try:
                self._tasks_list_ttl.clear()
            except Exception as exc:
                _service_logger.debug("同步清空任务列表 TTL 失败: %s", exc)
            return
        try:
            self._tasks_list_ttl.set("all", self._tasks_cache)
        except Exception as exc:
            _service_logger.debug("同步任务列表 TTL 失败: %s", exc)

    def _refresh_tasks_cache_after_write(self) -> None:
        """CRUD 写盘后强制重扫一次并填充缓存（替代仅置 None）。"""
        # getattr 兜底：__new__ 构造的实例（如单测）未走 __init__
        if getattr(self, "_cache_refresh_deferred", 0):
            # defer 期间仅标记脏位，由 defer_cache_refresh 退出时统一补刷
            self._cache_refresh_dirty = True
            return
        self.list_tasks(force_refresh=True, aggregate=False)

    @contextmanager
    def defer_cache_refresh(self):
        """批量写期间挂起每次写后的全量缓存刷新，退出时统一补刷一次。

        - 计数与脏位经锁保护：批量路由跑在事件循环，单任务路由跑在线程池，
          两者并发进入时自增/自减不会被拆开；
        - 仅当上下文中确有写后刷新被抑制（脏位）才补刷，纯 RUN 批量不做无谓 IO；
        - 补刷失败降级为 warning：写已落盘，不应让请求失败或遮蔽体内异常。
        """
        with self._cache_refresh_lock:
            self._cache_refresh_deferred = getattr(self, "_cache_refresh_deferred", 0) + 1
        try:
            yield
        finally:
            should_flush = False
            with self._cache_refresh_lock:
                self._cache_refresh_deferred -= 1
                if self._cache_refresh_deferred == 0 and getattr(
                    self, "_cache_refresh_dirty", False
                ):
                    self._cache_refresh_dirty = False
                    should_flush = True
            if should_flush:
                try:
                    self.list_tasks(force_refresh=True, aggregate=False)
                except Exception as exc:
                    _service_logger.warning(
                        "批量写退出时补刷任务缓存失败，交由下次访问惰性刷新: %s",
                        exc,
                    )

    async def _fetch_last_target_message_from_chat_history(
        self,
        signer: BackendUserSigner,
        task_config: Optional[Dict[str, Any]],
    ) -> str:
        if signer is None or not isinstance(task_config, dict):
            return ""

        chats = task_config.get("chats")
        if not isinstance(chats, list) or not chats:
            return ""

        history_limit = read_positive_int_env(
            "SIGN_TASK_LAST_TARGET_HISTORY_LIMIT",
            8,
            1,
        )
        best_text = ""
        best_timestamp = None
        fallback_text = ""
        fallback_timestamp = None

        # Skip if client was already terminated/disconnected after task finished
        try:
            app = signer.app
            if app is None:
                return ""
            # Check if client is still usable (not terminated)
            if not getattr(app, "is_connected", False) and not getattr(app, "is_initialized", False):
                # Client already torn down - don't try to re-enter
                return ""
        except Exception:
            return ""

        try:
            async with signer.app:
                for chat in chats:
                    if not isinstance(chat, dict):
                        continue
                    chat_id = chat.get("chat_id")
                    if chat_id in (None, ""):
                        continue

                    try:
                        # 历史按时间降序返回；逐条评估候选，跨 chat 聚合取最新非自己消息
                        async for message in signer.app.get_chat_history(
                            chat_id,
                            limit=history_limit,
                        ):
                            if not self._message_matches_thread(message, chat):
                                continue

                            candidate = self._format_target_message_summary(message)
                            if not candidate:
                                continue

                            message_time = getattr(message, "date", None)
                            from_user = getattr(message, "from_user", None)
                            is_self = bool(getattr(from_user, "is_self", False))

                            if not is_self:
                                if best_timestamp is None or (
                                    message_time is not None
                                    and message_time > best_timestamp
                                ):
                                    best_text = candidate
                                    best_timestamp = message_time
                            elif fallback_timestamp is None or (
                                message_time is not None
                                and message_time > fallback_timestamp
                            ):
                                fallback_text = candidate
                                fallback_timestamp = message_time
                    except Exception as exc:
                        _service_logger.debug("解析目标消息候选失败，跳过: %s", exc)
                        continue
        except Exception:
            # Silently ignore errors like "Client is already terminated"
            pass

        return best_text or fallback_text

    def _cleanup_old_logs(self):
        """清理超过保留天数的历史文件（SIGN_TASK_HISTORY_MAX_AGE_DAYS）。"""
        cleanup_old_history_files(
            self.run_history_dir, max_age_days=self._history_max_age_days
        )

    def _safe_history_key(self, name: str) -> str:
        return safe_history_key_io(name)

    def _history_file_path(self, task_name: str, account_name: str = "") -> Path:
        return history_file_path_io(self.run_history_dir, task_name, account_name)

    @staticmethod
    def _move_storage_path(source: Path, target: Path) -> None:
        if not source.exists():
            return

        source_resolved = str(source.resolve()).lower()
        target_resolved = str(target.resolve()).lower()
        if source_resolved == target_resolved:
            if str(source) == str(target):
                return
            temp_target = source.with_name(f"{source.name}.__rename_tmp__{uuid.uuid4().hex}")
            source.replace(temp_target)
            temp_target.replace(target)
            return

        if target.exists():
            raise ValueError(f"目标路径已存在: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

    def _known_account_names(self) -> List[str]:
        names = set()
        try:
            names.update(name for name in list_account_names() if name)
        except Exception as exc:
            _service_logger.debug("从数据库读取账号名失败: %s", exc)

        try:
            session_dir = settings.resolve_session_dir()
            for pattern in ("*.session", "*.session_string"):
                for path in session_dir.glob(pattern):
                    if path.stem:
                        names.add(path.stem)
        except Exception as exc:
            _service_logger.debug("扫描会话目录获取账号名失败: %s", exc)

        return sorted(names)

    def _infer_account_name(
        self, config: Dict[str, Any], task_dir: Optional[Path] = None
    ) -> str:
        account_name = config.get("account_name")
        if isinstance(account_name, str) and account_name.strip():
            return account_name.strip()

        if task_dir is not None and task_dir.parent != self.signs_dir:
            return task_dir.parent.name

        known_accounts = self._known_account_names()
        if "my_account" in known_accounts:
            return "my_account"
        if len(known_accounts) == 1:
            return known_accounts[0]
        return ""

    def _resolve_task_dir(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Path]:
        task_name = validate_storage_name(task_name, field_name="task_name")
        if account_name:
            account_name = validate_storage_name(account_name, field_name="account_name")
            account_task_dir = self.signs_dir / account_name / task_name
            if (account_task_dir / "config.json").exists():
                return account_task_dir

            legacy_task_dir = self.signs_dir / task_name
            config_file = legacy_task_dir / "config.json"
            if not config_file.exists():
                return None
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                return None
            if self._infer_account_name(config, legacy_task_dir) == account_name:
                return legacy_task_dir
            return None

        legacy_task_dir = self.signs_dir / task_name
        if (legacy_task_dir / "config.json").exists():
            return legacy_task_dir

        try:
            for acc_dir in self.signs_dir.iterdir():
                nested_task_dir = acc_dir / task_name
                if acc_dir.is_dir() and (nested_task_dir / "config.json").exists():
                    return nested_task_dir
        except Exception:
            return None
        return None

    @staticmethod
    def _normalize_account_names(
        account_names: Optional[Iterable[str]] = None,
        account_name: Optional[str] = None,
    ) -> List[str]:
        ordered: List[str] = []

        def _append(value: Optional[str]) -> None:
            if not isinstance(value, str):
                return
            # Preserve wildcard marker
            if value.strip() == "*":
                if "*" not in ordered:
                    ordered.append("*")
                return
            cleaned = validate_storage_name(value, field_name="account_name")
            if cleaned and cleaned not in ordered:
                ordered.append(cleaned)

        if account_names:
            for item in account_names:
                _append(item)
        _append(account_name)
        return ordered

    def _expand_account_names(self, account_names: List[str]) -> List[str]:
        """Expand wildcard '*' to all currently registered accounts."""
        if "*" in account_names:
            all_accounts = list_account_names()
            return all_accounts if all_accounts else account_names
        return account_names

    def _expand_wildcard_tasks(self) -> None:
        """
        For tasks with account_names: ["*"], create task directories
        for any accounts that don't have them yet.
        """
        if not self.signs_dir.exists():
            return
        all_accounts = list_account_names()
        if not all_accounts:
            return

        # Scan all existing task configs looking for wildcard
        seen_wildcard_tasks: List[tuple] = []  # (task_name, config, source_dir)
        for account_dir in self.signs_dir.iterdir():
            if not account_dir.is_dir():
                continue
            for task_dir in account_dir.iterdir():
                if not task_dir.is_dir():
                    continue
                config_file = task_dir / "config.json"
                if not config_file.exists():
                    continue
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    stored_names = config.get("account_names", [])
                    if isinstance(stored_names, list) and "*" in stored_names:
                        seen_wildcard_tasks.append((task_dir.name, config, task_dir))
                except Exception as exc:
                    _service_logger.debug("读取通配任务配置失败，跳过: %s (%s)", config_file, exc)
                    continue

        # For each wildcard task, ensure all accounts have a directory
        for task_name, base_config, _ in seen_wildcard_tasks:
            for acc in all_accounts:
                target_dir = self.signs_dir / acc / task_name
                if target_dir.exists():
                    continue
                # Create task for this account
                target_dir.mkdir(parents=True, exist_ok=True)
                new_config = dict(base_config)
                new_config["account_name"] = acc
                try:
                    write_json_atomic(target_dir / "config.json", new_config)
                except Exception as exc:
                    # 该账号的通配任务实际未生成，影响签到调度，必须留痕
                    _service_logger.warning(
                        "为账号 %s 写入通配任务配置失败: %s (%s)", acc, target_dir, exc
                    )

        self._refresh_tasks_cache_after_write()

    def _resolve_account_names_from_config(
        self,
        config: Dict[str, Any],
        task_dir: Optional[Path] = None,
        resolved_account_name: Optional[str] = None,
    ) -> List[str]:
        names = self._normalize_account_names(config.get("account_names"))
        if names:
            return names
        fallback = resolved_account_name or self._infer_account_name(config, task_dir)
        return self._normalize_account_names(account_name=fallback)

    def _build_task_response(
        self,
        *,
        task_name: str,
        primary_account_name: str,
        account_names: List[str],
        sign_at: str,
        chats: List[Dict[str, Any]],
        random_seconds: int,
        sign_interval: int,
        enabled: bool = True,
        last_run: Optional[Dict[str, Any]] = None,
        execution_mode: str = "fixed",
        range_start: str = "",
        range_end: str = "",
        notify_on_failure: bool = True,
        notify_on_success: bool = True,
        task_group_id: str = "",
        last_run_account_name: str = "",
        retry_count: int = 3,
    ) -> Dict[str, Any]:
        normalized_accounts = self._normalize_account_names(
            account_names, primary_account_name
        )
        return {
            "name": task_name,
            # Keep the owning account on raw task records. Aggregated task views
            # intentionally collapse to the first linked account elsewhere.
            "account_name": primary_account_name,
            "account_names": normalized_accounts,
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
            "chats": chats,
            "enabled": enabled,
            "last_run": last_run,
            "execution_mode": execution_mode,
            "range_start": range_start,
            "range_end": range_end,
            "notify_on_failure": notify_on_failure,
            "notify_on_success": notify_on_success,
            "task_group_id": task_group_id,
            "last_run_account_name": last_run_account_name,
            "retry_count": retry_count,
        }

    def _aggregate_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from backend.services.sign_task_group import aggregate_tasks

        return aggregate_tasks(
            tasks,
            normalize_account_names=lambda names, primary=None: self._normalize_account_names(
                names, primary
            ),
        )

    def _find_related_task_infos(
        self, task_name: str, account_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from backend.services.sign_task_group import filter_related_task_infos

        raw_tasks = self.list_tasks(force_refresh=True, aggregate=False)
        return filter_related_task_infos(
            raw_tasks,
            task_name,
            account_name,
            normalize_account_names=lambda names, primary=None: self._normalize_account_names(
                names, primary
            ),
        )

    def _iter_task_dirs(
        self, task_name: str, account_names: Iterable[str]
    ) -> List[tuple[str, Path]]:
        dirs: List[tuple[str, Path]] = []
        for name in self._normalize_account_names(account_names):
            task_dir = self._resolve_task_dir(task_name, name)
            if task_dir is not None:
                dirs.append((name, task_dir))
        return dirs

    @staticmethod
    def _repair_mojibake(text: str) -> str:
        return repair_mojibake(text)

    # 历史查询/删除/落盘：见 SignTaskHistoryMixin

    def _append_scheduler_log(self, filename: str, message: str) -> None:
        try:
            logs_dir = settings.resolve_logs_dir()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / filename
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f'{message}\n')
        except OSError as e:
            _service_logger.warning(
                'Failed to write scheduler log %s: %s', filename, e
            )

    def _get_effective_proxy(self, account_name: str) -> Optional[str]:
        try:
            from backend.services.config import get_config_service

            global_proxy = get_config_service().get_global_proxy()
        except Exception as exc:
            # 读取全局配置失败时降级为无全局代理，但需留下日志便于排查
            _service_logger.warning(
                "读取全局代理配置失败，降级为无全局代理 (account=%s): %s",
                account_name,
                exc,
            )
            global_proxy = None
        return resolve_effective_proxy(account_name, global_proxy=global_proxy)

    def get_task_history_logs(
        self, task_name: str, account_name: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        limit = clamp_limit(limit, minimum=1, maximum=200)

        if account_name:
            history = self._load_history_entries(task_name, account_name=account_name)
            result: List[Dict[str, Any]] = []
            try:
                from backend.services.keyword_monitor import get_keyword_monitor_service

                monitor_entry = get_keyword_monitor_service().get_task_history_entry(
                    task_name,
                    account_name,
                )
                if monitor_entry:
                    result.append(monitor_entry)
            except Exception as exc:
                _service_logger.debug(
                    "获取监控历史条目失败 %s/%s: %s", account_name, task_name, exc
                )

            result.extend(
                collect_formatted_history_items(
                    history[:limit],
                    task_name=task_name,
                    account_name=str(account_name),
                    repair=self._repair_mojibake,
                    extract_last_target=extract_last_target_message,
                    prefer_entry_account=True,
                )
            )
            return result

        merged: List[Dict[str, Any]] = []
        task = self.get_task(task_name, aggregate=True)
        if not task:
            return []

        for current_account in self._normalize_account_names(
            task.get("account_names"), task.get("account_name")
        ):
            merged.extend(
                self.get_task_history_logs(
                    task_name=task_name,
                    account_name=current_account,
                    limit=limit,
                )
            )

        return sort_history_items_desc(merged, limit=limit)

    def list_tasks(
        self,
        account_name: Optional[str] = None,
        force_refresh: bool = False,
        aggregate: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return sign tasks, optionally grouped by shared task set."""
        tasks: List[Dict[str, Any]]
        if not force_refresh:
            ttl_hit = self._tasks_list_ttl.get("all")
            if ttl_hit is not None:
                self._tasks_cache = ttl_hit
                tasks = ttl_hit
            elif self._tasks_cache is not None:
                tasks = self._tasks_cache
            else:
                tasks = []
                force_refresh = True
        else:
            tasks = []

        if force_refresh or not tasks:
            tasks = []
            base_dir = self.signs_dir

            _service_logger.debug("扫描任务目录: %s", base_dir)
            try:
                for account_path in base_dir.iterdir():
                    if not account_path.is_dir():
                        continue

                    if (account_path / "config.json").exists():
                        task_info = self._load_task_config(account_path)
                        if task_info:
                            tasks.append(task_info)
                        continue

                    for task_dir in account_path.iterdir():
                        if not task_dir.is_dir():
                            continue

                        task_info = self._load_task_config(task_dir)
                        if task_info:
                            tasks.append(task_info)

                self._tasks_cache = sorted(
                    tasks, key=lambda item: (item["account_name"], item["name"])
                )
                self._tasks_list_ttl.set("all", self._tasks_cache)
                tasks = self._tasks_cache
            except Exception as e:
                _service_logger.debug("扫描任务出错: %s", e)
                return []

        if account_name:
            tasks = [
                task for task in tasks if str(task.get("account_name") or "") == account_name
            ]

        if aggregate:
            tasks = self._aggregate_tasks(tasks)
        return self._attach_active_runs(tasks)

    def _attach_active_runs(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为任务列表挂载轻量 active_run 摘要。"""
        result: List[Dict[str, Any]] = []
        for task in tasks:
            item = dict(task)
            item["active_run"] = self._resolve_active_run_for_task(item)
            result.append(item)
        return result

    def _resolve_active_run_for_task(
        self, task: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        task_name = str(task.get("name") or "")
        if not task_name:
            return None
        candidates: List[str] = []
        for name in task.get("account_names") or []:
            if name and name != "*":
                candidates.append(str(name))
        primary = str(task.get("account_name") or "")
        if primary and primary != "*" and primary not in candidates:
            candidates.insert(0, primary)

        best: Optional[Dict[str, Any]] = None
        best_started = ""
        for acc in candidates:
            status = self._run_statuses.get(self._task_key(acc, task_name))
            summary = summarize_active_run(status)
            if not summary:
                continue
            started = str(summary.get("started_at") or "")
            if best is None or started > best_started:
                best = summary
                best_started = started
        return best

    def list_active_runs(self) -> List[Dict[str, Any]]:
        """返回内存中 state=running 的 run 摘要列表。"""
        runs: List[Dict[str, Any]] = []
        for status in self._run_statuses.values():
            summary = summarize_active_run(status)
            if summary:
                runs.append(summary)
        runs.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
        if len(runs) > 100:
            _service_logger.warning("活跃运行列表被截断: %s", len(runs))
            runs = runs[:100]
        return runs

    def _load_task_config(
        self, task_dir: Path, *, return_raw: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Load one task config and normalize multi-account metadata.

        return_raw=True 时同时返回磁盘原始 dict（保留 retry_count 键存在性等
        归一化会丢失的信息），避免调用方二次读盘。
        """
        config_file = task_dir / "config.json"
        if not config_file.exists():
            return (None, None) if return_raw else None

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            resolved_account_name = self._infer_account_name(config, task_dir)
            resolved_account_names = self._resolve_account_names_from_config(
                config,
                task_dir=task_dir,
                resolved_account_name=resolved_account_name,
            )

            last_run = config.get("last_run")
            if not last_run:
                last_run = self._get_last_run_info(
                    task_dir, account_name=resolved_account_name
                )

            normalized = self._build_task_response(
                task_name=task_dir.name,
                primary_account_name=resolved_account_name,
                account_names=resolved_account_names,
                sign_at=config.get("sign_at", ""),
                chats=config.get("chats", []),
                random_seconds=config.get("random_seconds", 0),
                sign_interval=config.get("sign_interval", 1),
                enabled=config.get("enabled", True),
                last_run=last_run,
                execution_mode=config.get("execution_mode", "fixed"),
                range_start=config.get("range_start", ""),
                range_end=config.get("range_end", ""),
                notify_on_failure=config.get("notify_on_failure", True),
                notify_on_success=config.get("notify_on_success", True),
                task_group_id=str(config.get("task_group_id") or ""),
                last_run_account_name=str(
                    (last_run or {}).get("account_name") or resolved_account_name
                ),
                retry_count=int(config.get("retry_count", 3)),
            )
            if return_raw:
                return normalized, config
            return normalized
        except Exception:
            return (None, None) if return_raw else None

    def get_task(
        self,
        task_name: str,
        account_name: Optional[str] = None,
        aggregate: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Get one task, optionally as an aggregated shared-task view."""
        if aggregate and not account_name:
            related = self._find_related_task_infos(task_name)
            if not related:
                return None
            grouped = self._aggregate_tasks(related)
            task = grouped[0] if grouped else None
        else:
            task_dir = self._resolve_task_dir(task_name, account_name)
            if task_dir is None:
                return None
            task = self._load_task_config(task_dir)
        if not task:
            return None
        out = dict(task)
        out["active_run"] = self._resolve_active_run_for_task(out)
        return out

    # CRUD: create/clone/update/rename/delete 见 SignTaskCrudMixin


    async def get_account_chats(
        self, account_name: str, force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """获取账号的 Chat 列表（带缓存）。"""
        from backend.services.sign_task_chats import get_account_chats_cached

        return await get_account_chats_cached(
            account_name,
            signs_dir=self.signs_dir,
            force_refresh=force_refresh,
            refresh_fn=self.refresh_account_chats,
            validate_name=validate_storage_name,
        )

    def search_account_chats(
        self,
        account_name: str,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """通过缓存搜索账号的 Chat 列表（不触发全量 get_dialogs）。"""
        from backend.services.sign_task_chats import search_account_chats_cached

        return search_account_chats_cached(
            account_name,
            query,
            signs_dir=self.signs_dir,
            limit=limit,
            offset=offset,
            validate_name=validate_storage_name,
        )

    @staticmethod
    def _is_invalid_session_error(err: Exception) -> bool:
        from backend.services.sign_task_chats import is_invalid_session_error

        return is_invalid_session_error(err)

    async def refresh_account_chats(self, account_name: str) -> List[Dict[str, Any]]:
        """连接 Telegram 并刷新 Chat 列表。"""
        from backend.services.sign_task_chats import (
            refresh_account_chats as refresh_account_chats_impl,
        )

        return await refresh_account_chats_impl(
            account_name,
            signs_dir=self.signs_dir,
            get_effective_proxy=self._get_effective_proxy,
            account_locks=self._account_locks,
            validate_name=validate_storage_name,
        )

    def _task_key(self, account_name: str, task_name: str) -> tuple[str, str]:
        return make_task_key(account_name, task_name)

    def _find_task_keys(self, task_name: str) -> List[tuple[str, str]]:
        return [key for key in self._active_logs.keys() if key[1] == task_name]

    def get_active_logs(
        self, task_name: str, account_name: Optional[str] = None
    ) -> List[str]:
        """获取正在运行任务的日志"""
        monitor_logs: List[str] = []
        try:
            from backend.services.keyword_monitor import get_keyword_monitor_service

            monitor_logs = get_keyword_monitor_service().get_task_logs(
                task_name,
                account_name,
            )
        except Exception as exc:
            _service_logger.debug(
                "读取关键词监听日志失败 task=%s account=%s: %s",
                task_name,
                account_name,
                exc,
            )
            monitor_logs = []

        if account_name:
            logs = list(self._active_logs.get(self._task_key(account_name, task_name), []))
            return self._merge_active_and_monitor_logs(logs, monitor_logs)
        # 兼容旧接口：返回第一个同名任务的日志
        for key in self._find_task_keys(task_name):
            logs = list(self._active_logs.get(key, []))
            return self._merge_active_and_monitor_logs(logs, monitor_logs)
        return list(monitor_logs)

    @staticmethod
    def _merge_active_and_monitor_logs(
        active_logs: List[str], monitor_logs: List[str]
    ) -> List[str]:
        """合并任务实时日志与关键词后台监听日志。"""
        if not monitor_logs:
            return list(active_logs)
        merged = list(active_logs)
        if merged:
            merged.append("---- 关键词后台监听日志 ----")
        merged.extend(monitor_logs)
        return merged

    def _set_run_status(
        self,
        account_name: str,
        task_name: str,
        *,
        run_id: str,
        state: str,
        success: Optional[bool] = None,
        error: str = "",
        output: str = "",
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        phase: Optional[str] = None,
        phase_detail: str = "",
        wait_seconds: Optional[float] = None,
        failure_category: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        retry_count_effective: Optional[int] = None,
        preserve_started_at: bool = True,
    ) -> Dict[str, Any]:
        task_key = self._task_key(account_name, task_name)
        prev = self._run_statuses.get(task_key) or {}
        # 同 run 内默认保留 started_at / 已写入的 timeout/retry，避免 phase 刷新丢字段
        if preserve_started_at and not started_at and prev.get("run_id") == run_id:
            started_at = prev.get("started_at")
        if timeout_seconds is None and prev.get("run_id") == run_id:
            timeout_seconds = prev.get("timeout_seconds")
        if retry_count_effective is None and prev.get("run_id") == run_id:
            retry_count_effective = prev.get("retry_count_effective")
        status = build_run_status(
            run_id=run_id,
            state=state,
            success=success,
            error=error,
            output=output,
            started_at=started_at,
            finished_at=finished_at,
            default_started_at=utc_now_iso(),
            phase=phase,
            phase_detail=phase_detail,
            wait_seconds=wait_seconds,
            account_name=account_name,
            task_name=task_name,
            failure_category=failure_category,
            timeout_seconds=timeout_seconds,
            retry_count_effective=retry_count_effective,
        )
        self._run_statuses[task_key] = status
        return dict(status)

    def _update_run_phase(
        self,
        account_name: str,
        task_name: str,
        *,
        run_id: Optional[str],
        phase: str,
        phase_detail: str = "",
        wait_seconds: Optional[float] = None,
        timeout_seconds: Optional[float] = None,
        retry_count_effective: Optional[int] = None,
    ) -> None:
        """仅在有 run_id 时推进 phase（保持 state=running）。"""
        if not run_id:
            return
        self._set_run_status(
            account_name,
            task_name,
            run_id=run_id,
            state=RUN_STATE_RUNNING,
            phase=phase,
            phase_detail=phase_detail,
            wait_seconds=wait_seconds,
            timeout_seconds=timeout_seconds,
            retry_count_effective=retry_count_effective,
        )

    def _schedule_run_status_cleanup(self, account_name: str, task_name: str) -> None:
        task_key = self._task_key(account_name, task_name)
        old_cleanup_task = self._run_status_cleanup_tasks.get(task_key)
        if old_cleanup_task and not old_cleanup_task.done():
            old_cleanup_task.cancel()

        cleanup_task: Optional[Any] = None

        async def cleanup() -> None:
            try:
                await asyncio.sleep(600)
                if not self._active_tasks.get(task_key):
                    self._run_statuses.pop(task_key, None)
            finally:
                # 仅当自身仍是注册条目时才移除，避免被取消的旧任务
                # 在下一轮事件循环执行 finally 时误删新注册的清理任务
                if self._run_status_cleanup_tasks.get(task_key) is cleanup_task:
                    self._run_status_cleanup_tasks.pop(task_key, None)

        cleanup_task = create_logged_task(
            cleanup(),
            logger=_service_logger,
            description=f"run status cleanup {account_name}/{task_name}",
        )
        self._run_status_cleanup_tasks[task_key] = cleanup_task

    async def start_task_run(self, account_name: str, task_name: str) -> Dict[str, Any]:
        account_name = validate_storage_name(account_name, field_name="account_name")
        task_name = validate_storage_name(task_name, field_name="task_name")

        task_key = self._task_key(account_name, task_name)
        existing_status = self._run_statuses.get(task_key)
        if self._active_tasks.get(task_key):
            if existing_status:
                return dict(existing_status)
            return idle_running_placeholder(started_at=utc_now_iso())

        task = self.get_task(task_name, account_name=account_name)
        if not task:
            raise ValueError(f"Task {task_name} does not exist or cannot be loaded")

        run_id = uuid.uuid4().hex
        started_at = utc_now_iso()
        status = self._set_run_status(
            account_name,
            task_name,
            run_id=run_id,
            state=RUN_STATE_RUNNING,
            success=None,
            error="",
            output="",
            started_at=started_at,
            finished_at=None,
            phase=PHASE_STARTING,
            phase_detail="任务已启动",
            preserve_started_at=False,
        )

        async def runner() -> None:
            result: Dict[str, Any]
            state = RUN_STATE_FINISHED
            try:
                result = await self.run_task_with_logs(account_name, task_name, run_id=run_id)
                if result.get("timed_out") or is_timeout_error_message(
                    str(result.get("error") or "")
                ):
                    state = RUN_STATE_TIMEOUT
            except asyncio.CancelledError:
                state = RUN_STATE_CANCELLED
                result = build_runner_failure_result(cancelled=True)
            except Exception as exc:
                result = build_runner_failure_result(error=str(exc) or "")
                if result.get("timed_out"):
                    state = RUN_STATE_TIMEOUT

            current_status = self._run_statuses.get(task_key)
            if current_status and current_status.get("run_id") == run_id:
                success = bool(result.get("success", False))
                error = str(result.get("error") or "")
                output = str(result.get("output") or "")
                category = resolve_terminal_failure_category(
                    state=state,
                    success=success,
                    result_category=result.get("failure_category"),
                    error=error,
                    output=output,
                )
                self._set_run_status(
                    account_name,
                    task_name,
                    run_id=run_id,
                    state=state,
                    success=success,
                    error=error,
                    output=output,
                    started_at=started_at,
                    finished_at=utc_now_iso(),
                    phase=None,
                    failure_category=category,
                )
                self._schedule_run_status_cleanup(account_name, task_name)
            self._background_run_tasks.pop(task_key, None)

        background_task = create_logged_task(
            runner(),
            logger=_service_logger,
            description=f"sign task run {account_name}/{task_name}",
        )
        self._background_run_tasks[task_key] = background_task
        return status

    def cancel_task_run(
        self,
        account_name: str,
        task_name: str,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """取消后台进行中的任务运行（协作式 cancel asyncio.Task）。"""
        from backend.services.sign_task_run_status import (
            build_cancel_run_response,
            is_run_id_mismatch,
        )

        account_name = validate_storage_name(account_name, field_name="account_name")
        task_name = validate_storage_name(task_name, field_name="task_name")
        task_key = self._task_key(account_name, task_name)

        status = self._run_statuses.get(task_key)
        if is_run_id_mismatch(status, run_id):
            return build_cancel_run_response(
                ok=False,
                cancelled=False,
                error="run_id 与当前运行不匹配",
                status=status,
                requested_run_id=run_id,
            )

        bg = self._background_run_tasks.get(task_key)
        if not bg or bg.done():
            if self._active_tasks.get(task_key):
                # 同步 run 路径可能无 background task；仅标记无法取消
                return build_cancel_run_response(
                    ok=False,
                    cancelled=False,
                    error="任务正在执行但无可取消的后台句柄（可能为同步调用）",
                    status=status,
                )
            return build_cancel_run_response(
                ok=False,
                cancelled=False,
                error="当前没有进行中的运行",
                status=status,
            )

        bg.cancel()
        self._active_logs.setdefault(task_key, []).append("用户请求取消任务…")
        return build_cancel_run_response(
            ok=True,
            cancelled=True,
            error="",
            status=self._run_statuses.get(task_key),
        )

    def get_task_run_status(
        self, account_name: str, task_name: str, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        account_name = validate_storage_name(account_name, field_name="account_name")
        task_name = validate_storage_name(task_name, field_name="task_name")

        task_key = self._task_key(account_name, task_name)
        return resolve_stored_run_status(
            self._run_statuses.get(task_key),
            requested_run_id=run_id,
        )

    def is_task_running(self, task_name: str, account_name: Optional[str] = None) -> bool:
        """检查任务是否正在运行"""
        if account_name:
            return self._active_tasks.get(self._task_key(account_name, task_name), False)
        return any(key[1] == task_name for key, running in self._active_tasks.items() if running)

    async def run_task_with_logs(
        self, account_name: str, task_name: str, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """运行任务并实时捕获日志 (In-Process)。实现见 sign_task_runner。"""
        from backend.services.sign_task_runner import execute_sign_task

        return await execute_sign_task(self, account_name, task_name, run_id=run_id)


# 创建全局实例
_sign_task_service: Optional[SignTaskService] = None


def get_sign_task_service() -> SignTaskService:
    global _sign_task_service
    if _sign_task_service is None:
        _sign_task_service = SignTaskService()
    return _sign_task_service
