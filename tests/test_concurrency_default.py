"""全局并发默认值测试 — 覆盖 tg_session.py 的 _resolve_concurrency_limit"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest


class TestResolveConcurrencyLimit:
    """_resolve_concurrency_limit 应正确处理优先级和默认值"""

    def test_env_var_takes_priority(self):
        """环境变量 TG_GLOBAL_CONCURRENCY 优先级最高"""
        from backend.utils.tg_session import _resolve_concurrency_limit

        with patch.dict(os.environ, {"TG_GLOBAL_CONCURRENCY": "10"}):
            assert _resolve_concurrency_limit() == 10

    def test_env_var_invalid_falls_through(self):
        """环境变量无效值应降级到下一级"""
        from backend.utils.tg_session import _resolve_concurrency_limit

        with patch.dict(os.environ, {"TG_GLOBAL_CONCURRENCY": "abc"}):
            result = _resolve_concurrency_limit()
            assert isinstance(result, int)
            assert result >= 1

    def test_env_var_zero_clamped_to_one(self):
        """环境变量 0 应被钳制为 1"""
        from backend.utils.tg_session import _resolve_concurrency_limit

        with patch.dict(os.environ, {"TG_GLOBAL_CONCURRENCY": "0"}):
            assert _resolve_concurrency_limit() == 1

    def test_dynamic_default_based_on_cpu(self):
        """无环境变量且无保存配置时应返回 min(cpu_count, 5)"""
        from backend.utils.tg_session import _resolve_concurrency_limit

        mock_service = MagicMock()
        mock_service.get_global_settings.return_value = {}
        with patch.dict(os.environ, {}, clear=False), \
             patch("backend.utils.tg_session.os.getenv", side_effect=lambda k, *a: os.environ.get(k, "")), \
             patch("backend.services.config.get_config_service", return_value=mock_service):
            result = _resolve_concurrency_limit()
            cpu_count = os.cpu_count() or 4
            expected = min(cpu_count, 5)
            assert result == expected

    def test_result_is_at_least_one(self):
        """任何情况下返回值应 >= 1"""
        from backend.utils.tg_session import _resolve_concurrency_limit

        result = _resolve_concurrency_limit()
        assert result >= 1


class TestUpdateGlobalSemaphore:
    """update_global_semaphore 应能运行时更新信号量"""

    def test_update_changes_semaphore_limit(self):
        """更新后信号量应使用新值"""
        from backend.utils.tg_session import update_global_semaphore, get_global_semaphore

        original = get_global_semaphore()
        original_limit = original._value

        update_global_semaphore(20)
        updated = get_global_semaphore()
        assert updated._value == 20

        # 恢复
        update_global_semaphore(original_limit)
