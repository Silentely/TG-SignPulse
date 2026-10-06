import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backend.core.database as db_mod
from backend.core.config import get_settings
from backend.core.database import Base, get_session_local, init_engine
from backend.models.sign_task import SignTaskModel, StorageMigrationRunModel
from tools.migrate_json_to_orm import rollback_migration, run_migration


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


def test_migration_lifecycle_dryrun_execute_and_batch_rollback():
    with tempfile.TemporaryDirectory() as tmpdir:
        signs_dir = Path(tmpdir) / ".signer" / "signs"
        task_dir = signs_dir / "userA" / "task1"
        task_dir.mkdir(parents=True)
        (task_dir / "config.json").write_text(
            json.dumps({"name": "task1", "enabled": True})
        )

        # 0. 先写入一条独立的不属于该迁移批次的数据
        session_local = get_session_local()
        with session_local() as db:
            other_task = SignTaskModel(
                account_name="other_user",
                task_name="untouched_task",
                config_json="{}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(other_task)
            db.commit()

        # 1. 运行 dry-run
        summary_dry = run_migration(signs_dir=signs_dir, dry_run=True)
        assert summary_dry["scanned_count"] == 1
        assert summary_dry["migrated_count"] == 0

        # 断言数据库只保持原有的 1 条独立任务
        with session_local() as db:
            assert db.query(SignTaskModel).count() == 1

        # 2. 运行正式 execute
        summary_exec = run_migration(signs_dir=signs_dir, dry_run=False)
        run_id = summary_exec["run_id"]
        assert summary_exec["migrated_count"] == 1

        with session_local() as db:
            assert db.query(SignTaskModel).count() == 2
            journal = (
                db.query(StorageMigrationRunModel).filter_by(run_id=run_id).first()
            )
            assert journal is not None
            assert journal.status == "COMPLETED"

        # 3. 运行 rollback 撤销：必须仅撤销本次迁移批次的 task1，绝不能误删 other_user 的任务！
        rb_res = rollback_migration(run_id=run_id)
        assert rb_res["rolled_back_count"] == 1

        with session_local() as db:
            # 核心断言：批次撤销后，other_user 的任务依然完好无损！
            assert db.query(SignTaskModel).count() == 1
            remaining = db.query(SignTaskModel).first()
            assert remaining.account_name == "other_user"
            journal = (
                db.query(StorageMigrationRunModel).filter_by(run_id=run_id).first()
            )
            assert journal.status == "ROLLED_BACK"


def test_dry_run_does_not_initialize_database_schema(monkeypatch, tmp_path):
    import tools.migrate_json_to_orm as migration_module

    signs_dir = tmp_path / "signs"
    task_dir = signs_dir / "account" / "task"
    task_dir.mkdir(parents=True)
    (task_dir / "config.json").write_text("{}")

    def fail_if_database_is_touched():
        raise AssertionError("dry-run must not initialize the database")

    monkeypatch.setattr(
        migration_module, "get_session_local", fail_if_database_is_touched
    )

    result = migration_module.run_migration(signs_dir, dry_run=True)

    assert result["scanned_count"] == 1
    assert result["migrated_count"] == 0


def test_migration_supports_workflow_steps_configuration():
    from tg_signer.config import SignChatV3

    with tempfile.TemporaryDirectory() as tmpdir:
        signs_dir = Path(tmpdir) / ".signer" / "signs"
        task_dir = signs_dir / "user_wf" / "wf_task"
        task_dir.mkdir(parents=True)
        raw_config = {
            "name": "wf_task",
            "enabled": True,
            "chats": [
                {
                    "chat_id": 999888,
                    "name": "wf_group",
                    "steps": [
                        {
                            "step_id": "s1",
                            "action_type": "send_text",
                            "config": {"text": "hello wf"},
                            "next_step_id": "COMPLETE",
                        }
                    ],
                    "initial_step_id": "s1",
                }
            ],
        }
        (task_dir / "config.json").write_text(json.dumps(raw_config))

        summary = run_migration(signs_dir=signs_dir, dry_run=False)
        assert summary["migrated_count"] == 1

        session_local = get_session_local()
        with session_local() as db:
            record = (
                db.query(SignTaskModel)
                .filter_by(account_name="user_wf", task_name="wf_task")
                .first()
            )
            assert record is not None
            loaded_cfg = json.loads(record.config_json)
            assert "steps" in loaded_cfg["chats"][0]
            assert loaded_cfg["chats"][0]["initial_step_id"] == "s1"
            validate_func = getattr(
                SignChatV3, "model_validate", getattr(SignChatV3, "parse_obj", None)
            )
            chat_obj = (
                validate_func(loaded_cfg["chats"][0])
                if validate_func
                else SignChatV3(**loaded_cfg["chats"][0])
            )
            assert len(chat_obj.steps) == 1
            assert chat_obj.steps[0].step_id == "s1"
