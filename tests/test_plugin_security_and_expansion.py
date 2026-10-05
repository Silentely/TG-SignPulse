"""Unit tests for newly implemented optimizations:
- Subprocess environment sanitization (build_sanitized_worker_env)
- Plugin RPC expansion (media, pin/unpin, get_messages, forward_messages)
- Plugin storage thread-local reuse and batch operations (mget, mset)
- Keyword monitor action 99 (CUSTOM_PLUGIN) execution
- Scheduler range mode large delay DateTrigger delegation
- Same-account task chaining (next_task_on_success)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.scheduler import _job_run_sign_task, _resolve_scheduler_timezone
from backend.services.keyword_monitor.continue_actions import (
    execute_continue_action,
)
from backend.services.sign_task_runner import _runner_trigger_chained_task
from tg_signer.core.plugin_host import (
    PluginProcessHost,
    build_sanitized_worker_env,
)
from tg_signer.core.plugin_ipc import ProxyMessage
from tg_signer.core.plugins import (
    PluginContext,
    PluginMeta,
    PluginRegistry,
    PluginStorageBackend,
    PluginStorageClient,
)

# ============================================================================
# 1. Subprocess Environment Sanitization
# ============================================================================


def test_build_sanitized_worker_env():
    raw_env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "/app/src",
        "LANG": "en_US.UTF-8",
        "PYTEST_CURRENT_TEST": "test_env",
        "APP_SECRET_KEY": "super_secret_jwt_key",
        "ADMIN_PASSWORD": "admin_master_pass",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "DB_URL": "mysql://root:pass@localhost/db",
        "OPENAI_API_KEY": "sk-1234567890",
        "DEEPSEEK_API_KEY": "sk-deepseek",
        "TG_API_HASH": "telegram_hash",
        "PLUGIN_CUSTOM_OPTION": "custom_val",
        "PATHEXT": ".COM;.EXE",
    }

    sanitized = build_sanitized_worker_env(raw_env)

    # Allowed safe variables
    assert sanitized.get("PATH") == "/usr/bin:/bin"
    assert sanitized.get("PYTHONPATH") == "/app/src"
    assert sanitized.get("LANG") == "en_US.UTF-8"
    assert sanitized.get("PYTEST_CURRENT_TEST") == "test_env"
    assert sanitized.get("PLUGIN_CUSTOM_OPTION") == "custom_val"
    assert sanitized.get("PATHEXT") == ".COM;.EXE"

    # Blocked sensitive variables
    assert "APP_SECRET_KEY" not in sanitized
    assert "ADMIN_PASSWORD" not in sanitized
    assert "DATABASE_URL" not in sanitized
    assert "DB_URL" not in sanitized
    assert "OPENAI_API_KEY" not in sanitized
    assert "DEEPSEEK_API_KEY" not in sanitized
    assert "TG_API_HASH" not in sanitized


# ============================================================================
# 2. Plugin Storage Thread-local Connection Reuse & Batch Operations
# ============================================================================


@pytest.mark.asyncio
async def test_plugin_storage_connection_reuse_and_batch_operations(tmp_path):
    db_file = tmp_path / "test_storage.db"
    backend = PluginStorageBackend(db_path=db_file)

    conn = backend._get_conn()
    assert conn is not None
    conn.close()

    # Test mset and mget on backend
    backend.mset(
        "ns1",
        {"k1": "val1", "k2": {"nested": 123}, "k3": 456},
        ttl=100.0,
    )
    res = backend.mget("ns1", ["k1", "k2", "non_existent"])
    assert res["k1"] == "val1"
    assert res["k2"] == {"nested": 123}
    assert "non_existent" not in res

    # Test client async methods
    client = PluginStorageClient("ns1", backend=backend)
    async_res = await client.mget(["k2", "k3"])
    assert async_res == {"k2": {"nested": 123}, "k3": 456}

    await client.mset({"k4": "batch_val4", "k5": "batch_val5"})
    all_keys = await client.keys()
    assert set(all_keys) >= {"k1", "k2", "k3", "k4", "k5"}

    backend.close()


# ============================================================================
# 3. Plugin Context & RPC Telegram API Expansion
# ============================================================================


@pytest.mark.asyncio
async def test_plugin_context_expanded_methods():
    mock_app = MagicMock()
    mock_app.send_photo = AsyncMock(return_value={"id": 101, "chat": {"id": 123}})
    mock_app.send_document = AsyncMock(return_value={"id": 102, "chat": {"id": 123}})
    mock_app.pin_chat_message = AsyncMock(return_value=True)
    mock_app.unpin_chat_message = AsyncMock(return_value=True)
    mock_app.unpin_all_chat_messages = AsyncMock(return_value=True)
    mock_app.get_messages = AsyncMock(return_value=[{"id": 101, "chat": {"id": 123}}])
    mock_app.forward_messages = AsyncMock(
        return_value=[{"id": 201, "chat": {"id": 456}}]
    )

    class FakeMsg:
        id = 99
        chat_id = 123

    ctx = PluginContext(
        app=mock_app,
        chat_id=123,
        message=FakeMsg(),
        message_thread_id=44,
        plugin_name="test_expansion",
    )

    await ctx.send_photo("photo.jpg", caption="test photo")
    mock_app.send_photo.assert_called_once_with(
        123, "photo.jpg", message_thread_id=44, caption="test photo"
    )

    await ctx.send_document("file.pdf", caption="doc")
    mock_app.send_document.assert_called_once_with(
        123, "file.pdf", message_thread_id=44, caption="doc"
    )

    await ctx.pin_message()
    mock_app.pin_chat_message.assert_called_once_with(123, message_id=99)

    await ctx.unpin_message()
    mock_app.unpin_chat_message.assert_called_once_with(123, message_id=99)

    await ctx.get_messages([101])
    mock_app.get_messages.assert_called_once_with(123, message_ids=[101])

    await ctx.forward_messages(chat_id=456)
    mock_app.forward_messages.assert_called_once_with(
        456, from_chat_id=123, message_ids=99
    )


@pytest.mark.asyncio
async def test_proxy_message_convenience_methods():
    mock_rpc = AsyncMock()
    mock_rpc.return_value = {"id": 105, "chat": {"id": 123}}

    msg = ProxyMessage({"id": 100, "text": "hello", "chat": {"id": 123}}, rpc=mock_rpc)
    await msg.reply_photo("photo.png", caption="hi")
    mock_rpc.assert_called_with(
        "send_photo", photo="photo.png", caption="hi", reply_to_message_id=100
    )

    await msg.pin()
    mock_rpc.assert_called_with("pin_message", message_id=100)

    await msg.unpin()
    mock_rpc.assert_called_with("unpin_message", message_id=100)


# ============================================================================
# 4. Keyword Monitor Action 99 (CUSTOM_PLUGIN)
# ============================================================================


@pytest.mark.asyncio
async def test_keyword_monitor_action_99_in_process():
    async def sample_handler(ctx):
        ctx.log("action 99 executed")
        return True

    PluginRegistry._plugins["test_km_plugin_action"] = PluginMeta(
        name="test_km_plugin_action",
        description="Keyword action test",
        handler=sample_handler,
        isolation_mode="in_process",
    )

    mock_service = MagicMock()
    mock_client = MagicMock()
    action = {"action": 99, "plugin_name": "test_km_plugin_action", "params": {"p1": 1}}

    with patch("tg_signer.core.plugin_host.PluginProcessHost") as mock_host:
        mock_host.return_value.execute = AsyncMock(return_value=True)
        success = await execute_continue_action(
            service=mock_service,
            client=mock_client,
            target_chat_id=12345,
            target_thread_id=None,
            action=action,
            timeout=5.0,
        )
        assert success is True
        mock_host.assert_called_once()
        assert mock_host.call_args.kwargs["plugin_name"] == "test_km_plugin_action"
        assert mock_host.call_args.kwargs["trigger_type"] == "reactive"


# ============================================================================
# 5. Task Scheduler Range Mode DateTrigger Delegation
# ============================================================================


@pytest.mark.asyncio
async def test_scheduler_range_large_delay_delegation():
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with (
        patch("backend.scheduler.scheduler", mock_scheduler),
        patch("backend.services.sign_tasks.get_sign_task_service") as mock_get_svc,
        patch("backend.scheduler._get_range_window") as mock_get_window,
    ):
        mock_svc = MagicMock()
        mock_svc.get_task.return_value = {
            "execution_mode": "range",
            "range_start": "10:00",
            "range_end": "12:00",
        }
        mock_get_svc.return_value = mock_svc

        tz = _resolve_scheduler_timezone()
        now = datetime.now(tz) if tz is not None else datetime.now()
        start_dt = now - timedelta(minutes=10)
        end_dt = now + timedelta(minutes=110)
        mock_get_window.return_value = (start_dt, end_dt)

        with patch("random.uniform", return_value=120.0):
            await _job_run_sign_task("acc1", "task1", is_direct=False)

        # Expected: scheduler.add_job called with DateTrigger because delay 120s > 45s
        assert mock_scheduler.add_job.called
        assert mock_scheduler.add_job.call_args.kwargs.get("args") == [
            "acc1",
            "task1",
            True,
        ]
        assert (
            "range-oneshot-acc1-task1"
            in mock_scheduler.add_job.call_args.kwargs.get("id", "")
        )


# ============================================================================
# 6. Task Chaining within Same Account (next_task_on_success)
# ============================================================================


@pytest.mark.asyncio
async def test_sign_task_chained_execution_on_success():
    mock_svc = MagicMock()
    mock_svc.get_task.return_value = {"name": "second_task", "enabled": True}
    mock_svc.start_task_run = AsyncMock()

    state = {
        "svc": mock_svc,
        "account_name": "my_account",
        "task_name": "first_task",
        "task_cfg": {
            "next_task_on_success": "second_task",
            "next_task_delay_seconds": 0.01,
        },
    }

    await _runner_trigger_chained_task(state)

    # Let the background chained task execute
    await asyncio.sleep(0.05)

    mock_svc.start_task_run.assert_called_once_with(
        "my_account", "second_task", visited_chain=["first_task"]
    )


# ============================================================================
# 7. Task Chaining in Config Build & CRUD
# ============================================================================


def test_task_chaining_config_build_and_crud(tmp_path):
    from backend.services.sign_task_config_build import (
        build_sign_task_config,
        resolve_update_field_values,
    )

    cfg = build_sign_task_config(
        account_name="acc1",
        account_names=["acc1"],
        next_task_on_success="task_beta",
        next_task_delay_seconds=5.0,
    )
    assert cfg["next_task_on_success"] == "task_beta"
    assert cfg["next_task_delay_seconds"] == 5.0

    updated = resolve_update_field_values(
        cfg,
        next_task_on_success="task_gamma",
        next_task_delay_seconds=10.0,
    )
    assert updated["next_task_on_success"] == "task_gamma"
    assert updated["next_task_delay_seconds"] == 10.0


# ============================================================================
# 8. Regression tests for Code Review Fixes
# ============================================================================


def test_continue_actions_includes_action_99():
    from backend.services.keyword_monitor.continue_actions import continue_actions

    raw_action = {
        "continue_actions": [
            {"action": 1, "text": "hello"},
            {"action": 99, "plugin_name": "my_plugin"},
            {"action": 888, "invalid": True},
        ]
    }
    filtered = continue_actions(raw_action)
    action_ids = [item["action"] for item in filtered]
    assert 1 in action_ids
    assert 99 in action_ids
    assert 888 not in action_ids


def test_mset_string_value_preservation(tmp_path):
    db_file = tmp_path / "test_mset_str.db"
    backend = PluginStorageBackend(db_path=db_file)

    backend.mset("test_ns", {"num_str": "1", "bool_str": "true", "null_str": "null"})
    res = backend.mget("test_ns", ["num_str", "bool_str", "null_str"])
    assert res["num_str"] == "1"
    assert isinstance(res["num_str"], str)
    assert res["bool_str"] == "true"
    assert isinstance(res["bool_str"], str)
    assert res["null_str"] == "null"
    assert isinstance(res["null_str"], str)


def test_build_sanitized_worker_env_extended_credentials():
    raw_env = {
        "PATH": "/bin",
        "COHERE_API_KEY": "cohere_token_123",
        "MISTRAL_API_KEY": "mistral_token_456",
        "PERPLEXITY_API_KEY": "pplx_key_789",
        "CUSTOM_APP_SECRET": "very_secret",
        "USER_LOGIN_PWD": "pwd123",
        "THIRD_PARTY_TOKEN": "token_abc",
        "PLUGIN_ALLOWED_KEY": "safe_plugin_option",
    }
    sanitized = build_sanitized_worker_env(raw_env)
    assert "COHERE_API_KEY" not in sanitized
    assert "MISTRAL_API_KEY" not in sanitized
    assert "PERPLEXITY_API_KEY" not in sanitized
    assert "CUSTOM_APP_SECRET" not in sanitized
    assert "USER_LOGIN_PWD" not in sanitized
    assert "THIRD_PARTY_TOKEN" not in sanitized
    assert sanitized.get("PATH") == "/bin"
    assert sanitized.get("PLUGIN_ALLOWED_KEY") == "safe_plugin_option"


def test_plugin_registry_isolation_mode():
    PluginRegistry._plugins.clear()

    @PluginRegistry.register(name="test_in_proc", isolation_mode="in_process")
    async def sample_fn(ctx):
        pass

    meta = PluginRegistry.get("test_in_proc")
    assert meta is not None
    assert meta.isolation_mode == "in_process"


@pytest.mark.asyncio
async def test_dynamic_chain_cycle_detection():
    mock_svc = MagicMock()
    mock_svc.get_task.return_value = {"name": "task_b", "enabled": True}
    mock_svc.start_task_run = AsyncMock()

    # task_b pointing back to task_a when task_a is already in visited_chain
    state = {
        "svc": mock_svc,
        "account_name": "acc",
        "task_name": "task_b",
        "task_cfg": {
            "next_task_on_success": "task_a",
            "next_task_delay_seconds": 0.01,
        },
        "visited_chain": ["task_a"],
    }

    await _runner_trigger_chained_task(state)
    await asyncio.sleep(0.02)
    # Since task_a was already visited, trigger should abort and not start task_a
    mock_svc.start_task_run.assert_not_called()


def test_static_chain_cycle_detection():
    from backend.services.sign_task_crud import SignTaskCrudMixin

    class DummyCrud(SignTaskCrudMixin):
        def get_task(self, name, account_name=None, aggregate=False):
            if name == "task_b":
                return {"name": "task_b", "next_task_on_success": "task_c"}
            if name == "task_c":
                return {"name": "task_c", "next_task_on_success": "task_a"}
            return None

    crud = DummyCrud()
    # task_a -> task_b -> task_c -> task_a should raise ValueError
    with pytest.raises(ValueError, match="循环引用"):
        crud._validate_task_chain(["acc1"], "task_a", "task_b")

    # task_a -> task_a should raise ValueError
    with pytest.raises(ValueError, match="自调用"):
        crud._validate_task_chain(["acc1"], "task_a", "task_a")


@pytest.mark.asyncio
async def test_scheduler_skips_disabled_task():
    mock_scheduler = MagicMock()
    with (
        patch("backend.scheduler.scheduler", mock_scheduler),
        patch("backend.services.sign_tasks.get_sign_task_service") as mock_get_svc,
    ):
        mock_svc = MagicMock()
        mock_svc.get_task.return_value = {"enabled": False}
        mock_get_svc.return_value = mock_svc

        await _job_run_sign_task("acc1", "task1", is_direct=True)
        # Should not start task run if disabled
        mock_svc.start_task_run.assert_not_called()


def test_remove_sign_task_job_cleans_oneshots():
    from backend.scheduler import remove_sign_task_job

    mock_scheduler = MagicMock()
    job1 = MagicMock(id="sign-acc1-task1")
    job2 = MagicMock(id="range-oneshot-acc1-task1-123456")
    job3 = MagicMock(id="range-oneshot-acc2-other-123456")
    mock_scheduler.get_jobs.return_value = [job1, job2, job3]
    mock_scheduler.get_job.side_effect = lambda jid: (
        job1 if jid == "sign-acc1-task1" else None
    )

    with (
        patch("backend.scheduler.scheduler", mock_scheduler),
        patch("backend.scheduler.instance_lock.has_scheduler_lock", return_value=True),
    ):
        remove_sign_task_job("acc1", "task1")

        mock_scheduler.remove_job.assert_any_call("sign-acc1-task1")
        mock_scheduler.remove_job.assert_any_call("range-oneshot-acc1-task1-123456")


@pytest.mark.asyncio
async def test_action_99_respects_disabled_plugin():
    from backend.services.keyword_monitor.continue_actions import (
        execute_custom_plugin_continue_action,
    )
    from tg_signer.core.plugins import PluginMeta, PluginRegistry

    plugin_name = "test_disabled_plugin_cr"
    meta = PluginMeta(
        name=plugin_name,
        description="test",
        handler=AsyncMock(),
        version="1.0.0",
        enabled=True,
    )
    PluginRegistry._plugins[plugin_name] = meta
    PluginRegistry.set_disabled(plugin_name, True)

    try:
        res = await execute_custom_plugin_continue_action(
            service=MagicMock(),
            client=MagicMock(),
            target_chat_id=12345,
            target_thread_id=None,
            action={"action": 99, "plugin_name": plugin_name},
        )
        assert res is False
    finally:
        PluginRegistry._plugins.pop(plugin_name, None)
        PluginRegistry._disabled_plugins.discard(plugin_name)


def test_mget_chunking_large_keys(tmp_path):
    backend = PluginStorageBackend(db_path=str(tmp_path / "storage.db"))
    # Write 1200 keys
    large_map = {f"key_{i}": f"val_{i}" for i in range(1200)}
    backend.mset("test_chunk", large_map)

    # Read back all 1200 keys
    res = backend.mget("test_chunk", list(large_map.keys()))
    assert len(res) == 1200
    assert res["key_0"] == "val_0"
    assert res["key_1199"] == "val_1199"


def test_env_sanitizer_preserves_data_directories():
    raw_env = {
        "PATH": "/bin",
        "APP_DATA_DIR": "/var/app_data",
        "TG_SIGNER_DATA_DIR": "/var/tg_data",
        "PLUGINS_DIR": "/var/plugins",
        "BUILTIN_PLUGINS_DIR": "/var/builtin",
        "PLUGIN_ISOLATION_ENGINE": "auto",
        "SECRET_TOKEN": "sensitive",
    }
    sanitized = build_sanitized_worker_env(raw_env)
    assert sanitized.get("APP_DATA_DIR") == "/var/app_data"
    assert sanitized.get("TG_SIGNER_DATA_DIR") == "/var/tg_data"
    assert sanitized.get("PLUGINS_DIR") == "/var/plugins"
    assert sanitized.get("BUILTIN_PLUGINS_DIR") == "/var/builtin"
    assert sanitized.get("PLUGIN_ISOLATION_ENGINE") == "auto"
    assert "SECRET_TOKEN" not in sanitized


def test_compute_range_compensation_skips_when_oneshot_pending():
    from datetime import datetime

    from backend.scheduler import _compute_range_task_compensation

    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    job_oneshot = MagicMock(id="range-oneshot-acc1-task_range-123")
    mock_scheduler.get_jobs.return_value = [job_oneshot]

    cfg = {
        "name": "task_range",
        "account_name": "acc1",
        "execution_mode": "range",
        "range_start": "00:00",
        "range_end": "23:59",
    }

    with patch("backend.scheduler.scheduler", mock_scheduler):
        dt = _compute_range_task_compensation(cfg, now=datetime(2026, 1, 1, 12, 0))
        assert dt is None


class TestForwardMessagesSessionBoundary:
    """forward_messages 不得越会话：源会话固定为触发会话，message_ids 仅限触发消息。"""

    @staticmethod
    def _ctx(chat_id=123, message_id=99):
        class FakeMsg:
            id = message_id

        return SimpleNamespace(chat_id=chat_id, message=FakeMsg())

    def test_plugin_supplied_from_chat_id_is_discarded(self):
        params = PluginProcessHost._resolve_forward_params(
            self._ctx(), {"from_chat_id": -100999, "message_ids": 99}
        )
        assert params["from_chat_id"] == 123
        assert params["message_ids"] == 99

    def test_default_message_ids_is_trigger_message(self):
        params = PluginProcessHost._resolve_forward_params(self._ctx(), {})
        assert params["message_ids"] == 99
        assert params["from_chat_id"] == 123

    def test_single_element_trigger_list_is_accepted(self):
        params = PluginProcessHost._resolve_forward_params(
            self._ctx(), {"message_ids": [99]}
        )
        assert params["message_ids"] == [99]

    def test_non_trigger_message_ids_is_rejected(self):
        with pytest.raises(ValueError, match="仅允许转发触发消息本身"):
            PluginProcessHost._resolve_forward_params(
                self._ctx(), {"message_ids": [99, 100]}
            )

        with pytest.raises(ValueError, match="仅允许转发触发消息本身"):
            PluginProcessHost._resolve_forward_params(
                self._ctx(), {"message_ids": 12345}
            )

    def test_missing_trigger_message_is_rejected(self):
        ctx = SimpleNamespace(chat_id=123, message=None)
        with pytest.raises(ValueError, match="没有有效消息 ID"):
            PluginProcessHost._resolve_forward_params(ctx, {})

    def test_other_params_pass_through(self):
        params = PluginProcessHost._resolve_forward_params(
            self._ctx(), {"message_ids": 99, "disable_notification": True}
        )
        assert params["disable_notification"] is True
        assert "from_chat_id" in params
