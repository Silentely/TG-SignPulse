"""
关键词命中记录：结构化落盘、查询、分组与 CSV 导出。

与 runtime 的文本日志互补：命中事件写入 JSONL，供面板列表/导出使用。
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings

logger = logging.getLogger("backend.keyword_monitor.hits")

MAX_RECORDS = 5000
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500

_lock = threading.Lock()
_records: List[Dict[str, Any]] = []
_loaded = False


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _hits_path() -> Path:
    path = get_settings().resolve_workdir() / "keyword_monitor" / "hits.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_loaded() -> None:
    global _loaded, _records
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        path = _hits_path()
        loaded: List[Dict[str, Any]] = []
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fp:
                    for line in fp:
                        text = line.strip()
                        if not text:
                            continue
                        try:
                            item = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(item, dict) and item.get("id"):
                            loaded.append(item)
            except OSError as exc:
                logger.warning("load keyword hits failed: %s", exc)
        # 文件顺序为追加；内存保持新→旧
        loaded.reverse()
        if len(loaded) > MAX_RECORDS:
            loaded = loaded[:MAX_RECORDS]
        _records = loaded
        _loaded = True


def _rewrite_file_locked() -> None:
    """按旧→新重写文件（调用方需持锁）。"""
    path = _hits_path()
    temp = path.with_suffix(".tmp")
    # 内存新→旧，写盘旧→新便于 append
    ordered = list(reversed(_records))
    with temp.open("w", encoding="utf-8") as fp:
        for item in ordered:
            fp.write(json.dumps(item, ensure_ascii=False) + "\n")
    temp.replace(path)


def record_keyword_hit(
    *,
    account_name: str,
    task_name: str,
    chat_id: Any = None,
    chat_title: str = "",
    keyword: str = "",
    keywords: Optional[List[str]] = None,
    message_id: Any = None,
    message_text: str = "",
    sender: str = "",
    url: str = "",
    push_channel: str = "",
    message_thread_id: Any = None,
) -> Dict[str, Any]:
    """追加一条命中记录并落盘。"""
    _ensure_loaded()
    text = str(message_text or "").replace("\r\n", "\n").strip()
    if len(text) > 500:
        text = text[:497] + "..."
    record: Dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "time": _utc_now_iso(),
        "account_name": str(account_name or "").strip(),
        "task_name": str(task_name or "").strip(),
        "chat_id": chat_id,
        "chat_title": str(chat_title or "").strip(),
        "keyword": str(keyword or "").strip(),
        "keywords": [str(k) for k in (keywords or []) if str(k).strip()][:20],
        "message_id": message_id,
        "message_text": text,
        "sender": str(sender or "").strip(),
        "url": str(url or "").strip(),
        "push_channel": str(push_channel or "").strip(),
        "message_thread_id": message_thread_id,
    }
    with _lock:
        _records.insert(0, record)
        if len(_records) > MAX_RECORDS:
            # 超限时整文件重写，去掉最旧记录
            del _records[MAX_RECORDS:]
            _rewrite_file_locked()
        else:
            path = _hits_path()
            with path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def list_keyword_hits(
    *,
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> Dict[str, Any]:
    _ensure_loaded()
    limit = max(1, min(int(limit or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT))
    offset = max(0, int(offset or 0))
    account = (account_name or "").strip()
    task = (task_name or "").strip()

    with _lock:
        filtered = [
            item
            for item in _records
            if (not account or item.get("account_name") == account)
            and (not task or item.get("task_name") == task)
        ]
        total = len(filtered)
        items = filtered[offset : offset + limit]
        # 浅拷贝，避免外部修改内存缓存
        items = [dict(item) for item in items]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


def group_keyword_hits(
    *,
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    group_by: str = "task",
    limit_per_group: int = 20,
) -> Dict[str, Any]:
    """
    按 task / account / chat 分组命中记录。
    每组保留最近 limit_per_group 条，并统计 count。
    """
    _ensure_loaded()
    key_field = {
        "task": "task_name",
        "account": "account_name",
        "chat": "chat_id",
    }.get((group_by or "task").strip().lower(), "task_name")
    per = max(1, min(int(limit_per_group or 20), 100))
    account = (account_name or "").strip()
    task = (task_name or "").strip()

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with _lock:
        for item in _records:
            if account and item.get("account_name") != account:
                continue
            if task and item.get("task_name") != task:
                continue
            raw_key = item.get(key_field)
            if key_field == "chat_id":
                label = str(item.get("chat_title") or raw_key or "-")
                key = f"{raw_key}|{label}"
            else:
                key = str(raw_key or "-")
            if len(buckets[key]) < per:
                buckets[key].append(dict(item))

    groups = []
    for key, items in buckets.items():
        if key_field == "chat_id" and "|" in key:
            chat_id, chat_title = key.split("|", 1)
            group_key = chat_id
            group_label = chat_title
        else:
            group_key = key
            group_label = key
        # count：同 key 的全量条数（不只是截断后的）
        groups.append(
            {
                "key": group_key,
                "label": group_label,
                "count": _count_group(key_field, group_key, account, task),
                "items": items,
            }
        )
    groups.sort(key=lambda g: (-int(g["count"]), str(g["label"])))
    return {"group_by": group_by if group_by in {"task", "account", "chat"} else "task", "groups": groups}


def _count_group(
    key_field: str,
    group_key: str,
    account: str,
    task: str,
) -> int:
    count = 0
    for item in _records:
        if account and item.get("account_name") != account:
            continue
        if task and item.get("task_name") != task:
            continue
        raw = item.get(key_field)
        if str(raw if raw is not None else "-") == str(group_key):
            count += 1
    return count


def export_keyword_hits_csv(
    *,
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    limit: int = 2000,
) -> str:
    """导出 CSV 文本（UTF-8 BOM 友好：调用方加 BOM 可选）。"""
    data = list_keyword_hits(
        account_name=account_name,
        task_name=task_name,
        limit=min(max(1, int(limit or 2000)), MAX_RECORDS),
        offset=0,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "time",
            "account_name",
            "task_name",
            "chat_id",
            "chat_title",
            "keyword",
            "keywords",
            "sender",
            "message_id",
            "message_text",
            "url",
            "push_channel",
            "message_thread_id",
        ]
    )
    for item in data["items"]:
        writer.writerow(
            [
                item.get("time") or "",
                item.get("account_name") or "",
                item.get("task_name") or "",
                item.get("chat_id") if item.get("chat_id") is not None else "",
                item.get("chat_title") or "",
                item.get("keyword") or "",
                "|".join(item.get("keywords") or []),
                item.get("sender") or "",
                item.get("message_id") if item.get("message_id") is not None else "",
                item.get("message_text") or "",
                item.get("url") or "",
                item.get("push_channel") or "",
                item.get("message_thread_id")
                if item.get("message_thread_id") is not None
                else "",
            ]
        )
    return buf.getvalue()


def clear_keyword_hits(
    *,
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
) -> int:
    """清空命中记录（可按账号/任务过滤），返回删除条数。"""
    _ensure_loaded()
    account = (account_name or "").strip()
    task = (task_name or "").strip()
    with _lock:
        before = len(_records)
        if not account and not task:
            _records.clear()
        else:
            kept = [
                item
                for item in _records
                if not (
                    (not account or item.get("account_name") == account)
                    and (not task or item.get("task_name") == task)
                )
            ]
            _records[:] = kept
        deleted = before - len(_records)
        _rewrite_file_locked()
        return deleted


def reset_hits_for_tests() -> None:
    """测试用：清空内存与文件状态。"""
    global _loaded, _records
    with _lock:
        _records = []
        _loaded = False
