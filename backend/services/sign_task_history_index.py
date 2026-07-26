"""
签到历史轻量索引

维护 `history/_recent_index.jsonl`：每次 run 落盘时追加一行摘要，
供 Dashboard SSE / 最近日志接口 O(尾部读取) 使用，避免全任务扫盘。

索引行字段（JSON object, 一行一条）:
  time, account_name, task_name, success, message, failure_category
不存 flow_logs，详情仍走原 history 文件。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("backend.sign_task_history_index")

INDEX_FILENAME = "_recent_index.jsonl"
DEFAULT_MAX_LINES = 2000

# 进程内最近条目缓存，供 SSE 高频读取；写路径同步更新
_memory_lock = threading.Lock()
_memory_recent: List[Dict[str, Any]] = []
_memory_max = 200
_memory_dir: Optional[str] = None


def index_file_path(run_history_dir: Path) -> Path:
    return Path(run_history_dir) / INDEX_FILENAME


def build_index_entry(
    *,
    time: str,
    account_name: str,
    task_name: str,
    success: bool,
    message: str = "",
    failure_category: str = "",
) -> Dict[str, Any]:
    """构造索引摘要行（无 flow_logs）。"""
    return {
        "time": str(time or ""),
        "created_at": str(time or ""),
        "account_name": str(account_name or ""),
        "task_name": str(task_name or ""),
        "success": bool(success),
        "message": str(message or "")[:500],
        "failure_category": str(failure_category or ""),
    }


def entry_from_history_item(
    item: Dict[str, Any],
    *,
    task_name: str,
    account_name: str,
) -> Dict[str, Any]:
    ts = str(item.get("time") or "")
    acc = str(item.get("account_name") or account_name or "")
    return build_index_entry(
        time=ts,
        account_name=acc,
        task_name=str(task_name or item.get("task_name") or ""),
        success=bool(item.get("success", False)),
        message=str(item.get("message") or ""),
        failure_category=str(item.get("failure_category") or ""),
    )


def _entry_key(entry: Dict[str, Any]) -> str:
    return (
        f"{entry.get('account_name')}|{entry.get('task_name')}|"
        f"{entry.get('time') or entry.get('created_at')}|{entry.get('success')}"
    )


def _sync_memory(run_history_dir: Path, entries_newest_first: List[Dict[str, Any]]) -> None:
    global _memory_recent, _memory_dir
    with _memory_lock:
        _memory_dir = str(run_history_dir.resolve())
        _memory_recent = list(entries_newest_first[:_memory_max])


def _prepend_memory(run_history_dir: Path, entry: Dict[str, Any]) -> None:
    global _memory_recent, _memory_dir
    with _memory_lock:
        dir_key = str(run_history_dir.resolve())
        if _memory_dir != dir_key:
            _memory_dir = dir_key
            _memory_recent = []
        # 去重：同 key 已存在则先移除
        key = _entry_key(entry)
        _memory_recent = [e for e in _memory_recent if _entry_key(e) != key]
        _memory_recent.insert(0, entry)
        if len(_memory_recent) > _memory_max:
            _memory_recent = _memory_recent[:_memory_max]


def get_memory_recent(
    run_history_dir: Path,
    *,
    limit: int = 50,
) -> Optional[List[Dict[str, Any]]]:
    """若内存缓存与目录匹配且非空，返回副本；否则 None（调用方应读盘）。"""
    with _memory_lock:
        if _memory_dir != str(run_history_dir.resolve()):
            return None
        if not _memory_recent:
            return None
        return list(_memory_recent[: max(1, int(limit))])


def clear_memory_cache() -> None:
    global _memory_recent, _memory_dir
    with _memory_lock:
        _memory_recent = []
        _memory_dir = None


def append_index_entry(
    run_history_dir: Path,
    entry: Dict[str, Any],
    *,
    max_lines: int = DEFAULT_MAX_LINES,
) -> None:
    """追加一条索引；超出 max_lines 时截断尾部旧行。"""
    run_history_dir = Path(run_history_dir)
    run_history_dir.mkdir(parents=True, exist_ok=True)
    path = index_file_path(run_history_dir)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        logger.warning("写入历史索引失败 path=%s: %s", path, exc)
        return

    _prepend_memory(run_history_dir, entry)
    _maybe_trim_index_file(path, max_lines=max_lines)
    # 实时推送：有 SSE 订阅者时即时通知（无订阅则为空操作）
    try:
        from backend.services.sign_history_events import publish_sign_history

        publish_sign_history(entry)
    except Exception as exc:
        logger.debug("发布历史事件失败: %s", exc)


def _maybe_trim_index_file(path: Path, *, max_lines: int) -> None:
    """文件行数粗略超过阈值时，只保留最后 max_lines 行。"""
    try:
        # 快速路径：文件不大时直接读
        size = path.stat().st_size
        # 粗估：每行 ~200 字节，超过 3 倍阈值再截断
        if size < max(max_lines, 1) * 200 * 3:
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_lines:
            return
        kept = lines[-max_lines:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except OSError as exc:
        logger.debug("截断历史索引失败: %s", exc)


def read_index_entries(
    run_history_dir: Path,
    *,
    limit: int = 50,
    account_name: Optional[str] = None,
    date_prefix: str = "",
) -> List[Dict[str, Any]]:
    """
    从索引读取最近条目（文件为 append 顺序，新在尾）。

    返回 newest-first 列表。
    """
    limit = max(1, int(limit or 1))
    path = index_file_path(run_history_dir)
    if not path.exists():
        return []

    acc_filter = str(account_name or "").strip()
    prefix = str(date_prefix or "").strip()[:10]

    # 读全文件再过滤：索引有行数上限，可接受
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except OSError as exc:
        logger.warning("读取历史索引失败 path=%s: %s", path, exc)
        return []

    collected: List[Dict[str, Any]] = []
    for line in reversed(raw_lines):
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if acc_filter and str(obj.get("account_name") or "") != acc_filter:
            continue
        ts = str(obj.get("time") or obj.get("created_at") or "")
        if prefix and not ts.startswith(prefix):
            continue
        # 规范化字段
        entry = build_index_entry(
            time=ts,
            account_name=str(obj.get("account_name") or ""),
            task_name=str(obj.get("task_name") or ""),
            success=bool(obj.get("success", False)),
            message=str(obj.get("message") or ""),
            failure_category=str(obj.get("failure_category") or ""),
        )
        collected.append(entry)
        if len(collected) >= limit:
            break
    return collected


def remove_index_entries_matching(
    run_history_dir: Path,
    *,
    account_name: str = "",
    task_name: str = "",
    created_at: str = "",
) -> int:
    """
    从索引文件删除匹配行。返回删除条数。

    任一过滤条件为空则不作为匹配条件（须至少一项非空）。
    """
    path = index_file_path(run_history_dir)
    if not path.exists():
        return 0
    acc = str(account_name or "").strip()
    task = str(task_name or "").strip()
    ts = str(created_at or "").strip()
    if not acc and not task and not ts:
        return 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0

    kept: List[str] = []
    removed = 0
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            kept.append(line if line.endswith("\n") else line + "\n")
            continue
        if not isinstance(obj, dict):
            kept.append(line if line.endswith("\n") else line + "\n")
            continue
        match = True
        if acc and str(obj.get("account_name") or "") != acc:
            match = False
        if task and str(obj.get("task_name") or "") != task:
            match = False
        if ts:
            entry_ts = str(obj.get("time") or obj.get("created_at") or "")
            if entry_ts != ts:
                match = False
        if match:
            removed += 1
            continue
        kept.append(json.dumps(obj, ensure_ascii=False) + "\n")

    if removed == 0:
        return 0
    try:
        if kept:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(kept)
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("重写历史索引失败: %s", exc)
        return 0

    clear_memory_cache()
    return removed


def clear_index(run_history_dir: Path) -> None:
    path = index_file_path(run_history_dir)
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("删除历史索引失败: %s", exc)
    clear_memory_cache()


def rebuild_index_from_history_files(
    run_history_dir: Path,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    load_file_entries: Optional[Any] = None,
) -> int:
    """
    从全部 `*.json` 历史文件重建索引（跳过索引自身）。

    load_file_entries: 可选 (path) -> list[dict]，便于测试注入。
    返回写入条数。
    """
    run_history_dir = Path(run_history_dir)
    if not run_history_dir.exists():
        clear_index(run_history_dir)
        return 0

    entries: List[Dict[str, Any]] = []
    for history_file in run_history_dir.glob("*.json"):
        if history_file.name.startswith("_"):
            continue
        # 文件名 acc__task.json 或 legacy task.json
        stem = history_file.stem
        if "__" in stem:
            acc_part, task_part = stem.split("__", 1)
        else:
            acc_part, task_part = "", stem

        if load_file_entries is not None:
            raw = load_file_entries(history_file)
        else:
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(data, list):
                raw = data
            elif isinstance(data, dict):
                raw = [data]
            else:
                raw = []

        for item in raw:
            if not isinstance(item, dict):
                continue
            acc = str(item.get("account_name") or acc_part or "")
            task = str(item.get("task_name") or task_part or "")
            entries.append(entry_from_history_item(item, task_name=task, account_name=acc))

    # 按 time 升序写入，使文件尾部为最新
    entries.sort(key=lambda e: str(e.get("time") or ""))
    if len(entries) > max_lines:
        entries = entries[-max_lines:]

    path = index_file_path(run_history_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("重建历史索引失败: %s", exc)
        return 0

    # 内存：newest first
    newest_first = list(reversed(entries))
    _sync_memory(run_history_dir, newest_first)
    return len(entries)


def ensure_index(
    run_history_dir: Path,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
) -> Path:
    """索引不存在时从历史文件重建。"""
    path = index_file_path(run_history_dir)
    if path.exists():
        return path
    rebuild_index_from_history_files(run_history_dir, max_lines=max_lines)
    return path


def list_recent_from_index(
    run_history_dir: Path,
    *,
    limit: int = 50,
    account_name: Optional[str] = None,
    date_prefix: str = "",
    prefer_memory: bool = True,
) -> List[Dict[str, Any]]:
    """
    对外主入口：优先内存 → 索引文件 → 必要时重建后再读。
    """
    run_history_dir = Path(run_history_dir)
    limit = max(1, int(limit or 1))

    if prefer_memory and not account_name and not date_prefix:
        mem = get_memory_recent(run_history_dir, limit=limit)
        if mem is not None:
            return mem

    ensure_index(run_history_dir)
    items = read_index_entries(
        run_history_dir,
        limit=limit,
        account_name=account_name,
        date_prefix=date_prefix,
    )
    if items:
        if not account_name and not date_prefix:
            _sync_memory(run_history_dir, items)
        return items

    # 索引空但可能有历史文件
    if any(run_history_dir.glob("*.json")) if run_history_dir.exists() else False:
        rebuild_index_from_history_files(run_history_dir)
        return read_index_entries(
            run_history_dir,
            limit=limit,
            account_name=account_name,
            date_prefix=date_prefix,
        )
    return []
