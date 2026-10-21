from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.sign_task_failure import FailureCategory
from backend.services.sign_task_runner import _runner_handle_error
from tg_signer.core.flow_context import ScopedFlowContext
from tg_signer.core.flow_engine import PulseFlowEngine
from tg_signer.core.flow_models import (
    ActionNode,
    ExecutionGraph,
    NodeStatus,
    StepOutcome,
)
from tg_signer.semantic.models import (
    Decision,
    SemanticReviewRequired,
    SemanticStopRequested,
    TriagePolicy,
)
from tg_signer.semantic.policy import triage_disposition


def test_hard_failure_ignores_model():
    """硬异常保护：即使模型判定为 review/stop，由于硬异常标志仍保持 unchanged"""
    answer = Decision(
        status="ok",
        selected="review",
        probabilities={"review": 1.0, "stop": 0.0, "retryable": 0.0, "unknown": 0.0},
    )
    assert (
        triage_disposition(
            decision=answer,
            policy=TriagePolicy(mode="assist"),
            hard_failure=True,
        )
        == "unchanged"
    )


def test_retry_suggestion_is_advisory_only():
    """模型建议 retryable 仅供参考，代码不生成重试指令，返回 unchanged"""
    answer = Decision(
        status="ok",
        selected="retryable",
        probabilities={"retryable": 1.0},
    )
    assert (
        triage_disposition(
            decision=answer,
            policy=TriagePolicy(mode="assist"),
            hard_failure=False,
        )
        == "unchanged"
    )


def test_triage_disposition_review_and_stop():
    """受控 review 与 stop 的处置判定"""
    pol = TriagePolicy(mode="assist", min_probability=0.95, min_margin=0.2)

    # 达标的 review
    rev_decision = Decision(
        status="ok",
        selected="review",
        probabilities={"review": 0.98, "stop": 0.01, "unknown": 0.01},
    )
    assert (
        triage_disposition(decision=rev_decision, policy=pol, hard_failure=False)
        == "review"
    )

    # 达标的 stop
    stop_decision = Decision(
        status="ok",
        selected="stop",
        probabilities={"stop": 0.96, "review": 0.02, "unknown": 0.02},
    )
    assert (
        triage_disposition(decision=stop_decision, policy=pol, hard_failure=False)
        == "stop"
    )

    # 置信度不足
    low_prob = Decision(
        status="ok",
        selected="stop",
        probabilities={"stop": 0.80, "review": 0.15},
    )
    assert (
        triage_disposition(decision=low_prob, policy=pol, hard_failure=False)
        == "unchanged"
    )

    # observe 模式不改变处置
    obs_pol = TriagePolicy(mode="observe")
    assert (
        triage_disposition(decision=stop_decision, policy=obs_pol, hard_failure=False)
        == "unchanged"
    )


@pytest.mark.asyncio
async def test_flow_engine_controlled_termination_does_not_execute_fallback_node():
    """当节点发生受控终止时，图执行立即终止，绝不跳转至 on_failure_node 或 error_handler"""
    engine = PulseFlowEngine()
    ctx = ScopedFlowContext()

    n1 = ActionNode(
        id="act_1",
        name="触发受控复核",
        action_type="send_text",
        on_failure_node_id="fallback_act",
    )
    n_fallback = ActionNode(
        id="fallback_act",
        name="容错节点",
        action_type="send_text",
    )
    graph = ExecutionGraph(
        entry_node_id="act_1",
        nodes={"act_1": n1, "fallback_act": n_fallback},
        error_handler_node_id="fallback_act",
    )

    fallback_called = False

    async def mock_executor(node, context):
        nonlocal fallback_called
        if node.id == "act_1":
            raise SemanticReviewRequired("机器人提示账号已被风控限制，需人工复核")
        if node.id == "fallback_act":
            fallback_called = True
            return StepOutcome(node_id=node.id, status=NodeStatus.SUCCESS)
        return StepOutcome(node_id=node.id, status=NodeStatus.FAILED)

    res = await engine.run(graph, ctx, mock_executor)
    assert res["status"] == "failed"
    assert fallback_called is False  # 绝对不执行 fallback_act
    assert res.get("failure_code") == "semantic_review_required"
    assert res.get("non_retryable") is True
    assert res.get("semantic_disposition") == "review"


@pytest.mark.asyncio
async def test_signer_runner_controlled_stop_prevents_retry_and_v3_fallback(
    monkeypatch,
):
    """验证启用了语义策略的任务遇到受控停止时：零重试，且即使开启自动回退也绝不降级至 v3"""
    from tg_signer.config import SignChatV3
    from tg_signer.core.signer_runner import SignerRunnerMixin

    monkeypatch.setenv("PULSEFLOW_AUTO_FALLBACK", "true")
    monkeypatch.setenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "3")

    runner = SignerRunnerMixin()
    runner.log = MagicMock()
    runner.context = MagicMock()
    runner.context.pulseflow_side_effect_started = False

    chat = SignChatV3(
        chat_id=12345678,
        actions=[
            {
                "action": 1,
                "text": "签到",
                "semantic_triage": {"mode": "assist", "min_probability": 0.95},
            }
        ],
    )

    flow_run_count = 0
    classic_run_called = False

    async def mock_run(graph, ctx, executor, event_bus=None):
        nonlocal flow_run_count
        flow_run_count += 1
        return {
            "status": "failed",
            "error": "触发受控终止",
            "failure_code": "semantic_stop_requested",
            "non_retryable": True,
            "semantic_disposition": "stop",
            "steps": 1,
            "path": ["step_0"],
        }

    async def mock_classic(c):
        nonlocal classic_run_called
        classic_run_called = True
        return True

    with patch("tg_signer.core.flow_engine.PulseFlowEngine.run", side_effect=mock_run):
        with patch.object(runner, "_run_workflow_chat", side_effect=mock_classic):
            with pytest.raises(SemanticStopRequested):
                await runner._run_pulseflow_chat(chat)

    assert flow_run_count == 1  # 尽管配置了 3 次重试，受控停止使整流程只执行 1 次
    assert classic_run_called is False  # 绝对禁止降级回退 Classic v3


@pytest.mark.asyncio
async def test_runner_handle_error_classification():
    """验证 _runner_handle_error 正确将受控异常映射为专有失败分类"""
    mock_svc = MagicMock()
    mock_svc._is_invalid_session_error.return_value = False

    # 1. 语义复核
    state_review = {
        "svc": mock_svc,
        "task_key": "test_acc:test_task",
        "account_name": "test_acc",
        "task_name": "test_task",
    }
    err_review = SemanticReviewRequired("机器人提示账号已被风控限制，需人工复核")
    await _runner_handle_error(state_review, err_review)
    assert (
        state_review.get("failure_category")
        == FailureCategory.SEMANTIC_REVIEW_REQUIRED.value
    )
    assert state_review.get("failure_code") == "semantic_review_required"

    # 2. 语义停止
    state_stop = {
        "svc": mock_svc,
        "task_key": "test_acc:test_task",
        "account_name": "test_acc",
        "task_name": "test_task",
    }
    err_stop = SemanticStopRequested("机器人明确拒绝并提示不要再次点击")
    await _runner_handle_error(state_stop, err_stop)
    assert (
        state_stop.get("failure_category")
        == FailureCategory.SEMANTIC_STOP_REQUESTED.value
    )
    assert state_stop.get("failure_code") == "semantic_stop_requested"
