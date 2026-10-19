import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from backend.services.keyword_monitor.continue_actions import (
    click_keyboard_sequence,
    click_keyboard_sequence_result,
    execute_ai_action,
)
from tg_signer.ai_tools import AITools
from tg_signer.compat import (
    button_text_matches,
    clean_text_for_match,
    parse_click_targets,
)
from tg_signer.config import ClickButtonByCalculationProblemAction
from tg_signer.core.signer_actions import SignerActionsMixin


def test_clean_text_for_match_emojis_and_symbols():
    # 纯 Emoji 不应被清洗为空
    assert clean_text_for_match("🐸") == "🐸"
    assert clean_text_for_match("🦁") == "🦁"
    assert clean_text_for_match(" 🐸 ") == "🐸"
    assert clean_text_for_match("🐸 青蛙") == "🐸青蛙"
    # 纯标点保底
    assert clean_text_for_match("...") == "..."


def test_button_text_matches_with_emojis():
    assert button_text_matches("🐸", "🐸") is True
    assert button_text_matches("🐸", "🐸 青蛙") is True
    assert button_text_matches("🦁", "🦁 狮子") is True
    assert button_text_matches("🐸", "🦁") is False


def test_parse_click_targets():
    # 1. 箭头
    assert parse_click_targets("🐸 → 🦁") == ["🐸", "🦁"]
    assert parse_click_targets("A -> B -> C") == ["A", "B", "C"]

    # 2. 逗号 / 分号
    assert parse_click_targets("🐸, 🦁") == ["🐸", "🦁"]
    assert parse_click_targets("🐸，🦁") == ["🐸", "🦁"]
    assert parse_click_targets("🐸; 🦁") == ["🐸", "🦁"]

    # 3. 换行
    assert parse_click_targets("🐸\n🦁") == ["🐸", "🦁"]

    # 4. JSON 数组 / 对象
    assert parse_click_targets('["🐸", "🦁"]') == ["🐸", "🦁"]
    assert parse_click_targets({"answer": ["🐸", "🦁"]}) == ["🐸", "🦁"]
    assert parse_click_targets({"result": "🐸, 🦁"}) == ["🐸", "🦁"]

    # 5. 单文本回退
    assert parse_click_targets("🐸") == ["🐸"]
    assert parse_click_targets("签到") == ["签到"]
    assert parse_click_targets("") == []
    assert parse_click_targets(None) == []


@pytest.mark.asyncio
async def test_click_keyboard_sequence_success():
    service = MagicMock()

    async def mock_retry(_c, fn, **kw):
        res = fn()
        return (await res) if inspect.isawaitable(res) else res

    service._call_client_with_retry = AsyncMock(side_effect=mock_retry)

    client = MagicMock()
    btn1 = InlineKeyboardButton("🐸", callback_data=b"frog")
    btn2 = InlineKeyboardButton("🦁", callback_data=b"lion")
    markup = InlineKeyboardMarkup([[btn1, btn2]])

    msg = MagicMock(spec=Message)
    msg.id = 100
    msg.chat = MagicMock(id=123)
    msg.reply_markup = markup

    client.get_messages = AsyncMock(return_value=msg)
    client.request_callback_answer = AsyncMock(return_value=True)

    with patch(
        "backend.services.keyword_monitor.continue_actions.click_inline_button",
        new=AsyncMock(return_value=True),
    ):
        result = await click_keyboard_sequence(
            service,
            client,
            123,
            None,
            ["🐸", "🦁"],
            msg,
            delay_min=0.01,
            delay_max=0.02,
        )
        assert result is True


@pytest.mark.asyncio
async def test_click_keyboard_sequence_partial_failure():
    service = MagicMock()

    async def mock_retry(_c, fn, **kw):
        res = fn()
        return (await res) if inspect.isawaitable(res) else res

    service._call_client_with_retry = AsyncMock(side_effect=mock_retry)
    client = MagicMock()

    btn1 = InlineKeyboardButton("🐸", callback_data=b"frog")
    markup = InlineKeyboardMarkup([[btn1]])  # 缺少第二个按钮

    msg = MagicMock(spec=Message)
    msg.id = 100
    msg.chat = MagicMock(id=123)
    msg.reply_markup = markup

    client.get_messages = AsyncMock(return_value=msg)

    with patch(
        "backend.services.keyword_monitor.continue_actions.click_inline_button",
        new=AsyncMock(return_value=True),
    ):
        result = await click_keyboard_sequence(
            service,
            client,
            123,
            None,
            ["🐸", "🦁"],
            msg,
            delay_min=0.01,
            delay_max=0.02,
        )
        assert result is False


@pytest.mark.asyncio
async def test_execute_ai_action_7_with_sequence():
    service = MagicMock()
    client = MagicMock()
    msg = MagicMock(spec=Message)
    msg.text = "请按顺序点击：🐸 → 🦁"
    msg.caption = None
    msg.photo = None

    ai_tools = MagicMock()
    ai_tools.calculate_problem = AsyncMock(return_value='["🐸", "🦁"]')

    with (
        patch(
            "backend.services.keyword_monitor.continue_actions.get_ai_tools",
            return_value=ai_tools,
        ),
        patch(
            "backend.services.keyword_monitor.continue_actions._run_ai_call",
            new=AsyncMock(return_value='["🐸", "🦁"]'),
        ),
        patch(
            "backend.services.keyword_monitor.continue_actions.click_keyboard_sequence_result",
            new=AsyncMock(return_value=(True, True)),
        ) as mock_sequence,
    ):
        action = {"action": 7, "ai_prompt": "提取顺序"}
        ok = await execute_ai_action(service, client, 123, None, action, msg)
        assert ok is True
        mock_sequence.assert_awaited_once_with(
            service, client, 123, None, ["🐸", "🦁"], msg
        )


def test_ai_tools_coerce_option_indexes_multi():
    options = [(1, "🐸"), (2, "🦁"), (3, "🐰")]
    # 逗号分隔
    assert AITools._coerce_option_indexes("🐸, 🦁", options) == [1, 2]
    # 箭头分隔
    assert AITools._coerce_option_indexes("🐸 → 🦁", options) == [1, 2]
    # JSON 数组
    assert AITools._coerce_option_indexes('["🐸", "🦁"]', options) == [1, 2]
    # dict 内部包装
    assert AITools._coerce_option_indexes({"answer": "🐸, 🦁"}, options) == [1, 2]


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.log = MagicMock()
        self.context = MagicMock()
        self._log_received_target_message = MagicMock()
        self._resolve_message_thread_id = MagicMock(return_value=None)


@pytest.mark.asyncio
async def test_signer_actions_multi_target_sequence():
    signer = DummySigner()
    btn1 = InlineKeyboardButton("🐸", callback_data=b"frog")
    btn2 = InlineKeyboardButton("🦁", callback_data=b"lion")
    markup = InlineKeyboardMarkup([[btn1, btn2]])

    msg = MagicMock(spec=Message)
    msg.id = 200
    msg.text = "请按顺序点击：🐸 → 🦁"
    msg.caption = None
    msg.chat = MagicMock(id=456)
    msg.reply_markup = markup

    signer.app.get_messages = AsyncMock(return_value=msg)
    signer._click_inline_button = AsyncMock(return_value=True)

    action = ClickButtonByCalculationProblemAction(action=7)
    with (
        patch.object(
            signer,
            "_execute_ai_action",
            new=AsyncMock(return_value="🐸 → 🦁"),
        ),
        patch.object(signer, "_log_received_target_message"),
    ):
        signer.get_ai_tools = MagicMock()
        ok = await signer._click_button_by_calculation_problem(action, msg)
        assert ok is True
        assert signer._click_inline_button.await_count == 2


def test_parse_click_targets_single_button_protection():
    # 1. 按钮文本为千分位数字时，不应按逗号拆分
    assert parse_click_targets("1,000") == ["1,000"]
    assert parse_click_targets("10,000.50") == ["10,000.50"]

    # 2. 键盘中存在与整串匹配的按钮时，优先作为完整单按钮，不进行拆分
    assert parse_click_targets(
        "Hello, World", available_buttons=["Hello, World", "Other"]
    ) == ["Hello, World"]
    # 若键盘中不存在该完整按钮，且包含分隔符，才执行拆分
    assert parse_click_targets("🐸, 🦁", available_buttons=["🐸", "🦁"]) == ["🐸", "🦁"]


@pytest.mark.asyncio
async def test_click_keyboard_sequence_stops_when_keyboard_removed():
    service = MagicMock()

    async def mock_retry(_c, fn, **kw):
        res = fn()
        return (await res) if inspect.isawaitable(res) else res

    service._call_client_with_retry = AsyncMock(side_effect=mock_retry)

    client = MagicMock()
    btn1 = InlineKeyboardButton("A", callback_data=b"a")
    btn2 = InlineKeyboardButton("B", callback_data=b"b")
    msg_with_markup = MagicMock(
        spec=Message, id=1, reply_markup=InlineKeyboardMarkup([[btn1, btn2]])
    )

    # 点击第一步后，机器人移除了键盘
    msg_removed = MagicMock(spec=Message, id=1, reply_markup=None)
    client.get_messages = AsyncMock(return_value=msg_removed)

    with patch(
        "backend.services.keyword_monitor.continue_actions.click_inline_button",
        new=AsyncMock(return_value=True),
    ) as mock_click:
        success, side_effect = await click_keyboard_sequence_result(
            service,
            client,
            123,
            None,
            ["A", "B"],
            msg_with_markup,
            delay_min=0,
            delay_max=0,
        )
        assert success is False
        assert side_effect is True
        # 第一步执行了点击产生副作用，第二步因键盘被移除未盲目执行回调
        assert mock_click.await_count == 1


def test_parse_click_targets_explicit_json_over_button_cleaning():
    # 显式 JSON 序列不应被去标点后的单按钮误覆盖
    assert parse_click_targets('["1", "2"]', available_buttons=["1", "2", "12"]) == [
        "1",
        "2",
    ]


def test_ai_tools_coerce_option_indexes_protects_full_button_text():
    options = [(1, "Hello"), (2, "Hello, World"), (3, "World")]
    assert AITools._coerce_option_indexes("Hello, World", options) == [2]


@pytest.mark.asyncio
async def test_execute_ai_action_7_partial_failure_raises_terminal_error():
    from backend.services.keyword_monitor.rules import TerminalAIActionError

    service = MagicMock()
    client = MagicMock()
    msg = MagicMock(
        spec=Message, text="验证码", caption=None, photo=None, reply_markup=None
    )

    ai_tools = MagicMock()
    ai_tools.calculate_problem = AsyncMock(return_value='["A", "B"]')

    with (
        patch(
            "backend.services.keyword_monitor.continue_actions.get_ai_tools",
            return_value=ai_tools,
        ),
        patch(
            "backend.services.keyword_monitor.continue_actions._run_ai_call",
            new=AsyncMock(return_value='["A", "B"]'),
        ),
        patch(
            "backend.services.keyword_monitor.continue_actions.click_keyboard_sequence_result",
            new=AsyncMock(return_value=(False, True)),  # 部分执行失败
        ),
    ):
        action = {"action": 7}
        with pytest.raises(TerminalAIActionError, match="partially executed"):
            await execute_ai_action(service, client, 123, None, action, msg)


@pytest.mark.asyncio
async def test_signer_actions_sequence_partial_failure_raises_runtime_error():
    signer = DummySigner()
    btn1 = InlineKeyboardButton("A", callback_data=b"a")
    markup = InlineKeyboardMarkup([[btn1]])
    msg = MagicMock(
        spec=Message, id=1, text="click A then B", caption=None, reply_markup=markup
    )
    msg.chat = MagicMock(id=123)

    signer.app.get_messages = AsyncMock(return_value=msg)
    # 第一步 A 点击成功，第二步 B 失败
    signer._click_single_target_by_text = AsyncMock(
        side_effect=lambda target, _: target == "A"
    )

    with pytest.raises(RuntimeError, match="前置目标已点击"):
        await signer._click_targets_sequence(["A", "B"], msg, delay_min=0, delay_max=0)


def test_button_text_matches_digit_boundary_with_emoji():
    target_clean = clean_text_for_match("10")
    btn_100_clean = clean_text_for_match("✅100")
    btn_10_clean = clean_text_for_match("✅10")
    assert button_text_matches(target_clean, btn_100_clean) is False
    assert button_text_matches(target_clean, btn_10_clean) is True


def test_parse_click_targets_normalized_full_button_protection():
    # 全半角标点差异应被归一化完整保护，不被误拆
    assert parse_click_targets("领取，奖励", available_buttons=["领取,奖励"]) == [
        "领取，奖励"
    ]


@pytest.mark.asyncio
async def test_flow_engine_stops_retry_on_sequence_click_partial_error():
    from tg_signer.core.flow_context import ScopedFlowContext
    from tg_signer.core.flow_engine import PulseFlowEngine
    from tg_signer.core.flow_models import (
        TERMINAL_FAIL_ID,
        ActionNode,
        ExecutionGraph,
        RetryPolicy,
    )

    signer = SignerActionsMixin()
    signer.app = MagicMock()
    signer.log = MagicMock()
    clicks = []

    async def click(target, msg):
        clicks.append(target)
        return target == "A"

    signer._click_single_target_by_text = click
    msg = MagicMock(spec=Message, id=1)
    msg.chat = MagicMock(id=123)
    signer.app.get_messages = AsyncMock(return_value=msg)

    graph = ExecutionGraph(
        entry_node_id="captcha",
        nodes={
            "captcha": ActionNode(
                id="captcha",
                on_failure_node_id=TERMINAL_FAIL_ID,
                retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0.001),
            )
        },
    )

    async def executor(node, ctx):
        return await signer._click_targets_sequence(
            ["A", "B"], msg, delay_min=0, delay_max=0
        )

    result = await PulseFlowEngine().run(graph, ScopedFlowContext(), executor)
    assert result["status"] == "failed"
    assert clicks == ["A", "B"]
    assert clicks.count("A") == 1


@pytest.mark.asyncio
async def test_sequence_click_timeout_interruption_prevents_retry():
    from tg_signer.core.flow_context import ScopedFlowContext
    from tg_signer.core.flow_engine import PulseFlowEngine
    from tg_signer.core.flow_models import (
        TERMINAL_FAIL_ID,
        ActionNode,
        ExecutionGraph,
        RetryPolicy,
    )
    from tg_signer.core.signer_actions import SignerActionsMixin

    signer = SignerActionsMixin()
    signer.log = MagicMock()
    signer.app = None
    clicks = []

    async def click(target, msg):
        clicks.append(target)
        return True

    signer._click_single_target_by_text = click
    graph = ExecutionGraph(
        entry_node_id="captcha",
        nodes={
            "captcha": ActionNode(
                id="captcha",
                timeout_seconds=0.02,
                on_failure_node_id=TERMINAL_FAIL_ID,
                retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0.001),
            )
        },
    )

    async def executor(node, ctx):
        return await signer._click_targets_sequence(
            ["A", "B"], MagicMock(spec=Message, id=1), delay_min=0.1, delay_max=0.1
        )

    result = await PulseFlowEngine().run(graph, ScopedFlowContext(), executor)
    assert result["status"] == "failed"
    # 第一步成功后若超时中断，绝不重复重试第一步
    assert clicks == ["A"]
