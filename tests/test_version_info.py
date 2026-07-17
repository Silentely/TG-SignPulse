"""版本解析与远程检查单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.utils.version_info import (
    check_remote_update,
    clear_update_check_cache,
    get_local_version_info,
    is_update_available,
    is_update_check_enabled,
    normalize_version,
    parse_semver,
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

    def test_success_newer_release(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tag_name": "v2.1.0",
            "html_url": "https://github.com/Silentely/TG-SignPulse/releases/tag/v2.1.0",
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
        assert result["enabled"] is True
        assert result["latest_version"] == "2.1.0"
        assert result["update_available"] is True
        assert result["error"] is None
        assert result["source"] == "github_releases"
        assert result["cached"] is False

    def test_cache_hit_second_call(self, monkeypatch):
        monkeypatch.setenv("APP_UPDATE_CHECK", "1")
        monkeypatch.setenv("APP_VERSION", "2.0.0")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tag_name": "v2.1.0",
            "html_url": "https://example.com/r",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.return_value = mock_resp
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
