"""版本解析与远程检查单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.utils.version_info import (
    check_remote_update,
    clear_update_check_cache,
    get_local_version_info,
    is_update_available,
    is_update_check_enabled,
    normalize_version,
    parse_semver,
    resolve_app_version,
    validate_update_check_url,
)


class TestSemver:
    def test_normalize_strips_v_prefix(self):
        assert normalize_version("v2.1.0") == "2.1.0"
        assert normalize_version("  V2.0.0 ") == "2.0.0"

    def test_parse_semver_basic(self):
        assert parse_semver("2.1.0") == (2, 1, 0)
        assert parse_semver("v1.0") == (1, 0, 0)
        assert parse_semver("3") == (3, 0, 0)

    def test_parse_semver_ignores_prerelease_and_build(self):
        assert parse_semver("2.1.0-rc.1") == (2, 1, 0)
        assert parse_semver("2.1.0+build.5") == (2, 1, 0)

    def test_is_update_available(self):
        assert is_update_available("2.0.0", "2.1.0") is True
        assert is_update_available("2.1.0", "2.1.0") is False
        assert is_update_available("2.2.0", "2.1.0") is False
        assert is_update_available("v2.0.0", "v2.0.1") is True

    def test_is_update_available_invalid_returns_false(self):
        assert is_update_available("", "2.0.0") is False
        assert is_update_available("2.0.0", "") is False


class TestResolveVersion:
    def test_empty_and_placeholder_fallback(self):
        assert resolve_app_version("2.0.0", "") == "2.0.0"
        assert resolve_app_version("2.0.0", "0.0.0") == "2.0.0"
        assert resolve_app_version("2.0.0", "v0.0.0") == "2.0.0"
        assert resolve_app_version("2.0.0", "0.0.0-dev") == "2.0.0"

    def test_real_env_override(self):
        assert resolve_app_version("2.0.0", "v2.1.0") == "2.1.0"


class TestValidateUrl:
    def test_https_ok(self):
        url = "https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest"
        assert validate_update_check_url(url) == url

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="https"):
            validate_update_check_url("http://example.com/x")

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            validate_update_check_url("")


class TestLocalInfo:
    def test_falls_back_to_tg_signer_version(self, monkeypatch):
        monkeypatch.delenv("APP_VERSION", raising=False)
        monkeypatch.setenv("GIT_SHA", "deadbeefcafebabe")
        monkeypatch.setenv("GIT_BRANCH", "dev")
        monkeypatch.delenv("BUILD_TIME", raising=False)
        info = get_local_version_info()
        from tg_signer import __version__

        assert info["version"] == __version__
        assert info["git_sha"] == "deadbeefcafebabe"
        assert info["git_branch"] == "dev"
        assert info["build_time"] == ""
        assert "python" in info
        assert isinstance(info["update_check_enabled"], bool)

    def test_app_version_env_overrides(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "v9.9.9")
        info = get_local_version_info()
        assert info["version"] == "9.9.9"

    def test_placeholder_app_version_falls_back(self, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "0.0.0")
        info = get_local_version_info()
        from tg_signer import __version__

        assert info["version"] == __version__


class TestUpdateCheckFlag:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("APP_UPDATE_CHECK", raising=False)
        assert is_update_check_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "off", "OFF", "no"])
    def test_disabled_values(self, monkeypatch, val):
        monkeypatch.setenv("APP_UPDATE_CHECK", val)
        assert is_update_check_enabled() is False


class TestRemoteCheck:
    def setup_method(self):
        clear_update_check_cache()

    def test_disabled_skips_network(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "0")
        with patch("backend.utils.version_info.httpx.Client") as client_cls:
            result = check_remote_update()
            client_cls.assert_not_called()
        assert result["enabled"] is False
        assert result["update_available"] is False
        assert result["error"] is None
        assert result["latest_version"] is None

    def _html_redirect_client(self, tag: str = "v2.1.0"):
        """模拟 github.com/releases/latest → /tag/vX 的 302。"""
        html_resp = MagicMock()
        html_resp.status_code = 302
        html_resp.is_redirect = True
        html_resp.headers = {
            "location": (
                f"https://github.com/Silentely/TG-SignPulse/releases/tag/{tag}"
            )
        }
        html_resp.url = httpx.URL(
            "https://github.com/Silentely/TG-SignPulse/releases/latest"
        )
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.return_value = html_resp
        return mock_client

    def test_success_newer_release(self, monkeypatch):
        """默认主路径：HTML 重定向解析 tag，不请求 api.github.com。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        mock_client = self._html_redirect_client("v2.1.0")
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["enabled"] is True
        assert result["latest_version"] == "2.1.0"
        assert result["update_available"] is True
        assert result["error"] is None
        assert result["source"] == "github_releases_redirect"
        assert result["cached"] is False
        # 只应请求 HTML latest，一次即可
        assert mock_client.get.call_count == 1
        called_url = str(mock_client.get.call_args[0][0])
        assert "api.github.com" not in called_url
        assert "github.com" in called_url and "releases/latest" in called_url

    def test_cache_hit_second_call(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        mock_client = self._html_redirect_client("v2.1.0")
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            first = check_remote_update(force=True)
            second = check_remote_update(force=False)
        assert first["cached"] is False
        assert second["cached"] is True
        assert mock_client.get.call_count == 1

    def test_network_error_soft_fail(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        # 阻断 HTML 与 JSON 兜底
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.side_effect = Exception("connection refused")
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["enabled"] is True
        assert result["update_available"] is False
        assert result["error"]
        assert len(result["error"]) > 0
        assert "developer.mozilla.org" not in (result["error"] or "")

    def test_network_error_not_cached(self, monkeypatch):
        """失败结果不得占用成功缓存，后续应再次请求。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.side_effect = Exception("timeout")
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            check_remote_update(force=True)
            check_remote_update(force=False)
        # 每次失败：HTML + JSON 兜底，故 call_count >= 2
        assert mock_client.get.call_count >= 2

    def test_rejects_non_https_custom_url(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_UPDATE_CHECK_URL", "http://evil.local/latest")
        result = check_remote_update(force=True)
        assert result["enabled"] is True
        assert result["update_available"] is False
        assert result["error"]
        assert "https" in result["error"].lower()

    def test_html_primary_does_not_need_token(self, monkeypatch):
        """自部署零配置：无 Token 也能用 HTML 重定向检查更新。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        monkeypatch.delenv("APP_GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        mock_client = self._html_redirect_client("v2.5.0")
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["error"] is None
        assert result["latest_version"] == "2.5.0"
        assert result["source"] == "github_releases_redirect"
        headers = mock_client.get.call_args.kwargs.get("headers") or {}
        assert "Authorization" not in headers

    def test_html_fail_falls_back_to_json_api(self, monkeypatch):
        """HTML 失败时再走 JSON/API 兜底。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)

        with patch(
            "backend.utils.version_info._fetch_via_html_redirect",
            side_effect=Exception("html down"),
        ), patch(
            "backend.utils.version_info._fetch_json_release",
            return_value={
                "enabled": True,
                "latest_version": "2.2.0",
                "latest_url": (
                    "https://github.com/Silentely/TG-SignPulse/releases/tag/v2.2.0"
                ),
                "update_available": True,
                "checked_at": "2026-07-26T00:00:00+00:00",
                "error": None,
                "source": "github_releases",
                "cached": False,
            },
        ):
            result = check_remote_update(force=True)
        assert result["error"] is None
        assert result["latest_version"] == "2.2.0"
        assert result["source"] == "github_releases"

    def test_friendly_error_hides_httpx_and_token(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Client error '403 rate limit exceeded' for url "
            "'https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest' "
            "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["enabled"] is True
        assert result["latest_version"] is None
        assert result["error"]
        # 不对用户提 Token / MDN 长链接
        assert "developer.mozilla.org" not in (result["error"] or "")
        assert "APP_GITHUB_TOKEN" not in (result["error"] or "")
        assert "GITHUB_TOKEN" not in (result["error"] or "")

    def test_stale_cache_on_failure_after_success(self, monkeypatch):
        """曾经成功后再次失败时返回过期缓存，而非硬错误。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.delenv("APP_UPDATE_CHECK_URL", raising=False)

        ok_client = self._html_redirect_client("v2.1.0")
        fail_client = MagicMock()
        fail_client.__enter__.return_value = fail_client
        fail_client.__exit__.return_value = None
        fail_client.get.side_effect = Exception("timeout")

        with patch(
            "backend.utils.version_info.httpx.Client", return_value=ok_client
        ):
            first = check_remote_update(force=True)
        assert first["latest_version"] == "2.1.0"

        from backend.utils import version_info as vi

        with vi._cache_lock:
            vi._cache["expires_at"] = 0.0

        with patch(
            "backend.utils.version_info.httpx.Client", return_value=fail_client
        ):
            second = check_remote_update(force=True)
        assert second["latest_version"] == "2.1.0"
        assert second["cached"] is True
        assert second["error"] is None
        assert "stale" in str(second.get("source") or "")

    def test_custom_json_url_skips_html(self, monkeypatch):
        """非 GitHub 的自定义 JSON 源直接请求，不套 HTML 路径。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.setenv(
            "APP_UPDATE_CHECK_URL", "https://example.com/releases/latest.json"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tag_name": "v3.0.0",
            "html_url": "https://example.com/r/v3.0.0",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.return_value = mock_resp
        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["latest_version"] == "3.0.0"
        assert result["source"] == "custom_release_json"
        called = str(mock_client.get.call_args[0][0])
        assert called == "https://example.com/releases/latest.json"

    def test_github_token_used_only_on_json_fallback(self, monkeypatch):
        """Token 仅在 JSON/API 兜底请求时附加，HTML 主路径不需要。"""
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        monkeypatch.setenv("APP_GITHUB_TOKEN", "ghp_test_token")
        # 自定义非 GitHub URL → 直接 JSON，验证 Authorization
        monkeypatch.setenv(
            "APP_UPDATE_CHECK_URL", "https://example.com/releases/latest.json"
        )

        api_resp = MagicMock()
        api_resp.status_code = 200
        api_resp.json.return_value = {
            "tag_name": "v2.1.0",
            "html_url": "https://example.com/r",
        }
        api_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.return_value = api_resp

        with patch(
            "backend.utils.version_info.httpx.Client", return_value=mock_client
        ):
            result = check_remote_update(force=True)
        assert result["latest_version"] == "2.1.0"
        headers = mock_client.get.call_args.kwargs.get("headers") or {}
        assert headers.get("Authorization") == "Bearer ghp_test_token"
