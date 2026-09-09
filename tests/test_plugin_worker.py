import asyncio
import json
import sys
from unittest.mock import AsyncMock

import pytest

from tg_signer.core.plugin_ipc import decode_ipc_payload, encode_ipc_payload
from tg_signer.core.plugin_worker import (
    ProxyPluginContext,
    import_single_plugin_source,
    run_worker_loop,
)


def test_import_single_plugin_source_file(tmp_path):
    pfile = tmp_path / "custom_sample.py"
    pfile.write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="tmp_sample_worker_file", mode="active")\n'
        "def handle(ctx): return 42\n"
    )
    meta = import_single_plugin_source(str(pfile), "tmp_sample_worker_file")
    assert meta is not None
    assert meta.name == "tmp_sample_worker_file"
    assert meta.handler(None) == 42


def test_import_single_plugin_source_dir(tmp_path):
    pdir = tmp_path / "pkg_plugin"
    pdir.mkdir()
    (pdir / "main.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="tmp_sample_worker_dir", mode="active")\n'
        "def handle(ctx): return 99\n"
    )
    meta = import_single_plugin_source(str(pdir), "tmp_sample_worker_dir")
    assert meta is not None
    assert meta.name == "tmp_sample_worker_dir"
    assert meta.handler(None) == 99


def test_import_single_plugin_source_nonexistent(tmp_path):
    assert import_single_plugin_source(str(tmp_path / "nonexistent.py"), "foo") is None


def test_import_single_plugin_source_syntax_error_and_cleanup(tmp_path):
    pfile = tmp_path / "bad_syntax.py"
    pfile.write_text("def invalid_syntax(:\n")

    with pytest.raises(SyntaxError):
        import_single_plugin_source(str(pfile), "bad_syntax_plugin")

    # Verify sys.modules cleaned up
    lingering = [
        k for k in sys.modules if k.startswith("_isolated_plugin_bad_syntax_plugin")
    ]
    assert len(lingering) == 0


@pytest.mark.asyncio
async def test_proxy_plugin_context_logging():
    logs = []
    ctx = ProxyPluginContext(
        chat_id=123,
        message=None,
        params={"key": "val"},
        rpc_requester=AsyncMock(),
        logger_sink=lambda payload: logs.append(payload),
    )
    # Positional
    ctx.log("test log positional", level="WARNING")
    # Keyword msg (isomorphism with PluginContext)
    ctx.log(msg="test log msg kwarg", level="DEBUG")
    # Keyword message
    ctx.log(message="test log message kwarg", level="ERROR")

    assert len(logs) == 3
    assert logs[0] == {
        "type": "log",
        "level": "WARNING",
        "message": "test log positional",
    }
    assert logs[1] == {"type": "log", "level": "DEBUG", "message": "test log msg kwarg"}
    assert logs[2] == {
        "type": "log",
        "level": "ERROR",
        "message": "test log message kwarg",
    }


@pytest.mark.asyncio
async def test_proxy_plugin_context_rpc_methods():
    rpc_mock = AsyncMock(return_value={"status": "ok"})
    logs = []
    msg_data = {
        "id": 888,
        "text": "original message",
        "chat": {"id": 123, "title": "Group", "type": "supergroup"},
        "from_user": {"id": 456, "username": "tester"},
        "buttons": [[{"text": "Btn1", "data": "b1"}]],
    }
    ctx = ProxyPluginContext(
        chat_id=123,
        message=msg_data,
        params={"foo": "bar"},
        rpc_requester=rpc_mock,
        logger_sink=lambda payload: logs.append(payload),
        message_thread_id=10,
    )

    # 1. reply
    res = await ctx.reply("hello reply")
    assert res == {"status": "ok"}
    rpc_mock.assert_called_with(
        "reply", text="hello reply", reply_to_message_id=888, message_thread_id=10
    )

    # 2. send_message
    rpc_mock.reset_mock()
    res = await ctx.send_message("direct message")
    assert res == {"status": "ok"}
    rpc_mock.assert_called_with(
        "send_message", text="direct message", message_thread_id=10
    )

    # 3. click via ctx
    rpc_mock.reset_mock()
    res = await ctx.click("Btn1")
    assert res == {"status": "ok"}
    rpc_mock.assert_called_with("click", text_or_index="Btn1")

    # 4. click via ctx.message
    rpc_mock.reset_mock()
    res = await ctx.message.click(0)
    assert res == {"status": "ok"}
    rpc_mock.assert_called_with("click", text_or_index=0)


@pytest.mark.asyncio
async def test_proxy_plugin_context_click_no_message_error():
    ctx = ProxyPluginContext(
        chat_id=123,
        message=None,
        params={},
        rpc_requester=AsyncMock(),
        logger_sink=lambda payload: None,
    )
    with pytest.raises(RuntimeError, match="当前上下文中无有效消息"):
        await ctx.click("Btn1")


@pytest.mark.asyncio
async def test_run_worker_loop_in_memory_success(tmp_path):
    pfile = tmp_path / "sync_worker_plugin.py"
    pfile.write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="sync_worker_plugin", mode="active")\n'
        "def handle(ctx):\n"
        '    ctx.log("doing work")\n'
        "    return True\n"
    )

    init_payload = {
        "plugin_name": "sync_worker_plugin",
        "source_path": str(pfile),
        "chat_id": 999,
        "message": None,
        "params": {},
    }

    in_reader = asyncio.StreamReader()
    in_reader.feed_data(encode_ipc_payload(init_payload).encode("utf-8"))
    in_reader.feed_eof()

    class FakeWriter:
        def __init__(self):
            self.lines = []

        def write(self, data: bytes):
            self.lines.extend(data.decode("utf-8").splitlines())

        async def drain(self):
            pass

    out_writer = FakeWriter()

    await run_worker_loop(reader=in_reader, writer=out_writer)

    # Verify output messages
    decoded = [json.loads(line) for line in out_writer.lines if line.strip()]
    assert any(
        d.get("type") == "log" and d.get("message") == "doing work" for d in decoded
    )
    return_msg = [d for d in decoded if d.get("type") == "return"]
    assert len(return_msg) == 1
    assert return_msg[0]["success"] is True
    assert return_msg[0]["result"] is True


@pytest.mark.asyncio
async def test_run_worker_loop_in_memory_plugin_not_found():
    init_payload = {
        "plugin_name": "non_existent_plugin_12345",
        "source_path": None,
        "chat_id": 999,
    }

    in_reader = asyncio.StreamReader()
    in_reader.feed_data(encode_ipc_payload(init_payload).encode("utf-8"))
    in_reader.feed_eof()

    class FakeWriter:
        def __init__(self):
            self.lines = []

        def write(self, data: bytes):
            self.lines.extend(data.decode("utf-8").splitlines())

        async def drain(self):
            pass

    out_writer = FakeWriter()

    await run_worker_loop(reader=in_reader, writer=out_writer)

    decoded = [json.loads(line) for line in out_writer.lines if line.strip()]
    return_msg = [d for d in decoded if d.get("type") == "return"]
    assert len(return_msg) == 1
    assert return_msg[0]["success"] is False
    assert "not found" in return_msg[0]["error"]


@pytest.mark.asyncio
async def test_run_worker_loop_in_memory_import_error_captured(tmp_path):
    pfile = tmp_path / "broken_import_plugin.py"
    pfile.write_text("import non_existent_pkg_xyz_12345\n")

    init_payload = {
        "plugin_name": "broken_import_plugin",
        "source_path": str(pfile),
        "chat_id": 999,
    }

    in_reader = asyncio.StreamReader()
    in_reader.feed_data(encode_ipc_payload(init_payload).encode("utf-8"))
    in_reader.feed_eof()

    class FakeWriter:
        def __init__(self):
            self.lines = []

        def write(self, data: bytes):
            self.lines.extend(data.decode("utf-8").splitlines())

        async def drain(self):
            pass

    out_writer = FakeWriter()

    await run_worker_loop(reader=in_reader, writer=out_writer)

    decoded = [json.loads(line) for line in out_writer.lines if line.strip()]
    return_msg = [d for d in decoded if d.get("type") == "return"]
    assert len(return_msg) == 1
    assert return_msg[0]["success"] is False
    assert (
        "ModuleNotFoundError: No module named 'non_existent_pkg_xyz_12345'"
        in return_msg[0]["error"]
    )
    assert "Traceback (most recent call last)" in return_msg[0]["error"]


@pytest.mark.asyncio
async def test_run_worker_loop_in_memory_exception_traceback(tmp_path):
    pfile = tmp_path / "failing_worker_plugin.py"
    pfile.write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="failing_worker_plugin", mode="active")\n'
        "async def handle(ctx):\n"
        '    raise ZeroDivisionError("intentional division by zero")\n'
    )

    init_payload = {
        "plugin_name": "failing_worker_plugin",
        "source_path": str(pfile),
        "chat_id": 999,
        "message": None,
        "params": {},
    }

    in_reader = asyncio.StreamReader()
    in_reader.feed_data(encode_ipc_payload(init_payload).encode("utf-8"))
    in_reader.feed_eof()

    class FakeWriter:
        def __init__(self):
            self.lines = []

        def write(self, data: bytes):
            self.lines.extend(data.decode("utf-8").splitlines())

        async def drain(self):
            pass

    out_writer = FakeWriter()

    await run_worker_loop(reader=in_reader, writer=out_writer)

    decoded = [json.loads(line) for line in out_writer.lines if line.strip()]
    return_msg = [d for d in decoded if d.get("type") == "return"]
    assert len(return_msg) == 1
    assert return_msg[0]["success"] is False
    assert "ZeroDivisionError: intentional division by zero" in return_msg[0]["error"]
    assert "Traceback (most recent call last)" in return_msg[0]["error"]


@pytest.mark.asyncio
async def test_run_worker_loop_host_eof_cancels_pending_rpc(tmp_path):
    pfile = tmp_path / "rpc_hanging_plugin.py"
    pfile.write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="rpc_hanging_plugin", mode="active")\n'
        "async def handle(ctx):\n"
        '    await ctx.reply("will hang")\n'
        "    return True\n"
    )

    init_payload = {
        "plugin_name": "rpc_hanging_plugin",
        "source_path": str(pfile),
        "chat_id": 999,
        "message": {"id": 1},
    }

    in_reader = asyncio.StreamReader()
    # Feed init payload, then EOF immediately without responding to RPC
    in_reader.feed_data(encode_ipc_payload(init_payload).encode("utf-8"))
    in_reader.feed_eof()

    class FakeWriter:
        def __init__(self):
            self.lines = []

        def write(self, data: bytes):
            self.lines.extend(data.decode("utf-8").splitlines())

        async def drain(self):
            pass

    out_writer = FakeWriter()

    await run_worker_loop(reader=in_reader, writer=out_writer)

    decoded = [json.loads(line) for line in out_writer.lines if line.strip()]
    return_msg = [d for d in decoded if d.get("type") == "return"]
    assert len(return_msg) == 1
    assert return_msg[0]["success"] is False
    assert "ConnectionResetError: IPC pipe closed by host" in return_msg[0]["error"]


@pytest.mark.asyncio
async def test_worker_subprocess_end_to_end(tmp_path):
    pfile = tmp_path / "subprocess_plugin.py"
    pfile.write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="subprocess_plugin", mode="active")\n'
        "async def handle(ctx):\n"
        '    ctx.log(msg="logging with kwarg from child process")\n'
        '    rep = await ctx.reply("hi host")\n'
        '    return rep.get("ack") == 1\n'
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tg_signer.core.plugin_worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # 1. send init payload
    init_payload = {
        "plugin_name": "subprocess_plugin",
        "source_path": str(pfile),
        "chat_id": 12345,
        "message": {"id": 1, "text": "ping"},
        "params": {},
    }
    proc.stdin.write(encode_ipc_payload(init_payload).encode("utf-8"))
    await proc.stdin.drain()

    # 2. read outputs from worker
    logs_received = []
    return_payload = None

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        msg = decode_ipc_payload(line.decode("utf-8"))
        if msg.get("type") == "log":
            logs_received.append(msg)
        elif msg.get("type") == "call":
            call_id = msg["id"]
            method = msg["method"]
            assert method == "reply"
            # reply back to worker with call_result
            resp = {
                "type": "call_result",
                "id": call_id,
                "success": True,
                "data": {"ack": 1},
            }
            proc.stdin.write(encode_ipc_payload(resp).encode("utf-8"))
            await proc.stdin.drain()
        elif msg.get("type") == "return":
            return_payload = msg
            break

    await proc.wait()

    assert any(
        "logging with kwarg from child process" in entry["message"]
        for entry in logs_received
    )
    assert return_payload is not None
    assert return_payload["success"] is True
    assert return_payload["result"] is True
