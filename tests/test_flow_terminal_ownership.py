from types import SimpleNamespace

import pytest

from tg_signer.config import SendTextAction, SignChatV3
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_models import ActionNode, ExecutionGraph, WaitEventNode
from tg_signer.core.signer_runner import _CutoverNodeExecutor


@pytest.mark.asyncio
async def test_explicit_wait_owns_result_over_legacy_success_signal():
    runner = SimpleNamespace(context=SimpleNamespace(), log=lambda *a, **k: None)

    async def wait_for(*args, **kwargs):
        runner.context.stop_after_current_action = True
        return True

    runner.wait_for = wait_for
    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(
                id="send",
                action_type="SEND_TEXT",
                params={"text": "hi"},
                next_node_id="wait",
            ),
            "wait": WaitEventNode(
                id="wait", timeout_seconds=0.01, metadata={"chat_id": 123}
            ),
        },
    )
    chat = SignChatV3(chat_id=123, actions=[SendTextAction(text="hi")])
    result = await PulseFlowEngine().run(
        graph, ScopedFlowContext(), _CutoverNodeExecutor(runner, chat, graph)
    )
    assert result["status"] == "failed"
    assert result["path"] == ["send", "wait"]
