import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_signer.config import PluginAction, SignChatV3
from tg_signer.core.signer_actions import SignerActionsMixin


class DummyRunner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.log = MagicMock()


@pytest.mark.asyncio
async def test_async_plugin_enforces_subprocess_in_reactive_path():
    """验证即便是 async def 异步插件，在生产消息处理路径中也强制走 PluginProcessHost 子进程"""
    runner = DummyRunner()
    action = PluginAction(plugin_name="demo_async_plugin", params={})
    chat = SignChatV3(chat_id="123456", actions=[action])
    message = MagicMock()
    message.text = "hello"

    async def fake_async_handler(context):
        return {"status": "ok"}

    fake_plugin = MagicMock()
    fake_plugin.handler = fake_async_handler
    fake_plugin.enabled = True

    with (
        patch("tg_signer.core.plugins.PluginRegistry.get", return_value=fake_plugin),
        patch("tg_signer.core.plugins.PluginRegistry.is_enabled", return_value=True),
        patch("tg_signer.core.signer_actions.PluginProcessHost") as mock_host_cls,
    ):
        mock_host_instance = AsyncMock()
        mock_host_instance.execute = AsyncMock(
            return_value={"success": True, "result": "done"}
        )
        mock_host_cls.return_value = mock_host_instance

        with patch.dict(os.environ, {"PLUGIN_ISOLATION_ENGINE": "auto"}):
            result = await runner._dispatch_reactive_plugin_message(
                action=action,
                chat=chat,
                message=message,
                eff_timeout=5.0,
            )

        assert mock_host_cls.called, "PluginProcessHost 必须被实例化调用"
        assert mock_host_instance.execute.called, "必须调用 host.execute()"
        assert result is True


@pytest.mark.asyncio
async def test_async_plugin_enforces_subprocess_in_active_wait_for():
    """验证即便是 async def 异步插件，在 wait_for 主动执行动作中也强制走 PluginProcessHost 子进程"""
    runner = DummyRunner()
    action = PluginAction(plugin_name="demo_async_active_plugin", mode="active", params={})
    chat = SignChatV3(chat_id="123456", actions=[action])

    async def fake_async_handler(context):
        return True

    fake_plugin = MagicMock()
    fake_plugin.handler = fake_async_handler
    fake_plugin.enabled = True
    fake_plugin.mode = "active"

    with (
        patch("tg_signer.core.plugins.PluginRegistry.get", return_value=fake_plugin),
        patch("tg_signer.core.plugins.PluginRegistry.is_enabled", return_value=True),
        patch("tg_signer.core.signer_actions.PluginProcessHost") as mock_host_cls,
    ):
        mock_host_instance = AsyncMock()
        mock_host_instance.execute = AsyncMock(return_value=True)
        mock_host_cls.return_value = mock_host_instance

        with patch.dict(os.environ, {"PLUGIN_ISOLATION_ENGINE": "auto"}):
            result = await runner.wait_for(chat, action, timeout=5.0)

        assert mock_host_cls.called, "PluginProcessHost 必须被实例化调用"
        assert mock_host_instance.execute.called, "必须调用 host.execute()"
        assert result is True
