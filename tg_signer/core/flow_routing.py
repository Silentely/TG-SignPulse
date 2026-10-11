# tg_signer/core/flow_routing.py
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from tg_signer.config import SignChatV3
from tg_signer.utils import read_positive_int_env

logger = logging.getLogger("tg_signer.flow_routing")

ENGINE_V4 = "v4"
ENGINE_V3 = "v3"

ENGINE_DISPLAY_NAMES = {
    ENGINE_V4: "PulseFlow (v4)",
    ENGINE_V3: "Classic (v3)",
}


def resolve_execution_engine(
    chat: Optional[SignChatV3] = None,
    task_engine: Optional[str] = None,
    global_engine: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    根据四级渐进切流策略解析生效的执行引擎：
    1. 任务/目标级覆盖 (Task/Chat Override):
       - chat.execution_engine 为 'v4' 或 'v3' (来源: 'chat' 或 'task')
       - task_engine 为 'v4' 或 'v3' (来源: 'task')
    2. 系统全局配置 (Global Settings): 由调用边界显式传入 global_engine
    3. 环境变量兜底 (Environment Variable): USE_PULSEFLOW_ENGINE=1/true/yes/v4/v3
    4. 默认经典模式 (Default): 'v3'

    Returns:
        Tuple[engine_code, engine_display_name, source]
        如: ('v4', 'PulseFlow (v4)', 'task') 或 ('v3', 'Classic (v3)', 'settings')
    """
    # 1a. 单目标 Chat 级显式指定
    if chat is not None:
        raw_chat_engine = getattr(chat, "execution_engine", None)
        if raw_chat_engine is not None:
            engine_norm = str(raw_chat_engine).strip().lower()
            if engine_norm in {ENGINE_V4, ENGINE_V3}:
                return (
                    engine_norm,
                    ENGINE_DISPLAY_NAMES[engine_norm],
                    "task",
                )

    # 1b. 单任务 Task 级显式指定
    if task_engine is not None:
        engine_norm = str(task_engine).strip().lower()
        if engine_norm in {ENGINE_V4, ENGINE_V3}:
            return (
                engine_norm,
                ENGINE_DISPLAY_NAMES[engine_norm],
                "task",
            )

    # 2. 系统全局配置由 backend/CLI 边界显式注入，core 不反向依赖 backend。
    if global_engine is not None:
        engine_norm = str(global_engine).strip().lower()
        if engine_norm in {ENGINE_V4, ENGINE_V3}:
            return (
                engine_norm,
                ENGINE_DISPLAY_NAMES[engine_norm],
                "settings",
            )

    # 3. 环境变量兜底
    env_raw = os.getenv("USE_PULSEFLOW_ENGINE", "").strip().lower()
    env_source = os.getenv("PULSEFLOW_ENGINE_SOURCE", "env").strip().lower()
    source = env_source if env_source in {"env", "settings"} else "env"
    if env_raw == ENGINE_V3:
        return ENGINE_V3, ENGINE_DISPLAY_NAMES[ENGINE_V3], source
    if (
        env_raw in {"1", "true", "yes", "on", "v4"}
        or read_positive_int_env("USE_PULSEFLOW_ENGINE", 0, 0) == 1
    ):
        return (
            ENGINE_V4,
            ENGINE_DISPLAY_NAMES[ENGINE_V4],
            source,
        )

    # 4. 系统默认
    return (
        ENGINE_V3,
        ENGINE_DISPLAY_NAMES[ENGINE_V3],
        "default",
    )
