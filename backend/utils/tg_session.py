from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from backend.core.config import get_settings
from backend.utils.atomic_io import write_text_atomic
from backend.utils.names import natural_sort_key
from backend.utils.time import utc_now, utc_now_iso

# session_string 校验与格式常量统一收敛到 tg_signer.compat（全项目唯一判定入口），
# 面板与 CLI 两条加载路径共享同一判定，避免同串不同判。
# 常量见 pyrogram/storage/storage.py：旧格式无 api_id，新格式含 api_id，均无版本前缀。
from tg_signer.compat import _SESSION_STRING_FORMAT, is_valid_session_string

_logger = logging.getLogger("backend.tg_session")

_SESSION_MODE_ENV = "TG_SESSION_MODE"
_SESSION_MODE_FILE = "file"
_SESSION_MODE_STRING = "string"

_GLOBAL_SEMAPHORE: Optional[asyncio.Semaphore] = None


def get_session_mode() -> str:
    mode = os.getenv(_SESSION_MODE_ENV, _SESSION_MODE_FILE).strip().lower()
    return _SESSION_MODE_STRING if mode == _SESSION_MODE_STRING else _SESSION_MODE_FILE


def is_string_session_mode() -> bool:
    return get_session_mode() == _SESSION_MODE_STRING


def get_global_semaphore() -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        limit = _resolve_concurrency_limit()
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE


def _resolve_concurrency_limit() -> int:
    # Priority: env var > global settings > default 1
    raw = (os.getenv("TG_GLOBAL_CONCURRENCY") or "").strip()
    if raw:
        try:
            return max(int(raw), 1)
        except ValueError:
            pass
    try:
        from backend.services.config import get_config_service

        settings = get_config_service().get_global_settings()
        val = settings.get("tg_global_concurrency")
        if val is not None:
            return max(int(val), 1)
    except Exception:
        pass
    # 默认：根据 CPU 核心数动态计算，上限为 5
    return min(os.cpu_count() or 4, 5)


def update_global_semaphore(new_limit: int) -> None:
    """Update the global semaphore with a new concurrency limit at runtime."""
    global _GLOBAL_SEMAPHORE
    if new_limit < 1:
        new_limit = 1
    _GLOBAL_SEMAPHORE = asyncio.Semaphore(new_limit)


def _account_store_path() -> Path:
    settings = get_settings()
    session_dir = settings.resolve_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / "accounts.json"


# accounts.json 进程内缓存：账号列表/状态/会话读取散落在登录、签到、
# 监听与状态检查等热路径，短窗口内复用避免每次请求全量读盘；
# 写入路径 _save_account_store 显式失效，保证读写一致
_ACCOUNT_STORE_CACHE_TTL = 2.0
_account_store_cache: dict[str, tuple[float, dict]] = {}


def _cached_account_store() -> dict:
    """带 2s TTL 的账户存储读取；TTL 与全局设置缓存策略一致。"""
    path = _account_store_path()
    key = str(path)
    now = time.monotonic()
    hit = _account_store_cache.get(key)
    if hit is not None and now - hit[0] < _ACCOUNT_STORE_CACHE_TTL:
        return hit[1]
    data = _read_account_store_file(path)
    _account_store_cache[key] = (now, data)
    return data


def _read_account_store_file(path: Path) -> dict:
    if not path.exists():
        return {"accounts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 损坏的 accounts.json 若静默返回空表，后续 _save_account_store 会用空数据
        # 原子覆盖原文件，导致账号存储数据不可恢复地丢失。这里先把损坏文件改名
        # 备份保留，再告警，供人工恢复或排查。
        try:
            # 时间戳用于文件名，不能含冒号等路径不友好字符，改用纯数字格式
            stamp = utc_now().strftime("%Y%m%dT%H%M%S")
            backup = path.with_name(f"accounts.json.corrupt-{stamp}")
            path.replace(backup)
        except OSError:
            backup = path
        _logger.warning(
            "accounts.json 读取失败，已备份到 %s 并回退为空存储: %s",
            backup,
            exc,
        )
        return {"accounts": {}}
    if not isinstance(data, dict):
        return {"accounts": {}}
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        data["accounts"] = {}
    return data


def _load_account_store() -> dict:
    return _cached_account_store()


def _save_account_store(data: dict) -> None:
    # 统一走 write_json_atomic：进程内写锁 + 唯一临时名 + fsync + rename，
    # 避免多协程/线程并发写固定 .tmp 文件时交错覆盖导致 accounts.json 损坏
    from backend.utils.atomic_io import write_json_atomic

    path = _account_store_path()
    write_json_atomic(path, data)
    # 写后失效缓存，下次读取重新落盘
    _account_store_cache.pop(str(path), None)


def list_account_names() -> list[str]:
    data = _load_account_store()
    return sorted(data["accounts"].keys(), key=natural_sort_key)


def get_account_session_string(account_name: str) -> Optional[str]:
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return None
    session_string = entry.get("session_string")
    if isinstance(session_string, str) and session_string.strip():
        cleaned = session_string.strip()
        from tg_signer.security import (
            SecretKeyError,
            decrypt_secret,
            is_encrypted_secret,
        )

        if is_encrypted_secret(cleaned):
            try:
                cleaned = decrypt_secret(cleaned) or ""
            except SecretKeyError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to decrypt session_string for account {account_name}"
                ) from exc
        # 非法串（含历史错误导出）视为不存在，便于调用方回退到文件导出
        if is_valid_session_string(cleaned):
            return cleaned
    return None


def get_account_storage_id(account_name: str) -> str:
    """Return the immutable identity used for account-scoped plugin storage.

    Legacy account records have no id and continue using their name until they
    are written again, preserving existing namespaces. Newly created records
    receive a random id so a delete/recreate cycle cannot inherit old state.
    """
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return str(account_name)
    storage_id = str(entry.get("storage_id") or "").strip()
    return storage_id or str(account_name)


def set_account_session_string(account_name: str, session_string: str) -> None:
    data = _load_account_store()
    accounts = data["accounts"]
    entry = accounts.get(account_name)
    legacy_entry = isinstance(entry, dict)
    if not isinstance(entry, dict):
        entry = {}
    # Keep legacy name-based namespaces stable for existing accounts. New
    # accounts get an immutable id so delete/recreate cannot inherit state.
    entry.setdefault("storage_id", account_name if legacy_entry else uuid.uuid4().hex)
    cleaned = session_string.strip()
    if not is_valid_session_string(cleaned):
        raise ValueError("invalid pyrogram session_string")
    from tg_signer.security import encrypt_secret

    stored = encrypt_secret(cleaned)
    entry["session_string"] = stored
    entry["updated_at"] = utc_now_iso()
    accounts[account_name] = entry
    _save_account_store(data)


def delete_account_session_string(account_name: str) -> None:
    data = _load_account_store()
    accounts = data["accounts"]
    if account_name in accounts:
        # Rotate legacy name-based storage identity before removal so a later
        # account with the same display name cannot inherit old plugin state.
        entry = accounts.get(account_name)
        if isinstance(entry, dict) and not entry.get("storage_id"):
            entry["storage_id"] = uuid.uuid4().hex
        accounts.pop(account_name, None)
        _save_account_store(data)


def rename_account_entry(old_account_name: str, new_account_name: str) -> None:
    if old_account_name == new_account_name:
        return

    data = _load_account_store()
    accounts = data["accounts"]

    entry = accounts.pop(old_account_name, None)
    if entry is None:
        return
    if new_account_name in accounts:
        raise ValueError(f"account_name {new_account_name} already exists")

    if not isinstance(entry, dict):
        entry = {}
    entry["updated_at"] = utc_now_iso()
    accounts[new_account_name] = entry
    _save_account_store(data)


def get_account_profile(account_name: str) -> dict[str, Any]:
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return {}
    credentials_needs_relogin = bool(entry.get("api_credentials_needs_relogin", False))
    return {
        "remark": entry.get("remark"),
        "proxy": entry.get("proxy"),
        "status": entry.get("status"),
        "status_message": entry.get("status_message"),
        "status_code": entry.get("status_code"),
        "status_checked_at": entry.get("status_checked_at"),
        "needs_relogin": bool(entry.get("needs_relogin", False))
        or credentials_needs_relogin,
        "invalid_notified_at": entry.get("invalid_notified_at"),
        "tags": list(entry.get("tags") or []),
        "device_family": entry.get("device_family"),
        "device_profile": entry.get("device_profile"),
        "proxy_probe_policy": entry.get("proxy_probe_policy", "strict"),
        "api_id": entry.get("api_id"),
        "has_api_hash": bool(entry.get("api_hash")),
        "api_credentials_needs_relogin": credentials_needs_relogin,
        "api_credentials_updated_at": entry.get("api_credentials_updated_at"),
    }


# ---------------------------------------------------------------------------
# 账号级 Telegram API 凭据（加密存储）
# ---------------------------------------------------------------------------


def _account_entry_for_update(account_name: str) -> tuple[dict, dict]:
    data = _load_account_store()
    accounts = data["accounts"]
    entry = accounts.get(account_name)
    if not isinstance(entry, dict):
        entry = {}
    return data, entry


def _decrypt_account_api_hash(account_name: str, raw: Any) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if not value:
        return None
    from tg_signer.security import (
        SecretKeyError,
        decrypt_secret,
        is_encrypted_secret,
    )

    if is_encrypted_secret(value):
        try:
            return decrypt_secret(value) or None
        except SecretKeyError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to decrypt api_hash for account {account_name}"
            ) from exc
    # 兼容历史上可能出现的明文（当前写入路径始终加密）
    return value


def get_account_credentials(account_name: str) -> dict[str, Any]:
    """读取账号级 API 凭据（Hash 已解密）。

    仅用于服务端解析；API 响应必须使用脱敏后的字段。
    """
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return {
            "api_id": None,
            "api_hash": None,
            "has_api_hash": False,
            "has_custom_api": False,
            "needs_relogin": False,
            "updated_at": None,
        }
    raw_id = entry.get("api_id")
    api_id: Optional[int]
    try:
        api_id = int(str(raw_id).strip()) if raw_id not in (None, "") else None
    except (TypeError, ValueError):
        api_id = None
    api_hash = _decrypt_account_api_hash(account_name, entry.get("api_hash"))
    has_custom = bool(raw_id not in (None, "") or entry.get("api_hash"))
    return {
        "api_id": api_id,
        "api_hash": api_hash,
        "has_api_hash": bool(api_hash),
        "has_custom_api": has_custom,
        "needs_relogin": bool(entry.get("api_credentials_needs_relogin", False)),
        "updated_at": entry.get("api_credentials_updated_at"),
    }


def get_account_license_credentials_for_api(account_name: str) -> dict[str, Any]:
    """API 层脱敏视图：绝不返回明文 Hash。"""
    from backend.services.telegram.credentials import mask_api_hash

    credentials = get_account_credentials(account_name)
    api_hash = credentials.get("api_hash")
    return {
        "use_custom_api": bool(credentials.get("has_custom_api")),
        "api_id": credentials.get("api_id"),
        "has_api_hash": bool(credentials.get("has_api_hash")),
        "api_hash_masked": mask_api_hash(api_hash),
        "api_credentials_source": "custom"
        if credentials.get("has_custom_api")
        else "global",
        "needs_relogin": bool(credentials.get("needs_relogin")),
    }


def account_has_session_artifact(account_name: str) -> bool:
    """账号是否已有可复用的登录会话（文件或存储串）。"""
    try:
        if get_account_session_string(account_name):
            return True
    except Exception:
        pass
    try:
        session_dir = get_settings().resolve_session_dir()
    except Exception:
        return False
    for candidate in (
        session_dir / f"{account_name}.session",
        session_string_file_path(session_dir, account_name),
    ):
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def set_account_credentials(
    account_name: str,
    api_id: int,
    api_hash: str,
    *,
    mark_needs_relogin: Optional[bool] = None,
) -> None:
    """加密写入账号级凭据；是否标记需重新登录默认按是否已有会话推断。"""
    from tg_signer.security import encrypt_secret

    data, entry = _account_entry_for_update(account_name)
    entry["api_id"] = int(api_id)
    entry["api_hash"] = encrypt_secret(str(api_hash))
    entry["api_credentials_updated_at"] = utc_now_iso()
    if mark_needs_relogin is None:
        mark_needs_relogin = account_has_session_artifact(account_name)
    entry["api_credentials_needs_relogin"] = bool(mark_needs_relogin)
    entry["updated_at"] = utc_now_iso()
    data["accounts"][account_name] = entry
    _save_account_store(data)


def clear_account_credentials(account_name: str) -> None:
    """清除账号级凭据，回到全局回退；同时清除凭据重登标记。"""
    data, entry = _account_entry_for_update(account_name)
    changed = False
    for key in (
        "api_id",
        "api_hash",
        "api_credentials_updated_at",
        "api_credentials_needs_relogin",
    ):
        if key in entry:
            entry.pop(key, None)
            changed = True
    if not changed:
        return
    entry["updated_at"] = utc_now_iso()
    data["accounts"][account_name] = entry
    _save_account_store(data)


def mark_account_credentials_relogin(account_name: str) -> None:
    data, entry = _account_entry_for_update(account_name)
    entry["api_credentials_needs_relogin"] = True
    entry["updated_at"] = utc_now_iso()
    data["accounts"][account_name] = entry
    _save_account_store(data)


def clear_account_credentials_relogin(account_name: str) -> None:
    data, entry = _account_entry_for_update(account_name)
    if not entry.get("api_credentials_needs_relogin"):
        return
    entry["api_credentials_needs_relogin"] = False
    entry["updated_at"] = utc_now_iso()
    data["accounts"][account_name] = entry
    _save_account_store(data)


def _read_sqlite_session_api_id(session_file: Path) -> Optional[int]:
    import sqlite3

    if not Path(session_file).is_file():
        return None
    try:
        # 只读打开，避免为探测凭据而创建/修改 Session 文件
        uri = f"file:{Path(session_file).resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5, check_same_thread=False)
        try:
            row = conn.execute("SELECT api_id FROM sessions LIMIT 1").fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row or row[0] in (None, "", 0):
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def session_string_api_id(session_string: Optional[str]) -> Optional[int]:
    """从 Pyrogram 新版 session_string 读取 api_id（旧格式无 api_id，返回 None）。"""
    if not isinstance(session_string, str) or not session_string.strip():
        return None
    import base64
    import struct

    cleaned = session_string.strip()
    try:
        raw = base64.urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except Exception:
        return None
    if len(raw) != struct.calcsize(_SESSION_STRING_FORMAT):
        return None
    try:
        _dc_id, api_id, _test_mode, _auth_key, _user_id, _is_bot = struct.unpack(
            _SESSION_STRING_FORMAT, raw
        )
    except struct.error:
        return None
    try:
        parsed = int(api_id)
    except (TypeError, ValueError):
        return None
    return parsed or None


def get_account_session_api_id(
    account_name: str, *, session_dir: Optional[Path] = None
) -> Optional[int]:
    """读取账号 Session 创建时的 api_id，不修改任何 Session 数据。"""
    if session_dir is None:
        session_dir = get_settings().resolve_session_dir()
    if not is_string_session_mode():
        api_id = _read_sqlite_session_api_id(
            Path(session_dir) / f"{account_name}.session"
        )
        if api_id:
            return api_id
    try:
        stored = get_account_session_string(account_name)
    except Exception:
        stored = None
    api_id = session_string_api_id(stored)
    if api_id:
        return api_id
    # 文件模式下的回退缓存串
    try:
        from_file = load_session_string_file(Path(session_dir), account_name)
    except Exception:
        from_file = None
    return session_string_api_id(from_file)


def replace_session_file(
    staging_base: Path, account_name: str, session_dir: Path
) -> None:
    """把登录暂存 Session 原子替换为正式 Session（保留旧文件直到成功）。"""
    import os
    import sqlite3

    staging_base = Path(staging_base)
    target = Path(session_dir) / f"{account_name}.session"
    staged = (
        staging_base.with_suffix(".session")
        if staging_base.suffix != ".session"
        else staging_base
    )
    if not staged.is_file():
        raise FileNotFoundError(f"staging session missing: {staged}")
    target.parent.mkdir(parents=True, exist_ok=True)

    # 先把暂存库的 WAL 尽量合并回主库，避免替换后丢失最新写入
    try:
        conn = sqlite3.connect(str(staged), timeout=5)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception:
        pass

    moved_suffixes: list[str] = []
    os.replace(staged, target)
    for suffix in ("-wal", "-shm", "-journal"):
        src_aux = Path(str(staged) + suffix)
        if not src_aux.exists():
            continue
        os.replace(src_aux, Path(str(target) + suffix))
        moved_suffixes.append(suffix)

    # 旧主库遗留、且新主库未携带的辅助文件必须删除，否则 SQLite 会误判
    for suffix in ("-wal", "-shm", "-journal"):
        if suffix in moved_suffixes:
            continue
        stale = Path(str(target) + suffix)
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_staging_session(staging_base: Path) -> None:
    """删除登录暂存 Session 及其 SQLite 辅助文件。"""
    staging_base = Path(staging_base)
    staged = (
        staging_base.with_suffix(".session")
        if staging_base.suffix != ".session"
        else staging_base
    )
    for path in (
        staged,
        Path(str(staged) + "-journal"),
        Path(str(staged) + "-wal"),
        Path(str(staged) + "-shm"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def get_account_proxy(account_name: str) -> Optional[str]:
    profile = get_account_profile(account_name)
    proxy = profile.get("proxy")
    if isinstance(proxy, str) and proxy.strip():
        return proxy.strip()
    return None


def set_account_profile(
    account_name: str,
    *,
    remark: Optional[str] = None,
    proxy: Optional[str] = None,
    proxy_probe_policy: Optional[str] = None,
    tags: Optional[list[str]] = None,
    device_family: Optional[str] = None,
    device_profile: Optional[dict] = None,
) -> None:
    data = _load_account_store()
    accounts = data["accounts"]
    entry = accounts.get(account_name)
    if not isinstance(entry, dict):
        entry = {}
    if remark is not None:
        entry["remark"] = remark.strip() if isinstance(remark, str) else remark
    if proxy is not None:
        entry["proxy"] = proxy.strip() if isinstance(proxy, str) else proxy
    if tags is not None:
        entry["tags"] = [str(t).strip() for t in tags if str(t).strip()]
    if device_family is not None:
        entry["device_family"] = (
            str(device_family).strip()
            if isinstance(device_family, str)
            else device_family
        )
    if device_profile is not None:
        entry["device_profile"] = device_profile
    if proxy_probe_policy is not None:
        entry["proxy_probe_policy"] = str(proxy_probe_policy).strip().lower()
    entry["updated_at"] = utc_now_iso()
    accounts[account_name] = entry
    _save_account_store(data)


def get_account_status(account_name: str) -> dict[str, Any]:
    profile = get_account_profile(account_name)
    status = profile.get("status")
    return {
        "status": status if isinstance(status, str) and status else "connected",
        "message": profile.get("status_message") or "",
        "code": profile.get("status_code"),
        "checked_at": profile.get("status_checked_at"),
        "needs_relogin": bool(profile.get("needs_relogin", False)),
        "invalid_notified_at": profile.get("invalid_notified_at"),
    }


def set_account_status(
    account_name: str,
    *,
    status: str,
    message: str = "",
    code: Optional[str] = None,
    needs_relogin: bool = False,
    invalid_notified_at: Optional[str] = None,
) -> None:
    data = _load_account_store()
    accounts = data["accounts"]
    entry = accounts.get(account_name)
    if not isinstance(entry, dict):
        entry = {}
    entry["status"] = status
    entry["status_message"] = message or ""
    entry["status_code"] = code
    entry["status_checked_at"] = utc_now_iso()
    entry["needs_relogin"] = bool(needs_relogin)
    if invalid_notified_at is not None:
        entry["invalid_notified_at"] = invalid_notified_at
    if status != "invalid":
        entry.pop("invalid_notified_at", None)
    entry["updated_at"] = utc_now_iso()
    accounts[account_name] = entry
    _save_account_store(data)


def session_string_file_path(session_dir: Path, account_name: str) -> Path:
    return session_dir / f"{account_name}.session_string"


# is_valid_session_string 由 tg_signer.compat 提供（见文件头部导入），
# 此处不再重复实现，保证 CLI 与面板判定完全一致


def load_session_string_file(session_dir: Path, account_name: str) -> Optional[str]:
    path = session_string_file_path(session_dir, account_name)
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
        except Exception:
            content = ""

        from tg_signer.security import (
            SecretKeyError,
            decrypt_secret,
            is_encrypted_secret,
        )

        if is_encrypted_secret(content):
            try:
                decrypted = decrypt_secret(content)
            except SecretKeyError:
                raise
            except Exception:
                decrypted = None
            if decrypted and is_valid_session_string(decrypted):
                return decrypted
            return None
        elif content and is_valid_session_string(content):
            # Legacy plaintext: migrate atomically to ciphertext.
            # Fail-closed: if migration fails (e.g. SecretKeyError), let it raise
            # without corrupting the original file.
            save_session_string_file(session_dir, account_name, content)
            return content

        # 坏缓存（含历史错误导出的 357 字符串）：删除后从 .session 重导
        try:
            path.unlink()
        except Exception:
            pass
    return _export_session_string_from_file(session_dir, account_name)


def _export_session_string_from_file(
    session_dir: Path, account_name: str
) -> Optional[str]:
    """从 .session SQLite 导出 Pyrogram 新版 session_string 并缓存。

    格式必须与 ``Client.export_session_string()`` 一致：
    ``struct.pack(">BI?256sQ?", dc_id, api_id, test_mode, auth_key, user_id, is_bot)``
    再 urlsafe_b64encode 并去掉 ``=`` padding。**禁止** Telethon 的 ``1`` 版本前缀。
    """
    import base64
    import sqlite3
    import struct

    session_file = session_dir / f"{account_name}.session"
    if not session_file.exists():
        return None

    try:
        conn = sqlite3.connect(str(session_file), timeout=10, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
        except Exception:
            pass

        try:
            row = conn.execute(
                "SELECT dc_id, api_id, test_mode, auth_key, user_id, is_bot FROM sessions"
            ).fetchone()
        except Exception as exc:
            # 未登录的 .session 无 sessions 表属常态，仅 debug；表损坏也会被归入此类
            _logger.debug("读取 sessions 表失败 account=%s: %s", account_name, exc)
            conn.close()
            return None

        if not row:
            conn.close()
            return None

        dc_id, api_id, test_mode, auth_key, user_id, is_bot = row
        conn.close()

        if not auth_key or not user_id:
            return None

        if isinstance(auth_key, memoryview):
            auth_key = auth_key.tobytes()
        elif not isinstance(auth_key, (bytes, bytearray)):
            auth_key = bytes(auth_key)
        auth_key = bytes(auth_key)
        if len(auth_key) < 256:
            auth_key = auth_key.ljust(256, b"\x00")
        elif len(auth_key) > 256:
            auth_key = auth_key[:256]

        # 新版 Pyrogram/kurigram 格式（含 api_id，无版本前缀）
        packed = struct.pack(
            _SESSION_STRING_FORMAT,
            int(dc_id),
            int(api_id or 0),
            bool(test_mode),
            auth_key,
            int(user_id),
            bool(is_bot),
        )
        session_string = base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")

        if not is_valid_session_string(session_string):
            return None

        # Cache it to .session_string file for future use
        # 原子写：会话字符串是登录态凭据，半截文件会让下次加载直接判定会话失效
        try:
            save_session_string_file(session_dir, account_name, session_string)
        except Exception:
            pass

        return session_string
    except Exception as exc:
        # sqlite 打开失败等异常需可观测：静默返回 None 会被误报为「session_string 不存在」
        _logger.warning("导出 session_string 失败 account=%s: %s", account_name, exc)
        return None


def save_session_string_file(
    session_dir: Path, account_name: str, session_string: str
) -> None:
    """原子写入加密会话字符串缓存（临时文件 + 权限收敛 0600 + fsync + rename）。

    Fail-closed: 遇到 SecretKeyError 必须抛出异常，绝不写入明文。
    """
    path = session_string_file_path(session_dir, account_name)
    cleaned = session_string.strip()
    from tg_signer.security import encrypt_secret

    stored = encrypt_secret(cleaned)
    write_text_atomic(path, stored)


def delete_session_string_file(session_dir: Path, account_name: str) -> None:
    path = session_string_file_path(session_dir, account_name)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


def load_account_session_string(
    account_name: str,
    *,
    session_dir: Path,
    session_mode: str,
) -> Optional[str]:
    """按会话模式加载账号 session_string；无可用值返回 None。

    string 模式：优先账号存储，回退会话文件导出；
    文件模式：仅尝试会话文件导出。
    """
    if session_mode == "string":
        return get_account_session_string(account_name) or load_session_string_file(
            session_dir, account_name
        )
    return load_session_string_file(session_dir, account_name)


def resolve_effective_proxy(
    account_name: str, global_proxy: Optional[str] = None
) -> Optional[str]:
    """解析账号生效代理：账号级代理优先，其次全局代理。"""
    proxy_value = get_account_proxy(account_name)
    if proxy_value:
        return proxy_value
    if isinstance(global_proxy, str) and global_proxy.strip():
        return global_proxy.strip()
    return None
