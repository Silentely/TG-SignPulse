"""TG-SignPulse 宿主端子进程 Worker 管理器与跨平台进程组超时硬终止控制器。"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any, Optional

from tg_signer.core.plugin_ipc import (
    decode_ipc_payload,
    encode_ipc_payload,
    serialize_message_for_worker,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry


def kill_process_tree(proc: Optional[asyncio.subprocess.Process]) -> None:
    """跨平台强杀进程及其整个进程组，彻底杜绝孤儿进程。"""
    if proc is None or proc.returncode is not None or proc.pid is None:
        return

    pid = proc.pid
    if os.name != "nt":
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    else:
        # Windows 环境下通过 taskkill /F /T 强杀整棵树
        try:
            import subprocess

            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


class PluginProcessHost:
    def __init__(self, plugin_name: str, ctx: PluginContext, timeout: float = 25.0):
        self.plugin_name = plugin_name
        self.ctx = ctx
        self.timeout = timeout
        self.process: Optional[asyncio.subprocess.Process] = None
        self.process_terminated_by_kill = False

    async def execute(self) -> Any:
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
            "params": self.ctx.params,
        }

        self.process.stdin.write(encode_ipc_payload(init_payload).encode("utf-8"))
        await self.process.stdin.drain()

        result_future = asyncio.get_running_loop().create_future()

        async def stderr_reader():
            """消费 stderr 输出，防止因子进程写满 stderr 管道缓冲区导致死锁。"""
            try:
                while True:
                    line = await self.process.stderr.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", "replace").strip()
                    if line_str:
                        self.ctx.log(f"[worker stderr] {line_str}", level="WARNING")
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        async def stdout_reader():
            try:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", "replace").strip()
                    if not line_str:
                        continue

                    # 免疫普通 print 输出干扰
                    if not line_str.startswith("{"):
                        self.ctx.log(f"[worker stdout] {line_str}", level="DEBUG")
                        continue

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
                            "data": call_res,
                            "error": call_err,
                        }
                        try:
                            self.process.stdin.write(
                                encode_ipc_payload(resp).encode("utf-8")
                            )
                            await self.process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError):
                            break
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not result_future.done():
                    result_future.set_exception(e)
            finally:
                if not result_future.done():
                    # 管道 EOF 但结果未返回，检查子进程是否已非正常退出
                    await self.process.wait()
                    if not result_future.done():
                        rc = self.process.returncode
                        result_future.set_exception(
                            RuntimeError(
                                f"Worker process exited unexpectedly with returncode {rc}"
                            )
                        )

        reader_task = asyncio.create_task(stdout_reader())
        stderr_task = asyncio.create_task(stderr_reader())

        try:
            return await asyncio.wait_for(result_future, timeout=self.timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            self.process_terminated_by_kill = True
            kill_process_tree(self.process)
            try:
                await self.process.wait()
            except (ProcessLookupError, Exception):
                pass
            raise TimeoutError(
                f"Plugin '{self.plugin_name}' timed out after {self.timeout}s and was killed"
            ) from exc
        finally:
            reader_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(reader_task, stderr_task, return_exceptions=True)
            try:
                if self.process and self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                if self.process and self.process.returncode is None:
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=0.2)
                    except (asyncio.TimeoutError, TimeoutError):
                        pass
            except Exception:
                pass
            kill_process_tree(self.process)
            try:
                if self.process:
                    await self.process.wait()
            except (ProcessLookupError, Exception):
                pass
