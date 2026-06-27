"""
关键词监听 Bot 命令触发测试

测试从 action 配置读取 bot_username，使用关键词捕获值作为命令参数。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.keyword_monitor import KeywordMonitorService


class TestBotLinkAction:
    """测试 action_id=9（触发 Bot 命令）的执行逻辑"""

    @pytest.fixture
    def service(self):
        return KeywordMonitorService()

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_bot_link_sends_start_with_keyword(self, service, mock_client):
        """action_id=9 应向配置的 bot 发送 /start {keyword}"""
        source_msg = MagicMock()
        source_msg.text = "MSKY-30-Register_KsdaqumLAS"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "GYFMsky_bot"}
        variables = {"keyword": "KsdaqumLAS", "message": source_msg.text}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with(
            "GYFMsky_bot", "/start KsdaqumLAS"
        )

    @pytest.mark.asyncio
    async def test_bot_link_no_bot_username(self, service, mock_client):
        """未配置 bot_username 时返回 False"""
        source_msg = MagicMock()
        source_msg.text = "some text"
        source_msg.caption = None

        action = {"action": 9}
        variables = {"keyword": "test"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is False
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_link_no_source_message(self, service, mock_client):
        """无源消息时返回 False"""
        action = {"action": 9, "bot_username": "GYFMsky_bot"}
        variables = {"keyword": "test"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=None, variables=variables,
        )
        assert result is False
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_link_empty_keyword(self, service, mock_client):
        """关键词捕获值为空时返回 False"""
        source_msg = MagicMock()
        source_msg.text = "some text"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "GYFMsky_bot"}
        variables = {"keyword": ""}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is False
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_link_rate_limit(self, service, mock_client):
        """同一 bot 30 秒内不重复触发"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "rate_bot"}
        variables = {"keyword": "code1"}

        # 第一次成功
        result1 = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result1 is True

        # 第二次被速率限制
        variables["keyword"] = "code2"
        result2 = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result2 is False
        assert mock_client.send_message.call_count == 1

    @pytest.mark.asyncio
    async def test_bot_link_send_failure(self, service, mock_client):
        """发送失败时返回 False"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        mock_client.send_message = AsyncMock(side_effect=ConnectionError("网络错误"))
        action = {"action": 9, "bot_username": "fail_bot"}
        variables = {"keyword": "test"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is False

    def test_continue_actions_includes_action_9(self, service):
        """_continue_actions 应接受 action_id=9"""
        action = {"continue_actions": [{"action": 9, "bot_username": "test"}]}
        result = service._continue_actions(action)
        assert len(result) == 1
        assert result[0]["action"] == 9

    def test_describe_continue_action_bot_link(self, service):
        """_describe_continue_action 应正确描述 action_id=9"""
        action = {"action": 9, "bot_username": "GYFMsky_bot"}
        desc = service._describe_continue_action(action)
        assert desc == "触发 Bot 命令: @GYFMsky_bot /start"

    def test_message_supports_action_9(self, service):
        """有 text 或 caption 的消息应支持 action_id=9"""
        msg = MagicMock()
        msg.text = "some text"
        msg.caption = None
        assert service._message_supports_action(msg, 9) is True

    def test_message_supports_action_9_empty(self, service):
        """无 text 无 caption 的消息不应支持 action_id=9"""
        msg = MagicMock()
        msg.text = None
        msg.caption = None
        assert service._message_supports_action(msg, 9) is False

    @pytest.mark.asyncio
    async def test_bot_link_caption_fallback(self, service, mock_client):
        """消息无 text 但有 caption 时应正常触发"""
        source_msg = MagicMock()
        source_msg.text = None
        source_msg.caption = "Register_ABC123"

        action = {"action": 9, "bot_username": "caption_bot"}
        variables = {"keyword": "ABC123"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with(
            "caption_bot", "/start ABC123"
        )

    @pytest.mark.asyncio
    async def test_bot_link_logs_account_and_task(self, service, mock_client):
        """成功时 account_name 和 task_name 应写入日志"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "log_bot"}
        variables = {"keyword": "code1"}

        await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
            account_name="my_account", task_name="my_task",
        )
        logs = service.get_task_logs("my_task", "my_account")
        assert any("Bot 命令触发成功" in line for line in logs)

    @pytest.mark.asyncio
    async def test_bot_link_no_variables_uses_default_template(self, service, mock_client):
        """variables=None 时默认 {keyword} 模板应渲染为空，返回 False"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "no_var_bot"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=None,
        )
        assert result is False
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_link_whitespace_bot_username(self, service, mock_client):
        """bot_username 为纯空格时应返回 False"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "   "}
        variables = {"keyword": "test"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is False
        mock_client.send_message.assert_not_called()

    def test_describe_bot_link_no_username(self, service):
        """无 bot_username 时描述应不含 @"""
        action = {"action": 9}
        desc = service._describe_continue_action(action)
        assert desc == "触发 Bot 命令 /start"

    @pytest.mark.asyncio
    async def test_bot_link_custom_start_param(self, service, mock_client):
        """自定义 start_param 模板应正确替换"""
        source_msg = MagicMock()
        source_msg.text = "验证码: 123456"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "custom_bot", "start_param": "{message}"}
        variables = {"keyword": "123456", "message": "验证码: 123456"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with(
            "custom_bot", "/start 验证码: 123456"
        )

    @pytest.mark.asyncio
    async def test_bot_link_custom_command_prefix(self, service, mock_client):
        """自定义命令前缀"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "test_bot", "command_prefix": "/get"}
        variables = {"keyword": "abc"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with("test_bot", "/get abc")

    @pytest.mark.asyncio
    async def test_bot_link_default_command_prefix(self, service, mock_client):
        """默认命令前缀为 /start"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "test_bot"}
        variables = {"keyword": "abc"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with("test_bot", "/start abc")

    def test_describe_bot_command_with_prefix(self, service):
        """describe 输出包含命令前缀"""
        action = {"action": 9, "bot_username": "GYFMsky_bot", "command_prefix": "/verify"}
        desc = service._describe_continue_action(action)
        assert desc == "触发 Bot 命令: @GYFMsky_bot /verify"

    @pytest.mark.asyncio
    async def test_command_prefix_auto_slash(self, service, mock_client):
        """command_prefix 不带 / 时自动补全"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "test_bot", "command_prefix": "get"}
        variables = {"keyword": "abc"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with("test_bot", "/get abc")

    @pytest.mark.asyncio
    async def test_command_prefix_empty_string_defaults(self, service, mock_client):
        """command_prefix 为空字符串时回退默认 /start"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "test_bot", "command_prefix": ""}
        variables = {"keyword": "abc"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with("test_bot", "/start abc")

    @pytest.mark.asyncio
    async def test_command_prefix_whitespace_defaults(self, service, mock_client):
        """command_prefix 为纯空格时回退默认 /start"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "test_bot", "command_prefix": "   "}
        variables = {"keyword": "abc"}

        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with("test_bot", "/start abc")

    @pytest.mark.asyncio
    async def test_rate_limit_per_account(self, service, mock_client):
        """不同账号同一 Bot 的速率限制应独立"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "shared_bot"}
        variables = {"keyword": "code1"}

        # 账号 A 触发
        result1 = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
            account_name="account_A",
        )
        assert result1 is True

        # 账号 B 同一 Bot 应独立触发（不被阻塞）
        variables["keyword"] = "code2"
        result2 = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables=variables,
            account_name="account_B",
        )
        assert result2 is True
        assert mock_client.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_exception_log_includes_cmd(self, service, mock_client):
        """异常日志应包含 command_prefix 字段"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        mock_client.send_message = AsyncMock(side_effect=ConnectionError("网络错误"))
        action = {"action": 9, "bot_username": "fail_bot", "command_prefix": "/get"}
        variables = {"keyword": "test"}

        with patch.object(service, '_append_rule_log'):
            result = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables=variables,
            )
        assert result is False

    def test_describe_command_prefix_empty_defaults(self, service):
        """describe 中空 command_prefix 应回退默认 /start"""
        action = {"action": 9, "bot_username": "test_bot", "command_prefix": ""}
        desc = service._describe_continue_action(action)
        assert "/start" in desc
