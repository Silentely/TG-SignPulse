"""TG-SignPulse 插件子进程 IPC 通信协议与数据代理。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def serialize_message_for_worker(msg: Any) -> Optional[Dict[str, Any]]:
    """将 Pyrogram 的 Message 对象序列化为可在 IPC 管道传输的精简字典。"""
    if not msg:
        return None

    chat_dict = None
    if getattr(msg, "chat", None) is not None:
        chat_dict = {
            "id": getattr(msg.chat, "id", None),
            "title": getattr(msg.chat, "title", None),
            "type": str(getattr(msg.chat, "type", "")),
        }
    elif getattr(msg, "chat_id", None) is not None:
        chat_dict = {"id": msg.chat_id, "title": None, "type": ""}

    user_dict = None
    if getattr(msg, "from_user", None) is not None:
        user_dict = {
            "id": getattr(msg.from_user, "id", None),
            "username": getattr(msg.from_user, "username", None),
            "first_name": getattr(msg.from_user, "first_name", None),
            "last_name": getattr(msg.from_user, "last_name", None),
        }

    buttons: List[List[Dict[str, Any]]] = []
    reply_markup = getattr(msg, "reply_markup", None)
    if reply_markup and hasattr(reply_markup, "inline_keyboard"):
        for row in reply_markup.inline_keyboard:
            row_data = []
            for btn in row:
                cb_data = getattr(btn, "callback_data", None)
                if isinstance(cb_data, bytes):
                    cb_data = cb_data.decode("utf-8", "ignore")
                elif cb_data is not None:
                    cb_data = str(cb_data)
                row_data.append(
                    {
                        "text": getattr(btn, "text", ""),
                        "data": cb_data or "",
                    }
                )
            buttons.append(row_data)

    raw_date = getattr(msg, "date", None)
    date_val = None
    if raw_date is not None:
        if hasattr(raw_date, "timestamp"):
            try:
                date_val = int(raw_date.timestamp())
            except Exception:
                date_val = str(raw_date)
        elif isinstance(raw_date, (int, float)):
            date_val = int(raw_date)
        else:
            date_val = str(raw_date)

    reply_to_dict = None
    reply_to_msg = getattr(msg, "reply_to_message", None)
    if reply_to_msg is not None:
        raw_rt_date = getattr(reply_to_msg, "date", None)
        rt_date_val = None
        if raw_rt_date is not None:
            if hasattr(raw_rt_date, "timestamp"):
                try:
                    rt_date_val = int(raw_rt_date.timestamp())
                except Exception:
                    rt_date_val = str(raw_rt_date)
            elif isinstance(raw_rt_date, (int, float)):
                rt_date_val = int(raw_rt_date)
            else:
                rt_date_val = str(raw_rt_date)

        rt_user_dict = None
        if getattr(reply_to_msg, "from_user", None) is not None:
            rt_user_dict = {
                "id": getattr(reply_to_msg.from_user, "id", None),
                "username": getattr(reply_to_msg.from_user, "username", None),
                "first_name": getattr(reply_to_msg.from_user, "first_name", None),
                "last_name": getattr(reply_to_msg.from_user, "last_name", None),
            }

        reply_to_dict = {
            "id": getattr(reply_to_msg, "id", None),
            "text": getattr(reply_to_msg, "text", None),
            "caption": getattr(reply_to_msg, "caption", None),
            "date": rt_date_val,
            "from_user": rt_user_dict,
        }

    return {
        "id": getattr(msg, "id", None),
        "text": getattr(msg, "text", None),
        "caption": getattr(msg, "caption", None),
        "date": date_val,
        "reply_to_message_id": getattr(msg, "reply_to_message_id", None),
        "reply_to_message": reply_to_dict,
        "chat": chat_dict,
        "from_user": user_dict,
        "buttons": buttons,
    }


class ProxyChat:
    def __init__(self, data: Optional[Dict[str, Any]]):
        data = data or {}
        self.id = data.get("id")
        self.title = data.get("title")
        self.type = data.get("type")

    def __bool__(self) -> bool:
        return bool(self.id or self.title)

    def __repr__(self) -> str:
        return f"ProxyChat(id={self.id}, title={self.title!r}, type={self.type!r})"


class ProxyUser:
    def __init__(self, data: Optional[Dict[str, Any]]):
        data = data or {}
        self.id = data.get("id")
        self.username = data.get("username")
        self.first_name = data.get("first_name")
        self.last_name = data.get("last_name")

    def __repr__(self) -> str:
        return f"ProxyUser(id={self.id}, username={self.username!r})"


class ProxyButton:
    def __init__(self, data: Dict[str, Any]):
        self.text = data.get("text", "")
        self.data = data.get("data", "")

    def __repr__(self) -> str:
        return f"ProxyButton(text={self.text!r}, data={self.data!r})"


class ProxyMessage:
    """在 Worker 进程中模拟 pyrogram.types.Message 的轻量代理对象。"""

    def __init__(self, data: Optional[Dict[str, Any]]):
        self._data = data or {}
        self.id = self._data.get("id")
        self.text = self._data.get("text")
        self.caption = self._data.get("caption")
        self.date = self._data.get("date")
        self.reply_to_message_id = self._data.get("reply_to_message_id")
        self.chat = ProxyChat(self._data.get("chat"))
        self.from_user = (
            ProxyUser(self._data.get("from_user"))
            if self._data.get("from_user")
            else None
        )

        self.buttons: List[List[ProxyButton]] = []
        for row in self._data.get("buttons") or []:
            self.buttons.append([ProxyButton(b) for b in row])

        self.reply_to_message = (
            ProxyMessage(self._data.get("reply_to_message"))
            if self._data.get("reply_to_message")
            else None
        )

    @property
    def chat_id(self) -> Optional[int]:
        return self.chat.id if self.chat else None

    @property
    def raw_text(self) -> str:
        return self._data.get("raw_text") or self.text or self.caption or ""

    def __repr__(self) -> str:
        return f"ProxyMessage(id={self.id}, text={self.text!r})"


def encode_ipc_payload(payload: Dict[str, Any], max_len: int = 16384) -> str:
    """将数据编码为单行 JSON，自动截断超大内容防止管道阻塞。"""
    if (
        "message" in payload
        and isinstance(payload["message"], str)
        and len(payload["message"]) > max_len
    ):
        payload = {
            **payload,
            "message": payload["message"][:max_len] + " ...[truncated]",
        }
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def decode_ipc_payload(line: str) -> Dict[str, Any]:
    """从单行 JSON 解码为字典对象。"""
    return json.loads(line)
