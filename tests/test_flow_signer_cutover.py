# tests/test_flow_signer_cutover.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_signer.config import (
    SendTextAction,
    SignChatV3,
)
from tg_signer.context_vars import task_retry_count_var
from tg_signer.core.runtime import UserSigner


@pytest.mark.asyncio
async def test_user_signer_pulseflow_cutover():
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.log = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)

    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
    )

    with patch.dict("os.environ", {"USE_PULSEFLOW_ENGINE": "1"}):
        result = await signer.sign_a_chat(chat)
        assert result is True
        assert signer.wait_for.call_count == 1
        # 验证输出执行引擎日志
        log_msgs = [call[0][0] for call in signer.log.call_args_list]
        assert any("PulseFlow (v4)" in m and "env" in m for m in log_msgs)


@pytest.mark.asyncio
async def test_user_signer_task_override_cutover():
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.log = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)

    # 任务级显式指定 execution_engine="v4"
    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
        execution_engine="v4",
    )

    with patch.dict("os.environ", {"USE_PULSEFLOW_ENGINE": "0"}):
        result = await signer.sign_a_chat(chat)
        assert result is True
        assert signer.wait_for.call_count == 1
        log_msgs = [call[0][0] for call in signer.log.call_args_list]
        assert any("PulseFlow (v4)" in m and "task" in m for m in log_msgs)


@pytest.mark.asyncio
async def test_user_signer_pulseflow_failure_raises_runtime_error():
    # 核心契约防线：当任务显式指定 v4 且未配置降级时，PulseFlow 失败必须抛出 RuntimeError
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.log = MagicMock()
    # 模拟 wait_for 返回 False 且未配置容错
    signer.wait_for = AsyncMock(return_value=False)

    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
        execution_engine="v4",
    )

    with pytest.raises(RuntimeError, match="PulseFlow 执行失败"):
        await signer.sign_a_chat(chat)


@pytest.mark.asyncio
async def test_user_signer_pulseflow_honors_task_retry_count():
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.log = MagicMock()
    attempts = 0

    async def wait_for(chat, action, next_action=None):
        nonlocal attempts
        attempts += 1
        return attempts > 1

    signer.wait_for = wait_for
    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
        execution_engine="v4",
    )
    token = task_retry_count_var.set(2)
    try:
        result = await signer.sign_a_chat(chat)
    finally:
        task_retry_count_var.reset(token)

    assert result is True
    assert attempts == 2


@pytest.mark.asyncio
async def test_user_signer_pulseflow_clears_stale_legacy_context():
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.context.chat_messages = {}
    signer.context.last_output = "STALE previous chat output"
    signer.context.last_received_text = "STALE previous message"
    signer.log = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)
    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping", skip_if_matched="STALE")],
        execution_engine="v4",
    )

    result = await signer.sign_a_chat(chat)

    assert result is True
    signer.wait_for.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_signer_pulseflow_auto_fallback_on_engine_error():
    """上线不脱钩保障：当系统全局/金丝雀切流命中 v4 时，若引擎异常，自动安全降级至经典引擎继续执行"""
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.context.chat_messages = {}
    signer.log = MagicMock()

    # 模拟 v4 尝试时 wait_for 失败，但后续降级到经典流程时 wait_for 成功
    call_counts = 0

    async def dynamic_wait_for(chat, action, next_action=None):
        nonlocal call_counts
        call_counts += 1
        # 第一次在 v4 运行失败触发异常，降级到 actions 经典引擎重跑时成功
        if call_counts == 1:
            return False
        return True

    signer.wait_for = dynamic_wait_for

    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
        # 未显式指定 execution_engine，由环境变量全局切流
    )

    with patch.dict("os.environ", {"USE_PULSEFLOW_ENGINE": "1"}):
        result = await signer.sign_a_chat(chat)
        assert result is True or result is None
        # 验证产生了降级警告日志
        log_msgs = [call[0][0] for call in signer.log.call_args_list]
        assert any("启动安全兜底机制" in m and "降级" in m for m in log_msgs)
        # 验证 context 中记录了降级发生
        assert getattr(signer.context, "pulseflow_fallback_occurred", False) is True


@pytest.mark.asyncio
async def test_user_signer_pulseflow_syncs_context_and_metrics_on_success():
    """上线不脱钩保障：v4 执行成功后，输出文本与指标完整回填至 runner.context，供下游通知使用"""
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.context.chat_messages = {}
    signer.log = MagicMock()

    async def fake_wait_for(chat, action, next_action=None):
        signer.context.last_output = "签到成功！获得 10 积分"
        return True

    signer.wait_for = fake_wait_for

    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/checkin")],
        execution_engine="v4",
    )

    result = await signer.sign_a_chat(chat)
    assert result is True
    # 验证上下文成功回填
    assert signer.context.last_output == "签到成功！获得 10 积分"
    assert signer.context.last_received_text == "签到成功！获得 10 积分"
    assert hasattr(signer.context, "flow_metrics")
    assert signer.context.flow_metrics["succeeded_steps"] == 1


@pytest.mark.asyncio
async def test_user_signer_pulseflow_action_context_progress_wiring():
    """步骤进度与日志标记去重保障：节点执行前后正确设置并清理动作上下文"""
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.context.chat_messages = {}
    signer.log = MagicMock()
    signer._set_current_action_context = MagicMock()
    signer._clear_current_action_context = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)

    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping")],
        execution_engine="v4",
    )

    result = await signer.sign_a_chat(chat)
    assert result is True
    signer._set_current_action_context.assert_called_once()
    signer._clear_current_action_context.assert_called_once()


@pytest.mark.asyncio
async def test_user_signer_pulseflow_skips_retry_after_side_effect():
    """首次动作已产生外部副作用时，整流程不得重试，避免重复发送。"""
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = MagicMock()
    signer.log = MagicMock()
    calls = 0

    async def wait_for(chat, action, next_action=None):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("second action failed")
        return True

    signer.wait_for = wait_for
    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/ping"), SendTextAction(text="/pong")],
        execution_engine="v4",
    )
    token = task_retry_count_var.set(3)
    try:
        with pytest.raises(RuntimeError):
            await signer.sign_a_chat(chat)
    finally:
        task_retry_count_var.reset(token)

    assert calls == 2


@pytest.mark.asyncio
async def test_user_signer_worker_context_real_instance_pulseflow_fields():
    """验证真实 UserSignerWorkerContext 实例在 PulseFlow 执行时赋字段不会抛出 Pydantic 字段缺失错误。"""
    from tg_signer.core.context import UserSignerWorkerContext

    real_ctx = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    # 验证字段默认值与写入
    assert real_ctx.pulseflow_side_effect_started is False
    assert real_ctx.pulseflow_fallback_occurred is False
    assert real_ctx.pulseflow_fallback_reason is None

    real_ctx.pulseflow_side_effect_started = True
    real_ctx.pulseflow_fallback_occurred = True
    real_ctx.pulseflow_fallback_reason = "norm error"
    assert real_ctx.pulseflow_side_effect_started is True
    assert real_ctx.pulseflow_fallback_occurred is True
    assert real_ctx.pulseflow_fallback_reason == "norm error"

    # 验证支持动态 extra 字段（如 flow_metrics 等）
    real_ctx.flow_metrics = {"steps": 1}
    assert real_ctx.flow_metrics["steps"] == 1


@pytest.mark.asyncio
async def test_pulseflow_runner_populates_workflow_path_and_steps():
    """验证 PulseFlow 执行成功后，workflow_path 和 workflow_steps 回填到 signer.context。"""
    from tg_signer.core.context import UserSignerWorkerContext

    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer.log = MagicMock()

    async def wait_for(chat, action, next_action=None):
        return True

    signer.wait_for = wait_for
    chat = SignChatV3(
        chat_id=88888,
        actions=[SendTextAction(text="/step1"), SendTextAction(text="/step2")],
        execution_engine="v4",
    )

    res = await signer.sign_a_chat(chat)
    assert res is True
    assert signer.context.workflow_path == ["step_0", "step_1"]
    assert signer.context.workflow_steps == 2
    assert signer.context.flow_trace is not None
    assert signer.context.pulseflow_side_effect_started is True


@pytest.mark.asyncio
async def test_runtime_send_message_and_dice_mark_pulseflow_side_effect():
    """验证 runtime.send_message 与 send_dice 会主动标记 pulseflow_side_effect_started。"""
    from tg_signer.core.context import UserSignerWorkerContext

    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer.log = MagicMock()
    signer.app = MagicMock()

    mock_msg = MagicMock()
    mock_msg.chat.id = 12345
    mock_msg.id = 999
    signer.app.send_message = AsyncMock(return_value=mock_msg)
    signer.app.send_dice = AsyncMock(return_value=mock_msg)

    assert signer.context.pulseflow_side_effect_started is False
    await signer.send_message(12345, "hello")
    assert signer.context.pulseflow_side_effect_started is True

    signer.context.pulseflow_side_effect_started = False
    await signer.send_dice(12345, "🎲")
    assert signer.context.pulseflow_side_effect_started is True


def test_flow_normalizer_dict_actions_preserves_policy():
    """验证使用 dict 动作配置时，stop_flow_on_terminal / continue_on_error 能被正确规范化。"""
    from tg_signer.core.flow_models import TERMINAL_COMPLETE_ID, TerminalPolicy
    from tg_signer.core.flow_normalizer import GraphNormalizer

    chat = MagicMock()
    chat.flow_graph = None
    chat.steps = None
    chat.actions = [
        {
            "action": "SEND_TEXT",
            "text": "/start",
            "stop_flow_on_terminal": True,
            "continue_on_error": True,
        }
    ]
    graph = GraphNormalizer.from_chat(chat)
    node = graph.nodes["step_0"]
    assert node.terminal_policy == TerminalPolicy.STOP_FLOW
    assert node.on_failure_node_id == TERMINAL_COMPLETE_ID

@pytest.mark.asyncio
async def test_user_signer_workflow_steps_executes_via_pulseflow_by_default():
    """验证工作流步骤任务 (chat.steps) 默认走 PulseFlow (v4) 执行。"""
    from tg_signer.config import SupportAction, WorkflowStepConfig
    from tg_signer.core.context import UserSignerWorkerContext

    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer.log = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)

    chat = SignChatV3(
        chat_id=88888,
        initial_step_id="step1",
        steps=[
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "/checkin"},
                next_step_id="COMPLETE",
            )
        ],
    )

    with patch.dict("os.environ", {}, clear=True):
        res = await signer.sign_a_chat(chat)
        assert res is True
        log_msgs = [call[0][0] for call in signer.log.call_args_list]
        assert any("PulseFlow (v4)" in m and "default" in m for m in log_msgs)
        assert signer.context.workflow_path == ["step1"]
        assert signer.context.workflow_steps == 1
        assert "step1" in signer.context.step_outputs


@pytest.mark.asyncio
async def test_user_signer_workflow_steps_explicit_v3_override_and_env_override():
    """验证显式 execution_engine="v3" 或环境变量 PULSEFLOW_ENGINE_OVERRIDE=v3 保持走 V3 执行。"""
    from tg_signer.config import SupportAction, WorkflowStepConfig
    from tg_signer.core.context import UserSignerWorkerContext

    # 1. 显式 chat.execution_engine = "v3"
    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer.log = MagicMock()
    signer.wait_for = AsyncMock(return_value=True)

    chat_v3 = SignChatV3(
        chat_id=88888,
        initial_step_id="step1",
        steps=[
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "/checkin"},
                next_step_id="COMPLETE",
            )
        ],
        execution_engine="v3",
    )

    with patch.dict("os.environ", {}, clear=True):
        res = await signer.sign_a_chat(chat_v3)
        assert res is True or res is None
        log_msgs = [call[0][0] for call in signer.log.call_args_list]
        assert not any("PulseFlow (v4)" in m for m in log_msgs)
        assert signer.context.workflow_path == ["step1"]

    # 2. 环境变量 PULSEFLOW_ENGINE_OVERRIDE=v3 强控
    signer2 = UserSigner.__new__(UserSigner)
    signer2._account = "test_acc"
    signer2.app = MagicMock()
    signer2.app.get_chat = AsyncMock()
    signer2.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer2.log = MagicMock()
    signer2.wait_for = AsyncMock(return_value=True)

    chat_default = SignChatV3(
        chat_id=88888,
        initial_step_id="step1",
        steps=[
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "/checkin"},
                next_step_id="COMPLETE",
            )
        ],
    )

    with patch.dict("os.environ", {"PULSEFLOW_ENGINE_OVERRIDE": "v3"}):
        res2 = await signer2.sign_a_chat(chat_default)
        assert res2 is True or res2 is None
        log_msgs2 = [call[0][0] for call in signer2.log.call_args_list]
        assert not any("PulseFlow (v4)" in m for m in log_msgs2)
        assert signer2.context.workflow_path == ["step1"]


@pytest.mark.asyncio
async def test_user_signer_side_effect_barrier_blocks_fallback_and_retry():
    """验证硬副作用屏障：已产生外部写操作后，严禁因切流降级回退至经典引擎或整流重试。"""
    from tg_signer.config import SupportAction, WorkflowStepConfig
    from tg_signer.core.context import UserSignerWorkerContext

    signer = UserSigner.__new__(UserSigner)
    signer._account = "test_acc"
    signer.app = MagicMock()
    signer.app.get_chat = AsyncMock()
    signer.context = UserSignerWorkerContext(sign_chats={}, chat_messages={})
    signer.log = MagicMock()

    call_count = 0

    async def wait_for_with_side_effect(chat, action, next_action=None):
        nonlocal call_count
        call_count += 1
        # 产生真实外部副作用：标记 pulseflow_side_effect_started
        signer.context.pulseflow_side_effect_started = True
        if call_count >= 1:
            # 外部写动作发出后发生异常（如网络中断或远端报错）
            raise RuntimeError("Telegram network drop after send_message")
        return True

    signer.wait_for = wait_for_with_side_effect

    chat = SignChatV3(
        chat_id=88888,
        initial_step_id="step1",
        steps=[
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "/pay"},
                next_step_id="COMPLETE",
            )
        ],
    )

    token = task_retry_count_var.set(3)
    try:
        with pytest.raises(RuntimeError, match="Telegram network drop after send_message"):
            await signer.sign_a_chat(chat)
    finally:
        task_retry_count_var.reset(token)

    # 验证：产生副作用后立即熔断，严禁重试整个流程导致重复写操作
    assert call_count == 1
    # 验证：严禁回退 Classic 经典引擎执行
    assert getattr(signer.context, "pulseflow_fallback_occurred", False) is False
    log_msgs = [call[0][0] for call in signer.log.call_args_list]
    assert any("已产生外部副作用" in m and "禁止自动回退 Classic" in m for m in log_msgs)

