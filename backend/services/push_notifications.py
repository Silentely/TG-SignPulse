from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from backend.utils.time import utc_now_iso_z_seconds

logger = logging.getLogger("backend.push_notifications")

# Telegram Bot API 单条消息上限；留余量避免 parse_mode=HTML 时超限报错
_TG_MSG_LIMIT = 3900


def _html_escape(value: Any) -> str:
    """转义 HTML 特殊字符，供 parse_mode=HTML 通知文本使用。"""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _safe_msg_truncate(text: str, parse_mode: Optional[str] = None) -> str:
    """截断到 Telegram 消息上限，HTML 模式下保持标签闭合。

    parse_mode=HTML 时若截断点落在标签内部或存在未闭合标签，
    Telegram 会返回 400；这里用标签栈找到最后一个平衡位置回退，
    保证输出不包含未闭合标签。
    """
    if len(text) <= _TG_MSG_LIMIT:
        return text
    if parse_mode != "HTML":
        return text[:_TG_MSG_LIMIT]

    head = text[:_TG_MSG_LIMIT]
    stack: list[str] = []
    safe_pos = 0  # 最后一次标签栈为空（或自闭合）后的位置
    i = 0
    while True:
        lt = head.find("<", i)
        if lt == -1:
            break
        gt = head.find(">", lt)
        if gt == -1:
            break  # 到头部末尾仍未见闭合，视为残缺，回退
        tag = head[lt : gt + 1]
        if tag.startswith("</"):
            name = tag[2:-1].strip().split(" ")[0]
            if stack and stack[-1] == name:
                stack.pop()
                if not stack:
                    safe_pos = gt + 1
        elif tag.endswith("/>"):
            safe_pos = gt + 1
        else:
            name = tag[1:-1].strip().split(" ")[0]
            stack.append(name)
        i = gt + 1

    if not stack:
        return head
    if safe_pos == 0:
        # 没有任何平衡点（头部即为残缺标签），退回纯截断并剥离残缺标签
        import re as _re

        return _re.sub(r"<[^>]*$", "", head)
    return head[:safe_pos]


def build_html_notification(
    *,
    title: str,
    fields: list[tuple[str, str]],
    footer: str = "",
) -> str:
    """构建 Telegram HTML 格式通知文本。

    - 标题加粗，字段标签加粗、值用等宽 code，整体逐行累积。
    - 字段值先按原始文本截断再转义，避免截断点切开 HTML 实体
      （如 &amp; 被切成 &am）导致 parse_mode=HTML 解析失败。
    - 返回的文本配合 parse_mode="HTML" 发送，长度不超过 _TG_MSG_LIMIT。
    """
    lines = [f"<b>{_html_escape(title)}</b>"]
    for label, value in fields:
        if not value:
            continue
        lines.append(
            f"<b>{_html_escape(label)}</b>: <code>{_html_escape(str(value)[:2000])}</code>"
        )
    if footer:
        lines.append(_html_escape(str(footer)[:2000]))

    text = ""
    for line in lines:
        if len(text) + len(line) + 1 > _TG_MSG_LIMIT:
            break
        text = f"{text}\n{line}" if text else line
    return text


def _as_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _bot_config(settings: Dict[str, Any]) -> tuple[str, str, Optional[int]]:
    """统一读取 Bot 通知凭据：token / chat_id 去空白，话题 ID 容错解析。

    供关键词推送、登录通知、任务成败通知等共用，避免各处重复魔法键读取。
    """
    token = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_bot_chat_id") or "").strip()
    thread_id = _as_int_or_none(settings.get("telegram_bot_message_thread_id"))
    return token, chat_id, thread_id


def is_in_quiet_hours(
    settings: Dict[str, Any], now: Optional[datetime] = None
) -> bool:
    """判断当前是否处于通知静默时段（支持跨午夜）。"""
    if not settings.get("telegram_bot_quiet_hours_enabled"):
        return False
    start_s = str(settings.get("telegram_bot_quiet_hours_start") or "23:00")
    end_s = str(settings.get("telegram_bot_quiet_hours_end") or "07:00")
    try:
        start_parts = start_s.split(":")
        end_parts = end_s.split(":")
        if len(start_parts) != 2 or len(end_parts) != 2:
            return False
        sh, sm = [int(x) for x in start_parts]
        eh, em = [int(x) for x in end_parts]
    except (TypeError, ValueError):
        return False
    # 能被 int 解析不等于合法时刻，非法范围按当前降级策略不进入静默时段。
    if not all(
        0 <= hour <= 23 and 0 <= minute <= 59
        for hour, minute in ((sh, sm), (eh, em))
    ):
        return False
    tz_name = str(settings.get("timezone") or "UTC")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)
    minutes = current.hour * 60 + current.minute
    start_m, end_m = sh * 60 + sm, eh * 60 + em
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


async def send_telegram_bot_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    message_thread_id: Optional[int] = None,
    parse_mode: Optional[str] = None,
) -> None:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": _safe_msg_truncate(text, parse_mode),
        "disable_web_page_preview": False,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
        )
        response.raise_for_status()


async def send_keyword_push(settings: Dict[str, Any], payload: Dict[str, Any]) -> None:
    channel = (settings.get("keyword_monitor_push_channel") or "telegram").strip()
    title = str(payload.get("title") or "TG-SignPulse 关键词命中")
    body = str(payload.get("body") or "")
    url = str(payload.get("url") or "")
    # 多通道标题统一带状态 emoji，避免各通道展示不一致
    if not title.startswith("🔔"):
        title = f"🔔 {title}"

    if channel in ("server_chan", "server酱"):
        sendkey = (
            settings.get("keyword_monitor_server_chan_send_key")
            or settings.get("server_chan_send_key")
            or ""
        ).strip()
        if not sendkey:
            logger.warning("Server酱 sendkey 未配置")
            return
        from tg_signer.notification.server_chan import sc_send

        await sc_send(sendkey, title, desp=body)
        return

    if channel == "telegram":
        bot_token, chat_id, thread_id = _bot_config(settings)
        if not bot_token or not chat_id:
            logger.warning("关键词监听 Telegram 通知未配置")
            return
        text = build_html_notification(
            title=title,
            fields=[
                ("关键词", payload.get("keyword") or ""),
                ("账号", payload.get("account_name") or ""),
                ("会话", payload.get("chat_title") or ""),
            ],
            footer=body or "",
        )
        if url:
            text += f"\n\n🔗 链接: {_html_escape(url)}"
        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
        return

    if channel == "bark":
        bark_url = (settings.get("keyword_monitor_bark_url") or "").strip()
        if not bark_url:
            logger.warning("关键词监听 Bark 地址未配置")
            return
        data = {"title": title, "body": body}
        if url:
            data["url"] = url
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(bark_url, json=data)
            response.raise_for_status()
        return

    custom_url = (settings.get("keyword_monitor_custom_url") or "").strip()
    if not custom_url:
        logger.warning("关键词监听自定义推送地址未配置")
        return

    request_payload = dict(payload)
    request_payload["title"] = title
    request_payload["body"] = body
    request_payload["url"] = url

    if any(token in custom_url for token in ("{title}", "{body}", "{url}")):
        final_url = (
            custom_url.replace("{title}", quote(title))
            .replace("{body}", quote(body))
            .replace("{url}", quote(url))
        )
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(final_url)
            response.raise_for_status()
        return

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(custom_url, json=request_payload)
        response.raise_for_status()


async def send_login_notification(
    settings: Dict[str, Any],
    *,
    username: str,
    ip_address: str,
) -> None:
    if not settings.get("telegram_bot_notify_enabled"):
        return
    if not settings.get("telegram_bot_login_notify_enabled"):
        return
    if is_in_quiet_hours(settings):
        return

    bot_token, chat_id, thread_id = _bot_config(settings)
    if not bot_token or not chat_id:
        logger.warning("Telegram 登录通知未配置")
        return

    text = build_html_notification(
        title="🔐 TG-SignPulse 登录通知",
        fields=[
            ("时间 (UTC)", utc_now_iso_z_seconds()),
            ("用户", username or ""),
            ("IP", ip_address or "未知"),
        ],
    )
    await send_telegram_bot_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        message_thread_id=thread_id,
        parse_mode="HTML",
    )


async def send_task_success_notification(
    settings: Dict[str, Any],
    *,
    account_name: str,
    task_name: str,
    message: str = "",
) -> None:
    """任务成功时的 Bot 通知。"""
    if not settings.get("telegram_bot_notify_enabled"):
        return
    if not settings.get("telegram_bot_task_success_enabled"):
        return
    if is_in_quiet_hours(settings):
        return

    bot_token, chat_id, thread_id = _bot_config(settings)
    if not bot_token or not chat_id:
        return

    fields = [
        ("时间 (UTC)", utc_now_iso_z_seconds()),
        ("账号", account_name),
        ("任务", task_name),
    ]
    if message:
        fields.append(("摘要", str(message)[:500]))
    text = build_html_notification(
        title="✅ TG-SignPulse 任务执行成功",
        fields=fields,
    )
    await send_telegram_bot_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        message_thread_id=thread_id,
        parse_mode="HTML",
    )


async def send_auto_backup_failure_notification(
    settings: Dict[str, Any],
    *,
    error: str,
    detail: str = "",
) -> None:
    """自动备份失败时的 Bot 通知（打包失败或 WebDAV 上传失败）。

    仅依赖通知总开关 + 已配置 Token/Chat；不绑定任务失败开关
    （备份是运维事件，与签到任务失败相互独立）。静默时段仍跳过。
    """
    if not settings.get("telegram_bot_notify_enabled"):
        return
    if is_in_quiet_hours(settings):
        return

    bot_token, chat_id, thread_id = _bot_config(settings)
    if not bot_token or not chat_id:
        return

    fields = [
        ("时间 (UTC)", utc_now_iso_z_seconds()),
        ("原因", str(error)[:800]),
    ]
    if detail:
        fields.append(("详情", str(detail)[:500]))
    text = build_html_notification(
        title="🗄️ TG-SignPulse 自动备份失败",
        fields=fields,
    )
    try:
        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("自动备份失败通知发送失败: %s", exc)
