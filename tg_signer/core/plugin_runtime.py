"""TG-SignPulse 插件异步运行时与 Worker 进程生命周期治理。

提供统一的 PluginResult 结果载荷抽象、PluginRuntime 执行器接口、
生产默认的 SubprocessPluginAdapter（基于子进程沙箱隔离）以及
单元测试专用的 TestMockAdapter（无需启动 OS 真实进程）。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from tg_signer.core.plugin_host import (
    PluginProcessHost,
    cleanup_all_worker_processes,
    get_active_worker_processes,
    register_worker_process,
    unregister_worker_process,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry


@dataclass
class PluginResult:
    """插件执行结果结构化载荷。"""

    success: bool
    return_value: Any = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "return_value": self.return_value,
            "logs": list(self.logs),
            "error": self.error,
            "execution_time": self.execution_time,
        }


class PluginRuntime(ABC):
    """插件异步运行时基类接口。"""

    @abstractmethod
    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
    ) -> PluginResult:
        """异步执行指定插件，返回 PluginResult 结构。"""
        pass

    @classmethod
    def cleanup_all(cls) -> int:
        """全局清理所有活动的 Worker 子进程。"""
        return cleanup_all_worker_processes()


class SubprocessPluginAdapter(PluginRuntime):
    """生产环境默认适配器：严格基于 PluginProcessHost 子进程沙箱隔离执行。"""

    def __init__(self, default_timeout: float = 25.0):
        self.default_timeout = default_timeout

    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
    ) -> PluginResult:
        start_time = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # 上下文缺省兜底与参数合并
        if context is None:
            context = PluginContext(
                app=None,
                chat_id=0,
                params=dict(args or {}),
                plugin_name=plugin_name,
            )
        elif args:
            if hasattr(context, "params") and isinstance(context.params, dict):
                context.params.update(args)
            elif not hasattr(context, "params"):
                context.params = dict(args)

        if not getattr(context, "plugin_name", None):
            context.plugin_name = plugin_name

        captured_logs: List[str] = []
        original_log = getattr(context, "log", None)
        had_instance_log = (
            hasattr(context, "__dict__") and "log" in context.__dict__
        )

        def capturing_log(msg: str, level: str = "INFO") -> None:
            formatted = f"[{level}] {msg}"
            captured_logs.append(formatted)
            if original_log and callable(original_log):
                try:
                    original_log(msg, level=level)
                except TypeError:
                    try:
                        original_log(msg)
                    except Exception:
                        pass
                except Exception:
                    pass

        try:
            context.log = capturing_log
        except Exception:
            pass

        try:
            host = PluginProcessHost(
                plugin_name=plugin_name,
                ctx=context,
                timeout=effective_timeout,
            )
            result = await host.execute()
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=True,
                return_value=result,
                logs=captured_logs,
                error=None,
                execution_time=duration,
            )
        except asyncio.CancelledError:
            # 外部协程被取消时，子进程已在 host 终结，保留协程取消语义
            raise
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=False,
                return_value=None,
                logs=captured_logs,
                error=str(exc),
                execution_time=duration,
            )
        finally:
            if (
                not had_instance_log
                and hasattr(context, "__dict__")
                and "log" in context.__dict__
            ):
                del context.__dict__["log"]
            elif had_instance_log and original_log is not None:
                context.log = original_log


class TestMockAdapter(PluginRuntime):
    """测试专用适配器：在单进程内存中模拟或直调插件，避免衍生真实操作系统进程。"""

    __test__ = False  # 避免 pytest 将其误识别为测试用例类

    def __init__(
        self,
        mock_handlers: Optional[Dict[str, Callable[..., Any]]] = None,
        default_return_value: Any = True,
    ):
        self._mock_handlers: Dict[str, Callable[..., Any]] = dict(mock_handlers or {})
        self.default_return_value = default_return_value
        self.execution_history: List[Dict[str, Any]] = []

    def register_mock_handler(
        self,
        plugin_name: str,
        handler: Callable[..., Any],
    ) -> None:
        """为测试注册特定插件的模拟处理函数。"""
        self._mock_handlers[plugin_name] = handler

    def set_mock_result(
        self,
        plugin_name: str,
        return_value: Any = True,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """快速设置某插件的固定返回值或异常行为。"""

        async def _mock_fn(*args, **kwargs):
            if not success and error:
                raise RuntimeError(error)
            return return_value

        self._mock_handlers[plugin_name] = _mock_fn

    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
    ) -> PluginResult:
        start_time = time.perf_counter()
        captured_logs: List[str] = []

        self.execution_history.append(
            {
                "plugin_name": plugin_name,
                "args": dict(args or {}),
                "context": context,
                "timeout": timeout,
            }
        )

        if context is None:
            context = PluginContext(
                app=None,
                chat_id=0,
                params=dict(args or {}),
                plugin_name=plugin_name,
            )
        elif args:
            if hasattr(context, "params") and isinstance(context.params, dict):
                context.params.update(args)
            elif not hasattr(context, "params"):
                context.params = dict(args)

        if not getattr(context, "plugin_name", None):
            context.plugin_name = plugin_name

        original_log = getattr(context, "log", None)
        had_instance_log = (
            hasattr(context, "__dict__") and "log" in context.__dict__
        )

        def capturing_log(msg: str, level: str = "INFO") -> None:
            formatted = f"[{level}] {msg}"
            captured_logs.append(formatted)
            if original_log and callable(original_log):
                try:
                    original_log(msg, level=level)
                except TypeError:
                    try:
                        original_log(msg)
                    except Exception:
                        pass
                except Exception:
                    pass

        try:
            context.log = capturing_log
        except Exception:
            pass

        try:
            handler = self._mock_handlers.get(plugin_name)
            if handler is None:
                meta = PluginRegistry.get(plugin_name)
                if meta and meta.handler:
                    handler = meta.handler

            if handler is None:
                duration = time.perf_counter() - start_time
                return PluginResult(
                    success=True,
                    return_value=self.default_return_value,
                    logs=captured_logs,
                    error=None,
                    execution_time=duration,
                )

            coro = self._invoke_handler(handler, context, args)
            if timeout is not None and timeout > 0:
                result = await asyncio.wait_for(coro, timeout=timeout)
            else:
                result = await coro

            duration = time.perf_counter() - start_time
            return PluginResult(
                success=True,
                return_value=result,
                logs=captured_logs,
                error=None,
                execution_time=duration,
            )
        except asyncio.TimeoutError:
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=False,
                return_value=None,
                logs=captured_logs,
                error=f"Plugin '{plugin_name}' execution timed out after {timeout} seconds",
                execution_time=duration,
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=False,
                return_value=None,
                logs=captured_logs,
                error=str(exc),
                execution_time=duration,
            )
        finally:
            if (
                not had_instance_log
                and hasattr(context, "__dict__")
                and "log" in context.__dict__
            ):
                del context.__dict__["log"]
            elif had_instance_log and original_log is not None:
                context.log = original_log

    async def _invoke_handler(
        self,
        handler: Callable[..., Any],
        context: Any,
        args: Dict[str, Any],
    ) -> Any:
        sig = None
        try:
            sig = inspect.signature(handler)
        except Exception:
            pass

        call_args: List[Any] = []
        if sig:
            param_count = len(sig.parameters)
            if param_count == 0:
                call_args = []
            elif param_count == 1:
                call_args = [context]
            else:
                call_args = [context, args]
        else:
            call_args = [context]

        if inspect.iscoroutinefunction(handler):
            return await handler(*call_args)
        else:
            res = handler(*call_args)
            if inspect.isawaitable(res):
                return await res
            return res


_default_runtime: Optional[PluginRuntime] = None


def get_plugin_runtime() -> PluginRuntime:
    """获取全局生效的 PluginRuntime 实例（缺省为 SubprocessPluginAdapter）。"""
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = SubprocessPluginAdapter()
    return _default_runtime


def set_plugin_runtime(runtime: Optional[PluginRuntime]) -> None:
    """设置全局生效的 PluginRuntime 实例（供测试或定制注入）。"""
    global _default_runtime
    _default_runtime = runtime


__all__ = [
    "PluginResult",
    "PluginRuntime",
    "SubprocessPluginAdapter",
    "TestMockAdapter",
    "get_plugin_runtime",
    "set_plugin_runtime",
    "register_worker_process",
    "unregister_worker_process",
    "get_active_worker_processes",
    "cleanup_all_worker_processes",
]
