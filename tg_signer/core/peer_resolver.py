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
    except asyncio.CancelledError:
        raise
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
        except asyncio.CancelledError:
            raise
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
    1. 候选 chat 必须具备可核对的真实身份（username 必须存在；若无 username 直接拒绝，严禁单纯靠 ID 变体放行）；
    2. 若只有 ID、既无 expected_username 也无 expected_name 时，无法确认目标身份，必须拒绝；
    3. 若提供了 expected_username，必须与 candidate 的 username 完全一致，否则拒绝；
    4. 若提供了 expected_name，必须与 candidate 的 username / title / first_name 匹配，否则拒绝；
    5. candidate_id 必须是 original_chat_id 的有效数字形态变体。
    """
    cand_id = getattr(candidate_chat, "id", None)
    if cand_id is None:
        return False

    cand_username = getattr(candidate_chat, "username", None)
    cand_title = getattr(candidate_chat, "title", None)
    cand_first_name = getattr(candidate_chat, "first_name", None)

    # 1. 只有 ID、没有 username 时直接拒绝（防冒名与跨会话误发）
    if not cand_username or not str(cand_username).strip():
        logger.warning("候选 chat (id=%s) 无 username，拒绝盲目形态转换匹配", cand_id)
        return False

    clean_cand_user = str(cand_username).lower().lstrip("@").strip()

    # 2. 只有 ID、未提供任何 expected_username 或 expected_name 时，无法确认身份，必须拒绝
    if not expected_username and not expected_name:
        logger.warning(
            "缺少 expected_username 和 expected_name，无法确认候选 chat (id=%s, user=%s) 的目标身份",
            cand_id,
            clean_cand_user,
        )
        return False

    # 3. 如果提供了 expected_username，必须一致
    if expected_username:
        clean_exp_user = (
            str(expected_username)
            .lower()
            .lstrip("@")
            .replace("https://t.me/", "")
            .strip()
        )
        if clean_exp_user and clean_cand_user != clean_exp_user:
            logger.warning(
                "候选 chat username 不匹配: expected=%s, actual=%s",
                clean_exp_user,
                clean_cand_user,
            )
            return False

    # 4. 如果提供了 expected_name，必须与候选身份匹配
    if expected_name:
        clean_exp_name = str(expected_name).lower().lstrip("@").strip()
        name_matched = False
        if clean_cand_user and (
            clean_cand_user == clean_exp_name or clean_exp_name in clean_cand_user
        ):
            name_matched = True
        if cand_title and clean_exp_name in str(cand_title).lower():
            name_matched = True
        if cand_first_name and clean_exp_name in str(cand_first_name).lower():
            name_matched = True

        if not name_matched:
            logger.warning(
                "候选 chat 身份与 expected_name 不符: expected_name=%s, candidate=(user=%s, title=%s)",
                expected_name,
                cand_username,
                cand_title,
            )
            return False

    # 5. ID 变体数学校验
    cand_str = str(cand_id)
    orig_abs_str = str(abs(original_chat_id))
    id_matched = False
    if cand_str.startswith("-100"):
        stripped_cand = cand_str[4:]
        if stripped_cand == orig_abs_str:
            id_matched = True
    elif abs(cand_id) == abs(original_chat_id):
        id_matched = True

    return id_matched


async def resolve_peer_id(
    client: Any,
    chat_id: Any,
    name: Optional[str] = None,
    username: Optional[str] = None,
    expected_name: Optional[str] = None,
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
                expected_name=expected_name or name,
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
