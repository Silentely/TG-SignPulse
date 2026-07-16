from pathlib import Path

inject = """
from backend.services.telegram.sessions import (
    _LOGIN_SESSION_MAX_AGE,
    _MAX_LOGIN_SESSIONS,
    _QR_LOGIN_SESSION_MAX_AGE,
    _cleanup_expired_login_sessions,
    _login_sessions,
    _qr_login_sessions,
    _release_login_session,
)
"""

pkg = Path(__file__).resolve().parents[1] / "backend" / "services" / "telegram"
for name in ("login_phone.py", "login_qr.py", "accounts.py", "devices.py"):
    p = pkg / name
    t = p.read_text(encoding="utf-8")
    if "from backend.services.telegram.sessions import" in t:
        print(name, "skip")
        continue
    needle = "settings = get_settings()\n"
    if needle not in t:
        print(name, "no settings")
        continue
    p.write_text(t.replace(needle, needle + inject + "\n", 1), encoding="utf-8")
    print("patched", name)

init = pkg / "__init__.py"
init.write_text(
    '"""Telegram 服务包：mixin 组合 + get_telegram_service。"""\n'
    "from backend.services.telegram.runtime import (  # noqa: F401\n"
    "    TelegramService,\n"
    "    get_telegram_service,\n"
    ")\n"
    "from backend.services.telegram.sessions import (  # noqa: F401\n"
    "    _login_sessions,\n"
    "    _qr_login_sessions,\n"
    ")\n",
    encoding="utf-8",
)
print("init ok")
