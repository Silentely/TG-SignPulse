"""Telegram API 凭据解析（api_id / api_hash 统一入口）。

解析优先级：环境变量 TG_API_ID / TG_API_HASH > 配置服务 telegram 配置。
缺失或无效时抛 ValueError，由调用方决定如何降级或报错。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def resolve_telegram_api_credentials(
    tg_config: Dict[str, Any],
    *,
    env_api_id: Optional[str] = None,
    env_api_hash: Optional[str] = None,
) -> tuple[int, str]:
    """解析 api_id / api_hash；无效时抛 ValueError。"""
    clean_env_id = (
        env_api_id.strip()
        if isinstance(env_api_id, str) and env_api_id.strip()
        else None
    )
    clean_env_hash = (
        env_api_hash.strip()
        if isinstance(env_api_hash, str) and env_api_hash.strip()
        else None
    )
    raw_id = clean_env_id if clean_env_id is not None else tg_config.get("api_id")
    raw_hash = clean_env_hash if clean_env_hash is not None else tg_config.get("api_hash")
    try:
        api_id = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        api_id = None
    if isinstance(raw_hash, str):
        raw_hash = raw_hash.strip()
    if not api_id or not raw_hash:
        raise ValueError("未配置 Telegram API ID 或 API Hash")
    return api_id, str(raw_hash)
