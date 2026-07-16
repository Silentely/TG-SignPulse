"""Telegram 服务包：mixin 组合 + get_telegram_service。"""
from backend.services.telegram.runtime import (  # noqa: F401
    TelegramService,
    get_telegram_service,
)
from backend.services.telegram.sessions import (  # noqa: F401
    _login_sessions,
    _qr_login_sessions,
)
