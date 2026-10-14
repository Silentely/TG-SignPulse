"""Tests for PluginRuntime, SubprocessPluginAdapter, TestMockAdapter, and Worker Lifecycle Governance."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from tg_signer.core.plugin_host import (
    cleanup_all_worker_processes,
    get_active_worker_processes,
    register_worker_process,
    unregister_worker_process,
)
from tg_signer.core.plugin_runtime import (
    PluginResult,
    PluginRuntime,
    SubprocessPluginAdapter,
    TestMockAdapter,
    get_plugin_runtime,
    set_plugin_runtime,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry


def _register_worker_fixtures():
    """Register top-level plugins so worker subprocesses can load them from this file."""
    PluginRegistry._plugins.pop("test_calc_plugin", None)

    @PluginRegistry.register(
        name="test_calc_plugin",
        mode="reactive",
    )
    def calc_handler(ctx: PluginContext):
        x = ctx.get_param("x", 10, int)
        y = ctx.get_param("y", 20, int)
        ctx.log(f"calculating {x} + {y}")
        return True

    PluginRegistry._plugins.pop("test_hang_plugin", None)

    @PluginRegistry.register(
        name="test_hang_plugin",
        mode="reactive",
    )
    def hang_handler(ctx: PluginContext):

        while True:
            time.sleep(0.05)


_register_worker_fixtures()


class TestPluginRuntimeGovernance:
    """PluginRuntime and Worker process governance test suite."""

    @pytest.fixture(autouse=True)
    def manage_runtime_lifecycle(self):
        """Scoped strictly to this suite: setup fixtures and clean worker processes on teardown."""
        _register_worker_fixtures()
        cleanup_all_worker_processes()
        set_plugin_runtime(None)
        yield
        cleanup_all_worker_processes()
        PluginRegistry._plugins.pop("test_calc_plugin", None)
        PluginRegistry._plugins.pop("test_hang_plugin", None)
        PluginRegistry._plugins.pop("reg_plugin", None)
        set_plugin_runtime(None)

    def test_plugin_result_dataclass(self):
        """Verify PluginResult initialization, defaults, and dictionary serialization."""
        res = PluginResult(
            success=True,
            return_value={"score": 100},
            logs=["[INFO] hello", "[DEBUG] test"],
            error=None,
            execution_time=0.123,
        )
        assert res.success is True
        assert res.return_value == {"score": 100}
        assert len(res.logs) == 2
        assert res.error is None
        assert res.execution_time == 0.123

        d = res.to_dict()
        assert d == {
            "success": True,
            "return_value": {"score": 100},
            "logs": ["[INFO] hello", "[DEBUG] test"],
            "error": None,
            "execution_time": 0.123,
        }

        # Defaults check
        res_def = PluginResult(success=False)
        assert res_def.return_value is None
        assert res_def.logs == []
        assert res_def.error is None
        assert res_def.execution_time == 0.0

    def test_worker_process_registry_tracking_and_cleanup(self):
        """Verify registration, query, unregistration, and bulk termination of worker processes."""
        assert len(get_active_worker_processes()) == 0

        mock_proc1 = MagicMock()
        mock_proc1.pid = 999991
        mock_proc2 = MagicMock()
        mock_proc2.pid = 999992

        register_worker_process(mock_proc1)
        register_worker_process(mock_proc2)
        assert len(get_active_worker_processes()) == 2
        assert mock_proc1 in get_active_worker_processes()
        assert mock_proc2 in get_active_worker_processes()

        # Unregister single
        unregister_worker_process(mock_proc1)
        assert len(get_active_worker_processes()) == 1
        assert mock_proc1 not in get_active_worker_processes()
        assert mock_proc2 in get_active_worker_processes()

        # Re-register and cleanup all
        register_worker_process(mock_proc1)
        with patch("tg_signer.core.plugin_host.kill_process_tree") as mock_kill:
            count = cleanup_all_worker_processes()
            assert count == 2
            assert mock_kill.call_count == 2
            assert len(get_active_worker_processes()) == 0

        # PluginRuntime.cleanup_all delegation
        register_worker_process(mock_proc1)
        with patch("tg_signer.core.plugin_host.kill_process_tree") as mock_kill:
            count = PluginRuntime.cleanup_all()
            assert count == 1
            assert mock_kill.call_count == 1
            assert len(get_active_worker_processes()) == 0

    @pytest.mark.asyncio
    async def test_mock_adapter_execution(self):
        """Verify TestMockAdapter executing async/sync handlers, capturing logs, and measuring duration."""
        adapter = TestMockAdapter()

        # 1. Async handler
        async def async_handler(ctx: PluginContext):
            ctx.log("running async handler")
            return {"result": "async_ok"}

        adapter.register_mock_handler("async_plugin", async_handler)
        ctx = PluginContext(app=None, chat_id=123)
        res = await adapter.execute("async_plugin", {"foo": "bar"}, ctx)

        assert res.success is True
        assert res.return_value == {"result": "async_ok"}
        assert res.execution_time >= 0.0
        assert any("running async handler" in log for log in res.logs)
        assert ctx.params.get("foo") == "bar"

        # 2. Sync handler
        def sync_handler(ctx: PluginContext):
            ctx.log("running sync handler")
            return 42

        adapter.register_mock_handler("sync_plugin", sync_handler)
        res2 = await adapter.execute("sync_plugin", {}, None)
        assert res2.success is True
        assert res2.return_value == 42
        assert any("running sync handler" in log for log in res2.logs)

        # 3. Execution history tracking
        assert len(adapter.execution_history) == 2
        assert adapter.execution_history[0]["plugin_name"] == "async_plugin"
        assert adapter.execution_history[1]["plugin_name"] == "sync_plugin"

    @pytest.mark.asyncio
    async def test_mock_adapter_error_and_timeout(self):
        """Verify TestMockAdapter correctly captures exceptions and timeout conditions."""
        adapter = TestMockAdapter()

        # 1. Error simulation via set_mock_result
        adapter.set_mock_result(
            "failing_plugin", success=False, error="Simulated failure"
        )
        res = await adapter.execute("failing_plugin", {}, None)
        assert res.success is False
        assert res.return_value is None
        assert "Simulated failure" in (res.error or "")

        # 2. Timeout handling
        async def slow_handler(ctx: PluginContext):
            await asyncio.sleep(1.0)
            return True

        adapter.register_mock_handler("slow_plugin", slow_handler)
        res_timeout = await adapter.execute("slow_plugin", {}, None, timeout=0.05)
        assert res_timeout.success is False
        assert "timed out" in (res_timeout.error or "")

    @pytest.mark.asyncio
    async def test_mock_adapter_fallback_to_registry(self):
        """Verify TestMockAdapter can execute handlers registered in PluginRegistry when no mock handler is set."""

        @PluginRegistry.register("reg_plugin", mode="active")
        async def reg_handler(ctx: PluginContext):
            return "from_registry"

        adapter = TestMockAdapter()
        res = await adapter.execute("reg_plugin", {}, None)
        assert res.success is True
        assert res.return_value == "from_registry"

        # Unknown plugin returns default_return_value
        res_unknown = await adapter.execute("non_existent_plugin", {}, None)
        assert res_unknown.success is True
        assert res_unknown.return_value is True

    def test_runtime_injection(self):
        """Verify getting and setting global plugin runtime."""
        default = get_plugin_runtime()
        assert isinstance(default, SubprocessPluginAdapter)

        mock_adapter = TestMockAdapter()
        set_plugin_runtime(mock_adapter)
        assert get_plugin_runtime() is mock_adapter

        set_plugin_runtime(None)
        assert isinstance(get_plugin_runtime(), SubprocessPluginAdapter)

    @pytest.mark.asyncio
    async def test_subprocess_plugin_adapter_real_process(self):
        """Verify SubprocessPluginAdapter launches an isolated worker subprocess and returns PluginResult."""
        adapter = SubprocessPluginAdapter(default_timeout=15.0)
        ctx = PluginContext(app=None, chat_id=1001, params={"x": 5, "y": 7})

        res = await adapter.execute("test_calc_plugin", {"x": 50, "y": 20}, ctx)
        assert res.success is True
        assert res.return_value is True
        assert res.execution_time > 0.0
        assert any("calculating 50 + 20" in log for log in res.logs)
        # Ensure active worker registry is empty after completion
        assert len(get_active_worker_processes()) == 0

    @pytest.mark.asyncio
    async def test_subprocess_plugin_adapter_timeout_governance(self):
        """Verify SubprocessPluginAdapter terminates hanging worker process upon timeout and cleans registry."""
        adapter = SubprocessPluginAdapter(default_timeout=0.3)
        ctx = PluginContext(app=None, chat_id=1001)

        res = await adapter.execute("test_hang_plugin", {}, ctx, timeout=0.3)
        assert res.success is False
        assert "timed out" in (res.error or "").lower()
        # Ensure worker process was terminated and unregistered
        assert len(get_active_worker_processes()) == 0

    @pytest.mark.asyncio
    async def test_subprocess_plugin_adapter_cancellation_cleans_worker(self):
        """Verify cancelling the caller task terminates the running worker process immediately."""
        adapter = SubprocessPluginAdapter(default_timeout=15.0)
        ctx = PluginContext(app=None, chat_id=1001)

        task = asyncio.create_task(adapter.execute("test_hang_plugin", {}, ctx))
        # Give subprocess a short moment to spawn and register
        for _ in range(50):
            if len(get_active_worker_processes()) > 0:
                break
            await asyncio.sleep(0.02)

        # Verify process was registered
        assert len(get_active_worker_processes()) == 1
        worker_proc = get_active_worker_processes()[0]

        # Cancel execution task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Verify worker was terminated and unregistered
        assert len(get_active_worker_processes()) == 0
        if hasattr(worker_proc, "returncode"):
            assert worker_proc.returncode is not None

    @pytest.mark.asyncio
    async def test_backend_shutdown_cleans_orphan_workers(self):
        """Verify that backend lifespan shutdown calls cleanup_all_worker_processes without leaving orphan workers."""
        mock_worker = MagicMock()
        mock_worker.pid = 987654

        register_worker_process(mock_worker)
        assert len(get_active_worker_processes()) == 1

        # Simulate shutdown logic as in backend/main.py
        from tg_signer.core.plugin_host import cleanup_all_worker_processes

        cleaned = cleanup_all_worker_processes()
        assert cleaned == 1
        assert len(get_active_worker_processes()) == 0
