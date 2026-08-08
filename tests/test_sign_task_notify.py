"""sign_task_notify 通知与账号预检测试：配置门控、静默时段、失效标记与预检判定全分支。"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from backend.services import config as config_mod
from backend.services import push_notifications as push_mod
from backend.services import sign_task_notify
from backend.services import telegram as telegram_mod
from backend.services.push_notifications import _bot_config


class _FakeConfigService:
    def __init__(self, settings: dict):
        self._settings = settings

    def get_global_settings(self) -> dict:
        return dict(self._settings)


@pytest.fixture()
def notify_env(monkeypatch):
    """替换配置服务与推送发送层为可观察替身，返回环境句柄。"""

    settings = {
        "telegram_bot_notify_enabled": True,
        "telegram_bot_task_failure_enabled": True,
        "telegram_bot_token": "tok",
        "telegram_bot_chat_id": "chat",
        "telegram_bot_message_thread_id": "42",
    }
    sent: list[dict] = []
    successes: list[dict] = []

    monkeypatch.setattr(
        config_mod, "get_config_service", lambda: _FakeConfigService(settings)
    )

    async def _fake_send(**kwargs):
        sent.append(kwargs)

    async def _fake_success(cfg, *, account_name, task_name, message=""):
        successes.append(
            {
                "cfg": cfg,
                "account_name": account_name,
                "task_name": task_name,
                "message": message,
            }
        )

    monkeypatch.setattr(push_mod, "send_telegram_bot_message", _fake_send)
    monkeypatch.setattr(push_mod, "is_in_quiet_hours", lambda cfg: False)
    monkeypatch.setattr(push_mod, "send_task_success_notification", _fake_success)
    return SimpleNamespace(settings=settings, sent=sent, successes=successes)


class TestBotConfig:
    """Bot 凭据统一读取：token/chat_id 去空白、话题 ID 非法输入回落 None。"""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("42", 42), (7, 7), (None, None), ("", None), ("abc", None), ({}, None)],
    )
    def test_thread_id_parse(self, value, expected):
        _, _, thread_id = _bot_config({"telegram_bot_message_thread_id": value})
        assert thread_id == expected

    def test_token_chat_id_stripped(self):
        token, chat_id, _ = _bot_config(
            {
                "telegram_bot_token": "  tok  ",
                "telegram_bot_chat_id": " 123 ",
            }
        )
        assert token == "tok"
        assert chat_id == "123"

    def test_missing_keys_fallback_empty(self):
        token, chat_id, thread_id = _bot_config({})
        assert token == "" and chat_id == "" and thread_id is None


class TestSendFailureNotification:
    @pytest.mark.asyncio()
    async def test_notify_disabled_skips(self, notify_env):
        notify_env.settings["telegram_bot_notify_enabled"] = False
        await sign_task_notify.send_failure_notification(
            account_name="a", task_name="t", message="boom"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_failure_flag_disabled_skips(self, notify_env):
        notify_env.settings["telegram_bot_task_failure_enabled"] = False
        await sign_task_notify.send_failure_notification(
            account_name="a", task_name="t", message="boom"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_quiet_hours_skips(self, notify_env, monkeypatch):
        monkeypatch.setattr(push_mod, "is_in_quiet_hours", lambda cfg: True)
        await sign_task_notify.send_failure_notification(
            account_name="a", task_name="t", message="boom"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_missing_token_skips(self, notify_env):
        notify_env.settings["telegram_bot_token"] = "  "
        await sign_task_notify.send_failure_notification(
            account_name="a", task_name="t", message="boom"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_happy_path_builds_text_and_thread(self, notify_env):
        await sign_task_notify.send_failure_notification(
            account_name="acc1",
            task_name="daily",
            message="网络超时",
            last_target_message="bot 回复内容",
            flow_logs=[f"log-{i}" for i in range(25)],
        )
        assert len(notify_env.sent) == 1
        msg = notify_env.sent[0]
        assert msg["bot_token"] == "tok"
        assert msg["chat_id"] == "chat"
        assert msg["message_thread_id"] == 42
        text = msg["text"]
        assert "acc1" in text and "daily" in text and "网络超时" in text
        assert "bot 回复内容" in text
        # 日志只保留最后 20 行
        assert "log-24" in text and "log-5" in text and "log-4" not in text

    @pytest.mark.asyncio()
    async def test_failure_category_label_included(self, notify_env):
        """失败分类以可读中文标签进入通知，时间标注 UTC。"""
        await sign_task_notify.send_failure_notification(
            account_name="acc1",
            task_name="daily",
            message="flood wait 60s",
            failure_category="flood_wait",
        )
        assert len(notify_env.sent) == 1
        text = notify_env.sent[0]["text"]
        assert "失败分类" in text
        assert "频率限制" in text
        assert "时间 (UTC)" in text

    @pytest.mark.asyncio()
    async def test_unknown_category_passthrough(self, notify_env):
        """未知分类原样透传，不崩溃。"""
        await sign_task_notify.send_failure_notification(
            account_name="a",
            task_name="t",
            message="x",
            failure_category="some_custom_cat",
        )
        text = notify_env.sent[0]["text"]
        assert "some_custom_cat" in text

    @pytest.mark.asyncio()
    async def test_send_error_is_swallowed_with_warning(
        self, notify_env, monkeypatch, caplog
    ):
        async def _boom(**kwargs):
            raise RuntimeError("telegram api down")

        monkeypatch.setattr(push_mod, "send_telegram_bot_message", _boom)
        with caplog.at_level(logging.WARNING, logger="backend.sign_task_notify"):
            await sign_task_notify.send_failure_notification(
                account_name="a", task_name="t", message="boom"
            )
        assert "Telegram 失败通知发送失败" in caplog.text


class TestSendSuccessNotification:
    @pytest.mark.asyncio()
    async def test_delegates_with_settings(self, notify_env):
        await sign_task_notify.send_success_notification(
            account_name="acc1", task_name="daily", message="签到 +5"
        )
        assert notify_env.successes == [
            {
                "cfg": notify_env.settings,
                "account_name": "acc1",
                "task_name": "daily",
                "message": "签到 +5",
            }
        ]

    @pytest.mark.asyncio()
    async def test_error_is_swallowed_with_warning(
        self, notify_env, monkeypatch, caplog
    ):
        async def _boom(cfg, *, account_name, task_name, message=""):
            raise RuntimeError("send failed")

        monkeypatch.setattr(push_mod, "send_task_success_notification", _boom)
        with caplog.at_level(logging.WARNING, logger="backend.sign_task_notify"):
            await sign_task_notify.send_success_notification(
                account_name="a", task_name="t"
            )
        assert "Telegram 成功通知发送失败" in caplog.text


class TestSendAccountInvalidNotification:
    @pytest.mark.asyncio()
    async def test_notify_disabled_skips(self, notify_env):
        notify_env.settings["telegram_bot_notify_enabled"] = False
        await sign_task_notify.send_account_invalid_notification(
            account_name="a", task_name="t", message="失效"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_missing_chat_id_skips(self, notify_env):
        notify_env.settings["telegram_bot_chat_id"] = ""
        await sign_task_notify.send_account_invalid_notification(
            account_name="a", task_name="t", message="失效"
        )
        assert notify_env.sent == []

    @pytest.mark.asyncio()
    async def test_happy_path_text(self, notify_env):
        del notify_env.settings["telegram_bot_message_thread_id"]
        await sign_task_notify.send_account_invalid_notification(
            account_name="acc1", task_name="daily", message="session 失效"
        )
        assert len(notify_env.sent) == 1
        msg = notify_env.sent[0]
        assert msg["message_thread_id"] is None
        text = msg["text"]
        assert "账号登录失效" in text
        assert "acc1" in text and "daily" in text and "session 失效" in text
        assert "时间 (UTC)" in text

    @pytest.mark.asyncio()
    async def test_send_error_is_swallowed_with_warning(
        self, notify_env, monkeypatch, caplog
    ):
        async def _boom(**kwargs):
            raise RuntimeError("telegram api down")

        monkeypatch.setattr(push_mod, "send_telegram_bot_message", _boom)
        with caplog.at_level(logging.WARNING, logger="backend.sign_task_notify"):
            await sign_task_notify.send_account_invalid_notification(
                account_name="a", task_name="t", message="失效"
            )
        assert (
            "Telegram 账号失效通知发送失败" in caplog.text
        )


@pytest.fixture()
def mark_env(monkeypatch):
    """替换账号状态存取与失效推送为替身，供 mark/check 行为断言。"""

    state = {"stored": {}}
    set_calls: list[dict] = []
    notified: list[dict] = []

    monkeypatch.setattr(
        sign_task_notify, "get_account_status", lambda name: dict(state["stored"])
    )
    monkeypatch.setattr(
        sign_task_notify,
        "set_account_status",
        lambda name, **kwargs: set_calls.append({"name": name, **kwargs}),
    )

    async def _fake_notify(**kwargs):
        notified.append(kwargs)

    monkeypatch.setattr(
        sign_task_notify, "send_account_invalid_notification", _fake_notify
    )
    monkeypatch.setattr(
        sign_task_notify, "utc_now_iso", lambda: "2026-07-31T00:00:00Z"
    )
    return SimpleNamespace(state=state, set_calls=set_calls, notified=notified)


class TestMarkAccountInvalid:
    @pytest.mark.asyncio()
    async def test_first_invalid_marks_and_notifies(self, mark_env):
        result = await sign_task_notify.mark_account_invalid(
            account_name="acc1", task_name="daily", message="session 失效"
        )
        assert result is True
        assert len(mark_env.set_calls) == 1
        call = mark_env.set_calls[0]
        assert call["status"] == "invalid"
        assert call["code"] == "ACCOUNT_SESSION_INVALID"
        assert call["needs_relogin"] is True
        assert call["invalid_notified_at"] == "2026-07-31T00:00:00Z"
        assert len(mark_env.notified) == 1

    @pytest.mark.asyncio()
    async def test_already_notified_keeps_timestamp_and_silences(self, mark_env):
        mark_env.state["stored"] = {"invalid_notified_at": "2026-01-01T00:00:00Z"}
        result = await sign_task_notify.mark_account_invalid(
            account_name="acc1", task_name="daily", message="session 失效"
        )
        assert result is False
        assert mark_env.set_calls[0]["invalid_notified_at"] == "2026-01-01T00:00:00Z"
        assert mark_env.notified == []

    @pytest.mark.asyncio()
    async def test_notify_disabled_still_returns_first_flag(self, mark_env):
        result = await sign_task_notify.mark_account_invalid(
            account_name="acc1",
            task_name="daily",
            message="session 失效",
            notify_on_failure=False,
        )
        assert result is True
        assert len(mark_env.set_calls) == 1
        assert mark_env.notified == []


class _FakeTelegramService:
    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self.result = result or {"ok": True}
        self.error = error
        self.calls: list[tuple] = []

    async def check_account_status(self, account, timeout_seconds, no_updates):
        self.calls.append((account, timeout_seconds, no_updates))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture()
def check_env(mark_env, monkeypatch):
    """在 mark_env 基础上接管 mark_account_invalid，并注入 telegram 服务替身。"""

    marked: list[dict] = []

    async def _fake_mark(**kwargs):
        marked.append(kwargs)
        return True

    monkeypatch.setattr(sign_task_notify, "mark_account_invalid", _fake_mark)

    env = SimpleNamespace(**vars(mark_env), marked=marked, service=None)

    def _set_service(svc):
        # 同步更新 env.service，保证测试断言的总是当前注入的实例
        monkeypatch.setattr(telegram_mod, "get_telegram_service", lambda: svc)
        env.service = svc

    env.set_service = _set_service
    _set_service(_FakeTelegramService())
    return env


class TestCheckAccountBeforeTask:
    @pytest.mark.asyncio()
    async def test_stored_invalid_short_circuits(self, check_env):
        check_env.state["stored"] = {
            "status": "invalid",
            "needs_relogin": True,
            "message": "session 过期",
        }
        result = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=True
        )
        assert result == "session 过期"
        assert len(check_env.marked) == 1

    @pytest.mark.asyncio()
    async def test_stored_invalid_uses_fallback_message(self, check_env):
        check_env.state["stored"] = {"status": "invalid", "needs_relogin": True}
        result = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=False
        )
        assert "acc1" in result and "重新登录" in result

    @pytest.mark.asyncio()
    async def test_service_error_fails_open(self, check_env, caplog):
        check_env.set_service(_FakeTelegramService(error=RuntimeError("network")))
        with caplog.at_level(logging.WARNING, logger="backend.sign_task_notify"):
            result = await sign_task_notify.check_account_before_task(
                account_name="acc1", task_name="daily", no_updates=True
            )
        assert result is None
        # 前置账号状态检查失败应记录中文诊断日志
        assert "前置账号状态检查失败" in caplog.text

    @pytest.mark.asyncio()
    async def test_ok_result_passes_and_params_forwarded(self, check_env):
        check_env.set_service(_FakeTelegramService({"ok": True}))
        result = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=True
        )
        assert result is None
        assert check_env.service.calls == [("acc1", 10.0, True)]

    @pytest.mark.asyncio()
    @pytest.mark.parametrize(
        "result",
        [
            {"ok": False, "needs_relogin": True, "message": "需重新登录"},
            {"ok": False, "status": "invalid", "message": "失效"},
            {"ok": False, "status": "not_found", "message": "不存在"},
            {"ok": False, "code": "ACCOUNT_SESSION_INVALID", "message": "失效"},
        ],
    )
    async def test_fatal_results_mark_invalid(self, check_env, result):
        check_env.set_service(_FakeTelegramService(result))
        message = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=False
        )
        assert message == result["message"]
        assert len(check_env.marked) == 1

    @pytest.mark.asyncio()
    async def test_fatal_empty_message_falls_back(self, check_env):
        check_env.set_service(
            _FakeTelegramService({"ok": False, "needs_relogin": True})
        )
        message = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=False
        )
        assert "acc1" in message and "重新登录" in message

    @pytest.mark.asyncio()
    async def test_benign_failure_passes(self, check_env):
        check_env.set_service(
            _FakeTelegramService({"ok": False, "status": "busy", "code": "RATE"})
        )
        result = await sign_task_notify.check_account_before_task(
            account_name="acc1", task_name="daily", no_updates=False
        )
        assert result is None
        assert check_env.marked == []
