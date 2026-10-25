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


def chat_scope_key(chat_id: int, thread_id: Optional[int] = None):
    """Keep ordinary chats on their historical key and isolate forum topics."""
    return chat_id if thread_id is None else (chat_id, thread_id)


class UserSignerWorkerContext(BaseModel):
    """签到工作上下文"""

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")
    else:

        class Config:
            arbitrary_types_allowed = True
            extra = "allow"

    sign_chats: dict  # 签到配置列表, int -> list[SignChatV3]
    chat_messages: dict  # 收到的消息, chat_id 或 (chat_id, thread_id) -> 消息
    topic_last_output: dict = Field(default_factory=dict)
    topic_last_received_text: dict = Field(default_factory=dict)
    waiting_message: Optional[Message] = None  # 正在处理的消息
    stop_after_current_action: bool = False
    stop_reason: Optional[str] = None
    last_callback_answer: Optional[str] = None
    last_callback_unconfirmed: bool = False
    current_action_index: Optional[int] = None
    current_action_total: Optional[int] = None
    current_action_description: str = ""
    logged_action_message_markers: set = Field(default_factory=set)
    step_outputs: dict = Field(default_factory=dict)
    last_output: Optional[str] = None
    last_received_text: Optional[str] = None
    workflow_path: Optional[list] = None
    workflow_steps: Optional[int] = None
    pulseflow_side_effect_started: bool = False
    pulseflow_fallback_occurred: bool = False
    pulseflow_fallback_reason: Optional[str] = None
