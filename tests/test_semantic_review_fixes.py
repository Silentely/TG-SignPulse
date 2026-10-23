import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.semantic import apply_suggestion
from backend.services.keyword_monitor.runtime import KeywordMonitorService
from backend.services.semantic import JevServiceConfig
from backend.services.semantic.review import validate_label
from backend.services.semantic.runtime import SemanticRuntime
from backend.services.semantic.store import SemanticStore
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import Decision, DecisionRequest, config_revision
from tg_signer.semantic.runtime_port import (
    get_registered_semantic_runtime,
    register_semantic_runtime_provider,
)


def test_tg_signer_no_backend_imports():
    """HIGH-1: 确保 tg_signer 核心源码内没有任何对 backend 的逆向 import 语句"""
    tg_signer_dir = Path("tg_signer")
    py_files = list(tg_signer_dir.rglob("*.py"))
    assert len(py_files) > 0

    violations = []
    for f in py_files:
        # 允许历史兼容的 template.py 外部数据字典 fallback（若存在），其它所有核心模块严禁依赖 backend
        if f.name == "template.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend"):
                        violations.append((str(f), alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("backend"):
                    violations.append((str(f), node.module))

    assert not violations, f"发现 tg_signer 逆向依赖 backend: {violations}"


def test_runtime_port_provider():
    """HIGH-1 补充: 验证 tg_signer.semantic.runtime_port 注册机制"""
    dummy_runtime = {"name": "dummy"}
    register_semantic_runtime_provider(lambda: dummy_runtime)
    assert get_registered_semantic_runtime() == dummy_runtime

    # 异常提供者应优雅返回 None
    register_semantic_runtime_provider(lambda: 1 / 0)
    assert get_registered_semantic_runtime() is None


def test_runtime_is_current_strict_config_revision(tmp_path: Path):
    """HIGH-2: is_current 严格核对任务的 config_revision 而非仅检查任务存在性"""
    runtime = SemanticRuntime(tmp_path)
    # 模拟 config_store
    runtime.config_store.load = MagicMock(return_value=JevServiceConfig(generation=1))

    sample_task = {
        "name": "task1",
        "sign_at": "09:00",
        "chats": [{"chat_id": 123}],
    }
    actual_rev = config_revision(sample_task)

    mock_task_obj = MagicMock()
    mock_task_obj.dict.return_value = sample_task

    with pytest.MonkeyPatch.context() as mp:
        mock_svc = MagicMock()
        mock_svc.get_task.return_value = mock_task_obj
        mp.setattr("backend.services.sign_tasks.SignTaskService", lambda: mock_svc)

        # 1. 相同 revision 返回 True
        assert (
            runtime.is_current(
                account_name="acc1",
                task_name="task1",
                revision=actual_rev,
                generation=1,
            )
            is True
        )

        # 2. 任务存在但 revision 改变，返回 False
        assert (
            runtime.is_current(
                account_name="acc1",
                task_name="task1",
                revision="different_rev_123",
                generation=1,
            )
            is False
        )

        # 3. 任务不存在返回 False
        mock_svc.get_task.return_value = None
        assert (
            runtime.is_current(
                account_name="acc1",
                task_name="task1",
                revision=actual_rev,
                generation=1,
            )
            is False
        )


def test_record_observation_schema_completeness(tmp_path: Path):
    """HIGH-3: record_observation 记录完整 schema（包括 state, observed_at, reason_code 等）"""
    runtime = SemanticRuntime(tmp_path)
    req = DecisionRequest(
        kind="result",
        scope="acc1:task1:123:node1",
        state={"text": "回复文本", "goal": "签到"},
        choices={"success": "成功", "failure": "失败"},
        instructions="判断回复",
        request_key="req_key_1",
        config_revision="rev_xyz",
    )
    decision = Decision(
        status="ok",
        selected="success",
        confidence=0.99,
        probabilities={"success": 0.99},
        model="system-one",
    )
    runtime.record_observation(req, decision, rule_result="unmatched", run_id="run_999")

    obs = runtime.semantic_store.list_observations()
    assert obs["total"] == 1
    item = obs["items"][0]
    assert item["scope"] == "acc1:task1:123:node1"
    assert item["run_id"] == "run_999"
    assert item["config_revision"] == "rev_xyz"
    assert item["reason_code"] == "rule_unmatched"
    assert item["state"] == {"text": "回复文本", "goal": "签到"}
    assert "observed_at" in item
    assert "created_at" in item


def test_apply_suggestion_cross_task_rejection(tmp_path: Path):
    """HIGH-4: apply_suggestion 严禁覆盖目标账号/任务名称以防跨任务错配"""
    from fastapi import BackgroundTasks, HTTPException

    store = SemanticStore(tmp_path)
    sug_id = store.save_suggestion(
        {
            "account_name": "acc_original",
            "task_name": "task_original",
            "scope": "acc_original:task_original",
            "status": "pending",
            "base_revision": "rev1",
            "patch": {},
        }
    )

    bg = BackgroundTasks()
    # 尝试覆盖为其他账号
    with pytest.raises(HTTPException) as exc_info:
        apply_suggestion(
            id=sug_id,
            background_tasks=bg,
            body={"account_name": "acc_hacker", "task_name": "task_original"},
            store=store,
            sign_task_service=MagicMock(),
            current_user={"username": "user1"},
        )
    assert exc_info.value.status_code == 400
    assert "ACCOUNT_MISMATCH" in exc_info.value.detail


def test_keyword_monitor_edited_handler_lifecycle():
    """HIGH-5: 关键词监听启停时对 EditedMessageHandler 进行完整注册与注销"""
    service = KeywordMonitorService()
    mock_client = MagicMock()
    h1 = (MagicMock(), 0)
    h2 = (MagicMock(), 0)

    service._handler_refs.append(("acc1", mock_client, [h1, h2]))

    # 测试 stop 清理
    async def _run_stop():
        await service.stop()

    import asyncio

    asyncio.run(_run_stop())

    mock_client.remove_handler.assert_any_call(*h1)
    mock_client.remove_handler.assert_any_call(*h2)
    assert len(service._handler_refs) == 0


def test_validate_label_strict():
    """HIGH-6: 标签白名单严格校验"""
    # 合法枚举
    assert validate_label("result", "success") is True
    assert validate_label("result", "failure") is True
    assert validate_label("triage", "retryable") is True
    assert validate_label("button", "correct") is True

    # 非法枚举值
    assert validate_label("result", "arbitrary_unknown_label") is False
    assert validate_label("triage", "invalid_action") is False
    assert validate_label("button", "malicious_script") is False

    # 自由文本型合法性（非空且 <= 64 字符）
    assert validate_label("button_label", "签到打卡") is True
    assert validate_label("button_label", "") is False
    assert validate_label("button_label", "a" * 65) is False

    # 未知 kind 拒绝
    assert validate_label("unknown_kind", "anything") is False


@pytest.mark.asyncio
async def test_jev_client_response_sanitization():
    """MEDIUM-5: JevClient 对服务端返回数据实施严格类型转换与边界截断"""
    client = JevClient(api_key="test", base_url="http://mock")
    req = DecisionRequest(
        kind="result",
        scope="acc:task:1:1",
        state={},
        choices={"yes": "是", "no": "否"},
        instructions="",
        request_key="req_san_1",
        config_revision="rev_1",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "system-one",
        "answers": {
            "decision": {
                "choice": "not_in_choices",  # 非法选项，应被截断为 unknown
                "confidence": 1.5,  # 超界置信度，应被截断为 1.0
                "probabilities": {
                    "yes": "0.8",  # 字符串应被转为 float
                    "bad": "invalid_number",  # 非法数值应被丢弃
                    "negative": -0.5,  # 负数应被丢弃
                },
            }
        },
        "usage": {"input_tokens": "42"},
    }

    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_resp)
    mock_http.is_closed = False
    client._client = mock_http
    dec = await client.query_choice(req, deadline=9999999999.0)

    assert dec.status == "ok"
    assert dec.selected == "unknown"
    assert dec.confidence == 1.0
    assert dec.probabilities == {"yes": 0.8}
    assert dec.input_tokens == 42


def test_standardized_user_agent_format(monkeypatch):
    """验证出站 User-Agent 标准化格式与版本联动"""
    from tg_signer import __version__
    from tg_signer.version import get_user_agent

    # 1. 默认无 APP_VERSION 时回退到引擎版本
    monkeypatch.delenv("APP_VERSION", raising=False)
    ua_default = get_user_agent("Jev")
    assert ua_default == f"TG-SignPulse-Jev/{__version__} (tg-signer/{__version__})"

    # 2. 注入容器环境 APP_VERSION 联动
    monkeypatch.setenv("APP_VERSION", "v3.0.0-beta.1")
    ua_env = get_user_agent("OpenAI")
    assert ua_env == f"TG-SignPulse-OpenAI/3.0.0-beta.1 (tg-signer/{__version__})"

    # 3. 占位版本不覆盖
    monkeypatch.setenv("APP_VERSION", "0.0.0")
    ua_placeholder = get_user_agent("AI")
    assert ua_placeholder == f"TG-SignPulse-AI/{__version__} (tg-signer/{__version__})"


@pytest.mark.asyncio
async def test_semantic_runtime_worker_cancellation_no_duplicate_task_done(
    tmp_path: Path,
):
    runtime = SemanticRuntime(tmp_path)
    runtime.start_workers(num_workers=1)

    req = DecisionRequest(
        kind="result",
        scope="acc:task:1:1",
        state={},
        choices={"yes": "是", "no": "否"},
        instructions="",
        request_key="req_cancel_test",
        config_revision="rev_1",
    )
    import time

    runtime.enqueue_observation(
        req, rule_result="ok", deadline=time.time() + 10.0, run_id="r1"
    )
    await runtime.close()
    assert len(runtime._workers) == 0
