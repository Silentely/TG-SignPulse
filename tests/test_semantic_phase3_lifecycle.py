from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.drift import collect_drift_candidates
from backend.services.semantic.store import SemanticStore
from backend.services.semantic.suggestions import build_literal_patch, locate_rule
from backend.services.sign_task_crud import SignTaskCrudMixin
from backend.services.sign_tasks import get_sign_task_service
from tg_signer.semantic.models import config_revision


class DummySignTaskService(SignTaskCrudMixin):
    def __init__(self, signs_dir: Path):
        self.signs_dir = signs_dir
        self.tasks_cache = {}

    def _resolve_task_dir(self, task_name: str, account_name: str) -> Path:
        return self.signs_dir / account_name / task_name

    def invalidate_tasks_cache(self, account_name: str | None = None) -> None:
        self.tasks_cache.clear()


def test_semantic_phase3_full_lifecycle(tmp_path: Path):
    """
    Phase 3 全生命周期集成测试：
    基线标注 -> 多 run 未匹配证据 -> 漂移候选检测 -> 建议生成 -> 409 冲突防护 -> 原子落地与状态流转
    """
    store = SemanticStore(tmp_path / "semantic")
    signs_dir = tmp_path / "signs"
    service = DummySignTaskService(signs_dir)

    task_dir = signs_dir / "user_a" / "checkin"
    task_dir.mkdir(parents=True)

    initial_config = {
        "sign_at": "09:00",
        "chats": [
            {
                "chat_id": 99901,
                "actions": [
                    {
                        "type": "button",
                        "text": "签到打卡",
                        "reply_success_patterns": ["打卡成功"],
                    }
                ],
            }
        ],
    }
    (task_dir / "config.json").write_text(json.dumps(initial_config), encoding="utf-8")
    base_rev = config_revision(initial_config)

    app.dependency_overrides[get_current_user] = lambda: {"username": "tester"}
    app.dependency_overrides[get_semantic_store] = lambda: store
    app.dependency_overrides[get_sign_task_service] = lambda: service

    client = TestClient(app)

    # 1. 人工确认标签并自动建立基线
    obs_id = store.append(
        {
            "scope": "user_a:checkin",
            "account_name": "user_a",
            "task_name": "checkin",
            "config_revision": base_rev,
            "run_id": "run_base",
            "kind": "button_label",
            "request_key": "req_base",
            "selected": "签到打卡",
        }
    )
    store.label(obs_id, scope="user_a:checkin", label="签到打卡")
    baseline = store.get_baseline(scope="user_a:checkin", config_revision=base_rev)
    assert baseline is not None
    assert baseline["expected"] == "签到打卡"

    # 2. 累积多次 run 的未匹配证据（同一 revision 下跨至少 2 个 run 累积 >=3 条证据）
    for i in range(3):
        store.append(
            {
                "scope": "user_a:checkin",
                "account_name": "user_a",
                "task_name": "checkin",
                "config_revision": base_rev,
                "run_id": f"run_{i % 2}",  # 2 个不同的 run_id
                "kind": "button_label",
                "request_key": f"req_drift_{i}",
                "reason_code": "button_missing",
                "text": "每日福利",
            }
        )

    obs_records = store.list_observations(scope="user_a:checkin")["items"]
    now = datetime.now(timezone.utc)
    drift_candidates = collect_drift_candidates(
        baseline=baseline,
        observations=obs_records,
        now=now,
    )
    assert len(drift_candidates) == 1
    drift = drift_candidates[0]
    assert drift["evidence_count"] >= 3
    assert drift["samples"][0] == "每日福利"

    # 3. 构造精准字面补丁
    target_path = locate_rule(
        initial_config, chat_id=99901, node_id="act_0", leaf="text"
    )
    patch = build_literal_patch(
        kind="button_label",
        path=target_path,
        old_value=initial_config["chats"][0]["actions"][0]["text"],
        observed_value=drift["samples"][0],
    )
    assert patch["op"] == "replace"
    assert patch["path"] == "/chats/0/actions/0/text"
    assert patch["value"] == "每日福利"

    sug_id = store.save_suggestion(
        {
            "scope": "user_a:checkin",
            "account_name": "user_a",
            "task_name": "checkin",
            "kind": "button_label",
            "base_revision": base_rev,
            "patch": patch,
            "confidence": 0.96,
        }
    )

    # 4. 模拟配置被外部并发改写（导致 revision 改变）
    concurrent_config = {**initial_config, "sign_at": "10:30"}
    (task_dir / "config.json").write_text(
        json.dumps(concurrent_config), encoding="utf-8"
    )

    # 尝试应用建议 -> 必须返回 409 拦截
    conflict_resp = client.post(f"/api/semantic/suggestions/{sug_id}/apply")
    assert conflict_resp.status_code == 409
    assert "SEMANTIC_CONFIG_CHANGED" in conflict_resp.json()["detail"]

    # 5. 还原配置并由当前基线版本原子采纳建议
    (task_dir / "config.json").write_text(json.dumps(initial_config), encoding="utf-8")
    apply_resp = client.post(f"/api/semantic/suggestions/{sug_id}/apply")
    assert apply_resp.status_code == 200
    data = apply_resp.json()
    assert data["status"] == "applied"

    # 校验最终写入配置
    final_config = json.loads((task_dir / "config.json").read_text(encoding="utf-8"))
    assert final_config["chats"][0]["actions"][0]["text"] == "每日福利"

    # 6. 再次尝试应用 -> 必须被 400 拦截（不可重复应用）
    repeat_resp = client.post(f"/api/semantic/suggestions/{sug_id}/apply")
    assert repeat_resp.status_code == 400
