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
