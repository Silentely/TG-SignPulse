"""TG-SignPulse Community Plugin: Telegram Mini App Claim.

自动获取 Telegram 小程序签到凭证并完成每日打卡领奖，无需手动打开小程序页面。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from tg_signer.core.plugins import (
    PluginContext,
    PluginFloodWaitError,
    PluginRegistry,
)

VERSION = "1.0.0"
AUTHOR = "TG-Community"

CLAIM_URL_INVALID = "CLAIM_URL_INVALID"
CLAIM_URL_SCHEME_FORBIDDEN = "CLAIM_URL_SCHEME_FORBIDDEN"
CLAIM_URL_PRIVATE_ADDRESS = "CLAIM_URL_PRIVATE_ADDRESS"
CLAIM_RESPONSE_INVALID = "CLAIM_RESPONSE_INVALID"
CLAIM_RESPONSE_TOO_LARGE = "response_too_large"
MAX_CLAIM_RESPONSE_BYTES = 1024 * 1024
MAX_CLAIM_FIELD_CHARS = 500
MAX_CLAIM_RESULT_CHARS = 4096
CLAIM_RESULT_FIELDS = frozenset(
    {"success", "code", "message", "msg", "error", "reward", "points", "status"}
)
CLAIM_SENSITIVE_KEY_PARTS = (
    "token",
    "cookie",
    "secret",
    "password",
    "password",
    "authorization",
    "apihash",
)


class ClaimUrlError(ValueError):
    """Raised when the configured claim endpoint violates the URL policy."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ClaimResponseError(ValueError):
    """Raised when the claim endpoint does not return the documented shape."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_sensitive_claim_key(key: str) -> bool:
    normalized = key.replace("_", "").replace("-", "").lower()
    return any(part in normalized for part in CLAIM_SENSITIVE_KEY_PARTS)


def sanitize_claim_result(response: Any) -> Dict[str, Any]:
    """Keep only useful result fields and redact/truncate returned data."""
    if not isinstance(response, dict):
        return {"error": "invalid response"}

    result: Dict[str, Any] = {}
    for raw_key, value in response.items():
        key = str(raw_key)
        if _is_sensitive_claim_key(key):
            result[key] = "***"
            continue
        if key not in CLAIM_RESULT_FIELDS:
            continue
        if isinstance(value, str):
            result[key] = value[:MAX_CLAIM_FIELD_CHARS]
        elif isinstance(value, (bool, int, float)) or value is None:
            result[key] = value
        else:
            result[key] = str(value)[:MAX_CLAIM_FIELD_CHARS]

    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_CLAIM_RESULT_CHARS:
        result["message"] = str(result.get("message", ""))[:256]
        result["error"] = str(result.get("error", ""))[:256]
        result["msg"] = str(result.get("msg", ""))[:256]
    return result


def validate_claim_response(response: Any) -> Dict[str, Any]:
    """Require a JSON object with an explicit boolean success field."""
    if not isinstance(response, dict) or not response or "raw" in response:
        raise ClaimResponseError(
            CLAIM_RESPONSE_INVALID,
            "invalid_json: claim response must be a non-empty JSON object",
        )
    if "success" not in response or not isinstance(response["success"], bool):
        raise ClaimResponseError(
            CLAIM_RESPONSE_INVALID,
            "missing_success: claim response must contain success=true",
        )
    return response


def _is_forbidden_claim_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def validate_claim_url(url: str) -> str:
    """Validate and resolve a public HTTPS claim endpoint.

    The hostname is resolved before the request and every returned address is
    checked. Only HTTPS is allowed; private, loopback, link-local, unspecified,
    and metadata-range addresses are rejected. The worker repeats this check at
    execution time so stale configuration cannot bypass the policy.
    """
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme.lower() != "https":
        raise ClaimUrlError(
            CLAIM_URL_SCHEME_FORBIDDEN,
            "claim_url must use https://; plaintext and non-HTTP schemes are forbidden",
        )
    if not parsed.hostname or parsed.username or parsed.password:
        raise ClaimUrlError(
            CLAIM_URL_INVALID,
            "claim_url must contain a hostname without credentials",
        )
    if parsed.fragment:
        raise ClaimUrlError(CLAIM_URL_INVALID, "claim_url must not contain a fragment")

    try:
        resolved = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ClaimUrlError(
            CLAIM_URL_INVALID, "claim_url hostname could not be resolved"
        ) from exc

    addresses = {item[4][0] for item in resolved if item[4]}
    if not addresses:
        raise ClaimUrlError(
            CLAIM_URL_INVALID, "claim_url hostname resolved to no addresses"
        )
    if any(_is_forbidden_claim_ip(address) for address in addresses):
        raise ClaimUrlError(
            CLAIM_URL_PRIVATE_ADDRESS,
            "claim_url resolves to a loopback, private, link-local, metadata, or unspecified address",
        )
    return parsed.geturl()


def parse_init_data(init_data_raw: str) -> Dict[str, str]:
    """仅供内部读取字段；不做验签，不得用于重组凭证。

    .. deprecated:: 1.0.0
        该辅助函数已废弃且不在插件主流程中使用。Mini App 插件按 Telegram 官方规范对
        MTProto 签发的原始凭证执行零篡改原样透传（Zero-tamper Pass-through），
        外部服务端接口直接消费未经客户端拆解或重组的 init_data_raw；验签由宿主/服务端负责。
    """
    return dict(urllib.parse.parse_qsl(init_data_raw, keep_blank_values=True))


def _perform_http_post(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """同步发送 HTTP POST 请求，返回 JSON 结构。"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_parts = []
        total_bytes = 0
        while True:
            remaining = MAX_CLAIM_RESPONSE_BYTES - total_bytes
            chunk = resp.read(min(64 * 1024, remaining + 1))
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_CLAIM_RESPONSE_BYTES:
                raise ValueError(CLAIM_RESPONSE_TOO_LARGE)
            content_parts.append(chunk)
        content = b"".join(content_parts).decode("utf-8")
        try:
            return json.loads(content)
        except Exception:
            return {"raw": content, "status_code": resp.status}


@PluginRegistry.register(
    name="mini_app_claim",
    mode="active",
    description="自动获取 Telegram 小程序签到凭证并完成每日打卡领奖，无需手动打开小程序页面。",
    version=VERSION,
    author=AUTHOR,
    context_version=2,
    plugin_api="2.0",
    min_app_version="1.9.0",
    permissions=["web_app", "storage", "network"],
    params_schema=[
        {
            "name": "bot_peer",
            "label": "目标机器人用户名",
            "type": "string",
            "default": "",
            "required": False,
            "description": "小程序的所属机器人用户名（如 @example_bot），留空则默认使用当前任务所在的机器人会话",
        },
        {
            "name": "claim_url",
            "label": "签到请求地址",
            "type": "string",
            "default": "https://claim.example.test/v1/claim",
            "required": True,
            "description": "小程序完成签到领奖的接口网址（由抓包或项目方提供）",
        },
        {
            "name": "from_bot_menu",
            "label": "从菜单按钮启动",
            "type": "boolean",
            "default": True,
            "required": False,
            "description": "小程序是否挂载在机器人的左下角菜单按钮中（通常保持开启即可）",
        },
        {
            "name": "max_flood_wait",
            "label": "遇到限流最大等待秒数",
            "type": "number",
            "default": 300,
            "required": False,
            "description": "当操作过于频繁被 Telegram 限流时，最大允许等待的秒数，超时则中止本次任务",
        },
    ],
)
async def handle_mini_app_claim(ctx: PluginContext) -> bool:
    """执行 Telegram Mini App 自动化签到流程。"""
    bot_peer = ctx.params.get("bot_peer") or ctx.chat_id
    claim_url = str(
        ctx.params.get("claim_url", "https://claim.example.test/v1/claim")
    ).strip()
    try:
        claim_url = validate_claim_url(claim_url)
    except ClaimUrlError as exc:
        ctx.log(f"[mini_app_claim] {exc.code}: {exc}", level="ERROR")
        if ctx.storage is not None:
            try:
                await ctx.storage.set("last_claim_status", "failed")
                await ctx.storage.set("last_claim_error", f"{exc.code}: {exc}")
                await ctx.storage.set("last_claim_timestamp", int(time.time()))
            except Exception as store_exc:
                ctx.log(
                    f"[mini_app_claim] 状态持久化失败: {store_exc}", level="WARNING"
                )
        return False
    from_bot_menu = bool(ctx.params.get("from_bot_menu", True))
    max_flood_wait = int(ctx.params.get("max_flood_wait", 300))

    ctx.log(
        f"[mini_app_claim] 开始请求 WebApp 凭证: bot_peer={bot_peer}, from_bot_menu={from_bot_menu}"
    )

    # 1. 调用 request_web_view 换取 initData，若遇 FloodWait 按服务端返回秒数等待
    try:
        webview_res = await ctx.request_web_view(
            bot_peer=bot_peer,
            from_bot_menu=from_bot_menu,
            platform="android",
        )
    except PluginFloodWaitError as exc:
        wait_seconds = exc.seconds
        if wait_seconds > max_flood_wait:
            ctx.log(
                f"[mini_app_claim] 触发 Telegram FloodWait ({wait_seconds}s > {max_flood_wait}s)，超出容忍阈值，放弃重试",
                level="WARNING",
            )
            raise
        ctx.log(
            f"[mini_app_claim] 触发 Telegram FloodWait，严格按服务端秒数休眠 {wait_seconds} 秒后重试...",
            level="WARNING",
        )
        await asyncio.sleep(wait_seconds)
        webview_res = await ctx.request_web_view(
            bot_peer=bot_peer,
            from_bot_menu=from_bot_menu,
            platform="android",
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if "FloodWait" in exc_name:
            wait_seconds = getattr(exc, "value", getattr(exc, "seconds", None))
            if wait_seconds is not None and isinstance(wait_seconds, int):
                if wait_seconds > max_flood_wait:
                    ctx.log(
                        f"[mini_app_claim] 触发 FloodWait ({wait_seconds}s > {max_flood_wait}s)，超出容忍阈值，放弃重试",
                        level="WARNING",
                    )
                    raise
                ctx.log(
                    f"[mini_app_claim] 触发 FloodWait，严格按服务端秒数休眠 {wait_seconds} 秒后重试...",
                    level="WARNING",
                )
                await asyncio.sleep(wait_seconds)
                webview_res = await ctx.request_web_view(
                    bot_peer=bot_peer,
                    from_bot_menu=from_bot_menu,
                    platform="android",
                )
            else:
                raise
        else:
            raise

    init_data_raw = webview_res.get("init_data_raw")
    if not init_data_raw:
        raw_url = webview_res.get("url", "")
        if "#tgWebAppData=" in raw_url:
            fragment = raw_url.split("#", 1)[1]
            data_part = fragment.split("tgWebAppData=", 1)[1]
            if "&" in data_part:
                data_part = data_part.split("&", 1)[0]
            init_data_raw = urllib.parse.unquote(data_part)

    if not init_data_raw:
        ctx.log("[mini_app_claim] 未能解析到有效的 init_data_raw 凭证", level="ERROR")
        return False

    ctx.log(
        f"[mini_app_claim] 凭证获取成功，长度 {len(init_data_raw)} 字节，执行零篡改透传"
    )

    # 2. 原样透传调用目标签到接口
    # 契约说明（P2）：
    # 在 Telegram Mini App 规范中，HMAC-SHA256 签名校验由目标服务端（Bot 后端）执行，
    # 插件客户端严格保持「零篡改原样透传」（zero-tamper pass-through）。
    # 测试与服务契约验证通过模拟服务端完成，插件本身禁止二次计算或修改 hash/auth_date。
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"tma {init_data_raw}",
        "X-Telegram-Init-Data": init_data_raw,
        "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    }
    payload = {
        "init_data": init_data_raw,
    }

    try:
        resp_data = await asyncio.to_thread(
            _perform_http_post,
            claim_url,
            payload,
            headers,
        )
    except Exception as exc:
        ctx.log(f"[mini_app_claim] 签到接口请求失败: {exc}", level="ERROR")
        if ctx.storage is not None:
            try:
                await ctx.storage.set("last_claim_status", "failed")
                await ctx.storage.set("last_claim_error", str(exc))
                await ctx.storage.set("last_claim_timestamp", int(time.time()))
            except Exception as store_exc:
                ctx.log(
                    f"[mini_app_claim] 状态持久化失败: {store_exc}", level="WARNING"
                )
        return False

    try:
        resp_data = validate_claim_response(resp_data)
    except ClaimResponseError as exc:
        ctx.log(f"[mini_app_claim] {exc.code}: {exc}", level="WARNING")
        if ctx.storage is not None:
            try:
                await ctx.storage.set("last_claim_status", "failed")
                await ctx.storage.set("last_claim_error", str(exc))
                await ctx.storage.set("last_claim_timestamp", int(time.time()))
            except Exception as store_exc:
                ctx.log(
                    f"[mini_app_claim] 状态持久化失败: {store_exc}", level="WARNING"
                )
        return False

    safe_resp_data = sanitize_claim_result(resp_data)

    # 业务返回校验 (P0-3)
    code = resp_data.get("code") if isinstance(resp_data, dict) else None
    success_field = resp_data.get("success") if isinstance(resp_data, dict) else None

    if (code is not None and code != 0) or success_field is False:
        err_msg = (
            (
                safe_resp_data.get("message")
                if isinstance(safe_resp_data, dict)
                else None
            )
            or (safe_resp_data.get("msg") if isinstance(safe_resp_data, dict) else None)
            or (
                safe_resp_data.get("error")
                if isinstance(safe_resp_data, dict)
                else None
            )
            or f"Business checkin failed with code {code}"
        )
        ctx.log(f"[mini_app_claim] 签到业务失败: {err_msg}", level="WARNING")
        if ctx.storage is not None:
            try:
                await ctx.storage.set("last_claim_status", "failed")
                await ctx.storage.set("last_claim_error", str(err_msg))
                await ctx.storage.set("last_claim_result", safe_resp_data)
                await ctx.storage.set("last_claim_timestamp", int(time.time()))
            except Exception as store_exc:
                ctx.log(
                    f"[mini_app_claim] 状态持久化失败: {store_exc}", level="WARNING"
                )
        return False

    # 3. 结果落库持久化 (P1-6: 状态落库为最佳努力，落库失败不影响签到成功判定)
    ctx.log(f"[mini_app_claim] 签到接口响应成功: {safe_resp_data}")
    if ctx.storage is not None:
        try:
            await ctx.storage.set("last_claim_status", "success")
            await ctx.storage.set("last_claim_result", safe_resp_data)
            await ctx.storage.set("last_claim_timestamp", int(time.time()))
        except Exception as store_exc:
            ctx.log(
                f"[mini_app_claim] 签到成功但状态持久化失败（已降级）: {store_exc}",
                level="WARNING",
            )

    return True
