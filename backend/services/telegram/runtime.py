"""TelegramService 组合入口（mixin 组合）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.telegram.accounts import TelegramAccountsMixin
from backend.services.telegram.devices import TelegramDevicesMixin
from backend.services.telegram.login_phone import TelegramPhoneLoginMixin
from backend.services.telegram.login_qr import TelegramQrLoginMixin
from backend.services.telegram.sessions import (  # noqa: F401
    _cleanup_expired_login_sessions,
    _login_sessions,
    _qr_login_sessions,
)

settings = get_settings()


class TelegramService(
    TelegramAccountsMixin,
    TelegramPhoneLoginMixin,
    TelegramQrLoginMixin,
    TelegramDevicesMixin,
):
    """Telegram 服务类（由 mixin 组合）。"""

    def __init__(self):
        self.session_dir = settings.resolve_session_dir()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._accounts_cache: Optional[List[Dict[str, Any]]] = None


_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service
