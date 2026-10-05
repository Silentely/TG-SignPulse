import asyncio
from unittest.mock import patch

import pytest

from backend.services.ai_provider_manager import (
    AIAllProvidersFailedError,
    AIProviderManager,
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
