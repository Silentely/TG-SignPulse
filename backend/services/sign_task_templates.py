"""任务模板实体与引用同步。

模板以 JSON 文件持久化(``<workdir>/task_templates.json``),与签到任务配置的
存储风格一致,不引入数据库表。任务在 ``config.json`` 记录 ``template_id``;
更新模板时把模板的公共字段同步到所有引用它的任务,账号/凭据、``enabled``
等任务私有字段保持不变。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils.atomic_io import (
    path_write_lock,
    read_json_safe,
    write_json_atomic,
)
from backend.utils.time import utc_now_iso_z_seconds

TEMPLATE_FILE_NAME = "task_templates.json"
_TEMPLATE_FILE_VERSION = 1

# 这些字段属于任务/账号自身,模板同步时绝不覆盖
TEMPLATE_PRIVATE_FIELDS = frozenset(
    {
        "name",
        "account_name",
        "account_names",
        "task_group_id",
        "enabled",
        "last_run",
        "template_id",
        "_version",
    }
)


def _clean_template_id(value: Any) -> str:
    return str(value or "").strip()


def _normalize_template_fields(fields: Any) -> Dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    return {
        str(key): value
        for key, value in fields.items()
        if str(key) not in TEMPLATE_PRIVATE_FIELDS
    }


class TaskTemplateStore:
    """任务模板 JSON 存储。"""

    def __init__(self, workdir: Path | str):
        self.workdir = Path(workdir)
        self.path = self.workdir / TEMPLATE_FILE_NAME

    def _load(self) -> Dict[str, Any]:
        payload = read_json_safe(self.path, default=None)
        if not isinstance(payload, dict):
            return {"_version": _TEMPLATE_FILE_VERSION, "templates": {}}
        templates = payload.get("templates")
        if not isinstance(templates, dict):
            payload["templates"] = {}
        return payload

    def _save(self, payload: Dict[str, Any]) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        with path_write_lock(self.path):
            write_json_atomic(self.path, payload)

    def list_templates(self) -> List[Dict[str, Any]]:
        templates = self._load().get("templates") or {}
        items = [t for t in templates.values() if isinstance(t, dict)]
        return sorted(items, key=lambda item: str(item.get("name") or ""))

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        template_id = _clean_template_id(template_id)
        template = (self._load().get("templates") or {}).get(template_id)
        return dict(template) if isinstance(template, dict) else None

    def create_template(
        self,
        *,
        name: str,
        fields: Optional[Dict[str, Any]] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("模板名称不能为空")
        now = utc_now_iso_z_seconds()
        template = {
            "id": uuid.uuid4().hex,
            "name": clean_name,
            "description": str(description or "").strip(),
            "fields": _normalize_template_fields(fields),
            "created_at": now,
            "updated_at": now,
        }
        payload = self._load()
        payload.setdefault("templates", {})[template["id"]] = template
        self._save(payload)
        return dict(template)

    def update_template(
        self,
        template_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        template_id = _clean_template_id(template_id)
        payload = self._load()
        templates = payload.setdefault("templates", {})
        existing = templates.get(template_id)
        if not isinstance(existing, dict):
            raise ValueError("模板不存在")

        updated = dict(existing)
        if name is not None:
            clean_name = str(name).strip()
            if not clean_name:
                raise ValueError("模板名称不能为空")
            updated["name"] = clean_name
        if description is not None:
            updated["description"] = str(description).strip()
        if fields is not None:
            updated["fields"] = _normalize_template_fields(fields)
        updated["updated_at"] = utc_now_iso_z_seconds()

        templates[template_id] = updated
        self._save(payload)
        return dict(updated)


def list_tasks_using_template(svc: Any, template_id: str) -> List[Dict[str, Any]]:
    """列出引用指定模板的任务(仅摘要)。"""
    template_id = _clean_template_id(template_id)
    if not template_id:
        return []
    out: List[Dict[str, Any]] = []
    for task in svc.list_tasks(force_refresh=True):
        if not isinstance(task, dict):
            continue
        if _clean_template_id(task.get("template_id")) != template_id:
            continue
        out.append(
            {
                "name": str(task.get("name") or ""),
                "account_name": str(task.get("account_name") or ""),
                "account_names": list(task.get("account_names") or []),
                "enabled": bool(task.get("enabled", True)),
            }
        )
    return out


def sync_template_to_tasks(svc: Any, template: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把模板公共字段覆盖到所有引用它的任务,保留任务私有字段。"""
    template_id = _clean_template_id(template.get("id"))
    template_fields = _normalize_template_fields(template.get("fields"))
    if not template_id or not template_fields:
        return []

    synced: List[Dict[str, Any]] = []
    for task in svc.list_tasks(force_refresh=True):
        if not isinstance(task, dict):
            continue
        if _clean_template_id(task.get("template_id")) != template_id:
            continue
        task_name = str(task.get("name") or "")
        account_name = str(task.get("account_name") or "")
        task_dir = svc._resolve_task_dir(task_name, account_name)
        if task_dir is None:
            continue
        config_file = Path(task_dir) / "config.json"
        if not config_file.exists():
            continue

        with path_write_lock(config_file):
            config = read_json_safe(config_file, default=None)
            if not isinstance(config, dict):
                continue
            merged = dict(config)
            for key, value in template_fields.items():
                if key in TEMPLATE_PRIVATE_FIELDS:
                    continue
                merged[key] = value
            # 私有字段以任务自身为准(模板中即使误带也不会覆盖)
            for key in TEMPLATE_PRIVATE_FIELDS:
                if key in config:
                    merged[key] = config[key]
            merged["template_id"] = template_id
            if merged == config:
                continue
            write_json_atomic(config_file, merged)

        synced.append({"name": task_name, "account_name": account_name})
        _reschedule_task(merged, account_name, task_name)

    if synced and hasattr(svc, "_refresh_tasks_cache_after_write"):
        svc._refresh_tasks_cache_after_write()
    return synced


def _reschedule_task(config: Dict[str, Any], account_name: str, task_name: str) -> None:
    """模板可能改变 sign_at/模式,尽力同步调度;失败不影响配置写入。"""
    try:
        from backend.scheduler import add_or_update_sign_task_job, remove_sign_task_job
        from backend.services.sign_task_config_build import resolve_schedule_plan

        plan = resolve_schedule_plan(
            str(config.get("execution_mode") or "fixed"),
            sign_at=str(config.get("sign_at") or "08:00"),
            range_start=str(config.get("range_start") or ""),
        )
        if plan["should_schedule"]:
            add_or_update_sign_task_job(
                account_name,
                task_name,
                plan["trigger_cron"],
                enabled=bool(config.get("enabled", True)),
                jitter=int(config.get("jitter_seconds") or 0),
            )
        else:
            remove_sign_task_job(account_name, task_name)
    except Exception:
        pass
