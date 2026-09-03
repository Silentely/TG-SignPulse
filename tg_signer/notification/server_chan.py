import asyncio
import re

from httpx import AsyncClient

# Server酱推送共享客户端：关键词命中推送是热路径，
# 每次新建 AsyncClient 会重复 TCP+TLS 握手；按事件循环缓存复用连接。
_SC_HEADERS = {"Content-Type": "application/json;charset=utf-8"}
_SC_TIMEOUT = 10
_sc_client = None
_sc_loop = None


def _get_sc_client() -> AsyncClient:
    global _sc_client, _sc_loop
    loop = asyncio.get_running_loop()
    client = _sc_client
    if client is None or getattr(client, "is_closed", True) or _sc_loop is not loop:
        client = AsyncClient(headers=_SC_HEADERS, timeout=_SC_TIMEOUT)
        _sc_client = client
        _sc_loop = loop
    return client


async def close_sc_client() -> None:
    global _sc_client, _sc_loop
    client = _sc_client
    _sc_client = None
    _sc_loop = None
    if client and not getattr(client, "is_closed", True):
        await client.aclose()


async def sc_send(sendkey, title, desp="", options=None):
    key = str(sendkey or "").strip()
    if not key:
        raise ValueError("sendkey cannot be empty")
    safe_title = str(title or "").strip()[:256] or "TG-SignPulse Notification"
    safe_options = options if isinstance(options, dict) else {}

    # 判断 sendkey 是否以 'sctp' 开头，并提取数字构造 URL
    if key.startswith("sctp"):
        match = re.match(r"sctp(\d+)t", key)
        if match:
            num = match.group(1)
            url = f"https://{num}.push.ft07.com/send/{key}.send"
        else:
            raise ValueError("Invalid sendkey format for sctp")
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    params = {"title": safe_title, "desp": desp, **safe_options}
    client = _get_sc_client()
    response = await client.post(url, json=params)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        # 非 JSON 响应（如网关错误页）：返回原始文本，由上层告警而非裸异常
        return {"raw": response.text}
