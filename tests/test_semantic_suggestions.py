from __future__ import annotations

import re

import pytest

from backend.services.semantic.suggestions import (
    build_literal_patch,
    locate_rule,
)


def test_result_patch_is_literal_not_generated_regex():
    """成功规则补丁必须是字面转义 (re.escape)，绝不能由模型自由生成未知正则"""
    observed_text = "恭喜获得签到奖励 +100 [已到账]"
    patch = build_literal_patch(
        kind="success_text",
        path="/chats/0/actions/0/reply_success_patterns",
        old_value=["签到成功"],
        observed_value=observed_text,
    )
    assert patch["op"] == "replace"
    assert patch["path"] == "/chats/0/actions/0/reply_success_patterns"
    expected_escaped = re.escape(observed_text)
    assert expected_escaped in patch["value"]
    assert "签到成功" in patch["value"]


def test_button_label_patch_replaces_text_cleanly():
    """按钮文案补丁严格替换为观察到的实际按钮文本"""
    patch = build_literal_patch(
        kind="button_label",
        path="/chats/0/actions/1/text",
        old_value="签到",
        observed_value="领取今日签到奖励",
    )
    assert patch["op"] == "replace"
    assert patch["path"] == "/chats/0/actions/1/text"
    assert patch["old"] == "签到"
    assert patch["value"] == "领取今日签到奖励"


def test_cannot_patch_schedule_or_credentials():
    """安全护栏：严禁对 sign_at、会话账号或非允许路径生成任何补丁"""
    with pytest.raises(ValueError, match="SEMANTIC_PATCH_UNSUPPORTED"):
        build_literal_patch(
            kind="button_label",
            path="/sign_at",
            old_value="08:00",
            observed_value="09:00",
        )

    with pytest.raises(ValueError, match="SEMANTIC_PATCH_UNSUPPORTED"):
        build_literal_patch(
            kind="success_text",
            path="/chats/0/chat_id",
            old_value=12345,
            observed_value="67890",
        )


def test_monitor_intent_requires_explicit_reviewer_intent():
    """意图修改必须来自人工审核者明确指定的 reviewer_intent，模型不得自由改写"""
    with pytest.raises(ValueError, match="REVIEWER_INTENT_REQUIRED"):
        build_literal_patch(
            kind="monitor_intent",
            path="/chats/0/actions/0/semantic_monitor/intent",
            old_value="领取空投",
            observed_value="自动提醒",
            reviewer_intent=None,
        )

    patch = build_literal_patch(
        kind="monitor_intent",
        path="/chats/0/actions/0/semantic_monitor/intent",
        old_value="领取空投",
        observed_value="自动提醒",
        reviewer_intent="抢领最新奖励",
    )
    assert patch["value"] == "抢领最新奖励"


def test_locate_rule_by_chat_and_node():
    """根据 chat_id 与 action/node 索引准确生成唯一 JSON Pointer 路径"""
    config = {
        "chats": [
            {
                "chat_id": 1001,
                "actions": [
                    {"action": 1, "text": "签到"},
                    {
                        "action": 3,
                        "text": "点击按钮",
                        "reply_success_patterns": ["成功"],
                    },
                ],
            },
            {
                "chat_id": 1002,
                "actions": [{"action": 1, "text": "ping"}],
            },
        ]
    }

    path = locate_rule(
        config,
        chat_id=1001,
        thread_id=None,
        node_id="step_1",  # 第 2 个 action
        leaf="text",
    )
    assert path == "/chats/0/actions/1/text"


def test_locate_rule_raises_on_unmatched():
    """无法唯一定位时抛出 ValueError，绝不随意猜测路径"""
    config = {"chats": [{"chat_id": 1001, "actions": []}]}
    with pytest.raises(ValueError, match="LOCATOR_NOT_FOUND"):
        locate_rule(config, chat_id=9999, thread_id=None, node_id="step_0", leaf="text")
