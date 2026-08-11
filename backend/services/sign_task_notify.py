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

# 失败分类对应的可操作建议：通知附带下一步指引，而非只报错
FAILURE_CATEGORY_ADVICE = {
    "session_invalid": "请到「账号管理」重新登录该账号后重试",
    "flood_wait": "Telegram 触发频率限制，建议降低任务并发或稍后重试",
    "ai_timeout": "AI 响应超时，请检查 AI 服务配置或稍后重试",
    "ai_error": "AI 服务返回错误，请检查 AI 配置（API Key / 模型）",
    "button_not_found": "目标按钮未找到，请确认聊天中按钮文案是否发生变化",
    "target_not_found": "目标会话或消息未找到，请检查任务的目标会话配置",
    "network_proxy": "网络或代理连接异常，请检查代理配置与网络连通性",
    "timeout": "任务执行超时，可适当提高超时设置或拆分任务",
    "strong_failure": "机器人回复疑似失败，请检查目标机器人当前状态",
}


def _failure_category_label(value: Optional[str]) -> str:
    if not value:
        return ""
    return FAILURE_CATEGORY_LABELS.get(value, value)


# 常见异常英文文本 → 中文摘要：通知面向最终用户，避免直接透出
# Pyrogram 的 FloodWait/Timeout 等英文报错原文
_FRIENDLY_ERROR_PATTERNS = [
    ("flood wait", "Telegram 频率限制（需等待后重试）"),
    ("floodwait", "Telegram 频率限制（需等待后重试）"),
    ("timed out", "执行超时"),
    ("timeout", "执行超时"),
    ("database is locked", "数据库被锁定（Session 并发冲突）"),
    ("auth key unregistered", "会话已失效"),
    ("auth key invalid", "会话已失效"),
    ("session revoked", "会话已失效"),
    ("unauthorized", "会话已失效"),
    ("connection reset", "网络连接被重置"),
    ("connection refused", "网络连接被拒绝"),
]


def _friendly_error_message(message: str) -> str:
    """常见异常英文文本映射为中文摘要；无命中时原样返回。"""
    lower = (message or "").lower()
    for pattern, friendly in _FRIENDLY_ERROR_PATTERNS:
        if pattern in lower:
            return friendly
    return message


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
        fields.append(("错误", _friendly_error_message(message) or "未知错误"))
        if last_target_message:
            fields.append(("目标消息", last_target_message))
        log_tail = "\n".join((flow_logs or [])[-20:])
        truncated = len(flow_logs or []) > 20
        footer_parts: List[str] = []
        advice = FAILURE_CATEGORY_ADVICE.get(failure_category or "")
        if advice:
            footer_parts.append(f"建议: {advice}")
        if log_tail:
            footer_parts.append(
                f"最近日志:\n{log_tail}"
                + ("\n（仅保留最近 20 条流程日志）" if truncated else "")
            )
        text = build_html_notification(
            title="❌ TG-SignPulse 任务执行失败",
            fields=fields,
            footer="\n".join(footer_parts),
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
                ("原因", message or "会话已失效，请重新登录"),
            ],
            footer="该账号下的任务已跳过。请到面板「账号管理」中重新登录该账号。",
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
