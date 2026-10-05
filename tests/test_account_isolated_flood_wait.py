from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.device_keepalive import DeviceKeepaliveService
from backend.services.flood_backoff import get_flood_backoff_manager


def test_flood_wait_isolation_between_accounts():
    mgr = get_flood_backoff_manager()
    mgr.clear()

    # 账号 A 报告 FloodWait 30 秒
    mgr.record_flood_wait(account_name="account_alpha", wait_seconds=30)

    # 断言账号 A 正处于避让惩罚中，剩余时间 > 25
    assert mgr.is_account_in_flood("account_alpha") is True
    assert mgr.get_remaining_wait("account_alpha") > 25

    # 关键断言：账号 B 绝不应该受影响！
    assert mgr.is_account_in_flood("account_beta") is False
    assert mgr.get_remaining_wait("account_beta") == 0


@pytest.mark.asyncio
async def test_device_keepalive_skips_flood_wait_account_only(isolated_env):
    mgr = get_flood_backoff_manager()
    mgr.clear()

    # 账号 alpha 处于 FloodWait
    mgr.record_flood_wait(account_name="account_alpha", wait_seconds=60)

    service = DeviceKeepaliveService()

    fake_accounts = [
        {"name": "account_alpha"},
        {"name": "account_beta"},
    ]

    mock_tg = MagicMock()
    mock_tg.list_accounts.return_value = fake_accounts
    mock_tg.check_account_status = AsyncMock(return_value={"ok": True})

    with (
        patch(
            "backend.services.device_keepalive.get_telegram_service",
            return_value=mock_tg,
        ),
        patch("backend.services.device_keepalive.get_config_service") as mock_cfg_svc,
    ):
        mock_cfg_svc.return_value.load_global_settings.return_value = {
            "enable_device_keepalive": True,
            "device_keepalive_interval_days": 1,
        }

        result = await service.run_keepalive(force=True)

        # 断言：alpha 被跳过，beta 成功保活
        assert result["skipped"] == 1
        assert result["kept_alive"] == 1
        results = result["results"]
        alpha_res = next(r for r in results if r["account_name"] == "account_alpha")
        beta_res = next(r for r in results if r["account_name"] == "account_beta")

        assert alpha_res["status"] == "skipped"
        assert "FloodWait避让中" in alpha_res["message"]
        assert beta_res["status"] == "ok"
        # 仅对 beta 发起了 check_account_status 远程调用
        mock_tg.check_account_status.assert_called_once_with(
            "account_beta", timeout_seconds=12.0, no_updates=True
        )
