from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_signer.config import (
    SendTextAction,
    SignChatV3,
    SupportAction,
)
from tg_signer.core.context import UserSignerWorkerContext
from tg_signer.core.signer_runner import SignerRunnerMixin


class BaselineSigner(SignerRunnerMixin):
    def __init__(self):
        self.app = MagicMock()
        self.app.get_chat = AsyncMock()
        self.me = MagicMock()
        self.me.phone_number = "+123456789"
        self.me.username = "test_user"
        self.me.first_name = "Test"
        self._account = "account_demo"
        self.tasks_dir = MagicMock()
        self.context = UserSignerWorkerContext(
            sign_chats={},
            chat_messages={},
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

    async def wait_for(self, chat, action, next_action=None):
        return True


@pytest.mark.asyncio
async def test_baseline_linear_execution_dual_keys_and_progress():
    """Task 0 Baseline: Linear action flow records int/str dual keys in step_outputs."""
    signer = BaselineSigner()
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(action=SupportAction.SEND_TEXT, text="Step 1"),
            SendTextAction(action=SupportAction.SEND_TEXT, text="Step 2"),
        ],
    )

    recorded_next_actions = []

    async def mock_wait_for(c, a, next_action=None):
        recorded_next_actions.append(next_action)
        return True

    signer.wait_for = mock_wait_for

    with patch("tg_signer.core.workflow_engine.WorkflowEngine.run") as mock_engine_run:
        await signer.sign_a_chat(chat)
        # Assert WorkflowEngine.run is NEVER called for linear chats
        mock_engine_run.assert_not_called()

    # Assert dual keys exist in step_outputs for 1-based indexing
    assert 1 in signer.context.step_outputs
    assert "1" in signer.context.step_outputs
    assert signer.context.step_outputs[1] == {"output": "Step 1"}
    assert signer.context.step_outputs["1"] == {"output": "Step 1"}

    assert 2 in signer.context.step_outputs
    assert "2" in signer.context.step_outputs
    assert signer.context.step_outputs[2] == {"output": "Step 2"}
    assert signer.context.step_outputs["2"] == {"output": "Step 2"}

    assert signer.context.last_output == "Step 2"

    # Assert next_action was correctly passed (Step 1 had Step 2, Step 2 had None)
    assert len(recorded_next_actions) == 2
    assert recorded_next_actions[0] is not None
    assert recorded_next_actions[0].text == "Step 2"
    assert recorded_next_actions[1] is None

    # Assert contexts were set and cleared
    assert len(signer.action_contexts) == 2
    assert signer.cleared_contexts >= 2


@pytest.mark.asyncio
async def test_baseline_stop_after_current_action():
    """Task 0 Baseline: stop_after_current_action stops linear execution early."""
    signer = BaselineSigner()
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(action=SupportAction.SEND_TEXT, text="Step 1"),
            SendTextAction(action=SupportAction.SEND_TEXT, text="Step 2"),
        ],
    )

    executed = []

    async def mock_wait_for(c, a, next_action=None):
        executed.append(a.text)
        if a.text == "Step 1":
            signer.context.stop_after_current_action = True
            signer.context.stop_reason = "Manual stop"
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert executed == ["Step 1"]
    assert 1 in signer.context.step_outputs
    assert 2 not in signer.context.step_outputs
    assert signer.context.stop_after_current_action is False


@pytest.mark.asyncio
async def test_baseline_transient_error_retry_step():
    """Task 0 Baseline: Transient errors trigger retry within step (2 attempts total)."""
    signer = BaselineSigner()
    chat = SignChatV3(
        chat_id=12345,
        name="test_group",
        actions=[
            SendTextAction(action=SupportAction.SEND_TEXT, text="Retry me"),
        ],
    )

    attempt_count = 0

    async def mock_wait_for(c, a, next_action=None):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise TimeoutError("Transient network timeout")
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert attempt_count == 2  # 1 failure + 1 retry success
    assert signer.context.step_outputs[1] == {"output": "Retry me"}
    assert any("瞬时错误" in log[1] for log in signer.logs)


@pytest.mark.asyncio
async def test_workflow_chat_execution_success_path():
    from tg_signer.config import WorkflowStepConfig

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Hello step 1"},
        next_step_id="s2",
    )
    step2 = WorkflowStepConfig(
        step_id="s2",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Hello step 2"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1, step2],
        initial_step_id="s1",
    )

    await signer.sign_a_chat(chat)

    assert getattr(signer.context, "workflow_path", None) == ["s1", "s2"]
    assert "s1" in signer.context.step_outputs
    assert "s2" in signer.context.step_outputs
    assert signer.context.step_outputs["s1"] == {"output": "Hello step 1"}
    assert signer.context.step_outputs["s2"] == {"output": "Hello step 2"}


@pytest.mark.asyncio
async def test_workflow_chat_execution_branching_on_failure():
    from tg_signer.config import WorkflowStepConfig

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Failing step"},
        next_step_id="COMPLETE",
        on_failure_step_id="s_fallback",
    )
    step_fallback = WorkflowStepConfig(
        step_id="s_fallback",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Fallback step"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1, step_fallback],
        initial_step_id="s1",
    )

    async def mock_wait_for(c, a, next_action=None):
        if getattr(a, "text", "") == "Failing step":
            return False
        return True

    signer.wait_for = mock_wait_for

    await signer.sign_a_chat(chat)

    assert getattr(signer.context, "workflow_path", None) == ["s1", "s_fallback"]
    assert "s_fallback" in signer.context.step_outputs
    assert signer.context.step_outputs["s_fallback"] == {"output": "Fallback step"}


@pytest.mark.asyncio
async def test_workflow_chat_execution_terminates_on_fail():
    from tg_signer.config import WorkflowStepConfig

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Failing step"},
        next_step_id="COMPLETE",
        on_failure_step_id="FAIL",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1],
        initial_step_id="s1",
    )

    async def mock_wait_for(c, a, next_action=None):
        return False

    signer.wait_for = mock_wait_for

    with pytest.raises(RuntimeError) as exc_info:
        await signer.sign_a_chat(chat)
    assert "工作流" in str(exc_info.value) and "失败" in str(exc_info.value)
    assert getattr(signer.context, "workflow_path", None) == ["s1"]


@pytest.mark.asyncio
async def test_workflow_chat_stop_after_current_action():
    from tg_signer.config import WorkflowStepConfig

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Step 1"},
        next_step_id="s2",
    )
    step2 = WorkflowStepConfig(
        step_id="s2",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Step 2"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1, step2],
        initial_step_id="s1",
    )

    async def mock_wait_for(c, a, next_action=None):
        signer.context.stop_after_current_action = True
        return True

    signer.wait_for = mock_wait_for

    await signer.sign_a_chat(chat)
    assert getattr(signer.context, "workflow_path", None) == ["s1"]
    assert "s2" not in signer.context.step_outputs


@pytest.mark.asyncio
async def test_workflow_step_continue_on_error_follows_success_branch():
    from tg_signer.config import WorkflowStepConfig

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "best effort", "continue_on_error": True},
        next_step_id="s2",
        on_failure_step_id="FAIL",
    )
    step2 = WorkflowStepConfig(
        step_id="s2",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "continued"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1, step2],
        initial_step_id="s1",
    )

    async def mock_wait_for(c, action, next_action=None):
        if getattr(action, "text", "") == "best effort":
            return False
        return True

    signer.wait_for = mock_wait_for
    await signer.sign_a_chat(chat)

    assert getattr(signer.context, "workflow_path", None) == ["s1", "s2"]


@pytest.mark.asyncio
async def test_workflow_uses_task_retry_count_for_whole_run():
    from tg_signer.config import WorkflowStepConfig
    from tg_signer.context_vars import task_retry_count_var

    signer = BaselineSigner()
    step = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "retry workflow"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step],
        initial_step_id="s1",
    )

    attempts = 0

    async def mock_wait_for(c, action, next_action=None):
        nonlocal attempts
        attempts += 1
        return attempts > 1

    signer.wait_for = mock_wait_for
    token = task_retry_count_var.set(2)
    try:
        await signer.sign_a_chat(chat)
    finally:
        task_retry_count_var.reset(token)

    assert attempts == 2
    assert getattr(signer.context, "workflow_path", None) == ["s1"]


@pytest.mark.asyncio
async def test_workflow_chat_loop_exceeded_error_bubbles_up():
    from tg_signer.config import WorkflowStepConfig
    from tg_signer.core.workflow_engine import WorkflowLoopExceededError

    signer = BaselineSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "Loop step"},
        next_step_id="s1",
        allow_loop=True,
        max_retries=1,
    )
    chat = SignChatV3(
        chat_id=12345,
        name="test_wf_group",
        steps=[step1],
        initial_step_id="s1",
    )

    with pytest.raises(WorkflowLoopExceededError):
        await signer.sign_a_chat(chat)
    assert getattr(signer.context, "workflow_path", None) == ["s1", "s1"]


class _IndexCapturingSigner(BaselineSigner):
    """记录 _set_current_action_context 的 index 与 _resolve_action_delay 的 fallback。"""

    def __init__(self):
        super().__init__()
        self.indexes = []
        self.delay_intervals = []

    def _set_current_action_context(self, index, total, action):
        self.indexes.append((index, total))
        return super()._set_current_action_context(index, total, action)

    def _resolve_action_delay(self, action, interval):
        self.delay_intervals.append(interval)
        return 0.0


@pytest.mark.asyncio
async def test_workflow_step_index_and_numeric_keys_are_one_based():
    """回归：工作流步骤序号与 step_outputs 数字键必须从 1 开始，且首步不施加间隔延迟。"""
    from tg_signer.config import WorkflowStepConfig

    signer = _IndexCapturingSigner()
    step1 = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "first"},
        next_step_id="s2",
    )
    step2 = WorkflowStepConfig(
        step_id="s2",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "second"},
        next_step_id="COMPLETE",
    )
    chat = SignChatV3(
        chat_id=12345,
        name="wf_index",
        steps=[step1, step2],
        initial_step_id="s1",
    )

    await signer.sign_a_chat(chat)

    assert signer.indexes == [(1, 2), (2, 2)]
    # 数字键 1-based；首步写入键 1/"1"，第二步写入键 2/"2"
    assert signer.context.step_outputs[1] == {"output": "first"}
    assert signer.context.step_outputs["1"] == {"output": "first"}
    assert signer.context.step_outputs[2] == {"output": "second"}
    assert signer.context.step_outputs["2"] == {"output": "second"}
    # action_interval 仅在第二步起生效（首步 fallback 为 0）
    assert signer.delay_intervals == [0.0, 1.0]
