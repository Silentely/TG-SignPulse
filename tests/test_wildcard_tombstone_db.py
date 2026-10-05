from __future__ import annotations

from datetime import datetime, timezone
import pytest

import backend.core.database as db_mod
from backend.core.config import get_settings
from backend.core.database import Base, get_session_local, init_engine
from backend.models.wildcard_tombstone import WildcardTombstoneModel
from backend.services.sign_tasks import SignTaskService


@pytest.fixture(autouse=True)
def setup_isolated_db(isolated_env):
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._SessionLocal = None
    init_engine()
    session_local = get_session_local()
    engine = session_local().get_bind()
    Base.metadata.create_all(bind=engine)
    yield
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._SessionLocal = None


def test_wildcard_tombstone_persists_across_service_reinit():
    session_local = get_session_local()
    with session_local() as db:
        tombstone = WildcardTombstoneModel(
            account_name="user_alpha",
            task_name="daily_checkin",
            parent_task_id="wildcard_main_uuid",
            parent_revision=1,
            removed_at=datetime.now(timezone.utc),
        )
        db.add(tombstone)
        db.commit()

    # 模拟服务重启（新初始化实例）
    new_service = SignTaskService()
    # 断言该账号的任务确实被墓碑标记，即使重启也绝不复活！对齐真实方法名 is_wildcard_removed
    assert new_service.is_wildcard_removed("user_alpha", "daily_checkin") is True
    assert new_service.is_wildcard_removed("user_alpha", "other_task") is False
    assert new_service.is_wildcard_removed("user_beta", "daily_checkin") is False


def test_wildcard_tombstone_record_and_clear_lifecycle():
    service = SignTaskService()

    # 1. 记录墓碑
    service.record_wildcard_removed("acc1", "task_x")
    assert service.is_wildcard_removed("acc1", "task_x") is True

    # 2. 幂等记录（不因唯一键冲突报错）
    service.record_wildcard_removed("acc1", "task_x")
    assert service.is_wildcard_removed("acc1", "task_x") is True

    # 3. 跨服务重启验证
    reloaded_service = SignTaskService()
    assert reloaded_service.is_wildcard_removed("acc1", "task_x") is True

    # 4. 清理墓碑
    reloaded_service.clear_wildcard_removed("acc1", "task_x")
    assert reloaded_service.is_wildcard_removed("acc1", "task_x") is False

    # 5. 跨服务再次确认已被清理
    third_service = SignTaskService()
    assert third_service.is_wildcard_removed("acc1", "task_x") is False


def test_wildcard_tombstone_prevents_expansion_after_restart(monkeypatch):
    import backend.services.sign_tasks as st_module

    svc1 = SignTaskService()
    monkeypatch.setattr(st_module, "list_account_names", lambda: ["acc1", "acc2"])

    # 创建通配任务并扩展
    svc1.create_task(
        task_name="wild_job",
        sign_at="09:00",
        chats=[],
        account_name="acc1",
        account_names=["*"],
    )
    svc1._expand_wildcard_tasks()

    # 删除 acc2 副本
    assert svc1.delete_task("wild_job", "acc2") is True

    # 模拟服务完全重启
    svc2 = SignTaskService()
    svc2.invalidate_tasks_cache()
    svc2._expand_wildcard_tasks()

    acc2_dir = svc2.signs_dir / "acc2" / "wild_job" / "config.json"
    assert not acc2_dir.exists()
    assert svc2.is_wildcard_removed("acc2", "wild_job") is True
