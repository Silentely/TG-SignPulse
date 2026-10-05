from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint

from backend.core.database import Base


class WildcardTombstoneModel(Base):
    __tablename__ = "wildcard_tombstones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_name = Column(String(128), nullable=False)
    task_name = Column(String(128), nullable=False)
    parent_task_id = Column(String(64), nullable=False, default="")
    parent_revision = Column(Integer, default=1, nullable=False)
    removed_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "account_name",
            "task_name",
            name="uq_wildcard_tombstone_account_task",
        ),
        Index("ix_wildcard_tombstone_lookup", "account_name", "task_name"),
    )
