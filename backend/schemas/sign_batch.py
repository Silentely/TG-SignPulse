"""
签到任务（文件存储体系）批量操作 Schema
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class SignBatchAction(str, Enum):
    """签到任务批量操作类型"""

    ENABLE = "enable"
    DISABLE = "disable"
    DELETE = "delete"
    RUN = "run"


class SignBatchTaskItem(BaseModel):
    """批量操作中的单个任务定位"""

    name: str = Field(..., min_length=1, description="任务名称")
    account_name: Optional[str] = Field(
        None, description="账号名；共享任务可省略，服务端按聚合规则解析"
    )


class SignBatchTaskRequest(BaseModel):
    """签到任务批量操作请求"""

    tasks: List[SignBatchTaskItem] = Field(
        ...,
        description="任务列表，至少 1 个，最多 100 个",
    )
    action: SignBatchAction = Field(..., description="批量操作类型")
    # run 时可指定统一账号；优先于 item.account_name
    run_account_name: Optional[str] = Field(
        None, description="批量执行时统一使用的账号（可选）"
    )

    @validator("tasks")
    def validate_tasks(cls, v: List[SignBatchTaskItem]) -> List[SignBatchTaskItem]:
        if len(v) < 1:
            raise ValueError("tasks 至少需要 1 个元素")
        if len(v) > 100:
            raise ValueError("tasks 最多允许 100 个元素")
        # 按 (name, account) 去重，保持顺序
        seen: set[tuple[str, str]] = set()
        deduped: List[SignBatchTaskItem] = []
        for item in v:
            key = (item.name.strip(), (item.account_name or "").strip())
            if not key[0]:
                raise ValueError("任务名称不能为空")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(
                SignBatchTaskItem(name=key[0], account_name=key[1] or None)
            )
        return deduped


class SignBatchTaskResult(BaseModel):
    """单个签到任务的批量操作结果"""

    name: str
    account_name: str = ""
    success: bool
    message: str = ""


class SignBatchTaskResponse(BaseModel):
    """签到任务批量操作响应"""

    total: int
    success_count: int
    fail_count: int
    results: List[SignBatchTaskResult] = Field(default_factory=list)
