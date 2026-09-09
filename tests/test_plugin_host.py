import asyncio
import os
import signal
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tg_signer.core.plugins import PluginRegistry, PluginContext
from tg_signer.core.plugin_host import PluginProcessHost, kill_process_tree


# Module-level registrations so that worker subprocess can resolve plugins when loading this file
def _register_worker_fixtures():
    PluginRegistry._plugins.pop("test_hang_with_child_process", None)

    @PluginRegistry.register(
        name="test_hang_with_child_process",
        mode="active",
    )
    def hang_handler(ctx: PluginContext):
        import time, subprocess, sys
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"])
        while True:
            time.sleep(0.05)

    PluginRegistry._plugins.pop("test_plugin_with_prints", None)

    @PluginRegistry.register(
        name="test_plugin_with_prints",
        mode="active",
    )
    def print_handler(ctx: PluginContext):
        print("Hello from stdout banner!")
        ctx.log("formal log")
        return True

    PluginRegistry._plugins.pop("test_plugin_rpc_roundtrip", None)

    @PluginRegistry.register(
        name="test_plugin_rpc_roundtrip",
        mode="active",
    )
    async def rpc_handler(ctx: PluginContext):
        ctx.log("starting rpc")
        rep = await ctx.reply("hello reply")
        sent = await ctx.send_message("hello send")
        clicked = await ctx.click("confirm_button")
        if rep and sent and clicked == "clicked_confirm_button":
            return True
        return False

    PluginRegistry._plugins.pop("test_plugin_worker_exception", None)

    @PluginRegistry.register(
        name="test_plugin_worker_exception",
        mode="active",
    )
    def err_handler(ctx: PluginContext):
        raise ValueError("Simulated worker error")


_register_worker_fixtures()


@pytest.fixture(autouse=True)
def ensure_fixtures_registered():
    _register_worker_fixtures()


@pytest.mark.asyncio
async def test_subprocess_host_kills_infinite_loop_and_cleans_process_group():
    PluginRegistry._plugins.pop("test_hang_with_child_process", None)

    @PluginRegistry.register(
        name="test_hang_with_child_process",
        mode="active",
    )
    def hang_handler(ctx: PluginContext):
        import time, subprocess, sys
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"])
        while True:
            time.sleep(0.05)

    mock_app = MagicMock()
    mock_logger = MagicMock()
    ctx = PluginContext(app=mock_app, chat_id=123, logger=mock_logger)

    host = PluginProcessHost(plugin_name="test_hang_with_child_process", ctx=ctx, timeout=0.3)

    with pytest.raises(TimeoutError) as exc_info:
        await host.execute()

    assert "timed out" in str(exc_info.value).lower()
    assert host.process_terminated_by_kill is True


@pytest.mark.asyncio
async def test_subprocess_host_tolerates_arbitrary_print_output():
    PluginRegistry._plugins.pop("test_plugin_with_prints", None)

    @PluginRegistry.register(
        name="test_plugin_with_prints",
        mode="active",
    )
    def print_handler(ctx: PluginContext):
        print("Hello from stdout banner!")
        ctx.log("formal log")
        return True

    mock_app = MagicMock()
    mock_logger = MagicMock()
    ctx = PluginContext(app=mock_app, chat_id=123, logger=mock_logger)

    host = PluginProcessHost(plugin_name="test_plugin_with_prints", ctx=ctx, timeout=2.0)
    res = await host.execute()
    assert res is True
    # 验证非 JSON print 打印被优雅降级捕获，而未破坏协议
    assert any("Hello from stdout banner!" in str(c) for c in mock_logger.mock_calls)


@pytest.mark.asyncio
async def test_subprocess_host_bidirectional_rpc():
    _register_worker_fixtures()
    mock_app = MagicMock()
    mock_app.send_message = AsyncMock(return_value={"id": 999, "text": "mocked"})
    mock_logger = MagicMock()

    class FakeMsg:
        id = 555
        chat_id = 123
        async def click(self, text_or_index, **kwargs):
            return f"clicked_{text_or_index}"

    ctx = PluginContext(app=mock_app, chat_id=123, message=FakeMsg(), logger=mock_logger)

    host = PluginProcessHost(plugin_name="test_plugin_rpc_roundtrip", ctx=ctx, timeout=3.0)
    res = await host.execute()

    assert res is True
    assert mock_app.send_message.call_count >= 2


@pytest.mark.asyncio
async def test_subprocess_host_captures_worker_exception():
    _register_worker_fixtures()
    mock_app = MagicMock()
    mock_logger = MagicMock()
    ctx = PluginContext(app=mock_app, chat_id=123, logger=mock_logger)

    host = PluginProcessHost(plugin_name="test_plugin_worker_exception", ctx=ctx, timeout=2.0)

    with pytest.raises(RuntimeError) as exc_info:
        await host.execute()

    assert "Simulated worker error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kill_process_tree_already_finished():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import sys; sys.exit(0)"
    )
    await proc.wait()
    # Should safely return without error
    kill_process_tree(proc)


@pytest.mark.asyncio
async def test_kill_process_tree_running_process():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(60)",
        start_new_session=True if os.name != "nt" else False
    )
    assert proc.returncode is None
    kill_process_tree(proc)
    await proc.wait()
    assert proc.returncode is not None


def test_kill_process_tree_windows():
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 99999

    with patch("os.name", "nt"), patch("subprocess.run") as mock_run:
        kill_process_tree(mock_proc)
        mock_run.assert_called_once_with(
            ["taskkill", "/F", "/T", "/PID", "99999"],
            stdout=-3,  # subprocess.DEVNULL
            stderr=-3,
            check=False,
        )


def test_kill_process_tree_posix_fallback_on_getpgid_error():
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 88888

    with patch("os.name", "posix"), patch("os.getpgid", side_effect=ProcessLookupError):
        kill_process_tree(mock_proc)
        mock_proc.kill.assert_called_once()
