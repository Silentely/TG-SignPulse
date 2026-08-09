"""设备保活服务测试：间隔配置容错、启停门控、并发忙响应与状态持久化。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core import config as config_module
from backend.services import device_keepalive as dk_mod
from backend.services.device_keepalive import DeviceKeepaliveService


def _fake_cfg(settings: dict) -> SimpleNamespace:
    return SimpleNamespace(get_global_settings=lambda: dict(settings))


@pytest.fixture()
def keepalive(tmp_path, monkeypatch):
    """隔离数据目录的服务实例 + 可控配置与 telegram 替身。"""

    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    config_module.get_settings.cache_clear()

    settings = {"device_keepalive_enabled": True}
    monkeypatch.setattr(
        dk_mod, "get_config_service", lambda: _fake_cfg(settings)
    )
    tg = MagicMock()
    tg.list_accounts.return_value = [{"name": "acc1"}]
    tg.check_account_status = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(dk_mod, "get_telegram_service", lambda: tg)

    svc = DeviceKeepaliveService()
    yield SimpleNamespace(svc=svc, settings=settings, tg=tg)
    config_module.get_settings.cache_clear()


class TestIntervalParsing:
    @pytest.mark.asyncio()
    async def test_invalid_interval_falls_back_to_default(self, keepalive):
        keepalive.settings["device_keepalive_interval_days"] = "abc"
        result = await keepalive.svc.run_due()
        assert result["interval_days"] == 30
        assert result["kept_alive"] == 1

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, 1), (-5, 1), (999, 170), ("7", 7), (30, 30)],
    )
    async def test_interval_clamped_to_bounds(self, keepalive, value, expected):
        keepalive.settings["device_keepalive_interval_days"] = value
        result = await keepalive.svc.run_due()
        assert result["interval_days"] == expected


class TestEnabledGate:
    @pytest.mark.asyncio()
    async def test_disabled_without_force_short_circuits(self, keepalive):
        keepalive.settings["device_keepalive_enabled"] = False
        result = await keepalive.svc.run_due()
        assert result["enabled"] is False
        assert result["checked"] == 0
        keepalive.tg.check_account_status.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_disabled_with_force_still_runs(self, keepalive):
        keepalive.settings["device_keepalive_enabled"] = False
        result = await keepalive.svc.run_due(force=True)
        assert result["enabled"] is False
        assert result["kept_alive"] == 1

    @pytest.mark.asyncio()
    async def test_busy_response_reports_real_enabled(self, keepalive):
        keepalive.settings["device_keepalive_enabled"] = False
        await keepalive.svc._running_lock.acquire()
        try:
            result = await keepalive.svc.run_due()
        finally:
            keepalive.svc._running_lock.release()
        assert result["success"] is False
        assert result["enabled"] is False
        assert "运行中" in result["message"]


class TestRunBehavior:
    @pytest.mark.asyncio()
    async def test_ok_result_persisted_and_skipped_next_run(self, keepalive):
        first = await keepalive.svc.run_due()
        assert first["kept_alive"] == 1
        state = json.loads(keepalive.svc.state_file.read_text(encoding="utf-8"))
        assert state["accounts"]["acc1"]["last_ok_at"]
        assert state["last_run_at"]

        second = await keepalive.svc.run_due()
        assert second["skipped"] == 1
        assert second["checked"] == 0
        assert second["results"][0]["status"] == "skipped"
        # 硬编码 message 中文化：未到期 / 保活成功
        assert second["results"][0]["message"] == "未到期"
        assert first["results"][0]["message"] == "保活成功"

    @pytest.mark.asyncio()
    async def test_failed_status_records_error(self, keepalive):
        keepalive.tg.check_account_status.return_value = {
            "ok": False,
            "message": "session invalid",
        }
        result = await keepalive.svc.run_due()
        assert result["success"] is False
        assert result["failed"] == 1
        assert result["results"][0]["message"] == "session invalid"
        state = json.loads(keepalive.svc.state_file.read_text(encoding="utf-8"))
        assert state["accounts"]["acc1"]["last_error"] == "session invalid"
        assert "last_ok_at" not in state["accounts"]["acc1"]

    @pytest.mark.asyncio()
    async def test_check_exception_tolerated(self, keepalive):
        keepalive.tg.check_account_status.side_effect = RuntimeError("network")
        result = await keepalive.svc.run_due()
        assert result["failed"] == 1
        assert "network" in result["results"][0]["message"]

    @pytest.mark.asyncio()
    async def test_force_ignores_fresh_state(self, keepalive):
        await keepalive.svc.run_due()
        forced = await keepalive.svc.run_due(force=True)
        assert forced["kept_alive"] == 1
        assert forced["skipped"] == 0
        assert keepalive.tg.check_account_status.await_count == 2
