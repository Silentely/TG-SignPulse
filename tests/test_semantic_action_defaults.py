"""Action defaults apply only through a configured JEV runtime."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.semantic import JevServiceConfig
from backend.services.semantic.runtime import SemanticRuntime
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import NodeStatus, WaitEventNode
from tg_signer.semantic.action_policy import resolve_action_semantic_policy
from tg_signer.semantic.models import Decision


@pytest.mark.parametrize(
    "value,mode",
    [
        (None, "assist"),
        ({}, "assist"),
        ({"mode": "off"}, "off"),
        ({"mode": "observe"}, "observe"),
    ],
)
def test_defaults_keep_explicit_modes(value, mode):
    assert resolve_action_semantic_policy(value)["mode"] == mode


@pytest.mark.parametrize(
    "enabled,key", [(False, "configured-key"), (True, ""), (False, "")]
)
def test_runtime_without_enabled_credentials_has_no_client(
    tmp_path, monkeypatch, enabled, key
):
    runtime = SemanticRuntime(tmp_path)
    monkeypatch.setattr(
        runtime.config_store,
        "load",
        lambda: JevServiceConfig(enabled=enabled, api_key=key),
    )
    client = MagicMock()
    monkeypatch.setattr("backend.services.semantic.runtime.JevClient", client)
    assert runtime.service is None
    client.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy,available,expected",
    [
        (None, True, NodeStatus.SUCCESS),
        ({"mode": "off"}, True, NodeStatus.TIMEOUT),
        (None, False, NodeStatus.TIMEOUT),
    ],
)
async def test_reply_default_assist_and_visible_logs(
    monkeypatch, policy, available, expected
):
    service = SimpleNamespace(
        evaluate=AsyncMock(
            return_value=Decision(
                status="ok",
                selected="already_done",
                probabilities={"already_done": 0.99, "unknown": 0.01},
                confidence=0.99,
            )
        )
    )
    runtime = SimpleNamespace(
        service=service if available else None, record_observation=MagicMock()
    )
    monkeypatch.setattr(
        "tg_signer.semantic.runtime_port.get_registered_semantic_runtime",
        lambda: runtime,
    )
    bus = TelegramEventBus()
    text = "今天的奖励已经领完了"
    await bus.publish(
        TelegramMessageEvent(
            event_id="",
            chat_id=100,
            message_id=1,
            message_thread_id=None,
            sender_id=200,
            event_type="NEW_MESSAGE",
            text=text,
            occurred_at=time.time(),
        )
    )
    node = WaitEventNode(
        id="wait",
        metadata={"chat_id": 100, "min_message_id": 0},
        success_patterns=["签到成功"],
        semantic_result=policy,
        timeout_seconds=0.02,
    )
    context = ScopedFlowContext()
    logs = []
    context.system["log"] = lambda message, **kwargs: logs.append(message)

    outcome = await PulseFlowEngine()._run_wait_event_node(node, context, bus)

    assert outcome.status == expected
    if expected == NodeStatus.SUCCESS:
        request = service.evaluate.call_args.args[0]
        assert request.state["text"] == text
        assert request.state["goal"]
        assert any("[JEV 回复] 开始语义判断" in log and text in log for log in logs)
        assert any(
            "[JEV 回复] 判断返回" in log
            and "already_done" in log
            and "处理=success" in log
            for log in logs
        )
    else:
        service.evaluate.assert_not_awaited()
        assert not any("开始语义判断" in log for log in logs)
        if not available:
            assert any("[JEV 回复] 未调用" in log for log in logs)
