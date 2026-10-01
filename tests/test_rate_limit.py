"""InMemoryRateLimiter 桶清理与基础行为测试"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException


def _limiter(max_buckets: int | None = None):
    from backend.core.rate_limit import InMemoryRateLimiter

    return InMemoryRateLimiter(max_buckets=max_buckets)


def _hit(
    limiter, scope="auth.login", key="1.2.3.4", max_attempts=5, window=300, block=900
):
    return limiter.hit(
        scope=scope,
        key=key,
        max_attempts=max_attempts,
        window_seconds=window,
        block_seconds=block,
        detail="too many",
    )


class TestRateLimiterBasics:
    def test_allow_then_block(self):
        limiter = _limiter()
        for _ in range(5):
            _hit(limiter)  # 前 5 次放行
        with pytest.raises(HTTPException) as exc:
            _hit(limiter)  # 第 6 次触发封锁
        assert exc.value.status_code == 429
        assert exc.value.headers["Retry-After"]

    def test_reset_clears_bucket(self):
        limiter = _limiter()
        for _ in range(6):
            try:
                _hit(limiter)
            except HTTPException:
                pass
        with pytest.raises(HTTPException):
            _hit(limiter)
        limiter.reset("auth.login", "1.2.3.4")
        _hit(limiter)  # 重置后不再封锁

    def test_reset_all_clears_all(self):
        limiter = _limiter()
        _hit(limiter, key="a")
        _hit(limiter, key="b")
        limiter.reset_all()
        assert limiter._attempts == {}
        assert limiter._blocked_until == {}
        assert limiter._last_seen == {}


class TestRateLimiterSweep:
    def test_sweep_removes_stale_attempt_buckets(self):
        limiter = _limiter()
        # 模拟一个 1 小时前有过一次尝试、此后无请求的桶
        stale = time.monotonic() - 7200
        limiter._attempts[("auth.login", "ghost")] = __import__("collections").deque(
            [stale]
        )
        limiter._hits_since_sweep = limiter._SWEEP_INTERVAL - 1  # 下一次 hit 触发清扫
        _hit(limiter)
        assert ("auth.login", "ghost") not in limiter._attempts

    def test_sweep_keeps_recent_buckets(self):
        limiter = _limiter()
        limiter._attempts[("auth.login", "live")] = __import__("collections").deque(
            [time.monotonic()]
        )
        limiter._hits_since_sweep = limiter._SWEEP_INTERVAL - 1
        _hit(limiter)
        assert ("auth.login", "live") in limiter._attempts

    def test_sweep_removes_expired_blocks(self):
        limiter = _limiter()
        limiter._blocked_until[("auth.login", "old")] = time.monotonic() - 10
        limiter._blocked_until[("auth.login", "active")] = time.monotonic() + 100
        limiter._hits_since_sweep = limiter._SWEEP_INTERVAL - 1
        _hit(limiter)
        assert ("auth.login", "old") not in limiter._blocked_until
        assert ("auth.login", "active") in limiter._blocked_until

    def test_sweep_runs_only_every_interval(self):
        limiter = _limiter()
        limiter._attempts[("auth.login", "ghost")] = __import__("collections").deque(
            [time.monotonic() - 7200]
        )
        # 未到间隔：不触发清扫，陈旧桶保留（每次用新 key 避免触发封锁）
        for i in range(limiter._SWEEP_INTERVAL - 1):
            _hit(limiter, key=f"other-{i}")
        assert ("auth.login", "ghost") in limiter._attempts
        # 到达间隔：清扫生效
        _hit(limiter, key="trigger")
        assert ("auth.login", "ghost") not in limiter._attempts


class TestRateLimiterCapacityLimits:
    def test_prune_capacity_bounds_total_buckets(self):
        # 实例化一个小容量限流器 (100 桶)
        limiter = _limiter(max_buckets=100)
        assert limiter._max_buckets == 100

        # 连续注入 150 个不同 key，并逐次断言峰值严格受控在 max_buckets 以内
        peak = 0
        for i in range(150):
            _hit(limiter, key=f"user-{i}", max_attempts=5)
            peak = max(peak, len(limiter._last_seen))

        assert peak <= 100

    def test_active_block_not_evicted_by_random_traffic(self):
        limiter = _limiter(max_buckets=100)
        # 对 victim 触发封禁
        for _ in range(6):
            try:
                _hit(limiter, key="victim", max_attempts=5, block=300)
            except HTTPException:
                pass

        assert ("auth.login", "victim") in limiter._blocked_until

        # 伪造大量随机请求试图冲刷淘汰 victim 的封禁
        for i in range(150):
            _hit(limiter, key=f"attacker-probe-{i}", max_attempts=5)

        # 验证 victim 的封锁记录依然存在且有效
        assert ("auth.login", "victim") in limiter._blocked_until
        with pytest.raises(HTTPException) as exc:
            _hit(limiter, key="victim", max_attempts=5)
        assert exc.value.status_code == 429

    def test_single_bucket_deque_length_bounded(self):
        limiter = _limiter()
        bucket = ("auth.login", "flooder")
        for _ in range(10):
            _hit(limiter, key="flooder", max_attempts=20, window=1000)

        # deque 长度受控，不会无限堆积
        attempts = limiter._attempts[bucket]
        assert len(attempts) <= 22

    def test_emergency_cap_evicts_oldest_when_all_keys_blocked(self):
        """当极端情况下大量桶均处于活跃封锁状态时，第二阶段强制保底驱逐防止 OOM，硬上限在 max_buckets 以内。"""
        limiter = _limiter(max_buckets=100)
        # 产生 200 个全部处于活跃封禁的 key
        for i in range(200):
            for _ in range(6):
                try:
                    _hit(limiter, key=f"blocked-{i}", max_attempts=5, block=300)
                except HTTPException:
                    pass

        # 验证紧急上限生效，桶数被硬封顶在 max_buckets 以内
        assert len(limiter._last_seen) <= 100

    def test_saturated_limiter_does_not_reset_fresh_key_attempts(self):
        """当桶表饱和时，正在计数的 fresh key 不得被当做普通桶在第一阶段被意外驱逐而清零计数。"""
        limiter = _limiter(max_buckets=100)
        # 产生 99 个处于封禁状态的 key，将桶表顶到饱和边缘
        for i in range(99):
            for _ in range(6):
                try:
                    _hit(limiter, key=f"blocked-{i}", max_attempts=5, block=300)
                except HTTPException:
                    pass

        # 此时 fresh key 连续尝试失败，必须在达到第 6 次时被封禁（触发 HTTPException 429）
        fresh_key = "fresh-attacker"
        with pytest.raises(HTTPException) as exc_info:
            for _ in range(10):
                _hit(limiter, key=fresh_key, max_attempts=5, block=300)
        assert exc_info.value.status_code == 429
