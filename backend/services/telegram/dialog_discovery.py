"""Telegram 对话文件夹（Dialog Filters）与论坛话题（Forum Topics）发现服务。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from pyrogram import raw, utils

from backend.utils.account_locks import (
    AccountLockTimeout,
    acquire_account_lock_with_timeout,
)
from tg_signer.compat import safe_get_forum_topics

logger = logging.getLogger("backend.telegram.dialog_discovery")


def extract_peer_id(peer: Any) -> Optional[Union[int, str]]:
    """从 InputPeer 或 Mock 对象中安全解析统一的 peer_id。"""
    if isinstance(peer, (int, str)):
        return peer
    try:
        return utils.get_peer_id(peer)
    except Exception:
        pass
    if hasattr(peer, "channel_id"):
        return utils.get_channel_id(peer.channel_id)
    if hasattr(peer, "chat_id"):
        return -abs(peer.chat_id)
    if hasattr(peer, "user_id"):
        return peer.user_id
    if hasattr(peer, "id"):
        return peer.id
    return None


def extract_peer_ids(peer_list: Any) -> List[Union[int, str]]:
    """批量解析 peer_id 列表，过滤空值。"""
    if not peer_list or not isinstance(peer_list, (list, tuple)):
        return []
    result = []
    for p in peer_list:
        pid = extract_peer_id(p)
        if pid is not None:
            result.append(pid)
    return result


def _extract_title(title_obj: Any) -> str:
    """提取 TextWithEntities 或普通字符串中的文本。"""
    if not title_obj:
        return ""
    if isinstance(title_obj, str):
        return title_obj
    if hasattr(title_obj, "text"):
        return str(title_obj.text or "")
    return str(title_obj)


def parse_dialog_filter(filter_item: Any) -> Optional[Dict[str, Any]]:
    """
    解析单个 DialogFilter 变体为统一的安全字典结构。
    支持 DialogFilterDefault, DialogFilterChatlist, DialogFilter 以及字典或通用对象。
    """
    if filter_item is None:
        return None

    if isinstance(filter_item, dict):
        return {
            "id": filter_item.get("id", "all" if filter_item.get("title") == "全部" else 0),
            "title": filter_item.get("title", ""),
            "emoticon": filter_item.get("emoticon"),
            "pinned_peers": filter_item.get("pinned_peers", []),
            "include_peers": filter_item.get("include_peers", []),
            "exclude_peers": filter_item.get("exclude_peers", []),
        }

    item_type_name = type(filter_item).__name__

    # 1. DialogFilterDefault (全对话默认过滤器，无 id)
    is_default = (
        isinstance(
            filter_item,
            getattr(getattr(raw, "types", None), "DialogFilterDefault", ()),
        )
        or item_type_name == "DialogFilterDefault"
        or getattr(filter_item, "id", None) is None
    )
    if is_default:
        return {
            "id": "all",
            "title": "全部",
            "emoticon": None,
            "pinned_peers": [],
            "include_peers": [],
            "exclude_peers": [],
        }

    # 2. DialogFilterChatlist
    is_chatlist = (
        isinstance(
            filter_item,
            getattr(getattr(raw, "types", None), "DialogFilterChatlist", ()),
        )
        or item_type_name == "DialogFilterChatlist"
    )
    if is_chatlist:
        return {
            "id": getattr(filter_item, "id", None),
            "title": _extract_title(getattr(filter_item, "title", "")),
            "emoticon": getattr(filter_item, "emoticon", None),
            "pinned_peers": extract_peer_ids(getattr(filter_item, "pinned_peers", [])),
            "include_peers": extract_peer_ids(getattr(filter_item, "include_peers", [])),
            "exclude_peers": [],
        }

    # 3. DialogFilter (常规)
    return {
        "id": getattr(filter_item, "id", None),
        "title": _extract_title(getattr(filter_item, "title", "")),
        "emoticon": getattr(filter_item, "emoticon", None),
        "pinned_peers": extract_peer_ids(getattr(filter_item, "pinned_peers", [])),
        "include_peers": extract_peer_ids(getattr(filter_item, "include_peers", [])),
        "exclude_peers": extract_peer_ids(getattr(filter_item, "exclude_peers", [])),
    }


def parse_dialog_filters(raw_filters: Any) -> List[Dict[str, Any]]:
    """批量解析 DialogFilter 列表，单条解析异常时跳过并记录警告。"""
    if raw_filters is None:
        return []
    if not isinstance(raw_filters, (list, tuple)):
        raw_filters = getattr(raw_filters, "filters", []) or []

    parsed_list: List[Dict[str, Any]] = []
    for item in raw_filters:
        try:
            parsed = parse_dialog_filter(item)
            if parsed is not None:
                parsed_list.append(parsed)
        except Exception as exc:
            logger.warning(
                "解析单个 DialogFilter 发生异常，已跳过: %r: %s",
                item,
                exc,
                exc_info=True,
            )
    return parsed_list


class TelegramDialogDiscoveryMixin:
    """TelegramService 对话文件夹与论坛话题发现能力混入类。"""

    def _normalize_account_name(self, account_name: str) -> str:
        from backend.utils.names import validate_storage_name

        return validate_storage_name(account_name, field_name="account_name")

    def account_exists(self, account_name: str) -> bool:
        return False

    def _build_account_client(self, account_name: str, no_updates: bool = True):
        raise NotImplementedError

    async def verify_account_proxy(
        self, account_name: str, proxy_dict: Optional[dict] = None
    ) -> None:
        pass

    async def list_account_folders(
        self, account_name: str, timeout_seconds: float = 12.0
    ) -> List[Dict[str, Any]]:
        """
        列出指定账号的 Telegram 对话文件夹（Dialog Filters）。
        前置调用 verify_account_proxy，并在账号锁保护下调用 GetDialogFilters。
        """
        account_name = self._normalize_account_name(account_name)
        if not self.account_exists(account_name):
            raise ValueError("账号不存在")

        client, proxy_dict = self._build_account_client(account_name, no_updates=True)
        await self.verify_account_proxy(account_name, proxy_dict)

        timeout_seconds = max(1.0, min(float(timeout_seconds or 12.0), 30.0))
        need_disconnect = False
        try:
            async with acquire_account_lock_with_timeout(
                account_name, timeout=timeout_seconds
            ):
                if not getattr(client, "is_connected", False):
                    await client.connect()
                    need_disconnect = True

                result = await asyncio.wait_for(
                    client.invoke(raw.functions.messages.GetDialogFilters()),
                    timeout=timeout_seconds,
                )
                raw_filters = getattr(result, "filters", None)
                if raw_filters is None:
                    if isinstance(result, list):
                        raw_filters = result
                    else:
                        raw_filters = []
                return parse_dialog_filters(raw_filters)
        except AccountLockTimeout as e:
            logger.warning("获取文件夹列表获取锁超时 %s: %s", account_name, e)
            raise AccountLockTimeout("ACCOUNT_BUSY") from e
        finally:
            if need_disconnect:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def list_forum_topics(
        self,
        account_name: str,
        chat_id: Union[int, str],
        limit: int = 100,
        timeout_seconds: float = 12.0,
    ) -> List[Dict[str, Any]]:
        """
        获取指定群组的论坛话题（Forum Topics）列表。
        前置调用 verify_account_proxy，并在账号锁保护下获取话题。
        若非 Forum 群组（或无权限/已关闭），优雅返回空列表 []，严禁抛出 500。
        """
        account_name = self._normalize_account_name(account_name)
        if not self.account_exists(account_name):
            raise ValueError("账号不存在")

        client, proxy_dict = self._build_account_client(account_name, no_updates=True)
        await self.verify_account_proxy(account_name, proxy_dict)

        limit = max(1, min(int(limit or 100), 200))
        timeout_seconds = max(1.0, min(float(timeout_seconds or 12.0), 30.0))
        need_disconnect = False
        try:
            async with acquire_account_lock_with_timeout(
                account_name, timeout=timeout_seconds
            ):
                if not getattr(client, "is_connected", False):
                    await client.connect()
                    need_disconnect = True

                try:
                    raw_topics = await asyncio.wait_for(
                        safe_get_forum_topics(client, chat_id, limit=limit),
                        timeout=timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(
                        "safe_get_forum_topics 获取话题失败（目标可能非论坛群组或权限受限）: %s: %s",
                        chat_id,
                        exc,
                    )
                    return []

                topics_list: List[Dict[str, Any]] = []
                for topic in raw_topics or []:
                    if isinstance(topic, dict):
                        topics_list.append(topic)
                        continue
                    topics_list.append(
                        {
                            "id": getattr(topic, "id", None),
                            "title": getattr(topic, "title", "") or "",
                            "icon_color": getattr(topic, "icon_color", None),
                            "icon_emoji_id": getattr(topic, "icon_emoji_id", None),
                            "top_message": getattr(topic, "top_message", None),
                            "closed": bool(getattr(topic, "closed", False)),
                            "pinned": bool(getattr(topic, "pinned", False)),
                            "hidden": bool(getattr(topic, "hidden", False)),
                        }
                    )
                return topics_list
        except AccountLockTimeout as e:
            logger.warning("获取论坛话题列表获取锁超时 %s: %s", account_name, e)
            raise AccountLockTimeout("ACCOUNT_BUSY") from e
        finally:
            if need_disconnect:
                try:
                    await client.disconnect()
                except Exception:
                    pass
