"""
关键词监听 Bot 命令触发测试

测试从 action 配置读取 bot_username，使用关键词捕获值作为命令参数。
覆盖：深链批量解析、正则多匹配、间隔等待发送。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from backend.services.keyword_monitor import (
    KeywordMonitorService,
    _extract_tg_start_links,
    _match_all_keyword_values,
)


class TestBotLinkHelpers:
    """纯函数：深链解析与多匹配"""

    def test_extract_multiple_start_links(self):
        text = (
            "已为您生成了30天注册码3个\n"
            "t.me/shrekpublicbot?start=SAKURA-30-Register_Ywyx26Doxi\n"
            "https://t.me/shrekpublicbot?start=SAKURA-30-Register_QjElUtgTgs\n"
            "t.me/shrekpublicbot?start=SAKURA-30-Register_Q2NK4Yw68E"
        )
        links = _extract_tg_start_links(text)
        assert links == [
            ("shrekpublicbot", "SAKURA-30-Register_Ywyx26Doxi"),
            ("shrekpublicbot", "SAKURA-30-Register_QjElUtgTgs"),
            ("shrekpublicbot", "SAKURA-30-Register_Q2NK4Yw68E"),
        ]

    def test_extract_start_links_dedupe(self):
        text = (
            "t.me/bot_a?start=CODE1\n"
            "t.me/bot_a?start=CODE1\n"
            "t.me/bot_b?start=CODE1"
        )
        links = _extract_tg_start_links(text)
        assert links == [("bot_a", "CODE1"), ("bot_b", "CODE1")]

    def test_match_all_regex_captures(self):
        action = {
            "keywords": [r"Register_(\w+)"],
            "match_mode": "regex",
        }
        text = "A-Register_aaa B-Register_bbb C-Register_ccc"
        assert _match_all_keyword_values(action, text) == ["aaa", "bbb", "ccc"]


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
        """未配置 bot_username 且无可解析深链时返回 False"""
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
    async def test_bot_link_rate_limit_waits_instead_of_skip(
        self, service, mock_client
    ):
        """同一 bot 连续触发应等待间隔后发送，而不是直接跳过"""
        source_msg = MagicMock()
        source_msg.text = "test"
        source_msg.caption = None

        action = {
            "action": 9,
            "bot_username": "rate_bot",
            "send_interval": 2.0,
        }
        variables = {"keyword": "code1"}

        with patch(
            "backend.services.keyword_monitor.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result1 = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables=variables,
            )
            assert result1 is True

            variables["keyword"] = "code2"
            result2 = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables=variables,
            )
            assert result2 is True
            assert mock_client.send_message.call_count == 2
            mock_sleep.assert_called()
            assert mock_sleep.call_args[0][0] == pytest.approx(2.0, abs=0.05)

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
        """无 bot_username 时描述提示可从深链解析"""
        action = {"action": 9}
        desc = service._describe_continue_action(action)
        assert "触发 Bot 命令 /start" in desc
        assert "深链" in desc

    @pytest.mark.asyncio
    async def test_bot_link_parses_multiple_deep_links(self, service, mock_client):
        """一条消息内多个 t.me/?start= 应全部触发"""
        source_msg = MagicMock()
        source_msg.text = (
            "已为您生成了30天注册码3个\n"
            "t.me/shrekpublicbot?start=SAKURA-30-Register_Ywyx26Doxi\n"
            "t.me/shrekpublicbot?start=SAKURA-30-Register_QjElUtgTgs\n"
            "t.me/shrekpublicbot?start=SAKURA-30-Register_Q2NK4Yw68E"
        )
        source_msg.caption = None

        action = {"action": 9, "send_interval": 0}
        with patch(
            "backend.services.keyword_monitor.asyncio.sleep", new_callable=AsyncMock
        ):
            result = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables={},
            )
        assert result is True
        assert mock_client.send_message.call_count == 3
        assert [c.args for c in mock_client.send_message.call_args_list] == [
            ("shrekpublicbot", "/start SAKURA-30-Register_Ywyx26Doxi"),
            ("shrekpublicbot", "/start SAKURA-30-Register_QjElUtgTgs"),
            ("shrekpublicbot", "/start SAKURA-30-Register_Q2NK4Yw68E"),
        ]

    @pytest.mark.asyncio
    async def test_bot_link_configured_bot_overrides_link_bot(
        self, service, mock_client
    ):
        """配置了 bot_username 时，优先使用配置的 Bot，参数仍取自深链"""
        source_msg = MagicMock()
        source_msg.text = "t.me/other_bot?start=CODE_ABC"
        source_msg.caption = None

        action = {
            "action": 9,
            "bot_username": "@PreferBot",
            "send_interval": 0,
        }
        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables={},
        )
        assert result is True
        mock_client.send_message.assert_called_once_with(
            "PreferBot", "/start CODE_ABC"
        )

    @pytest.mark.asyncio
    async def test_bot_link_multi_regex_match_action(self, service, mock_client):
        """父规则正则多捕获时应批量 /start"""
        source_msg = MagicMock()
        source_msg.text = "Register_aaa and Register_bbb and Register_ccc"
        source_msg.caption = None

        action = {"action": 9, "bot_username": "reg_bot", "send_interval": 0}
        match_action = {
            "keywords": [r"Register_(\w+)"],
            "match_mode": "regex",
        }
        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg,
            variables={"keyword": "aaa"},
            match_action=match_action,
        )
        assert result is True
        assert mock_client.send_message.call_count == 3
        assert [c.args for c in mock_client.send_message.call_args_list] == [
            ("reg_bot", "/start aaa"),
            ("reg_bot", "/start bbb"),
            ("reg_bot", "/start ccc"),
        ]

    @pytest.mark.asyncio
    async def test_bot_link_deep_links_take_priority_over_keyword(
        self, service, mock_client
    ):
        """存在深链时优先走深链完整 payload，而不是仅正则捕获后缀"""
        source_msg = MagicMock()
        source_msg.text = (
            "t.me/shrekpublicbot?start=SAKURA-30-Register_FullCode1\n"
            "Register_ignored"
        )
        source_msg.caption = None

        action = {"action": 9, "bot_username": "shrekpublicbot", "send_interval": 0}
        match_action = {
            "keywords": [r"Register_(\w+)"],
            "match_mode": "regex",
        }
        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg,
            variables={"keyword": "FullCode1"},
            match_action=match_action,
        )
        assert result is True
        mock_client.send_message.assert_called_once_with(
            "shrekpublicbot", "/start SAKURA-30-Register_FullCode1"
        )

    @pytest.mark.asyncio
    async def test_bot_link_max_batch_cap(self, service, mock_client):
        """max_batch 限制单次最多发送条数"""
        source_msg = MagicMock()
        source_msg.text = "\n".join(
            f"t.me/cap_bot?start=CODE{i}" for i in range(5)
        )
        source_msg.caption = None

        action = {
            "action": 9,
            "send_interval": 0,
            "max_batch": 2,
        }
        result = await service._execute_bot_link_action(
            mock_client, -1001234567890, None, action,
            source_message=source_msg, variables={},
        )
        assert result is True
        assert mock_client.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_bot_link_default_max_batch_is_five(self, service, mock_client):
        """默认最多发送 5 条，超出部分截断"""
        source_msg = MagicMock()
        source_msg.text = "\n".join(
            f"t.me/cap_bot?start=CODE{i}" for i in range(8)
        )
        source_msg.caption = None

        action = {"action": 9, "send_interval": 0}
        with patch(
            "backend.services.keyword_monitor.logger.warning"
        ) as mock_warn:
            result = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables={},
            )
        assert result is True
        assert mock_client.send_message.call_count == 5
        # 截断与风控提示应出现在 warning 日志中
        warn_text = " ".join(
            str(call_args) for call_args in mock_warn.call_args_list
        )
        assert "批量截断" in warn_text
        assert "风控" in warn_text or "封禁" in warn_text

    @pytest.mark.asyncio
    async def test_bot_link_high_max_batch_logs_risk_warning(
        self, service, mock_client
    ):
        """显式调高 max_batch 时应写入风控警告日志"""
        source_msg = MagicMock()
        source_msg.text = "t.me/risk_bot?start=ONLYONE"
        source_msg.caption = None

        action = {
            "action": 9,
            "send_interval": 0,
            "max_batch": 10,
        }
        with patch(
            "backend.services.keyword_monitor.logger.warning"
        ) as mock_warn:
            result = await service._execute_bot_link_action(
                mock_client, -1001234567890, None, action,
                source_message=source_msg, variables={},
            )
        assert result is True
        high_batch_calls = [
            c for c in mock_warn.call_args_list
            if c.args and "高于默认值" in str(c.args[0])
        ]
        assert high_batch_calls, "应记录 max_batch 高于默认的警告"
        assert high_batch_calls[0].args[1:] == (
            10,
            5,
            "调高 max_batch 可能导致 Telegram 风控、限流甚至账号封禁，请谨慎设置",
        )

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
