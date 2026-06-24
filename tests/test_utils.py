"""
后端工具函数单元测试

覆盖范围：
- 时间工具（backend.utils.time）
- 路径工具（backend.utils.paths）
- 代理工具（backend.utils.proxy）
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.utils.proxy import build_proxy_dict, normalize_proxy_url
from backend.utils.time import (
    UTC,
    utc_from_timestamp,
    utc_from_timestamp_iso_z,
    utc_now,
    utc_now_iso,
    utc_now_iso_z,
    utc_now_naive,
)


# ============================================================================
# 时间工具测试
# ============================================================================


class TestUtcNow:
    """utc_now() 测试套件"""

    def test_returns_aware_datetime(self):
        """返回值必须带 UTC 时区信息"""
        result = utc_now()
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_returns_utc_time(self):
        """返回的时间必须是 UTC 时区"""
        result = utc_now()
        assert result.tzinfo == UTC

    def test_close_to_real_time(self):
        """返回的时间应与真实时间相差不超过 1 秒"""
        before = datetime.now(timezone.utc)
        result = utc_now()
        after = datetime.now(timezone.utc)
        assert before <= result <= after

    @patch("backend.utils.time.datetime")
    def test_calls_datetime_now_with_utc(self, mock_dt):
        """验证内部调用 datetime.now(UTC)"""
        expected = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = expected
        # 需要保留 timezone.utc 的真实引用
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        result = utc_now()
        mock_dt.now.assert_called_once_with(UTC)


class TestUtcNowNaive:
    """utc_now_naive() 测试套件"""

    def test_returns_naive_datetime(self):
        """返回值必须无时区信息"""
        result = utc_now_naive()
        assert result.tzinfo is None

    def test_close_to_real_time(self):
        """返回的时间应与真实 UTC 时间相差不超过 1 秒"""
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utc_now_naive()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= result <= after

    def test_matches_utc_now_without_tz(self):
        """utc_now_naive 应等同于 utc_now() 去掉时区"""
        aware = utc_now()
        naive = utc_now_naive()
        # 两者应非常接近（微秒级差异可接受）
        diff = abs((aware.replace(tzinfo=None) - naive).total_seconds())
        assert diff < 0.1

    @patch("backend.utils.time.utc_now")
    def test_strips_tzinfo(self, mock_utc_now):
        """验证通过 replace(tzinfo=None) 去除时区"""
        mock_utc_now.return_value = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = utc_now_naive()
        assert result == datetime(2025, 6, 15, 10, 30, 0)
        assert result.tzinfo is None


class TestUtcNowIso:
    """utc_now_iso() 测试套件"""

    def test_returns_string(self):
        """返回值必须是字符串"""
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_valid_iso_format(self):
        """返回值必须是合法的 ISO 8601 格式"""
        result = utc_now_iso()
        # datetime.fromisoformat 在 3.10+ 能解析带时区的 ISO 格式
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None

    def test_contains_utc_offset(self):
        """ISO 格式应包含 UTC 偏移量信息"""
        result = utc_now_iso()
        assert "+00:00" in result or "Z" in result.lower()


class TestUtcNowIsoZ:
    """utc_now_iso_z() 测试套件"""

    def test_returns_string(self):
        """返回值必须是字符串"""
        result = utc_now_iso_z()
        assert isinstance(result, str)

    def test_ends_with_z(self):
        """返回值必须以 'Z' 结尾表示 UTC"""
        result = utc_now_iso_z()
        assert result.endswith("Z")

    def test_no_plus_offset(self):
        """返回值不应包含 +00:00 偏移（已替换为 Z）"""
        result = utc_now_iso_z()
        assert "+00:00" not in result


class TestUtcFromTimestamp:
    """utc_from_timestamp() 测试套件"""

    def test_returns_aware_datetime(self):
        """返回值必须带 UTC 时区"""
        result = utc_from_timestamp(0)
        assert result.tzinfo == timezone.utc

    def test_epoch_zero(self):
        """时间戳 0 应对应 1970-01-01 00:00:00 UTC"""
        result = utc_from_timestamp(0)
        assert result == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_known_timestamp(self):
        """验证已知时间戳的转换结果"""
        # 2024-01-01 00:00:00 UTC = 1704067200
        result = utc_from_timestamp(1704067200)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1

    def test_accepts_float(self):
        """必须支持浮点数时间戳"""
        result = utc_from_timestamp(1704067200.5)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024

    def test_accepts_int(self):
        """必须支持整数时间戳"""
        result = utc_from_timestamp(1704067200)
        assert isinstance(result, datetime)


class TestUtcFromTimestampIsoZ:
    """utc_from_timestamp_iso_z() 测试套件"""

    def test_epoch_returns_iso_z(self):
        """时间戳 0 的 ISO-Z 格式"""
        result = utc_from_timestamp_iso_z(0)
        assert result == "1970-01-01T00:00:00Z"

    def test_ends_with_z(self):
        """返回值必须以 Z 结尾"""
        result = utc_from_timestamp_iso_z(1704067200)
        assert result.endswith("Z")

    def test_no_plus_offset(self):
        """返回值不应包含 +00:00"""
        result = utc_from_timestamp_iso_z(1704067200)
        assert "+00:00" not in result


# ============================================================================
# 路径工具测试
# ============================================================================


class TestEnsureDataDirs:
    """ensure_data_dirs() 测试套件"""

    def _make_settings(self, tmp_path: Path) -> MagicMock:
        """构造模拟的 Settings 对象，所有路径指向 tmp_path 下"""
        base = tmp_path / "data"
        settings = MagicMock()
        settings.resolve_base_dir.return_value = base
        settings.resolve_workdir.return_value = base / ".signer"
        settings.resolve_session_dir.return_value = base / "sessions"
        settings.resolve_logs_dir.return_value = base / "logs"
        settings.resolve_db_path.return_value = base / "db.sqlite"
        return settings

    def test_creates_base_dir(self, tmp_path: Path):
        """必须创建基础数据目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        assert (tmp_path / "data").is_dir()

    def test_creates_workdir(self, tmp_path: Path):
        """必须创建工作目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        assert (tmp_path / "data" / ".signer").is_dir()

    def test_creates_session_dir(self, tmp_path: Path):
        """必须创建会话目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        assert (tmp_path / "data" / "sessions").is_dir()

    def test_creates_logs_dir(self, tmp_path: Path):
        """必须创建日志目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        assert (tmp_path / "data" / "logs").is_dir()

    def test_creates_db_parent_dir(self, tmp_path: Path):
        """必须创建数据库文件的父目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        assert (tmp_path / "data").is_dir()
        # db_path 的父目录就是 base，已验证

    def test_idempotent(self, tmp_path: Path):
        """重复调用不应报错（exist_ok=True）"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)
        # 第二次调用不应抛出异常
        ensure_data_dirs(settings)

        assert (tmp_path / "data").is_dir()

    def test_nested_paths(self, tmp_path: Path):
        """当数据库路径在子目录中时，应递归创建父目录"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        # 数据库路径在更深层目录
        settings.resolve_db_path.return_value = tmp_path / "data" / "sub" / "deep" / "db.sqlite"
        ensure_data_dirs(settings)

        assert (tmp_path / "data" / "sub" / "deep").is_dir()

    def test_calls_all_resolve_methods(self, tmp_path: Path):
        """必须调用所有 resolve_* 方法"""
        from backend.utils.paths import ensure_data_dirs

        settings = self._make_settings(tmp_path)
        ensure_data_dirs(settings)

        settings.resolve_base_dir.assert_called_once()
        settings.resolve_workdir.assert_called_once()
        settings.resolve_session_dir.assert_called_once()
        settings.resolve_logs_dir.assert_called_once()
        settings.resolve_db_path.assert_called_once()


# ============================================================================
# 代理工具测试
# ============================================================================


class TestNormalizeProxyUrl:
    """normalize_proxy_url() 测试套件"""

    def test_empty_string_returns_empty(self):
        """空字符串应原样返回"""
        assert normalize_proxy_url("") == ""

    def test_whitespace_only_returns_empty(self):
        """纯空白字符串应返回空"""
        assert normalize_proxy_url("   ") == ""

    def test_already_has_scheme(self):
        """已有协议的 URL 应原样返回"""
        url = "socks5://user:pass@host:1080"
        assert normalize_proxy_url(url) == url

    def test_http_scheme_preserved(self):
        """HTTP 代理 URL 应保留原始协议"""
        url = "http://proxy.example.com:8080"
        assert normalize_proxy_url(url) == url

    def test_https_scheme_preserved(self):
        """HTTPS 代理 URL 应保留原始协议"""
        url = "https://proxy.example.com:443"
        assert normalize_proxy_url(url) == url

    def test_host_port_only(self):
        """host:port 格式应添加 socks5:// 前缀"""
        result = normalize_proxy_url("127.0.0.1:1080")
        assert result == "socks5://127.0.0.1:1080"

    def test_with_at_sign(self):
        """包含 @ 的字符串（user:pass@host:port）应添加 socks5:// 前缀"""
        result = normalize_proxy_url("user:pass@host:1080")
        assert result == "socks5://user:pass@host:1080"

    def test_four_part_format(self):
        """host:port:user:password 格式应转换为 socks5://user:password@host:port"""
        result = normalize_proxy_url("192.168.1.1:1080:myuser:mypass")
        assert result == "socks5://myuser:mypass@192.168.1.1:1080"

    def test_strips_whitespace(self):
        """应去除前后空白"""
        result = normalize_proxy_url("  127.0.0.1:1080  ")
        assert result == "socks5://127.0.0.1:1080"

    def test_fallback_socks5(self):
        """无法识别的格式应添加 socks5:// 前缀"""
        result = normalize_proxy_url("somehost")
        assert result == "socks5://somehost"


class TestBuildProxyDict:
    """build_proxy_dict() 测试套件"""

    def test_empty_string_returns_none(self):
        """空字符串应返回 None"""
        assert build_proxy_dict("") is None

    def test_whitespace_only_returns_none(self):
        """纯空白字符串应返回 None"""
        assert build_proxy_dict("   ") is None

    def test_basic_socks5_proxy(self):
        """基础 socks5 代理应返回正确的字典"""
        result = build_proxy_dict("socks5://host:1080")
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "host"
        assert result["port"] == 1080
        assert "username" not in result
        assert "password" not in result

    def test_proxy_with_auth(self):
        """带认证的代理应包含 username 和 password"""
        result = build_proxy_dict("socks5://user:pass@host:1080")
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "host"
        assert result["port"] == 1080
        assert result["username"] == "user"
        assert result["password"] == "pass"

    def test_http_proxy(self):
        """HTTP 代理应正确解析"""
        result = build_proxy_dict("http://proxy.example.com:8080")
        assert result is not None
        assert result["scheme"] == "http"
        assert result["hostname"] == "proxy.example.com"
        assert result["port"] == 8080

    def test_https_proxy(self):
        """HTTPS 代理应正确解析"""
        result = build_proxy_dict("https://proxy.example.com:443")
        assert result is not None
        assert result["scheme"] == "https"
        assert result["hostname"] == "proxy.example.com"
        assert result["port"] == 443

    def test_host_port_auto_normalized(self):
        """host:port 格式应通过 normalize 自动转为 socks5"""
        result = build_proxy_dict("127.0.0.1:1080")
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "127.0.0.1"
        assert result["port"] == 1080

    def test_four_part_format(self):
        """host:port:user:password 格式应正确转换"""
        result = build_proxy_dict("192.168.1.1:1080:myuser:mypass")
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "192.168.1.1"
        assert result["port"] == 1080
        assert result["username"] == "myuser"
        assert result["password"] == "mypass"

    def test_at_sign_format(self):
        """user:pass@host:port 格式应正确解析"""
        result = build_proxy_dict("admin:secret@proxy.local:3128")
        assert result is not None
        assert result["scheme"] == "socks5"
        assert result["hostname"] == "proxy.local"
        assert result["port"] == 3128
        assert result["username"] == "admin"
        assert result["password"] == "secret"

    def test_ip_address_proxy(self):
        """IP 地址形式的代理应正确解析"""
        result = build_proxy_dict("socks5://10.0.0.1:9050")
        assert result is not None
        assert result["hostname"] == "10.0.0.1"
        assert result["port"] == 9050

    def test_returns_dict_type(self):
        """返回值必须是字典类型"""
        result = build_proxy_dict("socks5://host:1080")
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        """返回字典必须包含 scheme、hostname、port"""
        result = build_proxy_dict("socks5://host:1080")
        assert "scheme" in result
        assert "hostname" in result
        assert "port" in result

    def test_port_is_integer(self):
        """port 必须是整数类型"""
        result = build_proxy_dict("socks5://host:1080")
        assert isinstance(result["port"], int)
