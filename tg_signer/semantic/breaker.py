from __future__ import annotations

import time
from typing import Any, Literal

BreakerState = Literal["closed", "open", "half_open"]


class ProbeLease:
    """管理一次熔断器探测或调用的生命周期契约。

    无论调用成功、失败、异常、取消或早退，通过 lease.release() 在 finally 块中
    安全释放 in-flight 探测位，防止熔断器死锁或永远停在 half_open。
    """

    def __init__(
        self,
        breaker: CircuitBreaker,
        allowed: bool,
        generation: int,
        is_probe: bool,
    ) -> None:
        self.breaker = breaker
        self.allowed = allowed
        self.generation = generation
        self.is_probe = is_probe
        self.finished = False

    def record_success(self) -> None:
        if not self.finished:
            self.finished = True
            self.breaker.record_success(self.generation, is_probe=self.is_probe)

    def record_failure(self, now: float | None = None) -> None:
        if not self.finished:
            self.finished = True
            self.breaker.record_failure(self.generation, is_probe=self.is_probe, now=now)

    def release(self) -> None:
        """兜底释放：如果请求未显式记录成功/失败（例如协程取消 CancelledError 或早退），确保释放试水探测位。"""
        if not self.finished:
            self.finished = True
            self.breaker.release_probe(self.generation, is_probe=self.is_probe)


class CircuitBreaker:
    """JEV 语义接口熔断器。

    状态流转与安全契约：
    - closed: 正常调用。连续失败达到 failure_threshold（默认 5）后进入 open 并提升代次（generation）。
    - open: 熔断中（默认 60s）。所有请求被立即阻断降级，返回 escalate（走人工），绝不允许默认 approve。
      旧请求（先前代次）即使返回 200 也绝不可关闭当前 open 的熔断或清除计数。
    - half_open: 熔断到期（>= 60s）。允许且仅允许 1 个试水探测请求：
      - 试水成功：仅当试水请求代次与当前代次一致时，恢复 closed，重置连续失败计数。
      - 试水失败：重新进入 open，重置 60s 冷却计时，递增代次。
      - 取消/异常早退：通过 ProbeLease 释放探测标志位，保证下次请求可继续试水，绝不永远停在 half_open。
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
        self.generation: int = 0
        self._probe_in_flight: bool = False

    def get_state(self, now: float | None = None) -> BreakerState:
        if now is None:
            now = time.monotonic()
        if self.state == "open":
            if now - self.last_failure_time >= self.recovery_timeout:
                return "half_open"
        return self.state

    def acquire(self, now: float | None = None) -> ProbeLease:
        """申请执行权限，返回 ProbeLease。"""
        if now is None:
            now = time.monotonic()
        curr_state = self.get_state(now)
        if curr_state == "closed":
            return ProbeLease(self, allowed=True, generation=self.generation, is_probe=False)
        if curr_state == "half_open":
            if not self._probe_in_flight:
                self._probe_in_flight = True
                self.state = "half_open"
                return ProbeLease(self, allowed=True, generation=self.generation, is_probe=True)
            return ProbeLease(self, allowed=False, generation=self.generation, is_probe=False)
        return ProbeLease(self, allowed=False, generation=self.generation, is_probe=False)

    def allow_request(self, now: float | None = None) -> bool:
        """向后兼容的轻量查询方法。"""
        if now is None:
            now = time.monotonic()
        curr_state = self.get_state(now)
        if curr_state == "closed":
            return True
        if curr_state == "half_open":
            if not self._probe_in_flight:
                self._probe_in_flight = True
                self.state = "half_open"
                return True
            return False
        return False

    def record_success(
        self,
        request_generation: int | None = None,
        is_probe: bool = False,
        now: float | None = None,
    ) -> None:
        """记录调用成功。

        安全约束：
        - 只有当前代次的探测成功才允许将 half_open 转为 closed 并重置计数；
        - 若当前处于 open，旧请求成功绝不可关闭熔断或清零计数；
        - 若代次不符（旧请求慢返回），忽略该成功记录。
        """
        if self.state == "open":
            if self.get_state(now) == "half_open":
                self.state = "half_open"
            else:
                return

        curr_state = self.get_state(now)
        if curr_state == "half_open" or self.state == "half_open":
            # 仅当前代的试水请求（或直接兼容调用）才能恢复熔断器
            if (is_probe or request_generation is None) and (
                request_generation is None or request_generation == self.generation
            ):
                self.consecutive_failures = 0
                self.state = "closed"
                self._probe_in_flight = False
            return

        if curr_state == "closed":
            if request_generation is None or request_generation == self.generation:
                self.consecutive_failures = 0
            self._probe_in_flight = False

    def record_failure(
        self,
        request_generation: int | None = None,
        is_probe: bool = False,
        now: float | None = None,
    ) -> None:
        """记录调用失败。"""
        if now is None:
            now = time.monotonic()

        curr_state = self.get_state(now)
        self.consecutive_failures += 1
        self.last_failure_time = now
        self._probe_in_flight = False

        if curr_state == "half_open" or self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self.generation += 1

    def release_probe(self, request_generation: int | None = None, is_probe: bool = False) -> None:
        """释放探测位（用于 CancelledError 或未显式完成时的安全回收）。"""
        if is_probe:
            self._probe_in_flight = False

    def reset(self) -> None:
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.state = "closed"
        self.generation = 0
        self._probe_in_flight = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.get_state(),
            "generation": self.generation,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }
