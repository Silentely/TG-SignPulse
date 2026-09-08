import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.keyword_monitor.continue_actions import describe_continue_action
from backend.services.sign_task_config_inspect import task_requires_updates
from tg_signer.config import (
    PluginAction,
    SignChatV3,
    SupportAction,
)
from tg_signer.core.plugins import PluginContext, PluginRegistry
from tg_signer.core.signer_matchers import SignerMatchersMixin


def test_custom_plugin_enum_and_desc():
    assert SupportAction.CUSTOM_PLUGIN == 99
    assert SupportAction.CUSTOM_PLUGIN.desc == "自定义插件"
    assert SupportAction(99) == SupportAction.CUSTOM_PLUGIN


def test_plugin_action_serialization_and_defaults():
    action = PluginAction(plugin_name="math_solver")
    assert action.action == SupportAction.CUSTOM_PLUGIN
    assert action.plugin_name == "math_solver"
    assert action.mode == "reactive"
    assert action.timeout is None
    assert action.params == {}

    data = (
        action.to_jsonable()
        if hasattr(action, "to_jsonable")
        else (action.model_dump() if hasattr(action, "model_dump") else action.dict())
    )
    assert data["action"] == 99
    assert data["plugin_name"] == "math_solver"
    assert data["mode"] == "reactive"


def test_plugin_action_in_sign_chat_v3():
    chat = SignChatV3(
        chat_id=123456,
        actions=[
            PluginAction(plugin_name="test_active", mode="active"),
        ],
    )
    assert not chat.requires_updates

    reactive_chat = SignChatV3(
        chat_id=123456,
        actions=[
            PluginAction(plugin_name="test_reactive", mode="reactive"),
        ],
    )
    assert reactive_chat.requires_updates


def test_task_requires_updates_with_plugin():
    active_cfg = {"chats": [{"actions": [{"action": 99, "mode": "active"}]}]}
    assert not task_requires_updates(active_cfg)

    reactive_cfg = {"chats": [{"actions": [{"action": 99, "mode": "reactive"}]}]}
    assert task_requires_updates(reactive_cfg)

    default_mode_cfg = {"chats": [{"actions": [{"action": 99}]}]}
    assert task_requires_updates(default_mode_cfg)


def test_describe_action_for_plugin():
    class DummyMatcher(SignerMatchersMixin):
        pass

    matcher = DummyMatcher()
    action = PluginAction(plugin_name="math_solver", mode="reactive")
    assert matcher._describe_action(action) == "自定义插件「math_solver」(reactive)"


def test_describe_continue_action_for_plugin():
    action = {"action": 99, "plugin_name": "math_solver"}
    assert describe_continue_action(action) == "自定义插件: math_solver"


def test_plugin_registry_register_and_get():
    PluginRegistry.clear()

    @PluginRegistry.register("demo_plugin", mode="active", description="演示插件")
    async def demo_handler(ctx: PluginContext):
        return True

    meta = PluginRegistry.get("demo_plugin")
    assert meta is not None
    assert meta.name == "demo_plugin"
    assert meta.mode == "active"
    assert meta.description == "演示插件"
    assert meta.handler is demo_handler
    assert "demo_plugin" in PluginRegistry.list_plugins()


@pytest.mark.asyncio
async def test_plugin_context_logging_and_reply_and_click():
    mock_app = MagicMock()
    mock_app.send_message = AsyncMock(return_value=MagicMock(id=999))

    logged_messages = []
    mock_logger = MagicMock()
    mock_logger.log = lambda msg, level="INFO": logged_messages.append((level, msg))

    mock_msg = MagicMock()
    mock_msg.id = 100
    mock_msg.click = AsyncMock()

    ctx = PluginContext(
        app=mock_app,
        chat_id=-1001234567,
        message_thread_id=42,
        message=mock_msg,
        params={"key": "val"},
        logger=mock_logger,
    )

    ctx.log("测试日志输出", level="WARNING")
    assert logged_messages == [("WARNING", "测试日志输出")]

    res = await ctx.reply("回复内容")
    assert res.id == 999
    mock_app.send_message.assert_awaited_once_with(
        -1001234567,
        "回复内容",
        reply_to_message_id=100,
        message_thread_id=42,
    )

    mock_app.send_message.reset_mock()
    await ctx.send_message("主动消息")
    mock_app.send_message.assert_awaited_once_with(
        -1001234567,
        "主动消息",
        message_thread_id=42,
    )

    await ctx.click("确定")
    mock_msg.click.assert_awaited_once_with("确定")


def test_plugin_registry_isolation_on_broken_plugin():
    PluginRegistry.clear()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # 1. 目录型插件 (main.py)
        valid_dir = root / "valid_plugin"
        valid_dir.mkdir()
        (valid_dir / "main.py").write_text(
            "from tg_signer.core.plugins import PluginRegistry\n"
            "@PluginRegistry.register('valid_one', mode='reactive')\n"
            "def handler(ctx):\n    return True\n",
            encoding="utf-8",
        )

        # 2. 目录型插件 (__init__.py)
        init_dir = root / "init_plugin"
        init_dir.mkdir()
        (init_dir / "__init__.py").write_text(
            "from tg_signer.core.plugins import PluginRegistry\n"
            "@PluginRegistry.register('init_one', mode='active')\n"
            "def handler(ctx):\n    return True\n",
            encoding="utf-8",
        )

        # 3. 单文件插件 (*.py)
        (root / "single_file.py").write_text(
            "from tg_signer.core.plugins import PluginRegistry\n"
            "@PluginRegistry.register('single_one', mode='active')\n"
            "def handler(ctx):\n    return True\n",
            encoding="utf-8",
        )

        # 4. 损坏插件（语法错误）
        broken_dir = root / "broken_plugin"
        broken_dir.mkdir()
        (broken_dir / "main.py").write_text(
            "def broken_func(:\n    syntax error\n",
            encoding="utf-8",
        )

        # 5. 依赖缺失插件
        missing_dep_dir = root / "missing_dep_plugin"
        missing_dep_dir.mkdir()
        (missing_dep_dir / "main.py").write_text(
            "import non_existent_package_xyz_999\n",
            encoding="utf-8",
        )

        # 加载目录，断言即使存在多个故障插件也不会引发主程序崩溃
        loaded_count = PluginRegistry.load_plugins_from_dir(root)
        assert loaded_count == 3
        assert PluginRegistry.get("valid_one") is not None
        assert PluginRegistry.get("init_one") is not None
        assert PluginRegistry.get("single_one") is not None
        assert PluginRegistry.get("broken_plugin") is None


def test_plugin_registry_load_all_configured_plugins(monkeypatch, tmp_path):
    PluginRegistry.clear()
    plugins_dir = tmp_path / "custom_plugins"
    plugins_dir.mkdir()
    (plugins_dir / "test_env_plugin.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('env_plugin', mode='reactive')\n"
        "def handler(ctx):\n    return True\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGINS_DIR", str(plugins_dir))
    count = PluginRegistry.load_all_configured_plugins()
    assert count == 1
    assert PluginRegistry.get("env_plugin") is not None
