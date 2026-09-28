from unittest.mock import AsyncMock, patch

import pytest

from backend.services.chatops_bot import TelegramChatOpsWorker


async def _noop_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_chatops_help_command():
    worker = TelegramChatOpsWorker()
    with patch("backend.services.chatops_bot.send_telegram_bot_message", new_callable=AsyncMock) as mock_send:
        await worker.handle_command("dummy_token", "12345", "/help", {})
        mock_send.assert_called_once()
        text = mock_send.call_args[1]["text"]
        assert "/status" in text
        assert "/run" in text


@pytest.mark.asyncio
async def test_chatops_status_command():
    worker = TelegramChatOpsWorker()
    with patch("backend.services.chatops_bot.send_telegram_bot_message", new_callable=AsyncMock) as mock_send, \
         patch("backend.services.sign_tasks.get_sign_task_service") as mock_svc, \
         patch("backend.services.telegram.get_telegram_service") as mock_acc_svc:

        mock_svc.return_value.list_tasks.return_value = [{"name": "task1"}]
        mock_svc.return_value.list_active_runs.return_value = []
        mock_acc_svc.return_value.list_accounts.return_value = ["acc1"]

        await worker.handle_command("dummy_token", "12345", "/status", {})
        mock_send.assert_called_once()
        text = mock_send.call_args[1]["text"]
        assert "系统运行状态" in text
        assert "总账号数" in text


@pytest.mark.asyncio
async def test_chatops_run_command():
    worker = TelegramChatOpsWorker()
    with patch("backend.services.chatops_bot.send_telegram_bot_message", new_callable=AsyncMock) as mock_send, \
         patch("backend.services.sign_tasks.get_sign_task_service") as mock_svc:

        mock_svc.return_value.list_tasks.return_value = [{"name": "my_sign", "account_name": "acc1"}]
        mock_svc.return_value.run_task_with_logs = AsyncMock()

        # 无参数提示
        await worker.handle_command("dummy_token", "12345", "/run", {})
        assert "请指定任务名称" in mock_send.call_args[1]["text"]

        # 正常触发
        await worker.handle_command("dummy_token", "12345", "/run my_sign", {})
        assert "已触发任务执行" in mock_send.call_args[1]["text"]


class TestChatOpsSenderBinding:
    """_poll_loop 鉴权：chat_id 与发送者 user_id 必须同时满足才放行。"""

    @staticmethod
    def _update(chat_id, text, from_id=None):
        msg = {"chat": {"id": chat_id}, "text": text}
        if from_id is not None:
            msg["from"] = {"id": from_id}
        return {"update_id": 1, "message": msg}

    @staticmethod
    def _settings(**overrides):
        base = {
            "telegram_bot_token": "tok",
            "telegram_bot_chat_id": "555",
            "telegram_bot_chatops_enabled": True,
            "telegram_bot_admin_user_ids": "111, 222",
        }
        base.update(overrides)
        return base

    def _run_one_poll(self, updates, settings, monkeypatch):
        """跑一轮轮询：第一次 getUpdates 后即把 _running 置 False 结束循环。"""
        import asyncio

        worker = TelegramChatOpsWorker()
        handled = []

        async def _fake_handle(*args, **kwargs):
            handled.append(args)

        worker.handle_command = _fake_handle

        class _Resp:
            status_code = 200

            def json(self):
                return {"result": updates}

        class _Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return None

            async def aclose(self):
                return None

            async def get(self, url, params=None):
                # 成功路径没有 sleep，只能在这里作为迭代边界收敛循环
                worker._running = False
                return _Resp()

        monkeypatch.setattr(
            "backend.services.chatops_bot.httpx.AsyncClient", _Client, raising=False
        )

        # 轮询成功路径没有 sleep，失败/禁用路径才有；两侧都要能收敛循环，
        # 否则 _running 永为 True 会无限空转
        async def _bounded_sleep(_seconds):
            worker._running = False

        monkeypatch.setattr(
            "backend.services.chatops_bot.asyncio.sleep",
            _bounded_sleep,
            raising=False,
        )

        class _Cfg:
            def get_global_settings(self):
                return settings

            def get_global_proxy(self):
                return None

        monkeypatch.setattr(
            "backend.services.config.get_config_service",
            lambda: _Cfg(),
            raising=False,
        )

        original = worker._running
        worker._running = True
        try:
            asyncio.get_event_loop().run_until_complete(worker._poll_loop())
        finally:
            worker._running = original
        return handled

    def test_whitelisted_sender_is_accepted(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/status", from_id=222)], self._settings(), monkeypatch
        )
        assert len(handled) == 1

    def test_non_whitelisted_sender_is_dropped(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/run my_sign", from_id=999)],
            self._settings(),
            monkeypatch,
        )
        assert handled == []

    def test_missing_sender_id_is_dropped(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/status")], self._settings(), monkeypatch
        )
        assert handled == []

    def test_mismatched_chat_id_is_still_dropped(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("777", "/status", from_id=222)],
            self._settings(),
            monkeypatch,
        )
        assert handled == []

    def test_disabled_chatops_drops_everything(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/status", from_id=111)],
            self._settings(telegram_bot_chatops_enabled=False),
            monkeypatch,
        )
        assert handled == []

    def test_empty_admin_whitelist_drops_everything(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/status", from_id=111)],
            self._settings(telegram_bot_admin_user_ids=""),
            monkeypatch,
        )
        assert handled == []

    def test_whitelist_accepts_semicolon_and_whitespace_separators(self, monkeypatch):
        handled = self._run_one_poll(
            [self._update("555", "/status", from_id=333)],
            self._settings(telegram_bot_admin_user_ids="111; 333\t444"),
            monkeypatch,
        )
        assert len(handled) == 1


class TestChatOpsHtmlEscaping:
    @pytest.mark.asyncio
    async def test_run_unknown_task_escapes_markup(self):
        from unittest.mock import AsyncMock, patch

        worker = TelegramChatOpsWorker()
        with patch(
            "backend.services.chatops_bot.send_telegram_bot_message",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "backend.services.sign_tasks.get_sign_task_service"
        ) as mock_svc:
            mock_svc.return_value.list_tasks.return_value = []
            await worker.handle_command(
                "tok", "555", "/run <b>pwned</b>", {}
            )
            text = mock_send.call_args[1]["text"]
            assert "&lt;b&gt;pwned&lt;/b&gt;" in text
            assert "<b>pwned</b>" not in text
