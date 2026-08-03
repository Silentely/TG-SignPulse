"""
签到任务执行主路径

从 SignTaskService 抽离，行为保持不变；service 仅委托调用。
按阶段拆分为独立 helper，每个阶段可独立单测。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional

from backend.services.sign_task_failure import FailureCategory, classify_failure
from backend.services.sign_task_run_status import (
    PHASE_CHECKING_ACCOUNT,
    PHASE_COOLDOWN,
    PHASE_FINALIZING,
    PHASE_RUNNING,
    PHASE_WAITING_LOCK,
    is_timeout_error_message,
    resolve_effective_retry_count,
)
from backend.utils.task_logs import extract_last_target_message
from tg_signer.async_utils import create_logged_task
from tg_signer.log_utils import safe_exception_summary, safe_traceback_preview

if TYPE_CHECKING:
    from backend.services.sign_tasks import SignTaskService


_service_logger = logging.getLogger("backend.sign_tasks")


# ========== Phase helpers ==========


async def _runner_load_config(state: Dict[str, Any]) -> None:
    """Phase 1: 加载任务配置，提取运行参数。"""
    svc: SignTaskService = state["svc"]
    task_dir = svc._resolve_task_dir(state["task_name"], state["account_name"])
    task_cfg = svc._load_task_config(task_dir) if task_dir else None
    if not task_cfg:
        raise ValueError(f"Task {state['task_name']} does not exist or cannot be loaded")
    state.update(
        {
            "task_cfg": task_cfg,
            "requires_updates": svc._task_requires_updates(task_cfg),
            "has_keyword_monitor": svc._task_has_keyword_monitor(task_cfg),
            "signer_no_updates": not svc._task_requires_updates(task_cfg),
            "task_notify_on_failure": bool(task_cfg.get("notify_on_failure", True)),
            "task_notify_on_success": bool(task_cfg.get("notify_on_success", True)),
        }
    )


async def _runner_check_account(state: Dict[str, Any]) -> None:
    """Phase 2: 账号预检（失败则跳过后续执行）。"""
    from backend.services.sign_task_notify import check_account_before_task

    svc: SignTaskService = state["svc"]
    svc._update_run_phase(
        state["account_name"],
        state["task_name"],
        run_id=state.get("run_id"),
        phase=PHASE_CHECKING_ACCOUNT,
        phase_detail=f"检查账号 {state['account_name']}",
    )
    invalid_reason = await check_account_before_task(
        account_name=state["account_name"],
        task_name=state["task_name"],
        no_updates=state["signer_no_updates"],
        notify_on_failure=state["task_notify_on_failure"],
    )
    if invalid_reason:
        state["account_invalid_detected"] = True
        state["error_msg"] = (
            f"账号 {state['account_name']} 登录已失效，请重新登录: {invalid_reason}"
        )
        task_key = state.setdefault(
            "task_key", svc._task_key(state["account_name"], state["task_name"])
        )
        svc._active_logs[task_key].append(state["error_msg"])


async def _runner_refresh_keyword_monitor(state: Dict[str, Any]) -> None:
    """Phase 2.5: 刷新关键词后台监听（最佳-effort）。"""
    if not state.get("has_keyword_monitor"):
        return
    from backend.services.keyword_monitor import get_keyword_monitor_service

    svc: SignTaskService = state["svc"]
    task_key = state["task_key"]
    try:
        await get_keyword_monitor_service().restart_from_tasks()
    except Exception as exc:
        svc._active_logs.setdefault(task_key, []).append(
            f"关键词后台监听刷新失败: {exc}"
        )


async def _runner_acquire_lock(state: Dict[str, Any]) -> None:
    """Phase 3: 等待账号锁、处理冷却，并在锁持有期间完成全部执行。"""
    svc: SignTaskService = state["svc"]
    account_lock = state["account_lock"]

    svc._update_run_phase(
        state["account_name"],
        state["task_name"],
        run_id=state.get("run_id"),
        phase=PHASE_WAITING_LOCK,
        phase_detail=f"等待账号锁 {state['account_name']}",
    )

    async with account_lock:
        last_end = svc._account_last_run_end.get(state["account_name"])
        if last_end:
            gap = time.time() - last_end
            wait_seconds = svc._account_cooldown_seconds - gap
            if wait_seconds > 0:
                wait_i = max(
                    1,
                    int(wait_seconds)
                    if wait_seconds == int(wait_seconds)
                    else int(wait_seconds) + 1,
                )
                svc._update_run_phase(
                    state["account_name"],
                    state["task_name"],
                    run_id=state.get("run_id"),
                    phase=PHASE_COOLDOWN,
                    phase_detail=f"等待账号冷却 {wait_i} 秒",
                    wait_seconds=float(wait_i),
                )
                svc._active_logs[state["task_key"]].append(
                    f"等待账号冷却 {wait_i} 秒"
                )
                await asyncio.sleep(wait_seconds)

        state["lock_acquired"] = True

        await _runner_setup_logging(state)
        await _runner_resolve_credentials(state)
        await _runner_instantiate_signer(state)
        await _runner_prepare_execution(state)
        await _runner_execute_with_retry(state)


async def _runner_setup_logging(state: Dict[str, Any]) -> None:
    """Phase 4: 配置 TaskLogHandler 将日志注入 active_logs。"""
    svc: SignTaskService = state["svc"]
    task_key = state["task_key"]
    tg_logger = logging.getLogger("tg-signer")
    log_handler = state["TaskLogHandler"](svc._active_logs[task_key])
    log_handler.setLevel(logging.INFO)
    log_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    if tg_logger.getEffectiveLevel() > logging.INFO:
        tg_logger.setLevel(logging.INFO)
    tg_logger.addHandler(log_handler)
    state.update({"tg_logger": tg_logger, "log_handler": log_handler})
    _service_logger.debug(
        "已获取账号锁 %s，开始执行任务 %s",
        state["account_name"],
        state["task_name"],
    )
    svc._active_logs[task_key].append(
        f"开始执行任务: {state['task_name']} (账号: {state['account_name']})"
    )


async def _runner_resolve_credentials(state: Dict[str, Any]) -> None:
    """Phase 5: 解析 API 凭据、session 模式、代理配置。"""
    from backend.services.config import get_config_service
    from backend.services.telegram.credentials import resolve_telegram_api_credentials
    from backend.utils.proxy import build_proxy_dict
    from backend.utils.tg_session import (
        get_account_session_string,
        get_session_mode,
        load_session_string_file,
    )

    svc: SignTaskService = state["svc"]
    account_name = state["account_name"]
    config_service = get_config_service()
    tg_config = config_service.get_telegram_config()
    api_id, api_hash = resolve_telegram_api_credentials(
        tg_config,
        env_api_id=os.getenv("TG_API_ID"),
        env_api_hash=os.getenv("TG_API_HASH"),
    )

    session_dir = state["settings"].resolve_session_dir()
    session_mode = get_session_mode()
    session_string = None
    use_in_memory = False
    proxy_dict = None
    proxy_value = svc._get_effective_proxy(account_name)
    if proxy_value:
        proxy_dict = build_proxy_dict(proxy_value)

    if session_mode == "string":
        session_string = (
            get_account_session_string(account_name)
            or load_session_string_file(session_dir, account_name)
        )
        if not session_string:
            state["account_invalid_detected"] = True
            raise ValueError(f"账号 {account_name} 的 session_string 不存在")
        use_in_memory = True
    else:
        session_string = load_session_string_file(session_dir, account_name)
        use_in_memory = bool(session_string)
        if os.getenv("SIGN_TASK_FORCE_IN_MEMORY") == "0":
            session_string = None
            use_in_memory = False

    state.update(
        {
            "api_id": api_id,
            "api_hash": api_hash,
            "session_dir": session_dir,
            "session_string": session_string,
            "use_in_memory": use_in_memory,
            "proxy_dict": proxy_dict,
        }
    )


async def _runner_instantiate_signer(state: Dict[str, Any]) -> None:
    """Phase 6: 根据解析出的配置实例化 BackendUserSigner。"""
    svc: SignTaskService = state["svc"]
    state["signer"] = state["BackendUserSigner"](
        task_name=state["task_name"],
        session_dir=str(state["session_dir"]),
        account=state["account_name"],
        workdir=svc.workdir,
        proxy=state["proxy_dict"],
        session_string=state["session_string"],
        in_memory=state["use_in_memory"],
        api_id=state["api_id"],
        api_hash=state["api_hash"],
        no_updates=state["signer_no_updates"],
    )


async def _runner_prepare_execution(state: Dict[str, Any]) -> None:
    """Phase 7: 准备执行上下文（重试次数、超时、阶段标记）。"""
    from backend.services.runtime_settings import (
        get_execution_timeout,
        get_flow_retry_attempts,
    )
    from backend.services.sign_tasks import _task_retry_count_var

    svc: SignTaskService = state["svc"]
    raw_task_cfg = svc._load_raw_task_config_dict(
        state["task_name"], state["account_name"]
    )
    task_retry_count = resolve_effective_retry_count(
        raw_task_cfg, get_flow_retry_attempts()
    )
    _task_retry_count_var.set(task_retry_count)
    task_timeout = float(get_execution_timeout())

    svc._update_run_phase(
        state["account_name"],
        state["task_name"],
        run_id=state.get("run_id"),
        phase=PHASE_RUNNING,
        phase_detail=f"执行中（超时 {int(task_timeout)}s，重试 {task_retry_count}）",
        wait_seconds=None,
        timeout_seconds=task_timeout,
        retry_count_effective=task_retry_count,
    )

    state["task_timeout"] = task_timeout


async def _runner_execute_with_retry(state: Dict[str, Any]) -> None:
    """Phase 8: 带重试的执行循环（数据库锁冲突时退避）。"""
    from backend.utils.tg_session import get_global_semaphore

    svc: SignTaskService = state["svc"]
    signer = state["signer"]
    task_timeout = state["task_timeout"]
    task_key = state["task_key"]

    async with get_global_semaphore():
        max_retries = 5
        for attempt in range(max_retries):
            try:
                await asyncio.wait_for(
                    signer.run_once(num_of_dialogs=20),
                    timeout=task_timeout,
                )
                break
            except asyncio.TimeoutError:
                state["timed_out"] = True
                raise RuntimeError(
                    f"任务执行超时（{int(task_timeout)}秒），已强制终止"
                )
            except Exception as e:
                if "database is locked" in str(e).lower():
                    if attempt < max_retries - 1:
                        delay = 3 + (attempt * 3)
                        svc._active_logs[task_key].append(
                            f"Session 被锁定，{delay} 秒后重试... ({attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                raise

    state["success"] = True
    svc._active_logs[task_key].append("任务执行完成")
    # 增加缓冲时间，防止同账号连续执行任务时 Session 文件锁尚未完全释放
    await asyncio.sleep(2)


async def _runner_parse_reply(state: Dict[str, Any]) -> None:
    """Phase 9: 从日志流解析最近回复，检测强失败翻转。"""
    svc: SignTaskService = state["svc"]
    final_logs = list(svc._active_logs.get(state["task_key"], []))
    state["final_logs"] = final_logs
    state["output_str"] = "\n".join(final_logs)

    last_reply = ""
    for line in reversed(final_logs):
        if "收到来自「" in line and ("」的消息:" in line or "」对消息的更新，消息:" in line):
            try:
                splitter = "」的消息:" if "」的消息:" in line else "」对消息的更新，消息:"
                reply_part = line.split(splitter, 1)[-1].strip()
                if reply_part.startswith("Message:"):
                    reply_part = reply_part[len("Message:"):].strip()

                if "text: " in reply_part:
                    text_content = reply_part.split("text: ", 1)[-1].split("\n")[0].strip()
                    if text_content:
                        last_reply = text_content
                    elif "图片: " in reply_part:
                        last_reply = (
                            "[图片] "
                            + reply_part.split("图片: ", 1)[-1].split("\n")[0].strip()
                        )
                    else:
                        last_reply = reply_part.replace("\n", " ").strip()
                elif "图片: " in reply_part:
                    last_reply = (
                        "[图片] "
                        + reply_part.split("图片: ", 1)[-1].split("\n")[0].strip()
                    )
                else:
                    last_reply = reply_part.replace("\n", " ").strip()

                if len(last_reply) > 200:
                    last_reply = last_reply[:197] + "..."
            except Exception as e:
                _service_logger.debug("解析最近回复文本失败: %s", e)
            if last_reply:
                break

    if last_reply:
        reply_lower = last_reply.lower()
        failure_keywords = (
            "失败",
            "未成功",
            "无法",
            "failed",
            "failure",
            "not found",
        )
        if (
            any(keyword in reply_lower for keyword in failure_keywords)
            and svc._message_indicates_strong_failure(last_reply)
        ):
            state["success"] = False
            state["error_msg"] = f"机器人回复疑似失败: {last_reply}"
            final_logs.append(state["error_msg"])
            svc._active_logs.setdefault(state["task_key"], []).append(state["error_msg"])
            state["output_str"] = "\n".join(final_logs)

    state["last_reply"] = last_reply


async def _runner_fetch_target_message(state: Dict[str, Any]) -> None:
    """Phase 10: 补抓任务对象最后消息（超时则跳过）。"""
    if not state.get("success") or state.get("last_target_message"):
        return

    svc: SignTaskService = state["svc"]
    task_key = state["task_key"]
    signer = state.get("signer")
    task_cfg = state.get("task_cfg")
    final_logs = state.get("final_logs", [])

    if not signer or not task_cfg:
        return

    _service_logger.debug(
        "fetch_target | last_reply=%r | calling chat history fetch",
        state.get("last_reply"),
    )

    last_target_message = ""
    if not state.get("last_reply"):
        last_target_message = extract_last_target_message(final_logs)
        if not last_target_message:
            try:
                last_target_fetch_timeout = float(
                    os.getenv("SIGN_TASK_LAST_TARGET_FETCH_TIMEOUT", "5")
                )
                if last_target_fetch_timeout > 0:
                    last_target_message = await asyncio.wait_for(
                        svc._fetch_last_target_message_from_chat_history(signer, task_cfg),
                        timeout=last_target_fetch_timeout,
                    )
                else:
                    last_target_message = await svc._fetch_last_target_message_from_chat_history(
                        signer, task_cfg
                    )
            except asyncio.TimeoutError:
                timeout_log = (
                    f"补抓任务对象最后消息超时 ({last_target_fetch_timeout:.1f}s)，已跳过"
                )
                svc._active_logs.setdefault(task_key, []).append(timeout_log)
                state["final_logs"] = list(svc._active_logs.get(task_key, []))
                state["output_str"] = "\n".join(state["final_logs"])
                last_target_message = ""
            except Exception:
                last_target_message = ""
        else:
            state["last_reply"] = last_target_message

    if last_target_message:
        state["last_reply"] = last_target_message
    if last_target_message and not any(
        "任务对象最后一条消息:" in str(line) for line in state["final_logs"]
    ):
        last_message_line = f"任务对象最后一条消息: {last_target_message}"
        state["final_logs"].append(last_message_line)
        svc._active_logs.setdefault(task_key, []).append(last_message_line)
        state["output_str"] = "\n".join(state["final_logs"])
        state["last_target_message"] = last_target_message


async def _runner_save_run_info(state: Dict[str, Any]) -> None:
    """Phase 11: 保存执行记录（无论成功失败）。"""
    svc: SignTaskService = state["svc"]
    msg = state["error_msg"] if not state.get("success") else state.get("last_reply", "")
    svc._save_run_info(
        state["task_name"],
        state.get("success", False),
        msg,
        state["account_name"],
        flow_logs=state.get("final_logs", []),
    )


async def _runner_send_notifications(state: Dict[str, Any]) -> None:
    """Phase 12: 发送成功/失败通知。"""
    from backend.services.sign_task_notify import (
        send_failure_notification,
        send_success_notification,
    )

    success = state.get("success", False)
    if (
        not success
        and not state.get("account_invalid_detected", False)
        and state.get("task_notify_on_failure", True)
    ):
        await send_failure_notification(
            account_name=state["account_name"],
            task_name=state["task_name"],
            message=state.get("error_msg", "") or state.get("last_reply", ""),
            last_target_message=state.get("last_target_message") or None,
            flow_logs=state.get("final_logs", []),
        )
    elif success and state.get("task_notify_on_success", True):
        await send_success_notification(
            account_name=state["account_name"],
            task_name=state["task_name"],
            message=str(state.get("last_reply", "") or ""),
        )


async def _runner_schedule_cleanup(state: Dict[str, Any]) -> None:
    """Phase 13: 延迟清理 active_logs（60 秒无新日志时回收）。"""
    svc: SignTaskService = state["svc"]
    task_key = state["task_key"]

    old_cleanup_task = svc._cleanup_tasks.get(task_key)
    if old_cleanup_task and not old_cleanup_task.done():
        old_cleanup_task.cancel()

    cleanup_task: Optional[asyncio.Task[Any]] = None

    async def cleanup() -> None:
        try:
            await asyncio.sleep(60)
            if not svc._active_tasks.get(task_key):
                svc._active_logs.pop(task_key, None)
        finally:
            # 仅当自身仍是注册条目时才移除，避免被取消的旧任务
            # 在下一轮事件循环执行 finally 时误删新注册的清理任务
            if svc._cleanup_tasks.get(task_key) is cleanup_task:
                svc._cleanup_tasks.pop(task_key, None)

    cleanup_task = create_logged_task(
        cleanup(),
        logger=logging.getLogger("backend.sign_tasks"),
        description=f"active log cleanup {state['account_name']}/{state['task_name']}",
    )
    svc._cleanup_tasks[task_key] = cleanup_task


async def _runner_handle_error(state: Dict[str, Any], e: Exception) -> None:
    """统一异常处理：分类、日志、账号失效标记。"""
    svc: SignTaskService = state["svc"]

    if is_timeout_error_message(str(e)) or state.get("timed_out"):
        state["timed_out"] = True
    if state.get("account_invalid_detected") or svc._is_invalid_session_error(e):
        state["account_invalid_detected"] = True
        invalid_message = str(e) or f"账号 {state['account_name']} 登录已失效，请重新登录"
        from backend.services.sign_task_notify import mark_account_invalid

        await mark_account_invalid(
            account_name=state["account_name"],
            task_name=state["task_name"],
            message=invalid_message,
            notify_on_failure=state.get("task_notify_on_failure", True),
        )

    _run_id_tag = f" [run_id={state.get('run_id')}]" if state.get("run_id") else ""
    state["error_msg"] = f"任务执行出错{_run_id_tag}: {safe_exception_summary(e, 300)}"
    svc._active_logs[state["task_key"]].append(state["error_msg"])

    _tb = traceback.format_exc()
    _safe_tb = safe_traceback_preview(_tb, max_lines=6, max_line_chars=200)
    if _safe_tb:
        for _line in _safe_tb.splitlines():
            svc._active_logs[state["task_key"]].append(f"  {_line}")

    _service_logger.error(
        "任务执行出错%s [%s/%s]: %s",
        _run_id_tag,
        state["account_name"],
        state["task_name"],
        e,
        exc_info=True,
    )


async def _runner_finalize(state: Dict[str, Any]) -> None:
    """统一收尾：更新时间、解析回复、补抓消息、持久化、通知、清理。"""
    svc: SignTaskService = state["svc"]
    account_name = state["account_name"]
    task_key = state["task_key"]
    tg_logger = state.get("tg_logger")
    log_handler = state.get("log_handler")

    svc._account_last_run_end[account_name] = time.time()
    if state.get("lock_acquired"):
        svc._update_run_phase(
            account_name,
            state["task_name"],
            run_id=state.get("run_id"),
            phase=PHASE_FINALIZING,
            phase_detail="写入执行历史",
        )
    if log_handler is not None and tg_logger is not None:
        tg_logger.removeHandler(log_handler)

    final_logs = list(svc._active_logs.get(task_key, []))
    state["final_logs"] = final_logs
    state["output_str"] = "\n".join(final_logs)

    if state.get("success") and not state.get("last_reply"):
        await _runner_parse_reply(state)

    if state.get("success"):
        await _runner_fetch_target_message(state)

    await _runner_save_run_info(state)
    await _runner_send_notifications(state)

    svc._active_tasks[task_key] = False
    await _runner_schedule_cleanup(state)


# ========== Main orchestrator ==========


async def execute_sign_task(
    svc: "SignTaskService",
    account_name: str,
    task_name: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """运行任务并实时捕获日志（In-Process）。

    按阶段拆分为独立 helper，每个阶段可独立单测。
    """
    from backend.services.sign_task_backend import BackendUserSigner, TaskLogHandler
    from backend.services.sign_tasks import settings
    from backend.utils.account_locks import get_account_lock
    from backend.utils.names import validate_storage_name

    account_name = validate_storage_name(account_name, field_name="account_name")
    task_name = validate_storage_name(task_name, field_name="task_name")

    if svc.is_task_running(task_name, account_name):
        return {
            "success": False,
            "error": "任务已经在运行中",
            "output": "",
            "timed_out": False,
            "failure_category": None,
        }

    # 初始化账号锁（跨服务共享）
    if account_name not in svc._account_locks:
        svc._account_locks[account_name] = get_account_lock(account_name)
    account_lock = svc._account_locks[account_name]

    # 定时任务同时触发时排队等待账号锁
    _service_logger.debug("等待获取账号锁 %s...", account_name)
    if run_id:
        _service_logger.info("任务运行 run_id=%s [%s/%s]", run_id, account_name, task_name)

    task_key = svc._task_key(account_name, task_name)
    svc._active_tasks[task_key] = True
    svc._active_logs[task_key] = []
    if run_id:
        svc._active_logs[task_key].append(f"[run_id={run_id}]")

    # 共享状态：所有 helper 读写同一字典
    state: Dict[str, Any] = {
        "svc": svc,
        "account_name": account_name,
        "task_name": task_name,
        "run_id": run_id,
        "task_key": task_key,
        "account_lock": account_lock,
        "settings": settings,
        "BackendUserSigner": BackendUserSigner,
        "TaskLogHandler": TaskLogHandler,
        "success": False,
        "error_msg": "",
        "output_str": "",
        "account_invalid_detected": False,
        "timed_out": False,
        "task_notify_on_failure": True,
        "task_notify_on_success": True,
        "task_cfg": None,
        "signer": None,
        "final_logs": [],
        "last_reply": "",
        "last_target_message": "",
        "failure_category": None,
    }

    try:
        await _runner_load_config(state)

        if not state.get("account_invalid_detected"):
            # 记录监听状态
            svc._active_logs[task_key].append(
                f"消息更新监听: {'开启' if state['requires_updates'] else '关闭'}"
            )
            if state["has_keyword_monitor"]:
                svc._active_logs[task_key].append(
                    "关键词监听说明: 该动作由后台常驻监听服务执行；"
                    "本次手动运行只会刷新并展示后台监听状态，不代表监听只运行一次。"
                )

            await _runner_check_account(state)

        if not state.get("account_invalid_detected"):
            await _runner_refresh_keyword_monitor(state)
            await _runner_acquire_lock(state)

    except Exception as e:
        await _runner_handle_error(state, e)
    finally:
        await _runner_finalize(state)

    # Periodic pruning of stale entries to prevent memory growth
    svc._prune_stale_entries()

    # 失败分类
    if not state["success"]:
        state["failure_category"] = classify_failure(
            error=state["error_msg"],
            output=state["output_str"],
            success=False,
        ).value
        if state["timed_out"]:
            state["failure_category"] = FailureCategory.TIMEOUT.value

    return {
        "success": state["success"],
        "output": state["output_str"],
        "error": state["error_msg"],
        "timed_out": state["timed_out"],
        "failure_category": state["failure_category"],
    }
