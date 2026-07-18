from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("backend.push_notifications")


def _as_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def is_in_quiet_hours(
    settings: Dict[str, Any], now: Optional[datetime] = None
) -> bool:
    """判断当前是否处于通知静默时段（支持跨午夜）。"""
    if not settings.get("telegram_bot_quiet_hours_enabled"):
        return False
    start_s = str(settings.get("telegram_bot_quiet_hours_start") or "23:00")
    end_s = str(settings.get("telegram_bot_quiet_hours_end") or "07:00")
    try:
        sh, sm = [int(x) for x in start_s.split(":")[:2]]
        eh, em = [int(x) for x in end_s.split(":")[:2]]
    except (TypeError, ValueError):
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
) -> None:
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": False,
    }
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
        bot_token = (settings.get("telegram_bot_token") or "").strip()
        chat_id = (settings.get("telegram_bot_chat_id") or "").strip()
        if not bot_token or not chat_id:
            logger.warning("Keyword monitor Telegram notification is not configured")
            return
        text = f"{title}\n\n{body}"
        if url:
            text += f"\n\n链接: {url}"
        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=_as_int_or_none(
                settings.get("telegram_bot_message_thread_id")
            ),
        )
        return

    if channel == "bark":
        bark_url = (settings.get("keyword_monitor_bark_url") or "").strip()
        if not bark_url:
            logger.warning("Keyword monitor Bark URL is not configured")
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
        logger.warning("Keyword monitor custom push URL is not configured")
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

    bot_token = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_bot_chat_id") or "").strip()
    if not bot_token or not chat_id:
        logger.warning("Telegram login notification is not configured")
        return

    text = (
        "TG-SignPulse 登录通知\n"
        f"用户: {username}\n"
        f"IP: {ip_address or 'unknown'}"
    )
    await send_telegram_bot_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        message_thread_id=_as_int_or_none(settings.get("telegram_bot_message_thread_id")),
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

    bot_token = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_bot_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return

    text = (
        "TG-SignPulse 任务执行成功\n"
        f"账号: {account_name}\n"
        f"任务: {task_name}"
    )
    if message:
        text += f"\n摘要: {str(message)[:500]}"
    await send_telegram_bot_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        message_thread_id=_as_int_or_none(settings.get("telegram_bot_message_thread_id")),
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

    bot_token = (settings.get("telegram_bot_token") or "").strip()
    chat_id = (settings.get("telegram_bot_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return

    text = (
        "TG-SignPulse 自动备份失败\n"
        f"原因: {str(error)[:800]}"
    )
    if detail:
        text += f"\n详情: {str(detail)[:500]}"
    try:
        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=_as_int_or_none(
                settings.get("telegram_bot_message_thread_id")
            ),
        )
    except Exception as exc:
        logger.warning("自动备份失败通知发送失败: %s", exc)
