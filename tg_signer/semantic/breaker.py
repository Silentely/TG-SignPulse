from __future__ import annotations

import time
from typing import Any, Literal

BreakerState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """JEV 语义接口熔断器。

    状态流转：
    - closed: 正常调用。连续失败达到 failure_threshold（默认 5）后进入 open。
    - open: 熔断中（默认 60s）。所有请求被立即阻断降级，返回 escalate（走人工），绝不允许默认 approve。
    - half_open: 熔断到期（>= 60s）。允许且仅允许 1 个试水探测请求：
      - 试水成功：恢复 closed，重置连续失败计数为 0。
      - 试水失败：重新进入 open，重置 60s 冷却计时。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout = max(0.1, recovery_timeout)
        self.consecutive_failures: int = 0
        self.last_failure_time: float = 0.0
        self.state: BreakerState = "closed"
        self._probe_in_flight: bool = False

    def get_state(self, now: float | None = None) -> BreakerState:
        if now is None:
            now = time.monotonic()
        if self.state == "open":
            if now - self.last_failure_time >= self.recovery_timeout:
                return "half_open"
        return self.state

    def allow_request(self, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        curr_state = self.get_state(now)
        if curr_state == "closed":
            return True
        if curr_state == "half_open":
            # 仅放行 1 个试水探测请求
            if not self._probe_in_flight:
                self._probe_in_flight = True
                self.state = "half_open"
                return True
            return False
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "closed"
        self._probe_in_flight = False

    def record_failure(self, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        self.consecutive_failures += 1
        self.last_failure_time = now
        self._probe_in_flight = False
        if self.consecutive_failures >= self.failure_threshold or self.state == "half_open":
            self.state = "open"

    def reset(self) -> None:
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.state = "closed"
        self._probe_in_flight = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.get_state(),
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }
