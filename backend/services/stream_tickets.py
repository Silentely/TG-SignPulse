"""SSE / WebSocket 的短期一次性接入票据。

浏览器 `EventSource` 与 `WebSocket` 都无法设置 `Authorization` 头，历史上只能把
长效 JWT 塞进查询串。URL 会进入访问日志、反代日志、浏览器历史与 `Referer`，
而 JWT 默认有效期 12 小时——一条被记录的 URL 等于长期可用的凭证。

改为两段式：客户端先用 `Authorization: Bearer` 换一张短期、一次性、按用途与
资源隔离的随机票据，再用票据建流。票据本身不含任何用户信息（不可解码），
生命周期只有数十秒且兑换后立即作废，泄露窗口与可重放性都降到最低。

存储为进程内 `TTLCache`：与 `sign_history_events` 总线一致，SSE 本就是进程内
广播，多 worker 部署下票据同样不跨进程共享。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Optional

from backend.utils.cache import TTLCache
from tg_signer.utils import read_positive_float_env, read_positive_int_env

# 票据有效期（秒）：只需覆盖「换票 → 建流」这一步，取稍宽的值容忍慢网络与重试
TICKET_TTL_SECONDS = read_positive_float_env("STREAM_TICKET_TTL_SECONDS", 60.0, 60.0)
# 同时在途票据上限：正常一次页面加载只需 1~2 张，上限用于兜底防异常堆积
TICKET_MAX_ENTRIES = read_positive_int_env("STREAM_TICKET_MAX_ENTRIES", 256, 256)

# 票据用途：换票时声明，兑换时校验，避免一张票被拿去连别的流
PURPOSE_SIGN_HISTORY_SSE = "sign_history_sse"
PURPOSE_TASK_RUN_WS = "task_run_ws"


@dataclass(frozen=True)
class StreamTicket:
    """已兑换票据对应的主体信息。"""

    user_id: int
    username: str


class StreamTicketStore:
    """短期一次性票据的签发与兑换。"""

    def __init__(
        self,
        ttl: float = TICKET_TTL_SECONDS,
        max_entries: int = TICKET_MAX_ENTRIES,
    ) -> None:
        # value 存 StreamTicket；TTL 到期后 pop 视为未命中
        self._tickets: TTLCache[StreamTicket] = TTLCache(maxsize=max_entries, ttl=ttl)

    def issue(self, user_id: int, username: str, purpose: str, resource: str = "") -> str:
        """签发一张绑定用途与资源的票据。

        purpose / resource 会编码进 key，兑换时不一致即视为无效——
        这样票据无法被挪用到另一条流上，也不需要额外存一份绑定关系。
        """
        ticket = secrets.token_urlsafe(32)
        key = self._key(ticket, purpose, resource)
        self._tickets.set(key, StreamTicket(user_id=user_id, username=username))
        return ticket

    def consume(
        self, ticket: str, purpose: str, resource: str = ""
    ) -> Optional[StreamTicket]:
        """兑换票据：一次性取出，命中后立即作废。"""
        if not ticket or not str(ticket).strip():
            return None
        key = self._key(str(ticket).strip(), purpose, resource)
        return self._tickets.pop(key)

    def clear(self) -> int:
        """清空所有票据，返回清除条数（供测试与运维复位使用）。"""
        return self._tickets.clear()

    @staticmethod
    def _key(ticket: str, purpose: str, resource: str) -> str:
        return f"{purpose}|{resource}|{ticket}"


_store: Optional[StreamTicketStore] = None
_store_lock = threading.Lock()


def get_stream_ticket_store() -> StreamTicketStore:
    """获取进程内票据存储单例（双重检查锁定保证线程安全）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = StreamTicketStore()
    return _store
