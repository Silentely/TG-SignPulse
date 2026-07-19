"""
签到任务执行主路径

从 SignTaskService 抽离，行为保持不变；service 仅委托调用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from backend.services.sign_tasks import SignTaskService


async def execute_sign_task(
    svc: "SignTaskService",
    account_name: str,
    task_name: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """运行任务并实时捕获日志（In-Process）。"""
    # 局部导入：与 SignTaskService 模块依赖对齐，避免循环 import
    import asyncio
    import logging
    import os
    import time
    import traceback

    from backend.services.sign_task_backend import BackendUserSigner, TaskLogHandler
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
    from backend.services.sign_tasks import (
        _service_logger,
        _task_retry_count_var,
        settings,
    )
    from backend.utils.account_locks import get_account_lock
    from backend.utils.names import validate_storage_name
    from backend.utils.proxy import build_proxy_dict
    from backend.utils.task_logs import extract_last_target_message
    from backend.utils.tg_session import (
        get_account_session_string,
        get_global_semaphore,
        get_session_mode,
        load_session_string_file,
    )
    from tg_signer.async_utils import create_logged_task
    from tg_signer.log_utils import safe_exception_summary, safe_traceback_preview

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
    _service_logger.debug(f"等待获取账号锁 {account_name}...")
    if run_id:
        _service_logger.info(f"任务运行 run_id={run_id} [{account_name}/{task_name}]")

    task_key = svc._task_key(account_name, task_name)
    svc._active_tasks[task_key] = True
    svc._active_logs[task_key] = []
    if run_id:
        svc._active_logs[task_key].append(f"[run_id={run_id}]")

    # 获取 logger 实例
    tg_logger = logging.getLogger("tg-signer")
    log_handler: Optional[TaskLogHandler] = None

    success = False
    error_msg = ""
    output_str = ""
    account_invalid_detected = False
    timed_out = False
    task_notify_on_failure = True
    task_notify_on_success = True
    task_cfg: Optional[Dict[str, Any]] = None
    signer: Optional[BackendUserSigner] = None

    try:
        # 执行路径读磁盘配置，不走 get_task（避免挂 active_run 的额外开销）
        task_dir = svc._resolve_task_dir(task_name, account_name)
        task_cfg = svc._load_task_config(task_dir) if task_dir else None
        if not task_cfg:
            raise ValueError(f"Task {task_name} does not exist or cannot be loaded")
        requires_updates = svc._task_requires_updates(task_cfg)
        has_keyword_monitor = svc._task_has_keyword_monitor(task_cfg)
        signer_no_updates = not requires_updates
        task_notify_on_failure = bool(task_cfg.get("notify_on_failure", True))
        task_notify_on_success = bool(task_cfg.get("notify_on_success", True))

        svc._update_run_phase(
            account_name,
            task_name,
            run_id=run_id,
            phase=PHASE_CHECKING_ACCOUNT,
            phase_detail=f"检查账号 {account_name}",
        )

        invalid_reason = await svc._check_account_before_task(
            account_name,
            task_name,
            no_updates=signer_no_updates,
            notify_on_failure=task_notify_on_failure,
        )
        if invalid_reason:
            account_invalid_detected = True
            error_msg = f"账号 {account_name} 登录已失效，请重新登录: {invalid_reason}"
            svc._active_logs[task_key].append(error_msg)
        else:
            if has_keyword_monitor:
                try:
                    from backend.services.keyword_monitor import (
                        get_keyword_monitor_service,
                    )

                    await get_keyword_monitor_service().restart_from_tasks()
                except Exception as exc:
                    svc._active_logs[task_key].append(
                        f"关键词后台监听刷新失败: {exc}"
                    )

            svc._update_run_phase(
                account_name,
                task_name,
                run_id=run_id,
                phase=PHASE_WAITING_LOCK,
                phase_detail=f"等待账号锁 {account_name}",
            )

            async with account_lock:
                last_end = svc._account_last_run_end.get(account_name)
                if last_end:
                    gap = time.time() - last_end
                    wait_seconds = svc._account_cooldown_seconds - gap
                    if wait_seconds > 0:
                        # 向上取整秒，便于 UI 展示剩余冷却
                        wait_i = max(1, int(wait_seconds) if wait_seconds == int(wait_seconds) else int(wait_seconds) + 1)
                        svc._update_run_phase(
                            account_name,
                            task_name,
                            run_id=run_id,
                            phase=PHASE_COOLDOWN,
                            phase_detail=f"等待账号冷却 {wait_i} 秒",
                            wait_seconds=float(wait_i),
                        )
                        svc._active_logs[task_key].append(
                            f"等待账号冷却 {wait_i} 秒"
                        )
                        await asyncio.sleep(wait_seconds)

                log_handler = TaskLogHandler(svc._active_logs[task_key])
                log_handler.setLevel(logging.INFO)
                log_handler.setFormatter(
                    logging.Formatter("%(asctime)s - %(message)s")
                )
                if tg_logger.getEffectiveLevel() > logging.INFO:
                    tg_logger.setLevel(logging.INFO)
                tg_logger.addHandler(log_handler)

                _service_logger.debug(f"已获取账号锁 {account_name}，开始执行任务 {task_name}")
                svc._active_logs[task_key].append(
                    f"开始执行任务: {task_name} (账号: {account_name})"
                )

                # 配置 API 凭据
                from backend.services.config import get_config_service

                config_service = get_config_service()
                tg_config = config_service.get_telegram_config()
                api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
                api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")

                try:
                    api_id = int(api_id) if api_id is not None else None
                except (TypeError, ValueError):
                    api_id = None

                if isinstance(api_hash, str):
                    api_hash = api_hash.strip()

                if not api_id or not api_hash:
                    raise ValueError("未配置 Telegram API ID 或 API Hash")

                session_dir = settings.resolve_session_dir()
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
                        account_invalid_detected = True
                        raise ValueError(f"账号 {account_name} 的 session_string 不存在")
                    use_in_memory = True
                else:
                    # File mode: prefer in-memory to avoid SQLite "database is locked"
                    # Try to load session_string from .session_string file as fallback
                    session_string = load_session_string_file(
                        session_dir, account_name
                    )
                    if session_string:
                        use_in_memory = True
                    else:
                        use_in_memory = False

                    if os.getenv("SIGN_TASK_FORCE_IN_MEMORY") == "0":
                        # Explicitly disabled in-memory mode
                        session_string = None
                        use_in_memory = False

                svc._active_logs[task_key].append(
                    f"消息更新监听: {'开启' if requires_updates else '关闭'}"
                )
                if has_keyword_monitor:
                    svc._active_logs[task_key].append(
                        "关键词监听说明: 该动作由后台常驻监听服务执行；本次手动运行只会刷新并展示后台监听状态，不代表监听只运行一次。"
                    )

                # 实例化 UserSigner (使用 BackendUserSigner)
                # 注意: UserSigner 内部会使用 get_client 复用 client
                signer = BackendUserSigner(
                    task_name=task_name,
                    session_dir=str(session_dir),
                    account=account_name,
                    workdir=svc.workdir,
                    proxy=proxy_dict,
                    session_string=session_string,
                    in_memory=use_in_memory,
                    api_id=api_id,
                    api_hash=api_hash,
                    no_updates=signer_no_updates,
                )

                # 流程重试：配置文件存在 retry_count 键用任务值，否则用全局设置
                from backend.services.runtime_settings import (
                    get_execution_timeout,
                    get_flow_retry_attempts,
                )

                raw_task_cfg = svc._load_raw_task_config_dict(
                    task_name, account_name
                )
                task_retry_count = resolve_effective_retry_count(
                    raw_task_cfg, get_flow_retry_attempts()
                )
                _task_retry_count_var.set(task_retry_count)

                # 执行任务（数据库锁冲突时重试，带超时保护）
                task_timeout = float(get_execution_timeout())
                svc._update_run_phase(
                    account_name,
                    task_name,
                    run_id=run_id,
                    phase=PHASE_RUNNING,
                    phase_detail=f"执行中（超时 {int(task_timeout)}s，重试 {task_retry_count}）",
                    wait_seconds=None,
                    timeout_seconds=task_timeout,
                    retry_count_effective=task_retry_count,
                )
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
                            timed_out = True
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

                svc._update_run_phase(
                    account_name,
                    task_name,
                    run_id=run_id,
                    phase=PHASE_FINALIZING,
                    phase_detail="写入执行历史",
                )
                success = True
                svc._active_logs[task_key].append("任务执行完成")

                # 增加缓冲时间，防止同账号连续执行任务时，Session文件锁尚未完全释放导致 "database is locked"
                await asyncio.sleep(2)

    except Exception as e:
        if is_timeout_error_message(str(e)) or timed_out:
            timed_out = True
        if account_invalid_detected or svc._is_invalid_session_error(e):
            account_invalid_detected = True
            invalid_message = str(e) or f"账号 {account_name} 登录已失效，请重新登录"
            await svc._mark_account_invalid(
                account_name,
                task_name,
                invalid_message,
                notify_on_failure=task_notify_on_failure,
            )
        # 脱敏异常摘要写入任务日志流（会持久化、API 展示、通知外发）
        _run_id_tag = f" [run_id={run_id}]" if run_id else ""
        error_msg = f"任务执行出错{_run_id_tag}: {safe_exception_summary(e, 300)}"
        svc._active_logs[task_key].append(error_msg)
        # 脱敏 traceback 写入任务日志流
        _tb = traceback.format_exc()
        _safe_tb = safe_traceback_preview(_tb, max_lines=6, max_line_chars=200)
        if _safe_tb:
            for _line in _safe_tb.splitlines():
                svc._active_logs[task_key].append(f"  {_line}")
        # 服务端日志保留完整 exc_info（仅写入本地日志文件，不外发）
        _service_logger.error(f"任务执行出错{_run_id_tag} [{account_name}/{task_name}]: {e}", exc_info=True)
    finally:
        svc._account_last_run_end[account_name] = time.time()
        try:
            if log_handler is not None:
                tg_logger.removeHandler(log_handler)

            # 保存执行记录
            final_logs = list(svc._active_logs.get(task_key, []))
            output_str = "\n".join(final_logs)

            last_reply = ""
            if success:
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
                                    last_reply = "[图片] " + reply_part.split("图片: ", 1)[-1].split("\n")[0].strip()
                                else:
                                    last_reply = reply_part.replace("\n", " ").strip()
                            else:
                                last_reply = reply_part.replace("\n", " ").strip()

                            if len(last_reply) > 200:
                                last_reply = last_reply[:197] + "..."
                        except Exception:
                            pass
                        if last_reply:
                            break
                if last_reply:
                    reply_lower = last_reply.lower()
                    failure_keywords = (
                        "失败",
                        "错误",
                        "异常",
                        "未成功",
                        "无法",
                        "failed",
                        "failure",
                        "error",
                        "invalid",
                        "not found",
                    )
                    if (
                        any(keyword in reply_lower for keyword in failure_keywords)
                        and svc._message_indicates_strong_failure(last_reply)
                    ):
                        success = False
                        error_msg = f"机器人回复疑似失败: {last_reply}"
                        final_logs.append(error_msg)
                        svc._active_logs.setdefault(task_key, []).append(error_msg)
                        output_str = "\n".join(final_logs)

            last_target_message = extract_last_target_message(final_logs)
            if success and not last_target_message and signer is not None:
                try:
                    last_target_fetch_timeout = float(
                        os.getenv("SIGN_TASK_LAST_TARGET_FETCH_TIMEOUT", "5")
                    )
                    if last_target_fetch_timeout > 0:
                        last_target_message = await asyncio.wait_for(
                            svc._fetch_last_target_message_from_chat_history(
                                signer,
                                task_cfg,
                            ),
                            timeout=last_target_fetch_timeout,
                        )
                    else:
                        last_target_message = await svc._fetch_last_target_message_from_chat_history(
                            signer,
                            task_cfg,
                        )
                except asyncio.TimeoutError:
                    timeout_log = (
                        f"补抓任务对象最后消息超时 ({last_target_fetch_timeout:.1f}s)，已跳过"
                    )
                    svc._active_logs.setdefault(task_key, []).append(timeout_log)
                    final_logs = list(svc._active_logs.get(task_key, []))
                    output_str = "\n".join(final_logs)
                    last_target_message = ""
                except Exception:
                    last_target_message = ""
            if success and last_target_message:
                last_reply = last_target_message
            if last_target_message and not any(
                "任务对象最后一条消息:" in str(line) for line in final_logs
            ):
                last_message_line = f"任务对象最后一条消息: {last_target_message}"
                final_logs.append(last_message_line)
                svc._active_logs.setdefault(task_key, []).append(last_message_line)
                output_str = "\n".join(final_logs)

            msg = error_msg if not success else last_reply
            svc._save_run_info(
                task_name,
                success,
                msg,
                account_name,
                flow_logs=final_logs,
            )

            if not success and not account_invalid_detected and task_notify_on_failure:
                await svc._send_failure_notification(
                    account_name,
                    task_name,
                    error_msg or msg,
                    last_target_message=last_target_message or None,
                    flow_logs=final_logs,
                )
            elif success and task_notify_on_success:
                await svc._send_success_notification(
                    account_name,
                    task_name,
                    message=str(msg or last_reply or ""),
                )
        finally:
            svc._active_tasks[task_key] = False

        # 延迟清理日志（同一 task_key 仅保留一个 cleanup 协程）
        old_cleanup_task = svc._cleanup_tasks.get(task_key)
        if old_cleanup_task and not old_cleanup_task.done():
            old_cleanup_task.cancel()

        async def cleanup():
            try:
                await asyncio.sleep(60)
                if not svc._active_tasks.get(task_key):
                    svc._active_logs.pop(task_key, None)
            finally:
                svc._cleanup_tasks.pop(task_key, None)

        svc._cleanup_tasks[task_key] = create_logged_task(
            cleanup(),
            logger=logging.getLogger("backend.sign_tasks"),
            description=f"active log cleanup {account_name}/{task_name}",
        )

    # Periodic pruning of stale entries to prevent memory growth
    svc._prune_stale_entries()

    failure_category = None
    if not success:
        failure_category = classify_failure(
            error=error_msg,
            output=output_str,
            success=False,
        ).value
        if timed_out:
            failure_category = FailureCategory.TIMEOUT.value

    return {
        "success": success,
        "output": output_str,
        "error": error_msg,
        "timed_out": timed_out,
        "failure_category": failure_category,
    }

