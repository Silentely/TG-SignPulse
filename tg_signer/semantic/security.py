from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import urllib.parse
from typing import Any

from tg_signer.semantic.models import DecisionRequest

# 超长截断阈值（字节/字符）
MAX_STATE_CHARS: int = 4096
MAX_FIELD_CHARS: int = 2048

OFFICIAL_WHITELIST_HOSTS = frozenset(
    {"api.typesafe.ai", "api.example.com", "example.com"}
)


def is_ip_private_or_restricted(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def validate_ssrf_and_host(
    url: str,
    *,
    is_saved_key: bool = False,
    custom_allowed_hosts: set[str] | None = None,
) -> tuple[bool, str]:
    """校验目标 URL 是否存在 SSRF 风险，以及是否允许发送已保存密钥。

    安全策略：
    1. 必须使用 http 或 https 协议；
    2. 禁止向内网/保留 IP（127.0.0.1, 10.x, 172.16.x, 192.168.x, 169.254.x, ::1 等）发送请求；
    3. 禁止向云厂商元数据主机（如 169.254.169.254, metadata.google.internal, instance-data）发送请求；
    4. 禁止向 localhost 及 *.localhost 发送请求；
    5. 若使用已保存的 key（is_saved_key=True），目标 host 必须属于白名单，禁止将已存 key 送往任意自定义或未知主机。
    """
    if not url or not isinstance(url, str):
        return False, "SSRF_BLOCKED: Empty or invalid URL"

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception as e:
        return False, f"SSRF_BLOCKED: Malformed URL: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return (
            False,
            f"SSRF_BLOCKED: Unsupported scheme '{parsed.scheme}'; only http and https are allowed",
        )

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "SSRF_BLOCKED: Missing host in URL"

    # 检测常见回环与元数据主机名
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or hostname.endswith(
        ".localhost"
    ):
        return (
            False,
            f"SSRF_BLOCKED: Requests to localhost or loopback '{hostname}' are forbidden",
        )

    if hostname in ("metadata.google.internal", "instance-data", "169.254.169.254"):
        return (
            False,
            f"SSRF_BLOCKED: Requests to cloud metadata endpoint '{hostname}' are forbidden",
        )

    # 如果 host 是 IP 地址，检查是否为私有/受限地址
    if is_ip_private_or_restricted(hostname):
        return (
            False,
            f"SSRF_BLOCKED: Target IP address '{hostname}' is in a private or restricted network range",
        )

    # 凭据外送面管控：已保存的 key 只允许送往白名单 host
    if is_saved_key:
        whitelist = set(OFFICIAL_WHITELIST_HOSTS)
        if custom_allowed_hosts:
            whitelist.update(h.lower() for h in custom_allowed_hosts)
        env_allowed = os.getenv("JEV_ALLOWED_HOSTS", "").strip()
        if env_allowed:
            whitelist.update(
                h.strip().lower() for h in env_allowed.split(",") if h.strip()
            )

        if hostname not in whitelist:
            return (
                False,
                f"UNTRUSTED_HOST: Saved API key cannot be forwarded to non-whitelisted host '{hostname}'. "
                f"Allowed hosts: {sorted(whitelist)}",
            )

    return True, ""


def redact_sensitive_text(text: str, key: str | None = None) -> str:
    """脱敏字符串中的密钥、Token 与认证凭据，绝不泄露 key。

    覆盖场景：
    - 精确传入的 key 及其 Base64 / URL-Safe Base64 变体
    - Bearer tokens 与 sk-* 密钥
    - {"password": "..."}、{\"password\": \"...\"} 等 JSON / Dict 格式（支持转义引号）
    - apiKey: "..."、password: hunter2 等冒号/等号赋值格式（支持无引号）
    - secret=opaque 等 query / assignment 格式
    """
    if not text:
        return ""
    result = text
    # 精确匹配传入的 api_key 及其 Base64 / URL-Safe 变体
    if key and len(key.strip()) >= 4:
        clean_k = key.strip()
        result = result.replace(clean_k, "[REDACTED]")
        try:
            b64_k = base64.b64encode(clean_k.encode()).decode()
            if b64_k in result:
                result = result.replace(b64_k, "[REDACTED]")
            url_b64_k = base64.urlsafe_b64encode(clean_k.encode()).decode().rstrip("=")
            if url_b64_k and url_b64_k in result:
                result = result.replace(url_b64_k, "[REDACTED]")
        except Exception:
            pass

    # Bearer tokens 脱敏
    result = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_\-\.]{6,}",
        r"\1[REDACTED]",
        result,
        flags=re.IGNORECASE,
    )
    # sk- 前缀密钥脱敏
    result = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[REDACTED]", result)

    # JSON/Dict 结构脱敏：支持普通引号与转义引号 ({\"password\": \"secret\"})
    def _redact_quoted(match: re.Match) -> str:
        prefix = match.group(1)
        val = match.group(2)
        m_quote = re.match(r'^(?:\\*["\'])', val)
        quote = m_quote.group(0) if m_quote else '"'
        return f"{prefix}{quote}[REDACTED]{quote}"

    result = re.sub(
        r'(?i)((?:\\*["\'])?(?:api[_-]?key|apiKey|password|passwd|token|secret|access[_-]?token|accessToken|client[_-]?secret|clientSecret)(?:\\*["\'])?\s*[:=]\s*)((?:\\*["\'])[^"\'\\]*(?:\\*["\']))',
        _redact_quoted,
        result,
    )

    # 赋值结构脱敏（支持 = 与 :，支持无引号值如 password: hunter2 或 secret=opaque）
    result = re.sub(
        r'(?i)(\b(?:api[_-]?key|apiKey|password|passwd|token|secret|access[_-]?token|accessToken|client[_-]?secret|clientSecret)\s*[:=]\s*)([^\s"\'\\,;{}]+)',
        r"\1[REDACTED]",
        result,
    )
    return result


def truncate_state_if_needed(
    state: dict[str, Any],
    max_state_chars: int = MAX_STATE_CHARS,
    max_field_chars: int = MAX_FIELD_CHARS,
) -> tuple[dict[str, Any], bool]:
    """检查并截断过长的 state 字段。

    若字段发生截断，返回 (新 state, True)，否则 (原 state, False)。
    """
    is_truncated = False

    def _truncate_val(val: Any) -> Any:
        nonlocal is_truncated
        if isinstance(val, str):
            if len(val) > max_field_chars:
                is_truncated = True
                return val[:max_field_chars] + "... [TRUNCATED]"
            return val
        elif isinstance(val, dict):
            return {k: _truncate_val(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_truncate_val(item) for item in val]
        return val

    truncated_state = _truncate_val(state)

    try:
        serialized = json.dumps(truncated_state, ensure_ascii=False)
        if len(serialized) > max_state_chars:
            is_truncated = True
    except Exception:
        pass

    return truncated_state, is_truncated


def sanitize_request(request: DecisionRequest) -> DecisionRequest:
    """对 DecisionRequest 进行超长截断与安全性标注。

    若超长则截断并标注 truncated=True。
    """
    new_state, truncated = truncate_state_if_needed(request.state)
    is_truncated = bool(request.truncated or truncated)
    if is_truncated != request.truncated or new_state != request.state:
        from dataclasses import replace

        return replace(request, state=new_state, truncated=is_truncated)
    return request
