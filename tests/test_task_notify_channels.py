"""任务级通知渠道测试。

覆盖:
- 渠道 id 清洗与 Webhook 解析
- dispatch_matrix_notification 按任务选择的渠道发送，缺失/未知渠道只记日志
- 任务指定渠道时走矩阵渠道，未指定时回落到原有 TG Bot 行为
- 渠道发送异常不影响任务结果
- 执行器把任务配置里的 notify_channel_ids 传给通知层
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import config as config_mod
from backend.services import push_notifications as push_mod
from backend.services import sign_task_notify
from backend.services.notification_channels import (
    normalize_channel_ids,
    resolve_channel_webhook,
)
from backend.services.sign_task_config_build import (
    build_sign_task_config,
    resolve_update_field_values,
)
from backend.services.sign_task_runner import _runner_send_notifications


class _FakeConfigService:
    def __init__(self, settings: dict):
        self._settings = settings

    def get_global_settings(self) -> dict:
        return dict(self._settings)


@pytest.fixture()
def channel_env(monkeypatch):
    settings = {
        "telegram_bot_notify_enabled": True,
        "telegram_bot_task_failure_enabled": True,
        "telegram_bot_task_success_enabled": True,
        "telegram_bot_token": "tok",
        "telegram_bot_chat_id": "chat",
        "wecom_webhook_url": "https://qyapi.weixin.qq.com/webhook",
        "feishu_webhook_url": "https://open.feishu.cn/webhook",
        "dingtalk_webhook_url": "",
        "discord_webhook_url": "https://discord.com/webhook",
    }
    monkeypatch.setattr(
        config_mod, "get_config_service", lambda: _FakeConfigService(settings)
    )
    monkeypatch.setattr(push_mod, "is_in_quiet_hours", lambda cfg: False)

    mocks = SimpleNamespace(
        settings=settings,
        wecom=AsyncMock(),
        feishu=AsyncMock(),
        dingtalk=AsyncMock(),
        discord=AsyncMock(),
        bot=AsyncMock(),
        success=AsyncMock(),
    )
    monkeypatch.setattr(push_mod, "send_wecom_message", mocks.wecom)
    monkeypatch.setattr(push_mod, "send_feishu_message", mocks.feishu)
    monkeypatch.setattr(push_mod, "send_dingtalk_message", mocks.dingtalk)
    monkeypatch.setattr(push_mod, "send_discord_message", mocks.discord)
    monkeypatch.setattr(push_mod, "send_telegram_bot_message", mocks.bot)
    monkeypatch.setattr(push_mod, "send_outbox_telegram_message", mocks.bot)
    monkeypatch.setattr(push_mod, "send_task_success_notification", mocks.success)
    return mocks


def test_normalize_channel_ids_dedupes_and_lowercases():
    assert normalize_channel_ids([" WeCom ", "wecom", "", None, "FEISHU"]) == [
        "wecom",
        "feishu",
    ]
    assert normalize_channel_ids("discord") == ["discord"]
    assert normalize_channel_ids(None) == []


def test_resolve_channel_webhook():
    settings = {"wecom_webhook_url": " https://wecom ", "feishu_webhook_url": ""}
    assert resolve_channel_webhook(settings, "wecom") == "https://wecom"
    assert resolve_channel_webhook(settings, "feishu") is None
    assert resolve_channel_webhook(settings, "slack") is None


@pytest.mark.asyncio
async def test_dispatch_only_selected_channels(channel_env):
    await push_mod.dispatch_matrix_notification(
        channel_env.settings,
        title="t",
        fields=[("账号", "acc")],
        channel_ids=["feishu", "discord"],
    )
    channel_env.feishu.assert_awaited_once()
    channel_env.discord.assert_awaited_once()
    channel_env.wecom.assert_not_awaited()
    channel_env.dingtalk.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_skips_unknown_and_unconfigured_channels(channel_env, caplog):
    with caplog.at_level("WARNING", logger="backend.push_notifications"):
        # slack 不存在;dingtalk 未配置 Webhook
        await push_mod.dispatch_matrix_notification(
            channel_env.settings,
            title="t",
            fields=[("账号", "acc")],
            channel_ids=["slack", "dingtalk", "wecom"],
        )

    channel_env.wecom.assert_awaited_once()
    assert any("slack" in rec.message for rec in caplog.records)
    assert any("dingtalk" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_dispatch_swallows_channel_send_error(channel_env):
    channel_env.wecom.side_effect = RuntimeError("webhook down")
    # 不应向上抛出:通知失败不能影响任务结果
    await push_mod.dispatch_matrix_notification(
        channel_env.settings,
        title="t",
        fields=[("账号", "acc")],
        channel_ids=["wecom"],
    )
    channel_env.wecom.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_channels_used_and_bot_path_skipped(channel_env):
    await sign_task_notify.send_failure_notification(
        account_name="acc",
        task_name="task",
        message="boom",
        channel_ids=["wecom"],
    )
    channel_env.wecom.assert_awaited_once()
    # 任务显式指定渠道后不再回落到 TG Bot
    channel_env.bot.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_channels_used(channel_env):
    await sign_task_notify.send_success_notification(
        account_name="acc",
        task_name="task",
        message="done",
        channel_ids=["feishu"],
    )
    channel_env.feishu.assert_awaited_once()
    channel_env.success.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_channels_falls_back_to_existing_bot(channel_env):
    await sign_task_notify.send_failure_notification(
        account_name="acc",
        task_name="task",
        message="boom",
        channel_ids=None,
    )
    channel_env.bot.assert_awaited_once()
    channel_env.wecom.assert_not_awaited()
    channel_env.feishu.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_passes_task_channel_ids(monkeypatch):
    captured = {}

    async def fake_failure(**kwargs):
        captured["failure"] = kwargs

    async def fake_success(**kwargs):
        captured["success"] = kwargs

    monkeypatch.setattr(sign_task_notify, "send_failure_notification", fake_failure)
    monkeypatch.setattr(sign_task_notify, "send_success_notification", fake_success)

    state = {
        "success": False,
        "task_cfg": {"notify_channel_ids": ["wecom"]},
        "task_notify_on_failure": True,
        "account_name": "acc",
        "task_name": "task",
        "error_msg": "boom",
        "last_reply": "",
        "final_logs": [],
        "run_id": "r1",
        "aggregate_status": "failure",
    }
    await _runner_send_notifications(state)
    assert captured["failure"]["channel_ids"] == ["wecom"]

    state_success = dict(state, success=True, task_notify_on_success=True)
    await _runner_send_notifications(state_success)
    assert captured["success"]["channel_ids"] == ["wecom"]


def test_task_config_persists_channel_ids():
    cfg = build_sign_task_config(
        account_name="acc",
        account_names=["acc"],
        sign_at="09:00",
        chats=[],
        notify_channel_ids=[" WeCom ", "wecom", "feishu"],
    )
    assert cfg["notify_channel_ids"] == ["wecom", "feishu"]

    updated = resolve_update_field_values(
        {"notify_channel_ids": ["wecom"]}, notify_channel_ids=["discord"]
    )
    assert updated["notify_channel_ids"] == ["discord"]
    # 未显式更新时沿用既有值
    assert resolve_update_field_values({"notify_channel_ids": ["wecom"]})[
        "notify_channel_ids"
    ] == ["wecom"]


def test_list_available_channels_returns_metadata_and_configured_flag():
    from backend.services.notification_channels import list_available_channels

    settings = {
        "wecom_webhook_url": "https://wecom.example.com",
        "feishu_webhook_url": "",
    }
    channels = list_available_channels(settings)
    by_id = {c["id"]: c for c in channels}
    assert by_id["wecom"]["configured"] is True
    assert by_id["wecom"]["label"] == "企业微信"
    assert by_id["wecom"]["settings_key"] == "wecom_webhook_url"
    assert by_id["feishu"]["configured"] is False
    # 绝不能泄露真实 webhook url
    for c in channels:
        assert "url" not in c


def test_get_notify_channels_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.core.auth import get_current_user
    from backend.main import app

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    try:
        client = TestClient(app)
        res = client.get("/api/sign-tasks/notify-channels")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        ids = [item["id"] for item in data]
        assert "wecom" in ids
        assert "feishu" in ids
        assert "dingtalk" in ids
        assert "discord" in ids
    finally:
        app.dependency_overrides.pop(get_current_user, None)
