"""账号 API 请求/响应模型。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from backend.utils.task_logs import extract_last_target_message


class LoginStartRequest(BaseModel):
    """开始登录请求"""

    account_name: str
    phone_number: str
    proxy: Optional[str] = None


class LoginStartResponse(BaseModel):
    """开始登录响应"""

    phone_code_hash: str
    phone_number: str
    account_name: str
    message: str = "验证码已发送到您的手机"


class LoginVerifyRequest(BaseModel):
    """验证登录请求"""

    account_name: str
    phone_number: str
    phone_code: str
    phone_code_hash: str
    password: Optional[str] = None  # 2FA 密码
    proxy: Optional[str] = None


class LoginVerifyResponse(BaseModel):
    """验证登录响应"""

    success: bool
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    username: Optional[str] = None
    message: str


class QrLoginStartRequest(BaseModel):
    """扫码登录请求"""

    account_name: str
    proxy: Optional[str] = None


class QrLoginStartResponse(BaseModel):
    """扫码登录开始响应"""

    login_id: str
    qr_uri: str
    qr_image: Optional[str] = None
    expires_at: str


class AccountInfo(BaseModel):
    """账号信息"""

    name: str
    session_file: str
    exists: bool
    size: int
    remark: Optional[str] = None
    proxy: Optional[str] = None
    status: str = "connected"
    status_message: Optional[str] = None
    status_code: Optional[str] = None
    status_checked_at: Optional[str] = None
    needs_relogin: bool = False


class QrLoginStatusResponse(BaseModel):
    """扫码登录状态响应"""

    status: str
    expires_at: Optional[str] = None
    message: Optional[str] = None
    account: Optional[AccountInfo] = None
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    username: Optional[str] = None


class QrLoginCancelRequest(BaseModel):
    """扫码登录取消请求"""

    login_id: str


class QrLoginCancelResponse(BaseModel):
    """扫码登录取消响应"""

    success: bool
    message: str


class QrLoginPasswordRequest(BaseModel):
    """扫码登录 2FA 密码请求"""

    login_id: str
    password: str


class QrLoginPasswordResponse(BaseModel):
    """扫码登录 2FA 密码响应"""

    success: bool
    message: str
    account: Optional[AccountInfo] = None
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    username: Optional[str] = None


class AccountListResponse(BaseModel):
    """账号列表响应"""

    accounts: list[AccountInfo]
    total: int


class DeleteAccountResponse(BaseModel):
    """删除账号响应"""

    success: bool
    message: str


class AccountUpdateRequest(BaseModel):
    new_account_name: Optional[str] = None
    """更新账号备注/代理"""

    remark: Optional[str] = None
    proxy: Optional[str] = None


class AccountUpdateResponse(BaseModel):
    """更新账号响应"""

    success: bool
    message: str
    account: Optional[AccountInfo] = None


class AccountStatusCheckRequest(BaseModel):
    """批量账号状态检测请求"""

    account_names: Optional[list[str]] = None
    timeout_seconds: float = 6.0


class AccountStatusItem(BaseModel):
    """账号状态检测结果"""

    account_name: str
    ok: bool
    status: str
    message: str = ""
    code: Optional[str] = None
    checked_at: Optional[str] = None
    needs_relogin: bool = False
    user_id: Optional[int] = None


class AccountStatusCheckResponse(BaseModel):
    """批量账号状态检测响应"""

    results: list[AccountStatusItem]


class AccountDeviceItem(BaseModel):
    """Telegram 已登录设备/授权会话"""

    hash: str
    current: bool = False
    official_app: bool = False
    password_pending: bool = False
    device_model: str = ""
    platform: str = ""
    system_version: str = ""
    app_name: str = ""
    app_version: str = ""
    date_created: Optional[str] = None
    date_active: Optional[str] = None
    ip: str = ""
    country: str = ""
    region: str = ""


class AccountDevicesResponse(BaseModel):
    devices: list[AccountDeviceItem]
    total: int


class TerminateDeviceResponse(BaseModel):
    success: bool
    message: str


class OfficialMessageItem(BaseModel):
    id: Optional[int] = None
    date: Optional[str] = None
    text: str = ""
    outgoing: bool = False


class OfficialMessagesResponse(BaseModel):
    messages: list[OfficialMessageItem]
    total: int


# ============ API Routes ============



class AccountStatusJobStartRequest(BaseModel):
    """异步批量状态检测 Job 请求"""

    account_names: Optional[list[str]] = None
    timeout_seconds: float = 8.0



class AccountLogItem(BaseModel):
    """账号日志项"""

    id: int
    account_name: str
    task_name: str
    message: str
    summary: Optional[str] = None
    bot_message: Optional[str] = None
    success: bool
    created_at: str


def _extract_last_bot_message(item: dict) -> str:
    stored = str(item.get("last_target_message") or "").strip()
    if stored:
        return stored
    return extract_last_target_message(item.get("flow_logs"))



class ClearAccountLogsResponse(BaseModel):
    """清理账号日志响应"""

    success: bool
    cleared: int
    message: str
    code: Optional[str] = None


