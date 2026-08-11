"""调度同步与关键词监控重启的公共后台辅助。

创建/更新/删除任务、配置导入、批量操作等变更后，需要异步同步调度并重启关键词监控。
本模块收敛「同步 + 重启 + 失败降噪日志」公共逻辑，避免各路由重复实现。

失败降噪策略：同一来源首次失败打 ERROR + 完整堆栈便于排障，
连续失败降级为 WARNING 且不带堆栈，避免调度/监控反复失败时刷屏。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("backend.sync_helpers")

# 失败次数计数：key 为失败来源（如 sync_jobs / restart_monitors）
_fail_counts: dict[str, int] = {}


def _log_failure(key: str, message: str, exc: Exception) -> None:
    count = _fail_counts.get(key, 0)
    _fail_counts[key] = count + 1
    if count == 0:
        logger.error("%s: %s", message, exc, exc_info=True)
    else:
        logger.warning("%s（连续第 %s 次）: %s", message, count + 1, exc)


async def restart_keyword_monitors(*, context: str = "操作") -> None:
    """重启关键词监控；失败仅降噪告警，不阻塞调用方。"""
    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        await get_keyword_monitor_service().restart_from_tasks()
    except Exception as exc:
        _log_failure("restart_monitors", f"{context}后重启关键词监控失败", exc)


async def sync_jobs_and_restart_monitors(*, context: str = "任务变更") -> None:
    """后台同步调度并重启关键词监控；失败仅降噪告警，不阻塞调用方。"""
    try:
        from backend.scheduler import sync_jobs

        await sync_jobs()
    except Exception as exc:
        _log_failure("sync_jobs", f"{context}后调度同步失败", exc)
    await restart_keyword_monitors(context=context)
