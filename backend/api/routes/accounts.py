"""
账号管理 API 路由（重构版）
基于原项目逻辑，使用手机号登录
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.routes.accounts_helpers import (
    build_status_check_error_item,
    clamp_status_check_timeout,
    find_account_by_name,
    normalize_unique_account_names,
    qr_uri_to_data_url,
    resolve_account_rename_target,
)
from backend.api.routes.accounts_schemas import (
    AccountDeviceItem,
    AccountDevicesResponse,
    AccountInfo,
    AccountListResponse,
    AccountLogItem,
    AccountStatusCheckRequest,
    AccountStatusCheckResponse,
    AccountStatusItem,
    AccountStatusJobStartRequest,
    AccountUpdateRequest,
    AccountUpdateResponse,
    ClearAccountLogsResponse,
    DeleteAccountResponse,
    FolderItem,
    ImportSessionRequest,
    ImportSessionResponse,
    LoginStartRequest,
    LoginStartResponse,
    LoginVerifyRequest,
    LoginVerifyResponse,
    OfficialMessageItem,
    OfficialMessagesResponse,
    QrLoginCancelRequest,
    QrLoginCancelResponse,
    QrLoginPasswordRequest,
    QrLoginPasswordResponse,
    QrLoginStartRequest,
    QrLoginStartResponse,
    QrLoginStatusResponse,
    ResetAuthorizationsResponse,
    StandaloneSessionExportRequest,
    StandaloneSessionExportResponse,
    TerminateDeviceResponse,
    TopicItem,
    _extract_last_bot_message,
)
from backend.core.auth import get_current_user
from backend.core.rate_limit import compose_rate_limit_key, get_rate_limiter
from backend.models.user import User
from backend.services.telegram import get_telegram_service
from backend.utils.account_locks import AccountLockTimeout
from backend.utils.names import validate_storage_name

router = APIRouter()
logger = logging.getLogger("backend.accounts_api")
rate_limiter = get_rate_limiter()


def _apply_rate_limit(
    scope: str,
    request: Request,
    detail: str,
    *parts: str,
    max_attempts: int,
    window_seconds: int,
    block_seconds: int,
) -> str:
    key = compose_rate_limit_key(request, *parts)
    rate_limiter.hit(
        scope=scope,
        key=key,
        max_attempts=max_attempts,
        window_seconds=window_seconds,
        block_seconds=block_seconds,
        detail=detail,
    )
    return key


@router.post("/login/start", response_model=LoginStartResponse)
async def start_account_login(
    request: LoginStartRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    开始账号登录流程（发送验证码）

    1. 用户输入账号名和手机号
    2. 系统发送验证码到手机
    3. 返回 phone_code_hash 用于后续验证
    """
    try:
        limit_key = _apply_rate_limit(
            "accounts.login.start",
            http_request,
            "Too many account login code requests. Please try again later.",
            request.account_name,
            request.phone_number,
            max_attempts=6,
            window_seconds=600,
            block_seconds=900,
        )
        result = await get_telegram_service().start_login(
            account_name=request.account_name,
            phone_number=request.phone_number,
            proxy=request.proxy,
        )
        rate_limiter.reset("accounts.login.start", limit_key)

        return LoginStartResponse(**result)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            "发送验证码失败 account=%s: %s", request.account_name, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="发送验证码失败，请稍后重试",
        )


@router.post("/login/verify", response_model=LoginVerifyResponse)
async def verify_account_login(
    request: LoginVerifyRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    验证账号登录（输入验证码和可选的2FA密码）

    1. 用户输入验证码
    2. 如果启用了2FA，还需要输入2FA密码
    3. 验证成功后，生成 session 文件
    """
    try:
        limit_key = _apply_rate_limit(
            "accounts.login.verify",
            http_request,
            "Too many account login verification attempts. Please try again later.",
            request.account_name,
            request.phone_number,
            max_attempts=8,
            window_seconds=600,
            block_seconds=900,
        )
        result = await get_telegram_service().verify_login(
            account_name=request.account_name,
            phone_number=request.phone_number,
            phone_code=request.phone_code,
            phone_code_hash=request.phone_code_hash,
            password=request.password,
            proxy=request.proxy,
        )
        rate_limiter.reset("accounts.login.verify", limit_key)

        return LoginVerifyResponse(
            success=True,
            user_id=result.get("user_id"),
            first_name=result.get("first_name"),
            username=result.get("username"),
            message="登录成功",
        )

    except ValueError as e:
        message = str(e)
        lowered = message.lower()
        # 稳定错误码替代中文文案透传：前端按码分支，不随文案/语言漂移
        if "两步验证" in message or "session_password_needed" in lowered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SESSION_PASSWORD_NEEDED",
            ) from e
        if "2fa 密码错误" in lowered or "passwordhashinvalid" in lowered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PASSWORD_HASH_INVALID",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message
        ) from e
    except Exception as e:
        logger.error(
            "登录验证失败 account=%s: %s", request.account_name, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录验证失败，请稍后重试",
        )


@router.post("/qr/start", response_model=QrLoginStartResponse)
async def start_qr_login(
    request: QrLoginStartRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """开始扫码登录流程"""
    try:
        limit_key = _apply_rate_limit(
            "accounts.qr.start",
            http_request,
            "Too many QR login requests. Please try again later.",
            request.account_name,
            max_attempts=8,
            window_seconds=600,
            block_seconds=900,
        )
        result = await get_telegram_service().start_qr_login(
            account_name=request.account_name, proxy=request.proxy
        )
        rate_limiter.reset("accounts.qr.start", limit_key)

        return QrLoginStartResponse(
            login_id=result["login_id"],
            qr_uri=result["qr_uri"],
            qr_image=qr_uri_to_data_url(result.get("qr_uri") or ""),
            expires_at=result["expires_at"],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            "开始扫码登录失败 account=%s: %s", request.account_name, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="开始扫码登录失败，请稍后重试",
        )


@router.get("/qr/status", response_model=QrLoginStatusResponse)
async def get_qr_login_status(
    login_id: str, current_user: User = Depends(get_current_user)
):
    """获取扫码登录状态"""
    try:
        result = await get_telegram_service().get_qr_login_status(login_id)
        account = result.get("account")
        if account:
            account = AccountInfo(**account)
        return QrLoginStatusResponse(
            status=result.get("status"),
            expires_at=result.get("expires_at"),
            message=result.get("message"),
            account=account,
            user_id=result.get("user_id"),
            first_name=result.get("first_name"),
            username=result.get("username"),
        )
    except Exception as e:
        logger.error("获取扫码状态失败 login_id=%s: %s", login_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取扫码状态失败，请稍后重试",
        )


@router.post("/qr/password", response_model=QrLoginPasswordResponse)
async def submit_qr_login_password(
    request: QrLoginPasswordRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """提交扫码登录 2FA 密码"""
    try:
        limit_key = _apply_rate_limit(
            "accounts.qr.password",
            http_request,
            "Too many QR password attempts. Please try again later.",
            request.login_id,
            max_attempts=5,
            window_seconds=600,
            block_seconds=900,
        )
        result = await get_telegram_service().submit_qr_password(
            request.login_id, request.password
        )
        rate_limiter.reset("accounts.qr.password", limit_key)
        account = result.get("account")
        if account:
            account = AccountInfo(**account)
        return QrLoginPasswordResponse(
            success=True,
            message=result.get("message", "登录成功"),
            account=account,
            user_id=result.get("user_id"),
            first_name=result.get("first_name"),
            username=result.get("username"),
        )
    except ValueError as e:
        logger.warning("QR 密码校验失败 login_id=%s error=%s", request.login_id, e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            "提交 2FA 密码失败 login_id=%s: %s", request.login_id, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="提交 2FA 密码失败，请稍后重试",
        )


@router.post("/qr/cancel", response_model=QrLoginCancelResponse)
async def cancel_qr_login(
    request: QrLoginCancelRequest, current_user: User = Depends(get_current_user)
):
    """取消扫码登录"""
    try:
        success = await get_telegram_service().cancel_qr_login(request.login_id)
        return QrLoginCancelResponse(
            success=success,
            message="已取消" if success else "登录已失效",
        )
    except Exception as e:
        logger.error(
            "取消扫码登录失败 login_id=%s: %s", request.login_id, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取消扫码登录失败，请稍后重试",
        )




def _is_zip_payload(payload: bytes | str) -> bool:
    """Check whether session payload is a ZIP archive (e.g. Telegram Desktop TData)."""
    if isinstance(payload, bytes):
        return payload.startswith(b"PK") or payload.startswith(b"PK") or payload.startswith(b"PK")
    if isinstance(payload, str):
        cleaned = payload.strip()
        try:
            raw = base64.b64decode(cleaned)
            return raw.startswith(b"PK") or raw.startswith(b"PK") or raw.startswith(b"PK")
        except Exception:
            return False
    return False

@router.post("/import-session", response_model=ImportSessionResponse)
async def import_session(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """导入外部 Telegram 会话（Telethon SQLite, Pyrogram SQLite, Pyrogram StringSession, 或 TData zip）。"""
    content_type = request.headers.get("content-type", "")

    account_name = ""
    session_type = "auto"
    session_content: Optional[str] = None
    force = False
    proxy: Optional[str] = None
    tdata_password: Optional[str] = None
    payload: bytes | str = ""

    if "multipart/form-data" in content_type:
        form = await request.form()
        account_name = str(form.get("account_name") or "").strip()
        session_type = str(form.get("session_type") or "auto").strip()
        force_raw = form.get("force")
        force = str(force_raw).lower() in ("true", "1") if force_raw is not None else False
        proxy_raw = form.get("proxy")
        proxy = str(proxy_raw).strip() if proxy_raw else None
        tdata_pwd_raw = form.get("tdata_password")
        tdata_password = str(tdata_pwd_raw).strip() if tdata_pwd_raw else None

        file = form.get("file")
        if file and hasattr(file, "read"):
            payload = await file.read()
        else:
            session_content = form.get("session_content")
            if session_content:
                payload = str(session_content).strip()
    else:
        try:
            body = await request.json()
            req = ImportSessionRequest(**body)
            account_name = req.account_name.strip()
            session_type = req.session_type
            session_content = req.session_content
            force = req.force
            proxy = req.proxy
            tdata_password = req.tdata_password.strip() if req.tdata_password else None
            if not session_content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="session_content is required",
                )
            payload = session_content.strip()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON request: {exc}",
            ) from exc

    if not account_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account_name is required",
        )

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No session payload provided (file or session_content is required)",
        )

    MAX_SESSION_UPLOAD_SIZE = 50 * 1024 * 1024
    if (isinstance(payload, bytes) and len(payload) > MAX_SESSION_UPLOAD_SIZE) or (
        isinstance(payload, str) and len(payload) > MAX_SESSION_UPLOAD_SIZE * 4 // 3
    ):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Session payload exceeds 50MB limit",
        )

    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    svc = get_telegram_service()
    try:
        if _is_zip_payload(payload):
            zip_bytes = payload if isinstance(payload, bytes) else base64.b64decode(payload.strip())
            res = await svc.import_tdata_session(
                account_name=account_name,
                zip_payload=zip_bytes,
                password=tdata_password,
                force=force,
                proxy=proxy,
            )
        else:
            res = await svc.import_session(
                account_name=account_name,
                payload=payload,
                session_type=session_type,
                force=force,
                proxy=proxy,
            )
        return ImportSessionResponse(
            success=True,
            account_name=account_name,
            user_id=res.get("user_id"),
            first_name=res.get("first_name"),
            username=res.get("username"),
            message="会话导入成功",
        )
    except AccountLockTimeout:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ACCOUNT_BUSY",
        )
    except RuntimeError as e:
        err_msg = str(e)
        if "TDATA_CONVERTER_UNAVAILABLE" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TDATA_CONVERTER_UNAVAILABLE",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )
    except ValueError as e:
        err_msg = str(e)
        if "TDATA_PASSWORD_REQUIRED" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TDATA_PASSWORD_REQUIRED",
            )
        if "TDATA_PASSWORD_INVALID" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TDATA_PASSWORD_INVALID",
            )
        if "already exists" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg,
            )
        if "IMPORTED_SESSION_UNAUTHORIZED" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="IMPORTED_SESSION_UNAUTHORIZED",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )
    except Exception as e:
        logger.error(
            "Import session failed for %s: %s", account_name, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import session failed: {e}",
        )


@router.get("", response_model=AccountListResponse)
def list_accounts(current_user: User = Depends(get_current_user)):
    """
    获取所有账号列表

    返回所有 session 文件对应的账号
    """
    try:
        accounts = get_telegram_service().list_accounts()

        return AccountListResponse(
            accounts=[AccountInfo(**acc) for acc in accounts], total=len(accounts)
        )

    except Exception as e:
        logger.error("获取账号列表失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACCOUNTS_LOAD_FAILED",
        )


@router.post("/status/check", response_model=AccountStatusCheckResponse)
async def check_accounts_status(
    request: AccountStatusCheckRequest, current_user: User = Depends(get_current_user)
):
    """
    批量检测账号状态（同步，兼容旧客户端）。

    账号较多时建议改用 POST /accounts/status/check-jobs 异步 Job。
    说明：
    - 默认按当前账号列表检测；
    - 顺序检测并做轻微节流，避免刷新页面时触发请求洪峰。
    - 超过 8 个账号时仍同步执行，但前端批量入口已切到 Job API。
    """
    service = get_telegram_service()
    try:
        fallback = [item.get("name", "") for item in service.list_accounts()]
        names = normalize_unique_account_names(
            request.account_names,
            fallback_names=fallback,
        )
        timeout_seconds = clamp_status_check_timeout(request.timeout_seconds)
        results: list[AccountStatusItem] = []
        for idx, name in enumerate(names):
            try:
                item = await service.check_account_status(
                    name, timeout_seconds=timeout_seconds
                )
            except Exception as exc:
                item = build_status_check_error_item(name, exc)
            results.append(AccountStatusItem(**item))
            if idx < len(names) - 1:
                await asyncio.sleep(0.15)

        return AccountStatusCheckResponse(results=results)
    except Exception as e:
        logger.error("账号状态检测失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACCOUNT_CHECK_FAILED",
        )


@router.post("/status/check-jobs", status_code=status.HTTP_201_CREATED)
async def start_account_status_check_job(
    request: AccountStatusJobStartRequest,
    current_user: User = Depends(get_current_user),
):
    """启动账号会话状态批量检测 Job（可取消、可查询进度）。"""
    from backend.services.account_status_jobs import start_account_status_check_job

    try:
        return start_account_status_check_job(
            account_names=request.account_names,
            timeout_seconds=request.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("启动账号状态检测任务失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACCOUNT_CHECK_START_FAILED",
        )


@router.get("/status/check-jobs")
def list_account_status_check_jobs(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    from backend.services.account_status_jobs import list_account_status_jobs
    from tg_signer.utils import clamp

    return {"jobs": list_account_status_jobs(limit=clamp(limit, 1, 50))}


@router.get("/status/check-jobs/{job_id}")
def get_account_status_check_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from backend.services.account_status_jobs import get_account_status_job

    job = get_account_status_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="JOB_NOT_FOUND"
        )
    return job


@router.post("/status/check-jobs/{job_id}/cancel")
def cancel_account_status_check_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from backend.services.account_status_jobs import cancel_account_status_job

    if not cancel_account_status_job(job_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JOB_NOT_CANCELABLE",
        )
    return {"ok": True, "job_id": job_id}


def _build_history_log_item(
    item: dict, idx: int, account_name: Optional[str] = None
) -> dict:
    """历史日志条目统一构造：任务名兜底、消息/摘要/状态文案与失败分类归一。

    供最近日志与账号日志两个列表端点复用，避免展示字段漂移。
    """
    task_name = item.get("task_name") or "未知任务"
    success = bool(item.get("success", False))
    return {
        "id": idx + 1,
        "account_name": account_name or item.get("account_name", ""),
        "task_name": task_name,
        "message": item.get("message") or ("执行成功" if success else "执行失败"),
        "summary": f"任务: {task_name} {'成功' if success else '失败'}",
        "bot_message": _extract_last_bot_message(item) or None,
        "success": success,
        "created_at": item.get("time", ""),
        "failure_category": item.get("failure_category") or None,
    }


@router.get("/logs/recent", response_model=list[dict])
def get_recent_account_logs(
    limit: int = 50, current_user: User = Depends(get_current_user)
):
    from backend.services.sign_tasks import get_sign_task_service
    from tg_signer.utils import clamp

    limit = clamp(limit, 1, 200)

    history = get_sign_task_service().get_recent_history_logs(limit=limit)
    return [_build_history_log_item(item, idx) for idx, item in enumerate(history)]


@router.delete("/{account_name}", response_model=DeleteAccountResponse)
async def delete_account(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """
    删除账号（删除 session 文件）

    注意：删除后无法恢复，需要重新登录
    """
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        success = await get_telegram_service().delete_account(account_name)

        if success:
            # 清理签到服务内存中的账号痕迹：冷却时间戳与账号锁，
            # 避免同名重建账号继承旧冷却、锁实例残留
            from backend.services.sign_tasks import get_sign_task_service

            sign_svc = get_sign_task_service()
            sign_svc._account_last_run_end.pop(account_name, None)
            sign_svc._account_locks.pop(account_name, None)
            return DeleteAccountResponse(
                success=True, message=f"账号 {account_name} 已删除"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ACCOUNT_NOT_FOUND",
            )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("删除账号失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACCOUNT_DELETE_FAILED",
        )


@router.get("/{account_name}/exists")
def check_account_exists(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """检查账号是否存在"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    exists = get_telegram_service().account_exists(account_name)
    return {"exists": exists, "account_name": account_name}


@router.get("/{account_name}/devices", response_model=AccountDevicesResponse)
async def list_account_devices(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """获取账号已登录设备/授权会话列表。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        devices = await get_telegram_service().list_account_devices(account_name)
        return AccountDevicesResponse(
            devices=[AccountDeviceItem(**item) for item in devices],
            total=len(devices),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("获取设备列表失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取设备列表失败，请稍后重试",
        )


@router.delete(
    "/{account_name}/devices/{auth_hash}", response_model=TerminateDeviceResponse
)
async def terminate_account_device(
    account_name: str,
    auth_hash: str,
    current_user: User = Depends(get_current_user),
):
    """踢下线指定已登录设备。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        success = await get_telegram_service().terminate_account_device(
            account_name, int(auth_hash)
        )
        return TerminateDeviceResponse(
            success=success,
            message="设备已下线" if success else "设备下线失败",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("设备下线失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设备下线失败，请稍后重试",
        )



@router.post(
    "/{account_name}/session-exports",
    response_model=StandaloneSessionExportResponse,
)
async def export_standalone_session(
    account_name: str,
    request: Optional[StandaloneSessionExportRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """派生独立 SessionString 导出（基于 Telegram 官方扫码授权协议）。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        if not get_telegram_service().account_exists(account_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="账号不存在",
            )
        device_model = (
            request.device_model if request and request.device_model else "TG-SignPulse Exported Session"
        )
        timeout_seconds = (
            request.timeout_seconds if request and request.timeout_seconds else 60.0
        )

        result = await get_telegram_service().export_standalone_session(
            account_name,
            device_model=device_model,
            timeout_seconds=timeout_seconds,
        )
        if not result.success:
            if result.error == "ACCOUNT_BUSY":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="ACCOUNT_BUSY",
                )
            if result.error == "ACCOUNT_NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="账号不存在",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error or "派生独立 Session 失败",
            )
        return StandaloneSessionExportResponse(
            success=True,
            session_string=result.session_string,
            dc_id=result.dc_id,
            user_id=result.user_id,
            message="派生独立 Session 成功",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("派生独立 Session 失败 %s: %s", account_name, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"派生独立 Session 失败: {e}",
        )


@router.post(
    "/{account_name}/devices/reset-others", response_model=ResetAuthorizationsResponse
)
async def reset_account_authorizations(
    account_name: str,
    current_user: User = Depends(get_current_user),
):
    """一键清退账号除当前会话外的所有已授权设备。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        if not get_telegram_service().account_exists(account_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="账号不存在",
            )
        await get_telegram_service().reset_account_authorizations(account_name)
        return ResetAuthorizationsResponse(
            success=True,
            message="已成功清退其他设备",
        )
    except HTTPException:
        raise
    except AccountLockTimeout:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ACCOUNT_BUSY",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("清退其他设备失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="清退其他设备失败，请稍后重试",
        )


@router.get(
    "/{account_name}/official-messages", response_model=OfficialMessagesResponse
)
async def list_account_official_messages(
    account_name: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
):
    """读取账号和 Telegram 官方服务号 777000 的最近消息。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        messages = await get_telegram_service().list_official_messages(
            account_name, limit=limit
        )
        return OfficialMessagesResponse(
            messages=[OfficialMessageItem(**item) for item in messages],
            total=len(messages),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("获取官方消息失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取官方消息失败，请稍后重试",
        )


@router.get("/{account_name}/avatar")
async def get_account_avatar(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """获取账号 Telegram 头像（带本地缓存）"""
    from fastapi.responses import Response

    from backend.core.config import get_settings
    from backend.services import avatar_cache

    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    settings = get_settings()
    avatar_cache_dir = settings.resolve_workdir() / "avatars"
    avatar_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = avatar_cache_dir / f"{account_name}.jpg"
    no_avatar_marker = avatar_cache_dir / f"{account_name}.no_avatar"

    # 如果已标记为无头像（7天内），直接返回 404
    if avatar_cache.marker_hits_no_avatar(no_avatar_marker):
        raise HTTPException(status_code=404, detail="No avatar available")

    # 如果缓存存在且不超过 7 天，直接返回
    cached = avatar_cache.read_cached_avatar(cache_file)
    if cached is not None:
        return Response(content=cached, media_type="image/jpeg")

    # 尝试下载头像
    try:
        avatar_bytes = await avatar_cache.get_avatar_bytes(
            cache_file,
            no_avatar_marker,
            lambda: get_telegram_service().download_account_avatar(account_name),
        )
        if avatar_bytes:
            return Response(content=avatar_bytes, media_type="image/jpeg")
        else:
            # 明确判定无头像才写标记
            avatar_cache.mark_no_avatar(no_avatar_marker)
    except Exception:
        # 瞬时下载失败：回退缓存即可，不写"无头像"标记，下次请求重试
        logger.warning("获取账号头像失败 account=%s", account_name, exc_info=True)
        stale = avatar_cache.read_avatar_file(cache_file)
        if stale is not None:
            return Response(content=stale, media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="No avatar available")


@router.patch("/{account_name}", response_model=AccountUpdateResponse)
async def update_account(
    account_name: str,
    request: AccountUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    更新账号备注/代理/标签/设备画像（不影响登录状态）
    """
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    service = get_telegram_service()
    accounts = service.list_accounts(force_refresh=True)
    current_account = find_account_by_name(accounts, account_name)
    if not current_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_name} not found",
        )

    try:
        from backend.utils.tg_session import set_account_profile

        actual_account_name = str(current_account.get("name") or account_name).strip()

        device_profile_to_save = None
        device_family_to_save = None
        if request.device_family is not None or request.device_profile is not None:
            from backend.services.telegram.device_profiles import (
                get_random_profile,
                validate_device_profile,
            )
            from tg_signer.core import is_account_client_active

            if is_account_client_active(
                actual_account_name, getattr(service, "session_dir", None)
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="ACCOUNT_BUSY",
                )

            if request.device_profile is not None:
                profile_dict = dict(request.device_profile)
                if request.device_family is not None:
                    profile_dict["device_family"] = request.device_family
                device_profile_to_save = validate_device_profile(profile_dict)
                device_family_to_save = (
                    device_profile_to_save.get("device_family") or request.device_family
                )
            elif request.device_family is not None:
                device_family_to_save = request.device_family
                device_profile_to_save = get_random_profile(request.device_family)

        target_account_name, renamed = resolve_account_rename_target(
            actual_account_name,
            request.new_account_name,
        )
        if renamed:
            target_account_name = await service.rename_account(
                actual_account_name,
                target_account_name,
            )

        set_account_profile(
            target_account_name,
            remark=request.remark,
            proxy=request.proxy,
            tags=request.tags,
            device_family=device_family_to_save,
            device_profile=device_profile_to_save,
        )

        if renamed:
            from backend.scheduler import sync_jobs

            try:
                await sync_jobs()
            except Exception as exc:
                # 调度同步失败不应阻断改名主流程；与 config.py/batch.py 的兜底策略一致
                logger.warning("账号改名后同步调度任务失败: %s", exc)

        try:
            from backend.services.keyword_monitor import get_keyword_monitor_service

            await get_keyword_monitor_service().restart_from_tasks()
        except Exception as exc:
            # 监控重启失败仅告警，避免静默保持旧账号监控
            logger.warning("账号更新后重启关键词监控失败: %s", exc)

        updated = find_account_by_name(
            service.list_accounts(force_refresh=True),
            target_account_name,
        )
        if not updated:
            raise ValueError("账号信息更新后未找到对应账号")

        return AccountUpdateResponse(
            success=True,
            message="Account updated",
            account=AccountInfo(**updated),
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("更新账号信息失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACCOUNT_UPDATE_FAILED",
        )


@router.post("/logs/clear", response_model=ClearAccountLogsResponse)
def clear_recent_account_logs(current_user: User = Depends(get_current_user)):
    """清理全部最近任务执行日志"""
    try:
        from backend.services.sign_tasks import get_sign_task_service

        result = get_sign_task_service().clear_all_history_logs()
        return ClearAccountLogsResponse(
            success=True,
            cleared=result.get("removed_entries", 0),
            message="All logs cleared",
            code="LOGS_CLEARED",
        )
    except Exception:
        logger.exception("清理任务执行日志失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLEAR_LOGS_FAILED",
        )


@router.get("/{account_name}/logs", response_model=list[AccountLogItem])
def get_account_logs(
    account_name: str, limit: int = 100, current_user: User = Depends(get_current_user)
):
    """获取账号的任务执行历史日志"""
    from backend.services.sign_tasks import get_sign_task_service
    from tg_signer.utils import clamp

    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    limit = clamp(limit, 1, 200)

    history = get_sign_task_service().get_account_history_logs(account_name)

    return [
        AccountLogItem(**_build_history_log_item(item, i, account_name=account_name))
        for i, item in enumerate(history[:limit])
    ]


@router.post("/{account_name}/logs/clear", response_model=ClearAccountLogsResponse)
def clear_account_logs(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """清理账号的历史日志"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not get_telegram_service().account_exists(account_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ACCOUNT_NOT_FOUND",
        )
    try:
        from backend.services.sign_tasks import get_sign_task_service

        result = get_sign_task_service().clear_account_history_logs(account_name)
        return ClearAccountLogsResponse(
            success=True,
            cleared=result.get("removed_entries", 0),
            message="Logs cleared",
            code="LOGS_CLEARED",
        )
    except Exception:
        logger.exception("清理任务执行日志失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLEAR_LOGS_FAILED",
        )


@router.get("/{account_name}/logs/export")
def export_account_logs(
    account_name: str, current_user: User = Depends(get_current_user)
):
    """导出账号日志为 txt 文件"""
    from fastapi.responses import Response

    from backend.services.sign_tasks import get_sign_task_service

    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    history = get_sign_task_service().get_account_history_logs(account_name)

    content = f"账号日志: {account_name}\n"
    content += "=" * 40 + "\n\n"

    for item in history:
        time_str = item.get("time", "").replace("T", " ")[:19]
        status_text = "成功" if item.get("success") else "失败"
        content += f"[{time_str}] 任务: {item.get('task_name')} | 状态: {status_text}\n"
        if item.get("message"):
            content += f"消息: {item.get('message')}\n"
        content += "-" * 20 + "\n"

    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_acc = "".join(c for c in account_name if c.isalnum() or c in ("-", "_")) or "account"
    filename = f"{safe_acc}_logs_{stamp}.txt"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{account_name}/folders", response_model=list[FolderItem])
async def list_account_folders(
    account_name: str,
    timeout_seconds: float = 12.0,
    current_user: User = Depends(get_current_user),
):
    """获取指定账号的 Telegram 对话文件夹（Dialog Filters）列表。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        if not get_telegram_service().account_exists(account_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="账号不存在",
            )
        folders = await get_telegram_service().list_account_folders(
            account_name, timeout_seconds=timeout_seconds
        )
        return [FolderItem(**item) for item in folders]
    except HTTPException:
        raise
    except AccountLockTimeout:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ACCOUNT_BUSY",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("获取文件夹列表失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取文件夹列表失败，请稍后重试",
        )


@router.get("/{account_name}/chats/{chat_id}/topics", response_model=list[TopicItem])
async def list_account_forum_topics(
    account_name: str,
    chat_id: str,
    limit: int = 100,
    timeout_seconds: float = 12.0,
    current_user: User = Depends(get_current_user),
):
    """获取指定群组的论坛话题（Forum Topics）列表。"""
    try:
        account_name = validate_storage_name(account_name, field_name="account_name")
        if not get_telegram_service().account_exists(account_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="账号不存在",
            )
        try:
            target_chat_id: int | str = int(chat_id)
        except ValueError:
            target_chat_id = chat_id

        topics = await get_telegram_service().list_forum_topics(
            account_name,
            chat_id=target_chat_id,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
        return [TopicItem(**item) for item in topics]
    except HTTPException:
        raise
    except AccountLockTimeout:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ACCOUNT_BUSY",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("获取论坛话题列表失败: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取论坛话题列表失败，请稍后重试",
        )
