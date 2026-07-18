"""运行时可改设置解析：global_settings 优先，环境变量兜底。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _global_settings() -> Dict[str, Any]:
    try:
        from backend.services.config import get_config_service

        return get_config_service().get_global_settings() or {}
    except Exception:
        return {}


def resolve_int_setting(
    global_cfg: Dict[str, Any],
    key: str,
    env_name: str,
    default: int,
    *,
    min_v: Optional[int] = None,
    max_v: Optional[int] = None,
) -> int:
    """解析整数配置：面板 global 优先，其次环境变量，最后默认值。"""
    raw: Any = None
    if key in global_cfg and global_cfg[key] is not None and str(global_cfg[key]).strip() != "":
        raw = global_cfg[key]
    else:
        env_raw = os.getenv(env_name)
        if env_raw is not None and str(env_raw).strip() != "":
            raw = env_raw
        else:
            raw = default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if min_v is not None:
        value = max(min_v, value)
    if max_v is not None:
        value = min(max_v, value)
    return value


def get_execution_timeout() -> int:
    return resolve_int_setting(
        _global_settings(),
        "sign_task_execution_timeout",
        "SIGN_TASK_EXECUTION_TIMEOUT",
        300,
        min_v=30,
        max_v=3600,
    )


def get_account_cooldown() -> int:
    return resolve_int_setting(
        _global_settings(),
        "sign_task_account_cooldown",
        "SIGN_TASK_ACCOUNT_COOLDOWN",
        5,
        min_v=0,
        max_v=600,
    )


def get_flow_retry_attempts() -> int:
    return resolve_int_setting(
        _global_settings(),
        "sign_task_flow_retry_attempts",
        "SIGN_TASK_FLOW_RETRY_ATTEMPTS",
        1,
        min_v=1,
        max_v=10,
    )


def get_history_max_age_days() -> int:
    return resolve_int_setting(
        _global_settings(),
        "sign_task_history_max_age_days",
        "SIGN_TASK_HISTORY_MAX_AGE_DAYS",
        3,
        min_v=1,
        max_v=90,
    )


def get_ai_vision_timeout() -> int:
    return resolve_int_setting(
        _global_settings(),
        "ai_vision_timeout",
        "AI_VISION_TIMEOUT",
        15,
        min_v=3,
        max_v=120,
    )


def get_ai_vision_retry_attempts() -> int:
    return resolve_int_setting(
        _global_settings(),
        "ai_vision_retry_attempts",
        "AI_VISION_RETRY_ATTEMPTS",
        2,
        min_v=1,
        max_v=8,
    )


def get_sign_interval_seconds() -> Optional[int]:
    """返回签到账号间隔秒数；None 表示使用随机间隔。"""
    cfg = _global_settings()
    raw = cfg.get("sign_interval")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(0, min(value, 3600))
