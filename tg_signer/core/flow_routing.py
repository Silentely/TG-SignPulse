# tg_signer/core/flow_routing.py
from __future__ import annotations

import logging
import os
import zlib
from typing import Any, Dict, Optional, Tuple, Union

from tg_signer.config import FlowStepConfig, SignChatV3
from tg_signer.utils import read_positive_int_env

logger = logging.getLogger("tg_signer.flow_routing")

ENGINE_V4 = "v4"
ENGINE_V3 = "v3"

ENGINE_DISPLAY_NAMES = {
    ENGINE_V4: "PulseFlow (v4)",
    ENGINE_V3: "Classic (v3)",
}


class EngineResolutionResult(tuple):
    """三元组 (engine_code, engine_display, engine_source) 的增强子类。

    既完全兼容原生 tuple 解包：
        code, name, source = resolve_execution_engine(...)
    也兼容直接判断引擎字符串相等：
        if resolve_execution_engine(...) == "v4": ...
    """

    def __new__(cls, code: str, display_name: str, source: str):
        return super().__new__(cls, (code, display_name, source))

    @property
    def engine_code(self) -> str:
        return self[0]

    @property
    def engine_display(self) -> str:
        return self[1]

    @property
    def engine_source(self) -> str:
        return self[2]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self[0] == other
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()


def canary_hash_bucket(key: str, total_buckets: int = 100) -> int:
    """基于一致性 CRC32 哈希计算分桶 (0 ~ total_buckets-1)，保证同一目标分流结果稳定。"""
    if not key:
        return 0
    crc = zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF
    return crc % max(1, total_buckets)


def _chat_requires_flow_engine(c: Any) -> bool:
    """检测单会话是否包含图结构或新控制节点 FlowStepConfig。"""
    if c is None:
        return False
    if isinstance(c, dict):
        fg = c.get("flow_graph")
        if fg is not None and bool(fg):
            return True
        steps = c.get("steps")
        if steps:
            for s in steps:
                if isinstance(s, FlowStepConfig):
                    return True
                if isinstance(s, dict):
                    if "node_type" in s or any(
                        k in s
                        for k in (
                            "cases",
                            "filter_patterns",
                            "delay_seconds",
                            "regex",
                            "subflow_graph",
                            "branches",
                            "terminal_branch_target",
                        )
                    ):
                        return True
                elif getattr(s, "node_type", None) is not None:
                    return True
        return False

    fg = getattr(c, "flow_graph", None)
    if fg is not None and bool(fg):
        return True
    steps = getattr(c, "steps", None)
    if steps:
        for s in steps:
            if isinstance(s, FlowStepConfig) or getattr(s, "node_type", None) is not None:
                return True
    return False


def resolve_execution_engine(
    chat: Optional[Union[SignChatV3, Dict[str, Any]]] = None,
    task_engine: Optional[str] = None,
    global_engine: Optional[str] = None,
    canary_percentage: Optional[int] = None,
) -> EngineResolutionResult:
    """根据多级分流策略解析生效的执行引擎：

    0. 自适应引擎提升与冲突校验 (Adaptive Routing):
       - 若检测到会话使用了 flow_graph 或新控制节点 FlowStepConfig：
         - 若配置强制为 'v3'：抛出 ValueError 拒绝（经典引擎无法表达图结构）；
         - 否则：自动提升路由为 'v4' (PulseFlow)。
    1. 任务/目标级覆盖 (Task/Chat Override):
       - chat.execution_engine 为 'v4' 或 'v3' (来源: 'task')
       - task_engine 为 'v4' 或 'v3' (来源: 'task')
    2. 系统全局配置 (Global Settings): 由调用边界显式传入 global_engine (来源: 'settings')
    3. 灰度金丝雀分流 (Canary Traffic Splitting):
       - 若设置 canary_percentage 或环境变量 CANARY_PULSEFLOW_PERCENTAGE (0~100)
       - 依据 chat_id / name 计算稳定哈希分流 (来源: 'canary')
    4. 环境变量兜底 (Environment Variable): USE_PULSEFLOW_ENGINE=1/true/yes/v4/v3 (来源: 'env'/'settings')
    5. 默认经典模式 (Default): 'v3' (来源: 'default')

    Returns:
        EngineResolutionResult(engine_code, engine_display_name, source)
    """
    task_cfg_chats = None
    target_chat = chat
    if isinstance(chat, dict) and "chats" in chat:
        task_cfg_chats = chat.get("chats") or []
        if task_engine is None:
            task_engine = chat.get("execution_engine")
        target_chat = None

    requires_flow = False
    if task_cfg_chats is not None:
        requires_flow = any(_chat_requires_flow_engine(c) for c in task_cfg_chats)
    elif target_chat is not None:
        requires_flow = _chat_requires_flow_engine(target_chat)

    explicit_v3 = False
    if task_engine is not None and str(task_engine).strip().lower() == ENGINE_V3:
        explicit_v3 = True
    if target_chat is not None:
        raw_ce = getattr(target_chat, "execution_engine", None)
        if raw_ce is None and isinstance(target_chat, dict):
            raw_ce = target_chat.get("execution_engine")
        if raw_ce is not None and str(raw_ce).strip().lower() == ENGINE_V3:
            explicit_v3 = True
    if task_cfg_chats:
        for c in task_cfg_chats:
            ce = c.get("execution_engine") if isinstance(c, dict) else getattr(c, "execution_engine", None)
            if ce is not None and str(ce).strip().lower() == ENGINE_V3:
                explicit_v3 = True
                break

    if requires_flow:
        if explicit_v3:
            raise ValueError("工作流包含图结构/控制节点，无法在经典执行引擎上运行，请移除 execution_engine='v3' 或配置为 'v4'")
        explicit_v4 = False
        if task_engine is not None and str(task_engine).strip().lower() == ENGINE_V4:
            explicit_v4 = True
        if target_chat is not None:
            raw_ce = getattr(target_chat, "execution_engine", None)
            if raw_ce is None and isinstance(target_chat, dict):
                raw_ce = target_chat.get("execution_engine")
            if raw_ce is not None and str(raw_ce).strip().lower() == ENGINE_V4:
                explicit_v4 = True
        source = "task" if explicit_v4 else "auto"
        return EngineResolutionResult(ENGINE_V4, ENGINE_DISPLAY_NAMES[ENGINE_V4], source)

    # 1a. 单目标 Chat 级显式指定
    if target_chat is not None:
        raw_chat_engine = getattr(target_chat, "execution_engine", None)
        if raw_chat_engine is None and isinstance(target_chat, dict):
            raw_chat_engine = target_chat.get("execution_engine")
        if raw_chat_engine is not None:
            engine_norm = str(raw_chat_engine).strip().lower()
            if engine_norm in {ENGINE_V4, ENGINE_V3}:
                return EngineResolutionResult(
                    engine_norm,
                    ENGINE_DISPLAY_NAMES[engine_norm],
                    "task",
                )

    # 1b. 单任务 Task 级显式指定
    if task_engine is not None:
        engine_norm = str(task_engine).strip().lower()
        if engine_norm in {ENGINE_V4, ENGINE_V3}:
            return EngineResolutionResult(
                engine_norm,
                ENGINE_DISPLAY_NAMES[engine_norm],
                "task",
            )

    # 2. 系统全局配置由 backend/CLI 边界显式注入，core 不反向依赖 backend。
    if global_engine is not None:
        engine_norm = str(global_engine).strip().lower()
        if engine_norm in {ENGINE_V4, ENGINE_V3}:
            return EngineResolutionResult(
                engine_norm,
                ENGINE_DISPLAY_NAMES[engine_norm],
                "settings",
            )

    # 3. 灰度金丝雀分流 (Canary Traffic Splitting)
    pct = canary_percentage
    if pct is None:
        try:
            env_canary = os.getenv("CANARY_PULSEFLOW_PERCENTAGE")
            if env_canary is not None:
                pct = int(env_canary)
        except (ValueError, TypeError):
            pct = None

    if pct is not None and 0 < pct <= 100:
        hash_target = (
            getattr(target_chat, "chat_id", None)
            or (target_chat.get("chat_id") if isinstance(target_chat, dict) else None)
            or getattr(target_chat, "name", None)
            or (target_chat.get("name") if isinstance(target_chat, dict) else None)
        )
        if hash_target:
            bucket = canary_hash_bucket(str(hash_target), 100)
            if bucket < pct:
                return EngineResolutionResult(
                    ENGINE_V4,
                    ENGINE_DISPLAY_NAMES[ENGINE_V4],
                    "canary",
                )

    # 4. 环境变量兜底
    env_raw = os.getenv("USE_PULSEFLOW_ENGINE", "").strip().lower()
    env_source = os.getenv("PULSEFLOW_ENGINE_SOURCE", "env").strip().lower()
    source = env_source if env_source in {"env", "settings"} else "env"
    if env_raw == ENGINE_V3:
        return EngineResolutionResult(ENGINE_V3, ENGINE_DISPLAY_NAMES[ENGINE_V3], source)
    if (
        env_raw in {"1", "true", "yes", "on", "v4"}
        or read_positive_int_env("USE_PULSEFLOW_ENGINE", 0, 0) == 1
    ):
        return EngineResolutionResult(
            ENGINE_V4,
            ENGINE_DISPLAY_NAMES[ENGINE_V4],
            source,
        )

    # 5. 系统默认
    return EngineResolutionResult(
        ENGINE_V3,
        ENGINE_DISPLAY_NAMES[ENGINE_V3],
        "default",
    )
