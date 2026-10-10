# tests/test_flow_signer_cutover.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_signer.config import SendTextAction, SignChatV3
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
        # 验证输出了执行引擎日志
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
    # 核心契约防线：PulseFlow 失败时必须抛出 RuntimeError，供 _run_config_chats 捕获记入失败
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
