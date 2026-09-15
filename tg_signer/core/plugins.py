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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Union

_logger = logging.getLogger("tg_signer.plugins")


class PluginTimeoutError(RuntimeError):
    """插件执行超时；该错误不可通过步骤级重试安全恢复。"""


class PluginStorageBackend:
    """基于 SQLite 的线程与多进程安全轻量级 KV 存储后端。"""

    @staticmethod
    def _escape_like(text: str) -> str:
        return text.replace('/', '//').replace('%', '/%').replace('_', '/_')

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
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
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
            with self._get_conn() as conn:
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

    def set(self, namespace: str, key: str, value: Any, ttl: Optional[float] = None) -> None:
        now = time.time()
        expires_at = (now + ttl) if (ttl is not None and ttl > 0) else None
        val_str = json.dumps(value, ensure_ascii=False)
        try:
            with self._get_conn() as conn:
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
            with self._get_conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT value, expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
                current = default
                if row and (row[1] is None or row[1] >= now):
                    try:
                        parsed = json.loads(row[0])
                        if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
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
            with self._get_conn() as conn:
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
            with self._get_conn() as conn:
                if namespace:
                    cur = conn.execute("DELETE FROM plugin_kv WHERE namespace = ?", (namespace,))
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
            with self._get_conn() as conn:
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
            with self._get_conn() as conn:
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

    def get_all(self, namespace: str, prefix: str = "") -> Dict[str, Any]:
        """批量读取指定命名空间下所有未过期的键值对（支持前缀过滤），自动淘汰已过期记录。"""
        now = time.time()
        try:
            with self._get_conn() as conn:
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
            with self._get_conn() as conn:
                if plugin_name:
                    escaped_name = self._escape_like(plugin_name)
                    cur = conn.execute(
                        """
                        SELECT DISTINCT namespace FROM plugin_kv
                        WHERE namespace = ?
                           OR namespace LIKE ? ESCAPE '/'
                           OR namespace LIKE ? ESCAPE '/'
                        """,
                        (plugin_name, f"%:{escaped_name}", f"__test__:%:{escaped_name}"),
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
            with self._get_conn() as conn:
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
                    records.append({
                        "key": k,
                        "value": parsed_val,
                        "expires_at": exp,
                        "ttl_remaining": round(exp - now, 1) if exp is not None else None,
                    })
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
            return await loop.run_in_executor(None, self._backend.get, self.namespace, key, default)
        except RuntimeError:
            return self._backend.get(self.namespace, key, default)

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._backend.set, self.namespace, key, value, ttl)
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
            return await loop.run_in_executor(None, self._backend.delete, self.namespace, key)
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
            return await loop.run_in_executor(None, self._backend.keys, self.namespace, prefix)
        except RuntimeError:
            return self._backend.keys(self.namespace, prefix)

    async def get_all(self, prefix: str = "") -> Dict[str, Any]:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._backend.get_all, self.namespace, prefix)
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

    @property
    def storage(self) -> PluginStorageClient:
        if self._storage is None:
            ns = f"{self.chat_id}:{self.plugin_name}" if self.plugin_name else str(self.chat_id)
            self._storage = PluginStorageClient(namespace=ns)
        return self._storage

    @storage.setter
    def storage(self, value: PluginStorageClient) -> None:
        self._storage = value

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

    async def react(self, emoji: str, message_id: Optional[int] = None, **kwargs) -> Any:
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
            return await self.app.send_reaction(self.chat_id, message_id=msg_id, emoji=emoji, **kwargs)
        raise RuntimeError("Telegram Client 不支持 send_reaction 方法")


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
        return round(self.total_duration_ms / self.run_count, 1) if self.run_count > 0 else 0.0

    @property
    def success_rate(self) -> float:
        # 从未执行时无成功率可言，返回 0.0 而非 100.0，避免误导
        return round((self.success_count / self.run_count) * 100, 1) if self.run_count > 0 else 0.0

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
    def _is_same_registration(a: Callable[[PluginContext], Any], b: Callable[[PluginContext], Any]) -> bool:
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
    ) -> Callable:
        def decorator(fn: Callable[[PluginContext], Any]) -> Callable[[PluginContext], Any]:
            existing = cls._plugins.get(name)
            if existing is not None and existing.handler is not fn:
                # 仅放行"同一源文件同一行号"的重复注册（模块被再次执行的重载场景）；
                # 跨文件同名注册一律拒绝，防止后加载者静默覆盖先加载者
                if not cls._is_same_registration(existing.handler, fn):
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
            path_hash = hashlib.sha256(str(resolved_file).encode("utf-8")).hexdigest()[:12]
            module_name = f"tg_signer_plugin_{sanitized_name}_{path_hash}"

            # 若为目录型插件，将其所在目录加入 sys.path 以支持目录内的子模块/相对引用
            if plugin_file.name in ("main.py", "__init__.py"):
                parent_str = str(resolved_file.parent)
                if parent_str not in sys.path:
                    sys.path.insert(0, parent_str)

            try:
                spec_kwargs = {}
                if plugin_file.name in ("main.py", "__init__.py"):
                    # 目录型插件按包加载，保证 `from .helper import ...` 等相对导入可用。
                    spec_kwargs["submodule_search_locations"] = [str(resolved_file.parent)]
                spec = importlib.util.spec_from_file_location(
                    module_name, plugin_file, **spec_kwargs
                )
                if spec is None or spec.loader is None:
                    _logger.warning("无法创建插件规范: %s", plugin_file)
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod
                pre_keys = set(cls._plugins.keys())
                spec.loader.exec_module(mod)
                cls._loaded_files.add(resolved_file)
                cls._load_errors.pop(str(resolved_file), None)
                for meta in cls._plugins.values():
                    if meta.source_path and is_builtin_plugin_path(meta.source_path):
                        meta.builtin = True

                new_registered = [
                    meta
                    for name, meta in cls._plugins.items()
                    if name not in pre_keys and (meta.source_path == str(resolved_file) or not meta.source_path)
                ]

                # 模块级 PARAMS_SCHEMA 自动挂载
                if hasattr(mod, "PARAMS_SCHEMA"):
                    pending = [m for m in new_registered if not m.params_schema]
                    if len(pending) == 1:
                        pending[0].params_schema = mod.PARAMS_SCHEMA

                # 检查目录型插件是否附带 plugin.json 描述文件
                pjson_data: Dict[str, Any] = {}
                if plugin_file.name in ("main.py", "__init__.py"):
                    pjson_file = resolved_file.parent / "plugin.json"
                    if pjson_file.is_file():
                        try:
                            pjson_data = json.loads(pjson_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass

                # 模块级全局变量元数据提取（VERSION / UPDATED_AT / AUTHOR / CATEGORY / TAGS / ICON / HOMEPAGE）与 mtime 回退
                mod_version = getattr(mod, "VERSION", getattr(mod, "__version__", None))
                mod_updated_at = getattr(mod, "UPDATED_AT", getattr(mod, "__updated_at__", None))
                mod_author = getattr(mod, "AUTHOR", getattr(mod, "__author__", None))
                mod_category = getattr(mod, "CATEGORY", getattr(mod, "__category__", None))
                mod_tags = getattr(mod, "TAGS", getattr(mod, "__tags__", None))
                mod_icon = getattr(mod, "ICON", getattr(mod, "__icon__", None))
                mod_homepage = getattr(mod, "HOMEPAGE", getattr(mod, "__homepage__", None))

                for meta in new_registered:
                    if not meta.source_path:
                        meta.source_path = str(resolved_file)
                        meta.builtin = is_builtin_plugin_path(resolved_file)

                    if (not meta.version or meta.version == "1.0.0"):
                        if mod_version and isinstance(mod_version, str):
                            meta.version = mod_version.strip()
                        elif pjson_data.get("version"):
                            meta.version = str(pjson_data["version"]).strip()

                    if not meta.updated_at:
                        if mod_updated_at and isinstance(mod_updated_at, str):
                            meta.updated_at = mod_updated_at.strip()
                        elif pjson_data.get("updated_at"):
                            meta.updated_at = str(pjson_data["updated_at"]).strip()

                    if not meta.author:
                        if mod_author and isinstance(mod_author, str):
                            meta.author = mod_author.strip()
                        elif pjson_data.get("author"):
                            meta.author = str(pjson_data["author"]).strip()

                    if not meta.category:
                        meta.category = mod_category or pjson_data.get("category") or None

                    if not meta.tags:
                        raw_tags = mod_tags if mod_tags is not None else pjson_data.get("tags")
                        if isinstance(raw_tags, (list, tuple)):
                            meta.tags = [str(t).strip() for t in raw_tags if str(t).strip()]
                        elif isinstance(raw_tags, str) and raw_tags.strip():
                            meta.tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

                    if not meta.icon:
                        meta.icon = mod_icon or pjson_data.get("icon") or None

                    if not meta.homepage:
                        meta.homepage = mod_homepage or pjson_data.get("homepage") or None

                    if (not meta.description or meta.description == f"自定义插件 {meta.name}") and pjson_data.get("description"):
                        meta.description = str(pjson_data["description"]).strip()

                    if not meta.permissions and pjson_data.get("permissions") and isinstance(pjson_data["permissions"], list):
                        meta.permissions = list(pjson_data["permissions"])

                    # 若 updated_at 仍为空，则回退为文件 mtime
                    if not meta.updated_at and meta.source_path and os.path.isfile(meta.source_path):
                        try:
                            meta.updated_at = datetime.fromtimestamp(os.path.getmtime(meta.source_path)).strftime("%Y-%m-%d")
                        except Exception:
                            meta.updated_at = datetime.now().strftime("%Y-%m-%d")
                    elif not meta.updated_at:
                        meta.updated_at = datetime.now().strftime("%Y-%m-%d")
                _logger.info("已成功加载插件: %s (来自 %s)", folder_name, plugin_file)
            except ModuleNotFoundError as exc:
                sys.modules.pop(module_name, None)
                missing = getattr(exc, "name", None) or str(exc)
                _logger.warning(
                    "加载插件 %s 失败：缺少依赖模块 '%s'，可在环境中执行 pip install %s 进行安装",
                    plugin_file, missing, missing
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
                sys.modules.pop(module_name, None)
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
                # 严密捕获单插件的语法/加载错误，绝不雪崩
                sys.modules.pop(module_name, None)
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
    def __init__(self) -> None:
        self.warnings: List[Dict[str, Any]] = []

    def visit_Call(self, node: ast.Call) -> None:
        # 仅对可直接定位的调用目标告警：深属性链（如 a.b.eval()）无法可靠判定，
        # 静态审计本质是启发式提示而非安全边界
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            func_name = f"{node.func.value.id}.{node.func.attr}"
        else:
            self.generic_visit(node)
            return

        if func_name in (
            "eval", "exec", "compile", "__import__",
            "builtins.eval", "builtins.exec", "builtins.compile",
            "builtins.__import__", "importlib.import_module",
            "pickle.loads", "pickle.load", "_pickle.loads", "_pickle.load",
            "marshal.loads", "marshal.load", "shelve.open",
        ):
            self.warnings.append({
                "line": node.lineno,
                "column": node.col_offset,
                "severity": "high",
                "rule": f"disallowed-call:{func_name}",
                "message": f"检测到使用动态执行、隐式导入或危险反序列化函数 '{func_name}'",
            })
        elif func_name in (
            "os.system", "os.popen", "os.kill", "os.killpg", "shutil.rmtree",
            "shutil.move", "os.unlink", "os.remove", "os.rmdir", "pty.spawn",
            "os.execv", "os.execve", "os.execvp", "os.spawnl", "os.spawnlp",
            "os.spawnv", "os.spawnvp", "os.fork",
        ):
            self.warnings.append({
                "line": node.lineno,
                "column": node.col_offset,
                "severity": "high",
                "rule": f"dangerous-system-call:{func_name}",
                "message": f"检测到调用高危系统或破坏性文件操作 '{func_name}'",
            })
        elif func_name in (
            "subprocess.Popen", "subprocess.run", "subprocess.call",
            "subprocess.check_output", "subprocess.check_call",
        ):
            self.warnings.append({
                "line": node.lineno,
                "column": node.col_offset,
                "severity": "medium",
                "rule": f"process-execution:{func_name}",
                "message": f"检测到调用外部进程或跨路径移动 '{func_name}'",
            })

        self.generic_visit(node)


def audit_plugin_source(source: str) -> List[Dict[str, Any]]:
    """启发式静态审计插件源码中的高危调用。

    仅基于 AST 识别常见危险调用模式，可被别名、getattr 等间接手段绕过，
    定位为辅助提示能力而非安全边界。
    """
    try:
        tree = ast.parse(source, filename="<plugin_security_audit>")
        visitor = _SecurityVisitor()
        visitor.visit(tree)
        return visitor.warnings
    except SyntaxError as e:
        return [{
            "line": e.lineno,
            "column": e.offset,
            "severity": "high",
            "rule": "syntax-error",
            "message": f"代码存在语法错误，无法完成安全审计: {e.msg}",
        }]
    except Exception as e:
        return [{
            "line": 1,
            "column": 0,
            "severity": "medium",
            "rule": "audit-error",
            "message": f"审计解析异常: {e}",
        }]
