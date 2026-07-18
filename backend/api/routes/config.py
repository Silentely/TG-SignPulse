"""Configuration API routes."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.core.auth import get_current_user
from backend.models.user import User
from backend.services.config import get_config_service
from backend.utils.storage import is_writable_dir

router = APIRouter()


def _clear_sign_task_cache() -> None:
    try:
        from backend.services.sign_tasks import get_sign_task_service

        get_sign_task_service().invalidate_tasks_cache()
    except Exception as exc:
        # Best-effort cache invalidation; import should still succeed.
        import logging

        logging.getLogger("backend.config_api").debug(
            "清除签到任务缓存失败: %s", exc
        )


class ExportTaskResponse(BaseModel):
    task_name: str
    task_type: str
    config_json: str


class ImportTaskRequest(BaseModel):
    config_json: str
    task_name: Optional[str] = None
    account_name: Optional[str] = None


class ImportTaskResponse(BaseModel):
    success: bool
    task_name: str
    message: str


class ImportAllRequest(BaseModel):
    config_json: str
    overwrite: bool = False


class ImportAllResponse(BaseModel):
    signs_imported: int
    signs_skipped: int
    monitors_imported: int
    monitors_skipped: int
    settings_imported: int
    settings_skipped: int = 0
    errors: list[str]
    warnings: list[str] = []
    message: str


class TaskListResponse(BaseModel):
    sign_tasks: list[str]
    monitor_tasks: list[str]
    total: int


@router.get("/tasks", response_model=TaskListResponse)
def list_all_tasks(current_user: User = Depends(get_current_user)):
    try:
        sign_tasks = get_config_service().list_sign_tasks()
        monitor_tasks = get_config_service().list_monitor_tasks()
        return TaskListResponse(
            sign_tasks=sign_tasks,
            monitor_tasks=monitor_tasks,
            total=len(sign_tasks) + len(monitor_tasks),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}",
        )


@router.get("/export/sign/{task_name}")
def export_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    try:
        config_json = get_config_service().export_sign_task(
            task_name, account_name=account_name
        )
        if config_json is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_name} not found",
            )

        return Response(
            content=config_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export task: {str(e)}",
        )


@router.post("/import/sign", response_model=ImportTaskResponse)
async def import_sign_task(
    request: ImportTaskRequest, current_user: User = Depends(get_current_user)
):
    try:
        service = get_config_service()
        if not is_writable_dir(service.signs_dir):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Data directory is not writable: {service.signs_dir}",
            )

        success = service.import_sign_task(
            request.config_json, request.task_name, request.account_name
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid task config",
            )

        data = json.loads(request.config_json)
        final_task_name = request.task_name or data.get("task_name", "imported_task")

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()
        try:
            from backend.services.keyword_monitor import get_keyword_monitor_service

            await get_keyword_monitor_service().restart_from_tasks()
        except Exception:
            pass

        return ImportTaskResponse(
            success=True,
            task_name=final_task_name,
            message=f"Task {final_task_name} imported",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import task: {str(e)}",
        )


@router.get("/export/all")
def export_all_configs(current_user: User = Depends(get_current_user)):
    try:
        config_json = get_config_service().export_all_configs()
        return Response(
            content=config_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="tg_signer_all_configs.json"'
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export all configs: {str(e)}",
        )


@router.post("/import/all", response_model=ImportAllResponse)
async def import_all_configs(
    request: ImportAllRequest, current_user: User = Depends(get_current_user)
):
    try:
        result = get_config_service().import_all_configs(
            request.config_json, request.overwrite
        )

        message_parts = []
        if result.get("signs_imported", 0) > 0:
            message_parts.append(f"sign tasks imported: {result['signs_imported']}")
        if result.get("signs_skipped", 0) > 0:
            message_parts.append(f"sign tasks skipped: {result['signs_skipped']}")
        if result.get("monitors_imported", 0) > 0:
            message_parts.append(
                f"monitor tasks imported: {result['monitors_imported']}"
            )
        if result.get("monitors_skipped", 0) > 0:
            message_parts.append(f"monitor tasks skipped: {result['monitors_skipped']}")
        if result.get("settings_imported", 0) > 0:
            message_parts.append(f"settings imported: {result['settings_imported']}")
        if result.get("settings_skipped", 0) > 0:
            message_parts.append(f"settings skipped: {result['settings_skipped']}")
        if result.get("warnings"):
            message_parts.append(f"warnings: {len(result['warnings'])}")

        message = "; ".join(message_parts) if message_parts else "No config imported"
        # 导入成功后已同步调度；提示前端刷新
        if not result.get("errors"):
            message = f"{message}; scheduler synced" if message_parts else "scheduler synced"

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()
        try:
            from backend.services.keyword_monitor import get_keyword_monitor_service

            await get_keyword_monitor_service().restart_from_tasks()
        except Exception:
            pass

        return ImportAllResponse(
            signs_imported=int(result.get("signs_imported", 0)),
            signs_skipped=int(result.get("signs_skipped", 0)),
            monitors_imported=int(result.get("monitors_imported", 0)),
            monitors_skipped=int(result.get("monitors_skipped", 0)),
            settings_imported=int(result.get("settings_imported", 0)),
            settings_skipped=int(result.get("settings_skipped", 0)),
            errors=[str(item) for item in result.get("errors", [])],
            warnings=[str(item) for item in result.get("warnings", [])],
            message=message,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import all configs: {str(e)}",
        )


@router.delete("/sign/{task_name}")
async def delete_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    try:
        success = get_config_service().delete_sign_config(
            task_name, account_name=account_name
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_name} not found",
            )

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()

        return {"success": True, "message": f"Task {task_name} deleted"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete task: {str(e)}",
        )


class AIConfigRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class AIConfigResponse(BaseModel):
    has_config: bool
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_masked: Optional[str] = None


class AIConfigSaveResponse(BaseModel):
    success: bool
    message: str


class AITestResponse(BaseModel):
    success: bool
    message: str
    model_used: Optional[str] = None


@router.get("/ai", response_model=AIConfigResponse)
def get_ai_config(current_user: User = Depends(get_current_user)):
    try:
        config = get_config_service().get_ai_config()
        if not config:
            return AIConfigResponse(has_config=False)

        api_key = config.get("api_key", "")
        if api_key:
            masked = (
                api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
                if len(api_key) > 8
                else "****"
            )
        else:
            masked = None

        return AIConfigResponse(
            has_config=True,
            base_url=config.get("base_url"),
            model=config.get("model"),
            api_key_masked=masked,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read AI config: {str(e)}",
        )


@router.post("/ai", response_model=AIConfigSaveResponse)
def save_ai_config(
    request: AIConfigRequest, current_user: User = Depends(get_current_user)
):
    try:
        if not get_config_service().save_ai_config(
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save AI config: write failed",
            )
        return AIConfigSaveResponse(success=True, message="AI config saved")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save AI config: {str(e)}",
        )


@router.post("/ai/test", response_model=AITestResponse)
async def test_ai_connection(current_user: User = Depends(get_current_user)):
    try:
        result = await get_config_service().test_ai_connection()
        return AITestResponse(**result)
    except Exception as e:
        return AITestResponse(success=False, message=f"AI test failed: {str(e)}")


@router.delete("/ai", response_model=AIConfigSaveResponse)
def delete_ai_config(current_user: User = Depends(get_current_user)):
    try:
        get_config_service().delete_ai_config()
        return AIConfigSaveResponse(success=True, message="AI config deleted")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete AI config: {str(e)}",
        )


class GlobalSettingsRequest(BaseModel):
    sign_interval: Optional[int] = None
    log_retention_days: Optional[int] = None
    data_dir: Optional[str] = None
    global_proxy: Optional[str] = None
    tg_global_concurrency: Optional[int] = None
    device_keepalive_enabled: Optional[bool] = None
    device_keepalive_interval_days: Optional[int] = None
    telegram_bot_notify_enabled: Optional[bool] = None
    telegram_bot_login_notify_enabled: Optional[bool] = None
    telegram_bot_task_failure_enabled: Optional[bool] = None
    telegram_bot_task_success_enabled: Optional[bool] = None
    telegram_bot_quiet_hours_enabled: Optional[bool] = None
    telegram_bot_quiet_hours_start: Optional[str] = None
    telegram_bot_quiet_hours_end: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_bot_chat_id: Optional[str] = None
    telegram_bot_message_thread_id: Optional[int] = None
    timezone: Optional[str] = None
    sign_task_execution_timeout: Optional[int] = None
    sign_task_account_cooldown: Optional[int] = None
    sign_task_flow_retry_attempts: Optional[int] = None
    sign_task_history_max_age_days: Optional[int] = None
    ai_vision_timeout: Optional[int] = None
    ai_vision_retry_attempts: Optional[int] = None
    auto_backup_enabled: Optional[bool] = None
    auto_backup_interval_hours: Optional[int] = None
    auto_backup_keep: Optional[int] = None
    webdav_url: Optional[str] = None
    webdav_username: Optional[str] = None
    webdav_password: Optional[str] = None
    webdav_remote_dir: Optional[str] = None


class GlobalSettingsResponse(BaseModel):
    sign_interval: Optional[int] = None
    log_retention_days: int = 7
    data_dir: Optional[str] = None
    global_proxy: Optional[str] = None
    tg_global_concurrency: Optional[int] = 1
    device_keepalive_enabled: bool = True
    device_keepalive_interval_days: int = 30
    telegram_bot_notify_enabled: bool = False
    telegram_bot_login_notify_enabled: bool = False
    telegram_bot_task_failure_enabled: bool = True
    telegram_bot_task_success_enabled: bool = False
    telegram_bot_quiet_hours_enabled: bool = False
    telegram_bot_quiet_hours_start: Optional[str] = "23:00"
    telegram_bot_quiet_hours_end: Optional[str] = "07:00"
    telegram_bot_token: Optional[str] = None
    telegram_bot_chat_id: Optional[str] = None
    telegram_bot_message_thread_id: Optional[int] = None
    timezone: str = "Asia/Hong_Kong"
    sign_task_execution_timeout: Optional[int] = None
    sign_task_account_cooldown: Optional[int] = None
    sign_task_flow_retry_attempts: Optional[int] = None
    sign_task_history_max_age_days: Optional[int] = None
    ai_vision_timeout: Optional[int] = None
    ai_vision_retry_attempts: Optional[int] = None
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: Optional[int] = 24
    auto_backup_keep: Optional[int] = 3
    webdav_url: Optional[str] = None
    webdav_username: Optional[str] = None
    webdav_password: Optional[str] = None
    webdav_remote_dir: Optional[str] = "tg-signpulse-backups"


@router.get("/settings", response_model=GlobalSettingsResponse)
def get_global_settings(current_user: User = Depends(get_current_user)):
    try:
        settings = get_config_service().get_global_settings()
        from backend.core.config import get_settings
        settings.setdefault("timezone", get_settings().timezone)
        return GlobalSettingsResponse(**settings)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read global settings: {str(e)}",
        )


@router.post("/settings", response_model=AIConfigSaveResponse)
async def save_global_settings(
    request: GlobalSettingsRequest, current_user: User = Depends(get_current_user)
):
    try:
        # 只更新前端实际发送的字段，避免默认值覆盖已有配置
        settings = {}
        fields_set = getattr(request, "model_fields_set", None) or getattr(request, "__fields_set__", set())

        # 按需更新字段
        if "sign_interval" in fields_set:
            settings["sign_interval"] = request.sign_interval
        if "log_retention_days" in fields_set:
            settings["log_retention_days"] = request.log_retention_days
        if "data_dir" in fields_set:
            settings["data_dir"] = request.data_dir
        if "global_proxy" in fields_set:
            settings["global_proxy"] = request.global_proxy
        if "tg_global_concurrency" in fields_set:
            settings["tg_global_concurrency"] = request.tg_global_concurrency
        if "device_keepalive_enabled" in fields_set:
            settings["device_keepalive_enabled"] = request.device_keepalive_enabled
        if "device_keepalive_interval_days" in fields_set and request.device_keepalive_interval_days is not None:
            settings["device_keepalive_interval_days"] = max(
                1, min(int(request.device_keepalive_interval_days), 170)
            )
        if "telegram_bot_notify_enabled" in fields_set:
            settings["telegram_bot_notify_enabled"] = request.telegram_bot_notify_enabled
        if "telegram_bot_login_notify_enabled" in fields_set:
            settings["telegram_bot_login_notify_enabled"] = request.telegram_bot_login_notify_enabled
        if "telegram_bot_task_failure_enabled" in fields_set:
            settings["telegram_bot_task_failure_enabled"] = request.telegram_bot_task_failure_enabled
        if "telegram_bot_task_success_enabled" in fields_set:
            settings["telegram_bot_task_success_enabled"] = request.telegram_bot_task_success_enabled
        if "telegram_bot_quiet_hours_enabled" in fields_set:
            settings["telegram_bot_quiet_hours_enabled"] = request.telegram_bot_quiet_hours_enabled
        if "telegram_bot_quiet_hours_start" in fields_set:
            settings["telegram_bot_quiet_hours_start"] = request.telegram_bot_quiet_hours_start
        if "telegram_bot_quiet_hours_end" in fields_set:
            settings["telegram_bot_quiet_hours_end"] = request.telegram_bot_quiet_hours_end
        if "telegram_bot_token" in fields_set:
            settings["telegram_bot_token"] = request.telegram_bot_token
        if "telegram_bot_chat_id" in fields_set:
            settings["telegram_bot_chat_id"] = request.telegram_bot_chat_id
        if "telegram_bot_message_thread_id" in fields_set:
            settings["telegram_bot_message_thread_id"] = request.telegram_bot_message_thread_id
        if "timezone" in fields_set:
            settings["timezone"] = request.timezone
        if "sign_task_execution_timeout" in fields_set:
            v = request.sign_task_execution_timeout
            settings["sign_task_execution_timeout"] = (
                None if v is None else max(30, min(int(v), 3600))
            )
        if "sign_task_account_cooldown" in fields_set:
            v = request.sign_task_account_cooldown
            settings["sign_task_account_cooldown"] = (
                None if v is None else max(0, min(int(v), 600))
            )
        if "sign_task_flow_retry_attempts" in fields_set:
            v = request.sign_task_flow_retry_attempts
            settings["sign_task_flow_retry_attempts"] = (
                None if v is None else max(1, min(int(v), 10))
            )
        if "sign_task_history_max_age_days" in fields_set:
            v = request.sign_task_history_max_age_days
            settings["sign_task_history_max_age_days"] = (
                None if v is None else max(1, min(int(v), 90))
            )
        if "ai_vision_timeout" in fields_set:
            v = request.ai_vision_timeout
            settings["ai_vision_timeout"] = (
                None if v is None else max(3, min(int(v), 120))
            )
        if "ai_vision_retry_attempts" in fields_set:
            v = request.ai_vision_retry_attempts
            settings["ai_vision_retry_attempts"] = (
                None if v is None else max(1, min(int(v), 8))
            )
        if "auto_backup_enabled" in fields_set:
            settings["auto_backup_enabled"] = request.auto_backup_enabled
        if "auto_backup_interval_hours" in fields_set:
            v = request.auto_backup_interval_hours
            settings["auto_backup_interval_hours"] = (
                None if v is None else max(1, min(int(v), 168))
            )
        if "auto_backup_keep" in fields_set:
            v = request.auto_backup_keep
            settings["auto_backup_keep"] = (
                None if v is None else max(1, min(int(v), 30))
            )
        if "webdav_url" in fields_set:
            settings["webdav_url"] = (
                (request.webdav_url or "").strip() or None
            )
        if "webdav_username" in fields_set:
            settings["webdav_username"] = (
                (request.webdav_username or "").strip() or None
            )
        if "webdav_password" in fields_set:
            # 空字符串表示不修改已有密码
            pwd = request.webdav_password
            if pwd is not None and str(pwd).strip() != "":
                settings["webdav_password"] = str(pwd)
        if "webdav_remote_dir" in fields_set:
            settings["webdav_remote_dir"] = (
                (request.webdav_remote_dir or "").strip()
                or "tg-signpulse-backups"
            )

        # 校验时区格式
        if request.timezone and "timezone" in fields_set:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(request.timezone)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"无效的时区: {request.timezone}",
                )

        if not settings:
            return AIConfigSaveResponse(success=True, message="No settings to update")

        if not get_config_service().save_global_settings(settings):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save global settings: write failed",
            )
        # 时区/自动备份变更时同步调度器（后台执行，不阻塞响应）
        if "timezone" in settings or "auto_backup_enabled" in settings or "auto_backup_interval_hours" in settings:
            import asyncio

            from backend.scheduler import sync_jobs

            async def _safe_tz_sync():
                try:
                    await sync_jobs()
                except Exception as e:
                    import logging
                    logging.getLogger("backend.config_api").warning(f"设置变更调度同步失败: {e}")
            asyncio.ensure_future(_safe_tz_sync())
        return AIConfigSaveResponse(success=True, message="Global settings saved")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save global settings: {str(e)}",
        )


class DeviceKeepaliveResponse(BaseModel):
    success: bool
    enabled: bool = True
    checked: int = 0
    kept_alive: int = 0
    skipped: int = 0
    failed: int = 0
    interval_days: Optional[int] = None
    results: list[dict] = Field(default_factory=list)


@router.post("/settings/device-keepalive/run", response_model=DeviceKeepaliveResponse)
async def run_device_keepalive(current_user: User = Depends(get_current_user)):
    """立即执行一次设备保活。"""
    try:
        from backend.services.device_keepalive import get_device_keepalive_service

        result = await get_device_keepalive_service().run_due(force=True)
        return DeviceKeepaliveResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"设备保活失败: {str(e)}",
        )


class BotTestRequest(BaseModel):
    message: Optional[str] = None


class BotTestResponse(BaseModel):
    success: bool
    message: str


@router.post("/bot/test", response_model=BotTestResponse)
async def test_bot_notification(
    request: BotTestRequest = BotTestRequest(),
    current_user: User = Depends(get_current_user),
):
    """使用已保存的 Bot 配置发送测试消息。"""
    cfg = get_config_service().get_global_settings()
    bot_token = (cfg.get("telegram_bot_token") or "").strip()
    chat_id = (cfg.get("telegram_bot_chat_id") or "").strip()
    if not bot_token or not chat_id:
        return BotTestResponse(success=False, message="未配置 Bot Token 或 Chat ID")
    raw_msg = (request.message or "").strip()
    text = raw_msg or "TG-SignPulse 通知测试：连接正常"
    # 限制长度，避免误填超大文本导致 Telegram API 失败
    text = text[:3900]
    try:
        from backend.services.push_notifications import send_telegram_bot_message

        thread_id = cfg.get("telegram_bot_message_thread_id")
        try:
            thread_id = int(thread_id) if thread_id not in (None, "") else None
        except (TypeError, ValueError):
            thread_id = None
        await send_telegram_bot_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
        )
        return BotTestResponse(success=True, message="测试消息已发送")
    except Exception as e:
        # 不回传完整异常栈，避免 token/网络细节外泄到前端
        err = type(e).__name__
        return BotTestResponse(success=False, message=f"发送失败: {err}")


class ImportPreviewRequest(BaseModel):
    config_json: str


class ImportPreviewResponse(BaseModel):
    signs_count: int = 0
    monitors_count: int = 0
    settings_keys: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@router.post("/import-preview", response_model=ImportPreviewResponse)
def import_preview(
    request: ImportPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """预览配置导入，不写盘。"""
    try:
        result = get_config_service().preview_import_all(request.config_json)
        return ImportPreviewResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入预览失败: {e}",
        )


class TelegramConfigRequest(BaseModel):
    api_id: str
    api_hash: str


class TelegramConfigResponse(BaseModel):
    api_id: str
    api_hash: str
    is_custom: bool
    default_api_id: str
    default_api_hash: str


class TelegramConfigSaveResponse(BaseModel):
    success: bool
    message: str


@router.get("/telegram", response_model=TelegramConfigResponse)
def get_telegram_config(current_user: User = Depends(get_current_user)):
    try:
        config = get_config_service().get_telegram_config()
        service = get_config_service()
        return TelegramConfigResponse(
            api_id=config.get("api_id", ""),
            api_hash=config.get("api_hash", ""),
            is_custom=bool(config.get("is_custom", False)),
            default_api_id=service.DEFAULT_TG_API_ID,
            default_api_hash=service.DEFAULT_TG_API_HASH,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read Telegram config: {str(e)}",
        )


@router.post("/telegram", response_model=TelegramConfigSaveResponse)
def save_telegram_config(
    request: TelegramConfigRequest, current_user: User = Depends(get_current_user)
):
    try:
        if not request.api_id or not request.api_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="api_id and api_hash are required",
            )

        success = get_config_service().save_telegram_config(
            api_id=request.api_id,
            api_hash=request.api_hash,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save Telegram config",
            )
        return TelegramConfigSaveResponse(success=True, message="Telegram config saved")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save Telegram config: {str(e)}",
        )


@router.delete("/telegram", response_model=TelegramConfigSaveResponse)
def reset_telegram_config(current_user: User = Depends(get_current_user)):
    try:
        get_config_service().reset_telegram_config()
        return TelegramConfigSaveResponse(success=True, message="Telegram config reset")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset Telegram config: {str(e)}",
        )
