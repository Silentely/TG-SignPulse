# tests/test_flow_step_config.py
import pytest
from pydantic import ValidationError

from tg_signer.config import (
    FlowNodeType,
    FlowStepConfig,
    SendTextAction,
    SignChatV3,
    SupportAction,
    WorkflowConfigError,
    WorkflowStepConfig,
)


def test_legacy_workflow_step_intact():
    step = WorkflowStepConfig(
        step_id="s1",
        action_type=SupportAction.SEND_TEXT,
        config={"text": "hi"},
        next_step_id="COMPLETE",
    )
    assert step.action_type == SupportAction.SEND_TEXT
    assert step.step_id == "s1"


def test_flow_step_config_cases_and_params():
    step = FlowStepConfig(
        step_id="cond_1",
        node_type=FlowNodeType.CONDITION,
        cases=[{"condition": "'OK' in prev.output", "target_id": "step_2"}],
        default_target_id="COMPLETE",
    )
    assert step.node_type == FlowNodeType.CONDITION
    assert len(step.cases) == 1
    assert step.default_target_id == "COMPLETE"


def test_steps_discriminator_preserves_params_without_dropping():
    # 验证 Action 步骤解析为 FlowStepConfig 时，params 字段不被吞掉
    chat = SignChatV3(
        chat_id=123,
        steps=[
            {
                "step_id": "act_1",
                "node_type": "action",
                "action_type": "SEND_TEXT",
                "params": {"text": "hello params"},
                "next_step_id": "COMPLETE",
            }
        ],
    )
    assert isinstance(chat.steps[0], FlowStepConfig)
    assert chat.steps[0].params["text"] == "hello params"
    assert chat.steps[0].node_type == FlowNodeType.ACTION


def test_sign_chat_v3_flow_graph_only_valid():
    chat = SignChatV3(
        chat_id=123,
        flow_graph={
            "entry_node_id": "s1",
            "nodes": {
                "s1": {
                    "id": "s1",
                    "node_type": "delay",
                    "seconds": 2.0,
                    "next_node_id": "_TERMINAL_COMPLETE",
                }
            },
        },
    )
    assert chat.flow_graph is not None
    assert chat.flow_graph["entry_node_id"] == "s1"


def test_sign_chat_v3_rejects_conflicting_sources():
    with pytest.raises(
        (WorkflowConfigError, ValidationError),
        match="actions、steps、flow_graph 只能配置且必须配置其中一个",
    ):
        SignChatV3(
            chat_id=123,
            actions=[SendTextAction(text="hi")],
            flow_graph={"entry_node_id": "s1", "nodes": {}},
        )


def test_sign_chat_v3_rejects_all_empty_sources():
    with pytest.raises(
        (WorkflowConfigError, ValidationError),
        match="actions、steps、flow_graph 只能配置且必须配置其中一个",
    ):
        SignChatV3(chat_id=123)


def test_flow_step_config_validates_node_type_specific_fields():
    # 1. Action 节点缺少 action_type
    with pytest.raises(
        (WorkflowConfigError, ValidationError), match="必须提供 action_type"
    ):
        FlowStepConfig(step_id="act_1", node_type="action")

    # 2. Condition 节点既无 cases 也无 default_target_id
    with pytest.raises((WorkflowConfigError, ValidationError), match="至少一个出口"):
        FlowStepConfig(step_id="cond_1", node_type="condition")

    # 3. Delay 节点延迟为负数
    with pytest.raises(
        (WorkflowConfigError, ValidationError), match="延迟秒数必须非负"
    ):
        FlowStepConfig(step_id="delay_1", node_type="delay", delay_seconds=-1.0)

    # 4. Parallel 节点分支为空
    with pytest.raises(
        (WorkflowConfigError, ValidationError), match="必须配置非空 branches"
    ):
        FlowStepConfig(step_id="par_1", node_type="parallel", branches=[])
