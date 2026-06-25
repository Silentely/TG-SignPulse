from __future__ import annotations

from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 compatibility
    ConfigDict = None

_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")


class TaskStatsOut(BaseModel):
    """任务统计输出模型"""

    total: int
    enabled: int
    disabled: int
    with_logs: int

    if _PYDANTIC_V2 and ConfigDict is not None:
        model_config = ConfigDict(from_attributes=True)
    else:

        class Config:
            orm_mode = True
