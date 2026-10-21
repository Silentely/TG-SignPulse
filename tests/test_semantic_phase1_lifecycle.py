from pathlib import Path

import pytest

from backend.services.semantic.config import JevConfigStore
from backend.services.semantic.runtime import SemanticRuntime
from tg_signer.semantic.models import Decision, DecisionRequest


@pytest.mark.asyncio
async def test_semantic_phase1_lifecycle(tmp_path: Path):
    # 1. 初始化配置并保存 Jev 密钥
    cfg_store = JevConfigStore(tmp_path)
    cfg_store.save_patch({"enabled": True, "api_key": "mock_key_lifecycle"})
    assert cfg_store.load().enabled is True

    # 2. 运行时与存储注入
    runtime = SemanticRuntime(tmp_path)
    req = DecisionRequest(
        kind="result",
        scope="acc_demo:task_demo",
        state={"text": "恭喜签到成功，获得 10 积分"},
        choices={"success": "成功", "failure": "失败"},
        instructions="确认是否成功",
        request_key="req_lifecycle_1",
        config_revision="rev_1",
    )
    decision = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.99, "failure": 0.01},
        confidence=0.99,
        model="jev-1.13.0",
    )

    # 3. 记录旁路观察
    runtime.record_observation(req, decision, rule_result="success", run_id="run_101")

    # 4. 验证存储与人工打标链路
    store = runtime.semantic_store
    records = store.list_observations(scope="acc_demo:task_demo")
    assert records["total"] == 1
    obs_id = records["items"][0]["id"]
    assert records["items"][0]["selected"] == "success"

    store.label(obs_id, scope="acc_demo:task_demo", label="already_done")
    records_updated = store.list_observations(scope="acc_demo:task_demo")
    assert records_updated["items"][0]["human_label"] == "already_done"

    # 5. 全局关闭服务后状态重置
    cfg_store.save_patch({"enabled": False})
    assert runtime.service is None

    await runtime.close()
