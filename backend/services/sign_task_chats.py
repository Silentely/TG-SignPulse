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
