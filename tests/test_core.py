"""
tg_signer/core.py 单元测试

覆盖范围：
- Client 类：初始化、session_string 管理、上下文管理器协议
- UserSigner._resolve_action_delay：固定值、范围解析、无效输入回退
- 辅助函数：get_now、make_dirs、readable_chat
- 辅助函数：get_api_config、get_proxy、_read_positive_float_env、_read_positive_int_env
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tg_signer.compat import ChatType
from tg_signer.core import (
    Client,
    Waiter,
    UserSigner,
    get_now,
    get_api_config,
    get_client,
    get_proxy,
    make_dirs,
    readable_chat,
    _read_positive_float_env,
    _read_positive_int_env,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    _CLIENT_ASYNC_LOCKS,
)
from tg_signer.config import SendTextAction, SendDiceAction


# ============================================================================
# 辅助函数测试
# ============================================================================


class TestGetNow:
    """get_now 返回 UTC+8 时区的当前时间"""

    def test_returns_timezone_aware_datetime(self):
        result = get_now()
        assert result.tzinfo is not None

    def test_timezone_offset_is_utc_plus_8(self):
        result = get_now()
        expected_offset = timedelta(hours=8)
        assert result.utcoffset() == expected_offset

    def test_returns_current_time_within_tolerance(self):
        """返回时间与实际时间相差不超过 2 秒"""
        before = datetime.now(tz=timezone(timedelta(hours=8)))
        result = get_now()
        after = datetime.now(tz=timezone(timedelta(hours=8)))
        assert before <= result <= after + timedelta(seconds=2)


class TestMakeDirs:
    """make_dirs 创建目录并返回 Path 对象"""

    def test_creates_directory(self, tmp_path):
        target = tmp_path / "new_dir"
        assert not target.exists()
        result = make_dirs(target)
        assert target.is_dir()
        assert result == target

    def test_returns_path_object(self, tmp_path):
        target = tmp_path / "some_dir"
        result = make_dirs(target)
        assert isinstance(result, pathlib.Path)

    def test_exist_ok_true_by_default(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()
        # 不应抛出异常
        result = make_dirs(target)
        assert result.is_dir()

    def test_accepts_string_path(self, tmp_path):
        target_str = str(tmp_path / "string_dir")
        result = make_dirs(target_str)
        assert isinstance(result, pathlib.Path)
        assert result.is_dir()

    def test_nested_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        result = make_dirs(target)
        assert target.is_dir()


class TestReadableChat:
    """readable_chat 将 Chat 对象格式化为可读字符串"""

    @staticmethod
    def _make_chat(chat_type: str, chat_id: int = -100123, username: str = "testchat",
                   title: str = "Test Chat", first_name: str = None):
        return SimpleNamespace(
            id=chat_id,
            type=chat_type,
            username=username,
            title=title,
            first_name=first_name,
        )

    def test_bot_type(self):
        chat = self._make_chat(ChatType.BOT)
        result = readable_chat(chat)
        assert "BOT" in result
        assert "id: -100123" in result

    def test_group_type(self):
        chat = self._make_chat(ChatType.GROUP)
        result = readable_chat(chat)
        assert "群组" in result

    def test_supergroup_type(self):
        chat = self._make_chat(ChatType.SUPERGROUP)
        result = readable_chat(chat)
        assert "超级群组" in result

    def test_channel_type(self):
        chat = self._make_chat(ChatType.CHANNEL)
        result = readable_chat(chat)
        assert "频道" in result

    def test_personal_type_fallback(self):
        """未知类型应归类为"个人" """
        chat = self._make_chat("private")
        result = readable_chat(chat)
        assert "个人" in result

    def test_none_fields_show_dash(self):
        """当 username/title/first_name 为 None 时应显示 '-' """
        chat = SimpleNamespace(
            id=111,
            type=ChatType.GROUP,
            username=None,
            title=None,
            first_name=None,
        )
        result = readable_chat(chat)
        assert "username: -" in result
        assert "title: -" in result
        assert "name: -" in result

    def test_includes_all_fields(self):
        chat = self._make_chat(
            ChatType.CHANNEL,
            chat_id=-100999,
            username="mychannel",
            title="My Channel",
            first_name="Bot",
        )
        result = readable_chat(chat)
        assert "id: -100999" in result
        assert "username: mychannel" in result
        assert "title: My Channel" in result
        assert "name: Bot" in result


# ============================================================================
# get_api_config 测试
# ============================================================================


class TestGetApiConfig:
    """get_api_config 从环境变量或默认值读取 API 配置"""

    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("TG_API_ID", raising=False)
        monkeypatch.delenv("TG_API_HASH", raising=False)
        api_id, api_hash = get_api_config()
        assert api_id == 611335
        assert api_hash == "d524b414d21f4d37f08684c1df41ac9c"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("TG_API_ID", "99999")
        monkeypatch.setenv("TG_API_HASH", "custom-hash")
        api_id, api_hash = get_api_config()
        assert api_id == 99999
        assert api_hash == "custom-hash"

    def test_invalid_api_id_falls_back(self, monkeypatch):
        monkeypatch.setenv("TG_API_ID", "not-a-number")
        api_id, _ = get_api_config()
        assert api_id == 611335

    def test_empty_api_hash_falls_back(self, monkeypatch):
        monkeypatch.setenv("TG_API_HASH", "   ")
        _, api_hash = get_api_config()
        assert api_hash == "d524b414d21f4d37f08684c1df41ac9c"


# ============================================================================
# get_proxy 测试
# ============================================================================


class TestGetProxy:
    """get_proxy 解析代理 URL"""

    def test_returns_none_when_no_proxy(self, monkeypatch):
        monkeypatch.delenv("TG_PROXY", raising=False)
        assert get_proxy() is None

    def test_parses_proxy_url(self, monkeypatch):
        monkeypatch.setenv("TG_PROXY", "socks5://user:pass@127.0.0.1:1080")
        result = get_proxy()
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "127.0.0.1"
        assert result["port"] == 1080
        assert result["username"] == "user"
        assert result["password"] == "pass"

    def test_explicit_proxy_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TG_PROXY", "http://env-proxy:8080")
        result = get_proxy("http://explicit:3128")
        assert result["hostname"] == "explicit"
        assert result["port"] == 3128

    def test_returns_none_for_empty_string(self):
        assert get_proxy("") is None


# ============================================================================
# _read_positive_float_env / _read_positive_int_env 测试
# ============================================================================


class TestReadPositiveEnv:
    """环境变量读取辅助函数"""

    def test_float_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_FLOAT_VAL", raising=False)
        assert _read_positive_float_env("TEST_FLOAT_VAL", 5.0) == 5.0

    def test_float_valid_value(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAL", "10.5")
        assert _read_positive_float_env("TEST_FLOAT_VAL", 5.0) == 10.5

    def test_float_clamps_to_minimum(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAL", "0.1")
        result = _read_positive_float_env("TEST_FLOAT_VAL", 5.0, minimum=1.0)
        assert result == 1.0

    def test_float_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_FLOAT_VAL", "abc")
        assert _read_positive_float_env("TEST_FLOAT_VAL", 5.0) == 5.0

    def test_int_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_INT_VAL", raising=False)
        assert _read_positive_int_env("TEST_INT_VAL", 3) == 3

    def test_int_valid_value(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAL", "7")
        assert _read_positive_int_env("TEST_INT_VAL", 3) == 7

    def test_int_clamps_to_minimum(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAL", "0")
        result = _read_positive_int_env("TEST_INT_VAL", 3, minimum=1)
        assert result == 1

    def test_int_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEST_INT_VAL", "xyz")
        assert _read_positive_int_env("TEST_INT_VAL", 3) == 3


# ============================================================================
# Client 类测试
# ============================================================================


class TestClientInitialization:
    """Client 初始化逻辑"""

    def test_init_sets_key_from_workdir_and_name(self):
        """默认 key 由 workdir/name 拼接"""
        keys_before = set(_CLIENT_INSTANCES.keys())
        try:
            client = get_client(
                name="test_init",
                workdir="/tmp/test_core",
                api_id=12345,
                api_hash="testhash",
            )
            expected_key = str(pathlib.Path("/tmp/test_core").joinpath("test_init").resolve())
            assert client.key == expected_key
        finally:
            for k in list(_CLIENT_INSTANCES.keys()):
                if k not in keys_before:
                    _CLIENT_INSTANCES.pop(k, None)


class TestClientSessionString:
    """Client session_string 文件读写"""

    def test_session_string_file_path(self, tmp_path):
        """session_string_file 属性返回正确的路径"""
        from tg_signer.core import get_client, _CLIENT_INSTANCES
        keys_before = set(_CLIENT_INSTANCES.keys())
        try:
            client = get_client(
                name="session_test",
                workdir=str(tmp_path),
                api_id=12345,
                api_hash="testhash",
            )
            expected = tmp_path / "session_test.session_string"
            assert client.session_string_file == expected
        finally:
            for k in list(_CLIENT_INSTANCES.keys()):
                if k not in keys_before:
                    _CLIENT_INSTANCES.pop(k, None)

    def test_load_session_string_from_file(self, tmp_path):
        """load_session_string 从文件读取 session 字符串"""
        from tg_signer.core import get_client, _CLIENT_INSTANCES
        keys_before = set(_CLIENT_INSTANCES.keys())
        try:
            client = get_client(
                name="load_test",
                workdir=str(tmp_path),
                api_id=12345,
                api_hash="testhash",
            )
            session_file = tmp_path / "load_test.session_string"
            session_file.write_text("test-session-data")
            result = client.load_session_string()
            assert result == "test-session-data"
            assert client.session_string == "test-session-data"
        finally:
            for k in list(_CLIENT_INSTANCES.keys()):
                if k not in keys_before:
                    _CLIENT_INSTANCES.pop(k, None)

    def test_load_session_string_missing_file(self, tmp_path):
        """文件不存在时返回 None（Pyrogram BaseClient 默认值）"""
        from tg_signer.core import get_client, _CLIENT_INSTANCES
        keys_before = set(_CLIENT_INSTANCES.keys())
        try:
            client = get_client(
                name="missing_test",
                workdir=str(tmp_path),
                api_id=12345,
                api_hash="testhash",
            )
            result = client.load_session_string()
            # Pyrogram BaseClient 的 session_string 默认为 None
            assert result is None
        finally:
            for k in list(_CLIENT_INSTANCES.keys()):
                if k not in keys_before:
                    _CLIENT_INSTANCES.pop(k, None)


class TestGetClientCaching:
    """get_client 实例缓存机制"""

    def setup_method(self):
        """清理全局缓存，防止测试间干扰"""
        self._keys_before = set(_CLIENT_INSTANCES.keys())

    def teardown_method(self):
        """清理测试中新增的缓存条目"""
        for k in list(_CLIENT_INSTANCES.keys()):
            if k not in self._keys_before:
                _CLIENT_INSTANCES.pop(k, None)

    def test_same_name_returns_same_instance(self):
        """相同 name+workdir 返回同一个 Client 实例"""
        c1 = get_client(name="cache_test", workdir="/tmp/cache_test", api_id=1, api_hash="h")
        c2 = get_client(name="cache_test", workdir="/tmp/cache_test", api_id=1, api_hash="h")
        assert c1 is c2

    def test_different_name_returns_different_instance(self):
        """不同 name 返回不同实例"""
        c1 = get_client(name="cache_a", workdir="/tmp/cache_diff", api_id=1, api_hash="h")
        c2 = get_client(name="cache_b", workdir="/tmp/cache_diff", api_id=1, api_hash="h")
        assert c1 is not c2

    def test_in_memory_gets_separate_cache_key(self):
        """in_memory=True 且有 session_string 时使用独立缓存键"""
        c1 = get_client(name="mem_test", workdir="/tmp/mem_test", api_id=1, api_hash="h")
        c2 = get_client(
            name="mem_test", workdir="/tmp/mem_test", api_id=1, api_hash="h",
            in_memory=True, session_string="some-session",
        )
        # 两者缓存键不同
        assert c1.key != c2.key


# ============================================================================
# Waiter 类测试
# ============================================================================


class TestWaiter:
    """Waiter 数据结构：引用计数式等待集合"""

    def test_add_and_bool(self):
        w = Waiter()
        assert not w
        w.add(100)
        assert w

    def test_discard(self):
        w = Waiter()
        w.add(100)
        w.discard(100)
        assert not w

    def test_sub_decrements(self):
        w = Waiter()
        w.add(100)
        w.add(100)  # count = 2
        w.sub(100)  # count = 1
        assert 100 in w.waiting_ids
        w.sub(100)  # count = 0, auto discard
        assert 100 not in w.waiting_ids

    def test_clear(self):
        w = Waiter()
        w.add(1)
        w.add(2)
        w.clear()
        assert not w
        assert len(w.waiting_ids) == 0

    def test_discard_nonexistent_is_safe(self):
        w = Waiter()
        w.discard(999)  # 不应抛出异常

    def test_repr(self):
        w = Waiter()
        w.add(42)
        r = repr(w)
        assert "Waiter" in r
        assert "42" in r


# ============================================================================
# UserSigner._resolve_action_delay 测试
# ============================================================================


class TestResolveActionDelay:
    """UserSigner._resolve_action_delay 静态方法测试"""

    def test_no_delay_attribute_uses_fallback(self):
        """action 没有 delay 属性时使用 fallback_delay"""
        action = SimpleNamespace()  # 无 delay 属性
        result = UserSigner._resolve_action_delay(action, fallback_delay=5.0)
        assert result == 5.0

    def test_none_delay_uses_fallback(self):
        """delay 为 None 时使用 fallback_delay"""
        action = SimpleNamespace(delay=None)
        result = UserSigner._resolve_action_delay(action, fallback_delay=3.0)
        assert result == 3.0

    def test_empty_string_delay_uses_fallback(self):
        """delay 为空字符串时使用 fallback_delay"""
        action = SimpleNamespace(delay="")
        result = UserSigner._resolve_action_delay(action, fallback_delay=2.0)
        assert result == 2.0

    def test_whitespace_delay_uses_fallback(self):
        """delay 为纯空白时使用 fallback_delay"""
        action = SimpleNamespace(delay="   ")
        result = UserSigner._resolve_action_delay(action, fallback_delay=4.0)
        assert result == 4.0

    def test_fixed_numeric_delay(self):
        """固定数值字符串解析为浮点数"""
        action = SimpleNamespace(delay="5")
        result = UserSigner._resolve_action_delay(action, fallback_delay=0)
        assert result == 5.0

    def test_fixed_float_delay(self):
        """浮点数字符串正确解析"""
        action = SimpleNamespace(delay="2.5")
        result = UserSigner._resolve_action_delay(action, fallback_delay=0)
        assert result == 2.5

    def test_range_delay_within_bounds(self):
        """范围字符串 "1-5" 返回范围内的随机值"""
        action = SimpleNamespace(delay="1-5")
        random.seed(42)
        results = {UserSigner._resolve_action_delay(action, 0) for _ in range(100)}
        for r in results:
            assert 1.0 <= r <= 5.0

    def test_range_delay_reversed_order(self):
        """范围 "5-1"（start > end）自动交换"""
        action = SimpleNamespace(delay="5-1")
        random.seed(123)
        results = {UserSigner._resolve_action_delay(action, 0) for _ in range(100)}
        for r in results:
            assert 1.0 <= r <= 5.0

    def test_negative_delay_clamped_to_zero(self):
        """负数延迟被截断为 0"""
        action = SimpleNamespace(delay="-3")
        result = UserSigner._resolve_action_delay(action, fallback_delay=0)
        assert result == 0.0

    def test_negative_fallback_clamped_to_zero(self):
        """负数 fallback 被截断为 0"""
        action = SimpleNamespace()
        result = UserSigner._resolve_action_delay(action, fallback_delay=-5.0)
        assert result == 0.0

    def test_invalid_delay_string_uses_fallback(self):
        """无法解析的字符串回退到 fallback"""
        action = SimpleNamespace(delay="abc")
        result = UserSigner._resolve_action_delay(action, fallback_delay=7.0)
        assert result == 7.0

    def test_none_fallback_returns_zero(self):
        """fallback 为 None 时回退到 0.0"""
        action = SimpleNamespace()
        result = UserSigner._resolve_action_delay(action, fallback_delay=None)
        assert result == 0.0

    def test_range_delay_with_floats(self):
        """范围支持浮点数 "1.5-3.5" """
        action = SimpleNamespace(delay="1.5-3.5")
        random.seed(99)
        results = {UserSigner._resolve_action_delay(action, 0) for _ in range(200)}
        for r in results:
            assert 1.5 <= r <= 3.5

    def test_fixed_delay_with_spaces(self):
        """带前后空格的数字正确解析"""
        action = SimpleNamespace(delay="  10  ")
        result = UserSigner._resolve_action_delay(action, fallback_delay=0)
        assert result == 10.0

    def test_integer_delay_type(self):
        """delay 为整数类型时也能正确处理"""
        action = SimpleNamespace(delay=3)
        result = UserSigner._resolve_action_delay(action, fallback_delay=0)
        assert result == 3.0


# ============================================================================
# UserSigner._validate_sign_at 测试
# ============================================================================


class TestValidateSignAt:
    """UserSigner._validate_sign_at 类方法测试"""

    def test_valid_time_format(self):
        result = UserSigner._validate_sign_at("06:00:00")
        assert result is not None
        assert result == "0 6 * * *"

    def test_valid_crontab_format(self):
        result = UserSigner._validate_sign_at("30 8 * * *")
        assert result == "30 8 * * *"

    def test_chinese_colon_replacement(self):
        """中文冒号应被替换为英文冒号"""
        result = UserSigner._validate_sign_at("06：00：00")
        assert result == "0 6 * * *"

    def test_invalid_format_returns_none(self):
        result = UserSigner._validate_sign_at("not-a-time")
        assert result is None

    def test_midnight_time(self):
        result = UserSigner._validate_sign_at("00:00:00")
        assert result == "0 0 * * *"


# ============================================================================
# UserSigner._time_to_crontab 测试
# ============================================================================


class TestTimeToCrontab:
    """UserSigner._time_to_crontab 静态方法测试"""

    def test_morning(self):
        from datetime import time as dt_time
        result = UserSigner._time_to_crontab(dt_time(6, 30))
        assert result == "30 6 * * *"

    def test_midnight(self):
        from datetime import time as dt_time
        result = UserSigner._time_to_crontab(dt_time(0, 0))
        assert result == "0 0 * * *"

    def test_evening(self):
        from datetime import time as dt_time
        result = UserSigner._time_to_crontab(dt_time(23, 59))
        assert result == "59 23 * * *"


# ============================================================================
# UserSigner 辅助方法测试
# ============================================================================


class TestUserSignerHelpers:
    """UserSigner 实用方法测试（不需要网络连接的部分）"""

    def test_normalize_log_text_truncates(self):
        """长文本被截断并添加省略号"""
        long_text = "A" * 500
        result = UserSigner._normalize_log_text(long_text, limit=100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_normalize_log_text_multiline(self):
        """多行文本合并为单行，用 ' / ' 分隔"""
        result = UserSigner._normalize_log_text("line1\nline2\nline3")
        assert result == "line1 / line2 / line3"

    def test_normalize_log_text_empty(self):
        assert UserSigner._normalize_log_text(None) == ""
        assert UserSigner._normalize_log_text("") == ""

    def test_normalize_log_text_strips_lines(self):
        result = UserSigner._normalize_log_text("  hello  \n  world  ")
        assert result == "hello / world"

    def test_is_transient_step_error_timeout(self):
        """TimeoutError 判定为瞬时错误"""
        assert UserSigner._is_transient_step_error(TimeoutError("request timed out")) is True

    def test_is_transient_step_error_asyncio_timeout(self):
        """asyncio.TimeoutError 判定为瞬时错误"""
        assert UserSigner._is_transient_step_error(asyncio.TimeoutError()) is True

    def test_is_transient_step_error_connection_reset(self):
        """连接重置判定为瞬时错误"""
        assert UserSigner._is_transient_step_error(ConnectionError("Connection reset by peer")) is True

    def test_is_transient_step_error_flood_wait(self):
        """FloodWait 消息判定为瞬时错误"""
        assert UserSigner._is_transient_step_error(Exception("FLOOD_WAIT: 30 seconds")) is True

    def test_is_transient_step_error_rate_limit(self):
        """rate limit 消息判定为瞬时错误"""
        assert UserSigner._is_transient_step_error(Exception("Too Many Requests: rate limit exceeded")) is True

    def test_is_transient_step_error_non_transient(self):
        """非瞬时错误返回 False"""
        assert UserSigner._is_transient_step_error(ValueError("invalid config")) is False
        assert UserSigner._is_transient_step_error(RuntimeError("step failed")) is False

    def test_is_transient_step_error_quota_exhausted(self):
        """配额耗尽不属于瞬时错误"""
        assert UserSigner._is_transient_step_error(Exception("quota exceeded")) is False

    def test_is_transient_step_error_quota_with_429_not_transient(self):
        """429 + 配额不足的组合文本不误判为瞬时错误（Codex Major 3 回归测试）"""
        assert UserSigner._is_transient_step_error(
            Exception("429 Too Many Requests: insufficient_quota")
        ) is False
        assert UserSigner._is_transient_step_error(
            Exception("You exceeded your current quota")
        ) is False
        assert UserSigner._is_transient_step_error(
            Exception("billing hard limit reached")
        ) is False

    def test_is_transient_step_error_auth_error_not_transient(self):
        """认证错误不属于瞬时错误"""
        assert UserSigner._is_transient_step_error(
            Exception("Invalid API key provided")
        ) is False


# ============================================================================
# UserSigner context 相关测试
# ============================================================================


class TestUserSignerContext:
    """UserSignerWorkerContext 初始化与状态管理"""

    @patch("tg_signer.core.get_client")
    def test_ensure_ctx_creates_fresh_context(self, mock_get_client):
        """ensure_ctx 创建全新的上下文对象"""
        mock_get_client.return_value = MagicMock()
        signer = UserSigner.__new__(UserSigner)
        ctx = signer.ensure_ctx()
        assert ctx.waiter is not None
        assert isinstance(ctx.waiter, Waiter)
        assert ctx.stop_after_current_action is False
        assert ctx.stop_reason is None
        assert ctx.last_callback_answer is None
        assert ctx.current_action_index is None

    @patch("tg_signer.core.get_client")
    def test_ensure_ctx_independent_instances(self, mock_get_client):
        """多次调用 ensure_ctx 返回独立的上下文"""
        mock_get_client.return_value = MagicMock()
        signer = UserSigner.__new__(UserSigner)
        ctx1 = signer.ensure_ctx()
        ctx2 = signer.ensure_ctx()
        assert ctx1 is not ctx2
        ctx1.waiter.add(1)
        assert 1 not in ctx2.waiter.waiting_ids


# ============================================================================
# 辅助函数集成测试
# ============================================================================


class TestGetClientFunction:
    """get_client 函数的 API 配置逻辑"""

    def setup_method(self):
        self._keys_before = set(_CLIENT_INSTANCES.keys())

    def teardown_method(self):
        for k in list(_CLIENT_INSTANCES.keys()):
            if k not in self._keys_before:
                _CLIENT_INSTANCES.pop(k, None)

    def test_uses_env_api_config_as_fallback(self, monkeypatch):
        """未传 api_id/api_hash 时从环境变量读取"""
        monkeypatch.setenv("TG_API_ID", "11111")
        monkeypatch.setenv("TG_API_HASH", "env-hash")
        client = get_client(name="env_fallback_test", workdir="/tmp/env_fallback")
        assert client.api_id == 11111
        assert client.api_hash == "env-hash"

    def test_explicit_api_overrides_env(self, monkeypatch):
        """显式传入的 api_id/api_hash 优先于环境变量"""
        monkeypatch.setenv("TG_API_ID", "11111")
        monkeypatch.setenv("TG_API_HASH", "env-hash")
        client = get_client(
            name="override_test", workdir="/tmp/override",
            api_id=22222, api_hash="explicit-hash",
        )
        assert client.api_id == 22222
        assert client.api_hash == "explicit-hash"
