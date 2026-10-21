from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

DANGEROUS_PATTERNS = [
    re.compile(r"支付|pay|purchase|checkout|buy", re.IGNORECASE),
    re.compile(r"充值|recharge|topup|deposit", re.IGNORECASE),
    re.compile(r"删除|delete|remove|destroy", re.IGNORECASE),
    re.compile(r"授权|authorize|oauth|bind|绑定", re.IGNORECASE),
    re.compile(r"转账|transfer|withdraw|提现", re.IGNORECASE),
]


def is_dangerous_button(text: str) -> bool:
    for pat in DANGEROUS_PATTERNS:
        if pat.search(text):
            return True
    return False


@dataclass(frozen=True)
class ButtonCandidate:
    ref: str
    row: int
    column: int
    text: str


@dataclass(frozen=True)
class ButtonSnapshot:
    chat_id: int
    thread_id: int | None
    message_id: int
    sender_id: int | None
    revision: str
    candidates: tuple[ButtonCandidate, ...]


def extract_clickable_button_candidates(
    keyboard_rows: list[list[Any]],
    *,
    max_buttons: int = 32,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for r_idx, row in enumerate(keyboard_rows):
        for c_idx, btn in enumerate(row):
            # 仅限单 callback 按钮，排除 URL / WebApp 等
            url = getattr(btn, "url", None)
            web_app = getattr(btn, "web_app", None)
            cb_data = getattr(btn, "callback_data", None)

            if url or web_app or not cb_data:
                continue

            text = getattr(btn, "text", "") or ""
            text = text.strip()
            if not text or is_dangerous_button(text):
                continue

            candidates.append(
                {
                    "ref": f"btn_{r_idx}_{c_idx}",
                    "row": r_idx,
                    "col": c_idx,
                    "text": text,
                    "callback_data": cb_data,
                }
            )
            if len(candidates) >= max_buttons:
                return candidates

    return candidates


def button_snapshot_revision(message_id: str, buttons: list[Any]) -> str:
    parts = [str(message_id)]
    for b in buttons:
        text = getattr(b, "text", "") or ""
        cb_data = getattr(b, "callback_data", "") or ""
        parts.append(f"{text}:{cb_data}")
    raw = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_button_snapshot(message: Any) -> ButtonSnapshot:
    """从 Telegram 消息对象抽取只读候选按钮快照并生成防篡改 revision"""
    chat_id = getattr(getattr(message, "chat", None), "id", 0)
    thread_id = getattr(message, "message_thread_id", None)
    message_id = getattr(message, "id", 0)
    sender_id = getattr(getattr(message, "from_user", None), "id", None)
    text = getattr(message, "text", "") or getattr(message, "caption", "") or ""

    reply_markup = getattr(message, "reply_markup", None)
    inline_kb = getattr(reply_markup, "inline_keyboard", []) or []

    candidates_list: list[ButtonCandidate] = []
    local_button_rows: list[list[dict[str, Any]]] = []

    for r_idx, row in enumerate(inline_kb):
        row_dump = []
        for c_idx, btn in enumerate(row):
            b_text = getattr(btn, "text", "") or ""
            cb_data = getattr(btn, "callback_data", None)
            cb_str = ""
            if isinstance(cb_data, bytes):
                import base64

                cb_str = base64.b64encode(cb_data).decode("ascii")
            elif cb_data is not None:
                cb_str = str(cb_data)

            is_danger = is_dangerous_button(b_text)
            has_url = bool(getattr(btn, "url", None))
            has_webapp = bool(getattr(btn, "web_app", None))

            row_dump.append(
                {
                    "row": r_idx,
                    "col": c_idx,
                    "text": b_text,
                    "cb": cb_str,
                    "danger": is_danger,
                }
            )

            if cb_data is not None and not has_url and not has_webapp and not is_danger:
                ref = f"b{r_idx}_{c_idx}"
                candidates_list.append(
                    ButtonCandidate(ref=ref, row=r_idx, column=c_idx, text=b_text)
                )
        local_button_rows.append(row_dump)

    fingerprint = {
        "chat_id": chat_id,
        "thread_id": thread_id,
        "sender_id": sender_id,
        "message_id": message_id,
        "text": text,
        "buttons": local_button_rows,
    }
    rev = hashlib.sha256(
        json.dumps(
            fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()

    return ButtonSnapshot(
        chat_id=chat_id,
        thread_id=thread_id,
        message_id=message_id,
        sender_id=sender_id,
        revision=rev,
        candidates=tuple(candidates_list[:32]),
    )


def resolve_button(
    snapshot: ButtonSnapshot, current_message: Any, selected_ref: str
) -> Any | None:
    """重新核对当前消息，当且仅当身份与 revision 100% 吻合时返回目标按钮对象"""
    if (
        current_message is None
        or not selected_ref
        or selected_ref in {"none", "unknown"}
    ):
        return None

    current_snap = build_button_snapshot(current_message)
    if (
        current_snap.chat_id != snapshot.chat_id
        or current_snap.thread_id != snapshot.thread_id
        or current_snap.message_id != snapshot.message_id
        or current_snap.sender_id != snapshot.sender_id
        or current_snap.revision != snapshot.revision
    ):
        return None

    target_cand = next((c for c in snapshot.candidates if c.ref == selected_ref), None)
    if not target_cand:
        return None

    reply_markup = getattr(current_message, "reply_markup", None)
    inline_kb = getattr(reply_markup, "inline_keyboard", []) or []
    if target_cand.row < len(inline_kb):
        row = inline_kb[target_cand.row]
        if target_cand.column < len(row):
            return row[target_cand.column]

    return None
