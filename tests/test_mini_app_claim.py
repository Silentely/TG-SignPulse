"""Tests for Telegram Mini App Claim plugin and security verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from community_plugins.mini_app_claim.main import (
    handle_mini_app_claim,
    parse_init_data,
)
from tg_signer.core.plugin_storage import PluginStore
from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginStorageClient,
)


def _backend_validate_init_data(
    init_data_raw: str,
    bot_token: str,
    max_age_seconds: int = 86400,
    current_time: Optional[int] = None,
) -> dict[str, str]:
    """Simulated backend validation of Telegram Mini App initData."""
    params = parse_init_data(init_data_raw)
    auth_date_str = params.get("auth_date")
    if not auth_date_str:
        raise ValueError("Missing auth_date parameter")
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        raise ValueError("Invalid auth_date format")

    user_str = params.get("user")
    if not user_str or not user_str.strip():
        raise ValueError("Missing or empty user parameter")
    try:
        user_obj = json.loads(user_str)
    except Exception as exc:
        raise ValueError("Invalid user json payload") from exc
    if not user_obj:
        raise ValueError("Empty user json payload")

    received_hash = params.get("hash")
    if not received_hash:
        raise ValueError("Missing hash parameter")

    pairs = [
        f"{k}={v}" for k, v in sorted(params.items()) if k not in ("hash", "signature")
    ]
    data_check_string = "\n".join(pairs)

    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Invalid hash signature: HMAC mismatch")

    now = int(current_time if current_time is not None else time.time())
    if now - auth_date > max_age_seconds:
        raise ValueError("auth_date expired")

    return params


def _generate_valid_init_data(
    bot_token: str = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    auth_date: int = 1731000000,
    user_payload: dict | None = None,
    extra_fields: dict | None = None,
) -> str:
    """Helper to synthesize valid signed initData according to Telegram WebApp HMAC specification."""
    if user_payload is None:
        user_payload = {
            "id": 99887766,
            "first_name": "TestUser",
            "username": "testuser",
        }

    data: dict[str, str] = {
        "auth_date": str(auth_date),
        "query_id": "AAHd8Y0AAAAAAJ3xjQC2n9yV",
        "receiver": "123456",
        "signature": "mock_signature_from_mtproto_client",
        "user": json.dumps(user_payload, separators=(",", ":")),
    }
    if extra_fields:
        data.update(extra_fields)

    pairs = [
        f"{k}={v}" for k, v in sorted(data.items()) if k not in ("hash", "signature")
    ]
    data_check_string = "\n".join(pairs)
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    data["hash"] = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return urllib.parse.urlencode(data)


def _make_plugin_ctx(
    params: dict | None = None,
    chat_id: int = -10011223344,
    store: PluginStore | None = None,
) -> PluginContext:
    mock_app = MagicMock()
    ctx = PluginContext(
        app=mock_app,
        chat_id=chat_id,
        message=None,
        params=dict(params or {}),
        plugin_name="mini_app_claim",
        context_version=2,
    )
    if store is not None:
        ctx.storage = PluginStorageClient(
            namespace=f"test:mini_app_claim:{chat_id}",
            store=store,
        )
    return ctx


# ============================================================================
# 正向用例 (Forward Tests)
# ============================================================================


@pytest.mark.asyncio
async def test_mini_app_claim_success_flow(tmp_path):
    """Test successful mini app claim with verbatim initData passthrough and storage persistence."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
            "from_bot_menu": True,
        },
        store=store,
    )

    sample_init_data = _generate_valid_init_data()
    ctx.request_web_view = AsyncMock(
        return_value={
            "url": f"https://api.example.com/wv#tgWebAppData={sample_init_data}&tgWebAppVersion=8.0",
            "query_id": "AAHd8Y0AAAAAAJ3xjQC2n9yV",
            "init_data_raw": sample_init_data,
        }
    )

    mock_resp = {"code": 0, "message": "claimed", "reward": 50}

    with patch(
        "community_plugins.mini_app_claim.main._perform_http_post",
        return_value=mock_resp,
    ) as mock_post:
        success = await handle_mini_app_claim(ctx)

        assert success is True
        ctx.request_web_view.assert_awaited_once_with(
            bot_peer="@example_bot",
            from_bot_menu=True,
            platform="android",
        )

        mock_post.assert_called_once()
        call_url, call_payload, call_headers = mock_post.call_args[0][:3]
        assert call_url == "https://api.example.com/v1/claim"
        assert call_payload == {"init_data": sample_init_data}
        assert call_headers["Authorization"] == f"tma {sample_init_data}"
        assert call_headers["X-Telegram-Init-Data"] == sample_init_data

        status = await ctx.storage.get("last_claim_status")
        result = await ctx.storage.get("last_claim_result")
        assert status == "success"
        assert result == mock_resp


@pytest.mark.asyncio
async def test_mini_app_claim_flood_wait_exact_seconds(tmp_path):
    """Test FloodWait waits exact seconds returned by Telegram without guessing."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
            "max_flood_wait": 60,
        },
        store=store,
    )

    sample_init_data = _generate_valid_init_data()
    ctx.request_web_view = AsyncMock(
        side_effect=[
            PluginFloodWaitError(seconds=7),
            {
                "url": f"https://api.example.com/wv#tgWebAppData={sample_init_data}",
                "init_data_raw": sample_init_data,
            },
        ]
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch(
            "community_plugins.mini_app_claim.main._perform_http_post",
            return_value={"code": 0},
        ) as mock_post,
    ):
        success = await handle_mini_app_claim(ctx)

        assert success is True
        mock_sleep.assert_awaited_once_with(7)
        assert ctx.request_web_view.await_count == 2
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_mini_app_claim_flood_wait_exceeds_threshold(tmp_path):
    """Test FloodWait exceeding max threshold raises without retry or sleeping."""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "max_flood_wait": 30,
        },
        store=store,
    )

    ctx.request_web_view = AsyncMock(side_effect=PluginFloodWaitError(seconds=120))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(PluginFloodWaitError) as exc_info:
            await handle_mini_app_claim(ctx)

        assert exc_info.value.seconds == 120
        mock_sleep.assert_not_called()
        assert ctx.request_web_view.await_count == 1


# ============================================================================
# 反向用例 (Reverse & Negative Security Tests)
# ============================================================================


def test_reverse_exact_field_set_assertion():
    """精确断言解析字段集必须严格等于预期的 6 个字段，严禁使用 in 弱断言。"""
    init_data = _generate_valid_init_data()
    params = parse_init_data(init_data)
    actual_fields = sorted(params.keys())
    # 必须精确等于 list，不能用 subset 或 in
    assert actual_fields == [
        "auth_date",
        "hash",
        "query_id",
        "receiver",
        "signature",
        "user",
    ]


def test_reverse_tampered_hash_rejection():
    """断言篡改 hash 签名必定失败，无法通过 HMAC 验签。"""
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    valid_data = _generate_valid_init_data(bot_token=bot_token, auth_date=1731000000)

    # 干净地只篡改 hash 字段值，不引入任何多余参数
    params = dict(urllib.parse.parse_qsl(valid_data, keep_blank_values=True))
    params["hash"] = "deadbeef" * 8
    tampered_data = urllib.parse.urlencode(params)

    with pytest.raises(ValueError, match="Invalid hash signature: HMAC mismatch"):
        _backend_validate_init_data(
            tampered_data, bot_token=bot_token, current_time=1731000010
        )


def test_reverse_expired_auth_date():
    """断言过期的 auth_date 会被立即拒绝。"""
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    old_timestamp = 1700000000
    valid_old_data = _generate_valid_init_data(
        bot_token=bot_token, auth_date=old_timestamp
    )

    # 当前时间比 auth_date 晚 100,000 秒（超过 86,400 秒有效期）
    eval_now = old_timestamp + 100000
    with pytest.raises(ValueError, match="auth_date expired"):
        _backend_validate_init_data(
            valid_old_data,
            bot_token=bot_token,
            max_age_seconds=86400,
            current_time=eval_now,
        )


def test_reverse_empty_or_invalid_user():
    """断言空 user 或畸变 user 结构会被拦截。"""
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

    # Case A: user 为空字典
    empty_user_data = _generate_valid_init_data(bot_token=bot_token, user_payload={})
    with pytest.raises(ValueError, match="Empty user json payload"):
        _backend_validate_init_data(
            empty_user_data, bot_token=bot_token, current_time=1731000005
        )

    # Case B: user 字段缺失
    params = parse_init_data(_generate_valid_init_data(bot_token=bot_token))
    del params["user"]
    missing_user_raw = urllib.parse.urlencode(params)
    with pytest.raises(ValueError, match="Missing or empty user parameter"):
        _backend_validate_init_data(
            missing_user_raw, bot_token=bot_token, current_time=1731000005
        )


@pytest.mark.asyncio
async def test_reverse_plugin_backend_rejects_tampered_payload(tmp_path):
    """断言服务端因篡改拒绝 (HTTP 401) 时，插件记录 failed 并安全返回 False。"""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
        },
        store=store,
    )

    tampered_init_data = "query_id=fake&hash=invalid"
    ctx.request_web_view = AsyncMock(
        return_value={
            "url": "https://api.example.com/wv",
            "init_data_raw": tampered_init_data,
        }
    )

    # 模拟服务端 401 Unauthorized 异常
    with patch(
        "community_plugins.mini_app_claim.main._perform_http_post",
        side_effect=RuntimeError(
            "HTTP Error 401: Unauthorized - HMAC signature verification failed"
        ),
    ):
        success = await handle_mini_app_claim(ctx)

        assert success is False
        status = await ctx.storage.get("last_claim_status")
        err = await ctx.storage.get("last_claim_error")
        assert status == "failed"
        assert "401" in err


@pytest.mark.asyncio
async def test_claim_http_200_business_failure(tmp_path):
    """断言 HTTP 200 返回业务失败码 (code != 0) 时，插件记录 failed 并返回 False。"""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
        },
        store=store,
    )
    ctx.request_web_view = AsyncMock(
        return_value={
            "url": "https://api.example.com/wv",
            "init_data_raw": "query_id=test&hash=valid",
        }
    )

    with patch(
        "community_plugins.mini_app_claim.main._perform_http_post",
        return_value={"code": 1, "message": "already claimed today"},
    ):
        success = await handle_mini_app_claim(ctx)

        assert success is False
        status = await ctx.storage.get("last_claim_status")
        err = await ctx.storage.get("last_claim_error")
        assert status == "failed"
        assert "already claimed today" in str(err)


@pytest.mark.asyncio
async def test_claim_storage_write_failure_resilience(tmp_path):
    """断言签到成功但 storage 持久化失败时，插件保持 success=True 且不抛异常。"""
    store = PluginStore(tmp_path / "storage.db")
    ctx = _make_plugin_ctx(
        params={
            "bot_peer": "@example_bot",
            "claim_url": "https://api.example.com/v1/claim",
        },
        store=store,
    )
    ctx.request_web_view = AsyncMock(
        return_value={
            "url": "https://api.example.com/wv",
            "init_data_raw": "query_id=test&hash=valid",
        }
    )

    ctx.storage.set = AsyncMock(side_effect=IOError("Disk storage write failed"))

    with patch(
        "community_plugins.mini_app_claim.main._perform_http_post",
        return_value={"code": 0, "message": "claim success", "points": 100},
    ):
        success = await handle_mini_app_claim(ctx)
        assert success is True
