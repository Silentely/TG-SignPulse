"""TG-SignPulse 插件扩展核心模块。

提供 PluginContext 运行上下文、PluginRegistry 注册表及动态隔离加载能力。
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Literal, Optional, Tuple, Union

_logger = logging.getLogger("tg_signer.plugins")


class PluginTimeoutError(RuntimeError):
    """插件执行超时；该错误不可通过步骤级重试安全恢复。"""


class PluginStorageBackend:
    """基于 SQLite 的线程与多进程安全轻量级 KV 存储后端。"""

    @staticmethod
    def _escape_like(text: str) -> str:
        return text.replace("/", "//").replace("%", "/%").replace("_", "/_")

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is not None:
            self.db_path = Path(db_path)
        elif os.getenv("PLUGIN_STORAGE_PATH"):
            self.db_path = Path(os.getenv("PLUGIN_STORAGE_PATH"))
        else:
            base_dir = os.getenv("APP_DATA_DIR") or os.getenv("TG_SIGNER_DATA_DIR")
            if base_dir:
                self.db_path = Path(base_dir) / "plugin_storage.db"
            elif Path("/data").is_dir() and os.access("/data", os.W_OK):
                self.db_path = Path("/data/plugin_storage.db")
            else:
                self.db_path = Path.cwd() / "data" / "plugin_storage.db"

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except Exception as e:
            _logger.warning("初始化插件持久化存储失败 (%s): %s", self.db_path, e)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        pass

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_kv (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (namespace, key)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_plugin_kv_expires
                ON plugin_kv (expires_at)
                WHERE expires_at IS NOT NULL;
                """
            )
            conn.commit()

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        now = time.time()
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT value, expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
                row = cur.fetchone()
                if not row:
                    return default
                val_str, expires_at = row
                if expires_at is not None and expires_at < now:
                    conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                        (namespace, key),
                    )
                    conn.commit()
                    return default
                try:
                    return json.loads(val_str)
                except Exception:
                    return val_str
        except Exception as exc:
            _logger.warning("插件读取存储失败 [%s:%s]: %s", namespace, key, exc)
            return default

    def set(
        self, namespace: str, key: str, value: Any, ttl: Optional[float] = None
    ) -> None:
        now = time.time()
        expires_at = (now + ttl) if (ttl is not None and ttl > 0) else None
        val_str = json.dumps(value, ensure_ascii=False)
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at;
                    """,
                    (namespace, key, val_str, expires_at),
                )
                conn.commit()
        except Exception as exc:
            _logger.warning("插件写入存储失败 [%s:%s]: %s", namespace, key, exc)

    def increment(
        self, namespace: str, key: str, delta: int = 1, default: int = 0
    ) -> Optional[int]:
        """在事务锁内原子递增整数值，返回递增后的结果；写入失败返回 None。

        若目标键带有仍有效的 TTL，递增后保留原过期时间；过期键与新建键重置为永久。
        """
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT value, expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
                current = default
                if row and (row[1] is None or row[1] >= now):
                    try:
                        parsed = json.loads(row[0])
                        if isinstance(parsed, (int, float)) and not isinstance(
                            parsed, bool
                        ):
                            current = int(parsed)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                updated = current + int(delta)
                conn.execute(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, NULL)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = CASE
                            WHEN plugin_kv.expires_at IS NOT NULL
                                 AND plugin_kv.expires_at >= ?
                            THEN plugin_kv.expires_at
                            ELSE NULL
                        END
                    """,
                    (namespace, key, json.dumps(updated), now),
                )
                conn.commit()
                return updated
        except Exception as exc:
            _logger.warning("插件原子递增存储失败 [%s:%s]: %s", namespace, key, exc)
            return None

    def delete(self, namespace: str, key: str) -> bool:
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as exc:
            _logger.warning("插件删除存储失败 [%s:%s]: %s", namespace, key, exc)
            return False

    def clear(self, namespace: Optional[str] = None) -> int:
        try:
            with self._conn() as conn:
                if namespace:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ?", (namespace,)
                    )
                else:
                    cur = conn.execute("DELETE FROM plugin_kv")
                conn.commit()
                return cur.rowcount
        except Exception as exc:
            _logger.warning("插件清空存储失败: %s", exc)
            return 0

    def purge_expired(self, namespace: Optional[str] = None) -> int:
        """主动清理已过期的所有记录，返回被清理的记录数。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if namespace:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ? AND expires_at IS NOT NULL AND expires_at < ?",
                        (namespace, now),
                    )
                else:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE expires_at IS NOT NULL AND expires_at < ?",
                        (now,),
                    )
                conn.commit()
                return cur.rowcount
        except Exception as exc:
            _logger.warning("插件清理过期存储失败: %s", exc)
            return 0

    def keys(self, namespace: str, prefix: str = "") -> List[str]:
        """列出指定命名空间下未过期的键名（支持前缀匹配），自动淘汰已过期记录。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if prefix:
                    escaped_prefix = self._escape_like(prefix)
                    cur = conn.execute(
                        "SELECT key, expires_at FROM plugin_kv WHERE namespace = ? AND key LIKE ? ESCAPE '/'",
                        (namespace, f"{escaped_prefix}%"),
                    )
                else:
                    cur = conn.execute(
                        "SELECT key, expires_at FROM plugin_kv WHERE namespace = ?",
                        (namespace,),
                    )
                rows = cur.fetchall()
                valid_keys: List[str] = []
                expired_keys: List[str] = []
                for k, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                    else:
                        valid_keys.append(k)
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return sorted(valid_keys)
        except Exception as exc:
            _logger.warning("插件读取存储键列表失败 [%s]: %s", namespace, exc)
            return []

    def mget(self, namespace: str, keys: List[str]) -> Dict[str, Any]:
        """批量根据指定键列表读取键值对（自动分片规避 SQLite 变量上限，自动过滤与清理过期记录）。"""
        if not keys:
            return {}
        now = time.time()
        res: Dict[str, Any] = {}
        expired_keys: List[str] = []
        CHUNK_SIZE = 500
        key_list = list(keys)
        try:
            with self._conn() as conn:
                for i in range(0, len(key_list), CHUNK_SIZE):
                    chunk = key_list[i : i + CHUNK_SIZE]
                    placeholders = ",".join("?" for _ in chunk)
                    params = [namespace] + chunk
                    cur = conn.execute(
                        f"SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ? AND key IN ({placeholders})",
                        params,
                    )
                    rows = cur.fetchall()
                    for k, val_str, exp in rows:
                        if exp is not None and exp < now:
                            expired_keys.append(k)
                            continue
                        try:
                            res[k] = json.loads(val_str)
                        except Exception:
                            res[k] = val_str

                if expired_keys:
                    for i in range(0, len(expired_keys), CHUNK_SIZE):
                        exp_chunk = expired_keys[i : i + CHUNK_SIZE]
                        del_placeholders = ",".join("?" for _ in exp_chunk)
                        try:
                            conn.execute(
                                f"DELETE FROM plugin_kv WHERE namespace = ? AND key IN ({del_placeholders})",
                                [namespace] + exp_chunk,
                            )
                        except Exception as clean_exc:
                            _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                    conn.commit()
                return res
        except Exception as exc:
            _logger.warning("插件批量按键读取存储失败 [%s]: %s", namespace, exc)
            return {}

    def mset(
        self,
        namespace: str,
        mapping: Dict[str, Any],
        ttl: Optional[float] = None,
    ) -> None:
        """批量写入键值对，支持统一指定过期时间。"""
        if not mapping:
            return
        now = time.time()
        expires_at = (now + ttl) if (ttl is not None and ttl > 0) else None
        try:
            rows = []
            for k, val in mapping.items():
                val_str = json.dumps(val, ensure_ascii=False)
                rows.append((namespace, k, val_str, expires_at))
            with self._conn() as conn:
                conn.executemany(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at
                    """,
                    rows,
                )
                conn.commit()
        except Exception as exc:
            _logger.warning("插件批量写入存储失败 [%s]: %s", namespace, exc)

    def get_all(self, namespace: str, prefix: str = "") -> Dict[str, Any]:
        """批量读取指定命名空间下所有未过期的键值对（支持前缀过滤），自动淘汰已过期记录。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if prefix:
                    escaped_prefix = self._escape_like(prefix)
                    cur = conn.execute(
                        "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ? AND key LIKE ? ESCAPE '/'",
                        (namespace, f"{escaped_prefix}%"),
                    )
                else:
                    cur = conn.execute(
                        "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ?",
                        (namespace,),
                    )
                rows = cur.fetchall()
                res: Dict[str, Any] = {}
                expired_keys: List[str] = []
                for k, val_str, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                        continue
                    try:
                        res[k] = json.loads(val_str)
                    except Exception:
                        res[k] = val_str
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return res
        except Exception as exc:
            _logger.warning("插件批量读取存储失败 [%s]: %s", namespace, exc)
            return {}

    def list_namespaces(self, plugin_name: Optional[str] = None) -> List[str]:
        """列出当前数据库中存在的所有命名空间，可根据插件名称进行关联匹配。"""
        try:
            with self._conn() as conn:
                if plugin_name:
                    escaped_name = self._escape_like(plugin_name)
                    cur = conn.execute(
                        """
                        SELECT DISTINCT namespace FROM plugin_kv
                        WHERE namespace = ?
                           OR namespace LIKE ? ESCAPE '/'
                           OR namespace LIKE ? ESCAPE '/'
                        """,
                        (
                            plugin_name,
                            f"%:{escaped_name}",
                            f"__test__:%:{escaped_name}",
                        ),
                    )
                else:
                    cur = conn.execute("SELECT DISTINCT namespace FROM plugin_kv")
                rows = cur.fetchall()
                return sorted([r[0] for r in rows if r[0]])
        except Exception as exc:
            _logger.warning("查询插件存储命名空间失败: %s", exc)
            return []

    def get_all_records(self, namespace: str) -> List[Dict[str, Any]]:
        """获取指定命名空间下的完整结构化记录（含过期时间与剩余 TTL）。"""
        now = time.time()
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ?",
                    (namespace,),
                )
                rows = cur.fetchall()
                records: List[Dict[str, Any]] = []
                expired_keys: List[str] = []
                for k, val_str, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                        continue
                    try:
                        parsed_val = json.loads(val_str)
                    except Exception:
                        parsed_val = val_str
                    records.append(
                        {
                            "key": k,
                            "value": parsed_val,
                            "expires_at": exp,
                            "ttl_remaining": round(exp - now, 1)
                            if exp is not None
                            else None,
                        }
                    )
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return sorted(records, key=lambda x: x["key"])
        except Exception as exc:
            _logger.warning("插件读取存储记录失败 [%s]: %s", namespace, exc)
            return []


class PluginStorageClient:
    """供插件开发者使用的异步键值存储接口。"""

    def __init__(self, namespace: str, backend: Optional[PluginStorageBackend] = None):
        self.namespace = namespace
        self._backend = backend or PluginStorageBackend()

    async def get(self, key: str, default: Any = None) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.get, self.namespace, key, default
            )
        except RuntimeError:
            return self._backend.get(self.namespace, key, default)

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._backend.set, self.namespace, key, value, ttl
            )
        except RuntimeError:
            self._backend.set(self.namespace, key, value, ttl)

    async def increment(
        self, key: str, delta: int = 1, default: int = 0
    ) -> Optional[int]:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.increment, self.namespace, key, delta, default
            )
        except RuntimeError:
            return self._backend.increment(self.namespace, key, delta, default)

    async def delete(self, key: str) -> bool:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.delete, self.namespace, key
            )
        except RuntimeError:
            return self._backend.delete(self.namespace, key)

    async def clear(self) -> int:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._backend.clear, self.namespace)
        except RuntimeError:
            return self._backend.clear(self.namespace)

    async def keys(self, prefix: str = "") -> List[str]:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.keys, self.namespace, prefix
            )
        except RuntimeError:
            return self._backend.keys(self.namespace, prefix)

    async def mget(self, keys: List[str]) -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.mget, self.namespace, keys
            )
        except RuntimeError:
            return self._backend.mget(self.namespace, keys)

    async def mset(self, mapping: Dict[str, Any], ttl: Optional[float] = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._backend.mset, self.namespace, mapping, ttl
            )
        except RuntimeError:
            self._backend.mset(self.namespace, mapping, ttl)

    async def get_all(self, prefix: str = "") -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._backend.get_all, self.namespace, prefix
            )
        except RuntimeError:
            return self._backend.get_all(self.namespace, prefix)


@dataclass
class PluginContext:
    app: Any
    chat_id: int
    message_thread_id: Optional[int] = None
    message: Optional[Any] = None
    params: Dict[str, Any] = field(default_factory=dict)
    logger: Any = None
    plugin_name: str = ""
    _storage: Optional[PluginStorageClient] = None
    _global_storage: Optional[PluginStorageClient] = None

    @property
    def storage(self) -> PluginStorageClient:
        if self._storage is None:
            ns = (
                f"{self.chat_id}:{self.plugin_name}"
                if self.plugin_name
                else str(self.chat_id)
            )
            self._storage = PluginStorageClient(namespace=ns)
        return self._storage

    @storage.setter
    def storage(self, value: PluginStorageClient) -> None:
        self._storage = value

    @property
    def global_storage(self) -> PluginStorageClient:
        """全局/跨会话持久化存储客户端，以 'global:{plugin_name}' 为命名空间。"""
        if self._global_storage is None:
            ns = f"global:{self.plugin_name}" if self.plugin_name else "global"
            self._global_storage = PluginStorageClient(namespace=ns)
        return self._global_storage

    @global_storage.setter
    def global_storage(self, value: PluginStorageClient) -> None:
        self._global_storage = value

    def get_param(
        self,
        key: str,
        default: Any = None,
        param_type: Optional[type] = None,
    ) -> Any:
        """安全读取插件配置参数，支持缺省回退与自动类型转换。"""
        raw = (self.params or {}).get(key)
        if raw is None:
            return default
        if param_type is None:
            return raw
        try:
            if param_type is bool:
                if isinstance(raw, bool):
                    return raw
                if isinstance(raw, str):
                    val = raw.strip().lower()
                    if val in ("true", "1", "yes", "on"):
                        return True
                    if val in ("false", "0", "no", "off"):
                        return False
                    return default
                return bool(raw)
            return param_type(raw)
        except (ValueError, TypeError):
            return default

    def log(self, msg: str, level: str = "INFO") -> None:
        if self.logger is not None:
            if hasattr(self.logger, "log") and callable(self.logger.log):
                try:
                    self.logger.log(msg, level=level)
                    return
                except TypeError:
                    lvl = getattr(logging, level.upper(), logging.INFO)
                    self.logger.log(lvl, msg)
                    return
            if callable(self.logger):
                self.logger(msg)
                return
        lvl = getattr(logging, level.upper(), logging.INFO)
        _logger.log(lvl, msg)

    async def reply(self, text: str, **kwargs) -> Any:
        if self.message is not None and hasattr(self.message, "id"):
            kwargs.setdefault("reply_to_message_id", self.message.id)
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        sender = getattr(self.logger, "send_message", None)
        if sender is not None and callable(sender):
            try:
                res = sender(self.chat_id, text, **kwargs)
                if inspect.isawaitable(res):
                    return await res
            except TypeError:
                pass
        return await self.app.send_message(self.chat_id, text, **kwargs)

    async def send_message(self, text: str, **kwargs) -> Any:
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        sender = getattr(self.logger, "send_message", None)
        if sender is not None and callable(sender):
            try:
                res = sender(self.chat_id, text, **kwargs)
                if inspect.isawaitable(res):
                    return await res
            except TypeError:
                pass
        return await self.app.send_message(self.chat_id, text, **kwargs)

    async def click(self, text_or_index: Union[str, int], **kwargs) -> Any:
        if not self.message or not hasattr(self.message, "click"):
            raise RuntimeError("当前上下文中无有效消息，无法执行点击按钮")
        return await self.message.click(text_or_index, **kwargs)

    async def react(
        self, emoji: str, message_id: Optional[int] = None, **kwargs
    ) -> Any:
        """向消息添加 Emoji 表情表态（Reaction）。"""
        msg_id = message_id
        if msg_id is None and self.message is not None and hasattr(self.message, "id"):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中无有效消息 ID，无法执行表情表态")

        reactor = getattr(self.logger, "send_reaction", None)
        if reactor is not None and callable(reactor):
            try:
                res = reactor(self.chat_id, message_id=msg_id, emoji=emoji, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass

        if hasattr(self.app, "send_reaction") and callable(self.app.send_reaction):
            return await self.app.send_reaction(
                self.chat_id, message_id=msg_id, emoji=emoji, **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 send_reaction 方法")

    async def edit_message(
        self, text: str, message_id: Optional[int] = None, **kwargs
    ) -> Any:
        """编辑指定消息（默认编辑当前上下文触发的消息）。"""
        msg_id = message_id
        if msg_id is None and self.message is not None and hasattr(self.message, "id"):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中无有效消息 ID，无法执行编辑")
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)

        editor = getattr(self.logger, "edit_message", None)
        if editor is not None and callable(editor):
            try:
                res = editor(self.chat_id, message_id=msg_id, text=text, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass

        if hasattr(self.app, "edit_message_text") and callable(
            self.app.edit_message_text
        ):
            return await self.app.edit_message_text(
                self.chat_id, message_id=msg_id, text=text, **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 edit_message_text 方法")

    async def delete_message(self, message_id: Optional[int] = None, **kwargs) -> Any:
        """删除指定消息（默认删除当前上下文触发的消息）。"""
        msg_id = message_id
        if msg_id is None and self.message is not None and hasattr(self.message, "id"):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中无有效消息 ID，无法执行删除")

        deleter = getattr(self.logger, "delete_message", None)
        if deleter is not None and callable(deleter):
            try:
                res = deleter(self.chat_id, message_id=msg_id, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass

        if hasattr(self.app, "delete_messages") and callable(self.app.delete_messages):
            return await self.app.delete_messages(
                self.chat_id, message_ids=[msg_id], **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 delete_messages 方法")

    async def send_photo(
        self, photo: Union[str, bytes], caption: Optional[str] = None, **kwargs: Any
    ) -> Any:
        """发送图片到当前会话。"""
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        if caption is not None:
            kwargs["caption"] = caption
        sender = getattr(self.logger, "send_photo", None)
        if sender is not None and callable(sender):
            try:
                res = sender(self.chat_id, photo, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if hasattr(self.app, "send_photo") and callable(self.app.send_photo):
            return await self.app.send_photo(self.chat_id, photo, **kwargs)
        raise RuntimeError("Telegram Client 不支持 send_photo 方法")

    async def send_document(
        self, document: Union[str, bytes], caption: Optional[str] = None, **kwargs: Any
    ) -> Any:
        """发送文档/文件到当前会话。"""
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        if caption is not None:
            kwargs["caption"] = caption
        sender = getattr(self.logger, "send_document", None)
        if sender is not None and callable(sender):
            try:
                res = sender(self.chat_id, document, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if hasattr(self.app, "send_document") and callable(self.app.send_document):
            return await self.app.send_document(self.chat_id, document, **kwargs)
        raise RuntimeError("Telegram Client 不支持 send_document 方法")

    async def pin_message(self, message_id: Optional[int] = None, **kwargs: Any) -> Any:
        """置顶当前或指定消息。"""
        msg_id = message_id
        if msg_id is None and self.message is not None and hasattr(self.message, "id"):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行置顶")
        pinner = getattr(self.logger, "pin_chat_message", None)
        if pinner is not None and callable(pinner):
            try:
                res = pinner(self.chat_id, message_id=msg_id, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if hasattr(self.app, "pin_chat_message") and callable(
            self.app.pin_chat_message
        ):
            return await self.app.pin_chat_message(
                self.chat_id, message_id=msg_id, **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 pin_chat_message 方法")

    async def unpin_message(
        self, message_id: Optional[int] = None, **kwargs: Any
    ) -> Any:
        """取消置顶当前或指定消息（若未指定 message_id 则取消所有置顶）。"""
        msg_id = message_id
        if msg_id is None and self.message is not None and hasattr(self.message, "id"):
            msg_id = self.message.id
        unpinner = getattr(self.logger, "unpin_chat_message", None)
        if unpinner is not None and callable(unpinner):
            try:
                res = unpinner(self.chat_id, message_id=msg_id, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if (
            msg_id is not None
            and hasattr(self.app, "unpin_chat_message")
            and callable(self.app.unpin_chat_message)
        ):
            return await self.app.unpin_chat_message(
                self.chat_id, message_id=msg_id, **kwargs
            )
        if hasattr(self.app, "unpin_all_chat_messages") and callable(
            self.app.unpin_all_chat_messages
        ):
            return await self.app.unpin_all_chat_messages(self.chat_id, **kwargs)
        raise RuntimeError("Telegram Client 不支持取消置顶方法")

    async def get_messages(
        self, message_ids: Union[int, List[int]], **kwargs: Any
    ) -> Any:
        """根据消息 ID 获取消息对象。"""
        getter = getattr(self.logger, "get_messages", None)
        if getter is not None and callable(getter):
            try:
                res = getter(self.chat_id, message_ids=message_ids, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if hasattr(self.app, "get_messages") and callable(self.app.get_messages):
            return await self.app.get_messages(
                self.chat_id, message_ids=message_ids, **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 get_messages 方法")

    async def forward_messages(
        self,
        chat_id: Union[int, str],
        from_chat_id: Optional[Union[int, str]] = None,
        message_ids: Optional[Union[int, List[int]]] = None,
        **kwargs: Any,
    ) -> Any:
        """转发消息到目标会话。"""
        src_chat = from_chat_id or self.chat_id
        mids = message_ids
        if mids is None and self.message is not None and hasattr(self.message, "id"):
            mids = self.message.id
        if mids is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行转发")
        forwarder = getattr(self.logger, "forward_messages", None)
        if forwarder is not None and callable(forwarder):
            try:
                res = forwarder(
                    chat_id, from_chat_id=src_chat, message_ids=mids, **kwargs
                )
                if inspect.isawaitable(res):
                    return await res
                return res
            except TypeError:
                pass
        if hasattr(self.app, "forward_messages") and callable(
            self.app.forward_messages
        ):
            return await self.app.forward_messages(
                chat_id, from_chat_id=src_chat, message_ids=mids, **kwargs
            )
        raise RuntimeError("Telegram Client 不支持 forward_messages 方法")


@dataclass
class PluginLoadError:
    file_path: str
    plugin_name: str
    error_type: Literal["missing_dependency", "syntax_error", "load_error"]
    error_message: str
    missing_module: Optional[str] = None
    suggested_command: Optional[str] = None
    timestamp: str = ""


@dataclass
class PluginMeta:
    name: str
    handler: Callable[[PluginContext], Any]
    mode: Literal["reactive", "active"] = "reactive"
    description: str = ""
    version: str = "1.0.0"
    updated_at: str = ""
    author: str = ""
    source_path: Optional[str] = None
    params_schema: Optional[List[Dict[str, Any]]] = None
    enabled: bool = True
    builtin: bool = False
    permissions: List[str] = field(default_factory=list)
    doc: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    icon: Optional[str] = None
    homepage: Optional[str] = None
    isolation_mode: Literal["subprocess", "in_process"] = "subprocess"


@dataclass
class PluginMetrics:
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_run_at: Optional[str] = None
    last_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    last_error: Optional[str] = None

    @property
    def avg_duration_ms(self) -> float:
        return (
            round(self.total_duration_ms / self.run_count, 1)
            if self.run_count > 0
            else 0.0
        )

    @property
    def success_rate(self) -> float:
        # 从未执行时无成功率可言，返回 0.0 而非 100.0，避免误导
        return (
            round((self.success_count / self.run_count) * 100, 1)
            if self.run_count > 0
            else 0.0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_run_at": self.last_run_at,
            "last_duration_ms": self.last_duration_ms,
            "avg_duration_ms": self.avg_duration_ms,
            "success_rate": self.success_rate,
            "last_error": self.last_error,
        }


@dataclass
class PluginExecutionRecord:
    timestamp: str
    duration_ms: float
    success: bool
    trigger_type: str = "manual_test"
    error: Optional[str] = None
    log_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "trigger_type": self.trigger_type,
            "error": self.error,
            "log_summary": self.log_summary,
        }


def is_builtin_plugin_path(path: Union[str, Path, None]) -> bool:
    """判断给定文件或目录路径是否属于官方内置插件目录。

    说明：
     标识用于向前端展示与接口序列化时清晰区分插件来源：
    - True: 来源于系统镜像或官方仓库随附的内置插件目录（如 /app/plugins、BUILTIN_PLUGINS_DIR 或 cwd 下的 plugins/）；
    - False: 来源于用户自定义挂载目录（如 /data/plugins 或 PLUGINS_DIR）。
    判定基于严格的 pathlib 目录层级包含关系（p == b 或 b in p.parents），不代表第三方代码签名认证。
    """
    if not path:
        return False
    try:
        p = Path(path).resolve()
        for b in PluginRegistry.get_builtin_directories():
            try:
                b_res = b.resolve()
                if b_res.is_dir() and (p == b_res or b_res in p.parents):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


class PluginRegistry:
    _plugins: Dict[str, PluginMeta] = {}
    _loaded_files: set[Path] = set()
    _disabled_plugins: set[str] = set()
    _load_errors: Dict[str, PluginLoadError] = {}
    _metrics: Dict[str, PluginMetrics] = {}
    _execution_history: Dict[str, deque[PluginExecutionRecord]] = {}

    @staticmethod
    def _is_same_registration(
        a: Callable[[PluginContext], Any], b: Callable[[PluginContext], Any]
    ) -> bool:
        """判断两个函数是否来自同一源文件的同一处定义（即同一插件的重复加载）。"""
        try:
            file_a = inspect.getsourcefile(a)
            file_b = inspect.getsourcefile(b)
            line_a = a.__code__.co_firstlineno
            line_b = b.__code__.co_firstlineno
        except Exception:
            return False
        return bool(file_a and file_a == file_b and line_a == line_b)

    @classmethod
    def record_execution(
        cls,
        name: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        trigger_type: str = "manual_test",
        log_summary: Optional[str] = None,
    ) -> None:
        metrics = cls._metrics.setdefault(name, PluginMetrics())
        # 时长统一取整一次（保留两位，兼顾亚毫秒执行的可见性），保证 last/total/avg 口径一致
        rounded_ms = round(max(0.0, float(duration_ms)), 2)
        metrics.run_count += 1
        metrics.total_duration_ms += rounded_ms
        metrics.last_duration_ms = rounded_ms
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metrics.last_run_at = now_str
        if success:
            metrics.success_count += 1
        else:
            metrics.failure_count += 1
            metrics.last_error = str(error) if error else "Unknown error"

        hist = cls._execution_history.setdefault(name, deque(maxlen=30))
        record = PluginExecutionRecord(
            timestamp=now_str,
            duration_ms=round(float(duration_ms), 1),
            success=success,
            trigger_type=trigger_type,
            error=str(error) if error else None,
            log_summary=log_summary,
        )
        hist.appendleft(record)

    @classmethod
    def get_metrics(cls, name: str) -> Optional[PluginMetrics]:
        return cls._metrics.get(name)

    @classmethod
    def get_execution_history(
        cls, name: str, limit: int = 20
    ) -> List[PluginExecutionRecord]:
        hist = cls._execution_history.get(name)
        if not hist:
            return []
        return list(hist)[:limit]

    @classmethod
    def clear_execution_history(cls, name: Optional[str] = None) -> int:
        if name:
            hist = cls._execution_history.pop(name, None)
            return len(hist) if hist else 0
        total = sum(len(h) for h in cls._execution_history.values())
        cls._execution_history.clear()
        return total

    @classmethod
    def reset_metrics(cls, name: Optional[str] = None) -> None:
        if name:
            cls._metrics.pop(name, None)
            cls._execution_history.pop(name, None)
        else:
            cls._metrics.clear()
            cls._execution_history.clear()

    @classmethod
    def get_load_errors(cls) -> List[PluginLoadError]:
        return list(cls._load_errors.values())

    @classmethod
    def set_disabled(cls, name: str, disabled: bool = True) -> None:
        if disabled:
            cls._disabled_plugins.add(name)
        else:
            cls._disabled_plugins.discard(name)
        meta = cls._plugins.get(name)
        if meta:
            meta.enabled = not disabled

    @classmethod
    def is_enabled(cls, name: str) -> bool:
        return name not in cls._disabled_plugins

    @classmethod
    def register(
        cls,
        name: str,
        mode: Literal["reactive", "active"] = "reactive",
        description: str = "",
        params_schema: Optional[List[Dict[str, Any]]] = None,
        permissions: Optional[List[str]] = None,
        version: str = "1.0.0",
        updated_at: Optional[str] = None,
        author: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        icon: Optional[str] = None,
        homepage: Optional[str] = None,
        isolation_mode: Literal["subprocess", "in_process"] = "subprocess",
    ) -> Callable:
        def decorator(
            fn: Callable[[PluginContext], Any],
        ) -> Callable[[PluginContext], Any]:
            existing = cls._plugins.get(name)
            if existing is not None and existing.handler is not fn:
                is_placeholder = getattr(existing.handler, "_is_placeholder", False)
                if not is_placeholder and not cls._is_same_registration(
                    existing.handler, fn
                ):
                    raise ValueError(f"插件名称已注册: {name}")
            source_file = None
            try:
                source_file = inspect.getsourcefile(fn)
            except Exception:
                pass

            doc_str = getattr(fn, "__doc__", None)
            if not doc_str:
                try:
                    mod = inspect.getmodule(fn)
                    if mod and mod.__doc__:
                        doc_str = mod.__doc__.strip()
                except Exception:
                    pass
            if doc_str:
                doc_str = doc_str.strip()

            cls._plugins[name] = PluginMeta(
                name=name,
                handler=fn,
                mode=mode,
                description=description,
                version=version or "1.0.0",
                updated_at=updated_at or "",
                author=author or "",
                source_path=source_file,
                params_schema=params_schema or [],
                enabled=cls.is_enabled(name),
                builtin=is_builtin_plugin_path(source_file),
                permissions=list(permissions or []),
                doc=doc_str or None,
                category=category,
                tags=list(tags or []),
                icon=icon,
                homepage=homepage,
                isolation_mode=isolation_mode,
            )
            return fn

        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[PluginMeta]:
        return cls._plugins.get(name)

    @classmethod
    def list_plugins(cls) -> Dict[str, PluginMeta]:
        return dict(cls._plugins)

    @classmethod
    def clear(cls) -> None:
        cls._plugins.clear()
        cls._loaded_files.clear()
        cls._disabled_plugins.clear()
        cls._load_errors.clear()
        cls._metrics.clear()
        cls._execution_history.clear()
        for module_name in list(sys.modules):
            if module_name.startswith("tg_signer_plugin_"):
                sys.modules.pop(module_name, None)

    @classmethod
    def load_plugins_from_dir(cls, directory: Union[str, Path]) -> int:
        dir_path = Path(directory).resolve()
        if not dir_path.is_dir():
            _logger.debug("插件目录不存在: %s", dir_path)
            return 0

        initial_keys = set(cls._plugins.keys())
        candidate_files: list[Path] = []

        try:
            for p in sorted(dir_path.iterdir()):
                if p.name.startswith((".", "_")):
                    continue
                if p.is_dir():
                    if (p / "main.py").is_file():
                        candidate_files.append(p / "main.py")
                    elif (p / "__init__.py").is_file():
                        candidate_files.append(p / "__init__.py")
                elif p.is_file() and p.suffix == ".py":
                    candidate_files.append(p)
        except OSError as exc:
            _logger.warning("遍历插件目录异常 %s: %s", dir_path, exc)
            return 0

        for plugin_file in candidate_files:
            resolved_file = plugin_file.resolve()
            if resolved_file in cls._loaded_files:
                continue

            folder_name = (
                plugin_file.parent.name
                if plugin_file.name in ("main.py", "__init__.py")
                else plugin_file.stem
            )
            sanitized_name = re.sub(r"[^a-zA-Z0-9_]", "_", folder_name)
            path_hash = hashlib.sha256(str(resolved_file).encode("utf-8")).hexdigest()[
                :12
            ]
            module_name = f"tg_signer_plugin_{sanitized_name}_{path_hash}"

            # 若为目录型插件，将其所在目录加入 sys.path 以支持目录内的子模块/相对引用
            inserted_syspath = False
            parent_str = str(resolved_file.parent)
            if plugin_file.name in ("main.py", "__init__.py"):
                if parent_str not in sys.path:
                    sys.path.insert(0, parent_str)
                    inserted_syspath = True

            try:
                content_text = plugin_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content_text, filename=str(plugin_file))

                # 静态依赖检查：检测是否存在缺失的顶层模块依赖（无需动态导入）
                for stmt in tree.body:
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            top_pkg = alias.name.split(".")[0]
                            if importlib.util.find_spec(top_pkg) is None:
                                if (
                                    not (
                                        resolved_file.parent / f"{top_pkg}.py"
                                    ).is_file()
                                    and not (resolved_file.parent / top_pkg).is_dir()
                                ):
                                    raise ModuleNotFoundError(
                                        f"No module named '{top_pkg}'", name=top_pkg
                                    )
                    elif isinstance(stmt, ast.ImportFrom):
                        if getattr(stmt, "level", 0) == 0 and stmt.module:
                            top_pkg = stmt.module.split(".")[0]
                            if importlib.util.find_spec(top_pkg) is None:
                                if (
                                    not (
                                        resolved_file.parent / f"{top_pkg}.py"
                                    ).is_file()
                                    and not (resolved_file.parent / top_pkg).is_dir()
                                ):
                                    raise ModuleNotFoundError(
                                        f"No module named '{top_pkg}'", name=top_pkg
                                    )

                # 检查目录型插件是否附带 plugin.json 描述文件
                pjson_data: Dict[str, Any] = {}
                if plugin_file.name in ("main.py", "__init__.py"):
                    pjson_file = resolved_file.parent / "plugin.json"
                    if pjson_file.is_file():
                        try:
                            pjson_data = json.loads(
                                pjson_file.read_text(encoding="utf-8")
                            )
                        except Exception:
                            pass

                def _safe_eval(node: ast.AST) -> Any:
                    try:
                        return ast.literal_eval(node)
                    except Exception:
                        return None

                # 模块级全局变量元数据提取（支持 Assign 与 AnnAssign）
                mod_globals: Dict[str, Any] = {}
                for stmt in tree.body:
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                val = _safe_eval(stmt.value)
                                if val is not None:
                                    mod_globals[target.id.upper()] = val
                    elif isinstance(stmt, ast.AnnAssign):
                        if isinstance(stmt.target, ast.Name) and stmt.value is not None:
                            val = _safe_eval(stmt.value)
                            if val is not None:
                                mod_globals[stmt.target.id.upper()] = val

                mod_version = mod_globals.get("VERSION") or mod_globals.get(
                    "__VERSION__"
                )
                mod_updated_at = mod_globals.get("UPDATED_AT") or mod_globals.get(
                    "__UPDATED_AT__"
                )
                mod_author = mod_globals.get("AUTHOR") or mod_globals.get("__AUTHOR__")
                mod_category = mod_globals.get("CATEGORY") or mod_globals.get(
                    "__CATEGORY__"
                )
                mod_tags = mod_globals.get("TAGS") or mod_globals.get("__TAGS__")
                mod_icon = mod_globals.get("ICON") or mod_globals.get("__ICON__")
                mod_homepage = mod_globals.get("HOMEPAGE") or mod_globals.get(
                    "__HOMEPAGE__"
                )
                mod_params_schema = mod_globals.get("PARAMS_SCHEMA")

                # 扫描所有带 @PluginRegistry.register 装饰器的函数
                found_registrations = []
                module_doc = ast.get_docstring(tree) or ""

                for stmt in tree.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for deco in stmt.decorator_list:
                            if isinstance(deco, ast.Call):
                                is_reg = False
                                if (
                                    isinstance(deco.func, ast.Attribute)
                                    and deco.func.attr == "register"
                                ):
                                    is_reg = True
                                elif (
                                    isinstance(deco.func, ast.Name)
                                    and "register" in deco.func.id
                                ):
                                    is_reg = True

                                if is_reg:
                                    reg_info: Dict[str, Any] = {
                                        "name": stmt.name,
                                        "fn_name": stmt.name,
                                        "is_async": isinstance(
                                            stmt, ast.AsyncFunctionDef
                                        ),
                                        "doc": ast.get_docstring(stmt) or module_doc,
                                    }
                                    if deco.args:
                                        first_arg = _safe_eval(deco.args[0])
                                        if first_arg and isinstance(first_arg, str):
                                            reg_info["name"] = first_arg
                                    for kw in deco.keywords:
                                        if not kw.arg:
                                            continue
                                        kw_val = _safe_eval(kw.value)
                                        if kw_val is not None:
                                            reg_info[kw.arg.lower()] = kw_val
                                    found_registrations.append(reg_info)

                if not found_registrations:
                    found_registrations.append(
                        {
                            "name": folder_name,
                            "doc": module_doc,
                        }
                    )

                file_mtime_str = ""
                if os.path.isfile(str(resolved_file)):
                    try:
                        file_mtime_str = datetime.fromtimestamp(
                            os.path.getmtime(str(resolved_file))
                        ).strftime("%Y-%m-%d")
                    except Exception:
                        file_mtime_str = datetime.now().strftime("%Y-%m-%d")
                else:
                    file_mtime_str = datetime.now().strftime("%Y-%m-%d")

                for reg in found_registrations:
                    meta_name = str(reg.get("name") or folder_name)

                    # 版本提取
                    final_version = "1.0.0"
                    if reg.get("version"):
                        final_version = str(reg["version"]).strip()
                    elif mod_version and isinstance(mod_version, str):
                        final_version = mod_version.strip()
                    elif pjson_data.get("version"):
                        final_version = str(pjson_data["version"]).strip()

                    # 更新时间
                    final_updated_at = ""
                    if reg.get("updated_at"):
                        final_updated_at = str(reg["updated_at"]).strip()
                    elif mod_updated_at and isinstance(mod_updated_at, str):
                        final_updated_at = mod_updated_at.strip()
                    elif pjson_data.get("updated_at"):
                        final_updated_at = str(pjson_data["updated_at"]).strip()
                    else:
                        final_updated_at = file_mtime_str

                    # 作者
                    final_author = ""
                    if reg.get("author"):
                        final_author = str(reg["author"]).strip()
                    elif mod_author and isinstance(mod_author, str):
                        final_author = mod_author.strip()
                    elif pjson_data.get("author"):
                        final_author = str(pjson_data["author"]).strip()

                    # 模式
                    final_mode = (
                        reg.get("mode") or mod_globals.get("MODE") or "reactive"
                    )
                    if final_mode not in ("reactive", "active"):
                        final_mode = "reactive"

                    # 分类
                    final_category = (
                        reg.get("category")
                        or mod_category
                        or pjson_data.get("category")
                        or None
                    )

                    # 标签
                    raw_tags = reg.get("tags") or mod_tags or pjson_data.get("tags")
                    final_tags: List[str] = []
                    if isinstance(raw_tags, (list, tuple)):
                        final_tags = [
                            str(t).strip() for t in raw_tags if str(t).strip()
                        ]
                    elif isinstance(raw_tags, str) and raw_tags.strip():
                        final_tags = [
                            t.strip() for t in raw_tags.split(",") if t.strip()
                        ]

                    # 图标与主页
                    final_icon = (
                        reg.get("icon") or mod_icon or pjson_data.get("icon") or None
                    )
                    final_homepage = (
                        reg.get("homepage")
                        or mod_homepage
                        or pjson_data.get("homepage")
                        or None
                    )

                    # 描述
                    final_desc = str(reg.get("description") or "").strip()
                    if not final_desc or final_desc == f"自定义插件 {meta_name}":
                        if pjson_data.get("description"):
                            final_desc = str(pjson_data["description"]).strip()
                        elif reg.get("doc"):
                            final_desc = str(reg["doc"]).strip().split("\n")[0].strip()

                    # 权限
                    raw_perms = (
                        reg.get("permissions")
                        or mod_globals.get("PERMISSIONS")
                        or pjson_data.get("permissions")
                    )
                    final_permissions: List[str] = []
                    if isinstance(raw_perms, (list, tuple)):
                        final_permissions = [str(x) for x in raw_perms]

                    # 参数定义 schema
                    final_schema = (
                        reg.get("params_schema")
                        or mod_params_schema
                        or pjson_data.get("params_schema")
                    )
                    if not isinstance(final_schema, list):
                        final_schema = []

                    fn_real_name = reg.get("fn_name") or meta_name
                    is_async_fn = reg.get("is_async", True)

                    def _make_lazy_handler(t_file, t_mod, m_name, f_name, is_async):
                        real_fn = None

                        def _load_and_get_real_fn() -> Any:
                            nonlocal real_fn
                            if real_fn is not None:
                                return real_fn
                            spec_kw = {}
                            if t_file.name in ("main.py", "__init__.py"):
                                spec_kw["submodule_search_locations"] = [
                                    str(t_file.parent)
                                ]
                            spec = importlib.util.spec_from_file_location(
                                t_mod, t_file, **spec_kw
                            )
                            if spec is None or spec.loader is None:
                                return None
                            mod = importlib.util.module_from_spec(spec)
                            sys.modules[t_mod] = mod
                            ins = False
                            p_str = str(t_file.parent)
                            if (
                                t_file.name in ("main.py", "__init__.py")
                                and p_str not in sys.path
                            ):
                                sys.path.insert(0, p_str)
                                ins = True
                            try:
                                spec.loader.exec_module(mod)
                            finally:
                                if ins and p_str in sys.path:
                                    try:
                                        sys.path.remove(p_str)
                                    except ValueError:
                                        pass
                            m = cls._plugins.get(m_name)
                            if (
                                m
                                and m.handler
                                and not getattr(m.handler, "_is_placeholder", False)
                            ):
                                real_fn = m.handler
                            else:
                                real_fn = getattr(mod, f_name, None)
                            return real_fn

                        if is_async:

                            async def _lazy_handler(*args: Any, **kwargs: Any) -> Any:
                                real_f = _load_and_get_real_fn()
                                if real_f is None:
                                    return None
                                res = real_f(*args, **kwargs)
                                if inspect.iscoroutine(res):
                                    return await res
                                return res

                            _lazy_handler._is_placeholder = True
                            return _lazy_handler
                        else:

                            def _lazy_handler(*args: Any, **kwargs: Any) -> Any:
                                real_f = _load_and_get_real_fn()
                                if real_f is None:
                                    return None
                                return real_f(*args, **kwargs)

                            _lazy_handler._is_placeholder = True
                            return _lazy_handler

                    active_handler = _make_lazy_handler(
                        resolved_file, module_name, meta_name, fn_real_name, is_async_fn
                    )

                    meta = PluginMeta(
                        name=meta_name,
                        handler=active_handler,
                        mode=final_mode,
                        description=final_desc,
                        version=final_version,
                        updated_at=final_updated_at,
                        author=final_author,
                        source_path=str(resolved_file),
                        params_schema=final_schema,
                        enabled=cls.is_enabled(meta_name),
                        builtin=is_builtin_plugin_path(resolved_file),
                        permissions=final_permissions,
                        doc=reg.get("doc") or None,
                        category=final_category,
                        tags=final_tags,
                        icon=final_icon,
                        homepage=final_homepage,
                        isolation_mode="subprocess",
                    )
                    cls._plugins[meta_name] = meta

                cls._loaded_files.add(resolved_file)
                cls._load_errors.pop(str(resolved_file), None)
                _logger.info(
                    "已成功静态加载插件: %s (来自 %s)", folder_name, plugin_file
                )
            except ModuleNotFoundError as exc:
                missing = getattr(exc, "name", None) or str(exc)
                _logger.warning(
                    "加载插件 %s 失败：缺少依赖模块 '%s'，可在环境中执行 pip install %s 进行安装",
                    plugin_file,
                    missing,
                    missing,
                )
                cls._load_errors[str(resolved_file)] = PluginLoadError(
                    file_path=str(resolved_file),
                    plugin_name=folder_name,
                    error_type="missing_dependency",
                    error_message=f"缺少依赖模块 '{missing}'",
                    missing_module=missing,
                    suggested_command=f"pip install {missing}",
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except SyntaxError as exc:
                _logger.error("加载插件 %s 语法错误: %s", plugin_file, exc)
                cls._load_errors[str(resolved_file)] = PluginLoadError(
                    file_path=str(resolved_file),
                    plugin_name=folder_name,
                    error_type="syntax_error",
                    error_message=f"语法错误 (line {exc.lineno}): {exc.msg}",
                    missing_module=None,
                    suggested_command=None,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            except Exception as exc:
                _logger.error("加载插件 %s 失败: %s", plugin_file, exc, exc_info=True)
                cls._load_errors[str(resolved_file)] = PluginLoadError(
                    file_path=str(resolved_file),
                    plugin_name=folder_name,
                    error_type="load_error",
                    error_message=str(exc),
                    missing_module=None,
                    suggested_command=None,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            finally:
                if inserted_syspath and parent_str in sys.path:
                    try:
                        sys.path.remove(parent_str)
                    except ValueError:
                        pass

        loaded_count = len(cls._plugins) - len(initial_keys)
        return max(0, loaded_count)

    @classmethod
    def get_builtin_directories(cls) -> list[Path]:
        """获取官方内置插件所在的候选目录列表。"""
        candidates: list[Path] = []
        env_builtin = os.getenv("BUILTIN_PLUGINS_DIR")
        if env_builtin:
            candidates.append(Path(env_builtin).expanduser())

        # 容器标准内置目录
        app_plugins = Path("/app/plugins")
        if app_plugins.is_dir():
            candidates.append(app_plugins)

        # 当前工作目录下的 plugins 目录（本地运行根目录或 Docker WORKDIR /app）
        cwd_plugins = Path.cwd() / "plugins"
        if cwd_plugins.is_dir():
            candidates.append(cwd_plugins)

        # 保持顺序并以解析路径去重
        deduped: list[Path] = []
        seen_resolved: set[Path] = set()
        for c in candidates:
            try:
                res = c.resolve()
                if res.is_dir() and res not in seen_resolved:
                    seen_resolved.add(res)
                    deduped.append(c)
            except Exception:
                pass
        return deduped

    @classmethod
    def get_search_directories(cls) -> list[Path]:
        dirs: list[Path] = []
        for b in cls.get_builtin_directories():
            dirs.append(b)

        env_dir = os.getenv("PLUGINS_DIR")
        if env_dir:
            dirs.append(Path(env_dir).expanduser())

        data_base = os.getenv("APP_DATA_DIR")
        if data_base:
            dirs.append(Path(data_base).expanduser() / "plugins")
        elif Path("/data/plugins").is_dir():
            dirs.append(Path("/data/plugins"))
        else:
            dirs.append(Path.cwd() / "data" / "plugins")

        # 保持顺序并以解析路径去重
        deduped: list[Path] = []
        seen_resolved: set[Path] = set()
        for d in dirs:
            try:
                res = d.resolve()
                if res not in seen_resolved:
                    seen_resolved.add(res)
                    deduped.append(d)
            except Exception:
                if d not in deduped:
                    deduped.append(d)
        return deduped

    @classmethod
    def load_all_configured_plugins(cls) -> int:
        for d in cls.get_search_directories():
            if d.is_dir():
                cls.load_plugins_from_dir(d)
        return len(cls._plugins)

    @classmethod
    def reload_all_plugins(cls) -> int:
        cls.clear()
        return cls.load_all_configured_plugins()


class _SecurityVisitor(ast.NodeVisitor):
    _STAR_DANGEROUS_BARE_NAMES = frozenset(
        {
            "system",
            "popen",
            "kill",
            "killpg",
            "fork",
            "unlink",
            "remove",
            "rmdir",
            "execv",
            "execve",
            "execvp",
            "spawnl",
            "spawnv",
            "posix_spawn",
            "run",
            "Popen",
            "call",
            "check_output",
            "check_call",
            "getoutput",
            "getstatusoutput",
            "CDLL",
            "LoadLibrary",
            "eval",
            "exec",
            "compile",
            "__import__",
            "create_subprocess_shell",
            "create_subprocess_exec",
        }
    )

    def __init__(self) -> None:
        self.warnings: List[Dict[str, Any]] = []
        self._aliases: Dict[str, str] = {}
        self._star_import_roots: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            as_name = alias.asname or alias.name
            self._aliases[as_name] = alias.name
            root_mod = alias.name.split(".")[0]
            if root_mod in ("ctypes", "winreg", "msvcrt"):
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "high",
                        "rule": f"disallowed-import:{root_mod}",
                        "message": f"检测到导入底层系统原生操作库 '{root_mod}'",
                    }
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        root_mod = mod.split(".")[0] if mod else ""
        if root_mod in ("ctypes", "winreg", "msvcrt"):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"disallowed-import:{root_mod}",
                    "message": f"检测到导入底层系统原生操作库 '{root_mod}'",
                }
            )
        for alias in node.names:
            if alias.name == "*":
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "high",
                        "rule": f"star-import:{root_mod or '<relative>'}",
                        "message": f"检测到从系统或模块通配符导入 'from {mod or '<相对模块>'} import *'，静态审计无法追踪其命名空间",
                    }
                )
                if root_mod:
                    self._star_import_roots.add(root_mod)
                continue
            as_name = alias.asname or alias.name
            target = f"{mod}.{alias.name}" if mod else alias.name
            self._aliases[as_name] = target
            if target in (
                "os.system",
                "os.popen",
                "os.kill",
                "os.killpg",
                "os.posix_spawn",
                "subprocess.run",
                "subprocess.Popen",
                "subprocess.call",
                "subprocess.check_output",
                "subprocess.check_call",
                "subprocess.getoutput",
                "subprocess.getstatusoutput",
                "asyncio.create_subprocess_shell",
                "asyncio.create_subprocess_exec",
                "eval",
                "exec",
                "compile",
            ):
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "high",
                        "rule": f"dangerous-system-call:{target}",
                        "message": f"检测到从模块导入高危执行函数 '{target}'",
                    }
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # 高危函数名集合：与上方导入判定共用同一份名单
        dangerous_full_names = (
            "os.system",
            "os.popen",
            "subprocess.run",
            "subprocess.Popen",
            "subprocess.call",
            "subprocess.getoutput",
            "subprocess.getstatusoutput",
            "eval",
            "exec",
            "compile",
            "__import__",
            "asyncio.create_subprocess_shell",
            "asyncio.create_subprocess_exec",
        )

        def _resolve(value: ast.expr) -> Optional[str]:
            """把右值表达式解析为「已知全名」（Name 走别名表，Attribute 拼前缀）。"""
            if isinstance(value, ast.Name):
                return self._aliases.get(value.id, value.id)
            if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                return (
                    f"{self._aliases.get(value.value.id, value.value.id)}.{value.attr}"
                )
            return None

        # 逐目标处理：覆盖 a = x、a = b = x、(a, b) = (x, y) 三种形态
        pairs: List[Tuple[str, Optional[str]]] = []
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], (ast.Tuple, ast.List))
            and isinstance(node.value, (ast.Tuple, ast.List))
            and len(node.targets[0].elts) == len(node.value.elts)
        ):
            for target_elt, value_elt in zip(
                node.targets[0].elts, node.value.elts, strict=False
            ):
                for name in self._assign_target_names(target_elt):
                    pairs.append((name, _resolve(value_elt)))
        else:
            for target in node.targets:
                for name in self._assign_target_names(target):
                    pairs.append((name, _resolve(node.value)))

        for target_name, resolved in pairs:
            if resolved is None:
                continue
            if resolved in dangerous_full_names:
                self._aliases[target_name] = resolved
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "high",
                        "rule": f"dangerous-alias:{resolved}",
                        "message": f"检测到将高危函数 '{resolved}' 赋值给别名 '{target_name}'",
                    }
                )
            elif target_name not in self._aliases:
                # 传播模块/普通别名（如 sp = subprocess），让后续 sp.run(...) 能被还原
                self._aliases[target_name] = resolved
        self.generic_visit(node)

    @staticmethod
    def _assign_target_names(target: ast.expr) -> List[str]:
        """取出赋值目标的全部 Name 标识（支持 a = b = x 与 (a, b) = ...）。"""
        names: List[str] = []
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                names.extend(_SecurityVisitor._assign_target_names(elt))
        return names

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in (
            "__subclasses__",
            "__globals__",
            "__builtins__",
            "__code__",
            "__bases__",
            "__base__",
            "__mro__",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"sandbox-escape:{node.attr}",
                    "message": f"检测到使用沙箱逃逸反射属性 '{node.attr}'",
                }
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_name = ""
        if isinstance(node.func, ast.Name):
            raw_id = node.func.id
            func_name = self._aliases.get(raw_id, raw_id)
            if (
                raw_id not in self._aliases
                and raw_id in self._STAR_DANGEROUS_BARE_NAMES
                and self._star_import_roots
            ):
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "high",
                        "rule": f"dangerous-bare-call:{raw_id}",
                        "message": f"插件存在星号导入，无法判定裸名调用 '{raw_id}' 的真实来源，请改为显式导入",
                    }
                )
            elif raw_id in ("getattr", "vars"):
                target_arg = (
                    node.args[-1]
                    if raw_id == "getattr" and len(node.args) >= 2
                    else (node.args[0] if node.args else None)
                )
                if isinstance(target_arg, ast.Constant) and isinstance(
                    target_arg.value, str
                ):
                    val = target_arg.value
                    if val in self._STAR_DANGEROUS_BARE_NAMES or val in (
                        "system",
                        "popen",
                        "run",
                        "Popen",
                        "exec",
                        "eval",
                        "__builtins__",
                        "__subclasses__",
                        "__globals__",
                        "__code__",
                        "__bases__",
                        "__base__",
                        "__mro__",
                    ):
                        self.warnings.append(
                            {
                                "line": node.lineno,
                                "column": node.col_offset,
                                "severity": "high",
                                "rule": f"reflection-call:{raw_id}:{val}",
                                "message": f"检测到通过 {raw_id}() 动态反射获取高危函数/属性 '{val}'",
                            }
                        )
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                base_id = self._aliases.get(node.func.value.id, node.func.value.id)
                func_name = f"{base_id}.{node.func.attr}"
            elif isinstance(node.func.value, ast.Attribute) and isinstance(
                node.func.value.value, ast.Name
            ):
                grand_base = self._aliases.get(
                    node.func.value.value.id, node.func.value.value.id
                )
                func_name = f"{grand_base}.{node.func.value.attr}.{node.func.attr}"

        if func_name in (
            "eval",
            "exec",
            "compile",
            "__import__",
            "builtins.eval",
            "builtins.exec",
            "builtins.compile",
            "builtins.__import__",
            "importlib.import_module",
            "pickle.loads",
            "pickle.load",
            "_pickle.loads",
            "_pickle.load",
            "marshal.loads",
            "marshal.load",
            "shelve.open",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"disallowed-call:{func_name}",
                    "message": f"检测到使用动态执行、隐式导入或危险反序列化函数 '{func_name}'",
                }
            )
        elif func_name in (
            "os.system",
            "os.popen",
            "os.kill",
            "os.killpg",
            "shutil.rmtree",
            "shutil.move",
            "os.unlink",
            "os.remove",
            "os.rmdir",
            "os.removedirs",
            "os.renames",
            "pty.spawn",
            "os.execv",
            "os.execve",
            "os.execvp",
            "os.spawnl",
            "os.spawnlp",
            "os.spawnv",
            "os.spawnvp",
            "os.fork",
            "os.posix_spawn",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"dangerous-system-call:{func_name}",
                    "message": f"检测到调用高危系统或破坏性文件操作 '{func_name}'",
                }
            )
        elif func_name.startswith("ctypes.") or func_name in (
            "ctypes.CDLL",
            "ctypes.windll",
            "ctypes.pythonapi",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"ctypes-usage:{func_name}",
                    "message": f"检测到使用底层动态链接库调用 '{func_name}'",
                }
            )
        elif func_name in (
            "subprocess.Popen",
            "subprocess.run",
            "subprocess.call",
            "subprocess.check_output",
            "subprocess.check_call",
            "subprocess.getoutput",
            "subprocess.getstatusoutput",
            "asyncio.create_subprocess_shell",
            "asyncio.create_subprocess_exec",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "high",
                    "rule": f"process-execution:{func_name}",
                    "message": f"检测到调用外部进程执行命令 '{func_name}'",
                }
            )
        elif func_name in (
            "ssl._create_unverified_context",
            "ssl._create_default_https_context",
        ):
            self.warnings.append(
                {
                    "line": node.lineno,
                    "column": node.col_offset,
                    "severity": "medium",
                    "rule": f"insecure-ssl:{func_name}",
                    "message": f"检测到跳过全局 SSL 证书校验配置 '{func_name}'",
                }
            )
        elif func_name == "open":
            if (
                len(node.args) >= 1
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                target_path = node.args[0].value
                mode = "r"
                if (
                    len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if (
                        kw.arg == "mode"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        mode = kw.value.value
                if any(m in mode for m in ("w", "a", "x", "+")):
                    if (
                        target_path.startswith(
                            ("/etc", "/proc", "/sys", "/root", "/dev")
                        )
                        or "../" in target_path
                        or "..\\" in target_path
                    ):
                        self.warnings.append(
                            {
                                "line": node.lineno,
                                "column": node.col_offset,
                                "severity": "high",
                                "rule": "dangerous-path-write",
                                "message": f"检测到尝试向系统保护路径或跨目录写文件: '{target_path}'",
                            }
                        )

        for kw in node.keywords:
            if (
                kw.arg == "verify"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
            ):
                self.warnings.append(
                    {
                        "line": node.lineno,
                        "column": node.col_offset,
                        "severity": "medium",
                        "rule": "insecure-ssl:verify-false",
                        "message": "检测到 HTTP 请求参数配置了 verify=False 忽略证书校验",
                    }
                )

        self.generic_visit(node)


def validate_plugin_params(
    schema: Optional[List[Dict[str, Any]]],
    params: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    """校验插件运行时传入的参数是否符合其 PARAMS_SCHEMA 规范。

    返回:
        (validated_params, warnings):
        - validated_params: 填补了默认值并完成基本类型转化的有效参数字典
        - warnings: 格式不合规或缺失必填项的警告信息列表
    """
    eff = dict(params or {})
    warnings: List[str] = []
    if not schema:
        return eff, warnings

    for item in schema:
        if not isinstance(item, dict):
            continue
        key = item.get("name")
        if not key:
            continue
        label = item.get("label") or key
        required = bool(item.get("required", False))
        field_type = str(item.get("type", "string")).lower()
        default_val = item.get("default")

        val = eff.get(key)

        # 检查是否缺失
        is_empty = val is None or (isinstance(val, str) and val.strip() == "")
        if is_empty:
            if required:
                warnings.append(f"必填参数 '{label}' ({key}) 未配置或为空")
            elif default_val is not None:
                eff[key] = default_val
            continue

        # 类型校验与轻量转换
        if field_type in ("int", "integer"):
            try:
                eff[key] = int(val)
            except (ValueError, TypeError):
                warnings.append(f"参数 '{label}' ({key}) 期望整数，实际为: {val!r}")
        elif field_type in ("float", "number"):
            try:
                eff[key] = float(val)
            except (ValueError, TypeError):
                warnings.append(f"参数 '{label}' ({key}) 期望数值，实际为: {val!r}")
        elif field_type in ("bool", "boolean"):
            if isinstance(val, bool):
                eff[key] = val
            elif isinstance(val, str):
                eff[key] = val.strip().lower() in ("true", "1", "yes", "on")
            else:
                eff[key] = bool(val)
        elif field_type in ("select", "enum"):
            options = item.get("options")
            if isinstance(options, list) and options:
                valid_vals = []
                for opt in options:
                    if isinstance(opt, dict) and "value" in opt:
                        valid_vals.append(opt["value"])
                    else:
                        valid_vals.append(opt)
                if val not in valid_vals and str(val) not in [
                    str(v) for v in valid_vals
                ]:
                    warnings.append(
                        f"参数 '{label}' ({key}) 的值 {val!r} 不在允许的预设选项列表中"
                    )

    return eff, warnings


def detect_plugin_capabilities(source: str) -> List[str]:
    """通过静态 AST 扫描识别插件源码所使用的核心能力/权限集。"""
    capabilities = set()
    try:
        tree = ast.parse(source)
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod in (
                    "urllib",
                    "requests",
                    "httpx",
                    "aiohttp",
                    "socket",
                    "websocket",
                    "websockets",
                ):
                    capabilities.add("network")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_mod = node.module.split(".")[0]
                if root_mod in (
                    "urllib",
                    "requests",
                    "httpx",
                    "aiohttp",
                    "socket",
                    "websocket",
                    "websockets",
                ):
                    capabilities.add("network")

        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr in ("storage", "global_storage"):
                capabilities.add("storage")
            elif attr in ("send_message", "reply", "edit_message", "delete_message"):
                capabilities.add("message_write")
            elif attr == "react":
                capabilities.add("reactions")
            elif attr == "click":
                capabilities.add("buttons")

    order = ["network", "storage", "message_write", "reactions", "buttons"]
    return [c for c in order if c in capabilities]


_SECRET_PATTERNS = [
    (
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
        "hardcoded-telegram-token",
        "检测到代码中疑似硬编码了 Telegram Bot Token，建议使用环境变量或插件配置参数传入",
    ),
    (
        re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
        "hardcoded-private-key",
        "检测到代码中包含明文私钥凭据",
    ),
]


def extract_plugin_declared_permissions(source: str) -> List[str]:
    """从源码中提取声明的 PERMISSIONS 列表。"""
    perms: set = set()
    try:
        tree = ast.parse(source)
    except Exception:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id == "PERMISSIONS"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            perms.add(elt.value)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "permissions" and isinstance(
                    kw.value, (ast.List, ast.Tuple)
                ):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            perms.add(elt.value)

    return sorted(perms)


def audit_plugin_source(source: str) -> List[Dict[str, Any]]:
    """启发式静态审计插件源码中的高危调用与潜在安全隐患。"""
    warnings: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(source, filename="<plugin_security_audit>")
        visitor = _SecurityVisitor()
        visitor.visit(tree)
        warnings.extend(visitor.warnings)
    except SyntaxError as e:
        return [
            {
                "line": e.lineno or 1,
                "column": e.offset or 0,
                "severity": "high",
                "rule": "syntax-error",
                "message": f"代码存在语法错误，无法完成安全审计: {e.msg}",
            }
        ]
    except Exception as e:
        return [
            {
                "line": 1,
                "column": 0,
                "severity": "medium",
                "rule": "audit-error",
                "message": f"审计解析异常: {e}",
            }
        ]

    # 源码硬编码敏感秘钥扫描
    lines = source.splitlines()
    for line_no, line_content in enumerate(lines, start=1):
        for pattern, rule, msg in _SECRET_PATTERNS:
            if pattern.search(line_content):
                warnings.append(
                    {
                        "line": line_no,
                        "column": 0,
                        "severity": "medium",
                        "rule": rule,
                        "message": msg,
                    }
                )

    # 权限越界与未声明高级权限检查
    detected_caps = detect_plugin_capabilities(source)
    declared_perms = extract_plugin_declared_permissions(source)
    for cap in detected_caps:
        if cap in ("network", "storage") and cap not in declared_perms:
            warnings.append(
                {
                    "line": 1,
                    "column": 0,
                    "severity": "medium",
                    "rule": f"undeclared-capability:{cap}",
                    "message": f"源码使用了核心能力 '{cap}'，但未在 PERMISSIONS 声明中配置",
                }
            )

    warnings.sort(key=lambda w: (w.get("line") or 1, w.get("column") or 0))
    return warnings


def compute_plugin_security_report(source: str) -> Dict[str, Any]:
    """计算插件全方位安全体检报告，包含评分（0-100）、风险评级与阻断研判。

    阻断研判（has_critical）改为**基于告警严重度**：high/critical 一律阻断，
    不再按规则名做子串匹配——规则名匹配会让新增/改名的规则静默绕过门禁。
    另有两类审计失败形态必须失败关闭：star-import（星号导入使命名空间不可追踪）
    与 syntax-error / audit-error（审计本身没跑成）。
    """
    warnings = audit_plugin_source(source)
    detected_caps = detect_plugin_capabilities(source)
    declared_perms = extract_plugin_declared_permissions(source)
    # 仅对需要显式治理的关键权限（网络、持久存储）进行越界检查，避免常规响应回复行为被误报为越界
    auditable_permissions = ("network", "storage")
    undeclared = [
        c
        for c in detected_caps
        if c in auditable_permissions and c not in declared_perms
    ]

    deductions = 0
    has_high = False
    has_critical = False

    for w in warnings:
        sev = w.get("severity", "medium")
        rule = str(w.get("rule", ""))
        if sev in ("critical", "high"):
            deductions += 30
            has_high = True
            has_critical = True
        else:
            deductions += 10
        # 审计失败形态：星号导入 / 语法错误 / 审计异常，一律失败关闭
        if rule.split(":", 1)[0] in (
            "star-import",
            "syntax-error",
            "audit-error",
        ):
            has_critical = True

    score = max(0, 100 - deductions)
    if has_critical or score < 50:
        risk_level = "critical"
    elif has_high or score < 80:
        risk_level = "warning"
    elif deductions > 0:
        risk_level = "notice"
    else:
        risk_level = "safe"

    return {
        "passed": len(warnings) == 0,
        "score": score,
        "risk_level": risk_level,
        "warnings": warnings,
        "detected_capabilities": detected_caps,
        "declared_permissions": declared_perms,
        "undeclared_capabilities": undeclared,
        "can_save_safely": not has_critical,
    }
