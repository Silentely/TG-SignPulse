"""Reply retry regressions without Telegram network access."""

import asyncio
import time

import pytest

from backend.services import runtime_settings
from backend.services.config_mixins import apply_global_settings_to_env
from backend.services.sign_task_notify import is_bot_offline_timeout
from tg_signer.config import FlowStepConfig, SendTextAction, SignChatV3
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import (
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    StepOutcome,
    WaitEventNode,
)
from tg_signer.core.flow_normalizer import GraphNormalizer


@pytest.mark.parametrize("steps", [False, True])
def test_normalized_defaults_and_global_overrides(monkeypatch, steps):
    monkeypatch.setattr(runtime_settings, "_global_settings", lambda: {})
    for key in (
        "REPLY_TIMEOUT",
        "RETRY_INTERVAL",
        "RETRY_MAX_ATTEMPTS",
        "RETRY_KEYWORDS",
    ):
        monkeypatch.setenv("SIGN_TASK_" + key, "")
    chat = SignChatV3(
        chat_id=1,
        **(
            {"steps": [FlowStepConfig(step_id="wait", node_type="wait_event")]}
            if steps
            else {
                "actions": [SendTextAction(action=1, text="/sign", wait_for_reply=True)]
            }
        ),
    )
    wait = next(
        n
        for n in GraphNormalizer.from_chat(chat).nodes.values()
        if isinstance(n, WaitEventNode)
    )
    assert (wait.timeout_seconds, wait.retry_interval, wait.max_retries) == (90, 10, 3)
    assert wait.retry_keywords == list(runtime_settings.DEFAULT_RETRY_KEYWORDS)
    monkeypatch.setattr(
        runtime_settings,
        "_global_settings",
        lambda: {
            "sign_task_reply_timeout": 150,
            "sign_task_retry_interval": 15,
            "sign_task_retry_max_attempts": 0,
            "sign_task_retry_keywords": "custom\n稍后",
        },
    )
    apply_global_settings_to_env(runtime_settings._global_settings())
    wait = next(
        n
        for n in GraphNormalizer.from_chat(chat).nodes.values()
        if isinstance(n, WaitEventNode)
    )
    assert (wait.timeout_seconds, wait.retry_interval, wait.max_retries) == (150, 15, 0)
    assert wait.retry_keywords == ["custom", "稍后"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ending",
    ["success", "exhausted", "send_failed", "send_exception", "silent", "unmatched"],
)
async def test_keyword_retry_outcomes(ending):
    bus = TelegramEventBus()
    ctx = ScopedFlowContext()
    calls = 0
    busy = "当前签到人数较多，请 10 秒后再试。"
    wait = WaitEventNode(
        id="wait",
        success_patterns=["签到成功"],
        retry_keywords=list(runtime_settings.DEFAULT_RETRY_KEYWORDS),
        retry_interval=0.001,
        max_retries=3,
        timeout_seconds=0.02,
        metadata={"chat_id": 1},
        on_failure_node_id="FAIL",
    )
    action = ActionNode(id="send", next_node_id="wait")
    graph = ExecutionGraph(entry_node_id="send", nodes={"send": action, "wait": wait})

    async def execute(node, context):
        nonlocal calls
        calls += 1
        context.system["last_sent_message_id"] = calls * 10
        if calls > 1 and ending == "send_failed":
            return StepOutcome(
                node_id=node.id, status=NodeStatus.FAILED, output_text="发送失败"
            )
        if calls > 1 and ending == "send_exception":
            raise RuntimeError("发送异常")
        if ending == "silent":
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
        text = ("签到成功" if calls > 1 else busy) if ending == "success" else busy
        if ending == "unmatched":
            text = "机器人已响应但规则不匹配"
        await bus.publish(
            TelegramMessageEvent(
                event_id=str(calls),
                chat_id=1,
                message_thread_id=None,
                message_id=calls * 10 + 1,
                sender_id=1,
                event_type="NEW_MESSAGE",
                text=text,
                occurred_at=time.time(),
            )
        )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    result = await PulseFlowEngine(event_bus=bus).run(graph, ctx, execute)
    if ending == "success":
        assert result["status"] == "success", result
        assert calls == 2
    else:
        assert result["status"] == "failed"
        expected = {
            "exhausted": "retry_exhausted",
            "silent": "reply_timeout",
            "unmatched": "other",
            "send_failed": "other",
            "send_exception": "other",
        }[ending]
        assert result["failure_category"] == expected, result
        if ending == "exhausted":
            assert calls == 4
            assert f"已重试 3 次，最后一次返回：{busy}" in result["error"]
            assert not is_bot_offline_timeout(
                result["error"], failure_category=expected
            )[0]
    assert not bus._subscribers


@pytest.mark.asyncio
async def test_outer_timeout_allows_retry_interval():
    bus = TelegramEventBus()
    wait = WaitEventNode(
        id="wait",
        timeout_seconds=0.01,
        retry_keywords=["繁忙"],
        retry_interval=3.05,
        max_retries=1,
        action_node_id="send",
        metadata={"chat_id": 1},
        on_failure_node_id="FAIL",
    )
    action = ActionNode(id="send", next_node_id="wait")
    calls = 0

    async def execute(node, ctx):
        nonlocal calls
        calls += 1
        await bus.publish(
            TelegramMessageEvent(
                event_id=str(calls),
                chat_id=1,
                message_thread_id=None,
                message_id=calls,
                sender_id=1,
                event_type="NEW_MESSAGE",
                text="繁忙",
                occurred_at=time.time(),
            )
        )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    result = await PulseFlowEngine(event_bus=bus).run(
        ExecutionGraph(entry_node_id="send", nodes={"send": action, "wait": wait}),
        ScopedFlowContext(),
        execute,
    )
    assert result["failure_category"] == "retry_exhausted"
    assert calls == 2


@pytest.mark.asyncio
async def test_task_budget_covers_reply_retries(monkeypatch):
    from unittest.mock import Mock

    from backend.services.sign_task_runner import _runner_prepare_execution

    monkeypatch.setattr(runtime_settings, "_global_settings", lambda: {})
    state = {
        "svc": Mock(),
        "account_name": "dahao",
        "task_name": "Gemini Pixel",
        "raw_task_cfg": {
            "chats": [
                {
                    "chat_id": 1,
                    "actions": [{"action": 1, "text": "/sign", "wait_for_reply": True}],
                }
            ]
        },
    }
    await _runner_prepare_execution(state)
    assert state["task_timeout"] >= 90 * 4 + 10 * 3 + 25 * 4


@pytest.mark.parametrize("steps", [False, True])
def test_explicit_retry_configuration_and_timeout_floor(monkeypatch, steps):
    monkeypatch.setenv("SIGN_TASK_REPLY_TIMEOUT", "200")
    monkeypatch.setattr(
        runtime_settings, "_global_settings", lambda: {"sign_task_reply_timeout": 200}
    )
    if steps:
        chat = SignChatV3(
            chat_id=1,
            steps=[
                FlowStepConfig(
                    step_id="wait",
                    node_type="wait_event",
                    timeout_seconds=5,
                    retry_keywords=["custom"],
                    retry_interval=7,
                    max_retries=0,
                )
            ],
        )
    else:
        chat = SignChatV3(
            chat_id=1,
            actions=[
                SendTextAction(
                    action=1,
                    text="/sign",
                    wait_for_reply=True,
                    reply_timeout_seconds=5,
                    reply_retry_keywords=["custom"],
                    reply_retry_interval=7,
                    reply_retry_max_attempts=0,
                )
            ],
        )
    wait = next(
        n
        for n in GraphNormalizer.from_chat(chat).nodes.values()
        if isinstance(n, WaitEventNode)
    )
    assert (wait.timeout_seconds, wait.retry_interval, wait.max_retries) == (30, 7, 0)
    assert wait.retry_keywords == ["custom"]


def test_failure_categories_and_retry_keyword_variants():
    from backend.services.sign_task_failure import classify_failure
    from tg_signer.core.flow_engine import matches_retry_keyword

    for text in ["再试", "重试", "稍后", "人数较多", "繁忙", "请10秒后"]:
        assert matches_retry_keyword(text, runtime_settings.DEFAULT_RETRY_KEYWORDS)
    assert (
        matches_retry_keyword(
            "失败或者过期当天不可重试", runtime_settings.DEFAULT_RETRY_KEYWORDS
        )
        is None
    )
    assert (
        classify_failure(error="等待机器人回复确认超时（90 秒）", success=False).value
        == "reply_timeout"
    )
    assert (
        classify_failure(
            error="关键词要求重试，已重试 3 次，最后一次返回：繁忙", success=False
        ).value
        == "retry_exhausted"
    )
    assert (
        classify_failure(error="任务执行超时（300秒）", success=False).value
        == "timeout"
    )


@pytest.mark.asyncio
async def test_retry_restarts_flow_from_entry_for_image_action():
    bus = TelegramEventBus()
    engine = PulseFlowEngine(event_bus=bus)
    ctx = ScopedFlowContext()
    calls = []
    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(
                id="send", action_type="SEND_TEXT", next_node_id="click"
            ),
            "click": ActionNode(
                id="click",
                action_type="CHOOSE_OPTION_BY_IMAGE",
                next_node_id="wait",
            ),
            "wait": WaitEventNode(
                id="wait",
                timeout_seconds=0.2,
                retry_interval=0.001,
                max_retries=1,
                retry_keywords=["繁忙"],
                action_node_id="click",
                metadata={"chat_id": 1, "retry_entry_node_id": "send"},
            ),
        },
    )

    async def execute(node, context):
        calls.append(node.id)
        if node.id == "click":
            text = "繁忙" if calls.count("click") == 1 else "签到成功"
            context.system["last_sent_message_id"] = len(calls) * 10

            async def publish_reply():
                await asyncio.sleep(0.001)
                await bus.publish(
                    TelegramMessageEvent(
                        event_id=str(len(calls)),
                        chat_id=1,
                        message_thread_id=None,
                        message_id=len(calls) * 10 + 1,
                        sender_id=1,
                        event_type="NEW_MESSAGE",
                        text=text,
                        occurred_at=time.time(),
                    )
                )

            asyncio.create_task(publish_reply())
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    result = await engine.run(graph, ctx, execute, event_bus=bus)
    assert result["status"] == "success"
    assert calls == ["send", "click", "send", "click"]


@pytest.mark.asyncio
async def test_retry_exhaustion_with_timeout_word_preserves_category():
    from unittest.mock import Mock

    from backend.services.sign_task_runner import _runner_handle_error

    error = RuntimeError(
        "关键词要求重试，已重试 3 次，最后一次返回：TimeoutError，请稍后重试"
    )
    error.failure_category = "retry_exhausted"
    svc = Mock()
    svc._is_invalid_session_error.return_value = False
    state = {
        "svc": svc,
        "account_name": "dahao",
        "task_name": "Gemini Pixel",
        "task_key": "dahao:Gemini Pixel",
        "timed_out": False,
    }
    await _runner_handle_error(state, error)
    assert state["failure_category"] == "retry_exhausted"
    assert state["timed_out"] is False


@pytest.mark.parametrize(
    "text",
    [
        "回答超时，今日不能再签到了，请明天再试",
        "你今天已签到或签到机会已用完 / 总分: 1349",
    ],
)
@pytest.mark.asyncio
async def test_daily_terminal_failure_bypasses_stale_patterns_and_retry(text):
    bus = TelegramEventBus()
    calls = []
    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(id="send", next_node_id="wait"),
            "wait": WaitEventNode(
                id="wait",
                success_patterns=["签到成功"],
                failure_patterns=["签到失败"],
                retry_keywords=["再试"],
                retry_interval=0.001,
                max_retries=1,
                timeout_seconds=0.03,
                metadata={"chat_id": 1},
            ),
        },
    )

    async def execute(node, ctx):
        calls.append(node.id)
        await bus.publish(
            TelegramMessageEvent(
                event_id=str(len(calls)),
                chat_id=1,
                message_thread_id=None,
                message_id=len(calls),
                sender_id=1,
                event_type="NEW_MESSAGE",
                text=text,
                occurred_at=time.time(),
            )
        )
        return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)

    result = await PulseFlowEngine(event_bus=bus).run(
        graph, ScopedFlowContext(), execute
    )
    assert calls == ["send"]
    assert result["status"] == "failed"
    assert text in result["error"]
    assert result["non_retryable"] is True


def test_exhausted_opportunity_is_not_terminal_success():
    from tg_signer.core import UserSigner

    signer = object.__new__(UserSigner)
    assert not signer._text_has_terminal_success_text("你今天已签到或签到机会已用完")
    assert not signer._text_has_terminal_success_text("签到机会已用完")
    assert not signer._text_has_terminal_success_text("今天不能再签到")
    assert signer._text_has_terminal_success_text("今天已签到，请明天再来")


def test_old_default_reply_rules_upgrade_but_custom_rules_survive():
    from tg_signer.reply_settings import (
        DEFAULT_REPLY_FAILURE_PATTERNS,
        DEFAULT_REPLY_SUCCESS_PATTERNS,
    )

    chat = SignChatV3(
        chat_id=1,
        actions=[
            SendTextAction(
                text="/checkin",
                wait_for_reply=True,
                reply_success_patterns=["签到成功"],
                reply_failure_patterns=[r"出席率\s*失败", "签到失败", "操作失败"],
            )
        ],
    )
    wait = next(
        n
        for n in GraphNormalizer.from_chat(chat).nodes.values()
        if isinstance(n, WaitEventNode)
    )
    assert wait.success_patterns == list(DEFAULT_REPLY_SUCCESS_PATTERNS)
    assert wait.failure_patterns == list(DEFAULT_REPLY_FAILURE_PATTERNS)
    chat.actions[0].reply_success_patterns = ["专用成功回复"]
    wait = next(
        n
        for n in GraphNormalizer.from_chat(chat).nodes.values()
        if isinstance(n, WaitEventNode)
    )
    assert wait.success_patterns == ["专用成功回复"]


@pytest.mark.asyncio
async def test_action_wait_stops_on_daily_terminal_reply():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tg_signer.config import ChooseOptionByImageAction
    from tg_signer.core import UserSigner
    from tg_signer.core.context import UserSignerWorkerContext
    from tg_signer.reply_settings import BotTerminalFailure

    signer = object.__new__(UserSigner)
    reply = SimpleNamespace(
        id=101,
        text="回答超时，今日不能再签到了，请明天再试",
        caption=None,
        chat=SimpleNamespace(id=1),
        from_user=SimpleNamespace(is_bot=True),
        message_thread_id=None,
        reply_markup=None,
    )
    signer.context = UserSignerWorkerContext(
        sign_chats={}, chat_messages={1: {101: reply}}
    )
    signer.log = lambda *args, **kwargs: None
    signer._log_received_target_message = lambda *args, **kwargs: None
    signer._choose_option_by_image = AsyncMock()
    with pytest.raises(BotTerminalFailure, match="今日不能再签到"):
        await signer.wait_for(
            SignChatV3(chat_id=1, actions=[SendTextAction(text="/checkin")]),
            ChooseOptionByImageAction(),
            timeout=1,
        )
    signer._choose_option_by_image.assert_not_called()


@pytest.mark.asyncio
async def test_send_moves_directly_to_image_challenge_without_terminal_grace_wait():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tg_signer.config import ChooseOptionByImageAction
    from tg_signer.core import UserSigner

    signer = object.__new__(UserSigner)
    signer.context = SimpleNamespace(stop_after_current_action=False)
    signer._wait_for_terminal_success = AsyncMock()
    await signer._maybe_stop_after_send(
        SignChatV3(chat_id=1, actions=[SendTextAction(text="/checkin")]),
        before_state={},
        history_limit=8,
        next_action=ChooseOptionByImageAction(),
    )
    signer._wait_for_terminal_success.assert_not_called()


def test_saved_graph_reply_defaults_upgrade_without_mutating_source():
    from tg_signer.reply_settings import (
        DEFAULT_REPLY_FAILURE_PATTERNS,
        DEFAULT_REPLY_SUCCESS_PATTERNS,
    )

    source = ExecutionGraph(
        entry_node_id="wait",
        nodes={
            "wait": WaitEventNode(
                id="wait",
                success_patterns=["签到成功"],
                failure_patterns=[r"出席率\s*失败", "签到失败", "操作失败"],
            )
        },
    )
    compiled = GraphNormalizer.compile(source)
    assert compiled.nodes["wait"].success_patterns == list(
        DEFAULT_REPLY_SUCCESS_PATTERNS
    )
    assert compiled.nodes["wait"].failure_patterns == list(
        DEFAULT_REPLY_FAILURE_PATTERNS
    )
    assert source.nodes["wait"].success_patterns == ["签到成功"]


def test_previous_broad_failure_defaults_upgrade():
    from tg_signer.reply_settings import (
        DEFAULT_REPLY_FAILURE_PATTERNS,
        upgrade_reply_patterns,
    )

    previous = [
        "签到失败",
        "打卡失败",
        "操作失败",
        "验证码错误|验证失败",
        r"出席率\s*失败",
        r"(?i)(?:failed|failure|invalid)",
    ]
    assert upgrade_reply_patterns(previous, success=False) == list(
        DEFAULT_REPLY_FAILURE_PATTERNS
    )


@pytest.mark.asyncio
async def test_daily_failure_during_action_keeps_business_category():
    from tg_signer.reply_settings import BotTerminalFailure

    text = "回答超时，今日不能再签到了，请明天再试"

    async def execute(node, ctx):
        raise BotTerminalFailure(text)

    result = await PulseFlowEngine().run(
        ExecutionGraph(entry_node_id="send", nodes={"send": ActionNode(id="send")}),
        ScopedFlowContext(),
        execute,
    )
    assert result["status"] == "failed"
    assert result["failure_category"] == "other"
    assert result["non_retryable"] is True
    assert text in result["error"]


@pytest.mark.asyncio
async def test_image_action_stops_when_bot_reports_already_checked_in():
    from types import SimpleNamespace

    from tg_signer.config import ChooseOptionByImageAction
    from tg_signer.core import UserSigner
    from tg_signer.core.context import UserSignerWorkerContext

    signer = object.__new__(UserSigner)
    reply = SimpleNamespace(
        id=101,
        text="今天已签到，请明天再来",
        caption=None,
        chat=SimpleNamespace(id=1),
        from_user=SimpleNamespace(is_bot=True),
        message_thread_id=None,
        reply_markup=None,
    )
    signer.context = UserSignerWorkerContext(
        sign_chats={}, chat_messages={1: {101: reply}}
    )
    signer.log = lambda *args, **kwargs: None
    signer._log_received_target_message = lambda *args, **kwargs: None
    await signer.wait_for(
        SignChatV3(chat_id=1, actions=[SendTextAction(text="/checkin")]),
        ChooseOptionByImageAction(),
        timeout=0.01,
    )
    assert signer.context.stop_after_current_action
    assert "已签到" in signer.context.stop_reason


@pytest.mark.asyncio
async def test_normal_run_preserves_non_retryable_failure_category():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from tg_signer.config import SignConfigV3
    from tg_signer.core import UserSigner
    from tg_signer.reply_settings import BotTerminalFailure

    signer = object.__new__(UserSigner)
    failure = BotTerminalFailure("回答超时，今日不能再签到了，请明天再试")
    context = SimpleNamespace(last_chat_error=failure, chat_messages={}, sign_chats={})
    config = SignConfigV3(
        sign_at="00:00:00",
        chats=[SignChatV3(chat_id=1, actions=[SendTextAction(text="/checkin")])],
        random_seconds=0,
    )
    signer.user = SimpleNamespace(id=1)
    signer.app = MagicMock(is_connected=True)
    signer.cfg_cls = SignConfigV3
    signer._peers_preheated = True
    signer.load_config = lambda cls: config
    signer.load_sign_record = lambda: {}
    signer.ensure_ctx = lambda: context
    signer._run_config_chats = AsyncMock(return_value=[{"execution_status": "failed"}])
    signer.log = lambda *args, **kwargs: None
    with pytest.raises(BotTerminalFailure) as caught:
        await signer.normal_run(only_once=True, force_rerun=True)
    assert caught.value is failure
    assert caught.value.failure_category == "other"
