import asyncio
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
from tg_signer.core.signer_actions import SignerActionsMixin
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
    monkeypatch.chdir(tmp_path)
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


def test_plugin_registry_idempotency_and_name_sanitization(monkeypatch, tmp_path):
    PluginRegistry.clear()
    monkeypatch.chdir(tmp_path)
    # 插件目录名含连字符与点号 (my-hyphen.plugin)
    plugin_dir = tmp_path / "my-hyphen.plugin"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('hyphen_plugin', mode='reactive')\n"
        "def handler(ctx):\n    return True\n",
        encoding="utf-8",
    )
    # 单文件插件名含破折号 (single-dash.py)
    (tmp_path / "single-dash.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        "@PluginRegistry.register('dash_plugin', mode='active')\n"
        "def handler(ctx):\n    return True\n",
        encoding="utf-8",
    )

    # 第一次加载
    loaded1 = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded1 == 2
    assert PluginRegistry.get("hyphen_plugin") is not None
    assert PluginRegistry.get("dash_plugin") is not None

    # 第二次加载（幂等性：已加载文件不重复执行，新增计数为 0）
    loaded2 = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded2 == 0

    # load_all_configured_plugins 无论多次调用均返回已注册插件总数
    monkeypatch.setenv("PLUGINS_DIR", str(tmp_path))
    total = PluginRegistry.load_all_configured_plugins()
    assert total == 2


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.app.send_message = AsyncMock()
        self.app.get_chat_history = MagicMock()
        self.log_entries = []
        self.context = MagicMock()
        self.context.chat_messages = {}
        self.context.waiting_message = None
        self.context.last_callback_answer = None

    def log(self, msg, level="INFO"):
        self.log_entries.append((level, msg))

    def _message_matches_chat_thread(self, message, chat):
        return True

    def _message_is_actionable_target(self, message):
        return True

    def _log_received_target_message(self, message):
        pass

    def _describe_action(self, action):
        return str(action)

    def _current_action_step_label(self):
        return "第 1 步"


@pytest.mark.asyncio
async def test_active_plugin_execution_success():
    PluginRegistry.clear()
    executed_params = None

    @PluginRegistry.register("test_act", mode="active")
    async def act_handler(ctx: PluginContext):
        nonlocal executed_params
        executed_params = ctx.params
        ctx.log("插件运行正常")
        return True

    signer = DummySigner()
    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="test_act", mode="active", params={"foo": "bar"})])
    action = chat.actions[0]

    result = await signer.wait_for(chat, action, timeout=2.0)
    assert result is True
    assert executed_params == {"foo": "bar"}
    assert any("插件运行正常" in entry[1] for entry in signer.log_entries)


@pytest.mark.asyncio
async def test_active_plugin_timeout_circuit_breaker():
    PluginRegistry.clear()

    @PluginRegistry.register("hang_plugin", mode="active")
    async def hang_handler(ctx: PluginContext):
        await asyncio.sleep(5.0)
        return True

    signer = DummySigner()
    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="hang_plugin", mode="active", timeout=0.1)])
    action = chat.actions[0]

    with pytest.raises(RuntimeError) as exc_info:
        await signer.wait_for(chat, action, timeout=0.1)
    assert "超时" in str(exc_info.value) or "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_reactive_plugin_matching_and_retry():
    PluginRegistry.clear()

    @PluginRegistry.register("reply_calc", mode="reactive")
    async def calc_handler(ctx: PluginContext):
        if ctx.message and "answer_me" in ctx.message.text:
            await ctx.reply("42")
            return True
        return False

    signer = DummySigner()
    mock_msg_wrong = MagicMock()
    mock_msg_wrong.id = 1
    mock_msg_wrong.text = "irrelevant message"

    mock_msg_right = MagicMock()
    mock_msg_right.id = 2
    mock_msg_right.text = "answer_me please"

    signer.context.chat_messages[123] = {
        1: mock_msg_wrong,
        2: mock_msg_right,
    }

    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="reply_calc", mode="reactive")])
    action = chat.actions[0]

    result = await signer.wait_for(chat, action, timeout=2.0)
    assert result is None  # wait_for 返回 None 代表响应式步骤成功完成
    assert signer.context.chat_messages[123][2] is None


@pytest.mark.asyncio
async def test_plugin_not_found_raises():
    PluginRegistry.clear()
    signer = DummySigner()
    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="unregistered_plugin", mode="active")])
    action = chat.actions[0]

    with pytest.raises(RuntimeError) as exc_info:
        await signer.wait_for(chat, action, timeout=1.0)
    assert "not found in PluginRegistry" in str(exc_info.value)
    assert any("未注册或未成功加载" in entry[1] for entry in signer.log_entries)


@pytest.mark.asyncio
async def test_active_plugin_sync_handler_and_failure():
    PluginRegistry.clear()

    @PluginRegistry.register("sync_fail_plugin", mode="active")
    def sync_fail_handler(ctx: PluginContext):
        return False

    signer = DummySigner()
    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="sync_fail_plugin", mode="active")])
    action = chat.actions[0]

    result = await signer.wait_for(chat, action, timeout=1.0)
    assert result is False
    assert any("返回执行失败" in entry[1] for entry in signer.log_entries)


@pytest.mark.asyncio
async def test_reactive_plugin_history_fallback():
    PluginRegistry.clear()

    @PluginRegistry.register("hist_plugin", mode="reactive")
    async def hist_handler(ctx: PluginContext):
        if ctx.message and "target_hist" in ctx.message.text:
            return True
        return False

    signer = DummySigner()
    mock_msg = MagicMock()
    mock_msg.id = 99
    mock_msg.text = "target_hist here"

    async def fake_history(chat_id, limit=12):
        yield mock_msg

    signer.app.get_chat_history = fake_history

    chat = SignChatV3(chat_id=123, actions=[PluginAction(plugin_name="hist_plugin", mode="reactive")])
    action = chat.actions[0]

    result = await signer.wait_for(chat, action, timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_math_solver_sample_plugin():
    import importlib.util

    plugin_path = Path("plugins/math_solver/main.py").resolve()
    assert plugin_path.exists(), "plugins/math_solver/main.py 必须存在"

    PluginRegistry.clear()
    spec = importlib.util.spec_from_file_location("math_solver", plugin_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    meta = PluginRegistry.get("math_solver")
    assert meta is not None
    assert meta.mode == "reactive"

    # 测试识别并计算加减乘（符合 Issue #10 中的 2*31 场景）
    mock_app = MagicMock()
    mock_app.send_message = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.id = 77
    mock_msg.text = "请在 30 秒内输入 2*31 的答案"

    mock_logger = MagicMock()
    ctx = PluginContext(
        app=mock_app,
        chat_id=12345,
        message=mock_msg,
        logger=mock_logger,
    )

    handled = await meta.handler(ctx)
    assert handled is True
    assert mock_logger.log.called
    assert "成功匹配计算题" in mock_logger.log.call_args[0][0]
    mock_app.send_message.assert_awaited_once_with(
        12345,
        "62",
        reply_to_message_id=77,
    )

    # 测试加法、减法、符号乘法、除法及除以 0
    eval_fn = mod._evaluate_expression
    assert eval_fn("15 + 27") == 42
    assert eval_fn("100 - 45") == 55
    assert eval_fn("12 × 4") == 48
    assert eval_fn("80 ÷ 4") == 20
    assert eval_fn("80 / 4") == 20
    assert eval_fn("80 / 0") is None
    assert eval_fn("纯文本没有算式") is None
    assert eval_fn("当前时间 2026-09-08 12:00:00 签到成功") is None
    assert eval_fn("签到日期: 2025-12-31") is None
    assert eval_fn("2026-09-08 验证码: 7 * 8") == 56

    # 测试无消息或文本为空或不含算式时的防御处理
    empty_ctx = PluginContext(app=mock_app, chat_id=12345, message=None, logger=MagicMock())
    assert await meta.handler(empty_ctx) is False

    no_text_msg = MagicMock()
    no_text_msg.text = None
    no_text_ctx = PluginContext(app=mock_app, chat_id=12345, message=no_text_msg, logger=MagicMock())
    assert await meta.handler(no_text_ctx) is False

    non_math_msg = MagicMock()
    non_math_msg.text = "签到成功，欢迎下次光临！"
    non_math_ctx = PluginContext(app=mock_app, chat_id=12345, message=non_math_msg, logger=MagicMock())
    assert await meta.handler(non_math_ctx) is False


def test_support_action_compatibility_with_existing_actions():
    """验证所有原有的 1-8 动作及其描述未被篡改"""
    expected = {
        1: ("SEND_TEXT", "发送普通文本"),
        2: ("SEND_DICE", "发送Dice类型的emoji"),
        3: ("CLICK_KEYBOARD_BY_TEXT", "根据文本点击键盘"),
        4: ("CHOOSE_OPTION_BY_IMAGE", "根据图片选择选项"),
        5: ("REPLY_BY_CALCULATION_PROBLEM", "回复计算题"),
        6: ("REPLY_BY_IMAGE_RECOGNITION", "AI image recognition then send text"),
        7: ("CLICK_BUTTON_BY_CALCULATION_PROBLEM", "AI calculation then click button"),
        8: ("KEYWORD_NOTIFY", "关键词监听"),
        99: ("CUSTOM_PLUGIN", "自定义插件"),
    }
    for val, (name, desc) in expected.items():
        act = SupportAction(val)
        assert act.name == name
        assert act.desc == desc


def test_directory_plugin_with_sibling_import(tmp_path):
    """验证目录型插件能够顺利导入同目录下的辅助模块 (sys.path 注入)"""
    PluginRegistry.clear()
    plugin_dir = tmp_path / "multi_file_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "helper.py").write_text("MAGIC_NUM = 7788\n", encoding="utf-8")
    code = (
        "from tg_signer.core.plugins import PluginRegistry\n"
        "import helper\n\n"
        "@PluginRegistry.register('multi_file', mode='active')\n"
        "def run(ctx):\n"
        "    return helper.MAGIC_NUM\n"
    )
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")

    loaded = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded == 1
    meta = PluginRegistry.get("multi_file")
    assert meta is not None
    assert meta.handler(None) == 7788


def test_directory_plugin_with_relative_import(tmp_path):
    """验证目录型插件按包加载时支持相对导入。"""
    PluginRegistry.clear()
    plugin_dir = tmp_path / "relative_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "helper.py").write_text("MAGIC_NUM = 9911\n", encoding="utf-8")
    code = (
        "from .helper import MAGIC_NUM\n"
        "from tg_signer.core.plugins import PluginRegistry\n\n"
        "@PluginRegistry.register('relative_multi_file', mode='active')\n"
        "def run(ctx):\n"
        "    return MAGIC_NUM\n"
    )
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")

    loaded = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded == 1
    meta = PluginRegistry.get("relative_multi_file")
    assert meta is not None
    assert meta.handler(None) == 9911
