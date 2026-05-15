from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from backend.core.database import Base
from backend.utils.time import utc_now_naive


class LoginLog(Base):
    __tablename__ = "login_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    detail = Column(String(255), nullable=True)
    success = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False, index=True)
