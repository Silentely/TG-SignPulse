from __future__ import annotations

from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.config import (
    PluginAction,
    SignChatV3,
    SignConfigV3,
)
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.plugin_runtime import (
    PluginErrorTier,
    PluginResult,
    TestMockAdapter,
    set_plugin_runtime,
)
from tg_signer.core.plugins import (
    PluginAccountUnavailableError,
    PluginMeta,
    PluginRegistry,
)
from tg_signer.core.signer_actions import SignerActionsMixin
from tg_signer.core.signer_runner import SignerRunnerMixin


class RunnerMockSigner(SignerRunnerMixin, SignerActionsMixin):
    def __init__(self, account: str = "account_demo", task_name: str = "demo_task"):
        self.app = MagicMock()
        self.app.get_chat = AsyncMock()
        self.me = MagicMock()
        self.me.phone_number = "+123456789"
        self.me.username = "test_user"
        self.me.first_name = "Test"
        self._account = account
        self._task_name = task_name
        self.tasks_dir = MagicMock()
        self.context = UserSignerWorkerContext(
            sign_chats=defaultdict(list),
            chat_messages=defaultdict(dict),
        )
        self.logs = []
        self.action_contexts = []
        self.cleared_contexts = 0

    def log(self, msg, level="INFO"):
        self.logs.append((level, msg))

    def _describe_chat_run(self, chat):
        return f"Running chat {chat.chat_id}"

    def _set_current_action_context(self, index, total, action):
        desc = f"Action {index}/{total}: {getattr(action.action, 'desc', str(action.action))}"
        self.action_contexts.append((index, total, desc))
        return desc

    def _current_action_step_label(self):
        return "[Step]"

    def _resolve_action_delay(self, action, interval):
        return 0.0

    def _clear_current_action_context(self):
        self.cleared_contexts += 1

    def _is_transient_step_error(self, exc):
        return isinstance(exc, TimeoutError)


@pytest.mark.asyncio
async def test_runner_run_config_chats_account_unavailable_aborts_and_notifies():
    """Runner 层断言：账号不可用落 aborted/failed 结果，而不是 completed/success，且包含 stop_reason 并发送告警。"""
    PluginRegistry._plugins["account_unavail_runner_test"] = PluginMeta(
        name="account_unavail_runner_test",
        handler=lambda ctx: True,
        mode="active",
        description="",
        version="1.0.0",
        updated_at="2026-11-07",
        author="tester",
        source_path="",
        params_schema=[],
        context_version=2,
    )

    runner = RunnerMockSigner(account="tester_acc", task_name="test_sign_task")
    action = PluginAction(plugin_name="account_unavail_runner_test", mode="active")
    chat = SignChatV3(chat_id=123456, actions=[action])
    config = SignConfigV3(chats=[chat], sign_at="08:00:00", sign_interval=0)

    mock_runtime = TestMockAdapter()
    mock_runtime.mock_results["account_unavail_runner_test"] = PluginResult(
        success=False,
        error="RPCError: 400 YOU_BLOCKED_USER",
        error_tier=PluginErrorTier.ACCOUNT_UNAVAILABLE,
        should_break=False,
    )
    set_plugin_runtime(mock_runtime)

    alert_mock = AsyncMock()
    runner.account_unavailable_alert_handler = alert_mock

    try:
        targets = await runner._run_config_chats(config)

        # 1. 断言 targets 结果必须不是 success/completed，而是明确的 aborted 状态与 failed 业务结果
        assert len(targets) == 1
        target = targets[0]
        assert target["execution_status"] == "aborted"
        assert target["business_status"] == "failed"
        assert target["failure_category"] == "account_unavailable"
        assert target["retry_safe"] is False

        # 2. 断言 stop_reason 出现在结果中
        assert target["stop_reason"] is not None
        assert "account_unavailable" in target["stop_reason"]
        assert "YOU_BLOCKED_USER" in target["stop_reason"]

        # 3. 断言 runner 上下文聚合状态为 failed 且记录 stop_reason
        assert runner.context.aggregate_status == "failed"
        assert runner.context.business_status == "failed"
        assert runner.context.account_unavailable is True
        assert "account_unavailable" in runner.context.stop_reason

        # 4. 断言触发了现有告警通道（_send_account_unavailable_alert）
        alert_mock.assert_awaited_once()
        alert_args = alert_mock.call_args[1]
        assert alert_args["account_name"] == "tester_acc"
        assert alert_args["task_name"] == "test_sign_task"
        assert "account_unavailable" in alert_args["message"]
    finally:
        set_plugin_runtime(None)


@pytest.mark.asyncio
async def test_runner_sign_a_chat_does_not_retry_on_account_unavailable(monkeypatch):
    """Runner 层断言：sign_a_chat 遇到账号不可用时立即中止，不进行流程重试。"""
    PluginRegistry._plugins["account_unavail_no_retry"] = PluginMeta(
        name="account_unavail_no_retry",
        handler=lambda ctx: True,
        mode="active",
        description="",
        version="1.0.0",
        updated_at="2026-11-07",
        author="tester",
        source_path="",
        params_schema=[],
        context_version=2,
    )

    runner = RunnerMockSigner()
    action = PluginAction(plugin_name="account_unavail_no_retry", mode="active")
    chat = SignChatV3(chat_id=999999, actions=[action])

    monkeypatch.setenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "3")

    call_count = 0
    orig_wait_for = runner.wait_for

    async def counting_wait_for(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await orig_wait_for(*args, **kwargs)

    runner.wait_for = counting_wait_for

    mock_runtime = TestMockAdapter()
    mock_runtime.mock_results["account_unavail_no_retry"] = PluginResult(
        success=False,
        error="RPCError: 401 SESSION_REVOKED",
        error_tier=PluginErrorTier.ACCOUNT_UNAVAILABLE,
        should_break=False,
    )
    set_plugin_runtime(mock_runtime)

    try:
        with pytest.raises(PluginAccountUnavailableError) as exc_info:
            await runner.sign_a_chat(chat)

        assert "SESSION_REVOKED" in str(exc_info.value)
        # 即使配置了 3 次重试，遇到账号不可用也仅执行 1 次，严禁死循环重试
        assert call_count == 1
        assert runner.context.account_unavailable is True
        assert "account_unavailable" in runner.context.stop_reason
    finally:
        set_plugin_runtime(None)
