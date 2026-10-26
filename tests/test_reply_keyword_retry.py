"""Reply retry regressions without Telegram network access."""

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
