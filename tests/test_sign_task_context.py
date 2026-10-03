from __future__ import annotations

import asyncio

import pytest

from backend.services.sign_task_context import TaskExecutionContext, TaskPhase


def test_task_context_complete_transition_matrix():
    ctx = TaskExecutionContext(account_name="acc1", task_name="task1", run_id="r1")
    assert ctx.phase == TaskPhase.STARTING

    # 1. Disallowed skips
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.RUNNING)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.FINALIZING)

    # 2. Advance to WAITING_LOCK
    ctx.transition_to(TaskPhase.WAITING_LOCK)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.FINALIZING)  # must not skip RUNNING

    # 3. Advance to RUNNING
    ctx.transition_to(TaskPhase.RUNNING)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.FINISHED)  # must not skip FINALIZING

    # 4. Advance to FINALIZING
    ctx.transition_to(TaskPhase.FINALIZING)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.RUNNING)  # cannot go backward

    # 5. Advance to terminal FINISHED
    ctx.transition_to(TaskPhase.FINISHED)

    # 6. Terminal immutability
    for terminal_target in (
        TaskPhase.STARTING,
        TaskPhase.RUNNING,
        TaskPhase.FAILED,
        TaskPhase.CANCELLED,
    ):
        with pytest.raises(ValueError):
            ctx.transition_to(terminal_target)

    # 7. Blackboard dict mutation blocked
    with pytest.raises(TypeError):
        ctx["phase"] = TaskPhase.RUNNING


def test_task_context_transition_to_failed():
    ctx = TaskExecutionContext(account_name="acc1", task_name="task1")
    ctx.transition_to(TaskPhase.WAITING_LOCK)
    ctx.transition_to(TaskPhase.RUNNING)
    ctx.transition_to(TaskPhase.FINALIZING)
    ctx.transition_to(TaskPhase.FAILED)
    assert ctx.phase == TaskPhase.FAILED

    for terminal_target in (
        TaskPhase.STARTING,
        TaskPhase.WAITING_LOCK,
        TaskPhase.RUNNING,
        TaskPhase.FINALIZING,
        TaskPhase.FINISHED,
        TaskPhase.CANCELLED,
    ):
        with pytest.raises(ValueError):
            ctx.transition_to(terminal_target)


def test_task_context_transition_to_cancelled():
    ctx = TaskExecutionContext(account_name="acc1", task_name="task1")
    ctx.transition_to(TaskPhase.WAITING_LOCK)
    ctx.transition_to(TaskPhase.RUNNING)
    ctx.transition_to(TaskPhase.FINALIZING)
    ctx.transition_to(TaskPhase.CANCELLED)
    assert ctx.phase == TaskPhase.CANCELLED

    for terminal_target in (
        TaskPhase.STARTING,
        TaskPhase.WAITING_LOCK,
        TaskPhase.RUNNING,
        TaskPhase.FINALIZING,
        TaskPhase.FINISHED,
        TaskPhase.FAILED,
    ):
        with pytest.raises(ValueError):
            ctx.transition_to(terminal_target)


def test_task_context_disallowed_backward_and_skip_transitions():
    ctx = TaskExecutionContext(account_name="acc1", task_name="task1")
    # Skips from STARTING directly to terminal
    for target in (TaskPhase.FINISHED, TaskPhase.FAILED, TaskPhase.CANCELLED):
        with pytest.raises(ValueError):
            ctx.transition_to(target)

    ctx.transition_to(TaskPhase.WAITING_LOCK)
    # Backward from WAITING_LOCK to STARTING
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.STARTING)
    # Skips from WAITING_LOCK directly to terminal
    for target in (TaskPhase.FINISHED, TaskPhase.FAILED, TaskPhase.CANCELLED):
        with pytest.raises(ValueError):
            ctx.transition_to(target)

    ctx.transition_to(TaskPhase.RUNNING)
    # Backward from RUNNING
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.STARTING)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.WAITING_LOCK)
    # Skips from RUNNING directly to terminal
    for target in (TaskPhase.FAILED, TaskPhase.CANCELLED):
        with pytest.raises(ValueError):
            ctx.transition_to(target)

    ctx.transition_to(TaskPhase.FINALIZING)
    # Backward from FINALIZING
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.STARTING)
    with pytest.raises(ValueError):
        ctx.transition_to(TaskPhase.WAITING_LOCK)


def test_task_context_read_adapter_and_dict_compatibility():
    ctx = TaskExecutionContext(
        account_name="my_acc",
        task_name="my_task",
        run_id="run-123",
    )

    # __getitem__ access
    assert ctx["account_name"] == "my_acc"
    assert ctx["task_name"] == "my_task"
    assert ctx["run_id"] == "run-123"
    assert ctx["phase"] == TaskPhase.STARTING

    with pytest.raises(KeyError):
        _ = ctx["unknown_key"]

    # get() method
    assert ctx.get("account_name") == "my_acc"
    assert ctx.get("unknown_key") is None
    assert ctx.get("unknown_key", "default_val") == "default_val"

    # __contains__
    assert "account_name" in ctx
    assert "unknown_key" not in ctx

    # Direct attribute mutation is permitted
    ctx.error_msg = "test error"
    assert ctx.error_msg == "test error"
    assert ctx["error_msg"] == "test error"
    assert ctx.get("error_msg") == "test error"

    # Dict mutation via __setitem__ is blocked
    with pytest.raises(TypeError):
        ctx["error_msg"] = "should fail"


@pytest.mark.asyncio
async def test_runner_phases_lifecycle_transitions():
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.services.sign_task_runner import (
        _runner_acquire_lock,
        _runner_finalize,
    )

    svc = MagicMock()
    svc._active_logs = {}
    svc._cleanup_tasks = {}
    svc._active_tasks = {}
    svc._account_last_run_end = {}
    svc._account_cooldown_seconds = 0.0

    account_lock = asyncio.Lock()

    ctx = TaskExecutionContext(
        account_name="test_acc",
        task_name="test_task",
        run_id="run-test",
        task_key="test_acc:test_task",
        svc=svc,
        account_lock=account_lock,
    )

    assert ctx.phase == TaskPhase.STARTING

    # Step through acquire lock -> run_task
    with patch(
        "backend.services.sign_task_runner._runner_setup_logging", new_callable=AsyncMock
    ), patch(
        "backend.services.sign_task_runner._runner_resolve_credentials",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_instantiate_signer",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_prepare_execution",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_execute_with_retry",
        new_callable=AsyncMock,
    ):
        await _runner_acquire_lock(ctx)

    assert ctx.phase == TaskPhase.RUNNING
    assert ctx.lock_acquired is True

    # Finalize success
    ctx.success = True
    with patch(
        "backend.services.sign_task_runner._runner_schedule_cleanup",
        new_callable=AsyncMock,
    ):
        await _runner_finalize(ctx)

    assert ctx.phase == TaskPhase.FINISHED


@pytest.mark.asyncio
async def test_runner_phases_lifecycle_transitions_failed():
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.services.sign_task_runner import (
        _runner_acquire_lock,
        _runner_finalize,
    )

    svc = MagicMock()
    svc._active_logs = {}
    svc._cleanup_tasks = {}
    svc._active_tasks = {}
    svc._account_last_run_end = {}
    svc._account_cooldown_seconds = 0.0

    account_lock = asyncio.Lock()

    ctx = TaskExecutionContext(
        account_name="test_acc",
        task_name="test_task",
        run_id="run-test",
        task_key="test_acc:test_task",
        svc=svc,
        account_lock=account_lock,
    )

    with patch(
        "backend.services.sign_task_runner._runner_setup_logging", new_callable=AsyncMock
    ), patch(
        "backend.services.sign_task_runner._runner_resolve_credentials",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_instantiate_signer",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_prepare_execution",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_execute_with_retry",
        new_callable=AsyncMock,
    ):
        await _runner_acquire_lock(ctx)

    assert ctx.phase == TaskPhase.RUNNING

    # Finalize failure
    ctx.success = False
    ctx.error_msg = "Task crashed"
    with patch(
        "backend.services.sign_task_runner._runner_schedule_cleanup",
        new_callable=AsyncMock,
    ):
        await _runner_finalize(ctx)

    assert ctx.phase == TaskPhase.FAILED


@pytest.mark.asyncio
async def test_runner_phases_lifecycle_transitions_cancelled():
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.services.sign_task_runner import (
        _runner_acquire_lock,
        _runner_finalize,
    )

    svc = MagicMock()
    svc._active_logs = {}
    svc._cleanup_tasks = {}
    svc._active_tasks = {}
    svc._account_last_run_end = {}
    svc._account_cooldown_seconds = 0.0

    account_lock = asyncio.Lock()

    ctx = TaskExecutionContext(
        account_name="test_acc",
        task_name="test_task",
        run_id="run-test",
        task_key="test_acc:test_task",
        svc=svc,
        account_lock=account_lock,
    )

    with patch(
        "backend.services.sign_task_runner._runner_setup_logging", new_callable=AsyncMock
    ), patch(
        "backend.services.sign_task_runner._runner_resolve_credentials",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_instantiate_signer",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_prepare_execution",
        new_callable=AsyncMock,
    ), patch(
        "backend.services.sign_task_runner._runner_execute_with_retry",
        new_callable=AsyncMock,
    ):
        await _runner_acquire_lock(ctx)

    assert ctx.phase == TaskPhase.RUNNING

    # Finalize cancelled
    ctx.cancelled = True
    with patch(
        "backend.services.sign_task_runner._runner_schedule_cleanup",
        new_callable=AsyncMock,
    ):
        await _runner_finalize(ctx)

    assert ctx.phase == TaskPhase.CANCELLED

