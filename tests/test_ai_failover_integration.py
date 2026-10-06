"""AI 主节点失败后转备用节点的集成测试（含配置解析与指纹）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tg_signer.ai_tools import AITools, ai_cfg_signature, parse_fallback_providers
from tg_signer.core.ai_failover import AIProviderManager


def test_parse_fallback_providers_filters_invalid():
    assert parse_fallback_providers(None) == []
    assert parse_fallback_providers([]) == []
    assert parse_fallback_providers("not-json") == []
    assert parse_fallback_providers([{"base_url": "u"}]) == []  # 缺 api_key
    assert parse_fallback_providers("[]") == []
    assert parse_fallback_providers('[{"api_key":"k","base_url":"u","model":"m"}]') == [
        {"api_key": "k", "base_url": "u", "model": "m"}
    ]


def test_ai_cfg_signature_changes_with_fallback_providers():
    base = {"api_key": "a", "base_url": "u", "model": "m"}
    with_fb = {
        **base,
        "fallback_providers": [{"api_key": "b", "base_url": "u2", "model": "m2"}],
    }
    assert ai_cfg_signature(base) != ai_cfg_signature(with_fb)
    assert ai_cfg_signature(base) == ai_cfg_signature(dict(base))


def _cfg_with_fallback():
    return {
        "api_key": "primary-key",
        "base_url": "http://primary",
        "model": "m1",
        "fallback_providers": [
            {"api_key": "fb-key", "base_url": "http://fb", "model": "m2"}
        ],
    }


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_configured_provider():
    tools = AITools(_cfg_with_fallback())
    response = {
        "id": "x",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"selected_index": 1}'},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    captured = {}

    async def fake_primary(*args, **kwargs):
        raise RuntimeError("primary boom")

    async def fake_dispatch(self, payload, providers, *, abort_on_config_error=True):
        captured["providers"] = providers
        captured["payload"] = payload
        captured["abort"] = abort_on_config_error
        return response

    with (
        patch.object(
            AITools, "_run_visual_completion_with_client", side_effect=fake_primary
        ),
        patch.object(AIProviderManager, "dispatch_request", fake_dispatch),
    ):
        result = await tools._create_visual_completion(
            client=tools.client,
            model="m1",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
            max_tokens=16,
            expect_json=True,
        )

    # 原生 dict 被适配为属性可访问对象，现有调用方无需改动
    assert result.choices[0].message.content == '{"selected_index": 1}'
    assert result.usage.prompt_tokens == 1

    providers = captured["providers"]
    assert len(providers) == 1
    assert providers[0].api_key == "fb-key"
    assert providers[0].base_url == "http://fb"
    assert providers[0].model == "m2"
    # payload 不固定 model，交由各节点注入自身模型
    assert "model" not in captured["payload"]
    # 备用层不应因单个节点配置错误而中断整条链
    assert captured["abort"] is False


@pytest.mark.asyncio
async def test_no_fallback_reraises_primary_error():
    tools = AITools({"api_key": "k", "base_url": "http://p", "model": "m"})

    async def boom(*args, **kwargs):
        raise RuntimeError("primary boom")

    with patch.object(AITools, "_run_visual_completion_with_client", side_effect=boom):
        with pytest.raises(RuntimeError, match="primary boom"):
            await tools._create_visual_completion(
                client=tools.client,
                model="m",
                messages=[],
                temperature=0.1,
                max_tokens=16,
                expect_json=False,
            )


@pytest.mark.asyncio
async def test_all_fallbacks_fail_raises_runtime_error():
    from tg_signer.core.ai_failover import AIAllProvidersFailedError

    tools = AITools(_cfg_with_fallback())

    async def fake_primary(*args, **kwargs):
        raise RuntimeError("primary boom")

    async def always_fail(self, payload, providers, *, abort_on_config_error=True):
        raise AIAllProvidersFailedError("all down")

    with (
        patch.object(
            AITools, "_run_visual_completion_with_client", side_effect=fake_primary
        ),
        patch.object(AIProviderManager, "dispatch_request", always_fail),
    ):
        with pytest.raises(RuntimeError, match="全部备用节点均失败"):
            await tools._create_visual_completion(
                client=tools.client,
                model="m1",
                messages=[],
                temperature=0.1,
                max_tokens=16,
                expect_json=True,
            )
