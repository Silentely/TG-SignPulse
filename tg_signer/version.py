from __future__ import annotations

import os

__version__ = "2.7.0"


def get_user_agent(component: str = "AI") -> str:
    """标准化出站 HTTP 客户端 User-Agent，与应用版本及底层引擎版本联动。

    格式: TG-SignPulse-{component}/{app_version} (tg-signer/{engine_version})
    例如: TG-SignPulse-AI/2.7.0 (tg-signer/2.7.0)
         TG-SignPulse-Jev/2.7.0 (tg-signer/2.7.0)
    """
    env_ver = os.getenv("APP_VERSION", "").strip()
    if env_ver in {"", "0.0.0", "0.0.0-dev"}:
        app_ver = __version__
    else:
        app_ver = env_ver.lstrip("vV")
    comp_clean = component.strip() if component else "Core"
    return f"TG-SignPulse-{comp_clean}/{app_ver} (tg-signer/{__version__})"
