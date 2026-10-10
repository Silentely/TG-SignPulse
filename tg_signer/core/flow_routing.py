# tg_signer/core/flow_routing.py
from __future__ import annotations

import logging
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
) -> Tuple[str, str, str]:
    """
    根据四级渐进切流策略解析生效的执行引擎：
    1. 任务级覆盖 (Task Override): chat.execution_engine 为 'v4' 或 'v3'
    2. 系统全局配置 (Global Settings): global_settings.execution_engine
    3. 环境变量兜底 (Environment Variable): USE_PULSEFLOW_ENGINE=1
    4. 默认经典模式 (Default): 'v3'

    Returns:
        Tuple[engine_code, engine_display_name, source]
        如: ('v4', 'PulseFlow (v4)', 'task') 或 ('v3', 'Classic (v3)', 'settings')
    """
    # 1. 任务级显式指定
    if chat is not None:
        raw_task_engine = getattr(chat, "execution_engine", None)
        if raw_task_engine is not None:
            engine_norm = str(raw_task_engine).strip().lower()
            if engine_norm in {ENGINE_V4, ENGINE_V3}:
                return (
                    engine_norm,
                    ENGINE_DISPLAY_NAMES[engine_norm],
                    "task",
                )

    # 2. 系统全局配置（UI 开关）
    try:
        from backend.services.config import get_config_service

        settings = get_config_service().get_global_settings()
        raw_settings_engine = settings.get("execution_engine")
        if raw_settings_engine is not None:
            engine_norm = str(raw_settings_engine).strip().lower()
            if engine_norm in {ENGINE_V4, ENGINE_V3}:
                return (
                    engine_norm,
                    ENGINE_DISPLAY_NAMES[engine_norm],
                    "settings",
                )
    except Exception as exc:
        # 在某些纯 CLI 模式或测试环境中，backend 服务层未初始化，静默降级到下一优先级
        logger.debug("读取全局配置 execution_engine 降级: %s", exc)

    # 3. 环境变量兜底
    if read_positive_int_env("USE_PULSEFLOW_ENGINE", 0, 0) == 1:
        return (
            ENGINE_V4,
            ENGINE_DISPLAY_NAMES[ENGINE_V4],
            "env",
        )

    # 4. 系统默认
    return (
        ENGINE_V3,
        ENGINE_DISPLAY_NAMES[ENGINE_V3],
        "default",
    )
