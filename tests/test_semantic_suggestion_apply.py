from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.routes.semantic import get_semantic_store
from backend.core.auth import get_current_user
from backend.main import app
from backend.services.semantic.store import SemanticStore
from backend.services.semantic.suggestions import apply_checked_patch
from backend.services.sign_task_crud import SignTaskCrudMixin
from backend.services.task_config_io import TaskConfigConflict
from tg_signer.semantic.models import config_revision


class DummySignTaskService(SignTaskCrudMixin):
    def __init__(self, signs_dir: Path):
        self.signs_dir = signs_dir
        self.tasks_cache = {}

    def _resolve_task_dir(self, task_name: str, account_name: str) -> Path:
        return self.signs_dir / account_name / task_name

    def invalidate_tasks_cache(self, account_name: str | None = None) -> None:
        self.tasks_cache.clear()


def test_apply_checked_patch_valid():
    cfg = {
        "chats": [
            {
                "chat_id": 123,
                "actions": [
                    {"type": "button", "text": "旧按钮"},
                    {"type": "message", "reply_success_patterns": ["成功"]},
                ],
            }
        ]
    }

    # 1. 替换按钮文本
    p1 = {"op": "replace", "path": "/chats/0/actions/0/text", "value": "新按钮"}
    res1 = apply_checked_patch(cfg, p1)
    assert res1["chats"][0]["actions"][0]["text"] == "新按钮"
    # 原对象保持不可变
    assert cfg["chats"][0]["actions"][0]["text"] == "旧按钮"

    # 2. 替换 reply_success_patterns 列表
    p2 = {
        "op": "replace",
        "path": "/chats/0/actions/1/reply_success_patterns",
        "value": ["成功", "打卡成功"],
    }
    res2 = apply_checked_patch(cfg, p2)
    assert res2["chats"][0]["actions"][1]["reply_success_patterns"] == [
        "成功",
        "打卡成功",
    ]


def test_apply_checked_patch_forbidden_path():
    cfg = {"sign_at": "08:00", "chats": []}
    # 试图修改保护路径 /sign_at
    p = {"op": "replace", "path": "/sign_at", "value": "09:00"}
    with pytest.raises(ValueError, match="SEMANTIC_PATCH_UNSUPPORTED"):
        apply_checked_patch(cfg, p)

    # 试图修改非白名单叶子字段
    p_bad_leaf = {"op": "replace", "path": "/chats/0/actions/0/danger", "value": "x"}
    with pytest.raises(ValueError, match="SEMANTIC_PATCH_UNSUPPORTED"):
        apply_checked_patch(cfg, p_bad_leaf)


def test_sign_task_crud_apply_semantic_patch(tmp_path: Path):
    signs_dir = tmp_path / "signs"
    service = DummySignTaskService(signs_dir)

    task_dir = signs_dir / "acc1" / "daily"
    task_dir.mkdir(parents=True)
    initial_cfg = {
        "sign_at": "08:00",
        "chats": [
            {
                "chat_id": 1001,
                "actions": [{"type": "button", "text": "签到"}],
            }
        ],
    }
    (task_dir / "config.json").write_text(json.dumps(initial_cfg), encoding="utf-8")
    rev = config_revision(initial_cfg)

    # 1. 正常应用
    patch = {"op": "replace", "path": "/chats/0/actions/0/text", "value": "每日签到"}
    service.apply_semantic_patch(
        account_name="acc1",
        task_name="daily",
        expected_revision=rev,
        patch=patch,
    )
    saved_cfg = json.loads((task_dir / "config.json").read_text(encoding="utf-8"))
    assert saved_cfg["chats"][0]["actions"][0]["text"] == "每日签到"

    # 2. 版本冲突（外部并发修改导致 revision 不匹配）
    (task_dir / "config.json").write_text(
        json.dumps({**saved_cfg, "sign_at": "09:00"}), encoding="utf-8"
    )
    with pytest.raises(TaskConfigConflict):
        service.apply_semantic_patch(
            account_name="acc1",
            task_name="daily",
            expected_revision=rev,  # 使用陈旧版本号
            patch=patch,
        )


def test_api_apply_suggestion_flow(tmp_path: Path):
    store = SemanticStore(tmp_path / "semantic")
    signs_dir = tmp_path / "signs"
    service = DummySignTaskService(signs_dir)

    task_dir = signs_dir / "acc1" / "daily"
    task_dir.mkdir(parents=True)
    initial_cfg = {
        "sign_at": "08:00",
        "chats": [
            {
                "chat_id": 1001,
                "actions": [{"type": "button", "text": "签到"}],
            }
        ],
    }
    (task_dir / "config.json").write_text(json.dumps(initial_cfg), encoding="utf-8")
    base_rev = config_revision(initial_cfg)

    from backend.services.sign_tasks import get_sign_task_service

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    app.dependency_overrides[get_semantic_store] = lambda: store
    app.dependency_overrides[get_sign_task_service] = lambda: service

    client = TestClient(app)

    # 记录一条待处理建议
    s_id = store.save_suggestion(
        {
            "scope": "acc1:daily",
            "account_name": "acc1",
            "task_name": "daily",
            "kind": "button_label",
            "base_revision": base_rev,
            "patch": {
                "op": "replace",
                "path": "/chats/0/actions/0/text",
                "old": "签到",
                "value": "领奖",
            },
        }
    )

    # 应用建议
    resp = client.post(f"/api/semantic/suggestions/{s_id}/apply")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "applied"
    assert data["suggestion_id"] == s_id

    # 验证文件已经被改写
    saved_cfg = json.loads((task_dir / "config.json").read_text(encoding="utf-8"))
    assert saved_cfg["chats"][0]["actions"][0]["text"] == "领奖"

    # 重复应用拦截（不再是 pending 状态）
    resp_again = client.post(f"/api/semantic/suggestions/{s_id}/apply")
    assert resp_again.status_code == 400

    # 再次创建一条建议，但模拟版本冲突
    s_conflict_id = store.save_suggestion(
        {
            "scope": "acc1:daily",
            "account_name": "acc1",
            "task_name": "daily",
            "kind": "button_label",
            "base_revision": "outdated_rev_123456",
            "patch": {
                "op": "replace",
                "path": "/chats/0/actions/0/text",
                "old": "领奖",
                "value": "再签",
            },
        }
    )
    resp_conflict = client.post(f"/api/semantic/suggestions/{s_conflict_id}/apply")
    assert resp_conflict.status_code == 409
    assert "SEMANTIC_CONFIG_CHANGED" in resp_conflict.json()["detail"]
