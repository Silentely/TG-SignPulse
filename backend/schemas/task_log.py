from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")


class TaskLogOut(BaseModel):
    id: int
    task_id: int
    status: str
    log_path: Optional[str] = None
    output: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            orm_mode = True
