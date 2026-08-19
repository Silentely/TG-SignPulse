from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler: AsyncIOScheduler | None = None


def _parse_clock_time(value: str):
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid clock time: {value}")


def _resolve_scheduler_timezone():
    """解析调度器使用的时区（Web UI 全局设置优先，回退环境变量）；失败返回 None。"""
    try:
        from backend.core.config import get_settings
        from backend.services.config import get_config_service

        saved_settings = get_config_service().get_global_settings()
        tz_name = saved_settings.get("timezone") or get_settings().timezone
        if not tz_name:
            return None
        from zoneinfo import ZoneInfo

        return ZoneInfo(str(tz_name))
    except Exception as exc:
        logging.getLogger("backend.scheduler").debug(
            "解析调度器时区失败，使用本地时区: %s", exc
        )
        return None


def create_cron_trigger(cron_str: str, timezone: str = "") -> CronTrigger:
    """自动解析格式并创建 CronTrigger，支持 5位和6位 cron 表达式以及 HH:MM 或 HH:MM:SS"""
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
    tz = timezone
    if not tz:
        try:
            from backend.core.config import get_settings
            from backend.services.config import get_config_service
            saved_settings = get_config_service().get_global_settings()
            tz = saved_settings.get("timezone") or get_settings().timezone
        except (ImportError, AttributeError, ValueError, KeyError) as exc:
            logging.getLogger("backend.scheduler").debug(
                "读取全局时区配置失败，使用调度器默认时区: %s", exc
            )
            tz = ""

    parts = cron_str.split()
    if len(parts) == 6:
        return CronTrigger(
            second=parts[0],
            minute=parts[1],
            hour=parts[2],
            day=parts[3],
            month=parts[4],
            day_of_week=parts[5],
            timezone=tz or None,
        )
    return CronTrigger.from_crontab(cron_str, timezone=tz or None)



async def _job_run_sign_task(account_name: str, task_name: str) -> None:
    """运行签到任务的 Job 包装器"""
    import asyncio
    import random
    from datetime import timedelta

    from backend.services.sign_tasks import get_sign_task_service

    logger = logging.getLogger("backend.scheduler")
    try:
        logger.info("Scheduler: 正在运行签到任务 %s (账号: %s)", task_name, account_name)

        # 获取任务配置，检查是否为随机时间段模式
        sign_task_service = get_sign_task_service()
        task_config = sign_task_service.get_task(task_name, account_name)
        if task_config and task_config.get("execution_mode") == "range":
            range_start_str = task_config.get("range_start")
            range_end_str = task_config.get("range_end")

            if range_start_str and range_end_str:
                try:
                    # 解析时间
                    start_time = _parse_clock_time(range_start_str)
                    end_time = _parse_clock_time(range_end_str)

                    # 用应用时区锚定当前时刻（与 cron trigger 语义一致）：
                    # 原 naive datetime.now() 在进程 TZ 与 Web UI 时区不一致、
                    # 或窗口跨 DST 切换时会算错窗口
                    tz = _resolve_scheduler_timezone()
                    now = datetime.now(tz) if tz is not None else datetime.now()
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

                    # 如果结束时间小于开始时间，假设是第二天（虽然CRON触发通常在开始时间，这里做个防御）
                    if end_dt < start_dt:
                        end_dt += timedelta(days=1)

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
        # 打包 + WebDAV 上传均为同步阻塞操作，放入线程池避免冻结事件循环
        # （数据目录大时打包可能耗时数十秒，阻塞期间 API/SSE/调度全部停摆）
        result = await asyncio.to_thread(
            run_auto_backup,
            data_dir,
            keep=auto_backup_keep(cfg),
            webdav_settings=cfg,
        )
        wd = result.get("webdav") or {}
        logger.info(
            "Auto backup finished: path=%s size=%s pruned=%s remote_pruned=%s "
            "local_removed=%s webdav=%s webdav_error=%s",
            result.get("path"),
            result.get("size_bytes"),
            result.get("pruned"),
            result.get("remote_pruned"),
            result.get("local_removed"),
            wd.get("success"),
            wd.get("error"),
        )
        # 打包失败，或配置了 WebDAV 但上传失败 → 通知
        fail_reason = ""
        if not result.get("success"):
            fail_reason = str(result.get("error") or "备份打包失败")
        elif (cfg.get("webdav_url") or "").strip() and wd.get("success") is False:
            fail_reason = str(wd.get("error") or "WebDAV 上传失败")
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
    Sync APScheduler jobs from file-based sign tasks (legacy ORM tasks removed).
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
                if jid.startswith("db-") or jid.startswith("sign-"):
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

    # 同步签到任务 (SignTask)；旧 ORM db-* job 不再注册
    existing_ids = {
        job.id
        for job in scheduler.get_jobs()
        if str(job.id or "").startswith("db-") or str(job.id or "").startswith("sign-")
    }
    desired_ids = set()

    # 主动移除遗留 db-* 任务
    for job_id in list(existing_ids):
        if str(job_id).startswith("db-"):
            try:
                scheduler.remove_job(job_id)
            except JobLookupError:
                pass
            existing_ids.discard(job_id)

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
            trigger = create_cron_trigger(st["sign_at"])
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
        # 优先使用 Web UI 保存的时区，否则使用环境变量
        tz = settings.timezone
        try:
            saved_settings = get_config_service().get_global_settings()
            saved_tz = saved_settings.get("timezone")
            if saved_tz:
                tz = saved_tz
        except (ImportError, AttributeError, ValueError, KeyError) as exc:
            logging.getLogger("backend.scheduler").warning(
                "读取全局时区设置失败，使用默认时区 %s: %s", settings.timezone, exc
            )

        # 多实例场景：仅锁持有者注册业务调度
        try_acquire_scheduler_lock()

        scheduler = AsyncIOScheduler(
            timezone=tz,
            job_defaults={
                "misfire_grace_time": 3600,  # 允许任务延迟 1 小时执行
                "coalesce": True,  # 合并积压的执行
                "max_instances": 10,  # 增加并发实例数，避免多账号任务相互阻塞
            },
        )
        scheduler.start()

        # 添加每日凌晨 3 点执行的维护任务
        scheduler.add_job(
            _job_maintenance,
            trigger=CronTrigger.from_crontab("0 3 * * *"),
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
    account_name: str, task_name: str, cron_expression: str, enabled: bool = True
) -> None:
    """动态添加或更新签到任务 Job"""
    global scheduler
    if not scheduler:
        return

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"

    if not enabled:
        remove_sign_task_job(account_name, task_name)
        return

    try:
        cron = cron_expression
        trigger = create_cron_trigger(cron)

        # 总是使用 replace_existing=True 来覆盖旧的
        scheduler.add_job(
            _job_run_sign_task,
            trigger=trigger,
            id=job_id,
            args=[account_name, task_name],
            replace_existing=True,
        )
        logger.info("Scheduler: 已添加/更新任务 %s -> %s", job_id, cron)
    except (ValueError, KeyError, RuntimeError) as e:
        logger.error("Scheduler: 添加任务 %s 失败（参数或调度器错误）: %s", job_id, e)
    except Exception:
        logger.exception("Scheduler: 添加任务 %s 发生未知异常", job_id)


def remove_sign_task_job(account_name: str, task_name: str) -> None:
    """动态移除签到任务 Job"""
    from apscheduler.jobstores.base import JobLookupError

    global scheduler
    if not scheduler:
        return

    logger = logging.getLogger("backend.scheduler")
    job_id = f"sign-{account_name}-{task_name}"
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("Scheduler: 已移除任务 %s", job_id)
    except (JobLookupError, RuntimeError) as e:
        logger.error("Scheduler: 移除任务 %s 失败（调度器状态错误）: %s", job_id, e)
    except Exception:
        logger.exception("Scheduler: 移除任务 %s 发生未知异常", job_id)
