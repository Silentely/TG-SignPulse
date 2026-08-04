"""引擎侧上下文变量。

任务级重试次数由 backend 任务执行器写入、引擎读取；定义在引擎侧避免
tg_signer 反向依赖 backend。
"""
from contextvars import ContextVar

task_retry_count_var: ContextVar[int] = ContextVar("task_retry_count", default=1)
