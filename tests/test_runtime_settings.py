"""运行时设置解析单元测试。"""

from __future__ import annotations

from unittest.mock import patch

from backend.services.runtime_settings import (
    get_execution_timeout,
    get_sign_interval_seconds,
    resolve_int_setting,
)


def test_resolve_prefers_global_over_env(monkeypatch):
    monkeypatch.setenv("SIGN_TASK_EXECUTION_TIMEOUT", "999")
    assert (
        resolve_int_setting(
            {"sign_task_execution_timeout": 120},
            "sign_task_execution_timeout",
            "SIGN_TASK_EXECUTION_TIMEOUT",
            300,
            min_v=30,
            max_v=3600,
        )
        == 120
    )


def test_resolve_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("SIGN_TASK_EXECUTION_TIMEOUT", "180")
    assert (
        resolve_int_setting(
            {},
            "sign_task_execution_timeout",
            "SIGN_TASK_EXECUTION_TIMEOUT",
            300,
        )
        == 180
    )


def test_resolve_clamps_minmax():
    assert (
        resolve_int_setting(
            {"sign_task_execution_timeout": 5},
            "sign_task_execution_timeout",
            "SIGN_TASK_EXECUTION_TIMEOUT",
            300,
            min_v=30,
            max_v=3600,
        )
        == 30
    )


def test_get_execution_timeout_default(monkeypatch):
    monkeypatch.delenv("SIGN_TASK_EXECUTION_TIMEOUT", raising=False)
    with patch(
        "backend.services.runtime_settings._global_settings",
        return_value={},
    ):
        assert get_execution_timeout() == 300


def test_get_execution_timeout_reads_global(monkeypatch):
    monkeypatch.delenv("SIGN_TASK_EXECUTION_TIMEOUT", raising=False)
    with patch(
        "backend.services.runtime_settings._global_settings",
        return_value={"sign_task_execution_timeout": 321},
    ):
        assert get_execution_timeout() == 321


def test_sign_interval_none_when_empty():
    with patch(
        "backend.services.runtime_settings._global_settings",
        return_value={"sign_interval": None},
    ):
        assert get_sign_interval_seconds() is None
