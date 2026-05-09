from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String

from backend.core.database import Base
from backend.utils.time import utc_now_naive


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    totp_secret = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive, nullable=False)
