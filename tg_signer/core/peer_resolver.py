"""Telegram peer/access_hash 恢复与预热。

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
5. 最后对历史错误 ID 做形态转换（如缺少 -100 前缀），必须放在预热之后且必须严格核对目标身份。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger("tg-signer.peer")

DEFAULT_DIALOG_LIMIT = 500
_WARM_FLAG = "_tg_signpulse_peers_warmed"
_WARM_LOCK_ATTR = "_tg_signpulse_peers_warm_lock"
_GLOBAL_THREAD_LOCK = threading.Lock()


def _get_client_warm_lock(client: Any) -> asyncio.Lock:
    """获取或初始化绑定到 client 实例的 asyncio.Lock，带线程安全保护。"""
    with _GLOBAL_THREAD_LOCK:
        lock = getattr(client, _WARM_LOCK_ATTR, None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(client, _WARM_LOCK_ATTR, lock)
        return lock


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

    每个 client 实例成功预热后只做一次（由 ``_WARM_FLAG`` 标记），避免每次预热都翻会话。
    并发调用时使用异步锁保护，且只有在真正成功完成后才置位，异常路径不置位以便后续重试。
    """
    if getattr(client, _WARM_FLAG, False):
        return 0

    lock = _get_client_warm_lock(client)
    async with lock:
        # 在获取锁后二次检查，避免并发时重复执行
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
            # 只有整条预热链真正成功跑完才把 flag 置为 True
            setattr(client, _WARM_FLAG, True)
            logger.info("peer 预热完成：扫描 %s 个会话（limit=%s）", fetched, limit)
            return fetched
        except BaseException as exc:  # noqa: BLE001 - 预热失败不致命，允许下次重试
            logger.warning(
                "预热对话列表失败（limit=%s）：%s: %s", limit, type(exc).__name__, exc
            )
            if attempts is not None:
                attempts.append((f"预热对话列表(limit={limit})", exc))
            return 0


def candidate_ids(chat_id: int) -> List[int]:
    """历史配置里 chat_id 可能缺 `-100` 前缀或丢了负号，这里给出候选形态。"""
    candidates: List[int] = []
    if chat_id > 0:
        candidates.append(int(f"-100{chat_id}"))
        candidates.append(-chat_id)
    elif not str(chat_id).startswith("-100"):
        candidates.append(int(f"-100{abs(chat_id)}"))
    return [c for c in candidates if c != chat_id]


def _verify_candidate_identity(
    candidate_chat: Any,
    original_chat_id: int,
    expected_username: Optional[str] = None,
    expected_name: Optional[str] = None,
) -> bool:
    """核对形态转换后的候选 chat 是否为真正目标。

    要求：
    1. 命中后必须做身份核对（用户名 / ID 双向比对，二者至少一个能对上）；
    2. 对不上就丢弃该候选并降级，不许「猜一个最像的」；
    3. 若有预期用户名，且候选 chat 存在用户名但两者不符，必须拒绝（防冒名/误发）。
    """
    cand_id = getattr(candidate_chat, "id", None)
    if cand_id is None:
        return False

    cand_username = getattr(candidate_chat, "username", None)

    clean_expected_user = (
        expected_username.lower().lstrip("@").replace("https://t.me/", "").strip()
        if expected_username
        else None
    )
    clean_cand_user = (
        cand_username.lower().lstrip("@").strip() if cand_username else None
    )

    # 1. 用户名冲突安全检查：如果有预期用户名，且候选 chat 带有用户名，两者必须一致
    if clean_expected_user:
        if clean_cand_user and clean_cand_user != clean_expected_user:
            return False

    # 2. 用户名对上
    username_matched = False
    if (
        clean_expected_user
        and clean_cand_user
        and clean_expected_user == clean_cand_user
    ):
        username_matched = True

    # 3. ID 双向数学比对：candidate_id 必须是原 chat_id 的有效形态变体
    id_matched = False
    cand_str = str(cand_id)
    orig_abs_str = str(abs(original_chat_id))

    if cand_str.startswith("-100"):
        stripped_cand = cand_str[4:]
        if stripped_cand == orig_abs_str:
            id_matched = True
    elif abs(cand_id) == abs(original_chat_id):
        id_matched = True

    # 用户名 / ID 双向比对，二者至少一个能对上
    if username_matched:
        return True

    if id_matched:
        return True

    return False


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

    # 5. 历史错误 ID 的形态转换（必须在预热之后且必须严格核对目标身份）
    for candidate in candidate_ids(chat_id):
        chat = await _attempt(
            f"候选 id {candidate}",
            lambda c=candidate: client.get_chat(c),
            attempts,
        )
        if chat is not None:
            if _verify_candidate_identity(
                chat,
                chat_id,
                expected_username=username,
                expected_name=name,
            ):
                return PeerResolution(
                    int(chat.id), chat, f"id-variant:{candidate}", dialogs_scanned
                )
            attempts.append(
                (
                    f"候选 id {candidate} 身份核对失败",
                    RuntimeError(
                        f"候选 id {candidate} 会话身份 (username={getattr(chat, 'username', None)}, "
                        f"title={getattr(chat, 'title', None)}) 无法确认目标身份"
                    ),
                )
            )

    raise PeerResolveError(chat_id, attempts)
