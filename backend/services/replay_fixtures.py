"""Replay sanitized event sequences through PulseFlow without external I/O."""

from __future__ import annotations

import time
from typing import Any

from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_event_bus import TelegramEventBus, TelegramMessageEvent
from tg_signer.core.flow_models import ExecutionGraph, NodeStatus, StepOutcome


async def replay_fixture(
    fixture: dict[str, Any], graph: ExecutionGraph
) -> dict[str, Any]:
    if fixture.get("version") != 1:
        raise ValueError("Unsupported fixture version")
    events = fixture.get("events", [])
    if not isinstance(events, list) or len(events) > 100:
        raise ValueError("Fixture events must be a list with at most 100 items")
    bus = TelegramEventBus()
    plan = []
    for raw in events:
        if not isinstance(raw, dict) or raw.get("event_type", "NEW_MESSAGE") not in {
            "NEW_MESSAGE",
            "EDITED_MESSAGE",
        }:
            raise ValueError("Unsupported fixture event")
        ev = TelegramMessageEvent(
            event_id="replay",
            chat_id=int(raw["chat_id"]),
            message_thread_id=raw.get("message_thread_id"),
            message_id=int(raw["message_id"]),
            sender_id=raw.get("sender_id"),
            event_type=raw.get("event_type", "NEW_MESSAGE"),
            text=str(raw.get("text", ""))[:4000],
            occurred_at=time.time(),
            is_outgoing=bool(raw.get("is_outgoing", False)),
            button_snapshot=tuple(raw.get("buttons", [])),
        )
        await bus.publish(ev, include_legacy_scope=True)

    async def execute(node, ctx):
        kind = str(getattr(node, "action_type", "")).upper()
        if kind in {"CUSTOM_PLUGIN", "99"}:
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text="Plugin execution is disabled during replay",
            )
        allowed = {
            "SEND_TEXT",
            "1",
            "SEND_DICE",
            "CLICK_KEYBOARD_BY_TEXT",
            "CLICK_KEYBOARD",
            "2",
        }
        if kind not in allowed:
            return StepOutcome(
                node_id=node.id,
                status=NodeStatus.FAILED,
                output_text=f"Unsupported replay action: {kind}",
            )
        row = {
            "node_id": node.id,
            "action_type": kind,
            "params": getattr(node, "params", {}),
        }
        if "CLICK" in kind:
            requested = row["params"].get("text")
            buttons = [
                b
                for event in events
                for group in event.get("buttons", [])
                for b in group
            ]
            if requested and not any(
                (b.get("text") if isinstance(b, dict) else b[0]) == requested
                for b in buttons
            ):
                return StepOutcome(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    output_text="Fixture button not found",
                )
        plan.append(row)
        return StepOutcome(
            node_id=node.id,
            status=NodeStatus.SUCCESS,
            output_text="",
            updates_last_output=False,
        )

    result = await PulseFlowEngine(event_bus=bus).run(
        graph, ScopedFlowContext(), execute
    )
    result["side_effect_plan"] = plan
    result["simulation"] = True
    return result
