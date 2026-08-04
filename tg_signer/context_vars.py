"""引擎侧上下文变量。

任务级重试次数由 backend 任务执行器写入、引擎读取；定义在引擎侧避免
tg_signer 反向依赖 backend。默认值 0 表示"未设置"：CLI 独立运行时
signer_runner 的 ``if _ctx_val and _ctx_val > 0`` 判定不生效，回退到
SIGN_TASK_FLOW_RETRY_ATTEMPTS 环境变量。
"""
from contextvars import ContextVar

task_retry_count_var: ContextVar[int] = ContextVar("task_retry_count", default=0)
