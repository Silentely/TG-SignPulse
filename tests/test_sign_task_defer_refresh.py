"""SignTaskService.defer_cache_refresh 批量写抑制机制测试。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.auth import create_access_token


def _make_service_with_spy():
    """构造不走 __init__ 的 SignTaskService，并用列表记录 list_tasks 调用。"""
    from backend.services.sign_tasks import SignTaskService

    svc = SignTaskService.__new__(SignTaskService)
    svc._cache_refresh_deferred = 0
    calls: list[dict] = []
    svc.list_tasks = lambda **kwargs: calls.append(kwargs) or []
    return svc, calls


def test_refresh_after_write_triggers_rescan_normally():
    """未 defer 时，写后立即触发一次全量刷新。"""
    svc, calls = _make_service_with_spy()
    svc._refresh_tasks_cache_after_write()
    assert calls == [{"force_refresh": True, "aggregate": False}]


def test_defer_cache_refresh_suppresses_and_flushes_once():
    """defer 上下文内多次写不触发重扫，退出时统一刷一次。"""
    svc, calls = _make_service_with_spy()

    with svc.defer_cache_refresh():
        svc._refresh_tasks_cache_after_write()
        svc._refresh_tasks_cache_after_write()
        assert calls == []

    assert calls == [{"force_refresh": True, "aggregate": False}]


def test_defer_cache_refresh_nested_flushes_once():
    """嵌套 defer 仅在最外层退出时刷一次。"""
    svc, calls = _make_service_with_spy()

    with svc.defer_cache_refresh():
        with svc.defer_cache_refresh():
            svc._refresh_tasks_cache_after_write()
        assert calls == []
        assert svc._cache_refresh_deferred == 1
    assert svc._cache_refresh_deferred == 0
    assert calls == [{"force_refresh": True, "aggregate": False}]


def test_defer_cache_refresh_flushes_on_exception():
    """上下文内抛异常仍恢复计数并刷一次缓存。"""
    svc, calls = _make_service_with_spy()

    with pytest.raises(RuntimeError), svc.defer_cache_refresh():
        svc._refresh_tasks_cache_after_write()
        raise RuntimeError("boom")

    assert svc._cache_refresh_deferred == 0
    assert calls == [{"force_refresh": True, "aggregate": False}]


def test_batch_route_defers_service_cache_refresh(client, db_session):
    """批量路由应将服务调用包进 defer_cache_refresh 上下文。"""
    service = MagicMock()
    service.get_task.return_value = {
        "name": "daily",
        "account_name": "acc1",
        "account_names": ["acc1"],
        "enabled": False,
    }
    service.update_task.return_value = {"name": "daily", "enabled": True}

    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(hours=1))
    with (
        patch(
            "backend.api.routes.batch.get_sign_task_service",
            return_value=service,
        ),
        patch(
            "backend.api.routes.batch.sync_jobs",
            new_callable=AsyncMock,
        ),
        patch(
            "backend.api.routes.batch._restart_keyword_monitors",
            new_callable=AsyncMock,
        ),
    ):
        resp = client.post(
            "/api/batch/sign-tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "action": "enable",
                "tasks": [
                    {"name": "daily", "account_name": "acc1"},
                    {"name": "weekly", "account_name": "acc1"},
                ],
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success_count"] == 2
    service.defer_cache_refresh.assert_called_once()
