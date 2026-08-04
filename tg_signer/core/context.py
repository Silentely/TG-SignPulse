"""UserSigner 工作上下文（从 runtime.py 拆出，供配置/执行 Mixin 共用）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from tg_signer.compat import Message

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1
    ConfigDict = None

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")


class UserSignerWorkerContext(BaseModel):
    """签到工作上下文"""

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(arbitrary_types_allowed=True)
    else:
        class Config:
            arbitrary_types_allowed = True

    sign_chats: dict  # 签到配置列表, int -> list[SignChatV3]
    chat_messages: dict  # 收到的消息, int -> dict[int, Optional[Message]]
    waiting_message: Optional[Message] = None  # 正在处理的消息
    stop_after_current_action: bool = False
    stop_reason: Optional[str] = None
    last_callback_answer: Optional[str] = None
    current_action_index: Optional[int] = None
    current_action_total: Optional[int] = None
    current_action_description: str = ""
    logged_action_message_markers: set = Field(default_factory=set)
