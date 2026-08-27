"""后台同步/监控重启失败日志降噪回归（公共 sync_helpers 模块）。

首次失败打 ERROR + 完整堆栈便于排障；连续失败降级为 WARNING 且不带堆栈，
避免调度/监控反复失败时刷屏。
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from backend.services import sync_helpers


def test_failure_first_error_then_warning(caplog):
    sync_helpers._fail_counts.clear()
    with caplog.at_level(logging.DEBUG, logger="backend.sync_helpers"):
        sync_helpers._log_failure("k", "同步失败", RuntimeError("boom1"))
        sync_helpers._log_failure("k", "同步失败", RuntimeError("boom2"))

    records = [r for r in caplog.records if r.name == "backend.sync_helpers"]
    assert len(records) == 2
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None, "首次失败应携带堆栈"
    assert "boom1" in records[0].getMessage()
    assert records[1].levelno == logging.WARNING
    assert records[1].exc_info is None, "连续失败应抑制堆栈"
    assert "连续第 2 次" in records[1].getMessage()


def test_failure_key_isolated(caplog):
    """不同失败来源计数隔离：各自首次都打 ERROR。"""
    sync_helpers._fail_counts.clear()
    with caplog.at_level(logging.DEBUG, logger="backend.sync_helpers"):
        sync_helpers._log_failure("a", "A 失败", RuntimeError("a1"))
        sync_helpers._log_failure("b", "B 失败", RuntimeError("b1"))
    records = [r for r in caplog.records if r.name == "backend.sync_helpers"]
    assert [r.levelno for r in records] == [logging.ERROR, logging.ERROR]


def test_success_resets_fail_count(caplog):
    """成功后失败计数重置：恢复后的新失败重新打 ERROR+堆栈。"""
    sync_helpers._fail_counts.clear()
    with caplog.at_level(logging.DEBUG, logger="backend.sync_helpers"):
        sync_helpers._log_failure("k", "同步失败", RuntimeError("boom1"))
        sync_helpers._log_failure("k", "同步失败", RuntimeError("boom2"))
        sync_helpers._reset_fail_count("k")
        sync_helpers._log_failure("k", "同步失败", RuntimeError("boom3"))
    records = [r for r in caplog.records if r.name == "backend.sync_helpers"]
    assert [r.levelno for r in records] == [
        logging.ERROR,
        logging.WARNING,
        logging.ERROR,
    ]
    assert records[2].exc_info is not None, "恢复后的新失败应重新携带堆栈"


def test_sync_jobs_failure_does_not_block_restart():
    """sync_jobs 失败后仍继续重启监控，两者相互独立。"""
    calls: list[str] = []

    async def _fake_sync_jobs():
        calls.append("sync_jobs")
        raise RuntimeError("scheduler broken")

    async def _fake_restart(*, context: str = ""):
        calls.append("restart")

    with patch("backend.scheduler.sync_jobs", side_effect=_fake_sync_jobs), patch(
        "backend.services.sync_helpers.restart_keyword_monitors",
        side_effect=_fake_restart,
    ):
        import asyncio

        asyncio.run(sync_helpers.sync_jobs_and_restart_monitors(context="测试"))

    assert calls == ["sync_jobs", "restart"]


def test_restart_keyword_monitors_failure_logged(caplog):
    """重启监控失败走降噪日志，不向上抛。"""
    sync_helpers._fail_counts.clear()
    with patch(
        "backend.services.keyword_monitor.get_keyword_monitor_service",
        side_effect=RuntimeError("monitor broken"),
    ):
        import asyncio

        with caplog.at_level(logging.DEBUG, logger="backend.sync_helpers"):
            asyncio.run(sync_helpers.restart_keyword_monitors(context="测试"))

    records = [r for r in caplog.records if r.name == "backend.sync_helpers"]
    assert records and records[0].levelno == logging.ERROR


def test_route_delegates_to_shared_helper():
    """任务/导入/批量路由的后台同步均委托公共 helper，避免实现漂移。"""
    from backend.api.routes import batch as batch_mod
    from backend.api.routes import config as config_mod
    from backend.api.routes import sign_tasks_v2

    # 代码层面确认委托：函数体引用公共模块符号
    assert "sync_helpers" in sign_tasks_v2._safe_background_sync.__doc__ or (
        "sync_helpers" in _source_of(sign_tasks_v2._safe_background_sync)
    )
    assert "sync_helpers" in _source_of(config_mod._post_import_sync)
    assert "sync_helpers" in _source_of(batch_mod._restart_keyword_monitors)


def _source_of(func) -> str:
    import inspect

    return inspect.getsource(func)
