from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from backend.core.database import get_session_local
from backend.models.task import Task
from backend.services.tasks import run_task_once

scheduler: AsyncIOScheduler | None = None


def _parse_clock_time(value: str):
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid clock time: {value}")


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
        except ValueError:
            pass

    # 获取有效时区：优先使用传入参数，否则从全局配置回退到环境变量
    tz = timezone
    if not tz:
        try:
            from backend.core.config import get_settings
            from backend.services.config import get_config_service
            saved_settings = get_config_service().get_global_settings()
            tz = saved_settings.get("timezone") or get_settings().timezone
        except Exception:
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


async def _job_run_task(task_id: int) -> None:
    db: Session = get_session_local()()
    try:
        # 这里的查询是同步的，对于 SQLite 且任务量不大可以接受
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not task.enabled:
            return
        # run_task_once 将被改为 async
        await run_task_once(db, task)
    finally:
        db.close()


async def _job_run_sign_task(account_name: str, task_name: str) -> None:
    """运行签到任务的 Job 包装器"""
    import asyncio
    import logging
    import random
    from datetime import datetime, timedelta

    from backend.services.sign_tasks import get_sign_task_service

    logger = logging.getLogger("backend.scheduler")
    try:
        logger.info(f"Scheduler: 正在运行签到任务 {task_name} (账号: {account_name})")

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

                    # 转换为当前日期的 datetime
                    now = datetime.now()
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
                        # 生成随机延迟
                        delay_seconds = random.uniform(0, total_seconds)
                        logger.info(
                            f"Scheduler: 任务 {task_name} 设置为随机时间段模式 ({range_start_str} - {range_end_str})"
                        )
                        logger.info(
                            f"Scheduler: 将随机等待 {int(delay_seconds)} 秒 ({delay_seconds / 60:.2f} 分钟) 后执行"
                        )

                        await asyncio.sleep(delay_seconds)

                except Exception as e:
                    logger.error(f"Scheduler: 计算随机时间段延迟失败: {e}，将立即执行")

        # run_task_with_logs 是 async 的，我们使用它
        sign_task_service = get_sign_task_service()
        result = await sign_task_service.run_task_with_logs(account_name, task_name)
        if result.get("success"):
            logger.info(f"Scheduler: 任务 {task_name} 执行成功")
        else:
            logger.error(f"Scheduler: 任务 {task_name} 执行失败: {result.get('error')}")
    except Exception as e:
        logger.error(f"Scheduler: 运行签到任务 {task_name} 失败: {e}", exc_info=True)


async def _job_maintenance() -> None:
    """每日维护任务：清理旧日志等"""
    db: Session = get_session_local()()
    try:
        from backend.services.sign_tasks import get_sign_task_service
        from backend.services.tasks import cleanup_old_logs

        # 清理数据库任务日志
        count = cleanup_old_logs(db, days=3)
        print(f"Maintenance: 已清理 {count} 条数据库任务日志")

        # 清理签到任务日志
        sign_service = get_sign_task_service()
        sign_service._cleanup_old_logs()

        # 清理内存中的过期状态
        sign_service._prune_stale_entries()
    finally:
        db.close()


async def _job_device_keepalive() -> None:
    """定期保活 Telegram 授权设备/会话，避免长期不活跃被自动踢下线。"""
    import logging

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
        logger.error("Device keepalive job failed: %s", exc, exc_info=True)


async def _job_auto_backup() -> None:
    """按全局设置执行自动备份。"""
    import logging
    from pathlib import Path

    logger = logging.getLogger("backend.scheduler")
    try:
        from backend.core.config import get_settings
        from backend.services.backup_archive import (
            auto_backup_keep,
            run_auto_backup,
            should_run_auto_backup,
        )
        from backend.services.config import get_config_service

        cfg = get_config_service().get_global_settings()
        if not should_run_auto_backup(cfg):
            return
        data_dir = Path(get_settings().resolve_base_dir())
        result = run_auto_backup(data_dir, keep=auto_backup_keep(cfg))
        logger.info(
            "Auto backup finished: path=%s size=%s pruned=%s",
            result.get("path"),
            result.get("size_bytes"),
            result.get("pruned"),
        )
    except Exception as exc:
        logger.error("Auto backup job failed: %s", exc, exc_info=True)


def _sync_auto_backup_job() -> None:
    """根据全局设置注册/移除自动备份 interval job。"""
    global scheduler
    if scheduler is None:
        return
    import logging

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
            )
            logger.info("Auto backup job registered: every %sh", hours)
        else:
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("同步自动备份任务失败: %s", exc)


async def sync_jobs() -> None:
    """
    Sync APScheduler jobs from DB tasks table and file-based sign tasks.
    """
    if scheduler is None:
        return

    # 每次同步时检查时区是否变更，运行时无法直接修改调度器时区，仅记录日志
    import logging

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
                    except Exception:
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
            _tz_logger.info(f"时区已变更 ({scheduler_tz} → {desired_tz})，将在下次调度器重启后生效")
        _sync_auto_backup_job()
    except Exception as e:
        _tz_logger.warning(f"时区变更检测失败: {e}")

    from backend.services.sign_tasks import get_sign_task_service

    db: Session = get_session_local()()
    try:
        # 1. 同步数据库任务
        tasks = db.query(Task).filter(Task.enabled).all()
        existing_ids = {
            job.id
            for job in scheduler.get_jobs()
            if job.id.startswith("db-") or job.id.startswith("sign-")
        }
        desired_ids = set()

        for task in tasks:
            job_id = f"db-{task.id}"
            desired_ids.add(job_id)

            try:
                trigger = create_cron_trigger(task.cron)
                if job_id in existing_ids:
                    scheduler.reschedule_job(job_id, trigger=trigger)
                else:
                    scheduler.add_job(
                        _job_run_task,
                        trigger=trigger,
                        id=job_id,
                        args=[task.id],
                        replace_existing=True,
                    )
            except Exception as e:
                print(f"Error scheduling DB task {task.id}: {e}")

        # 2. 同步签到任务 (SignTask)
        # 使用缓存的任务列表，减少 I/O
        sign_task_service = get_sign_task_service()
        # Expand wildcard tasks for newly added accounts
        sign_task_service._expand_wildcard_tasks()
        sign_tasks = sign_task_service.list_tasks(force_refresh=True)
        for st in sign_tasks:
            account_name = str(st.get("account_name") or "").strip()
            task_name = str(st.get("name") or "").strip()
            if not account_name or not task_name:
                print(f"Skip scheduling sign task with missing account/name: {st}")
                continue

            job_id = f"sign-{account_name}-{task_name}"
            desired_ids.add(job_id)

            # SignTask 目前默认都是启用的，或者根据 st['enabled']
            if not st.get("enabled", True):
                if job_id in existing_ids:
                    scheduler.remove_job(job_id)
                continue

            if st.get("execution_mode") == "listen":
                if job_id in existing_ids:
                    scheduler.remove_job(job_id)
                continue

            try:
                trigger = create_cron_trigger(st["sign_at"])
                if st.get("execution_mode") == "range" and st.get("range_start"):
                    trigger = create_cron_trigger(st["range_start"])

                if job_id in existing_ids:
                    scheduler.reschedule_job(job_id, trigger=trigger)
                else:
                    # 使用新的 job wrapper
                    scheduler.add_job(
                        _job_run_sign_task,
                        trigger=trigger,
                        id=job_id,
                        args=[account_name, task_name],
                        replace_existing=True,
                    )
            except Exception as e:
                print(f"Error scheduling sign task {task_name}: {e}")

        # remove obsolete jobs
        for job_id in existing_ids - desired_ids:
            scheduler.remove_job(job_id)
    finally:
        db.close()


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
        except Exception:
            pass

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
        except Exception:
            pass
        scheduler = None
    try:
        from backend.scheduler.instance_lock import release_scheduler_lock

        release_scheduler_lock()
    except Exception:
        pass
        scheduler = None


def add_or_update_sign_task_job(
    account_name: str, task_name: str, cron_expression: str, enabled: bool = True
) -> None:
    """动态添加或更新签到任务 Job"""
    global scheduler
    if not scheduler:
        return

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
        print(f"Scheduler: 已添加/更新任务 {job_id} -> {cron}")
    except Exception as e:
        print(f"Scheduler: 添加任务 {job_id} 失败: {e}")


def remove_sign_task_job(account_name: str, task_name: str) -> None:
    """动态移除签到任务 Job"""
    global scheduler
    if not scheduler:
        return

    job_id = f"sign-{account_name}-{task_name}"
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            print(f"Scheduler: 已移除任务 {job_id}")
    except Exception as e:
        print(f"Scheduler: 移除任务 {job_id} 失败: {e}")
