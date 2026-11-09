"""Telegram peer/access_hash 恢复。

Pyrogram 的 session string（以及它对应的 MemoryStorage）只保存授权信息
（dc_id / auth_key / user_id），不保存 peer 的 access_hash。
切换成 string session / in_memory 之后：
* get_chat(数字 id) 只有在本地 peer 存储里已经有该会话时才工作；
* 对用户 / 机器人会话会返回 PEER_ID_INVALID / USER_ID_INVALID；
* 对频道会退化成 channels.GetChannels(access_hash=0)，返回 CHANNEL_INVALID。

本模块提供多级解析流程：
1. 直接解析（peer 已在存储里时最快）；
2. 拉取最近会话 get_dialogs() 预热（pyrogram 内部将 peer/access_hash 写回本地存储），再重试；
3. 走 get_users()（部分版本的用户会话只在这个接口里落存储）；
4. 用显式或缓存的 username 解析；
5. 最后对历史错误 ID 做形态转换（如缺少 -100 前缀），必须放在预热之后。
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger("tg-signer.peer")

DEFAULT_DIALOG_LIMIT = 500
_WARM_FLAG = "_tg_signpulse_peers_warmed"


class PeerResolveError(RuntimeError):
    """所有解析方式都失败。"""

    def __init__(self, chat_id: Any, attempts: List[Tuple[str, BaseException]]):
        self.chat_id = chat_id
        self.attempts = attempts
        tried = "；".join(
            f"{label} -> {type(err).__name__}: {err}" for label, err in attempts[-6:]
        )
        super().__init__(
            f"无法解析 chat_id={chat_id}：当前 Session 里没有它的 peer/access_hash。"
            f"已尝试：{tried}。"
            "处理办法：在面板刷新该账号的对话列表后重试；"
            "仍然失败说明该会话已不在账号的对话中，请用 @username 重新添加会话。"
        )


@dataclass
class PeerResolution:
    chat_id: int
    chat: Any
    method: str
    dialogs_scanned: int = 0


async def _attempt(
    label: str,
    factory: Callable[[], Any],
    attempts: List[Tuple[str, BaseException]],
) -> Any:
    try:
        res = factory()
        if inspect.isawaitable(res):
            return await res
        return res
    except BaseException as exc:  # noqa: BLE001 - 记录后继续尝试其他方式
        attempts.append((label, exc))
        return None


async def warm_peer_cache(
    client: Any,
    limit: int = DEFAULT_DIALOG_LIMIT,
    attempts: Optional[List[Tuple[str, BaseException]]] = None,
) -> int:
    """拉取最近会话，让 pyrogram 把 peer/access_hash 写回本地存储。

    每个 client 实例只做一次（由 ``_WARM_FLAG`` 标记），避免每次预热都翻会话。
    """
    if getattr(client, _WARM_FLAG, False):
        return 0

    fetched = 0
    try:
        dialogs = client.get_dialogs(limit=limit)
        if hasattr(dialogs, "__aiter__"):
            async for _dialog in dialogs:
                fetched += 1
        elif inspect.isawaitable(dialogs):
            res = await dialogs
            fetched = len(res) if isinstance(res, (list, tuple)) else 0
        elif hasattr(dialogs, "__iter__"):
            for _dialog in dialogs:
                fetched += 1
    except BaseException as exc:  # noqa: BLE001 - 预热失败不致命，继续其他方式
        logger.warning(
            "预热对话列表失败（limit=%s）：%s: %s", limit, type(exc).__name__, exc
        )
        if attempts is not None:
            attempts.append((f"预热对话列表(limit={limit})", exc))
    finally:
        setattr(client, _WARM_FLAG, True)

    logger.info("peer 预热完成：扫描 %s 个会话（limit=%s）", fetched, limit)
    return fetched


def candidate_ids(chat_id: int) -> List[int]:
    """历史配置里 chat_id 可能缺 `-100` 前缀或丢了负号，这里给出候选形态。"""
    candidates: List[int] = []
    if chat_id > 0:
        candidates.append(int(f"-100{chat_id}"))
        candidates.append(-chat_id)
    elif not str(chat_id).startswith("-100"):
        candidates.append(int(f"-100{abs(chat_id)}"))
    return [c for c in candidates if c != chat_id]


async def resolve_peer_id(
    client: Any,
    chat_id: Any,
    name: Optional[str] = None,
    username: Optional[str] = None,
    dialog_limit: int = DEFAULT_DIALOG_LIMIT,
    cache_lookup: Optional[Callable[[int, Optional[str]], Optional[dict]]] = None,
) -> PeerResolution:
    """把配置里的 chat_id 解析成当前 Session 可用的 peer id。

    参数:
        client: pyrogram Client（已连接）。
        chat_id: int，或 ``@username`` / ``t.me/xxx`` 形式的字符串。
        name: 任务里配置的会话名，用于模糊匹配聊天缓存。
        username: 显式给出的 username，优先级高于缓存。
        dialog_limit: 预热时扫描的会话数量。
        cache_lookup: ``(chat_id, name) -> {"id":..., "username":...}`` 的回调查询缓存。

    异常:
        PeerResolveError: 全部方式都失败。
    """
    attempts: List[Tuple[str, BaseException]] = []

    if isinstance(chat_id, str):
        try:
            chat_id = int(chat_id)
        except ValueError:
            pass

    if not isinstance(chat_id, int):
        chat = await _attempt(
            f"按用户名解析 {chat_id}", lambda: client.get_chat(chat_id), attempts
        )
        if chat is not None:
            return PeerResolution(int(chat.id), chat, "username")
        raise PeerResolveError(chat_id, attempts)

    # 1. 直接解析
    chat = await _attempt(
        f"直接解析 {chat_id}", lambda: client.get_chat(chat_id), attempts
    )
    if chat is not None:
        return PeerResolution(int(chat.id), chat, "direct")

    # 2. 预热对话列表后重试（修复 string session 丢 peer 的核心步骤）
    dialogs_scanned = await warm_peer_cache(client, dialog_limit, attempts)
    chat = await _attempt(
        f"预热后解析 {chat_id}", lambda: client.get_chat(chat_id), attempts
    )
    if chat is not None:
        return PeerResolution(int(chat.id), chat, "dialog-warm", dialogs_scanned)

    # 3. users.GetUsers（用户 / 机器人会话）
    if chat_id > 0:
        users = await _attempt("get_users", lambda: client.get_users(chat_id), attempts)
        if users:
            chat = await _attempt(
                f"get_users 后解析 {chat_id}",
                lambda: client.get_chat(chat_id),
                attempts,
            )
            if chat is not None:
                return PeerResolution(int(chat.id), chat, "get_users", dialogs_scanned)

    # 4. 显式 username 或聊天缓存里的 username
    cached_entry: Optional[dict] = None
    if not username and cache_lookup is not None:
        try:
            cached_entry = cache_lookup(chat_id, name)
        except Exception:  # noqa: BLE001 - 缓存查询失败不影响主流程
            cached_entry = None
    if not username and cached_entry:
        cached_username = cached_entry.get("username")
        if isinstance(cached_username, str) and cached_username.strip():
            username = cached_username.strip()

    if username:
        chat = await _attempt(
            f"按缓存用户名 @{username.lstrip('@')} 解析",
            lambda: client.get_chat(username),
            attempts,
        )
        if chat is not None:
            return PeerResolution(int(chat.id), chat, "username-hint", dialogs_scanned)

    # 5. 历史错误 ID 的形态转换（必须在预热之后）
    for candidate in candidate_ids(chat_id):
        chat = await _attempt(
            f"候选 id {candidate}",
            lambda c=candidate: client.get_chat(c),
            attempts,
        )
        if chat is not None:
            return PeerResolution(
                int(chat.id), chat, f"id-variant:{candidate}", dialogs_scanned
            )

    raise PeerResolveError(chat_id, attempts)
