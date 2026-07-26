"""
账号会话（Chat）缓存检索与 dialog 映射

从 SignTaskService 抽离的纯逻辑，便于单测；网络拉取仍由服务类负责。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("backend.sign_task_chats")


def clamp_chat_search_page(limit: int, offset: int) -> tuple[int, int]:
    """规范化分页参数。"""
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    if offset < 0:
        offset = 0
    return limit, offset


def empty_chat_search_page(*, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    limit, offset = clamp_chat_search_page(limit, offset)
    return {"items": [], "total": 0, "limit": limit, "offset": offset}


def search_chats_in_cache(
    data: Any,
    query: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    在已加载的 chats 列表中按关键词分页搜索。

    - 数字 / -100 前缀：按 id 子串匹配
    - 其它：title / username 不区分大小写包含
    """
    limit, offset = clamp_chat_search_page(limit, offset)
    if not isinstance(data, list):
        return empty_chat_search_page(limit=limit, offset=offset)

    q = (query or "").strip()
    if not q:
        total = len(data)
        return {
            "items": data[offset : offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    is_numeric = q.lstrip("-").isdigit()
    if is_numeric or q.startswith("-100"):

        def match(chat: Dict[str, Any]) -> bool:
            if not isinstance(chat, dict):
                return False
            chat_id = chat.get("id")
            if chat_id is None:
                return False
            return q in str(chat_id)

    else:
        q_lower = q.lower()

        def match(chat: Dict[str, Any]) -> bool:
            if not isinstance(chat, dict):
                return False
            title = (chat.get("title") or "").lower()
            username = (chat.get("username") or "").lower()
            return q_lower in title or q_lower in username

    filtered = [c for c in data if match(c)]
    total = len(filtered)
    return {
        "items": filtered[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def load_chats_cache_file(cache_file: Path) -> Optional[List[Dict[str, Any]]]:
    """读取 chats_cache.json；失败或非 list 返回 None。"""
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        _logger.debug("读取 chat 缓存失败 %s: %s", cache_file, exc)
        return None
    if not isinstance(data, list):
        return None
    return data


def save_chats_cache_file(cache_file: Path, chats: List[Dict[str, Any]]) -> bool:
    """写入 chats 缓存；失败返回 False。"""
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(chats, f, ensure_ascii=False, indent=2)
        return True
    except (OSError, TypeError, ValueError) as exc:
        _logger.debug("保存 chat 缓存失败 %s: %s", cache_file, exc)
        return False


def resolve_account_session_for_chats(
    account_name: str,
    *,
    session_dir: Path,
    session_mode: str,
    get_session_string,
    load_session_string_file_fn,
) -> Dict[str, Any]:
    """
    解析刷新会话列表所需的 session 参数。

    返回 dict:
      session_string, fallback_session_string, used_fallback_session, session_file
    失败抛 ValueError。
    """
    session_file = session_dir / f"{account_name}.session"
    session_string = None
    fallback_session_string = None
    used_fallback_session = False

    if session_mode == "string":
        session_string = (
            get_session_string(account_name)
            or load_session_string_file_fn(session_dir, account_name)
        )
        if not session_string:
            raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")
    else:
        fallback_session_string = (
            get_session_string(account_name)
            or load_session_string_file_fn(session_dir, account_name)
        )
        if not session_file.exists():
            if fallback_session_string:
                session_string = fallback_session_string
                used_fallback_session = True
            else:
                raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")

    return {
        "session_string": session_string,
        "fallback_session_string": fallback_session_string,
        "used_fallback_session": used_fallback_session,
        "session_file": session_file,
    }


def resolve_telegram_api_credentials(
    tg_config: Dict[str, Any],
    *,
    env_api_id: Optional[str] = None,
    env_api_hash: Optional[str] = None,
) -> tuple[int, str]:
    """解析 api_id / api_hash；无效时抛 ValueError。"""
    raw_id = env_api_id or tg_config.get("api_id")
    raw_hash = env_api_hash or tg_config.get("api_hash")
    try:
        api_id = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        api_id = None
    if isinstance(raw_hash, str):
        raw_hash = raw_hash.strip()
    if not api_id or not raw_hash:
        raise ValueError("未配置 Telegram API ID 或 API Hash")
    return api_id, str(raw_hash)


def map_pyrogram_chat(chat: Any) -> Optional[Dict[str, Any]]:
    """
    将 Pyrogram Chat 对象映射为缓存条目。
    chat 无效或缺 id 时返回 None。
    """
    if chat is None:
        return None
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        return None
    chat_type = getattr(chat, "type", None)
    type_name = chat_type.name.lower() if chat_type else "private"
    return {
        "id": chat_id,
        "title": getattr(chat, "title", None)
        or getattr(chat, "first_name", None)
        or getattr(chat, "username", None)
        or str(chat_id),
        "username": getattr(chat, "username", None),
        "type": type_name,
    }


SEARCH_GLOBAL_FALLBACK_TERMS = ("", "a", "1")


def append_mapped_chat(
    local_chats: List[Dict[str, Any]],
    chat: Any,
    *,
    seen_ids: Optional[set] = None,
) -> bool:
    """
    将 Pyrogram chat 映射并追加到列表。

    seen_ids 非空时按 id 去重；成功追加返回 True。
    """
    mapped = map_pyrogram_chat(chat)
    if mapped is None:
        return False
    chat_id = mapped.get("id")
    if seen_ids is not None:
        if chat_id in seen_ids:
            return False
        seen_ids.add(chat_id)
    local_chats.append(mapped)
    return True


def build_chat_client_kwargs(
    *,
    account_name: str,
    workdir: Path,
    api_id: int,
    api_hash: str,
    session_string: Optional[str],
    in_memory: bool,
    proxy: Any = None,
    no_updates: bool = True,
) -> Dict[str, Any]:
    """构造 get_client 刷新会话列表用的参数。"""
    return {
        "name": account_name,
        "workdir": workdir,
        "api_id": api_id,
        "api_hash": api_hash,
        "session_string": session_string,
        "in_memory": in_memory,
        "proxy": proxy,
        "no_updates": no_updates,
    }


def client_kwargs_with_fallback_session(
    client_kwargs: Dict[str, Any],
    fallback_session_string: str,
) -> Dict[str, Any]:
    """session 失效后改用 string session 重试的 kwargs。"""
    retry = dict(client_kwargs)
    retry["session_string"] = fallback_session_string
    retry["in_memory"] = True
    retry["no_updates"] = True
    return retry


# ---------------------------------------------------------------------------
# 网络拉取：刷新 Telegram dialogs 并写缓存（原 SignTaskService.refresh_account_chats）
# ---------------------------------------------------------------------------

import os
from typing import Awaitable, Callable, MutableMapping

import logging as _logging

_fetch_logger = _logging.getLogger("backend.sign_task_chats")


def is_invalid_session_error(err: Exception) -> bool:
    """判断是否为 session 失效类错误。"""
    msg = str(err)
    if not msg:
        return False
    upper = msg.upper()
    return (
        "AUTH_KEY_UNREGISTERED" in upper
        or "AUTH_KEY_INVALID" in upper
        or "SESSION_REVOKED" in upper
        or "SESSION_EXPIRED" in upper
        or "USER_DEACTIVATED" in upper
    )


async def get_account_chats_cached(
    account_name: str,
    *,
    signs_dir: Path,
    force_refresh: bool = False,
    refresh_fn: Callable[[str], Awaitable[List[Dict[str, Any]]]],
    validate_name: Callable[..., str],
) -> List[Dict[str, Any]]:
    """读缓存或调用 refresh_fn 刷新。"""
    account_name = validate_name(account_name, field_name="account_name")
    cache_file = signs_dir / account_name / "chats_cache.json"
    if not force_refresh:
        cached = load_chats_cache_file(cache_file)
        if cached is not None:
            return cached
    return await refresh_fn(account_name)


def search_account_chats_cached(
    account_name: str,
    query: str,
    *,
    signs_dir: Path,
    limit: int = 50,
    offset: int = 0,
    validate_name: Callable[..., str],
) -> Dict[str, Any]:
    """通过缓存搜索，不触发 get_dialogs。"""
    account_name = validate_name(account_name, field_name="account_name")
    cache_file = signs_dir / account_name / "chats_cache.json"
    data = load_chats_cache_file(cache_file)
    if data is None:
        return empty_chat_search_page(limit=limit, offset=offset)
    return search_chats_in_cache(data, query, limit=limit, offset=offset)


async def cleanup_invalid_session_and_chat_cache(
    account_name: str,
    *,
    signs_dir: Path,
) -> None:
    """删除账号 session 并清理 chats 缓存。"""
    try:
        from backend.services.telegram import get_telegram_service

        await get_telegram_service().delete_account(account_name)
    except Exception as e:
        _fetch_logger.debug("清理无效 Session 失败: %s", e)
    try:
        cache_file = signs_dir / account_name / "chats_cache.json"
        if cache_file.exists():
            cache_file.unlink()
    except Exception:
        pass


async def refresh_account_chats(
    account_name: str,
    *,
    signs_dir: Path,
    get_effective_proxy: Callable[[str], Optional[str]],
    account_locks: MutableMapping[str, Any],
    validate_name: Callable[..., str],
) -> List[Dict[str, Any]]:
    """
    连接 Telegram 并刷新 Chat 列表，写入 signs_dir/<account>/chats_cache.json。
    """
    from backend.core.config import get_settings
    from backend.services.config import get_config_service
    from backend.utils.account_locks import get_account_lock
    from backend.utils.proxy import build_proxy_dict
    from backend.utils.tg_session import (
        get_account_session_string,
        get_global_semaphore,
        get_session_mode,
        load_session_string_file,
    )
    from tg_signer.core import get_client

    account_name = validate_name(account_name, field_name="account_name")

    settings = get_settings()
    session_dir = settings.resolve_session_dir()
    session_mode = get_session_mode()
    session_info = resolve_account_session_for_chats(
        account_name,
        session_dir=session_dir,
        session_mode=session_mode,
        get_session_string=get_account_session_string,
        load_session_string_file_fn=load_session_string_file,
    )
    session_string = session_info["session_string"]
    fallback_session_string = session_info["fallback_session_string"]
    used_fallback_session = session_info["used_fallback_session"]

    config_service = get_config_service()
    tg_config = config_service.get_telegram_config()
    api_id, api_hash = resolve_telegram_api_credentials(
        tg_config,
        env_api_id=os.getenv("TG_API_ID"),
        env_api_hash=os.getenv("TG_API_HASH"),
    )

    proxy_dict = None
    proxy_value = get_effective_proxy(account_name)
    if proxy_value:
        proxy_dict = build_proxy_dict(proxy_value)
    client_kwargs = build_chat_client_kwargs(
        account_name=account_name,
        workdir=session_dir,
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=session_mode == "string",
        proxy=proxy_dict,
    )
    client = get_client(**client_kwargs)

    chats: List[Dict[str, Any]] = []
    logger = _fetch_logger
    try:
        if account_name not in account_locks:
            account_locks[account_name] = get_account_lock(account_name)

        account_lock = account_locks[account_name]

        async def _fetch_chats(active_client) -> List[Dict[str, Any]]:
            local_chats: List[Dict[str, Any]] = []
            async with account_lock:
                async with get_global_semaphore():
                    async with active_client:
                        await active_client.get_me()

                        try:
                            async for dialog in active_client.get_dialogs():
                                try:
                                    append_mapped_chat(
                                        local_chats,
                                        getattr(dialog, "chat", None),
                                    )
                                except Exception:
                                    continue
                        except Exception as e:
                            logger.warning(
                                "get_dialogs 失败 (已获取 %s 个): %s: %s",
                                len(local_chats),
                                type(e).__name__,
                                e,
                            )

                        if not local_chats:
                            logger.info(
                                "get_dialogs 返回空，尝试 search_global 获取会话"
                            )
                            seen_ids: set = set()
                            for term in SEARCH_GLOBAL_FALLBACK_TERMS:
                                try:
                                    async for msg in active_client.search_global(
                                        term, limit=50
                                    ):
                                        try:
                                            append_mapped_chat(
                                                local_chats,
                                                getattr(msg, "chat", None),
                                                seen_ids=seen_ids,
                                            )
                                        except Exception:
                                            continue
                                except Exception:
                                    continue

            return local_chats

        try:
            chats = await _fetch_chats(client)
        except Exception as e:
            if is_invalid_session_error(e):
                if fallback_session_string and not used_fallback_session:
                    logger.warning(
                        "Session invalid for %s, retry with session_string: %s",
                        account_name,
                        e,
                    )
                    try:
                        from tg_signer.core import close_client_by_name

                        await close_client_by_name(account_name, workdir=session_dir)
                    except Exception:
                        pass
                    used_fallback_session = True
                    client = get_client(
                        **client_kwargs_with_fallback_session(
                            client_kwargs, fallback_session_string
                        )
                    )
                    chats = await _fetch_chats(client)
                else:
                    logger.warning(
                        "Session invalid for %s: %s",
                        account_name,
                        e,
                    )
                    await cleanup_invalid_session_and_chat_cache(
                        account_name, signs_dir=signs_dir
                    )
                    raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")
            else:
                raise

        account_dir = signs_dir / account_name
        cache_file = account_dir / "chats_cache.json"
        if not save_chats_cache_file(cache_file, chats):
            logger.debug("保存 Chat 缓存失败: %s", cache_file)

        return chats

    except Exception as e:
        raise e
