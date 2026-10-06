from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.events import _sign_log_sse_bytes
from backend.services.sign_task_failure import (
    FailureCategory,
    classify_failure,
    failure_category_label,
)
from backend.services.sign_task_runner import execute_sign_task
from tests.test_sign_task_runner import FakeSvc
from tg_signer.core.workflow_engine import WorkflowLoopExceededError


def test_workflow_loop_exceeded_classification():
    cat = classify_failure(
        error="WorkflowLoopExceededError: 步骤 s1 执行次数 (3) 超过允许上限 2",
        output="",
        success=False,
    )
    assert cat == FailureCategory.TASK_LOOP_EXCEEDED
    assert (
        failure_category_label(FailureCategory.TASK_LOOP_EXCEEDED) == "工作流循环熔断"
    )


@pytest.mark.asyncio
async def test_runner_workflow_loop_exceeded_sets_category_and_no_chain(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class FailingSigner:
        def __init__(self, *args, **kwargs):
            self.context = MagicMock()
            self.context.workflow_path = ["s1", "s1", "s1"]
            self.context.workflow_steps = 3

        async def run_once(self, *args, **kwargs):
            raise WorkflowLoopExceededError("执行已达最大步数硬上限 25")

    fake_svc = FakeSvc(
        task_cfg={
            "chats": [],
            "next_task_on_success": "chained_task",
        }
    )

    with (
        patch("backend.services.sign_task_backend.BackendUserSigner", FailingSigner),
        patch("backend.services.sign_task_runner._runner_check_account"),
        patch(
            "backend.services.sign_task_runner._runner_trigger_chained_task"
        ) as mock_chain,
    ):
        res = await execute_sign_task(
            fake_svc,
            "acc1",
            "wf_task",
        )

        assert res["success"] is False
        assert res["failure_category"] == FailureCategory.TASK_LOOP_EXCEEDED.value
        mock_chain.assert_not_called()


def test_workflow_path_sse_serialization():
    item = {
        "account_name": "acc1",
        "task_name": "wf_task",
        "success": True,
        "bot_message": "ok",
        "created_at": "2026-10-06T12:00:00Z",
        "failure_category": None,
        "workflow_path": ["s1", "s2"],
    }
    raw_bytes = _sign_log_sse_bytes(item)
    assert b'"workflow_path": ["s1", "s2"]' in raw_bytes


@pytest.mark.asyncio
async def test_runner_workflow_path_passed_to_save_run_info(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    class SuccessSigner:
        def __init__(self, *args, **kwargs):
            self.context = MagicMock()
            self.context.workflow_path = ["s1", "s2"]
            self.context.workflow_steps = 2

        async def run_once(self, *args, **kwargs):
            return True

    class FakeWfSvc(FakeSvc):
        def _save_run_info(
            self,
            task_name,
            success,
            msg,
            account_name,
            flow_logs=None,
            workflow_path=None,
        ):
            self.saved.append(
                {
                    "task": task_name,
                    "success": success,
                    "msg": msg,
                    "account": account_name,
                    "logs": list(flow_logs or []),
                    "workflow_path": workflow_path,
                }
            )

    fake_svc = FakeWfSvc(
        task_cfg={
            "chats": [],
        }
    )

    with (
        patch("backend.services.sign_task_backend.BackendUserSigner", SuccessSigner),
        patch("backend.services.sign_task_runner._runner_check_account"),
    ):
        res = await execute_sign_task(
            fake_svc,
            "acc1",
            "wf_task",
        )

        assert res["success"] is True
        assert res["workflow_path"] == ["s1", "s2"]
        assert len(fake_svc.saved) == 1
        assert fake_svc.saved[0].get("workflow_path") == ["s1", "s2"]
