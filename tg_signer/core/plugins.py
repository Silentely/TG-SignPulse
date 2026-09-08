"""TG-SignPulse 插件扩展核心模块。

提供 PluginContext 运行上下文、PluginRegistry 注册表及动态隔离加载能力。
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Union

_logger = logging.getLogger("tg_signer.plugins")


@dataclass
class PluginContext:
    app: Any
    chat_id: int
    message_thread_id: Optional[int] = None
    message: Optional[Any] = None
    params: Dict[str, Any] = field(default_factory=dict)
    logger: Any = None

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


@dataclass
class PluginMeta:
    name: str
    handler: Callable[[PluginContext], Any]
    mode: Literal["reactive", "active"] = "reactive"
    description: str = ""


class PluginRegistry:
    _plugins: Dict[str, PluginMeta] = {}
    _loaded_files: set[Path] = set()

    @classmethod
    def register(
        cls,
        name: str,
        mode: Literal["reactive", "active"] = "reactive",
        description: str = "",
    ) -> Callable:
        def decorator(fn: Callable[[PluginContext], Any]) -> Callable[[PluginContext], Any]:
            cls._plugins[name] = PluginMeta(
                name=name,
                handler=fn,
                mode=mode,
                description=description,
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
            module_name = f"tg_signer_plugin_{sanitized_name}"

            # 若为目录型插件，将其所在目录加入 sys.path 以支持目录内的子模块/相对引用
            if plugin_file.name in ("main.py", "__init__.py"):
                parent_str = str(resolved_file.parent)
                if parent_str not in sys.path:
                    sys.path.insert(0, parent_str)

            try:
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                if spec is None or spec.loader is None:
                    _logger.warning("无法创建插件规范: %s", plugin_file)
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)
                cls._loaded_files.add(resolved_file)
                _logger.info("已成功加载插件: %s (来自 %s)", folder_name, plugin_file)
            except Exception as exc:
                # 严密捕获单插件的语法/加载错误，绝不雪崩
                sys.modules.pop(module_name, None)
                _logger.error("加载插件 %s 失败: %s", plugin_file, exc, exc_info=True)

        current_keys = set(cls._plugins.keys())
        return len(current_keys - initial_keys)

    @classmethod
    def load_all_configured_plugins(cls) -> int:
        """从环境变量与默认数据目录扫描并加载所有插件。返回已注册的插件总数。"""
        search_dirs: list[Path] = []

        # 1. 环境变量显式指定 (如 Docker 挂载 /app/user-plugins)
        env_dir = os.environ.get("PLUGINS_DIR") or os.environ.get("TG_SIGNER_PLUGINS_DIR")
        if env_dir:
            search_dirs.append(Path(env_dir))

        # 2. 容器与数据目录 (/data/plugins 或 APP_DATA_DIR/plugins)
        app_data = os.environ.get("APP_DATA_DIR")
        if app_data:
            search_dirs.append(Path(app_data) / "plugins")
        else:
            search_dirs.append(Path("/data/plugins"))

        # 3. 本地当前工作目录 ./plugins
        search_dirs.append(Path.cwd() / "plugins")

        visited: set[Path] = set()
        for d in search_dirs:
            resolved = d.resolve()
            if resolved in visited or not resolved.is_dir():
                continue
            visited.add(resolved)
            cls.load_plugins_from_dir(resolved)
        return len(cls._plugins)
