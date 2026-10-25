"""
SignTaskHistoryStore: 独立且语义完备的签到历史管理领域模块。

承载签到历史的持久化存储、轻量索引维护、按条件查询、单条删除、
结构化清理、趋势聚合统计以及历史文件重命名/改名等核心业务原语。
不反向耦合 SignTaskService 宿主对象。
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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
    clear_index,
    ensure_index,
    list_recent_from_index,
    read_index_entries,
    rebuild_index_from_history_files,
    remove_index_entries_matching,
)
from backend.services.sign_task_history_io import (
    cleanup_old_history_files,
    count_history_entries,
    filter_history_entries,
    history_file_owner,
    history_file_path,
    load_history_entries,
    load_history_payload_from_file,
    merge_history_payloads,
    migrate_legacy_history_file,
    resolve_existing_history_file,
    safe_history_key,
    split_history_entries_by_account,
    unsafe_history_key,
)
from backend.services.sign_task_history_query import (
    collect_formatted_history_items,
    find_history_item_by_time,
    sort_history_items_desc,
)
from backend.services.sign_task_text import repair_mojibake
from backend.utils.atomic_io import (
    path_write_lock,
    read_json_safe,
    write_json_atomic,
)
from backend.utils.task_logs import extract_last_target_message
from backend.utils.time import utc_now_iso

logger = logging.getLogger("backend.services.sign_task_history_store")


class SignTaskHistoryStore:
    """语义完备的签到任务历史数据存储层。"""

    safe_history_key = staticmethod(safe_history_key)
    unsafe_history_key = staticmethod(unsafe_history_key)
    load_payload_from_file = staticmethod(load_history_payload_from_file)
    count_history_entries = staticmethod(count_history_entries)
    normalize_flow_logs = staticmethod(normalize_and_trim_flow_logs)

    def __init__(
        self,
        history_dir: Path | str,
        signs_dir: Optional[Path | str] = None,
        *,
        max_entries_per_file: int = 50,
        max_flow_lines: int = 200,
        max_line_chars: int = 500,
        repair: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.history_dir = Path(history_dir)
        self.signs_dir = Path(signs_dir) if signs_dir is not None else None
        self.max_entries_per_file = max(1, int(max_entries_per_file))
        self.max_flow_lines = max_flow_lines
        self.max_line_chars = max_line_chars
        self.repair = repair or repair_mojibake
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def get_history_file_path(self, account: str = "", task: str = "") -> Path:
        """获取任务对应的历史文件路径（采用可逆 safe_history_key 编码）。"""
        return history_file_path(self.history_dir, task, account)

    def resolve_history_file(self, account: str, task: str) -> Optional[Path]:
        """解析任务已存在的历史文件路径（支持向前兼容的旧版编码文件）。"""
        return resolve_existing_history_file(self.history_dir, task, account)

    def load_entries(self, account: str = "", task: str = "") -> List[Dict[str, Any]]:
        """加载特定账号/任务的历史记录列表。"""
        return load_history_entries(self.history_dir, task, account_name=account)

    def legacy_history_candidates(
        self, account: str = "", task: str = ""
    ) -> List[Path]:
        """获取旧版历史文件候选路径列表（用于兼容检查）。"""
        from backend.services.sign_task_history_io import legacy_history_file_path

        candidates: List[Path] = []
        if account:
            candidates.append(legacy_history_file_path(self.history_dir, task, account))
        candidates.append(legacy_history_file_path(self.history_dir, task))
        target = self.get_history_file_path(account, task)
        return [path for path in candidates if path != target]

    def record_run(
        self,
        account: str,
        task: str,
        entry: Dict[str, Any],
        *,
        publish_event: bool = True,
    ) -> Dict[str, Any]:
        """
        记录单次签到执行结果。

        完成日志规范化/截断、失败分类兜底、旧编码迁移、并发安全原子落盘、
        轻量索引同步以及可选的 SSE 事件广播。
        返回落盘保存的条目字典。
        """
        success = bool(entry.get("success", False))
        message = str(entry.get("message") or entry.get("bot_message") or "")
        flow_logs = entry.get("flow_logs")
        workflow_path = entry.get("workflow_path")
        created_at = str(
            entry.get("created_at")
            or entry.get("time")
            or entry.get("timestamp")
            or utc_now_iso()
        )

        normalized_logs, flow_truncated, flow_line_count = normalize_and_trim_flow_logs(
            flow_logs,
            repair=self.repair,
            max_lines=self.max_flow_lines,
            max_line_chars=self.max_line_chars,
        )
        last_target = str(
            entry.get("last_target_message")
            or extract_last_target_message(normalized_logs)
        )

        failure_category = entry.get("failure_category")
        if failure_category is None:
            cat = classify_failure(
                error=None if success else message,
                output="\n".join(normalized_logs[-50:]) if normalized_logs else message,
                success=success,
            )
            failure_category = cat.value
        else:
            failure_category = str(failure_category)

        run_entry = build_history_run_entry(
            success=success,
            message=message,
            account_name=account,
            timestamp=created_at,
            normalized_logs=normalized_logs,
            flow_truncated=flow_truncated,
            flow_line_count=flow_line_count,
            last_target_message=last_target,
            failure_category=failure_category,
            repair=self.repair,
            workflow_path=workflow_path,
        )
        run_entry["created_at"] = created_at
        run_entry["task_name"] = task
        run_entry["aggregate_status"] = entry.get(
            "aggregate_status", "legacy_aggregate"
        )
        for field_name in ("targets", "unknown_side_effects"):
            if field_name in entry:
                run_entry[field_name] = entry[field_name]

        # 若存在旧编码历史文件，先合并迁移到当前规范路径
        migrate_legacy_history_file(
            self.history_dir,
            task,
            account,
            max_entries=self.max_entries_per_file,
        )

        target_file = self.get_history_file_path(account, task)
        with path_write_lock(target_file):
            raw = (
                load_history_payload_from_file(target_file)
                if target_file.exists()
                else []
            )
            updated = prepend_history_entry(
                raw, run_entry, max_entries=self.max_entries_per_file
            )
            write_json_atomic(target_file, updated)

        idx_entry = build_index_entry(
            time=created_at,
            account_name=account,
            task_name=task,
            success=success,
            message=message,
            failure_category=failure_category,
            workflow_path=workflow_path,
        )
        try:
            append_index_entry(
                self.history_dir,
                idx_entry,
                publish_event=publish_event,
            )
        except Exception as exc:
            logger.debug("追加历史索引失败: %s", exc)

        return run_entry

    def query_history(
        self,
        account: Optional[str] = None,
        task: Optional[str] = None,
        limit: Optional[int] = 50,
        date_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按账号、任务、日期前缀等维度筛选历史日志（返回时间倒序列表）。"""
        clamped_limit = (
            clamp_limit(limit, minimum=1, maximum=1000) if limit is not None else None
        )
        date_prefix = str(date_filter or "").strip()[:10]

        # 场景 1: account + task 双重过滤
        if account and task:
            history_file = resolve_existing_history_file(
                self.history_dir, task, account
            )
            if history_file is None or not history_file.exists():
                return []
            raw = load_history_entries(self.history_dir, task, account_name=account)
            items = collect_formatted_history_items(
                raw,
                task_name=task,
                account_name=account,
                repair=self.repair,
                extract_last_target=extract_last_target_message,
                date_prefix=date_prefix,
            )
            return sort_history_items_desc(items, limit=clamped_limit)

        # 场景 2: 仅指定 task（扫描所有账号下的该任务历史）
        if task and not account:
            safe_task = safe_history_key(task)
            items: List[Dict[str, Any]] = []
            for hf in self.history_dir.glob("*.json"):
                if hf.name.startswith("_"):
                    continue
                stem = hf.stem
                if "__" in stem:
                    acc_part, t_part = stem.split("__", 1)
                    if t_part != safe_task and unsafe_history_key(t_part) != task:
                        continue
                    acc_name = unsafe_history_key(acc_part)
                else:
                    if stem != safe_task and unsafe_history_key(stem) != task:
                        continue
                    acc_name = ""
                raw = load_history_payload_from_file(hf)
                items.extend(
                    collect_formatted_history_items(
                        raw,
                        task_name=task,
                        account_name=acc_name,
                        repair=self.repair,
                        extract_last_target=extract_last_target_message,
                        date_prefix=date_prefix,
                        prefer_entry_account=True,
                    )
                )
            return sort_history_items_desc(items, limit=clamped_limit)

        # 场景 3: 仅指定 account（优先读取索引）
        if account and not task:
            try:
                ensure_index(self.history_dir)
                indexed = list_recent_from_index(
                    self.history_dir,
                    limit=clamped_limit,
                    account_name=account,
                    date_prefix=date_prefix,
                    prefer_memory=False,
                )
                if indexed is not None:
                    return [
                        {
                            **item,
                            "created_at": item.get("created_at")
                            or item.get("time")
                            or "",
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
                logger.debug("从索引读取账号历史失败，回退扫盘: %s", exc)

            safe_acc = safe_history_key(account)
            items = []
            for hf in self.history_dir.glob(f"{safe_acc}__*.json"):
                stem = hf.stem
                t_part = stem.split("__", 1)[1]
                t_name = unsafe_history_key(t_part)
                raw = load_history_payload_from_file(hf)
                items.extend(
                    collect_formatted_history_items(
                        raw,
                        task_name=t_name,
                        account_name=account,
                        repair=self.repair,
                        extract_last_target=extract_last_target_message,
                        date_prefix=date_prefix,
                    )
                )
            return sort_history_items_desc(items, limit=clamped_limit)

        # 场景 4: 全局历史查询（既未指定 account 也未指定 task）
        try:
            ensure_index(self.history_dir)
            prefer_memory = not date_prefix
            indexed = list_recent_from_index(
                self.history_dir,
                limit=clamped_limit,
                date_prefix=date_prefix,
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
            logger.debug("从索引读取全局历史失败，回退扫盘: %s", exc)

        items = []
        for hf in self.history_dir.glob("*.json"):
            if hf.name.startswith("_"):
                continue
            stem = hf.stem
            if "__" in stem:
                acc_part, t_part = stem.split("__", 1)
                acc_name = unsafe_history_key(acc_part)
                t_name = unsafe_history_key(t_part)
            else:
                acc_name = ""
                t_name = unsafe_history_key(stem)
            raw = load_history_payload_from_file(hf)
            items.extend(
                collect_formatted_history_items(
                    raw,
                    task_name=t_name,
                    account_name=acc_name,
                    repair=self.repair,
                    extract_last_target=extract_last_target_message,
                    date_prefix=date_prefix,
                    prefer_entry_account=True,
                )
            )
        return sort_history_items_desc(items, limit=clamped_limit)

    def get_history_entry(
        self, account: str, task: str, created_at: str
    ) -> Optional[Dict[str, Any]]:
        """获取特定历史条目的完整详情（含完整 flow_logs）。"""
        target_time = str(created_at or "").strip()
        if not target_time:
            return None
        hf = resolve_existing_history_file(self.history_dir, task, account)
        if hf is None or not hf.exists():
            return None
        raw_payload = load_history_payload_from_file(hf)
        owner = history_file_owner(hf)
        if owner == account:
            raw_entries = raw_payload
        else:
            raw_entries = filter_history_entries(raw_payload, account_name=account)
        return find_history_item_by_time(
            raw_entries,
            target_time=target_time,
            task_name=task,
            account_name=account,
            repair=self.repair,
            extract_last_target=extract_last_target_message,
        )

    def delete_history_entry(self, account: str, task: str, created_at: str) -> bool:
        """删除指定 created_at 的历史条目并同步维护索引。"""
        target_time = str(created_at or "").strip()
        if not target_time:
            return False

        history_file = resolve_existing_history_file(self.history_dir, task, account)
        if history_file is None or not history_file.exists():
            return False

        with path_write_lock(history_file):
            raw_entries = load_history_payload_from_file(history_file)
            kept_entries: List[Any] = []
            deleted = False
            for entry in raw_entries:
                if not isinstance(entry, dict):
                    kept_entries.append(entry)
                    continue
                entry_time = str(entry.get("created_at") or entry.get("time") or "")
                entry_account = str(entry.get("account_name") or "")
                account_matches = entry_account == account or (
                    not entry_account and history_file_owner(history_file) == account
                )
                if not deleted and entry_time == target_time and account_matches:
                    deleted = True
                    continue
                kept_entries.append(entry)

            if not deleted:
                return False

            if kept_entries:
                write_json_atomic(history_file, kept_entries)
            else:
                history_file.unlink(missing_ok=True)

        try:
            remove_index_entries_matching(
                self.history_dir,
                account_name=account,
                task_name=task,
                created_at=target_time,
            )
        except Exception as exc:
            logger.debug("删除历史索引条目失败: %s", exc)

        return True

    def clear_history(
        self, account: Optional[str] = None, task: Optional[str] = None
    ) -> Dict[str, int]:
        """
        清理签到历史（支持全量清空、按账号清理、按任务清理、按账号+任务清理）。

        返回统一结构化字典：{"removed_files": int, "removed_entries": int}
        """
        removed_files = 0
        removed_entries = 0

        if not self.history_dir.exists():
            return {"removed_files": 0, "removed_entries": 0}

        # 模式 1: 全量清空
        if account is None and task is None:
            for hf in list(self.history_dir.glob("*.json")):
                if hf.name.startswith("_"):
                    continue
                try:
                    data = read_json_safe(hf, default=[])
                    removed_entries += count_history_entries(data)
                    hf.unlink(missing_ok=True)
                    removed_files += 1
                except Exception as exc:
                    logger.warning("删除历史文件失败: %s (%s)", hf, exc)
            clear_index(self.history_dir)
            return {"removed_files": removed_files, "removed_entries": removed_entries}

        # 模式 2: 按账号与任务清理
        if account is not None and task is not None:
            hf = resolve_existing_history_file(self.history_dir, task, account)
            if hf and hf.exists():
                with path_write_lock(hf):
                    data = read_json_safe(hf, default=[])
                    entries = (
                        data
                        if isinstance(data, list)
                        else [data]
                        if isinstance(data, dict)
                        else []
                    )
                    own_idx = [
                        i
                        for i, e in enumerate(entries)
                        if isinstance(e, dict)
                        and str(e.get("account_name") or account) == account
                    ]
                    removed_entries = len(own_idx)
                    others = [e for i, e in enumerate(entries) if i not in set(own_idx)]
                    if not others:
                        hf.unlink(missing_ok=True)
                        removed_files = 1
                    else:
                        write_json_atomic(hf, others)
            remove_index_entries_matching(
                self.history_dir, account_name=account, task_name=task
            )
            return {"removed_files": removed_files, "removed_entries": removed_entries}

        # 模式 3: 仅按账号清理
        if account is not None and task is None:
            safe_acc = safe_history_key(account)
            for hf in list(self.history_dir.glob("*.json")):
                if hf.name.startswith("_"):
                    continue
                owner = history_file_owner(hf)
                stem = hf.stem
                if (
                    owner == account
                    or stem.startswith(f"{safe_acc}__")
                    or stem.startswith(f"{account}__")
                    or "__" not in stem
                ):
                    with path_write_lock(hf):
                        data = read_json_safe(hf, default=[])
                        entries = (
                            data
                            if isinstance(data, list)
                            else [data]
                            if isinstance(data, dict)
                            else []
                        )
                        own_idx = [
                            i
                            for i, e in enumerate(entries)
                            if isinstance(e, dict)
                            and str(e.get("account_name") or owner or account)
                            == account
                        ]
                        if not own_idx:
                            continue
                        removed_entries += len(own_idx)
                        others = [
                            e for i, e in enumerate(entries) if i not in set(own_idx)
                        ]
                        if not others:
                            hf.unlink(missing_ok=True)
                            removed_files += 1
                        else:
                            write_json_atomic(hf, others)
            remove_index_entries_matching(self.history_dir, account_name=account)
            return {"removed_files": removed_files, "removed_entries": removed_entries}

        # 模式 4: 仅按任务清理
        safe_task = safe_history_key(task or "")
        for hf in list(self.history_dir.glob("*.json")):
            if hf.name.startswith("_"):
                continue
            stem = hf.stem
            match = False
            if "__" in stem:
                _, t_part = stem.split("__", 1)
                if t_part == safe_task or unsafe_history_key(t_part) == task:
                    match = True
            elif stem == safe_task or unsafe_history_key(stem) == task:
                match = True
            if match:
                with path_write_lock(hf):
                    data = read_json_safe(hf, default=[])
                    removed_entries += count_history_entries(data)
                    hf.unlink(missing_ok=True)
                    removed_files += 1
        remove_index_entries_matching(self.history_dir, task_name=task or "")
        return {"removed_files": removed_files, "removed_entries": removed_entries}

    def count_entries(self, account: str, task: str) -> int:
        """统计特定账号特定任务的历史记录数。"""
        hf = resolve_existing_history_file(self.history_dir, task, account)
        if hf is None or not hf.exists():
            return 0
        raw = load_history_payload_from_file(hf)
        owner = history_file_owner(hf)
        if owner == account:
            return len(raw)
        return len(filter_history_entries(raw, account_name=account))

    def get_history_trends(self, days: int = 7) -> Dict[str, Any]:
        """按天聚合最近 N 天的签到历史趋势与成功率指标。"""
        days = max(1, min(int(days), 90))
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days - 1)
        start_date_str = cutoff_date.strftime("%Y-%m-%d")

        daily_buckets: Dict[str, Dict[str, Any]] = {}
        for i in range(days):
            d_str = (cutoff_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            daily_buckets[d_str] = {
                "date": d_str,
                "total": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 1.0,
            }

        ensure_index(self.history_dir)
        try:
            entries = read_index_entries(self.history_dir, limit=5000)
        except Exception as e:
            logger.debug("读取历史索引失败: %s", e)
            entries = []

        total_runs = 0
        total_success = 0
        categories: Dict[str, int] = {}

        for entry in entries:
            ts_str = str(entry.get("time") or entry.get("created_at") or "")
            date_key = ts_str[:10] if len(ts_str) >= 10 else ""
            if not date_key or date_key < start_date_str:
                continue

            if date_key in daily_buckets:
                daily_buckets[date_key]["total"] += 1
                total_runs += 1
                if entry.get("success"):
                    daily_buckets[date_key]["success"] += 1
                    total_success += 1
                else:
                    daily_buckets[date_key]["failed"] += 1
                    cat = str(entry.get("failure_category") or "unknown")
                    if cat:
                        categories[cat] = categories.get(cat, 0) + 1

        trends_list = []
        for d_str in sorted(daily_buckets.keys()):
            item = daily_buckets[d_str]
            item["success_rate"] = (
                round(item["success"] / item["total"], 2) if item["total"] > 0 else 1.0
            )
            trends_list.append(item)

        overall_success_rate = (
            round(total_success / total_runs, 2) if total_runs > 0 else 1.0
        )

        return {
            "days": days,
            "total_runs": total_runs,
            "total_success": total_success,
            "total_failed": total_runs - total_success,
            "overall_success_rate": overall_success_rate,
            "trends": trends_list,
            "categories": categories,
        }

    def cleanup_expired(self, max_age_days: int) -> int:
        """删除过期历史文件并触发索引重建，返回清理的文件数量。"""
        removed = cleanup_old_history_files(self.history_dir, max_age_days=max_age_days)
        if removed > 0:
            self.rebuild_index()
        return removed

    def rebuild_index(self) -> int:
        """从全部现有 history 文件重建轻量索引。"""
        return rebuild_index_from_history_files(self.history_dir)

    def rename_history_file(
        self, old_account: str, new_account: str, task: str
    ) -> bool:
        """
        账号重命名底层原语：将指定任务的历史文件由旧账号名重命名/迁移至新账号名。
        """
        old_file = resolve_existing_history_file(self.history_dir, task, old_account)
        if old_file is None or not old_file.exists():
            return False

        new_file = self.get_history_file_path(new_account, task)
        if old_file == new_file:
            return True

        with path_write_lock(old_file):
            payload = load_history_payload_from_file(old_file)
            owned, others = split_history_entries_by_account(payload, old_account)
            if not owned:
                return False

            with path_write_lock(new_file):
                if new_file.exists():
                    merged = merge_history_payloads(
                        load_history_payload_from_file(new_file),
                        owned,
                        max_entries=self.max_entries_per_file,
                    )
                else:
                    merged = owned
                write_json_atomic(new_file, merged)

            if others:
                write_json_atomic(old_file, others)
            else:
                old_file.unlink(missing_ok=True)

        self.rebuild_index()
        return True

    def rewrite_account_in_entries(
        self, account: str, task: str, new_account: str
    ) -> int:
        """
        账号重命名底层原语：改写历史条目内部的 account_name 字段。
        """
        target_file = resolve_existing_history_file(
            self.history_dir, task, new_account
        ) or resolve_existing_history_file(self.history_dir, task, account)
        if target_file is None or not target_file.exists():
            return 0

        with path_write_lock(target_file):
            payload = load_history_payload_from_file(target_file)
            rewritten = 0
            for item in payload:
                if isinstance(item, dict):
                    acc = str(item.get("account_name") or "")
                    if not acc or acc == account:
                        item["account_name"] = new_account
                        rewritten += 1
            if rewritten > 0:
                write_json_atomic(target_file, payload)

        if rewritten > 0:
            self.rebuild_index()
        return rewritten
