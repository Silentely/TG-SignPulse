"""
签到任务通知与账号预检

从 SignTaskService 抽出的 Telegram 推送 / 失效标记逻辑，供 runner 与 facade 复用。
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from backend.services.sign_task_failure import failure_category_label_by_value
from backend.utils.tg_session import get_account_status, set_account_status
from backend.utils.time import utc_now_iso, utc_now_iso_z_seconds

logger = logging.getLogger("backend.sign_task_notify")

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
    """中文标签取自 sign_task_failure 的唯一定义，避免多份文案漂移。"""
    return failure_category_label_by_value(value)


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
    ("nodename nor servname", "DNS 域名解析失败"),
    ("server disconnected", "服务器端断开连接"),
    ("remoteprotocolerror", "远程通信协议错误"),
    ("gaierror", "DNS 域名解析失败"),
    ("timed out connecting", "网络连接超时"),
]


_LOG_RUNNER_PREFIX = re.compile(r"^账户「.*?」\s*-\s*任务「.*?」\s*[:：]\s*")

_WRAPPER_PREFIXES = (
    "任务执行出错:",
    "任务执行出错：",
    "RuntimeError:",
    "Exception:",
    "会话执行失败:",
    "会话执行失败：",
    "PulseFlow 执行失败（工作流节点执行失败）:",
    "PulseFlow 执行失败（工作流节点执行失败）：",
    "PulseFlow 执行失败:",
    "PulseFlow 执行失败：",
    "工作流节点执行失败:",
    "工作流节点执行失败：",
)


def strip_error_wrappers(text: str) -> str:
    """去除层层嵌套的技术性包装前缀，直接提取核心原因。"""
    if not isinstance(text, str):
        return "" if text is None else str(text)
    res = text.strip()
    changed = True
    while changed:
        changed = False
        for p in _WRAPPER_PREFIXES:
            if res.startswith(p):
                res = res[len(p) :].strip()
                changed = True
    return res


def extract_failure_reason_from_logs(flow_logs: Optional[List[str]]) -> Optional[str]:
    """从流程日志倒序提取高价值的核心错误原因（用于替代无意义的泛化兜底）。"""
    if not flow_logs:
        return None
    for line in reversed(flow_logs):
        if not isinstance(line, str):
            continue
        line_clean = _LOG_RUNNER_PREFIX.sub("", line).strip()
        if "期间收到机器人回复" in line_clean and "未匹配" in line_clean:
            return line_clean
        if line_clean.startswith("等待机器人回复确认超时") or line_clean.startswith(
            "等待机器人确认超时"
        ):
            return line_clean
        if line_clean.startswith("签到失败:"):
            reason = strip_error_wrappers(line_clean[len("签到失败:") :].strip())
            if reason and not reason.startswith("所有会话均执行失败"):
                return reason
        if "命中失败规则" in line_clean or "机器人明确返回失败" in line_clean:
            return line_clean
    return None


def friendly_error_message(message: str) -> str:
    """常见异常英文文本映射为中文摘要；已有业务级详细中文说明时原样返回。"""
    if not isinstance(message, str):
        return "" if message is None else str(message)
    stripped = strip_error_wrappers(message)
    # 若已有详细的业务级描述（如等待机器人确认、未匹配规则等），完整保留真实细节
    if any(
        k in stripped
        for k in ("等待机器人", "未匹配", "工作流", "会话执行失败", "节点执行失败")
    ):
        return stripped
    lower = stripped.lower()
    for pattern, friendly in _FRIENDLY_ERROR_PATTERNS:
        if pattern in lower:
            return friendly
    return stripped


def is_bot_offline_timeout(
    message: str,
    flow_logs: Optional[List[str]] = None,
    failure_category: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """判断是否属于等待机器人回复超时且期间未收到任何回复（疑似机器人离线/未响应）。

    返回 (is_offline, timeout_seconds_str)。
    """
    combined = (message or "") + " " + " ".join((flow_logs or [])[-15:])

    # 若期间收到了机器人的回复（虽然未匹配成功关键词），属于规则未匹配，而非未响应离线
    if "期间收到机器人回复" in combined:
        return False, None

    offline_indicators = (
        "等待期间未收到机器人的任何回复消息",
        "等待期间未收到机器人的任何回复",
        "未收到机器人的任何回复",
        "未收到任何回复",
    )
    is_offline = any(ind in combined for ind in offline_indicators)
    if not is_offline:
        if (
            "等待机器人回复确认超时" in combined
            or "等待机器人确认超时" in combined
            or (failure_category == "timeout" and "等待机器人" in combined)
        ):
            is_offline = True

    if not is_offline:
        return False, None

    timeout_sec = None
    m = re.search(r"超时[（(]?\s*(\d+)\s*秒", combined) or re.search(
        r"(\d+)\s*秒", combined
    )
    if m:
        timeout_sec = m.group(1)

    return True, timeout_sec


def clean_flow_logs_for_notification(
    flow_logs: Optional[List[str]],
    max_lines: int = 20,
) -> tuple[List[str], bool]:
    """清洗流程日志供 Telegram 通知展示：过滤 Python Traceback 与代码回溯，保留业务步骤日志。"""
    if not flow_logs:
        return [], False
    cleaned: List[str] = []
    skip_stack = False
    for line in flow_logs:
        if not isinstance(line, str):
            continue
        strip_line = line.strip()
        if not strip_line:
            continue
        if "Traceback (most recent call last):" in strip_line:
            skip_stack = True
            continue
        if skip_stack:
            if (
                strip_line.startswith('File "')
                or strip_line.startswith("await self.")
                or strip_line.startswith("raise ")
                or strip_line.startswith("return await ")
                or strip_line.startswith("await ")
            ):
                continue
            if strip_line.startswith("RuntimeError:") or strip_line.startswith(
                "Exception:"
            ):
                skip_stack = False
                continue
        if (
            strip_line.startswith('File "')
            or ("line " in strip_line and "in normal_run" in strip_line)
            or strip_line.startswith("await self.normal_run")
            or strip_line.startswith("await sign_once()")
        ):
            continue
        cleaned.append(strip_line)

    truncated = len(cleaned) > max_lines
    return cleaned[-max_lines:], truncated


async def send_failure_notification(
    *,
    account_name: str,
    task_name: str,
    message: str,
    last_target_message: Optional[str] = None,
    flow_logs: Optional[List[str]] = None,
    failure_category: Optional[str] = None,
    run_id: str | None = None,
    aggregate_status: str = "failure",
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
            sanitize_push_error,
            send_outbox_telegram_message,
        )

        if is_in_quiet_hours(cfg):
            return
        bot_token, chat_id, thread_id = _bot_config(cfg)
        if not bot_token or not chat_id:
            return

        # 1. 机器人长时间未返回消息 / 疑似离线场景：精简发送清晰通知，不附带冗余日志与堆栈
        is_offline, timeout_sec = is_bot_offline_timeout(
            message=message,
            flow_logs=flow_logs,
            failure_category=failure_category,
        )
        if is_offline:
            sec_disp = f"（{timeout_sec} 秒）" if timeout_sec else ""
            fields = [
                ("时间 (UTC)", utc_now_iso_z_seconds()),
                ("账号", account_name),
                ("任务", task_name),
                ("失败分类", "等待回复超时"),
                (
                    "错误说明",
                    f"账号「{account_name}」执行任务「{task_name}」遇到机器人未在规定时间{sec_disp}返回消息，疑似离线或未响应",
                ),
            ]
            advice = "请确认目标机器人是否正常在线，或适当提高【回复等待超时】时间"
            text = build_html_notification(
                title=f"❌ {account_name} · {task_name} 执行失败（机器人疑似离线）",
                fields=fields,
                footer=f"建议: {advice}",
            )
            await send_outbox_telegram_message(
                event_type="task_failure",
                account_name=account_name,
                task_name=task_name,
                run_id=run_id,
                aggregate_status=aggregate_status,
                bot_token=bot_token,
                chat_id=chat_id,
                text=text,
                message_thread_id=thread_id,
                parse_mode="HTML",
            )
            return

        # 2. 通用失败通知分支
        fields = [
            ("时间 (UTC)", utc_now_iso_z_seconds()),
            ("账号", account_name),
            ("任务", task_name),
        ]

        # 动态细化失败分类标签
        combined_err_context = (message or "") + " " + " ".join((flow_logs or [])[-10:])
        category_label = _failure_category_label(failure_category)
        if "未匹配" in combined_err_context:
            category_label = "关键词未匹配"
        elif "等待机器人" in combined_err_context and (
            "超时" in combined_err_context or failure_category == "timeout"
        ):
            category_label = "等待回复超时"
        if category_label:
            fields.append(("失败分类", category_label))

        # 提炼核心错误原因，去除多余包装并过滤无意义泛化兜底
        raw_error = friendly_error_message(message)
        if not raw_error or raw_error in (
            "所有会话均执行失败（详细请看运行日志）",
            "所有会话均执行失败",
            "执行失败",
        ):
            from_logs = extract_failure_reason_from_logs(flow_logs)
            if from_logs:
                raw_error = from_logs
            elif not raw_error:
                raw_error = "未捕获到错误明细，请展开流程日志查看"
        error_text = raw_error[:400] + ("..." if len(raw_error) > 400 else "")
        fields.append(("错误", error_text))

        # 提取机器人实际回复内容（展示为目标消息）
        from backend.utils.task_logs import extract_last_target_message

        bot_reply = (last_target_message or "").strip()
        if not bot_reply and flow_logs:
            bot_reply = extract_last_target_message(flow_logs).strip()

        # 错误与目标消息常同源，相同时只展示一处；且避免将发送的消息作为目标消息展示
        if (
            bot_reply
            and bot_reply != (message or "").strip()
            and bot_reply != error_text
            and bot_reply != raw_error
        ):
            target_msg = bot_reply
            if len(target_msg) > 300:
                target_msg = target_msg[:297] + "..."
            fields.append(("目标消息", target_msg))

        clean_logs, truncated = clean_flow_logs_for_notification(flow_logs)
        log_tail = "\n".join(clean_logs)
        footer_parts: List[str] = []

        # 给出具体可落地的排查与修改建议
        advice = None
        if "未匹配" in combined_err_context:
            if bot_reply:
                advice = "机器人已回复但未匹配成功关键词。请参考上方【目标消息】，在任务配置中将【确认成功关键词】修改为机器人回复中的词语（如：出席率 成功 或 成功）"
            else:
                advice = "机器人已回复但未匹配成功关键词，请查看日志中机器人的实际回复，并在任务配置中调整【确认成功关键词】"
        elif "等待机器人" in combined_err_context:
            advice = "等待机器人回复超时（期间未收到任何回复）。请确认目标机器人是否正常在线，或适当提高【回复等待超时】时间"
        if not advice:
            advice = FAILURE_CATEGORY_ADVICE.get(failure_category or "")
        if advice:
            footer_parts.append(f"建议: {advice}")
        if log_tail:
            footer_parts.append(
                f"最近日志:\n{log_tail}"
                + ("\n（仅保留最近 20 条流程日志）" if truncated else "")
            )
        text = build_html_notification(
            title=f"❌ {account_name} · {task_name} 执行失败",
            fields=fields,
            footer="\n".join(footer_parts),
        )

        await send_outbox_telegram_message(
            event_type="task_failure",
            account_name=account_name,
            task_name=task_name,
            run_id=run_id,
            aggregate_status=aggregate_status,
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(
            "Telegram 失败通知发送失败 (账号=%s, 任务=%s): %s",
            account_name,
            task_name,
            sanitize_push_error(e),
        )


async def send_success_notification(
    *,
    account_name: str,
    task_name: str,
    message: str = "",
    run_id: str | None = None,
    aggregate_status: str = "success",
) -> None:
    try:
        from backend.services.config import get_config_service
        from backend.services.push_notifications import (
            sanitize_push_error,
            send_task_success_notification,
        )

        cfg = get_config_service().get_global_settings()
        await send_task_success_notification(
            cfg,
            account_name=account_name,
            task_name=task_name,
            message=message or "",
            **(
                {"run_id": run_id, "aggregate_status": aggregate_status}
                if run_id is not None
                else {}
            ),
        )
    except Exception as e:
        logger.warning(
            "Telegram 成功通知发送失败 (账号=%s, 任务=%s): %s",
            account_name,
            task_name,
            sanitize_push_error(e),
        )


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
            is_in_quiet_hours,
            sanitize_push_error,
            send_telegram_bot_message,
        )

        cfg = get_config_service().get_global_settings()
        if not cfg.get("telegram_bot_notify_enabled"):
            return
        # 与失败/成功/登录通知一致：静默时段内不打扰
        if is_in_quiet_hours(cfg):
            return
        bot_token, chat_id, thread_id = _bot_config(cfg)
        if not bot_token or not chat_id:
            return

        text = build_html_notification(
            title=f"⚠️ {account_name} 账号登录失效",
            fields=[
                ("时间 (UTC)", utc_now_iso_z_seconds()),
                ("账号", account_name),
                ("任务", task_name),
                (
                    "原因",
                    (friendly_error_message(message) or "会话已失效，请重新登录")[:400],
                ),
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
        logger.warning(
            "Telegram 账号失效通知发送失败 (账号=%s, 任务=%s): %s",
            account_name,
            task_name,
            sanitize_push_error(e),
        )


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
    if (
        needs_relogin
        or status in {"invalid", "not_found"}
        or code == "ACCOUNT_SESSION_INVALID"
    ):
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
