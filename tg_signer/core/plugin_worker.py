"""TG-SignPulse 插件独立 Worker 进程入口与上下文代理。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from tg_signer.core.plugin_ipc import (
    ProxyMessage,
    decode_ipc_payload,
    encode_ipc_payload,
)
from tg_signer.core.plugins import PluginMeta, PluginRegistry


def import_single_plugin_source(
    source_path: str, plugin_name: str
) -> Optional[PluginMeta]:
    """定向加载单个插件，避免在 Worker 启动时重复扫描全量目录。"""
    p = Path(source_path)
    if not p.exists():
        return None

    entry_file = (
        p
        if p.is_file()
        else (p / "main.py" if (p / "main.py").exists() else p / "__init__.py")
    )
    if not entry_file.exists():
        return None

    # 若为目录型插件，将其所在目录加入 sys.path 以支持目录内的子模块/相对引用
    if entry_file.name in ("main.py", "__init__.py"):
        parent_str = str(entry_file.parent.resolve())
        if parent_str not in sys.path:
            sys.path.insert(0, parent_str)

    mod_name = f"_isolated_plugin_{plugin_name}_{abs(hash(str(entry_file))) % 100000}"
    spec_kwargs = {}
    if entry_file.name in ("main.py", "__init__.py"):
        spec_kwargs["submodule_search_locations"] = [str(entry_file.parent.resolve())]

    spec = importlib.util.spec_from_file_location(
        mod_name, str(entry_file), **spec_kwargs
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(mod_name, None)
            raise

    return PluginRegistry.get(plugin_name)


class ProxyStorageClient:
    """在 Worker 进程中通过 JSON-RPC 代理对宿主持久化存储的访问。"""

    def __init__(self, rpc_requester: Callable[..., Any]):
        self._rpc = rpc_requester

    async def get(self, key: str, default: Any = None) -> Any:
        return await self._rpc("storage_get", key=key, default=default)

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        return await self._rpc("storage_set", key=key, value=value, ttl=ttl)

    async def increment(self, key: str, delta: int = 1, default: int = 0) -> int:
        return await self._rpc(
            "storage_increment", key=key, delta=delta, default=default
        )

    async def delete(self, key: str) -> bool:
        return await self._rpc("storage_delete", key=key)

    async def clear(self) -> int:
        return await self._rpc("storage_clear")


class ProxyPluginContext:
    """在 Worker 进程中提供与 PluginContext 100% 同构的执行上下文。"""

    def __init__(
        self,
        chat_id: int,
        message: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]],
        rpc_requester: Callable[..., Any],
        logger_sink: Callable[[Dict[str, Any]], Any],
        message_thread_id: Optional[int] = None,
        plugin_name: str = "",
    ):
        self.chat_id = chat_id
        self.message_thread_id = message_thread_id
        self.message = ProxyMessage(message) if message else None
        self.params = params or {}
        self.plugin_name = plugin_name
        self._rpc = rpc_requester
        self._logger = logger_sink
        self.storage = ProxyStorageClient(self._rpc)

        if self.message:
            self.message.click = self.click

    def log(
        self,
        msg: Optional[str] = None,
        level: str = "INFO",
        message: Optional[str] = None,
    ) -> None:
        text = msg if msg is not None else (message if message is not None else "")
        payload = {"type": "log", "level": level, "message": str(text)}
        self._logger(payload)

    async def reply(self, text: str, **kwargs) -> Any:
        if self.message is not None and getattr(self.message, "id", None) is not None:
            kwargs.setdefault("reply_to_message_id", self.message.id)
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        res = await self._rpc("reply", text=text, **kwargs)
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res)
        return res

    async def send_message(self, text: str, **kwargs) -> Any:
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        res = await self._rpc("send_message", text=text, **kwargs)
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res)
        return res

    async def click(self, text_or_index: Union[str, int], **kwargs) -> Any:
        if not self.message:
            raise RuntimeError("当前上下文中无有效消息，无法执行点击按钮")
        return await self._rpc("click", text_or_index=text_or_index, **kwargs)

    async def react(self, emoji: str, message_id: Optional[int] = None, **kwargs) -> Any:
        msg_id = message_id
        if msg_id is None and self.message is not None and getattr(self.message, "id", None) is not None:
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中无有效消息 ID，无法执行表情表态")
        call_params = {"emoji": emoji, "message_id": msg_id}
        call_params.update(kwargs)
        return await self._rpc("react", **call_params)


async def run_worker_loop(
    reader: Optional[asyncio.StreamReader] = None,
    writer: Optional[Any] = None,
) -> None:
    # 限制子进程最大虚拟内存配额（仅 POSIX 生效，防 OOM 内存泄露）
    if sys.platform != "win32":
        try:
            import resource
            max_mb = int(os.environ.get("PLUGIN_MAX_MEMORY_MB", "256"))
            if max_mb > 0:
                max_bytes = max_mb * 1024 * 1024
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                hard_limit = hard if hard > 0 else max_bytes
                resource.setrlimit(resource.RLIMIT_AS, (min(max_bytes, hard_limit), hard_limit))
        except Exception:
            pass

    loop = asyncio.get_running_loop()

    if reader is None or writer is None:
        r = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(r)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        w_transport, w_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(w_transport, w_protocol, None, loop)
        reader = r

    req_id = 0
    pending_calls: Dict[int, asyncio.Future] = {}

    def send_payload_sync(payload: Dict[str, Any]) -> None:
        encoded = encode_ipc_payload(payload).encode("utf-8")
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is loop:
            writer.write(encoded)
        else:
            loop.call_soon_threadsafe(writer.write, encoded)

    async def flush_writer() -> None:
        try:
            res = writer.drain()
            if inspect.isawaitable(res):
                await res
        except Exception:
            pass

    async def rpc_request(method: str, **params) -> Any:
        nonlocal req_id
        req_id += 1
        current_id = req_id
        fut = loop.create_future()
        pending_calls[current_id] = fut
        send_payload_sync(
            {"type": "call", "id": current_id, "method": method, "params": params}
        )
        await flush_writer()
        return await fut

    # 读取初始配置
    init_line = await reader.readline()
    if not init_line:
        return
    line_str = init_line.decode("utf-8") if isinstance(init_line, bytes) else init_line
    init_data = decode_ipc_payload(line_str)

    plugin_name = init_data["plugin_name"]
    source_path = init_data.get("source_path")

    meta = None
    try:
        if source_path:
            meta = import_single_plugin_source(source_path, plugin_name)
        if not meta:
            PluginRegistry.load_all_configured_plugins()
            meta = PluginRegistry.get(plugin_name)
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", None) or str(e)
        hint = f"缺少依赖模块 '{missing}'，可在环境中执行 pip install {missing} 进行安装"
        exc_str = traceback.format_exc()
        send_payload_sync(
            {
                "type": "return",
                "success": False,
                "error": f"{hint}\n\n{exc_str}",
            }
        )
        await flush_writer()
        return
    except Exception:
        exc_str = traceback.format_exc()
        send_payload_sync(
            {
                "type": "return",
                "success": False,
                "error": exc_str,
            }
        )
        await flush_writer()
        return

    if not meta:
        send_payload_sync(
            {
                "type": "return",
                "success": False,
                "error": f"Plugin '{plugin_name}' not found",
            }
        )
        await flush_writer()
        return

    ctx = ProxyPluginContext(
        chat_id=init_data["chat_id"],
        message=init_data.get("message"),
        params=init_data.get("params"),
        rpc_requester=rpc_request,
        logger_sink=send_payload_sync,
        message_thread_id=init_data.get("message_thread_id"),
        plugin_name=plugin_name,
    )

    async def host_listener():
        while True:
            line = await reader.readline()
            if not line:
                for fut in list(pending_calls.values()):
                    if not fut.done():
                        fut.set_exception(
                            ConnectionResetError("IPC pipe closed by host")
                        )
                pending_calls.clear()
                break
            try:
                line_text = line.decode("utf-8") if isinstance(line, bytes) else line
                msg = decode_ipc_payload(line_text)
            except Exception:
                continue
            if msg.get("type") == "call_result":
                cid = msg.get("id")
                if cid in pending_calls:
                    fut = pending_calls.pop(cid)
                    if msg.get("success"):
                        fut.set_result(msg.get("data"))
                    else:
                        fut.set_exception(
                            RuntimeError(msg.get("error", "RPC call failed"))
                        )

    listener_task = asyncio.create_task(host_listener())

    try:
        if inspect.iscoroutinefunction(meta.handler):
            res = await meta.handler(ctx)
        else:
            res = await asyncio.to_thread(meta.handler, ctx)
        send_payload_sync({"type": "return", "success": True, "result": bool(res)})
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", None) or str(e)
        hint = f"缺少依赖模块 '{missing}'，可在环境中执行 pip install {missing} 进行安装"
        exc_str = traceback.format_exc()
        send_payload_sync({"type": "return", "success": False, "error": f"{hint}\n\n{exc_str}"})
    except Exception:
        exc_str = traceback.format_exc()
        send_payload_sync({"type": "return", "success": False, "error": exc_str})
    finally:
        await flush_writer()
        for fut in list(pending_calls.values()):
            if not fut.done():
                fut.cancel()
        pending_calls.clear()
        listener_task.cancel()


def main() -> None:
    try:
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
