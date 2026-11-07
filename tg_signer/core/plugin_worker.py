"""TG-SignPulse 插件独立 Worker 进程入口与上下文代理。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from tg_signer.core.plugin_ipc import (
    ProxyMessage,
    decode_ipc_payload,
    encode_ipc_payload,
)
from tg_signer.core.plugins import (
    PluginConnectionResetError,
    PluginError,
    PluginExecutionIdentity,
    PluginFloodWaitError,
    PluginMessageNotFoundError,
    PluginMeta,
    PluginNotSupportedError,
    PluginPermissionDeniedError,
    PluginRegistry,
    PluginTimeoutError,
    plugin_storage_namespace,
    validate_plugin_origin_and_context,
)

__all__ = [
    "PluginConnectionResetError",
    "PluginError",
    "PluginFloodWaitError",
    "PluginMessageNotFoundError",
    "PluginNotSupportedError",
    "PluginPermissionDeniedError",
    "PluginTimeoutError",
    "ProxyPluginContext",
    "ProxyStorageClient",
]


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

    meta = PluginRegistry.get(plugin_name)
    if meta is not None:
        manifest = None
        manifest_file = entry_file.parent / "plugin.json"
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        try:
            validate_plugin_origin_and_context(
                path=source_path,
                name=plugin_name,
                context_version=getattr(meta, "context_version", 1),
                manifest=manifest,
                plugin_api=getattr(meta, "plugin_api", None),
                min_app_version=getattr(meta, "min_app_version", None),
            )
        except Exception:
            PluginRegistry.unregister(plugin_name)
            sys.modules.pop(mod_name, None)
            raise

    return meta


class ProxyStorageClient:
    """在 Worker 进程中通过 JSON-RPC 代理对宿主持久化存储的访问。"""

    def __init__(
        self,
        rpc_requester: Callable[..., Any],
        is_global: bool = False,
        namespace: str = "",
        scope: Optional[str] = None,
    ):
        self._rpc = rpc_requester
        self._is_global = is_global
        # 与宿主侧 PluginStorageClient 保持同构：命名空间仅作标识供插件读取，
        # 实际的存储域划分由宿主的 storage/global_storage 决定
        self.namespace = namespace
        self._scope = scope

    def _scope_kwargs(self, **kwargs: Any) -> Dict[str, Any]:
        if self._is_global:
            kwargs["is_global"] = True
        if self._scope is not None:
            kwargs["scope"] = self._scope
        return kwargs

    async def get(self, key: str, default: Any = None) -> Any:
        return await self._rpc(
            "storage_get", **self._scope_kwargs(key=key, default=default)
        )

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        return await self._rpc(
            "storage_set", **self._scope_kwargs(key=key, value=value, ttl=ttl)
        )

    async def increment(
        self,
        key: str,
        amount: int = 1,
        default: int = 0,
        ttl: Optional[Union[int, float]] = None,
        *,
        delta: Optional[int] = None,
    ) -> Optional[int]:
        step = delta if delta is not None else amount
        return await self._rpc(
            "storage_increment",
            **self._scope_kwargs(
                key=key, amount=step, delta=step, default=default, ttl=ttl
            ),
        )

    async def delete(self, key: str) -> bool:
        return await self._rpc("storage_delete", **self._scope_kwargs(key=key))

    async def clear(self) -> int:
        return await self._rpc("storage_clear", **self._scope_kwargs())

    async def keys(self, prefix: str = "") -> List[str]:
        res = await self._rpc("storage_keys", **self._scope_kwargs(prefix=prefix))
        return list(res or [])

    async def list_keys(self, prefix: str = "") -> List[str]:
        return await self.keys(prefix=prefix)

    async def get_all_records(self) -> List[Dict[str, Any]]:
        res = await self._rpc("storage_get_all_records", **self._scope_kwargs())
        return list(res or [])

    async def get_all(self, prefix: str = "") -> Dict[str, Any]:
        res = await self._rpc("storage_get_all", **self._scope_kwargs(prefix=prefix))
        return dict(res or {})

    async def mget(self, keys: List[str]) -> Dict[str, Any]:
        res = await self._rpc("storage_mget", **self._scope_kwargs(keys=keys))
        return dict(res or {})

    async def mset(self, mapping: Dict[str, Any], ttl: Optional[float] = None) -> None:
        await self._rpc("storage_mset", **self._scope_kwargs(mapping=mapping, ttl=ttl))


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
        identity: Optional[Dict[str, Any]] = None,
        context_version: int = 1,
        storage_prefix: str = "",
    ):
        self.chat_id = chat_id
        self.message_thread_id = message_thread_id
        self._rpc = rpc_requester
        self._logger = logger_sink
        self.message = ProxyMessage(message, rpc=self._rpc) if message else None
        self.params = params or {}
        self.plugin_name = plugin_name
        self.identity = PluginExecutionIdentity(
            **(identity or {"chat_id": chat_id, "thread_id": message_thread_id})
        )
        self.context_version = context_version if context_version in {1, 2} else 1
        self.storage_prefix = storage_prefix
        storage_ns = f"{chat_id}:{plugin_name}" if plugin_name else str(chat_id)
        global_ns = f"global:{plugin_name}" if plugin_name else "global"
        self.storage = ProxyStorageClient(
            self._rpc, is_global=False, namespace=storage_ns
        )
        self.global_storage = ProxyStorageClient(
            self._rpc, is_global=True, namespace=global_ns
        )
        if context_version == 2:
            try:
                self.storage = self.storage_for("chat")
            except Exception:
                pass

        if self.message:
            self.message.click = self.click

    def _has_scoped_identity(self, scope: str) -> bool:
        """与宿主侧保持一致：作用域存储缺少完整身份时回退旧版共享命名空间。"""
        if scope == "global":
            return True
        if not self.identity.account_id:
            return False
        if scope in {"task", "chat"} and not self.identity.task_id:
            return False
        return True

    def storage_for(self, scope: str) -> ProxyStorageClient:
        if scope not in {"global", "account", "task", "chat"}:
            raise ValueError("PLUGIN_STORAGE_INVALID_SCOPE")
        if not self._has_scoped_identity(scope):
            namespace = self.storage_prefix + (
                f"{self.chat_id}:{self.plugin_name}"
                if self.plugin_name
                else str(self.chat_id)
            )
            return ProxyStorageClient(self._rpc, namespace=namespace)
        namespace = self.storage_prefix + plugin_storage_namespace(
            self.plugin_name, self.identity, scope
        )
        return ProxyStorageClient(self._rpc, namespace=namespace, scope=scope)

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
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def send_message(self, text: str, **kwargs) -> Any:
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        res = await self._rpc("send_message", text=text, **kwargs)
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def send_photo(
        self, photo: str, caption: Optional[str] = None, **kwargs
    ) -> Any:
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        res = await self._rpc("send_photo", photo=photo, caption=caption, **kwargs)
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def send_document(
        self, document: str, caption: Optional[str] = None, **kwargs
    ) -> Any:
        if self.message_thread_id is not None:
            kwargs.setdefault("message_thread_id", self.message_thread_id)
        res = await self._rpc(
            "send_document", document=document, caption=caption, **kwargs
        )
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def click(self, text_or_index: Union[str, int], **kwargs) -> Any:
        if not self.message:
            raise RuntimeError("当前上下文中无有效消息，无法执行点击按钮")
        return await self._rpc("click", text_or_index=text_or_index, **kwargs)

    async def react(
        self, emoji: str, message_id: Optional[int] = None, **kwargs
    ) -> Any:
        msg_id = message_id
        if (
            msg_id is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行表情表态")
        call_params = {"emoji": emoji, "message_id": msg_id}
        call_params.update(kwargs)
        return await self._rpc("react", **call_params)

    async def edit_message(
        self, text: str, message_id: Optional[int] = None, **kwargs
    ) -> Any:
        msg_id = message_id
        if (
            msg_id is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行编辑")
        call_params = {"text": text, "message_id": msg_id}
        if self.message_thread_id is not None:
            call_params.setdefault("message_thread_id", self.message_thread_id)
        call_params.update(kwargs)
        res = await self._rpc("edit_message", **call_params)
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def delete_message(self, message_id: Optional[int] = None, **kwargs) -> Any:
        msg_id = message_id
        if (
            msg_id is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行删除")
        call_params = {"message_id": msg_id}
        call_params.update(kwargs)
        return await self._rpc("delete_message", **call_params)

    async def pin_message(self, message_id: Optional[int] = None, **kwargs) -> Any:
        msg_id = message_id
        if (
            msg_id is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            msg_id = self.message.id
        if msg_id is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行置顶")
        call_params = {"message_id": msg_id}
        call_params.update(kwargs)
        return await self._rpc("pin_message", **call_params)

    async def unpin_message(self, message_id: Optional[int] = None, **kwargs) -> Any:
        msg_id = message_id
        if (
            msg_id is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            msg_id = self.message.id
        call_params = {"message_id": msg_id}
        call_params.update(kwargs)
        return await self._rpc("unpin_message", **call_params)

    async def get_messages(self, message_ids: Union[int, List[int]], **kwargs) -> Any:
        call_params = {"message_ids": message_ids}
        call_params.update(kwargs)
        res = await self._rpc("get_messages", **call_params)
        if isinstance(res, list):
            return [
                ProxyMessage(m, rpc=self._rpc)
                if isinstance(m, dict) and "id" in m
                else m
                for m in res
            ]
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def forward_messages(
        self,
        chat_id: Union[int, str],
        from_chat_id: Optional[Union[int, str]] = None,
        message_ids: Optional[Union[int, List[int]]] = None,
        **kwargs,
    ) -> Any:
        mids = message_ids
        if (
            mids is None
            and self.message is not None
            and getattr(self.message, "id", None) is not None
        ):
            mids = self.message.id
        if mids is None:
            raise ValueError("当前上下文中没有有效消息 ID，无法执行转发")
        call_params = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_ids": mids,
        }
        call_params.update(kwargs)
        res = await self._rpc("forward_messages", **call_params)
        if isinstance(res, list):
            return [
                ProxyMessage(m, rpc=self._rpc)
                if isinstance(m, dict) and "id" in m
                else m
                for m in res
            ]
        if isinstance(res, dict) and "id" in res and "chat" in res:
            return ProxyMessage(res, rpc=self._rpc)
        return res

    async def send_chat_action(self, action: str = "typing", **kwargs: Any) -> bool:
        """向当前会话发送聊天动作指示器（如 typing）。"""
        call_params = {"action": action}
        call_params.update(kwargs)
        res = await self._rpc("send_chat_action", **call_params)
        return bool(res)

    async def read_chat_history(self, max_id: Optional[int] = 0, **kwargs: Any) -> bool:
        """将当前会话的历史消息标记为已读（清空未读计数与小红点）。"""
        safe_max_id = int(max_id or 0)
        call_params = {"max_id": safe_max_id}
        call_params.update(kwargs)
        res = await self._rpc("read_chat_history", **call_params)
        return bool(res)


async def run_worker_loop(
    reader: Optional[asyncio.StreamReader] = None,
    writer: Optional[Any] = None,
) -> None:
    # 限制子进程最大虚拟内存配额（仅 POSIX 生效，防 OOM 内存泄露）
    # 默认提高至 1024MB，且在 pytest 运行时跳过 setrlimit，避免 Linux 64位 glibc 线程与 mmap 耗尽虚拟地址空间
    if sys.platform != "win32" and "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            import resource

            max_mb = int(os.environ.get("PLUGIN_MAX_MEMORY_MB", "1024"))
            if max_mb > 0:
                max_bytes = max_mb * 1024 * 1024
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                hard_limit = hard if hard > 0 else max_bytes
                resource.setrlimit(
                    resource.RLIMIT_AS, (min(max_bytes, hard_limit), hard_limit)
                )
            cur_soft, cur_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            safe_nofile = min(cur_soft, 1024)
            if safe_nofile > 0:
                resource.setrlimit(resource.RLIMIT_NOFILE, (safe_nofile, cur_hard))
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
            if current_loop is loop and writer:
                writer.write(encoded)
                return
        except RuntimeError:
            pass
        if loop.is_running() and writer:
            loop.call_soon_threadsafe(writer.write, encoded)

    async def flush_writer() -> None:
        if writer:
            is_closing_fn = getattr(writer, "is_closing", None)
            if is_closing_fn and callable(is_closing_fn) and is_closing_fn():
                return
            try:
                res = writer.drain()
                if inspect.isawaitable(res):
                    await res
            except Exception:
                pass

    async def rpc_request(method: str, **params: Any) -> Any:
        nonlocal req_id
        req_id += 1
        current_id = req_id
        fut = loop.create_future()
        pending_calls[current_id] = fut
        send_payload_sync(
            {"type": "call", "id": current_id, "method": method, "params": params}
        )
        await flush_writer()
        try:
            return await fut
        except asyncio.CancelledError:
            pending_calls.pop(current_id, None)
            send_payload_sync({"type": "call_cancel", "id": current_id})
            await flush_writer()
            raise

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
        hint = (
            f"缺少依赖模块 '{missing}'，可在环境中执行 pip install {missing} 进行安装"
        )
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
        identity=init_data.get("identity"),
        context_version=init_data.get("context_version", 1),
        storage_prefix=init_data.get("storage_prefix", ""),
    )

    async def host_listener():
        while True:
            line = await reader.readline()
            if not line:
                for fut in list(pending_calls.values()):
                    if not fut.done():
                        fut.set_exception(
                            PluginConnectionResetError("IPC pipe closed by host")
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
                        err_code = msg.get("error_code")
                        err_msg = msg.get("error", "RPC call failed")
                        if err_code == "permission_denied":
                            fut.set_exception(PluginPermissionDeniedError(err_msg))
                        elif err_code == "flood_wait":
                            try:
                                secs = int(err_msg)
                            except (ValueError, TypeError):
                                secs = 0
                            fut.set_exception(PluginFloodWaitError(secs))
                        elif err_code == "unsupported":
                            fut.set_exception(PluginNotSupportedError(err_msg))
                        elif err_code == "message_not_found":
                            fut.set_exception(PluginMessageNotFoundError(err_msg))
                        elif err_code == "timeout":
                            fut.set_exception(PluginTimeoutError(err_msg))
                        elif err_code == "ipc_disconnected":
                            fut.set_exception(PluginConnectionResetError(err_msg))
                        else:
                            fut.set_exception(RuntimeError(err_msg))

    listener_task = asyncio.create_task(host_listener())

    try:
        if inspect.iscoroutinefunction(meta.handler):
            res = await meta.handler(ctx)
        else:
            res = await asyncio.to_thread(meta.handler, ctx)
        from tg_signer.core.plugin_runtime import adapt_plugin_result

        validated = adapt_plugin_result(res, identity=ctx.identity)
        send_payload_sync(
            {"type": "return", "success": True, "result": validated.return_value}
        )
    except ModuleNotFoundError as e:
        missing = getattr(e, "name", None) or str(e)
        hint = (
            f"缺少依赖模块 '{missing}'，可在环境中执行 pip install {missing} 进行安装"
        )
        exc_str = traceback.format_exc()
        send_payload_sync(
            {"type": "return", "success": False, "error": f"{hint}\n\n{exc_str}"}
        )
    except Exception as exc:
        exc_str = traceback.format_exc()
        error_type = type(exc).__name__
        error_code = None
        error_message = str(exc)
        seconds = getattr(exc, "seconds", None)

        if isinstance(exc, PluginPermissionDeniedError):
            error_code = "permission_denied"
        elif isinstance(exc, PluginFloodWaitError):
            error_code = "flood_wait"
            if seconds is None:
                try:
                    seconds = int(error_message)
                except (ValueError, TypeError):
                    seconds = 0
        elif isinstance(exc, PluginNotSupportedError):
            error_code = "unsupported"
        elif isinstance(exc, PluginMessageNotFoundError):
            error_code = "message_not_found"
        elif isinstance(exc, PluginTimeoutError):
            error_code = "timeout"
        elif isinstance(
            exc, (PluginConnectionResetError, ConnectionResetError, BrokenPipeError)
        ):
            error_code = "ipc_disconnected"

        resp = {
            "type": "return",
            "success": False,
            "error": exc_str,
            "error_type": error_type,
            "error_message": error_message,
        }
        if error_code:
            resp["error_code"] = error_code
        if seconds is not None:
            resp["seconds"] = seconds
        send_payload_sync(resp)
    finally:
        await asyncio.sleep(0)
        await flush_writer()
        for fut in list(pending_calls.values()):
            if not fut.done():
                fut.cancel()
        pending_calls.clear()
        listener_task.cancel()


def main() -> None:
    if sys.platform != "win32":
        try:
            signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        except Exception:
            pass
    try:
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
