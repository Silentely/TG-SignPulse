# tests/test_flow_signer_cutover.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tg_signer.config import SignChatV3, SendTextAction
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
        # 验证底层 wait_for 被调用了
        assert signer.wait_for.call_count == 1
