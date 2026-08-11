"""
签到任务通知与账号预检

从 SignTaskService 抽出的 Telegram 推送 / 失效标记逻辑，供 runner 与 facade 复用。
"""
from __future__ import annotations

import logging
from typing import List, Optional

from backend.utils.tg_session import get_account_status, set_account_status
from backend.utils.time import utc_now_iso, utc_now_iso_z_seconds

logger = logging.getLogger("backend.sign_task_notify")

# 失败分类中文标签：通知面向最终用户，用可读文案而非内部枚举值
FAILURE_CATEGORY_LABELS = {
    "session_invalid": "会话失效",
    "flood_wait": "频率限制",
    "ai_timeout": "AI 超时",
    "ai_error": "AI 错误",
    "button_not_found": "按钮未找到",
    "target_not_found": "目标未找到",
    "network_proxy": "网络/代理",
    "timeout": "超时",
    "strong_failure": "业务失败",
    "unknown": "未知",
    "none": "",
}


def _failure_category_label(value: Optional[str]) -> str:
    if not value:
        return ""
    return FAILURE_CATEGORY_LABELS.get(value, value)


async def send_failure_notification(
    *,
    account_name: str,
    task_name: str,
    message: str,
    last_target_message: Optional[str] = None,
    flow_logs: Optional[List[str]] = None,
    failure_category: Optional[str] = None,
) -> None:
    try:
        from backend.services.config import get_config_service

        cfg = get_config_service().get_global_settings()
        if not cfg.get("telegram_bot_notify_enabled"):
            return
        if not cfg.get("telegram_bot_task_failure_enabled", True):
            return
        from backend.services.push_notifications import (
            _bot_config,
            build_html_notification,
            is_in_quiet_hours,
            send_telegram_bot_message,
        )

        if is_in_quiet_hours(cfg):
            return
        bot_token, chat_id, thread_id = _bot_config(cfg)
        if not bot_token or not chat_id:
            return

        fields = [
            ("时间 (UTC)", utc_now_iso_z_seconds()),
            ("账号", account_name),
            ("任务", task_name),
        ]
        category_label = _failure_category_label(failure_category)
        if category_label:
            fields.append(("失败分类", category_label))
        fields.append(("错误", message or "未知错误"))
        if last_target_message:
            fields.append(("目标消息", last_target_message))
        log_tail = "\n".join((flow_logs or [])[-20:])
        truncated = len(flow_logs or []) > 20
        text = build_html_notification(
            title="❌ TG-SignPulse 任务执行失败",
            fields=fields,
            footer=(
                f"最近日志:\n{log_tail}"
                + ("\n（仅保留最近 20 条流程日志）" if truncated else "")
                if log_tail
                else ""
            ),
        )

        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Telegram 失败通知发送失败: %s", e)


async def send_success_notification(
    *,
    account_name: str,
    task_name: str,
    message: str = "",
) -> None:
    try:
        from backend.services.config import get_config_service
        from backend.services.push_notifications import (
            send_task_success_notification,
        )

        cfg = get_config_service().get_global_settings()
        await send_task_success_notification(
            cfg,
            account_name=account_name,
            task_name=task_name,
            message=message or "",
        )
    except Exception as e:
        logger.warning("Telegram 成功通知发送失败: %s", e)


async def send_account_invalid_notification(
    *,
    account_name: str,
    task_name: str,
    message: str,
) -> None:
    try:
        from backend.services.config import get_config_service
        from backend.services.push_notifications import (
            _bot_config,
            build_html_notification,
            send_telegram_bot_message,
        )

        cfg = get_config_service().get_global_settings()
        if not cfg.get("telegram_bot_notify_enabled"):
            return
        bot_token, chat_id, thread_id = _bot_config(cfg)
        if not bot_token or not chat_id:
            return

        text = build_html_notification(
            title="⚠️ TG-SignPulse 账号登录失效",
            fields=[
                ("时间 (UTC)", utc_now_iso_z_seconds()),
                ("账号", account_name),
                ("任务", task_name),
                ("原因", message or "session 已失效，请重新登录"),
            ],
            footer="该账号下的任务已跳过。",
        )

        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Telegram 账号失效通知发送失败: %s", e)


async def mark_account_invalid(
    *,
    account_name: str,
    task_name: str,
    message: str,
    notify_on_failure: bool = True,
) -> bool:
    """标记账号失效；首次失效且允许通知时推送。返回是否新通知。"""
    current = get_account_status(account_name)
    already_notified = bool(current.get("invalid_notified_at"))
    notified_at = current.get("invalid_notified_at") or utc_now_iso()
    set_account_status(
        account_name,
        status="invalid",
        message=message,
        code="ACCOUNT_SESSION_INVALID",
        needs_relogin=True,
        invalid_notified_at=notified_at,
    )
    if not already_notified and notify_on_failure:
        await send_account_invalid_notification(
            account_name=account_name,
            task_name=task_name,
            message=message,
        )
    return not already_notified


async def check_account_before_task(
    *,
    account_name: str,
    task_name: str,
    no_updates: bool,
    notify_on_failure: bool = True,
) -> Optional[str]:
    """任务前账号预检；失效返回原因文案，正常返回 None。"""
    stored_status = get_account_status(account_name)
    if stored_status.get("status") == "invalid" and stored_status.get("needs_relogin"):
        message = (
            str(stored_status.get("message") or "").strip()
            or f"账号 {account_name} 登录已失效，请重新登录"
        )
        await mark_account_invalid(
            account_name=account_name,
            task_name=task_name,
            message=message,
            notify_on_failure=notify_on_failure,
        )
        return message

    try:
        from backend.services.telegram import get_telegram_service

        result = await get_telegram_service().check_account_status(
            account_name,
            timeout_seconds=10.0,
            no_updates=no_updates,
        )
    except Exception as e:
        logger.warning(
            "任务 %s/%s 前置账号状态检查失败: %s",
            account_name,
            task_name,
            e,
        )
        return None

    if result.get("ok"):
        return None

    needs_relogin = bool(result.get("needs_relogin"))
    status = str(result.get("status") or "")
    code = str(result.get("code") or "")
    if needs_relogin or status in {"invalid", "not_found"} or code == "ACCOUNT_SESSION_INVALID":
        message = (
            str(result.get("message") or "").strip()
            or f"账号 {account_name} 登录已失效，请重新登录"
        )
        await mark_account_invalid(
            account_name=account_name,
            task_name=task_name,
            message=message,
            notify_on_failure=notify_on_failure,
        )
        return message

    return None
