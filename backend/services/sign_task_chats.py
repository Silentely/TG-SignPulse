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
