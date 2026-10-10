"""
测试工具函数

提供通用的测试辅助功能，包括时间处理、配置生成、
异步测试辅助、临时文件管理等。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar

T = TypeVar("T")


def utc_now_naive() -> datetime:
    """返回当前 UTC 时间（无时区信息），与后端模型一致"""
    return datetime.utcnow()


def utc_now_aware() -> datetime:
    """返回当前 UTC 时间（带时区信息）"""
    return datetime.now(tz=timezone.utc)


def cst_now() -> datetime:
    """返回当前中国标准时间（UTC+8）"""
    return datetime.now(tz=timezone(timedelta(hours=8)))


def make_timestamp(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    """生成指定偏移量的时间戳（无时区）"""
    return utc_now_naive() - timedelta(days=days_ago, hours=hours_ago)


# ---------- 临时目录/文件管理 ----------


class TempDirManager:
    """临时目录管理器，自动清理"""

    def __init__(self):
        self._dirs: List[str] = []

    def create(self, prefix: str = "tg_signpulse_test_") -> Path:
        """创建临时目录并跟踪"""
        d = tempfile.mkdtemp(prefix=prefix)
        self._dirs.append(d)
        return Path(d)

    def cleanup(self):
        """清理所有已创建的临时目录"""
        import shutil

        for d in self._dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        self._dirs.clear()


def create_temp_config_file(
    config_data: Dict[str, Any],
    directory: Optional[Path] = None,
    filename: str = "config.json",
) -> Path:
    """在指定目录下创建临时 JSON 配置文件"""
    if directory is None:
        directory = Path(tempfile.mkdtemp())
    config_file = directory / filename
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as fp:
        json.dump(config_data, fp, ensure_ascii=False)
    return config_file


# ---------- 异步测试辅助 ----------


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """在新的事件循环中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def async_return(value: T) -> T:
    """包装同步值为异步返回"""
    return value


async def async_raise(exc: Exception):
    """包装异常为异步抛出"""
    raise exc


# ---------- 并发测试辅助 ----------


class ThreadStartupError(RuntimeError):
    """并发线程未能全部进入就绪状态，或未能在限时内结束。

    典型成因是解释器级竞态：覆盖追踪器会给每个新线程安装追踪函数
    （threading._trace_hook 在 _bootstrap_inner 中调用 _sys.settrace），多个
    线程同时启动时可能抛出 RuntimeError，使该线程在进入目标函数前死亡。
    此时线程不会执行 work，因此重拉一个不产生副作用。
    """


def run_threads_together(
    work: Callable[[int], T],
    count: int,
    *,
    ready_timeout: float = 10.0,
    join_timeout: float = 10.0,
) -> List[T]:
    """启动 count 个线程，待全部就绪后同时放行，按序号返回各线程的返回值。

    相对 threading.Barrier 的差别：Barrier 少一个参与者就永久等待，而线程在
    启动阶段死亡（见 ThreadStartupError）属环境级偶发事件。这里改用「就绪标记
    + 事件门闸」：为每个序号启动线程，就绪前死亡的线程会被重新拉起（work 尚未
    执行，重拉无副作用），全部就绪后才放行。启动竞态最多拖慢用例，不会挂死 CI；
    超过 ready_timeout 仍未凑齐或超过 join_timeout 仍未结束，则抛
    ThreadStartupError，而不是无限阻塞。

    work 收到线程序号，返回值按序号收集；work 内抛出的异常会在主线程重抛。
    """
    if count < 1:
        raise ValueError(f"count 必须 >= 1，收到 {count}")

    results: List[Any] = [None] * count
    failures: List[BaseException] = []
    lock = threading.Lock()
    ready_cond = threading.Condition(lock)
    ready_flags = [False] * count
    start_gate = threading.Event()
    cancelled = threading.Event()
    threads: Dict[int, threading.Thread] = {}

    def _run(index: int) -> None:
        with ready_cond:
            ready_flags[index] = True
            ready_cond.notify_all()
        start_gate.wait(timeout=join_timeout)
        if cancelled.is_set():
            # 就绪阶段已判定失败：不再执行 work，避免失败回合产生副作用
            return
        try:
            results[index] = work(index)
        except BaseException as exc:  # 带回主线程，由调用方断言
            with lock:
                failures.append(exc)

    deadline = time.monotonic() + ready_timeout
    try:
        while not all(ready_flags):
            for index in range(count):
                current = threads.get(index)
                if ready_flags[index] or (current is not None and current.is_alive()):
                    continue
                thread = threading.Thread(
                    target=_run, args=(index,), name=f"together-{index}"
                )
                threads[index] = thread
                thread.start()
            if time.monotonic() >= deadline:
                raise ThreadStartupError(
                    f"{count} 个线程在 {ready_timeout}s 内仅 {sum(ready_flags)} 个就绪"
                )
            with ready_cond:
                ready_cond.wait_for(lambda: all(ready_flags), timeout=0.05)
    except ThreadStartupError:
        cancelled.set()
        raise
    finally:
        start_gate.set()

    for thread in threads.values():
        thread.join(timeout=join_timeout)
    stuck = [index for index, thread in threads.items() if thread.is_alive()]
    if stuck:
        raise ThreadStartupError(f"线程 {stuck} 在 {join_timeout}s 内未结束")
    if failures:
        raise failures[0]
    return results


# ---------- 环境变量管理 ----------


class EnvManager:
    """
    环境变量管理器，支持批量设置和自动恢复

    用法:
        env = EnvManager()
        env.set("KEY", "VALUE")
        # ... 测试 ...
        env.restore()  # 恢复原始值
    """

    def __init__(self):
        self._originals: Dict[str, Optional[str]] = {}

    def set(self, key: str, value: str):
        """设置环境变量，保存原始值"""
        if key not in self._originals:
            self._originals[key] = os.environ.get(key)
        os.environ[key] = value

    def unset(self, key: str):
        """删除环境变量，保存原始值"""
        if key not in self._originals:
            self._originals[key] = os.environ.get(key)
        os.environ.pop(key, None)

    def restore(self):
        """恢复所有修改过的环境变量"""
        for key, original in self._originals.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        self._originals.clear()


# ---------- 断言辅助 ----------


def assert_dict_subset(subset: Dict[str, Any], full: Dict[str, Any]):
    """断言 subset 中的所有键值对都存在于 full 中"""
    for key, value in subset.items():
        assert key in full, f"缺少键: {key}"
        assert full[key] == value, (
            f"键 {key} 的值不匹配: 期望 {value}, 实际 {full[key]}"
        )


def assert_datetime_recent(dt: Optional[datetime], max_seconds: int = 60):
    """断言时间戳在最近 max_seconds 秒内"""
    assert dt is not None, "时间戳为 None"
    now = utc_now_naive()
    diff = abs((now - dt).total_seconds())
    assert diff < max_seconds, f"时间戳 {dt} 距今 {diff:.1f}s，超出 {max_seconds}s 范围"


# ---------- JSON 序列化辅助 ----------


class DateTimeEncoder(json.JSONEncoder):
    """支持 datetime 的 JSON 编码器"""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def json_dumps(data: Any) -> str:
    """JSON 序列化，支持 datetime"""
    return json.dumps(data, cls=DateTimeEncoder, ensure_ascii=False)


# ---------- 配置测试常量 ----------

TEST_API_ID = "12345"
TEST_API_HASH = "test-api-hash-abcdef123456"
TEST_SECRET_KEY = "test-secret-key-for-jwt-0123456789"
TEST_OPENAI_API_KEY = "test-openai-key"
TEST_SESSION_STRING = "test-session-string-for-in-memory"
TEST_CHAT_ID = -1001234567890
TEST_USER_ID = 111111
