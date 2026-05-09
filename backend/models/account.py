from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.core.database import Base
from backend.utils.time import utc_now_naive


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String(100), unique=True, nullable=False, index=True)
    api_id = Column(String(64), nullable=False)
    api_hash = Column(String(128), nullable=False)
    proxy = Column(Text, nullable=True)  # store JSON string for proxy config
    status = Column(String(32), default="idle", nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False
    )

    tasks = relationship("Task", back_populates="account", cascade="all,delete")
