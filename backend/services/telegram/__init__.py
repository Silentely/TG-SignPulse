"""Telegram 服务包：mixin 组合 + get_telegram_service。"""

from backend.services.telegram.runtime import (  # noqa: F401
    TelegramService,
    get_telegram_service,
)
from backend.services.telegram.sessions import (  # noqa: F401
    _login_sessions,
    _qr_login_sessions,
)


def _resolve_account_client_credentials(account_name: str):
    """供 tg_signer Client 工厂使用的账号级凭据钩子。

    仅在账号配置了独立凭据时返回凭据对；否则返回 None 让引擎使用全局配置。
    单边/非法配置会向上抛出，保证 fail-closed。
    """
    from backend.services.telegram.credentials import resolve_account_credentials

    resolved = resolve_account_credentials(account_name)
    if resolved.source != "account":
        return None
    return resolved.as_tuple()


def _register_client_credential_resolver() -> None:
    from tg_signer.core import register_account_credential_resolver

    register_account_credential_resolver(_resolve_account_client_credentials)


_register_client_credential_resolver()
