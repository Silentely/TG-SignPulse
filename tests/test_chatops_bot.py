import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.services.chatops_bot import TelegramChatOpsWorker


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
