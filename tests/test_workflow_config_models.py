from __future__ import annotations

import pytest
from pydantic import ValidationError

from tg_signer.config import (
    SendTextAction,
    SignChatV3,
    SupportAction,
)


class TestWorkflowConfigModels:
    """工作流步骤模型 WorkflowStepConfig 及 SignChatV3 互斥与校验测试 (Task 1)"""

    def test_workflow_step_config_valid(self):
        from tg_signer.config import WorkflowStepConfig

        step = WorkflowStepConfig(
            step_id="step1",
            action_type=SupportAction.SEND_TEXT,
            config={"text": "hi"},
            next_step_id="step2",
            on_failure_step_id="FAIL",
            allow_loop=True,
            max_retries=2,
        )
        assert step.step_id == "step1"
        assert step.action_type == SupportAction.SEND_TEXT
        assert step.max_retries == 2
        wf_step = step.to_workflow_step()
        assert wf_step.step_id == "step1"
        assert wf_step.allow_loop is True
        assert wf_step.max_retries == 2

    def test_workflow_step_config_invalid_step_id(self):
        from tg_signer.config import WorkflowStepConfig

        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="   ",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi"},
            )

        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="COMPLETE",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi"},
            )

    def test_workflow_step_config_loop_constraints(self):
        from tg_signer.config import WorkflowStepConfig

        # allow_loop=True requires max_retries >= 0
        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi"},
                allow_loop=True,
                max_retries=None,
            )

        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi"},
                allow_loop=True,
                max_retries=-1,
            )

        # allow_loop=False cannot specify max_retries
        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi"},
                allow_loop=False,
                max_retries=1,
            )

    def test_workflow_step_config_action_conflict(self):
        from tg_signer.config import WorkflowStepConfig

        with pytest.raises(ValidationError):
            WorkflowStepConfig(
                step_id="step1",
                action_type=SupportAction.SEND_TEXT,
                config={"text": "hi", "action": SupportAction.SEND_DICE},
            )

    def test_action_from_step_success_and_error(self):
        from tg_signer.config import (
            WorkflowConfigError,
            WorkflowStepConfig,
            action_from_step,
        )

        step = WorkflowStepConfig(
            step_id="step1",
            action_type=SupportAction.SEND_TEXT,
            config={"text": "hello"},
        )
        action = action_from_step(step)
        assert isinstance(action, SendTextAction)
        assert action.text == "hello"

        # Missing text
        invalid_step = WorkflowStepConfig(
            step_id="bad_step",
            action_type=SupportAction.SEND_TEXT,
            config={},
        )
        with pytest.raises(WorkflowConfigError):
            action_from_step(invalid_step)

    def test_sign_chat_v3_steps_and_actions_mutually_exclusive(self):
        from tg_signer.config import WorkflowStepConfig

        step1 = WorkflowStepConfig(
            step_id="s1",
            action_type=SupportAction.SEND_TEXT,
            config={"text": "step 1"},
        )

        # Neither actions nor steps
        with pytest.raises(ValidationError):
            SignChatV3(chat_id=123)

        # Both actions and steps
        with pytest.raises(ValidationError):
            SignChatV3(
                chat_id=123,
                actions=[SendTextAction(text="hi")],
                steps=[step1],
                initial_step_id="s1",
            )

        # Valid steps-only
        chat = SignChatV3(
            chat_id=123,
            steps=[step1],
            initial_step_id="s1",
        )
        assert chat.actions is None
        assert len(chat.steps) == 1
        assert chat.initial_step_id == "s1"
        assert chat.requires_ai is False

    def test_sign_chat_v3_steps_validation(self):
        from tg_signer.config import WorkflowStepConfig

        step1 = WorkflowStepConfig(
            step_id="s1",
            action_type=SupportAction.SEND_TEXT,
            config={"text": "step 1"},
        )

        # Empty steps
        with pytest.raises(ValidationError):
            SignChatV3(chat_id=123, steps=[], initial_step_id="s1")

        # Missing initial_step_id
        with pytest.raises(ValidationError):
            SignChatV3(chat_id=123, steps=[step1])

        # initial_step_id not in steps
        with pytest.raises(ValidationError):
            SignChatV3(chat_id=123, steps=[step1], initial_step_id="s2")

        # Duplicate step_id
        step1_dup = WorkflowStepConfig(
            step_id="s1",
            action_type=SupportAction.SEND_TEXT,
            config={"text": "step 1 dup"},
        )
        with pytest.raises(ValidationError):
            SignChatV3(chat_id=123, steps=[step1, step1_dup], initial_step_id="s1")

    def test_sign_chat_v3_requires_ai_and_updates_for_steps(self):
        from tg_signer.config import WorkflowStepConfig

        step_calc = WorkflowStepConfig(
            step_id="s1",
            action_type=SupportAction.REPLY_BY_CALCULATION_PROBLEM,
            config={"ai_prompt": "solve"},
        )
        chat = SignChatV3(chat_id=123, steps=[step_calc], initial_step_id="s1")
        assert chat.requires_ai is True
        assert chat.requires_updates is True

    def test_chat_config_api_validation(self):
        from backend.api.routes.sign_tasks_v2 import ChatConfig
        from backend.core.pydantic_compat import model_dump
        from backend.services.sign_task_crud import _validate_chats_workflow
        from tg_signer.config import WorkflowConfigError

        # actions only is valid
        cfg_actions = ChatConfig(chat_id=123, actions=[{"action": 1, "text": "hi"}])
        _validate_chats_workflow([model_dump(cfg_actions)])

        # steps only is valid
        cfg_steps = ChatConfig(
            chat_id=123,
            steps=[{"step_id": "s1", "action_type": 1, "config": {"text": "hi"}}],
            initial_step_id="s1",
        )
        _validate_chats_workflow([model_dump(cfg_steps)])

        # both actions and steps is invalid → WorkflowConfigError
        with pytest.raises(WorkflowConfigError):
            _validate_chats_workflow(
                [
                    model_dump(
                        ChatConfig(
                            chat_id=123,
                            actions=[{"action": 1, "text": "hi"}],
                            steps=[{"step_id": "s1", "action_type": 1}],
                        )
                    )
                ]
            )

        # neither actions nor steps is invalid → WorkflowConfigError
        with pytest.raises(WorkflowConfigError):
            _validate_chats_workflow([model_dump(ChatConfig(chat_id=123))])

    def test_sign_chat_v3_to_jsonable_legacy_compatibility(self):
        from tg_signer.config import WorkflowStepConfig

        # Legacy actions chat
        chat_actions = SignChatV3(chat_id=123, actions=[SendTextAction(text="hi")])
        dump_actions = chat_actions.to_jsonable()
        assert "actions" in dump_actions
        assert "steps" not in dump_actions
        assert "initial_step_id" not in dump_actions

        # Steps chat
        step = WorkflowStepConfig(step_id="s1", action_type=SupportAction.SEND_TEXT, config={"text": "hi"})
        chat_steps = SignChatV3(chat_id=123, steps=[step], initial_step_id="s1")
        dump_steps = chat_steps.to_jsonable()
        assert "steps" in dump_steps
        assert "initial_step_id" in dump_steps
        assert "actions" not in dump_steps

    def test_sign_chat_v3_str_formatting(self):
        from tg_signer.config import WorkflowStepConfig

        step = WorkflowStepConfig(step_id="s1", action_type=SupportAction.SEND_TEXT, config={"text": "hi"})
        chat_steps = SignChatV3(chat_id=123, steps=[step], initial_step_id="s1")
        s = str(chat_steps)
        assert "Workflow Steps Flow:" in s
        assert "[s1]" in s
