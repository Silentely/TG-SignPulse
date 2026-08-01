"""
签到历史读写 Mixin

从 SignTaskService 抽出的历史查询/删除/落盘逻辑，保持公开 API 不变。
依赖宿主：run_history_dir, signs_dir, _tasks_cache, _history_max_* 与路径/列表 helper。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.sign_task_failure import classify_failure
from backend.services.sign_task_history_format import (
    build_history_run_entry,
    clamp_limit,
    normalize_and_trim_flow_logs,
    prepend_history_entry,
)
from backend.services.sign_task_history_index import (
    append_index_entry,
    build_index_entry,
    list_recent_from_index,
    remove_index_entries_matching,
)
from backend.services.sign_task_history_index import (
    clear_index as clear_history_index,
)
from backend.services.sign_task_history_index import (
    ensure_index as ensure_history_index,
)
from backend.services.sign_task_history_io import (
    count_history_entries as count_history_entries_io,
)
from backend.services.sign_task_history_io import (
    load_history_entries as load_history_entries_io,
)
from backend.services.sign_task_history_io import (
    load_history_payload_from_file as load_history_payload_from_file_io,
)
from backend.services.sign_task_history_io import (
    resolve_existing_history_file as resolve_existing_history_file_io,
)
from backend.services.sign_task_history_query import (
    collect_formatted_history_items,
    find_history_item_by_time,
    sort_history_items_desc,
)
from backend.utils.names import validate_storage_name
from backend.utils.task_logs import extract_last_target_message

_logger = logging.getLogger("backend.sign_task_history_ops")


class SignTaskHistoryMixin:
    """历史相关方法；由 SignTaskService 继承。"""

    def _normalize_flow_logs(
        self, flow_logs: Optional[List[str]]
    ) -> tuple[List[str], bool, int]:
        return normalize_and_trim_flow_logs(
            flow_logs,
            repair=self._repair_mojibake,
            max_lines=self._history_max_flow_lines,
            max_line_chars=self._history_max_line_chars,
        )

    def _load_history_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        return load_history_entries_io(
            self.run_history_dir, task_name, account_name=account_name
        )

    def _resolve_existing_history_file(
        self, task_name: str, account_name: str = ""
    ) -> Optional[Path]:
        return resolve_existing_history_file_io(
            self.run_history_dir, task_name, account_name
        )

    @staticmethod
    def _load_history_payload_from_file(history_file: Path) -> List[Any]:
        return load_history_payload_from_file_io(history_file)

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
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if last_run:
                        config["last_run"] = last_run
                    else:
                        config.pop("last_run", None)
                    with open(config_file, "w", encoding="utf-8") as f:
                        json.dump(config, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    _logger.warning(
                        "回写任务元数据 last_run 失败: %s (%s)", config_file, exc
                    )

        if self._tasks_cache is not None:
            for task in self._tasks_cache:
                if not isinstance(task, dict):
                    continue
                if task.get("name") != task_name or task.get("account_name") != account_name:
                    continue
                if last_run:
                    task["last_run"] = last_run
                else:
                    task.pop("last_run", None)
                break

    def get_account_history_logs(self, account_name: str) -> List[Dict[str, Any]]:
        """获取某账号下所有任务的最近历史日志"""
        account_name = validate_storage_name(account_name, field_name="account_name")
        all_history: List[Dict[str, Any]] = []
        if not self.run_history_dir.exists():
            return []

        # 仅读取该账号任务相关历史，避免全目录扫描
        tasks = self.list_tasks(account_name=account_name)
        seen_tasks: set[str] = set()

        for task in tasks:
            task_name = str(task.get("name") or "").strip()
            if not task_name or task_name in seen_tasks:
                continue
            seen_tasks.add(task_name)

            all_history.extend(
                collect_formatted_history_items(
                    self._load_history_entries(task_name, account_name=account_name),
                    task_name=task_name,
                    account_name=account_name,
                    repair=self._repair_mojibake,
                    extract_last_target=extract_last_target_message,
                )
            )

        return sort_history_items_desc(all_history)

    def get_recent_history_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """最近历史：优先读轻量索引（O(尾部)），避免全任务扫盘。"""
        limit = clamp_limit(limit, minimum=1, maximum=200)
        try:
            ensure_history_index(self.run_history_dir)
            indexed = list_recent_from_index(
                self.run_history_dir,
                limit=limit,
                prefer_memory=True,
            )
            if indexed:
                # 索引条目已是列表展示结构（无 flow_logs）；补齐兼容字段
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

        # 回退：全任务扫描（索引缺失或损坏时）
        recent: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for task in self.list_tasks(force_refresh=False, aggregate=False):
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
                    repair=self._repair_mojibake,
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
        """按账号/日期筛选历史。列表场景优先索引；需要 flow_logs 时仍读详情接口。"""
        limit = clamp_limit(limit, minimum=1, maximum=1000)

        normalized_account = (
            validate_storage_name(account_name, field_name="account_name")
            if account_name
            else None
        )
        normalized_date = str(date or "").strip()[:10]

        try:
            ensure_history_index(self.run_history_dir)
            indexed = list_recent_from_index(
                self.run_history_dir,
                limit=limit,
                account_name=normalized_account,
                date_prefix=normalized_date,
                prefer_memory=False,
            )
            if indexed:
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
            _logger.debug("筛选历史索引失败，回退全量: %s", exc)

        history_items: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for task in self.list_tasks(
            account_name=normalized_account,
            force_refresh=False,
            aggregate=False,
        ):
            task_name = str(task.get("name") or "").strip()
            current_account = str(task.get("account_name") or "").strip()
            if not task_name or not current_account:
                continue

            pair = (current_account, task_name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            history = self._load_history_entries(task_name, account_name=current_account)
            history_items.extend(
                collect_formatted_history_items(
                    history,
                    task_name=task_name,
                    account_name=current_account,
                    repair=self._repair_mojibake,
                    extract_last_target=extract_last_target_message,
                    date_prefix=normalized_date,
                )
            )

        return sort_history_items_desc(history_items, limit=limit)

    def get_history_log_detail(
        self,
        account_name: str,
        task_name: str,
        created_at: str,
    ) -> Optional[Dict[str, Any]]:
        normalized_account = validate_storage_name(
            account_name, field_name="account_name"
        )
        normalized_task = validate_storage_name(task_name, field_name="task_name")
        return find_history_item_by_time(
            self._load_history_entries(
                normalized_task, account_name=normalized_account
            ),
            target_time=created_at,
            task_name=normalized_task,
            account_name=normalized_account,
            repair=self._repair_mojibake,
            extract_last_target=extract_last_target_message,
        )

    def delete_history_log(
        self,
        account_name: str,
        task_name: str,
        created_at: str,
    ) -> bool:
        normalized_account = validate_storage_name(
            account_name, field_name="account_name"
        )
        normalized_task = validate_storage_name(task_name, field_name="task_name")
        target_time = str(created_at or "").strip()
        if not target_time:
            return False

        history_file = self._resolve_existing_history_file(
            normalized_task, normalized_account
        )
        if history_file is None:
            return False

        raw_entries = self._load_history_payload_from_file(history_file)
        kept_entries: List[Any] = []
        deleted = False

        for entry in raw_entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue

            entry_time = str(entry.get("time") or "")
            entry_account = str(entry.get("account_name") or "")
            account_matches = not entry_account or entry_account == normalized_account

            if not deleted and entry_time == target_time and account_matches:
                deleted = True
                continue

            kept_entries.append(entry)

        if not deleted:
            return False

        if kept_entries:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(kept_entries, f, ensure_ascii=False, indent=2)
        else:
            try:
                history_file.unlink()
            except FileNotFoundError:
                pass

        remaining_entries = [
            entry
            for entry in kept_entries
            if isinstance(entry, dict)
            and str(entry.get("account_name") or normalized_account) == normalized_account
        ]
        remaining_entries.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
        latest_entry = remaining_entries[0] if remaining_entries else None
        self._set_task_last_run_metadata(
            normalized_task,
            normalized_account,
            latest_entry if isinstance(latest_entry, dict) else None,
        )
        try:
            remove_index_entries_matching(
                self.run_history_dir,
                account_name=normalized_account,
                task_name=normalized_task,
                created_at=target_time,
            )
        except Exception as exc:
            _logger.debug("删除历史索引条目失败: %s", exc)
        return True

    @staticmethod
    def _count_history_entries(data: Any) -> int:
        return count_history_entries_io(data)

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
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "last_run" not in config:
                return
            del config["last_run"]
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            _logger.debug("清理 last_run 元数据失败: %s (%s)", config_file, exc)

    def clear_all_history_logs(self) -> Dict[str, int]:
        removed_files = 0
        removed_entries = 0

        if not self.run_history_dir.exists():
            return {"removed_files": 0, "removed_entries": 0}

        seen_tasks: set[tuple[str, str]] = set()
        for task in self.list_tasks(force_refresh=True, aggregate=False):
            task_name = str(task.get("name") or "").strip()
            account_name = str(task.get("account_name") or "").strip()
            if not task_name:
                continue
            key = (account_name, task_name)
            if key in seen_tasks:
                continue
            seen_tasks.add(key)
            self._clear_task_last_run_metadata(task_name, account_name)

        if self._tasks_cache is not None:
            for task in self._tasks_cache:
                if isinstance(task, dict):
                    task.pop("last_run", None)

        for history_file in self.run_history_dir.glob("*.json"):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    removed_entries += self._count_history_entries(json.load(f))
            except Exception as exc:
                _logger.warning("读取历史文件失败: %s (%s)", history_file, exc)
            try:
                history_file.unlink()
                removed_files += 1
            except Exception as exc:
                _logger.warning("删除历史文件失败: %s (%s)", history_file, exc)

        try:
            clear_history_index(self.run_history_dir)
        except Exception as exc:
            _logger.debug("清空历史索引失败: %s", exc)

        return {"removed_files": removed_files, "removed_entries": removed_entries}

    def clear_account_history_logs(self, account_name: str) -> Dict[str, int]:
        """清理某账号的历史日志，不影响其他账号"""
        account_name = validate_storage_name(account_name, field_name="account_name")
        removed_files = 0
        removed_entries = 0

        if not self.run_history_dir.exists():
            return {"removed_files": 0, "removed_entries": 0}

        tasks = self.list_tasks(account_name=account_name)
        for task in tasks:
            task_name = task.get("name") or ""
            if not task_name:
                continue

            self._clear_task_last_run_metadata(task_name, account_name)
            if self._tasks_cache is not None:
                for t in self._tasks_cache:
                    if t["name"] == task_name and t.get("account_name") == account_name:
                        t.pop("last_run", None)
                        break

            history_file = self._history_file_path(task_name, account_name)
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        removed_entries += self._count_history_entries(json.load(f))
                except Exception as exc:
                    _logger.warning("读取历史文件失败: %s (%s)", history_file, exc)
                try:
                    history_file.unlink()
                    removed_files += 1
                except Exception as exc:
                    _logger.warning("删除历史文件失败: %s (%s)", history_file, exc)
                continue

            legacy_file = self.run_history_dir / f"{self._safe_history_key(task_name)}.json"
            if not legacy_file.exists():
                continue

            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data_list = [data]
                elif isinstance(data, list):
                    data_list = data
                else:
                    data_list = []
            except Exception as exc:
                _logger.warning("读取遗留历史文件失败，跳过: %s (%s)", legacy_file, exc)
                continue

            if not data_list:
                try:
                    legacy_file.unlink()
                    removed_files += 1
                except Exception as exc:
                    _logger.warning("删除遗留历史文件失败: %s (%s)", legacy_file, exc)
                continue

            from backend.services.sign_task_history_io import plan_legacy_history_clear

            plan = plan_legacy_history_clear(data_list, account_name)
            removed_entries += int(plan.get("removed_entries") or 0)
            if plan.get("remove_file"):
                try:
                    legacy_file.unlink()
                    removed_files += 1
                except Exception as exc:
                    _logger.warning("删除遗留历史文件失败: %s (%s)", legacy_file, exc)
            else:
                try:
                    with open(legacy_file, "w", encoding="utf-8") as f:
                        json.dump(plan.get("kept") or [], f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    _logger.warning("回写遗留历史文件失败: %s (%s)", legacy_file, exc)

        try:
            remove_index_entries_matching(
                self.run_history_dir,
                account_name=account_name,
            )
        except Exception as exc:
            _logger.debug("按账号清理历史索引失败: %s", exc)

        return {"removed_files": removed_files, "removed_entries": removed_entries}

    def _get_last_run_info(
        self, task_dir: Path, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        获取任务的最后执行信息
        """
        history_file = self._history_file_path(task_dir.name, account_name)
        legacy_file = self.run_history_dir / f"{task_dir.name}.json"

        if not history_file.exists():
            if account_name and legacy_file.exists():
                history_file = legacy_file
            else:
                return None

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data[0]  # 最近的一条
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
    ):
        """保存任务执行历史 (保留列表)"""
        from datetime import datetime

        history_file = self._history_file_path(task_name, account_name)
        normalized_logs, flow_truncated, flow_line_count = self._normalize_flow_logs(
            flow_logs
        )
        last_target_message = extract_last_target_message(normalized_logs)

        category = classify_failure(
            error=None if success else message,
            output="\n".join(normalized_logs[-50:]) if normalized_logs else message,
            success=success,
        )
        new_entry = build_history_run_entry(
            success=success,
            message=message,
            account_name=account_name,
            timestamp=datetime.now().isoformat(),
            normalized_logs=normalized_logs,
            flow_truncated=flow_truncated,
            flow_line_count=flow_line_count,
            last_target_message=last_target_message,
            failure_category=category.value,
            repair=self._repair_mojibake,
        )

        history_raw: Any = []
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    history_raw = json.load(f)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
                _logger.warning(
                    "读取历史失败 task=%s account=%s file=%s: %s",
                    task_name,
                    account_name,
                    history_file,
                    exc,
                )
                history_raw = []

        history = prepend_history_entry(
            history_raw,
            new_entry,
            max_entries=self._history_max_entries,
        )

        try:
            write_json_atomic(history_file, history)

            # 同时更新任务配置中的 last_run
            from backend.services.sign_task_history_io import (
                patch_tasks_cache_last_run,
                resolve_task_config_dir,
            )

            task = self.get_task(task_name, account_name)
            if task:
                task_dir = resolve_task_config_dir(
                    self.signs_dir, account_name, task_name
                )
                config_file = task_dir / "config.json"
                if config_file.exists():
                    try:
                        with open(config_file, "r", encoding="utf-8") as f:
                            config = json.load(f)
                        config["last_run"] = new_entry
                        with open(config_file, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
                        _logger.warning(
                            "更新任务配置 last_run 失败 task=%s account=%s: %s",
                            task_name,
                            account_name,
                            e,
                        )

            # 更新内存缓存（避免置空 self._tasks_cache）
            patch_tasks_cache_last_run(
                self._tasks_cache,
                task_name=task_name,
                account_name=account_name,
                last_run=new_entry,
            )
            self._sync_tasks_list_ttl()

            # 轻量索引：供 SSE / 最近日志 O(1) 读取
            try:
                append_index_entry(
                    self.run_history_dir,
                    build_index_entry(
                        time=str(new_entry.get("time") or ""),
                        account_name=account_name,
                        task_name=task_name,
                        success=bool(success),
                        message=str(new_entry.get("message") or message or ""),
                        failure_category=str(
                            new_entry.get("failure_category") or category.value or ""
                        ),
                    ),
                )
            except Exception as idx_exc:
                _logger.debug(
                    "追加历史索引失败 task=%s account=%s: %s",
                    task_name,
                    account_name,
                    idx_exc,
                )

        except (OSError, TypeError, ValueError) as e:
            _logger.warning(
                "保存运行信息失败 task=%s account=%s: %s",
                task_name,
                account_name,
                e,
            )

