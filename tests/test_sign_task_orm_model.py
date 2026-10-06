from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

import backend.core.database as db_mod
from backend.core.config import get_settings
from backend.core.database import Base, get_session_local, init_engine
from backend.models.sign_task import SignTaskModel, cas_update_sign_task


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


def test_sign_task_unique_constraint_on_account_and_task_name():
    session_local = get_session_local()
    with session_local() as db:
        task1 = SignTaskModel(
            account_name="user1",
            task_name="daily_checkin",
            config_json="{}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task1)
        db.commit()

        task2 = SignTaskModel(
            account_name="user1",
            task_name="daily_checkin",
            config_json="{}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task2)
        with pytest.raises(IntegrityError):
            db.commit()


def test_sign_task_optimistic_lock_cas_update():
    session_local = get_session_local()
    with session_local() as db:
        task = SignTaskModel(
            account_name="user2",
            task_name="task_cas",
            config_json="{}",
            revision=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.commit()
        task_id = task.id

    # 模拟并发修改：事务 A 成功将 revision 1 -> 2
    with session_local() as db:
        row_updated = (
            db.query(SignTaskModel)
            .filter_by(id=task_id, revision=1)
            .update({"config_json": '{"updated": "by A"}', "revision": 2})
        )
        db.commit()
        assert row_updated == 1

    # 事务 B 基于过期的 revision 1 尝试更新，影响行数必须为 0！
    with session_local() as db:
        stale_update = (
            db.query(SignTaskModel)
            .filter_by(id=task_id, revision=1)
            .update({"config_json": '{"updated": "by B"}', "revision": 2})
        )
        db.commit()
        assert stale_update == 0, "乐观锁失效，允许了基于旧版本的并发写！"


def test_cas_update_sign_task_success_then_stale_rejected():
    session_local = get_session_local()
    with session_local() as db:
        task = SignTaskModel(
            account_name="user3",
            task_name="task_cas_helper",
            config_json="{}",
            revision=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task)
        db.commit()
        task_id = task.id

    # 基于当前 revision 的条件更新应生效，并自增 revision
    with session_local() as db:
        assert cas_update_sign_task(db, task_id, 1, config_json='{"v": 2}') is True
        db.commit()

    # 再次用过期 revision 更新必须失败，且不改变已落盘的数据
    with session_local() as db:
        assert (
            cas_update_sign_task(db, task_id, 1, config_json='{"stale": true}') is False
        )
        db.commit()

    with session_local() as db:
        row = db.query(SignTaskModel).filter_by(id=task_id).one()
        assert row.revision == 2
        assert row.config_json == '{"v": 2}'


def test_cas_update_rejects_caller_supplied_revision():
    session_local = get_session_local()
    with session_local() as db:
        with pytest.raises(ValueError):
            cas_update_sign_task(db, 1, 1, revision=99)
