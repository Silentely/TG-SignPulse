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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

from backend.core.config import get_settings
from backend.utils.time import utc_now_iso_z_seconds

logger = logging.getLogger("backend.keyword_monitor.hits")

MAX_RECORDS = 5000
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500

# 满额后的批量重写阈值：内存/文件允许临时超到 MAX_RECORDS + 该值，
# 攒够一批才整文件重写，避免稳态下每条命中都全量重写 5000 行
_REWRITE_BATCH = 100

_lock = threading.Lock()
_records: List["HitRecord"] = []
_loaded = False

# Excel/CSV 公式注入前缀
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class HitRecord(TypedDict, total=False):
    """单条关键词命中记录（JSONL 落盘结构）。"""

    id: str
    time: str
    account_name: str
    task_name: str
    chat_id: Union[int, str]
    chat_title: str
    keyword: str
    keywords: List[str]
    message_id: Optional[int]
    message_text: str
    sender: str
    url: str
    push_channel: str
    message_thread_id: Optional[int]


class HitListResponse(TypedDict):
    """list_keyword_hits 返回结构。"""

    total: int
    offset: int
    limit: int
    items: List[HitRecord]


class HitGroup(TypedDict):
    """group_keyword_hits 单个分组。"""

    key: Union[str, Tuple[str, str]]
    label: str
    count: int
    items: List[HitRecord]


class HitGroupResponse(TypedDict):
    """group_keyword_hits 返回结构。"""

    group_by: str
    groups: List[HitGroup]


def _hits_path() -> Path:
    path = get_settings().resolve_workdir() / "keyword_monitor" / "hits.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _csv_cell(value: Any) -> str:
    """将单元格转为字符串，并防止公式注入。"""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _CSV_FORMULA_PREFIXES:
        return "'" + text
    return text


def _as_optional_int(value: Any) -> Optional[int]:
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clip(value: Any, limit: int) -> str:
    """字符串字段收敛：转字符串、去首尾空白并按上限截断。"""
    return str(value or "").strip()[:limit]


def _safe_message_text(message_text: Any) -> str:
    """消息文本：统一换行、去首尾空白、超长截断补省略号。"""
    text = str(message_text or "").replace("\r\n", "\n").strip()
    if len(text) > 500:
        text = text[:497] + "..."
    return text


def _safe_url(url: Any) -> str:
    """仅保留 http(s) URL，防止 javascript: 等危险协议进入导出/展示。"""
    raw_url = str(url or "").strip()
    if raw_url.lower().startswith(("http://", "https://")):
        return raw_url[:500]
    return ""


def _clean_keywords(keywords: Optional[List[Any]]) -> List[str]:
    """关键词列表：转字符串、去空白截断、剔除空串，上限 20 条。"""
    cleaned = [
        str(k or "").strip()[:200] for k in (keywords or []) if str(k or "").strip()
    ]
    return cleaned[:20]


def _normalize_hit_record(raw: Dict[str, Any]) -> Optional[HitRecord]:
    """
    将 JSONL 行归一为 HitRecord。

    仅要求 id 为非空字符串；其余字段做截断与类型收敛，
    避免历史脏数据在列表/导出时炸类型或注入异常结构。
    """
    rid = _clip(raw.get("id"), 64)
    if not rid:
        return None

    chat_id = raw.get("chat_id")
    if chat_id is not None and not isinstance(chat_id, (int, str)):
        chat_id = str(chat_id)

    record: HitRecord = {
        "id": rid,
        "time": _clip(raw.get("time"), 40),
        "account_name": _clip(raw.get("account_name"), 120),
        "task_name": _clip(raw.get("task_name"), 120),
        "chat_id": chat_id,  # type: ignore[typeddict-item]
        "chat_title": _clip(raw.get("chat_title"), 200),
        "keyword": _clip(raw.get("keyword"), 200),
        "keywords": _clean_keywords(raw.get("keywords")),
        "message_id": _as_optional_int(raw.get("message_id")),
        "message_text": _safe_message_text(raw.get("message_text")),
        "sender": _clip(raw.get("sender"), 120),
        "url": _safe_url(raw.get("url")),
        "push_channel": _clip(raw.get("push_channel"), 40),
        "message_thread_id": _as_optional_int(raw.get("message_thread_id")),
    }
    return record


def _ensure_loaded() -> None:
    global _loaded, _records
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        path = _hits_path()
        loaded: List[HitRecord] = []
        skipped_bad_lines = 0
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
                            # 坏行：记录后跳过，避免静默丢数据无法排查
                            skipped_bad_lines += 1
                            continue
                        if not isinstance(item, dict):
                            skipped_bad_lines += 1
                            continue
                        normalized = _normalize_hit_record(item)
                        if normalized is not None:
                            loaded.append(normalized)
            except OSError as exc:
                logger.warning("加载关键词命中记录失败: %s", exc)
        if skipped_bad_lines:
            logger.warning(
                "加载关键词命中记录时跳过 %d 行坏数据（%s）",
                skipped_bad_lines,
                path,
            )
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
    chat_id: Optional[Union[int, str]] = None,
    chat_title: str = "",
    keyword: str = "",
    keywords: Optional[List[str]] = None,
    message_id: Optional[int] = None,
    message_text: str = "",
    sender: str = "",
    url: str = "",
    push_channel: str = "",
    message_thread_id: Optional[int] = None,
) -> HitRecord:
    """追加一条命中记录并落盘。"""
    _ensure_loaded()
    record: HitRecord = {
        "id": uuid.uuid4().hex,
        "time": utc_now_iso_z_seconds(),
        "account_name": _clip(account_name, 120),
        "task_name": _clip(task_name, 120),
        "chat_id": chat_id,
        "chat_title": _clip(chat_title, 200),
        "keyword": _clip(keyword, 200),
        "keywords": _clean_keywords(keywords),
        "message_id": message_id,
        "message_text": _safe_message_text(message_text),
        "sender": _clip(sender, 120),
        "url": _safe_url(url),
        "push_channel": _clip(push_channel, 40),
        "message_thread_id": message_thread_id,
    }
    with _lock:
        _records.insert(0, record)
        if len(_records) >= MAX_RECORDS + _REWRITE_BATCH:
            # 批量整文件重写：满额稳态下每 _REWRITE_BATCH 条才重写一次，
            # 期间以追加写落盘；重启加载时仍按 MAX_RECORDS 截断（见 _ensure_loaded）
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
    max_limit: int = MAX_LIST_LIMIT,
) -> HitListResponse:
    """
    列出命中记录。

    max_limit 用于导出场景放宽上限（默认列表仍限制 MAX_LIST_LIMIT）。
    """
    _ensure_loaded()
    ceiling = max(1, min(int(max_limit or MAX_LIST_LIMIT), MAX_RECORDS))
    limit = max(1, min(int(limit or DEFAULT_LIST_LIMIT), ceiling))
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
        items = [dict(item) for item in filtered[offset : offset + limit]]

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
) -> HitGroupResponse:
    """
    按 task / account / chat 分组命中记录。
    每组保留最近 limit_per_group 条，并统计 count。
    """
    _ensure_loaded()
    normalized_group = (group_by or "task").strip().lower()
    if normalized_group not in {"task", "account", "chat"}:
        normalized_group = "task"
    key_field = {
        "task": "task_name",
        "account": "account_name",
        "chat": "chat_id",
    }[normalized_group]
    per = max(1, min(int(limit_per_group or 20), 100))
    account = (account_name or "").strip()
    task = (task_name or "").strip()

    # 内存 key：chat 用 (id, title) 元组，避免 title 含分隔符时解析错误
    buckets: Dict[Union[str, Tuple[str, str]], List[HitRecord]] = defaultdict(list)
    counts: Dict[Union[str, Tuple[str, str]], int] = defaultdict(int)

    with _lock:
        for item in _records:
            if account and item.get("account_name") != account:
                continue
            if task and item.get("task_name") != task:
                continue
            raw_key = item.get(key_field)
            if key_field == "chat_id":
                bucket_key: Union[str, Tuple[str, str]] = (
                    str(raw_key if raw_key is not None else "-"),
                    str(item.get("chat_title") or raw_key or "-"),
                )
            else:
                bucket_key = str(raw_key or "-")
            counts[bucket_key] += 1
            if len(buckets[bucket_key]) < per:
                buckets[bucket_key].append(dict(item))

        groups = []
        for key, items in buckets.items():
            if isinstance(key, tuple):
                group_key, group_label = key
            else:
                group_key = key
                group_label = key
            groups.append(
                {
                    "key": group_key,
                    "label": group_label,
                    "count": counts[key],
                    "items": items,
                }
            )

    groups.sort(key=lambda g: (-int(g["count"]), str(g["label"])))
    return {"group_by": normalized_group, "groups": groups}


def export_keyword_hits_csv(
    *,
    account_name: Optional[str] = None,
    task_name: Optional[str] = None,
    limit: int = 2000,
) -> str:
    """导出 CSV 文本（UTF-8 BOM 由路由层添加）。"""
    data = list_keyword_hits(
        account_name=account_name,
        task_name=task_name,
        limit=min(max(1, int(limit or 2000)), MAX_RECORDS),
        offset=0,
        max_limit=MAX_RECORDS,
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
                _csv_cell(item.get("time")),
                _csv_cell(item.get("account_name")),
                _csv_cell(item.get("task_name")),
                _csv_cell(item.get("chat_id")),
                _csv_cell(item.get("chat_title")),
                _csv_cell(item.get("keyword")),
                _csv_cell("|".join(item.get("keywords") or [])),
                _csv_cell(item.get("sender")),
                _csv_cell(item.get("message_id")),
                _csv_cell(item.get("message_text")),
                _csv_cell(item.get("url")),
                _csv_cell(item.get("push_channel")),
                _csv_cell(item.get("message_thread_id")),
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
