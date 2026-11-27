"""任务模板实体与引用同步测试。

覆盖:
- 模板 JSON 存储的创建/列出/更新与持久化
- 更新模板时仅同步引用它的任务,公共字段覆盖、账号私有字段与 enabled 保留
- 解绑后不再接收同步
- 任务配置 template_id 的构建与更新语义
- 模板 API 路由已挂载
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.sign_task_config_build import (
    build_sign_task_config,
    resolve_update_field_values,
)
from backend.services.sign_task_templates import (
    TaskTemplateStore,
    list_tasks_using_template,
    sync_template_to_tasks,
)


class _FakeSvc:
    def __init__(self, workdir: Path, configs: list[dict]):
        self.workdir = workdir
        self.signs_dir = workdir / "signs"
        self._configs = configs
        self.refreshed = 0

    def list_tasks(self, force_refresh: bool = False):
        return [dict(cfg) for cfg in self._configs]

    def _resolve_task_dir(self, task_name: str, account_name: str):
        task_dir = self.signs_dir / account_name / task_name
        return task_dir if (task_dir / "config.json").exists() else None

    def _refresh_tasks_cache_after_write(self):
        self.refreshed += 1


def _write_task(workdir: Path, account: str, name: str, **fields) -> dict:
    task_dir = workdir / "signs" / account / name
    task_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "account_name": account,
        "account_names": [account],
        "name": name,
        "enabled": True,
        "sign_at": "08:00",
        "chats": [{"chat_id": 1}],
        **fields,
    }
    (task_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8"
    )
    return cfg


def _read_task(workdir: Path, account: str, name: str) -> dict:
    path = workdir / "signs" / account / name / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_template_store_crud(tmp_path):
    store = TaskTemplateStore(tmp_path)
    created = store.create_template(
        name="每日签到", description="desc", fields={"sign_at": "09:00"}
    )
    assert created["id"]
    assert created["fields"] == {"sign_at": "09:00"}

    assert [t["id"] for t in store.list_templates()] == [created["id"]]
    assert store.get_template(created["id"])["name"] == "每日签到"

    updated = store.update_template(
        created["id"], name="新名字", fields={"sign_at": "10:00"}
    )
    assert updated["name"] == "新名字"
    assert updated["fields"] == {"sign_at": "10:00"}

    # 重新实例化读取同一 JSON,确认持久化
    reloaded = TaskTemplateStore(tmp_path).get_template(created["id"])
    assert reloaded["name"] == "新名字"

    with pytest.raises(ValueError):
        store.create_template(name="  ")


def test_template_private_fields_are_stripped(tmp_path):
    store = TaskTemplateStore(tmp_path)
    created = store.create_template(
        name="t",
        fields={"sign_at": "09:00", "enabled": False, "account_name": "x"},
    )
    # 模板不允许携带私有字段
    assert created["fields"] == {"sign_at": "09:00"}


def test_sync_template_updates_only_referencing_tasks(tmp_path):
    _write_task(
        tmp_path,
        "acc1",
        "task_a",
        template_id="tpl1",
        sign_at="08:00",
        chats=[{"chat_id": 1}],
        enabled=False,  # 任务级开关,不得被模板覆盖
        last_run={"success": True},
    )
    _write_task(
        tmp_path,
        "acc2",
        "task_b",
        template_id="",
        sign_at="08:00",
        chats=[{"chat_id": 2}],
    )
    svc = _FakeSvc(
        tmp_path,
        [
            _read_task(tmp_path, "acc1", "task_a"),
            _read_task(tmp_path, "acc2", "task_b"),
        ],
    )

    template = {
        "id": "tpl1",
        "name": "模板",
        "fields": {"sign_at": "10:30", "chats": [{"chat_id": 99}]},
    }
    synced = sync_template_to_tasks(svc, template)

    assert synced == [{"name": "task_a", "account_name": "acc1"}]
    assert svc.refreshed == 1

    task_a = _read_task(tmp_path, "acc1", "task_a")
    assert task_a["sign_at"] == "10:30"
    assert task_a["chats"] == [{"chat_id": 99}]
    # 私有/任务级字段保留
    assert task_a["account_name"] == "acc1"
    assert task_a["account_names"] == ["acc1"]
    assert task_a["enabled"] is False
    assert task_a["last_run"] == {"success": True}
    assert task_a["template_id"] == "tpl1"

    # 未引用模板的任务完全不受影响
    task_b = _read_task(tmp_path, "acc2", "task_b")
    assert task_b["sign_at"] == "08:00"
    assert task_b["chats"] == [{"chat_id": 2}]


def test_unbound_task_not_synced(tmp_path):
    _write_task(tmp_path, "acc1", "task_a", template_id="", sign_at="08:00")
    svc = _FakeSvc(tmp_path, [_read_task(tmp_path, "acc1", "task_a")])

    synced = sync_template_to_tasks(
        svc,
        {"id": "tpl1", "fields": {"sign_at": "10:30"}},
    )
    assert synced == []
    assert _read_task(tmp_path, "acc1", "task_a")["sign_at"] == "08:00"


def test_list_tasks_using_template(tmp_path):
    _write_task(tmp_path, "acc1", "task_a", template_id="tpl1")
    _write_task(tmp_path, "acc2", "task_b", template_id="tpl1")
    _write_task(tmp_path, "acc3", "task_c", template_id="other")
    svc = _FakeSvc(
        tmp_path,
        [
            _read_task(tmp_path, "acc1", "task_a"),
            _read_task(tmp_path, "acc2", "task_b"),
            _read_task(tmp_path, "acc3", "task_c"),
        ],
    )
    names = [item["name"] for item in list_tasks_using_template(svc, "tpl1")]
    assert names == ["task_a", "task_b"]


def test_task_config_template_id_semantics():
    cfg = build_sign_task_config(
        account_name="acc",
        account_names=["acc"],
        sign_at="09:00",
        chats=[],
        template_id="tpl1",
    )
    assert cfg["template_id"] == "tpl1"

    # 未提供时沿用既有绑定
    assert resolve_update_field_values({"template_id": "tpl1"})["template_id"] == "tpl1"
    # 显式空串表示解绑
    assert (
        resolve_update_field_values({"template_id": "tpl1"}, template_id="")[
            "template_id"
        ]
        == ""
    )


def test_template_routes_registered():
    from backend.api.routes import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/task-templates" in paths
    assert "/task-templates/{template_id}" in paths
    assert "/task-templates/{template_id}/tasks" in paths


def test_template_sync_result_has_warnings_field():
    from backend.api.routes.task_templates import TemplateOut, TemplateSyncResult

    tpl = TemplateOut(id="1", name="t")
    res = TemplateSyncResult(template=tpl, synced_tasks=[], warnings=["warn1"])
    assert res.warnings == ["warn1"]
    assert res.dict()["warnings"] == ["warn1"]


def test_update_template_validation_status_code(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.core.auth import get_current_user
    from backend.main import app

    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    try:
        store = TaskTemplateStore(tmp_path)
        created = store.create_template(name="t1")

        monkeypatch.setattr(
            "backend.api.routes.task_templates._get_store",
            lambda: TaskTemplateStore(tmp_path),
        )

        client = TestClient(app)
        # 模板不存在 -> 404
        r_not_found = client.put(
            "/api/task-templates/non_existent", json={"name": "new"}
        )
        assert r_not_found.status_code == 404
        assert "模板不存在" in r_not_found.text

        # 名称为空 -> 422
        r_invalid = client.put(
            f"/api/task-templates/{created['id']}", json={"name": "   "}
        )
        assert r_invalid.status_code == 422
        assert "模板名称不能为空" in r_invalid.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_template_private_fields_preserves_last_run_account_name(tmp_path):
    _write_task(
        tmp_path,
        "acc1",
        "task_a",
        template_id="tpl1",
        last_run_account_name="acc1",
    )
    svc = _FakeSvc(tmp_path, [_read_task(tmp_path, "acc1", "task_a")])
    template = {
        "id": "tpl1",
        "fields": {"sign_at": "12:00", "last_run_account_name": "other"},
    }
    sync_template_to_tasks(svc, template)
    task = _read_task(tmp_path, "acc1", "task_a")
    assert task["last_run_account_name"] == "acc1"


def test_sync_template_skips_reschedule_when_schedule_unchanged(tmp_path, monkeypatch):
    _write_task(
        tmp_path,
        "acc1",
        "task_a",
        template_id="tpl1",
        sign_at="08:00",
        chats=[{"chat_id": 1}],
    )
    svc = _FakeSvc(tmp_path, [_read_task(tmp_path, "acc1", "task_a")])
    rescheduled = []
    monkeypatch.setattr(
        "backend.services.sign_task_templates._reschedule_task",
        lambda *args: rescheduled.append(args),
    )

    # 仅更新 chats，sign_at 保持一致
    template = {"id": "tpl1", "fields": {"chats": [{"chat_id": 999}]}}
    synced = sync_template_to_tasks(svc, template)
    assert synced == [{"name": "task_a", "account_name": "acc1"}]
    # 调度未变，未触发 reschedule
    assert rescheduled == []

    # 当 sign_at 变更时，触发 reschedule
    template_time = {"id": "tpl1", "fields": {"sign_at": "11:00"}}
    sync_template_to_tasks(svc, template_time)
    assert len(rescheduled) == 1


def test_sync_template_error_isolation(tmp_path):
    _write_task(tmp_path, "acc1", "task_ok", template_id="tpl1")
    _write_task(tmp_path, "acc2", "task_bad", template_id="tpl1")
    # 破坏 task_bad 的 config.json
    (tmp_path / "signs" / "acc2" / "task_bad" / "config.json").write_text(
        "{bad json", encoding="utf-8"
    )

    svc = _FakeSvc(
        tmp_path,
        [
            _read_task(tmp_path, "acc1", "task_ok"),
            {"name": "task_bad", "account_name": "acc2", "template_id": "tpl1"},
        ],
    )
    # 单个任务损坏不阻断正常任务的同步
    synced = sync_template_to_tasks(svc, {"id": "tpl1", "fields": {"sign_at": "15:00"}})
    assert synced == [{"name": "task_ok", "account_name": "acc1"}]
    assert _read_task(tmp_path, "acc1", "task_ok")["sign_at"] == "15:00"
