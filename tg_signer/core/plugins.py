"""TG-SignPulse 插件扩展核心模块。

提供 PluginContext 运行上下文、PluginRegistry 注册表及动态隔离加载能力。
"""
from __future__ import annotations

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Union

_logger = logging.getLogger("tg_signer.plugins")


class PluginTimeoutError(RuntimeError):
    """插件执行超时；该错误不可通过步骤级重试安全恢复。"""


class PluginStorageBackend:
    """基于 SQLite 的线程与多进程安全轻量级 KV 存储后端。"""

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
class PluginMeta:
    name: str
    handler: Callable[[PluginContext], Any]
    mode: Literal["reactive", "active"] = "reactive"
    description: str = ""
    source_path: Optional[str] = None
    params_schema: Optional[List[Dict[str, Any]]] = None
    enabled: bool = True


class PluginRegistry:
    _plugins: Dict[str, PluginMeta] = {}
    _loaded_files: set[Path] = set()
    _disabled_plugins: set[str] = set()

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
    ) -> Callable:
        def decorator(fn: Callable[[PluginContext], Any]) -> Callable[[PluginContext], Any]:
            existing = cls._plugins.get(name)
            if existing is not None and existing.handler is not fn:
                raise ValueError(f"插件名称已注册: {name}")
            source_file = None
            try:
                source_file = inspect.getsourcefile(fn)
            except Exception:
                pass
            cls._plugins[name] = PluginMeta(
                name=name,
                handler=fn,
                mode=mode,
                description=description,
                source_path=source_file,
                params_schema=params_schema or [],
                enabled=cls.is_enabled(name),
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
                if p.is_dir():
                    if (p / "main.py").is_file():
                        candidate_files.append(p / "main.py")
                    elif (p / "__init__.py").is_file():
                        candidate_files.append(p / "__init__.py")
                elif p.is_file() and p.suffix == ".py" and not p.name.startswith("__"):
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
                # 模块级 PARAMS_SCHEMA 自动挂载：仅当该文件本次恰好注册一个
                # 未在装饰器声明 schema 的插件时回填，避免同文件多插件误挂。
                if hasattr(mod, "PARAMS_SCHEMA"):
                    pending = [
                        meta
                        for name, meta in cls._plugins.items()
                        if name not in pre_keys
                        and meta.source_path == str(resolved_file)
                        and not meta.params_schema
                    ]
                    if len(pending) == 1:
                        pending[0].params_schema = mod.PARAMS_SCHEMA
                _logger.info("已成功加载插件: %s (来自 %s)", folder_name, plugin_file)
            except ModuleNotFoundError as exc:
                sys.modules.pop(module_name, None)
                missing = getattr(exc, "name", None) or str(exc)
                _logger.warning(
                    "加载插件 %s 失败：缺少依赖模块 '%s'，可在环境中执行 pip install %s 进行安装",
                    plugin_file, missing, missing
                )
            except Exception as exc:
                # 严密捕获单插件的语法/加载错误，绝不雪崩
                sys.modules.pop(module_name, None)
                _logger.error("加载插件 %s 失败: %s", plugin_file, exc, exc_info=True)

        loaded_count = len(cls._plugins) - len(initial_keys)
        return max(0, loaded_count)

    @classmethod
    def get_search_directories(cls) -> list[Path]:
        dirs: list[Path] = []
        env_dir = os.getenv("PLUGINS_DIR")
        if env_dir:
            dirs.append(Path(env_dir).expanduser())

        data_base = os.getenv("APP_DATA_DIR")
        if data_base:
            dirs.append(Path(data_base).expanduser() / "plugins")
        elif Path("/data/plugins").is_dir():
            dirs.append(Path("/data/plugins"))

        cwd_plugins = Path.cwd() / "plugins"
        dirs.append(cwd_plugins)

        # 保持顺序并去重
        deduped: list[Path] = []
        for d in dirs:
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
