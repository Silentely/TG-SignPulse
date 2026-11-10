"""测试 Cloudflare Provider 支持、存量识别、D1 凭据切换保护与响应归一化故障转移"""

from __future__ import annotations

import json
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
