"""测试 Cloudflare Provider 支持、存量识别、D1 凭据切换保护与响应归一化故障转移"""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.config import ConfigService
from tg_signer.ai_tools import AITools
from tg_signer.core.ai_failover import (
    AIProviderManager,
    AIProviderResponseError,
    normalize_ai_response,
)

_FAKE_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _pin_hostname_dns(monkeypatch):
    """把主机名解析钉死为公网 IP，彻底解耦外部真实 DNS。"""
    real_getaddrinfo = socket.getaddrinfo

    def _pinned_getaddrinfo(host, *args, **kwargs):
        if isinstance(host, str):
            name = host.strip("[]").lower()
            if name in ("localhost", "localhost.localdomain"):
                return real_getaddrinfo("127.0.0.1", *args, **kwargs)
            try:
                ipaddress.ip_address(name)
            except ValueError:
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        (_FAKE_PUBLIC_IP, 0),
                    )
                ]
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _pinned_getaddrinfo)


class TestAiLegacyMigrationAndProvider:
    """存量配置自动识别与 Cloudflare Account ID 校验测试"""

    def test_legacy_cf_url_migration(self, isolated_env: Path):
        """存量配置包含手填 CF URL 时，读取时自动识别为 cloudflare 并提取 account_id"""
        service = ConfigService()
        config_file = service.workdir / ".openai_config.json"
        cf_id = "0123456789abcdef0123456789abcdef"
        legacy_data = {
            "api_key": "sk-dummy-token",
            "base_url": f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/ai",
            "model": "@cf/meta/llama-3.2-11b-vision-instruct",
        }
        config_file.write_text(json.dumps(legacy_data), encoding="utf-8")

        cfg = service.get_ai_config()
        assert cfg is not None
        assert cfg["provider"] == "cloudflare", (
            "存量 CF URL 应自动识别为 cloudflare provider"
        )
        assert cfg["cloudflare_account_id"] == cf_id, "应自动提取 32 位 Account ID"
        assert cfg["model"] == "@cf/meta/llama-3.2-11b-vision-instruct"

        # 检查 AITools 同样能自动解析
        tools = AITools(cfg)
        assert tools.provider == "cloudflare"
        assert tools.cloudflare_account_id == cf_id
        assert tools._is_cloudflare_vision() is True

    def test_account_id_hex_validation(self, isolated_env: Path):
        """Account ID 必须是 32 位十六进制，否则抛出 ValueError"""
        service = ConfigService()
        with pytest.raises(ValueError, match="32 位十六进制"):
            service.save_ai_config(
                api_key="token-123",
                provider="cloudflare",
                cloudflare_account_id="invalid-short-id",
            )

    def test_account_id_masked(self, isolated_env: Path):
        """Account ID 应在脱敏后正确生成掩码"""
        service = ConfigService()
        cf_id = "0123456789abcdef0123456789abcdef"
        service.save_ai_config(
            api_key="token-123",
            provider="cloudflare",
            cloudflare_account_id=cf_id,
        )
        cfg = service.get_ai_config()
        assert cfg["cloudflare_account_id"] == cf_id
        from backend.api.routes.config import get_ai_config
        from backend.models.user import User

        resp = get_ai_config(current_user=User(username="test"))
        assert resp.cloudflare_account_id_masked == "0123************************cdef"

    def test_account_id_not_leaked_in_get_ai_config_response(self, isolated_env: Path):
        """P2: get_ai_config 响应的整个 JSON 中（包括 base_url），绝对不许出现完整的 32 位 hex account id"""
        from backend.api.routes.config import get_ai_config
        from backend.models.user import User

        service = ConfigService()
        cf_id = "0123456789abcdef0123456789abcdef"
        service.save_ai_config(
            api_key="cf-token-123",
            provider="cloudflare",
            cloudflare_account_id=cf_id,
        )

        resp = get_ai_config(current_user=User(username="test"))
        resp_json = (
            resp.model_dump_json()
            if hasattr(resp, "model_dump_json")
            else json.dumps(resp.dict())
        )
        assert cf_id not in resp_json, (
            f"响应 JSON 中泄露了完整的 32 位 Account ID: {resp_json}"
        )
        assert resp.cloudflare_account_id_masked is not None
        assert "****" in resp.cloudflare_account_id_masked
        assert "****" in (resp.base_url or "")


class TestProviderSwitchSecretProtection:
    """D1: 切换 provider 时禁止静默复用旧 provider 密钥"""

    def test_switch_provider_without_key_raises(self, isolated_env: Path):
        """从 openai 切换至 cloudflare 且不传新 key 时必须拒绝保存并报错"""
        service = ConfigService()
        # 初始为 openai 配置
        service.save_ai_config(
            api_key="sk-openai-original-secret",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            provider="openai",
        )

        cf_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        # 切换到 cloudflare，但 api_key 为空
        with pytest.raises(ValueError, match="禁止复用旧密钥"):
            service.save_ai_config(
                api_key=None,
                provider="cloudflare",
                cloudflare_account_id=cf_id,
                model="@cf/meta/llama-3.2-11b-vision-instruct",
            )

    def test_switch_provider_with_new_key_succeeds(self, isolated_env: Path):
        """从 openai 切换至 cloudflare 并提供新 key 应成功保存"""
        service = ConfigService()
        service.save_ai_config(
            api_key="sk-openai-original",
            provider="openai",
        )
        cf_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        service.save_ai_config(
            api_key="cf-new-token",
            provider="cloudflare",
            cloudflare_account_id=cf_id,
        )
        cfg = service.get_ai_config()
        assert cfg["provider"] == "cloudflare"
        assert cfg["api_key"] == "cf-new-token"
        assert cfg["cloudflare_account_id"] == cf_id

    def test_switch_from_openai_to_cf_discards_stale_base_url(self, isolated_env: Path):
        """P1: 从 OpenAI 切换到 CF 时，即使传入旧的 OpenAI base_url，也必须丢弃并以 account_id 重建为 CF 端点，且旧 token 绝不残留"""
        service = ConfigService()
        old_openai_url = "https://api.openai.com/v1"
        old_openai_key = "sk-openai-original-key-12345"
        service.save_ai_config(
            api_key=old_openai_key,
            base_url=old_openai_url,
            model="gpt-4o",
            provider="openai",
        )

        cf_id = "0123456789abcdef0123456789abcdef"
        new_cf_token = "cf-new-secret-token"
        # 切换到 CF，入参故意携带旧的 OpenAI base_url
        service.save_ai_config(
            api_key=new_cf_token,
            provider="cloudflare",
            cloudflare_account_id=cf_id,
            base_url=old_openai_url,
        )

        cfg = service.get_ai_config()
        assert cfg["provider"] == "cloudflare"
        expected_cf_url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/ai"
        assert cfg["base_url"] == expected_cf_url, (
            "base_url 必须重建为 CF 端点，旧的 OpenAI URL 必须被丢弃"
        )
        assert cfg["api_key"] == new_cf_token
        assert old_openai_key not in json.dumps(cfg), (
            "旧 OpenAI token 绝不能残留在配置中"
        )

        # 进一步校验：AITools 初始化的 endpoint 确实是 CF 端点
        tools = AITools(cfg)
        assert tools.base_url == expected_cf_url
        assert tools.provider == "cloudflare"
        assert tools.api_key == new_cf_token


class TestNormalizationAndEmptyCheck:
    """B1: 传输层响应归一化与 200 空内容判定"""

    def test_normalize_cloudflare_success(self):
        """合法 CF 响应成功归一化为 OpenAI choices 结构"""
        cf_raw = {
            "result": {"answer": "Option 2: dog"},
            "success": True,
        }
        res = normalize_ai_response(
            cf_raw, provider_type="cloudflare", model="@cf/llama"
        )
        assert "choices" in res
        choice = res["choices"][0]
        assert choice["message"]["role"] == "assistant"
        content = json.loads(choice["message"]["content"])
        assert content["answer"] == "Option 2: dog"

    def test_normalize_cloudflare_empty_body_raises(self):
        """CF 返回 200 但 body 为空或缺少有效 answer 必须判失败"""
        # 1. 缺少 answer 字段
        with pytest.raises(AIProviderResponseError, match="响应内容无效"):
            normalize_ai_response(
                {"result": {}, "success": True}, provider_type="cloudflare"
            )

        # 2. answer 为空串
        with pytest.raises(AIProviderResponseError, match="响应内容无效"):
            normalize_ai_response(
                {"result": {"answer": "   "}, "success": True},
                provider_type="cloudflare",
            )

        # 3. 业务 success 为 False
        with pytest.raises(AIProviderResponseError, match="业务执行失败"):
            normalize_ai_response(
                {"success": False, "errors": ["Model busy"]}, provider_type="cloudflare"
            )


@pytest.mark.asyncio
class TestCloudflareFailoverToOpenAI:
    """主节点为 Cloudflare 时失败能够顺利退到备用 OpenAI 节点"""

    async def test_cf_failure_falls_back_to_secondary(self):
        tools = AITools(
            {
                "api_key": "cf-token",
                "provider": "cloudflare",
                "cloudflare_account_id": "0123456789abcdef0123456789abcdef",
                "model": "@cf/meta/llama-3.2-11b-vision-instruct",
                "fallback_providers": [
                    {
                        "id": "backup-openai",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-backup-key",
                        "model": "gpt-4o-mini",
                    }
                ],
            }
        )

        # 模拟主 CF 请求抛异常
        with patch.object(
            tools,
            "_call_cloudflare_vision_with_retries",
            side_effect=RuntimeError("Cloudflare 500 error"),
        ):
            # 模拟备用节点调用成功
            mock_openai_resp = {
                "id": "chatcmpl-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"answer": "1"}),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
            with patch.object(
                AIProviderManager,
                "_call_single_provider",
                new=AsyncMock(return_value=mock_openai_resp),
            ):
                result = await tools._create_visual_completion(
                    client=None,
                    model="@cf/meta/llama-3.2-11b-vision-instruct",
                    messages=[{"role": "user", "content": "pick 1"}],
                    temperature=0.1,
                    max_tokens=256,
                    expect_json=True,
                )
                assert result.choices[0].message.content == json.dumps({"answer": "1"})


class TestAiConfigRouteValidation:
    """P3 & P4: 路由层参数枚举校验与 ValueError 映射为 400"""

    def test_save_ai_config_invalid_provider_returns_400(self, isolated_env: Path):
        """P4: provider 非法枚举值一律拒绝并返回 400"""
        from fastapi import HTTPException

        from backend.api.routes.config import AIConfigRequest, save_ai_config
        from backend.models.user import User

        user = User(username="admin")
        req = AIConfigRequest(
            api_key="token-123",
            provider="unsupported_provider",
        )
        with pytest.raises(HTTPException) as exc_info:
            save_ai_config(request=req, current_user=user)
        assert exc_info.value.status_code == 400
        assert "不支持的 AI 提供商" in exc_info.value.detail

    def test_save_ai_config_value_error_returns_400_and_masked(
        self, isolated_env: Path
    ):
        """P3: 非法配置参数引发的 ValueError 应被路由层转换为 400，且 detail 脱敏"""
        from fastapi import HTTPException

        from backend.api.routes.config import AIConfigRequest, save_ai_config
        from backend.models.user import User

        user = User(username="admin")
        req = AIConfigRequest(
            api_key="cf-token-123456789",
            provider="cloudflare",
            cloudflare_account_id="invalid-id-xyz",
        )
        with pytest.raises(HTTPException) as exc_info:
            save_ai_config(request=req, current_user=user)
        assert exc_info.value.status_code == 400
        assert "32 位十六进制" in exc_info.value.detail
        assert "cf-token-123456789" not in exc_info.value.detail

    def test_service_invalid_provider_raises_value_error(self, isolated_env: Path):
        """P4 服务层直接校验：非法 provider 抛出 ValueError"""
        service = ConfigService()
        with pytest.raises(ValueError, match="不支持的 AI 提供商类型"):
            service.save_ai_config(
                api_key="token-123",
                provider="invalid_type",
            )
