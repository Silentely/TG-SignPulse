import asyncio
import json
from unittest.mock import patch

import pytest

from backend.services.ai_provider_manager import (
    AIAllProvidersFailedError,
    AIProviderConfigError,
    AIProviderManager,
    AIProviderResponseError,
    ProviderConfig,
)


@pytest.mark.asyncio
async def test_failover_switches_to_secondary_on_timeout():
    manager = AIProviderManager(total_deadline=3.0)
    p1 = ProviderConfig(
        id="primary",
        base_url="http://p1",
        api_key="k1",
        model="m1",
        timeout=0.5,
    )
    p2 = ProviderConfig(
        id="secondary",
        base_url="http://p2",
        api_key="k2",
        model="m2",
        timeout=0.5,
    )

    async def mock_call(provider, payload, timeout):
        if provider.id == "primary":
            await asyncio.sleep(timeout + 0.1)
            raise TimeoutError("p1 timeout")
        return {"result": 42}

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        res = await manager.dispatch_request(
            payload={"prompt": "solve"}, providers=[p1, p2]
        )
        assert res == {"result": 42}


@pytest.mark.asyncio
async def test_auth_error_aborts_immediately_without_failover():
    manager = AIProviderManager(total_deadline=5.0)
    p1 = ProviderConfig(
        id="primary",
        base_url="http://p1",
        api_key="bad_key",
        model="m1",
        timeout=1.0,
    )
    p2 = ProviderConfig(
        id="secondary",
        base_url="http://p2",
        api_key="k2",
        model="m2",
        timeout=1.0,
    )

    async def mock_call(provider, payload, timeout):
        if provider.id == "primary":
            raise ValueError("HTTP 401 Unauthorized: Invalid API Key")
        return {"result": 42}

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        with pytest.raises(ValueError) as exc_info:
            await manager.dispatch_request(payload={}, providers=[p1, p2])
        assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_all_providers_failing_raises_all_providers_failed_error():
    manager = AIProviderManager(total_deadline=2.0)
    p1 = ProviderConfig(
        id="p1", base_url="http://p1", api_key="k1", model="m1", timeout=0.2
    )

    async def mock_call(provider, payload, timeout):
        raise RuntimeError("Service Unavailable 503")

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        with pytest.raises(AIAllProvidersFailedError):
            await manager.dispatch_request(payload={}, providers=[p1])


class _FakeNonJsonResponse:
    status_code = 200
    text = "<html>gateway login page</html>"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        raise json.JSONDecodeError("Expecting value", self.text, 0)


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, *args, **kwargs):
        return _FakeNonJsonResponse()


@pytest.mark.asyncio
async def test_non_json_200_maps_to_retryable_response_error():
    """200 但响应体非 JSON 必须映射为可重试的 AIProviderResponseError（而非配置异常）。"""
    manager = AIProviderManager(total_deadline=5.0)
    provider = ProviderConfig(
        id="primary", base_url="http://p1", api_key="k1", model="m1", timeout=1.0
    )
    with patch("tg_signer.core.ai_failover.httpx.AsyncClient", _FakeAsyncClient):
        with pytest.raises(AIProviderResponseError):
            await manager._call_single_provider(
                provider, {"prompt": "solve"}, timeout=1.0
            )


@pytest.mark.asyncio
async def test_non_json_200_fails_over_instead_of_aborting():
    """主节点抛 AIProviderResponseError 时，dispatch_request 必须降级到下一节点而非中断。"""
    manager = AIProviderManager(total_deadline=5.0)
    p1 = ProviderConfig(
        id="primary", base_url="http://p1", api_key="k1", model="m1", timeout=1.0
    )
    p2 = ProviderConfig(
        id="secondary", base_url="http://p2", api_key="k2", model="m2", timeout=1.0
    )

    async def mock_call(provider, payload, timeout):
        if provider.id == "primary":
            raise AIProviderResponseError("HTTP 200 响应体非 JSON")
        return {"result": 42}

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        res = await manager.dispatch_request(
            payload={"prompt": "solve"}, providers=[p1, p2]
        )
        assert res == {"result": 42}


@pytest.mark.asyncio
async def test_config_error_does_not_abort_when_abort_disabled():
    """abort_on_config_error=False 时，配置类错误（401/404）仅记录并继续下一节点。"""
    manager = AIProviderManager(total_deadline=5.0)
    p1 = ProviderConfig(
        id="primary", base_url="http://p1", api_key="bad", model="m1", timeout=1.0
    )
    p2 = ProviderConfig(
        id="secondary", base_url="http://p2", api_key="k2", model="m2", timeout=1.0
    )

    async def mock_call(provider, payload, timeout):
        if provider.id == "primary":
            raise AIProviderConfigError("HTTP 401 Unauthorized")
        return {"result": 42}

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        res = await manager.dispatch_request(
            payload={}, providers=[p1, p2], abort_on_config_error=False
        )
        assert res == {"result": 42}
    # 默认仍中断容灾，保持既有权重
    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        with pytest.raises(AIProviderConfigError):
            await manager.dispatch_request(payload={}, providers=[p1, p2])


@pytest.mark.asyncio
async def test_provider_model_is_merged_into_payload():
    manager = AIProviderManager(total_deadline=5.0)
    provider = ProviderConfig(
        id="p", base_url="http://p", api_key="k", model="chosen-model", timeout=1.0
    )
    captured = []

    async def mock_call(p, payload, timeout):
        captured.append(payload)
        return {"ok": True}

    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        await manager.dispatch_request(payload={"prompt": "x"}, providers=[provider])

    assert captured and captured[0]["model"] == "chosen-model"
    # 调用方显式传入的 model 不应被覆盖
    captured.clear()
    with patch.object(manager, "_call_single_provider", side_effect=mock_call):
        await manager.dispatch_request(
            payload={"prompt": "x", "model": "caller-model"}, providers=[provider]
        )
    assert captured[0]["model"] == "caller-model"


@pytest.mark.asyncio
async def test_empty_providers_raises_clear_error():
    manager = AIProviderManager(total_deadline=5.0)
    with pytest.raises(AIAllProvidersFailedError):
        await manager.dispatch_request(payload={}, providers=[])
