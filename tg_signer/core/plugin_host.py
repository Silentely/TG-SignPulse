"""TG-SignPulse 插件子进程宿主隔离执行器。"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from typing import Any, Optional, Union

from tg_signer.core.plugin_ipc import (
    decode_ipc_payload,
    encode_ipc_payload,
    serialize_message_for_worker,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry


def kill_process_tree(target: Union[int, Any]) -> None:
    """跨平台终结子进程树（含孙子进程）。支持传入 pid 整数或包含 pid 属性的进程对象。"""
    pid = getattr(target, "pid", target)
    if not isinstance(pid, int) or pid <= 0:
        return
    if os.name != "nt":
        try:
            pgid = os.getpgid(pid)
            if pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL)
                return
        except ProcessLookupError:
            pass
        except OSError:
            pass

        if hasattr(target, "kill") and callable(target.kill):
            try:
                target.kill()
                return
            except Exception:
                pass

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    else:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass


class PluginProcessHost:
    def __init__(
        self,
        plugin_name: str,
        ctx: PluginContext,
        timeout: float = 25.0,
        trigger_type: str = "manual_test",
    ):
        self.plugin_name = plugin_name
        self.ctx = ctx
        self.timeout = timeout
        # 指标口径：manual_test=调试台模拟执行；active/reactive=正式任务执行
        self.trigger_type = trigger_type
        self.process: Optional[asyncio.subprocess.Process] = None
        self.process_terminated_by_kill = False
        if not getattr(self.ctx, "plugin_name", None):
            self.ctx.plugin_name = plugin_name

    def _metric_success(self, res: Any) -> bool:
        """按插件模式判定指标成功口径：active 模式返回 False 即执行失败；
        reactive 模式返回 False 仅表示消息未命中处理，仍属正常执行完成。"""
        if res is None:
            return True
        meta = PluginRegistry.get(self.plugin_name)
        if getattr(meta, "mode", "reactive") == "active":
            return bool(res)
        return True

    async def execute(self) -> Any:
        start_time = time.perf_counter()
        try:
            return await self._execute_inner(start_time)
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            PluginRegistry.record_execution(
                self.plugin_name,
                duration_ms,
                success=False,
                error=str(e),
                trigger_type=self.trigger_type,
            )
            raise

    async def _execute_inner(self, start_time: float) -> Any:
        meta = PluginRegistry.get(self.plugin_name)
        source_path = meta.source_path if meta else None

        cmd = [sys.executable, "-u", "-m", "tg_signer.core.plugin_worker"]
        kwargs = {"start_new_session": True} if os.name != "nt" else {}

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        init_payload = {
            "plugin_name": self.plugin_name,
            "source_path": source_path,
            "chat_id": self.ctx.chat_id,
            "message_thread_id": getattr(self.ctx, "message_thread_id", None),
            "message": serialize_message_for_worker(self.ctx.message),
            "params": getattr(self.ctx, "params", {}),
        }

        encoded_init = encode_ipc_payload(init_payload).encode("utf-8")
        assert self.process.stdin is not None
        self.process.stdin.write(encoded_init)
        await self.process.stdin.drain()

        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        async def stderr_reader():
            assert self.process.stderr is not None
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line_str:
                    self.ctx.log(f"[worker stderr] {line_str}", level="WARNING")

        async def stdout_reader():
            assert self.process.stdout is not None
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line_str:
                    continue

                if line_str.startswith("{"):
                    try:
                        payload = decode_ipc_payload(line_str)
                    except Exception:
                        self.ctx.log(f"[worker stdout] {line_str}", level="DEBUG")
                        continue

                    if not isinstance(payload, dict):
                        self.ctx.log(f"[worker stdout] {line_str}", level="DEBUG")
                        continue

                    msg_type = payload.get("type")
                    if msg_type == "log":
                        self.ctx.log(
                            payload.get("message", ""),
                            level=payload.get("level", "INFO"),
                        )
                    elif msg_type == "return":
                        if payload.get("success"):
                            if not result_future.done():
                                result_future.set_result(payload.get("result", True))
                        else:
                            if not result_future.done():
                                result_future.set_exception(
                                    RuntimeError(
                                        payload.get("error", "Unknown worker error")
                                    )
                                )
                    elif msg_type == "call":
                        cid = payload.get("id")
                        method = payload.get("method")
                        params = payload.get("params", {}) or {}
                        call_res = None
                        call_ok = True
                        call_err = ""
                        try:
                            call_params = dict(params)
                            if method == "reply":
                                text = call_params.pop("text", "")
                                call_res = await self.ctx.reply(text, **call_params)
                            elif method == "send_message":
                                text = call_params.pop("text", "")
                                call_res = await self.ctx.send_message(
                                    text, **call_params
                                )
                            elif method == "click":
                                text_or_index = call_params.pop("text_or_index", None)
                                call_res = await self.ctx.click(
                                    text_or_index, **call_params
                                )
                            elif method == "react":
                                emoji = call_params.pop("emoji", "👍")
                                call_res = await self.ctx.react(
                                    emoji, **call_params
                                )
                            elif method.startswith("storage_"):
                                is_global = bool(call_params.pop("is_global", False))
                                target_storage = (
                                    getattr(self.ctx, "global_storage", self.ctx.storage)
                                    if is_global
                                    else self.ctx.storage
                                )
                                if method == "storage_get":
                                    key = call_params.get("key", "")
                                    default = call_params.get("default", None)
                                    call_res = await target_storage.get(key, default=default)
                                elif method == "storage_set":
                                    key = call_params.get("key", "")
                                    value = call_params.get("value", None)
                                    ttl = call_params.get("ttl", None)
                                    await target_storage.set(key, value, ttl=ttl)
                                    call_res = True
                                elif method == "storage_increment":
                                    key = call_params.get("key", "")
                                    delta = call_params.get("delta", 1)
                                    default = call_params.get("default", 0)
                                    call_res = await target_storage.increment(
                                        key, delta=delta, default=default
                                    )
                                elif method == "storage_delete":
                                    key = call_params.get("key", "")
                                    call_res = await target_storage.delete(key)
                                elif method == "storage_clear":
                                    call_res = await target_storage.clear()
                                elif method == "storage_keys":
                                    prefix = call_params.get("prefix", "")
                                    call_res = await target_storage.keys(prefix=prefix)
                                elif method == "storage_get_all":
                                    prefix = call_params.get("prefix", "")
                                    call_res = await target_storage.get_all(prefix=prefix)
                                else:
                                    raise ValueError(f"Unknown storage RPC method: {method}")
                            else:
                                raise ValueError(f"Unknown RPC method: {method}")

                            if hasattr(call_res, "id") and hasattr(call_res, "chat"):
                                call_res = serialize_message_for_worker(call_res)
                        except Exception as e:
                            call_ok = False
                            call_err = str(e)

                        resp = {
                            "type": "call_result",
                            "id": cid,
                            "success": call_ok,
                        }
                        if call_ok:
                            resp["data"] = call_res
                        else:
                            resp["error"] = call_err

                        encoded_resp = encode_ipc_payload(resp).encode("utf-8")
                        if self.process.stdin and not self.process.stdin.is_closing():
                            try:
                                self.process.stdin.write(encoded_resp)
                                await self.process.stdin.drain()
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                pass
                else:
                    self.ctx.log(f"[worker stdout] {line_str}", level="DEBUG")

        stderr_task = asyncio.create_task(stderr_reader())
        stdout_task = asyncio.create_task(stdout_reader())

        async def wait_process():
            return await self.process.wait()

        process_wait_task = asyncio.create_task(wait_process())

        try:
            done, pending = await asyncio.wait(
                [result_future, process_wait_task],
                timeout=self.timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if result_future in done:
                duration_ms = (time.perf_counter() - start_time) * 1000
                # 先取结果再记账：future 携带异常时在此抛出，由 execute() 统一记为
                # 失败，避免"一条成功 + 一条失败"的双重计数与伪成功记录
                res = result_future.result()
                PluginRegistry.record_execution(
                    self.plugin_name,
                    duration_ms,
                    success=self._metric_success(res),
                    trigger_type=self.trigger_type,
                )
                return res

            if process_wait_task in done:
                # 子进程提前退出，等待 stdout 排空以获取任何 return 包
                try:
                    await asyncio.wait_for(stdout_task, timeout=0.5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                if result_future.done():
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    # 同上：先取结果再记账，异常交由 execute() 统一记录
                    res = result_future.result()
                    PluginRegistry.record_execution(
                        self.plugin_name,
                        duration_ms,
                        success=self._metric_success(res),
                        trigger_type=self.trigger_type,
                    )
                    return res
                exit_code = process_wait_task.result()
                raise RuntimeError(
                    f"Worker process exited prematurely with code {exit_code}"
                )

            # 超时处理
            self.process_terminated_by_kill = True
            kill_process_tree(self.process.pid)
            raise TimeoutError(
                f"Plugin execution timed out after {self.timeout} seconds"
            )

        finally:
            stderr_task.cancel()
            stdout_task.cancel()
            process_wait_task.cancel()
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass

            if self.process and self.process.returncode is None:
                kill_process_tree(self.process.pid)
                try:
                    await asyncio.shield(
                        asyncio.wait_for(self.process.wait(), timeout=1.0)
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
