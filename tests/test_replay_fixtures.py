import pytest

from tg_signer.core.flow_models import ActionNode, ExecutionGraph, WaitEventNode


@pytest.mark.asyncio
async def test_replay_uses_real_wait_rules_without_sending_telegram():
    from backend.services.replay_fixtures import replay_fixture

    graph = ExecutionGraph(
        entry_node_id="send",
        nodes={
            "send": ActionNode(
                id="send",
                action_type="SEND_TEXT",
                params={"text": "/hello"},
                next_node_id="wait",
            ),
            "wait": WaitEventNode(
                id="wait",
                success_patterns=["confirmed"],
                timeout_seconds=0.1,
                metadata={"chat_id": 123},
            ),
        },
    )
    fixture = {
        "version": 1,
        "events": [{"chat_id": 123, "message_id": 2, "text": "confirmed"}],
    }
    first = await replay_fixture(fixture, graph)
    second = await replay_fixture(fixture, graph)
    assert first["status"] == second["status"] == "success"
    assert first["path"] == ["send", "wait"]
    assert first["side_effect_plan"][0]["action_type"] == "SEND_TEXT"


@pytest.mark.asyncio
async def test_replay_refuses_plugin_code_and_unknown_fixture_operations():
    from backend.services.replay_fixtures import replay_fixture

    graph = ExecutionGraph(
        entry_node_id="a",
        nodes={
            "a": ActionNode(
                id="a", action_type="CUSTOM_PLUGIN", params={"plugin_name": "arbitrary"}
            )
        },
    )
    result = await replay_fixture({"version": 1, "events": []}, graph)
    assert result["status"] == "failed"
    with pytest.raises(ValueError, match="version"):
        await replay_fixture({"version": 99, "events": []}, graph)
