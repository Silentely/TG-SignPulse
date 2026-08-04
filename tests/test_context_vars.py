"""context_vars 与任务级重试回退语义测试。

拆分时 contextvar 从 backend.services.sign_tasks 下沉到 tg_signer/context_vars.py：
默认值必须为 0（未设置），否则 CLI 独立运行时 SIGN_TASK_FLOW_RETRY_ATTEMPTS
环境变量失效（恒为 1）。本测试锁定该回归。
"""
from __future__ import annotations

import os

from tg_signer.context_vars import task_retry_count_var


def _flow_attempts_with_context() -> int:
    """sign_a_chat 内部重试读取逻辑（同款表达式）。"""
    max_flow_attempts = 1
    _ctx_val = task_retry_count_var.get()
    if _ctx_val and _ctx_val > 0:
        max_flow_attempts = _ctx_val
    else:
        max_flow_attempts = int(os.getenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "1"))
    return max_flow_attempts


def test_default_is_unset_zero():
    """默认值 0 表示"未设置"，signer_runner 的 >0 判定不命中。"""
    assert task_retry_count_var.get() == 0


def test_env_used_when_context_unset(monkeypatch):
    """CLI 场景（contextvar 未 set）：回退到 SIGN_TASK_FLOW_RETRY_ATTEMPTS。"""
    monkeypatch.setenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "3")
    assert _flow_attempts_with_context() == 3


def test_context_value_overrides_env(monkeypatch):
    """backend 场景（contextvar 已 set）：以 contextvar 为准。"""
    monkeypatch.setenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "3")
    token = task_retry_count_var.set(5)
    try:
        assert _flow_attempts_with_context() == 5
    finally:
        task_retry_count_var.reset(token)


def test_negative_or_zero_context_falls_back_to_env(monkeypatch):
    """backend set 0/负值时按"未设置"处理，回退 env。"""
    monkeypatch.setenv("SIGN_TASK_FLOW_RETRY_ATTEMPTS", "2")
    token = task_retry_count_var.set(0)
    try:
        assert _flow_attempts_with_context() == 2
    finally:
        task_retry_count_var.reset(token)
