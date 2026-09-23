from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler: AsyncIOScheduler | None = None
_ADAPTIVE_NEXT_RUNS: dict[str, datetime] = {}
_RANGE_COMPENSATION_RUNS: dict[str, datetime] = {}


def _parse_clock_time(value: str):
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid clock time: {value}")


def _read_configured_timezone_name() -> str:
    """读取配置的时区名称（Web UI 全局设置优先，回退环境变量）；未配置返回空串。"""
    try:
        from backend.core.config import get_settings
        from backend.services.config import get_config_service

        saved_settings = get_config_service().get_global_settings()
        return str(saved_settings.get("timezone") or get_settings().timezone or "")
    except Exception as exc:
        logging.getLogger("backend.scheduler").debug(
            "读取全局时区配置失败，使用调度器默认时区: %s", exc
        )
        return ""


def _resolve_scheduler_timezone():
    """解析调度器使用的时区（Web UI 全局设置优先，回退环境变量）；失败返回 None。"""
    tz_name = _read_configured_timezone_name()
    if not tz_name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception as exc:
        logging.getLogger("backend.scheduler").debug(
            "解析调度器时区失败，使用本地时区: %s", exc
        )
        return None


def create_cron_trigger(cron_str: str, timezone: str = "", jitter: int = 0) -> CronTrigger:
    """自动解析格式并创建 CronTrigger，支持 5位和6位 cron 表达式以及 HH:MM 或 HH:MM:SS。"""
    if ":" in cron_str:
        parts = cron_str.split(":")
        try:
            if len(parts) == 2:
                hour, minute = parts
                cron_str = f"0 {int(minute)} {int(hour)} * * *"
            elif len(parts) == 3:
                hour, minute, second = parts
                cron_str = f"{int(second)} {int(minute)} {int(hour)} * * *"
        except ValueError as exc:
            logging.getLogger("backend.scheduler").debug(
                "clock-time cron parse failed for %r: %s", cron_str, exc
            )

    # 获取有效时区：优先使用传入参数，否则从全局配置回退到环境变量
    tz = timezone or _read_configured_timezone_name()

    parts = cron_str.split()
    if len(parts) == 6:
        trigger = CronTrigger(
            second=parts[0],
            minute=parts[1],
            hour=parts[2],
            day=parts[3],
            month=parts[4],
            day_of_week=parts[5],
            timezone=tz or None,
            jitter=jitter if jitter > 0 else None,
        )
        return trigger
    trigger = CronTrigger.from_crontab(cron_str, timezone=tz or None)
    if jitter > 0:
        trigger.jitter = jitter
    return trigger


def _get_range_window(
    range_start_str: str,
    range_end_str: str,
    now: datetime,
) -> tuple[datetime, datetime] | None:
    """计算当前时刻对应的 range 时间窗口 [start_dt, end_dt)"""
    try:
        start_time = _parse_clock_time(range_start_str)
        end_time = _parse_clock_time(range_end_str)
    except Exception:
        return None

    start_dt = now.replace(
        hour=start_time.hour,
        minute=start_time.minute,
        second=start_time.second,
        microsecond=0,
    )
    end_dt = now.replace(
        hour=end_time.hour,
        minute=end_time.minute,
        second=end_time.second,
        microsecond=0,
    )

    if end_dt <= start_dt:
        # 跨天窗口（例如 22:00 到 06:00）
        if now < end_dt:
            # 凌晨时段，窗口始于前一天
            start_dt -= timedelta(days=1)
        else:
            # 夜间时段，窗口延续到次日
            end_dt += timedelta(days=1)

    return start_dt, end_dt


def _compute_range_task_compensation(
    task_config: dict[str, Any],
    tz: ZoneInfo | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """检查 range 模式任务在当前时间窗口内是否需要补偿执行。

    如果当前处于窗口内，且本周期内尚未成功执行，则在剩余时间窗口内随机生成一个执行时间。
    若无需补偿或已执行过，则返回 None。
    """
    if not isinstance(task_config, dict):
        return None
    if task_config.get("execution_mode") != "range":
        return None

    range_start_str = task_config.get("range_start")
    range_end_str = task_config.get("range_end")
    if not range_start_str or not range_end_str:
        return None

    if now is None:
        now = datetime.now(tz) if tz is not None else datetime.now()

    window = _get_range_window(range_start_str, range_end_str, now)
    if not window:
        return None
    start_dt, end_dt = window

    # 当前不在时间窗口内，无需补偿（由常规 CronTrigger 在窗口起点触发）
    if not (start_dt <= now < end_dt):
        return None

    # 检查是否已在当前窗口内成功执行过
    last_run = task_config.get("last_run")
    if not isinstance(last_run, dict):
        try:
            from backend.services.sign_tasks import get_sign_task_service

            svc = get_sign_task_service()
            task_name = str(task_config.get("name") or "")
            account_name = str(task_config.get("account_name") or "")
            task_dir = svc._resolve_task_dir(task_name, account_name or None)
            last_run = svc._get_last_run_info(task_dir, account_name)
        except Exception:
            last_run = None

    if isinstance(last_run, dict) and last_run.get("time"):
        try:
            last_run_str = str(last_run["time"]).strip()
            if last_run_str.endswith("Z"):
                last_run_str = last_run_str[:-1] + "+00:00"
            last_run_dt = datetime.fromisoformat(last_run_str)
            if last_run_dt.tzinfo is not None and tz is not None:
                last_run_dt = last_run_dt.astimezone(tz)
            elif last_run_dt.tzinfo is None and tz is not None:
                last_run_dt = last_run_dt.replace(tzinfo=tz)

            # 如果本周期内已经有成功执行记录，则不补偿
            if last_run_dt >= start_dt and last_run.get("success") is True:
                return None
        except Exception:
            pass

    # 计算窗口剩余秒数并在剩余时间内生成随机延迟
    remaining_seconds = max(0.0, (end_dt - now).total_seconds())
    if remaining_seconds <= 15.0:
        delay_seconds = min(2.0, remaining_seconds)
    else:
        max_delay = max(5.0, remaining_seconds - 5.0)
        delay_seconds = random.uniform(5.0, max_delay)

    return now + timedelta(seconds=delay_seconds)


async def _job_run_sign_task(account_name: str, task_name: str) -> None:
    """运行签到任务的 Job 包装器"""
    from backend.services.sign_tasks import get_sign_task_service

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"
    is_compensation = job_id in _RANGE_COMPENSATION_RUNS
    if is_compensation:
        _RANGE_COMPENSATION_RUNS.pop(job_id, None)
        logger.info(
            "Scheduler: 任务 %s (账号=%s) 处于补偿执行时间点，跳过时间段延迟直接执行",
            task_name,
            account_name,
        )

    try:
        logger.info("Scheduler: 正在运行签到任务 %s (账号: %s)", task_name, account_name)

        # 获取任务配置，检查是否为随机时间段模式
        sign_task_service = get_sign_task_service()
        task_config = sign_task_service.get_task(task_name, account_name)
        if task_config and task_config.get("execution_mode") == "range":
            if not is_compensation:
                range_start_str = task_config.get("range_start")
                range_end_str = task_config.get("range_end")
                if range_start_str and range_end_str:
                    try:
                        # 用应用时区锚定当前时刻（与 cron trigger 语义一致）：
                        # 原 naive datetime.now() 在进程 TZ 与 Web UI 时区不一致、
                        # 或窗口跨 DST 切换时会算错窗口
                        tz = _resolve_scheduler_timezone()
                        now = datetime.now(tz) if tz is not None else datetime.now()
                        # 窗口计算统一走 _get_range_window：跨天窗口（22:00→06:00）
                        # 在凌晨迟到触发时必须回退 start_dt 一天，否则窗口会被算成
                        # 32 小时，随机延迟可能把执行推到数小时后、远超 range_end
                        window = _get_range_window(range_start_str, range_end_str, now)
                        if window is None:
                            raise ValueError(
                                f"无法解析时间段 {range_start_str}-{range_end_str}"
                            )
                        start_dt, end_dt = window

                        # 计算总秒数
                        total_seconds = (end_dt - start_dt).total_seconds()

                        if total_seconds > 0:
                            # 生成随机延迟；misfire/迟到触发时截断到窗口剩余时间，
                            # 避免把执行推过 range_end
                            remaining = max(0.0, (end_dt - now).total_seconds())
                            delay_seconds = min(random.uniform(0, total_seconds), remaining)
                            logger.debug(
                                "Scheduler: 任务 %s (账号=%s) 设置为随机时间段模式 (%s - %s)",
                                task_name,
                                account_name,
                                range_start_str,
                                range_end_str,
                            )
                            logger.debug(
                                "Scheduler: 将随机等待 %d 秒 (%.2f 分钟) 后执行",
                                int(delay_seconds),
                                delay_seconds / 60,
                            )

                            await asyncio.sleep(delay_seconds)

                    except (ValueError, KeyError, TypeError) as e:
                        logger.error(
                            "Scheduler: 计算随机时间段延迟失败 (账号=%s, 任务=%s): %s，将立即执行",
                            account_name,
                            task_name,
                            e,
                            exc_info=True,
                        )
        elif task_config:
            _ADAPTIVE_NEXT_RUNS.pop(job_id, None)
            # 错峰延迟由 CronTrigger 的 jitter 承担（见 create_cron_trigger），
            # 此处不再重复 sleep，避免实际延迟达到配置上限的两倍

        # run_task_with_logs 是 async 的，我们使用它（service 已在上方获取）
        result = await sign_task_service.run_task_with_logs(account_name, task_name)
        if result.get("success"):
            logger.info("Scheduler: 任务 %s 执行成功", task_name)
        else:
            logger.error(
                "Scheduler: 任务 %s 执行失败 (账号=%s): %s",
                task_name,
                account_name,
                result.get('error'),
            )
    except Exception as e:
        # 顶层兜底：Job 执行入口不能让异常逃逸到调度器导致后续任务被压制
        logger.error(
            "Scheduler: 运行签到任务 %s 失败 (账号=%s): %s",
            task_name,
            account_name,
            e,
            exc_info=True,
        )


async def _job_maintenance() -> None:
    """每日维护任务：清理签到历史与内存状态。"""
    try:
        from backend.services.sign_tasks import get_sign_task_service

        sign_service = get_sign_task_service()
        sign_service._cleanup_old_logs()
        sign_service._prune_stale_entries()
    except Exception as exc:
        logging.getLogger("backend.scheduler").warning(
            "Maintenance job failed: %s", exc, exc_info=True
        )


async def _job_device_keepalive() -> None:
    """定期保活 Telegram 授权设备/会话，避免长期不活跃被自动踢下线。"""
    logger = logging.getLogger("backend.scheduler")
    try:
        from backend.services.device_keepalive import get_device_keepalive_service

        result = await get_device_keepalive_service().run_due()
        logger.info(
            "Device keepalive finished: checked=%s ok=%s skipped=%s failed=%s",
            result.get("checked"),
            result.get("kept_alive"),
            result.get("skipped"),
            result.get("failed"),
        )
    except Exception as exc:
        # 顶层兜底：保活 Job 失败不能阻塞调度器
        logger.error("设备保活任务失败: %s", exc, exc_info=True)


async def _job_auto_backup() -> None:
    """按全局设置执行自动备份。"""
    from pathlib import Path

    logger = logging.getLogger("backend.scheduler")
    cfg: dict = {}
    try:
        from backend.core.config import get_settings
        from backend.services.backup_archive import (
            auto_backup_keep,
            run_auto_backup,
            should_run_auto_backup,
        )
        from backend.services.config import get_config_service
        from backend.services.push_notifications import (
            send_auto_backup_failure_notification,
        )

        cfg = get_config_service().get_global_settings()
        if not should_run_auto_backup(cfg):
            return
        data_dir = Path(get_settings().resolve_base_dir())
        # 打包 + 远端上传均为同步阻塞操作，放入线程池避免冻结事件循环
        # （数据目录大时打包可能耗时数十秒，阻塞期间 API/SSE/调度全部停摆）
        result = await asyncio.to_thread(
            run_auto_backup,
            data_dir,
            keep=auto_backup_keep(cfg),
            webdav_settings=cfg,
            s3_settings=cfg,
        )
        wd = result.get("webdav") or {}
        s3 = result.get("s3") or {}
        logger.info(
            "Auto backup finished: path=%s size=%s pruned=%s remote_pruned=%s "
            "local_removed=%s webdav=%s webdav_error=%s s3=%s s3_error=%s",
            result.get("path"),
            result.get("size_bytes"),
            result.get("pruned"),
            result.get("remote_pruned"),
            result.get("local_removed"),
            wd.get("success"),
            wd.get("error"),
            s3.get("success"),
            s3.get("error"),
        )
        # 打包失败，或配置了远端但上传失败 → 通知（WebDAV 优先，与上传顺序一致）
        fail_reason = ""
        if not result.get("success"):
            fail_reason = str(result.get("error") or "备份打包失败")
        elif (cfg.get("webdav_url") or "").strip() and wd.get("success") is False:
            fail_reason = str(wd.get("error") or "WebDAV 上传失败")
        elif not (cfg.get("webdav_url") or "").strip() and s3 and s3.get("success") is False:
            fail_reason = str(s3.get("error") or "对象存储上传失败")
        if fail_reason:
            await send_auto_backup_failure_notification(
                cfg,
                error=fail_reason,
                detail=f"path={result.get('path') or '-'}",
            )
    except Exception as exc:
        # 顶层兜底：自动备份 Job 失败不能阻塞调度器，但要推送告警
        logger.error("自动备份任务失败: %s", exc, exc_info=True)
        try:
            from backend.services.push_notifications import (
                send_auto_backup_failure_notification,
            )

            if cfg:
                await send_auto_backup_failure_notification(
                    cfg, error=str(exc), detail="scheduler exception"
                )
        except Exception:
            logger.exception("自动备份失败通知也发送失败")


def _sync_auto_backup_job() -> None:
    """根据全局设置注册/移除自动备份 interval job。"""
    global scheduler
    if scheduler is None:
        return

    from apscheduler.jobstores.base import JobLookupError
    from apscheduler.triggers.interval import IntervalTrigger

    logger = logging.getLogger("backend.scheduler")
    job_id = "system-auto-backup"
    try:
        from backend.services.backup_archive import (
            auto_backup_interval_hours,
            should_run_auto_backup,
        )
        from backend.services.config import get_config_service

        cfg = get_config_service().get_global_settings()
        if should_run_auto_backup(cfg):
            hours = auto_backup_interval_hours(cfg)
            scheduler.add_job(
                _job_auto_backup,
                trigger=IntervalTrigger(hours=hours),
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("自动备份任务已注册：每 %s 小时", hours)
        else:
            try:
                scheduler.remove_job(job_id)
            except JobLookupError:
                # job 不存在时静默忽略
                pass
    except (ImportError, AttributeError, ValueError, KeyError, RuntimeError) as exc:
        logger.warning("同步自动备份任务失败: %s", exc)
    except Exception:
        # 兜底：未知异常不阻塞 sync 流程，记录完整堆栈便于排障
        logger.exception("同步自动备份任务发生未知异常")


async def sync_jobs() -> None:
    """
    Sync APScheduler jobs from file-based sign tasks.
    """
    if scheduler is None:
        return

    # 每次同步时检查时区是否变更，运行时无法直接修改调度器时区，仅记录日志
    from apscheduler.jobstores.base import JobLookupError

    from backend.scheduler.instance_lock import has_scheduler_lock
    _tz_logger = logging.getLogger("backend.scheduler")
    if not has_scheduler_lock():
        # 无锁副本：移除业务 job，避免误调度
        if getattr(scheduler, "running", False):
            for job in list(scheduler.get_jobs()):
                jid = str(job.id or "")
                if jid.startswith("sign-"):
                    try:
                        scheduler.remove_job(jid)
                    except JobLookupError:
                        # job 已被移除，静默忽略
                        pass
        _tz_logger.info("本进程未持有调度锁，已跳过业务任务同步")
        return
    try:
        from backend.core.config import get_settings
        from backend.services.config import get_config_service

        saved_settings = get_config_service().get_global_settings()
        saved_tz = saved_settings.get("timezone")
        desired_tz = saved_tz or get_settings().timezone
        scheduler_tz = str(getattr(scheduler, 'timezone', ''))
        if desired_tz and desired_tz != scheduler_tz:
            _tz_logger.info("时区已变更 (%s → %s)，将在下次调度器重启后生效", scheduler_tz, desired_tz)
        _sync_auto_backup_job()
    except (ImportError, AttributeError, ValueError, KeyError) as e:
        _tz_logger.warning("时区变更检测失败: %s", e)
    except Exception:
        _tz_logger.exception("时区变更检测发生未知异常")

    from backend.services.sign_tasks import get_sign_task_service

    # 同步签到任务 (SignTask)
    existing_ids = {
        job.id
        for job in scheduler.get_jobs()
        if str(job.id or "").startswith("sign-")
    }
    desired_ids = set()

    sign_task_service = get_sign_task_service()
    # Expand wildcard tasks for newly added accounts
    sign_task_service._expand_wildcard_tasks()
    sign_tasks = sign_task_service.list_tasks(force_refresh=True)
    for st in sign_tasks:
        account_name = str(st.get("account_name") or "").strip()
        task_name = str(st.get("name") or "").strip()
        if not account_name or not task_name:
            # 只记录缺失的标识，不打印完整任务 dict（可能含账号等敏感配置）
            logging.getLogger("backend.scheduler").warning(
                "跳过缺少 账号/任务名 的签到任务调度 (account=%r name=%r)",
                st.get("account_name"),
                st.get("name"),
            )
            continue

        job_id = f"sign-{account_name}-{task_name}"
        desired_ids.add(job_id)

        if not st.get("enabled", True):
            if job_id in existing_ids:
                try:
                    scheduler.remove_job(job_id)
                except JobLookupError:
                    # 并发 sync 下 job 可能已被其他协程移除，静默忽略
                    pass
            continue

        if st.get("execution_mode") == "listen":
            if job_id in existing_ids:
                try:
                    scheduler.remove_job(job_id)
                except JobLookupError:
                    pass
            continue

        try:
            jitter = int(st.get("jitter_seconds") or 0)
            trigger = create_cron_trigger(st["sign_at"], jitter=jitter)
            if st.get("execution_mode") == "range" and st.get("range_start"):
                trigger = create_cron_trigger(st["range_start"])

            if job_id in existing_ids:
                scheduler.reschedule_job(job_id, trigger=trigger)
            else:
                scheduler.add_job(
                    _job_run_sign_task,
                    trigger=trigger,
                    id=job_id,
                    args=[account_name, task_name],
                    replace_existing=True,
                )

            if job_id in _ADAPTIVE_NEXT_RUNS:
                target_dt = _ADAPTIVE_NEXT_RUNS[job_id]
                now_dt = datetime.now(target_dt.tzinfo) if target_dt.tzinfo else datetime.now()
                if target_dt > now_dt:
                    job = scheduler.get_job(job_id)
                    if job:
                        job.modify(next_run_time=target_dt)
                else:
                    _ADAPTIVE_NEXT_RUNS.pop(job_id, None)
            elif st.get("execution_mode") == "range":
                tz = getattr(scheduler, "timezone", None) or _resolve_scheduler_timezone()
                if job_id in _RANGE_COMPENSATION_RUNS:
                    target_dt = _RANGE_COMPENSATION_RUNS[job_id]
                    now_dt = datetime.now(target_dt.tzinfo) if target_dt.tzinfo else datetime.now()
                    if target_dt > now_dt:
                        job = scheduler.get_job(job_id)
                        if job:
                            job.modify(next_run_time=target_dt)
                    else:
                        _RANGE_COMPENSATION_RUNS.pop(job_id, None)
                else:
                    comp_dt = _compute_range_task_compensation(st, tz=tz)
                    if comp_dt:
                        _RANGE_COMPENSATION_RUNS[job_id] = comp_dt
                        job = scheduler.get_job(job_id)
                        if job:
                            job.modify(next_run_time=comp_dt)
                            logging.getLogger("backend.scheduler").info(
                                "Scheduler: 任务 %s (账号=%s) 处于时间段窗口内且今日未成功执行，已安排补偿执行: %s",
                                task_name,
                                account_name,
                                comp_dt,
                            )
        except (ValueError, KeyError, RuntimeError) as e:
            logging.getLogger("backend.scheduler").warning(
                "Error scheduling sign task %s: %s", task_name, e
            )
        except Exception:
            logging.getLogger("backend.scheduler").exception(
                "调度签到任务 %s 发生未知异常", task_name
            )

    # remove obsolete jobs
    for job_id in existing_ids - desired_ids:
        try:
            scheduler.remove_job(job_id)
        except JobLookupError:
            # 并发 sync 下 job 可能已被其他协程移除，静默忽略
            pass


async def init_scheduler(sync_on_startup: bool = True) -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        from backend.core.config import get_settings
        from backend.scheduler.instance_lock import try_acquire_scheduler_lock
        from backend.services.config import get_config_service

        settings = get_settings()
        job_defaults = {
            "misfire_grace_time": 3600,
            "coalesce": True,
            "max_instances": 10,
        }
        try:
            saved_settings = get_config_service().get_global_settings()
            saved_tz = saved_settings.get("timezone")
            tz = saved_tz or settings.timezone
        except Exception:
            tz = settings.timezone

        # 尝试抢占调度锁（单实例运行）
        has_lock = try_acquire_scheduler_lock()
        if not has_lock:
            logging.getLogger("backend.scheduler").warning(
                "当前实例未获取到调度锁，将以只读/备用模式运行调度器（不执行实际调度）"
            )
            scheduler = AsyncIOScheduler(timezone=tz, job_defaults=job_defaults)
            scheduler.start()
            return scheduler

        scheduler = AsyncIOScheduler(timezone=tz, job_defaults=job_defaults)
        scheduler.start()

        # 添加每日维护任务（清理签到历史等）
        scheduler.add_job(
            _job_maintenance,
            trigger=CronTrigger.from_crontab("0 4 * * *"),
            id="system-maintenance",
            replace_existing=True,
        )

        # 添加每日凌晨 3:30 执行的设备保活任务
        scheduler.add_job(
            _job_device_keepalive,
            trigger=CronTrigger.from_crontab("30 3 * * *"),
            id="system-device-keepalive",
            replace_existing=True,
        )

        _sync_auto_backup_job()

        if sync_on_startup:
            await sync_jobs()
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler:
        try:
            if getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)
        except RuntimeError as exc:
            # 调度器已停止或未运行时静默忽略
            logging.getLogger("backend.scheduler").debug(
                "调度器关闭时已停止运行: %s", exc
            )
        except Exception:
            logging.getLogger("backend.scheduler").exception(
                "调度器关闭发生未知异常"
            )
        scheduler = None
    try:
        from backend.scheduler.instance_lock import release_scheduler_lock

        release_scheduler_lock()
    except Exception:
        logging.getLogger("backend.scheduler").exception(
            "释放调度锁发生未知异常"
        )
        scheduler = None


def add_or_update_sign_task_job(
    account_name: str,
    task_name: str,
    cron_expression: str,
    enabled: bool = True,
    jitter: int = 0,
) -> None:
    """动态添加或更新签到任务 Job"""
    from backend.scheduler.instance_lock import has_scheduler_lock

    global scheduler
    if not scheduler or not has_scheduler_lock():
        return

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"

    if not enabled:
        remove_sign_task_job(account_name, task_name)
        return

    try:
        cron = cron_expression
        trigger = create_cron_trigger(cron, jitter=jitter)

        # 总是使用 replace_existing=True 来覆盖旧的
        scheduler.add_job(
            _job_run_sign_task,
            trigger=trigger,
            id=job_id,
            args=[account_name, task_name],
            replace_existing=True,
        )
        logger.info("Scheduler: 已添加/更新任务 %s -> %s (jitter=%s)", job_id, cron, jitter)

        # 检查是否为 range 模式任务且需补偿调度
        try:
            from backend.services.sign_tasks import get_sign_task_service

            task_cfg = get_sign_task_service().get_task(task_name, account_name)
            if task_cfg and task_cfg.get("execution_mode") == "range":
                tz = getattr(scheduler, "timezone", None) or _resolve_scheduler_timezone()
                comp_dt = _compute_range_task_compensation(task_cfg, tz=tz)
                if comp_dt:
                    _RANGE_COMPENSATION_RUNS[job_id] = comp_dt
                    job = scheduler.get_job(job_id)
                    if job:
                        job.modify(next_run_time=comp_dt)
                        logger.info(
                            "Scheduler: 动态更新任务 %s (账号=%s) 处于时间段窗口内且未成功执行，已安排补偿执行: %s",
                            task_name,
                            account_name,
                            comp_dt,
                        )
        except Exception as exc:
            logger.debug("Scheduler: 检查任务 %s 补偿异常: %s", job_id, exc)
    except (ValueError, KeyError, RuntimeError) as e:
        logger.error("Scheduler: 添加任务 %s 失败（参数或调度器错误）: %s", job_id, e)
    except Exception:
        logger.exception("Scheduler: 添加任务 %s 发生未知异常", job_id)


def remove_sign_task_job(account_name: str, task_name: str) -> None:
    """动态移除签到任务 Job"""
    from apscheduler.jobstores.base import JobLookupError

    from backend.scheduler.instance_lock import has_scheduler_lock

    global scheduler
    if not scheduler or not has_scheduler_lock():
        return

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"
    _ADAPTIVE_NEXT_RUNS.pop(job_id, None)
    _RANGE_COMPENSATION_RUNS.pop(job_id, None)
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("Scheduler: 已移除任务 %s", job_id)
    except (JobLookupError, RuntimeError) as e:
        logger.error("Scheduler: 移除任务 %s 失败（调度器状态错误）: %s", job_id, e)
    except Exception:
        logger.exception("Scheduler: 移除任务 %s 发生未知异常", job_id)


def reschedule_sign_task_once(
    account_name: str,
    task_name: str,
    run_at: datetime,
) -> bool:
    """动态修改指定签到任务的下一次触发时间（单次调整，不影响 cron 原定义）。

    Returns:
        bool: True 表示成功调整，False 表示未找到任务或调度器未就绪。
    """
    global scheduler
    if not scheduler:
        return False

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"
    try:
        _ADAPTIVE_NEXT_RUNS[job_id] = run_at
        job = scheduler.get_job(job_id)
        if job:
            job.modify(next_run_time=run_at)
            logger.info("Scheduler: 动态调整任务 %s 下次运行时间为: %s", job_id, run_at)
            return True
        logger.debug("Scheduler: 未找到任务 %s，无法动态调整运行时间", job_id)
        return False
    except Exception as e:
        logger.warning("Scheduler: 动态调整任务 %s 运行时间失败: %s", job_id, e)
        return False
