from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.core.database import Base


class SignTaskModel(Base):
    __tablename__ = "sign_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_name = Column(String(128), nullable=False, index=True)
    task_name = Column(String(128), nullable=False, index=True)
    is_wildcard = Column(Boolean, default=False, nullable=False)
    cron_expr = Column(String(64), nullable=True)
    random_window = Column(String(64), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    revision = Column(Integer, default=1, nullable=False)  # 乐观锁
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("account_name", "task_name", name="uq_sign_task_account_name"),
        Index("ix_sign_task_active", "account_name", "enabled"),
    )


class SignTaskHistoryModel(Base):
    __tablename__ = "sign_task_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    account_name = Column(String(128), nullable=False, index=True)
    task_name = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False)  # success, failed, timeout
    message = Column(Text, nullable=True)
    flow_logs_json = Column(Text, nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_history_lookup", "account_name", "task_name", "executed_at"),
    )


class StorageMigrationRunModel(Base):
    __tablename__ = "storage_migration_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False)  # COMPLETED, ROLLED_BACK
    scanned_count = Column(Integer, default=0)
    migrated_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


class StorageMigrationItemModel(Base):
    __tablename__ = "storage_migration_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(128), nullable=False)
    task_name = Column(String(128), nullable=False)
    source_sha256 = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "run_id", "account_name", "task_name", name="uq_migration_item"
        ),
    )
