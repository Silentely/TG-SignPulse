"""
账号会话状态批量检查 Job。

基于 BackgroundJobStore：可取消、可落盘、服务重启后中断任务标记 failed。
前端批量检测走异步 Job，避免账号多时 HTTP 长阻塞。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.background_job import BackgroundJobStore
from backend.utils.names import validate_storage_name

logger = logging.getLogger("backend.account_status_jobs")

KIND = "account_status_check"
MAX_ACCOUNTS = 200
DEFAULT_TIMEOUT = 8.0
MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 20.0
INTER_DELAY_SECONDS = 0.15

_store: Optional[BackgroundJobStore] = None
# 防止并发 start 竞态创建两个请求同时通过“无 running”检查
_start_lock = threading.Lock()


def get_account_status_job_store() -> BackgroundJobStore:
    global _store
    if _store is None:
        root = get_settings().resolve_workdir() / "jobs" / "account_status"
        _store = BackgroundJobStore(root)
    return _store


def _normalize_names(account_names: Optional[List[str]]) -> List[str]:
    from backend.services.telegram import get_telegram_service

    service = get_telegram_service()
    if account_names:
        names: List[str] = []
        seen: set[str] = set()
        for name in account_names:
            normalized = (name or "").strip()
            if not normalized or normalized in seen:
                continue
            # 与路径段校验一致，拒绝穿越/非法账号名
            try:
                normalized = validate_storage_name(
                    normalized, field_name="account_name"
                )
            except ValueError:
                continue
            seen.add(normalized)
            names.append(normalized)
    else:
        names = [
            str(item.get("name") or "").strip()
            for item in service.list_accounts()
            if str(item.get("name") or "").strip()
        ]
    if len(names) > MAX_ACCOUNTS:
        raise ValueError(f"单次最多检测 {MAX_ACCOUNTS} 个账号")
    if not names:
        raise ValueError("没有可检测的账号")
    return names


def _clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value if value is not None else DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, min(timeout, MAX_TIMEOUT))


async def _run_status_check(job_id: str, names: List[str], timeout_seconds: float) -> None:
    from backend.services.telegram import get_telegram_service

    store = get_account_status_job_store()
    service = get_telegram_service()
    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0

    store.append_log(
        job_id,
        "info",
        f"开始批量检测 {len(names)} 个账号，超时 {timeout_seconds:.1f}s",
    )

    for idx, name in enumerate(names):
        if store.is_cancel_requested(job_id):
            store.append_log(job_id, "info", "检测已取消")
            break
        try:
            item = await service.check_account_status(
                name, timeout_seconds=timeout_seconds
            )
        except Exception as exc:
            item = {
                "account_name": name,
                "ok": False,
                "status": "error",
                "message": str(exc) or "status check failed",
                "code": "STATUS_CHECK_FAILED",
                "checked_at": None,
                "needs_relogin": False,
            }
        if not isinstance(item, dict):
            item = {
                "account_name": name,
                "ok": False,
                "status": "error",
                "message": "invalid status payload",
                "code": "STATUS_CHECK_FAILED",
            }
        results.append(item)
        if item.get("ok"):
            ok_count += 1
            store.append_log(job_id, "info", f"{name}: 正常", ref=name)
        else:
            fail_count += 1
            msg = item.get("message") or item.get("code") or item.get("status") or "异常"
            store.append_log(job_id, "error", f"{name}: {msg}", ref=name)

        store.update_progress(
            job_id,
            done=idx + 1,
            total=len(names),
            extra={"ok": ok_count, "fail": fail_count},
        )
        if idx < len(names) - 1 and not store.is_cancel_requested(job_id):
            await asyncio.sleep(INTER_DELAY_SECONDS)

    summary = {
        "total": len(names),
        "checked": len(results),
        "ok": ok_count,
        "fail": fail_count,
    }
    # mark_completed 在 canceling 时会记为 canceled
    store.mark_completed(job_id, summary=summary, results=results)


def start_account_status_check_job(
    *,
    account_names: Optional[List[str]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """创建并启动批量状态检测 Job，立即返回 job 视图。"""
    names = _normalize_names(account_names)
    timeout = _clamp_timeout(timeout_seconds)
    store = get_account_status_job_store()

    with _start_lock:
        # 同一时刻只允许一个 running 批量检测，避免对 Telegram 过载
        for job in store.list_jobs(limit=10):
            if job.get("kind") == KIND and job.get("status") in {
                "running",
                "canceling",
            }:
                raise ValueError("已有批量状态检测在运行，请稍后再试或先取消")

        created = store.create_job(
            kind=KIND,
            payload={
                "account_names": names,
                "timeout_seconds": timeout,
            },
            progress={"total": len(names), "done": 0, "ok": 0, "fail": 0},
        )
        job_id = str(created["job_id"])

        async def _runner() -> None:
            try:
                await _run_status_check(job_id, names, timeout)
            except Exception as exc:
                logger.exception("account status job %s failed", job_id)
                store.mark_failed(job_id, str(exc) or "status check job failed")

        store.start_background(job_id, _runner, name=f"account-status-{job_id[:8]}")
        return store.get_job(job_id) or created


def get_account_status_job(job_id: str) -> Optional[Dict[str, Any]]:
    return get_account_status_job_store().get_job(job_id)


def list_account_status_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    jobs = get_account_status_job_store().list_jobs(limit=limit)
    return [job for job in jobs if job.get("kind") == KIND]


def cancel_account_status_job(job_id: str) -> bool:
    store = get_account_status_job_store()
    job = store.get_job(job_id)
    if not job or job.get("kind") != KIND:
        return False
    return store.request_cancel(job_id)
