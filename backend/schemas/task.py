from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")


class TaskBase(BaseModel):
    name: str  # 对应 tg-signer 的 task_name
    cron: str
    account_id: int


class TaskCreate(TaskBase):
    enabled: bool = True


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    cron: Optional[str] = None
    enabled: Optional[bool] = None
    account_id: Optional[int] = None


class TaskOut(TaskBase):
    id: int
    enabled: bool
    last_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            orm_mode = True
