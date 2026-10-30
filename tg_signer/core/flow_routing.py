# tg_signer/core/flow_routing.py
from __future__ import annotations

import logging
import os
import zlib
from typing import Any, Dict, Optional, Union

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


def task_requires_semantic(c: Any) -> bool:
    """检测任务或会话是否启用了任何语义策略 (semantic_result / semantic_button / semantic_triage)。"""
    if c is None:
        return False
    if isinstance(c, dict) and "chats" in c:
        chats = c.get("chats") or []
        return any(task_requires_semantic(item) for item in chats)
    elif getattr(c, "chats", None) is not None:
        return any(task_requires_semantic(item) for item in getattr(c, "chats", []))

    def _has_sem(obj: Any) -> bool:
        if obj is None:
            return False
        if isinstance(obj, dict):
            for k in ("semantic_result", "semantic_button", "semantic_triage"):
                v = obj.get(k)
                if isinstance(v, dict) and v.get("mode") in {"observe", "assist"}:
                    return True
                elif getattr(v, "mode", None) in {"observe", "assist"}:
                    return True
            return False
        for k in ("semantic_result", "semantic_button", "semantic_triage"):
            v = getattr(obj, k, None)
            if isinstance(v, dict) and v.get("mode") in {"observe", "assist"}:
                return True
            elif getattr(v, "mode", None) in {"observe", "assist"}:
                return True
        return False

    if _has_sem(c):
        return True

    steps = c.get("steps") if isinstance(c, dict) else getattr(c, "steps", None)
    if steps:
        for s in steps:
            if _has_sem(s):
                return True

    actions = c.get("actions") if isinstance(c, dict) else getattr(c, "actions", None)
    if actions:
        for a in actions:
            if _has_sem(a):
                return True

    return False


def _chat_requires_flow_engine(c: Any) -> bool:
    """检测单会话是否包含图结构或新控制节点 FlowStepConfig 或语义自动化策略。"""
    if c is None:
        return False
    if task_requires_semantic(c):
        return True
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
                            "success_patterns",
                            "failure_patterns",
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
        actions = c.get("actions")
        if actions:
            for act in actions:
                if (
                    isinstance(act, dict) and bool(act.get("wait_for_reply"))
                ) or getattr(act, "wait_for_reply", False):
                    return True
        return False

    fg = getattr(c, "flow_graph", None)
    if fg is not None and bool(fg):
        return True
    steps = getattr(c, "steps", None)
    if steps:
        for s in steps:
            if (
                isinstance(s, FlowStepConfig)
                or getattr(s, "node_type", None) is not None
            ):
                return True
    actions = getattr(c, "actions", None)
    if actions:
        for act in actions:
            if getattr(act, "wait_for_reply", False):
                return True
    return False


def _chat_has_steps(c: Any) -> bool:
    """检测会话是否配置了工作流步骤 steps。"""
    if c is None:
        return False
    if isinstance(c, dict):
        steps = c.get("steps")
        return bool(steps)
    steps = getattr(c, "steps", None)
    return bool(steps)


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
    0.5. 紧急环境强控过渡窗口覆盖 (Transition Window Emergency Override):
       - PULSEFLOW_ENGINE_OVERRIDE=v3 或 v4 (来源: 'override')
    1. 任务/目标级覆盖 (Task/Chat Override):
       - chat.execution_engine 为 'v4' 或 'v3' (来源: 'task')
       - task_engine 为 'v4' 或 'v3' (来源: 'task')
    2. 系统全局配置 (Global Settings): 由调用边界显式传入 global_engine (来源: 'settings')
    3. 灰度金丝雀分流 (Canary Traffic Splitting):
       - 若设置 canary_percentage 或环境变量 CANARY_PULSEFLOW_PERCENTAGE (0~100)
       - 依据 chat_id / name 计算稳定哈希分流 (来源: 'canary')
    4. 环境变量兜底 (Environment Variable): USE_PULSEFLOW_ENGINE=1/true/yes/v4/v3 (来源: 'env'/'settings')
    5. 系统默认 (Default):
       - 工作流步骤任务 (chat.steps) 默认切流至 'v4' (PulseFlow) (来源: 'default')
       - 经典动作流任务 (chat.actions) 默认保持 'v3' (来源: 'default')

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

    raw_env_override = os.getenv("PULSEFLOW_ENGINE_OVERRIDE", "").strip().lower()
    if raw_env_override in {"classic", "v3", ENGINE_V3}:
        env_engine_override = ENGINE_V3
    elif raw_env_override in {"pulseflow", "v4", ENGINE_V4}:
        env_engine_override = ENGINE_V4
    else:
        env_engine_override = ""

    explicit_v3 = False
    if env_engine_override == ENGINE_V3:
        explicit_v3 = True
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
            ce = (
                c.get("execution_engine")
                if isinstance(c, dict)
                else getattr(c, "execution_engine", None)
            )
            if ce is not None and str(ce).strip().lower() == ENGINE_V3:
                explicit_v3 = True
                break

    if requires_flow:
        if explicit_v3:
            raise ValueError(
                "工作流包含图结构/控制节点，无法在经典执行引擎上运行，请移除 execution_engine='v3' 或配置为 'v4'"
            )
        explicit_v4 = False
        if env_engine_override == ENGINE_V4:
            explicit_v4 = True
        if task_engine is not None and str(task_engine).strip().lower() == ENGINE_V4:
            explicit_v4 = True
        if target_chat is not None:
            raw_ce = getattr(target_chat, "execution_engine", None)
            if raw_ce is None and isinstance(target_chat, dict):
                raw_ce = target_chat.get("execution_engine")
            if raw_ce is not None and str(raw_ce).strip().lower() == ENGINE_V4:
                explicit_v4 = True
        source = (
            "task"
            if explicit_v4
            else ("override" if env_engine_override == ENGINE_V4 else "auto")
        )
        return EngineResolutionResult(
            ENGINE_V4, ENGINE_DISPLAY_NAMES[ENGINE_V4], source
        )

    # 0.5 紧急环境强控过渡窗口覆盖 (Transition Window Emergency Override)
    if env_engine_override in {ENGINE_V4, ENGINE_V3}:
        return EngineResolutionResult(
            env_engine_override,
            ENGINE_DISPLAY_NAMES[env_engine_override],
            "override",
        )

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
        return EngineResolutionResult(
            ENGINE_V3, ENGINE_DISPLAY_NAMES[ENGINE_V3], source
        )
    if (
        env_raw in {"1", "true", "yes", "on", "v4"}
        or read_positive_int_env("USE_PULSEFLOW_ENGINE", 0, 0) == 1
    ):
        return EngineResolutionResult(
            ENGINE_V4,
            ENGINE_DISPLAY_NAMES[ENGINE_V4],
            source,
        )

    # 5. 系统默认：全面平滑切流至 PulseFlow (v4)，除非显式指定 v3 或开启回滚闸
    return EngineResolutionResult(
        ENGINE_V4,
        ENGINE_DISPLAY_NAMES[ENGINE_V4],
        "default",
    )
