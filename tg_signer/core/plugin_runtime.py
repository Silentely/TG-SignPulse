"""TG-SignPulse 插件异步运行时与 Worker 进程生命周期治理。

提供统一的 PluginResult 结果负载抽象、PluginRuntime 执行器接口、
生产默认的 SubprocessPluginAdapter（基于子进程沙箱隔离）以及
单元测试专用的 TestMockAdapter（无需启动 OS 真实进程）。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

from tg_signer.core import plugin_host as _ph
from tg_signer.core.plugin_host import (
    PluginProcessHost,
    cleanup_all_worker_processes,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry


@dataclass
class PluginResult:
    """插件执行结果结构化负载。"""

    success: bool = True
    return_value: Any = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    execution_time: float = 0.0
    is_timeout: bool = False
    handled: Optional[bool] = None
    outcome: Literal["confirmed", "failed", "skipped", "unknown"] = "unknown"
    outputs: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "success": self.success,
            "return_value": self.return_value,
            "logs": list(self.logs),
            "error": self.error,
            "execution_time": self.execution_time,
        }
        if self.is_timeout:
            d["is_timeout"] = True
        if self.handled is not None:
            d.update(
                handled=self.handled,
                outcome=self.outcome,
                outputs=self.outputs,
                evidence=self.evidence,
            )
        return d


MAX_PLUGIN_RESULT_BYTES = 32768


def adapt_plugin_result(value: Any, *, identity=None) -> PluginResult:
    """Validate plugin claims; handled is control flow, never host confirmation.

    Evidence may reference the current host event/revision only. Plugins cannot
    mint host evidence records or change their provenance through this channel.
    """
    if isinstance(value, PluginResult):
        value = (
            {
                "handled": value.handled,
                "outcome": value.outcome,
                "outputs": value.outputs,
                "evidence": value.evidence,
            }
            if value.handled is not None
            else value.return_value
        )

    def check_json(item, depth=0):
        if depth > 20:
            raise ValueError("PLUGIN_RESULT_INVALID: nesting limit")
        if item is None or type(item) in {str, bool, int}:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check_json(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check_json(child, depth + 1)
            return
        raise ValueError("PLUGIN_RESULT_INVALID: JSON value required")

    check_json(value)
    if (
        len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        > MAX_PLUGIN_RESULT_BYTES
    ):
        raise ValueError("PLUGIN_RESULT_INVALID: byte limit")
    if isinstance(value, dict) and ("handled" in value or "outcome" in value):
        if set(value) - {"handled", "outcome", "outputs", "evidence"}:
            raise ValueError("PLUGIN_RESULT_INVALID: unknown result fields")
        handled, outcome = value.get("handled"), value.get("outcome", "unknown")
        outputs, evidence = value.get("outputs", {}), value.get("evidence", [])
        if type(handled) is not bool or outcome not in {
            "confirmed",
            "failed",
            "skipped",
            "unknown",
        }:
            raise ValueError("PLUGIN_RESULT_INVALID: handled/outcome")
        if not isinstance(outputs, dict) or not isinstance(evidence, list):
            raise ValueError("PLUGIN_RESULT_INVALID: outputs/evidence")
        for ref in evidence:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"event_id", "event_revision"}
                or identity is None
                or not identity.event_id
                or ref["event_id"] != identity.event_id
                or ref["event_revision"] != identity.event_revision
            ):
                raise ValueError("PLUGIN_RESULT_INVALID: host evidence reference")
        return PluginResult(
            return_value=value,
            handled=handled,
            outcome=outcome,
            outputs=outputs,
            evidence=evidence,
        )
    return PluginResult(return_value=value, handled=bool(value), outcome="unknown")


class PluginRuntime(ABC):
    """插件运行时契约接口。"""

    @abstractmethod
    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
        trigger_type: str = "scheduled",
    ) -> PluginResult:
        """异步执行指定插件，返回标准结构化结果。"""
        pass

    @staticmethod
    def cleanup_all() -> int:
        """清理所有正在运行的插件进程。"""
        return cleanup_all_worker_processes()


class SubprocessPluginAdapter(PluginRuntime):
    """生产环境默认适配器：通过独立子进程与 IPC 执行插件代码，保证宿主稳定性。"""

    def __init__(self, default_timeout: float = 30.0):
        self.default_timeout = default_timeout

    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
        trigger_type: str = "scheduled",
    ) -> PluginResult:
        start_time = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self.default_timeout

        # 确保 context 属性健全
        if context is not None:
            if not hasattr(context, "params") or not isinstance(context.params, dict):
                try:
                    context.params = dict(args)
                except Exception:
                    pass
            else:
                context.params.update(args)

            if not getattr(context, "plugin_name", None):
                try:
                    context.plugin_name = plugin_name
                except Exception:
                    pass

        captured_logs: List[str] = []
        original_log = getattr(context, "log", None) if context else None

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

        if context is not None:
            try:
                context.log = capturing_log
            except Exception:
                pass

        try:
            host_cls = getattr(_ph, "PluginProcessHost", PluginProcessHost)
            host = host_cls(
                plugin_name=plugin_name,
                ctx=context,
                timeout=effective_timeout,
                trigger_type=trigger_type,
            )
            result = await host.execute()
            duration = time.perf_counter() - start_time
            adapted = adapt_plugin_result(
                result, identity=getattr(context, "identity", None)
            )
            return PluginResult(
                success=True,
                return_value=result,
                logs=captured_logs,
                error=None,
                execution_time=duration,
                handled=adapted.handled,
                outcome=adapted.outcome,
                outputs=adapted.outputs,
                evidence=adapted.evidence,
            )
        except TimeoutError as exc:
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=False,
                return_value=None,
                logs=captured_logs,
                error=str(exc)
                or f"Plugin '{plugin_name}' timed out after {effective_timeout}s",
                execution_time=duration,
                is_timeout=True,
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

    @staticmethod
    def cleanup_all() -> int:
        """注销并终止当前所有活跃的插件子进程树。"""
        return cleanup_all_worker_processes()


class TestMockAdapter(PluginRuntime):
    """测试专用适配器：直接在内存中执行注册的插件 handler 或 mock 回调，无需启动操作系统进程。"""

    def __init__(
        self,
        custom_handlers: Optional[Dict[str, Callable]] = None,
        default_return_value: Any = True,
    ):
        self.custom_handlers: Dict[str, Callable] = custom_handlers or {}
        self.mock_results: Dict[str, PluginResult] = {}
        self.execution_history: List[Dict[str, Any]] = []
        self.default_return_value = default_return_value

    def register_mock_handler(self, plugin_name: str, handler: Callable) -> None:
        self.custom_handlers[plugin_name] = handler

    def set_handler(self, plugin_name: str, handler: Callable) -> None:
        self.custom_handlers[plugin_name] = handler

    def set_mock_result(
        self,
        plugin_name: str,
        *,
        success: bool = True,
        return_value: Any = None,
        error: Optional[str] = None,
        logs: Optional[List[str]] = None,
    ) -> None:
        self.mock_results[plugin_name] = PluginResult(
            success=success,
            return_value=return_value,
            error=error,
            logs=logs or [],
        )

    async def execute(
        self,
        plugin_name: str,
        args: Dict[str, Any],
        context: Any,
        *,
        timeout: Optional[float] = None,
        trigger_type: str = "scheduled",
    ) -> PluginResult:
        start_time = time.perf_counter()
        self.execution_history.append(
            {
                "plugin_name": plugin_name,
                "args": dict(args),
                "trigger_type": trigger_type,
                "timeout": timeout,
            }
        )

        if context is None:
            context = PluginContext(
                app=None, chat_id=0, plugin_name=plugin_name, params=dict(args)
            )
        else:
            if not hasattr(context, "params") or not isinstance(context.params, dict):
                try:
                    context.params = dict(args)
                except Exception:
                    pass
            else:
                context.params.update(args)

        if plugin_name in self.mock_results:
            duration = time.perf_counter() - start_time
            res = self.mock_results[plugin_name]
            res.execution_time = duration
            return res

        handler = self.custom_handlers.get(plugin_name)
        if not handler:
            meta = PluginRegistry.get(plugin_name)
            if meta and meta.handler:
                handler = meta.handler

        if not handler:
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=True,
                return_value=self.default_return_value,
                logs=[],
                error=None,
                execution_time=duration,
            )

        captured_logs: List[str] = []

        def mock_log(msg: str, level: str = "INFO") -> None:
            captured_logs.append(f"[{level}] {msg}")

        try:
            context.log = mock_log
        except Exception:
            pass

        try:
            if inspect.iscoroutinefunction(handler):
                coro = handler(context)
            else:

                async def _sync_runner():
                    return handler(context)

                coro = _sync_runner()

            if timeout is not None:
                res = await asyncio.wait_for(coro, timeout=timeout)
            else:
                res = await coro

            duration = time.perf_counter() - start_time
            adapted = adapt_plugin_result(
                res, identity=getattr(context, "identity", None)
            )
            return PluginResult(
                success=True,
                return_value=res,
                logs=captured_logs,
                error=None,
                execution_time=duration,
                handled=adapted.handled,
                outcome=adapted.outcome,
                outputs=adapted.outputs,
                evidence=adapted.evidence,
            )
        except (asyncio.TimeoutError, TimeoutError):
            duration = time.perf_counter() - start_time
            return PluginResult(
                success=False,
                return_value=None,
                logs=captured_logs,
                error=f"Plugin '{plugin_name}' timed out after {timeout}s",
                execution_time=duration,
                is_timeout=True,
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

    @staticmethod
    def cleanup_all() -> int:
        return 0


_global_runtime: Optional[PluginRuntime] = None


def get_plugin_runtime() -> PluginRuntime:
    """获取全局单例 PluginRuntime 实例。"""
    global _global_runtime
    if _global_runtime is None:
        _global_runtime = SubprocessPluginAdapter()
    return _global_runtime


def set_plugin_runtime(runtime: Optional[PluginRuntime]) -> None:
    """替换全局 PluginRuntime（仅限测试或定制环境使用）。"""
    global _global_runtime
    _global_runtime = runtime


def reset_plugin_runtime() -> None:
    """重置全局 PluginRuntime 为默认 SubprocessPluginAdapter。"""
    global _global_runtime
    _global_runtime = None
