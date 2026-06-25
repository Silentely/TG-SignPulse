"""
批量操作 Schema 定义

提供任务批量操作的请求和响应模型，支持：
- 批量启用/禁用任务
- 批量删除任务
- 批量执行任务
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field, validator


class BatchAction(str, Enum):
    """批量操作类型枚举"""

    ENABLE = "enable"
    DISABLE = "disable"
    DELETE = "delete"
    RUN = "run"


class BatchTaskRequest(BaseModel):
    """批量任务操作请求"""

    task_ids: List[int] = Field(
        ...,
        description="任务 ID 列表，至少 1 个，最多 100 个",
    )
    action: BatchAction = Field(..., description="批量操作类型")

    @validator("task_ids")
    def validate_task_ids(cls, v: List[int]) -> List[int]:
        """校验 task_ids：正整数、去重、长度 1-100"""
        if len(v) < 1:
            raise ValueError("task_ids 至少需要 1 个元素")
        if len(v) > 100:
            raise ValueError("task_ids 最多允许 100 个元素")
        for tid in v:
            if tid < 1:
                raise ValueError(f"task_ids 必须为正整数，收到 {tid}")
        # 去重但保持顺序
        seen: set[int] = set()
        deduped: List[int] = []
        for tid in v:
            if tid not in seen:
                seen.add(tid)
                deduped.append(tid)
        return deduped


class BatchTaskResult(BaseModel):
    """单个任务的批量操作结果"""

    task_id: int
    success: bool
    message: str = ""


class BatchTaskResponse(BaseModel):
    """批量任务操作响应"""

    total: int = Field(..., description="请求操作的任务总数")
    success_count: int = Field(..., description="成功数量")
    fail_count: int = Field(..., description="失败数量")
    results: List[BatchTaskResult] = Field(
        default_factory=list,
        description="每个任务的操作结果",
    )
