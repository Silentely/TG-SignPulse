"""Telegram API 凭据统一解析入口（账号级 / 全局）。

解析优先级：

1. 账号独立凭据（``session_dir/accounts.json`` 中的 profile entry）；
2. 完整环境变量对（``TG_API_ID`` + ``TG_API_HASH``）；
3. 完整面板配置对（``.telegram_api.json``）；
4. 完整内置默认对。

成对规则（fail-closed）：``api_id`` 与 ``api_hash`` 必须来自同一来源。
任何来源只要出现了单边配置，就直接抛错，绝不跨来源拼接，也绝不静默降级。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional, Tuple

CredentialSource = Literal["account", "env", "panel", "default"]

# 与 TelegramConfigMixin 的内置公开默认凭据保持一致。在此处保留常量副本，
# 避免解析器反向依赖配置服务（配置服务与账号模块均会导入本模块）。
DEFAULT_API_ID = "611335"
DEFAULT_API_HASH = "d524b414d21f4d37f08684c1df41ac9c"

_PAIR_REQUIRED_MESSAGE = "API ID 与 API Hash 必须成对填写，或均留空使用全局配置"
_INVALID_MESSAGE = "Telegram API ID 必须是正整数，API Hash 必须为非空字符串"


class TelegramCredentialsError(ValueError):
    """凭据解析失败基类；``code`` 供 API 层稳定映射错误码。"""

    code = "API_CREDENTIALS_INVALID"


class ApiCredentialsPairRequired(TelegramCredentialsError):
    """只配置了 api_id 或 api_hash 中的一项。"""

    code = "API_CREDENTIALS_PAIR_REQUIRED"


class ApiCredentialsInvalid(TelegramCredentialsError):
    """api_id / api_hash 格式非法。"""

    code = "API_CREDENTIALS_INVALID"


class ApiCredentialsUnavailable(TelegramCredentialsError):
    """没有任何可用来源。"""

    code = "API_CREDENTIALS_UNAVAILABLE"


class ApiCredentialsMismatch(TelegramCredentialsError):
    """Session 创建时使用的 api_id 与当前配置不一致。"""

    code = "API_CREDENTIALS_MISMATCH"


_UNSET = object()


def mask_api_hash(api_hash: Optional[str]) -> Optional[str]:
    """脱敏 API Hash：保留前 4 位与后 4 位，中间固定 4 个星号。"""
    if not isinstance(api_hash, str):
        return None
    value = api_hash.strip()
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


def credential_fingerprint(api_id: int, api_hash: str) -> str:
    """稳定凭据指纹（不包含明文 Hash），用于客户端缓存键与隔离比较。"""
    digest = hashlib.sha256(f"{int(api_id)}:{api_hash}".encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class ResolvedTelegramCredentials:
    """一次解析得到的完整凭据对。"""

    api_id: int
    api_hash: str
    source: CredentialSource
    account_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_custom(self) -> bool:
        return self.source == "account"

    @property
    def masked_hash(self) -> str:
        return mask_api_hash(self.api_hash) or "****"

    @property
    def fingerprint(self) -> str:
        return credential_fingerprint(self.api_id, self.api_hash)

    def as_tuple(self) -> Tuple[int, str]:
        return self.api_id, self.api_hash


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def parse_api_id(value: Any) -> int:
    """解析 api_id；非法时抛 ApiCredentialsInvalid。"""
    raw = _clean_text(value)
    if not raw:
        raise ApiCredentialsInvalid(_INVALID_MESSAGE)
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiCredentialsInvalid(_INVALID_MESSAGE) from exc
    if parsed <= 0:
        raise ApiCredentialsInvalid(_INVALID_MESSAGE)
    return parsed


def parse_api_hash(value: Any) -> str:
    """解析 api_hash；非法时抛 ApiCredentialsInvalid。"""
    raw = _clean_text(value)
    if not raw:
        raise ApiCredentialsInvalid(_INVALID_MESSAGE)
    return raw


def parse_credential_pair(
    api_id: Any,
    api_hash: Any,
    *,
    source: CredentialSource,
    account_name: Optional[str] = None,
) -> Optional[ResolvedTelegramCredentials]:
    """解析一组同源凭据。

    返回 ``None`` 表示两项均为空（该来源未配置）；单边配置抛
    :class:`ApiCredentialsPairRequired`，格式非法抛
    :class:`ApiCredentialsInvalid`。
    """
    raw_id = _clean_text(api_id)
    raw_hash = _clean_text(api_hash)
    if not raw_id and not raw_hash:
        return None
    if bool(raw_id) != bool(raw_hash):
        raise ApiCredentialsPairRequired(_PAIR_REQUIRED_MESSAGE)
    return ResolvedTelegramCredentials(
        api_id=parse_api_id(raw_id),
        api_hash=parse_api_hash(raw_hash),
        source=source,
        account_name=account_name,
    )


def _resolve_env_values(env_api_id: Any, env_api_hash: Any) -> Tuple[Any, Any]:
    if env_api_id is _UNSET and env_api_hash is _UNSET:
        return os.getenv("TG_API_ID"), os.getenv("TG_API_HASH")
    return (
        None if env_api_id is _UNSET else env_api_id,
        None if env_api_hash is _UNSET else env_api_hash,
    )


def _resolve_panel_pair(tg_config: Optional[Dict[str, Any]]):
    if not isinstance(tg_config, dict):
        return None
    # get_telegram_config() 会带 configured 标记，用于区分「面板未配置」和
    # 「面板配置了与默认值相同的值」，同时暴露原始单边字段以便 fail-closed。
    if "configured" in tg_config:
        if not tg_config.get("configured"):
            return None
        return parse_credential_pair(
            tg_config.get("configured_api_id"),
            tg_config.get("configured_api_hash"),
            source="panel",
        )
    # 兼容直接传入的原始配置字典（测试 / 旧调用方）
    if tg_config.get("is_custom") is False:
        return None
    return parse_credential_pair(
        tg_config.get("api_id"),
        tg_config.get("api_hash"),
        source="panel",
    )


def resolve_global_credentials(
    tg_config: Optional[Dict[str, Any]] = None,
    *,
    env_api_id: Any = _UNSET,
    env_api_hash: Any = _UNSET,
) -> ResolvedTelegramCredentials:
    """按 env 对 > 面板对 > 内置默认对的顺序解析全局凭据。"""
    raw_env_id, raw_env_hash = _resolve_env_values(env_api_id, env_api_hash)
    env_pair = parse_credential_pair(raw_env_id, raw_env_hash, source="env")
    if env_pair is not None:
        return env_pair

    panel_pair = _resolve_panel_pair(tg_config)
    if panel_pair is not None:
        return panel_pair

    default_pair = parse_credential_pair(
        DEFAULT_API_ID, DEFAULT_API_HASH, source="default"
    )
    if default_pair is None:  # pragma: no cover - 常量始终有效
        raise ApiCredentialsUnavailable(_INVALID_MESSAGE)
    return default_pair


def _resolve_account_pair(
    profile: Optional[Dict[str, Any]],
    account_name: Optional[str],
):
    if profile is None:
        return None
    return parse_credential_pair(
        profile.get("api_id"),
        profile.get("api_hash"),
        source="account",
        account_name=account_name,
    )


def resolve_telegram_credentials(
    tg_config: Optional[Dict[str, Any]] = None,
    *,
    env_api_id: Any = _UNSET,
    env_api_hash: Any = _UNSET,
    account_name: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
    include_account: bool = True,
) -> ResolvedTelegramCredentials:
    """唯一凭据解析入口：账号对优先，否则回退完整全局链。"""
    if include_account and profile is None and account_name:
        from backend.utils.tg_session import get_account_credentials

        profile = get_account_credentials(account_name)

    account_pair = _resolve_account_pair(profile, account_name)
    if account_pair is not None:
        return account_pair

    return resolve_global_credentials(
        tg_config,
        env_api_id=env_api_id,
        env_api_hash=env_api_hash,
    )


def resolve_telegram_api_credentials(
    tg_config: Dict[str, Any],
    *,
    env_api_id: Optional[str] = None,
    env_api_hash: Optional[str] = None,
    account_name: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Tuple[int, str]:
    """向后兼容的元组接口；新代码应使用 :func:`resolve_telegram_credentials`。"""
    resolved = resolve_telegram_credentials(
        tg_config,
        env_api_id=env_api_id,
        env_api_hash=env_api_hash,
        account_name=account_name,
        profile=profile,
    )
    return resolved.as_tuple()


def resolve_account_credentials(
    account_name: str,
    *,
    tg_config: Optional[Dict[str, Any]] = None,
    env_api_id: Any = _UNSET,
    env_api_hash: Any = _UNSET,
) -> ResolvedTelegramCredentials:
    """解析指定账号的生效凭据（账号对 > 全局链）。"""
    if tg_config is None:
        from backend.services.config import get_config_service

        tg_config = get_config_service().get_telegram_config()
    return resolve_telegram_credentials(
        tg_config,
        env_api_id=env_api_id,
        env_api_hash=env_api_hash,
        account_name=account_name,
    )


def ensure_session_credentials_match(
    account_name: str,
    resolved: ResolvedTelegramCredentials,
    *,
    session_dir=None,
) -> Optional[int]:
    """校验账号级专属凭据与 Session 创建时的 api_id 是否一致。

    返回 Session 中记录的 api_id（无法读取时返回 ``None``）。只有账号显式
    配置了专属凭据（``source == "account"``）时才会校验；不一致时抛
    :class:`ApiCredentialsMismatch`，调用方必须按「需重新登录」处理，
    不得删除 Session，也不得误判为会话失效。

    全局凭据（env / 面板 / 内置默认）的变更属于配置漂移，不能阻断旧 Session：
    Pyrogram 复用已有 Session 时使用 Session 内持久化的 api_id 建立
    InitConnection，``api_hash`` 只在新授权时使用，因此旧 Session 仍可正常
    使用。此类情况直接返回 Session 记录的 api_id，保持升级前行为。
    """
    from backend.utils.tg_session import get_account_session_api_id

    session_api_id = get_account_session_api_id(account_name, session_dir=session_dir)
    if not resolved.is_custom or not session_api_id:
        return session_api_id
    if int(session_api_id) != int(resolved.api_id):
        raise ApiCredentialsMismatch(
            f"账号 {account_name} 的 Session 使用 API ID {session_api_id} 创建，"
            f"与当前配置的 API ID {resolved.api_id} 不一致，请重新登录该账号"
        )
    return session_api_id


def _is_keep_marker(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    return cleaned in ("", "KEEP", "keep") or "****" in cleaned


def apply_account_credential_update(
    account_name: str,
    *,
    api_id: Any,
    api_hash: Any,
    fields_set: set[str],
) -> str:
    """应用 PATCH 的凭据更新语义，返回 ``saved`` / ``cleared`` / ``unchanged``。

    - 两项都未出现在请求中：不修改。
    - 两项均为空：清除账号级凭据，回退全局。
    - 仅更新 api_id（api_hash 为 ``KEEP``/空/掩码）：保留原加密 Hash。
    - 仅更新 api_hash：保留原 api_id。
    - 最终形成单边有效凭据：抛 :class:`ApiCredentialsPairRequired`。
    """
    from backend.utils.tg_session import (
        account_has_session_artifact,
        clear_account_credentials,
        get_account_credentials,
        set_account_credentials,
    )

    id_in_payload = "api_id" in fields_set
    hash_in_payload = "api_hash" in fields_set
    if not id_in_payload and not hash_in_payload:
        return "unchanged"

    id_present = not _is_keep_marker(api_id)
    hash_keep = _is_keep_marker(api_hash)

    if not id_present and hash_keep:
        # 显式提交两个空字段 = 清除；只提交一个空字段 = 不修改
        if id_in_payload and hash_in_payload:
            clear_account_credentials(account_name)
            return "cleared"
        return "unchanged"

    existing = get_account_credentials(account_name)
    existing_id = existing.get("api_id")
    existing_hash = existing.get("api_hash")

    if id_present and hash_keep:
        if not existing_hash:
            raise ApiCredentialsPairRequired(_PAIR_REQUIRED_MESSAGE)
        final_id = parse_api_id(api_id)
        final_hash = parse_api_hash(existing_hash)
    elif not id_present and not hash_keep:
        if not existing_id:
            raise ApiCredentialsPairRequired(_PAIR_REQUIRED_MESSAGE)
        final_id = parse_api_id(existing_id)
        final_hash = parse_api_hash(api_hash)
    else:
        final_id = parse_api_id(api_id)
        final_hash = parse_api_hash(api_hash)

    set_account_credentials(
        account_name,
        final_id,
        final_hash,
        mark_needs_relogin=account_has_session_artifact(account_name),
    )
    return "saved"
