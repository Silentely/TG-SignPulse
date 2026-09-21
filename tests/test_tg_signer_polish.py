"""tg_signer 打磨回归测试。

覆盖：
- _execute_ai_action 空结果检查（原实现误写 not result_empty_check，恒不触发）
- UserMonitor.on_message 中 Server酱 推送失败不中断其余监控项
- _click_inline_button 死分支清理后按文本位置参数点击
- create_logged_task done 回调异常时仍取出任务异常
- Client.__aexit__ 保留异步锁，避免退出/进入互斥失效
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from types import SimpleNamespace

import pytest
from pyrogram import errors as pyrogram_errors

from tg_signer.async_utils import (
    compute_backoff,
    create_logged_task,
    schedule_deferred_cleanup,
)
from tg_signer.compat import is_session_invalid_error
from tg_signer.core.client import (
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    Client,
    close_client_by_name,
)
from tg_signer.core.monitor import UserMonitor
from tg_signer.core.runtime import UserSigner
from tg_signer.utils import clamp


class TestComputeBackoff:
    """统一指数退避：shift=0 与 shift=1 两组语义与既有实现一致。"""

    def test_shift_zero_matches_1_2_4_8(self):
        assert [compute_backoff(i, cap=8) for i in range(1, 6)] == [1, 2, 4, 8, 8]

    def test_shift_one_matches_2_4_8(self):
        assert [compute_backoff(i, cap=8, shift=1) for i in range(1, 5)] == [2, 4, 8, 8]

    def test_lower_cap(self):
        assert [compute_backoff(i, cap=4, shift=1) for i in range(1, 5)] == [2, 4, 4, 4]

    def test_attempt_below_one_clamped(self):
        assert compute_backoff(0) == 1
        assert compute_backoff(-3) == 1


class TestClamp:
    """数值钳制助手：等价 max(low, min(value, high))。"""

    def test_within_range_unchanged(self):
        assert clamp(5, 1, 10) == 5

    def test_low_clip(self):
        assert clamp(-3, 1, 10) == 1

    def test_high_clip(self):
        assert clamp(42, 1, 10) == 10

    def test_float_value(self):
        assert clamp(0.5, 0.0, 1.0) == 0.5

    def test_inverted_bounds_returns_low(self):
        # max(low, min(value, high))：low>high 时 min 取 high，外层 max 取 low
        assert clamp(7, 10, 1) == 10


class TestScheduleDeferredCleanup:
    """延迟清理：到期且不活跃时弹出，活跃时保留，重复注册取消旧任务。"""

    @pytest.mark.asyncio
    async def test_pops_target_when_inactive_after_delay(self):
        registry: dict = {}
        active: dict = {"k": False}
        target: dict = {"k": "data"}
        schedule_deferred_cleanup(
            task_key="k",
            delay_seconds=0.01,
            registry=registry,
            active=active,
            target=target,
        )
        assert "k" in registry
        await asyncio.sleep(0.05)
        assert "k" not in target
        assert "k" not in registry  # 自身已注销

    @pytest.mark.asyncio
    async def test_keeps_target_when_still_active(self):
        registry: dict = {}
        active: dict = {"k": True}
        target: dict = {"k": "data"}
        schedule_deferred_cleanup(
            task_key="k",
            delay_seconds=0.01,
            registry=registry,
            active=active,
            target=target,
        )
        await asyncio.sleep(0.05)
        assert target.get("k") == "data"

    @pytest.mark.asyncio
    async def test_repeated_register_cancels_old_task(self):
        registry: dict = {}
        active: dict = {"k": False}
        target: dict = {"k": "data"}
        schedule_deferred_cleanup(
            task_key="k",
            delay_seconds=0.5,  # 旧任务睡眠较长
            registry=registry,
            active=active,
            target=target,
        )
        old_task = registry["k"]
        schedule_deferred_cleanup(
            task_key="k",
            delay_seconds=0.01,
            registry=registry,
            active=active,
            target=target,
        )
        await asyncio.sleep(0)  # 让事件循环处理 cancel，进入已取消状态
        assert old_task.cancelled()
        # 旧任务被取消后不得误删新注册条目（身份守卫）
        await asyncio.sleep(0.6)
        assert registry.get("k") is None or registry["k"] is not old_task
        await asyncio.sleep(0.05)
        assert "k" not in registry


class TestExecuteAiAction:
    """AI 调用样板：空结果检查（T1）"""

    @pytest.mark.asyncio
    async def test_empty_result_triggers_warning_and_returns_none(self):
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))

        async def ai_call():
            return ""

        result = await signer._execute_ai_action(
            method="test_method",
            ai_call=ai_call,
            model="test-model",
            request_meta={},
            result_meta={},
            action_log="开始 AI 调用",
            empty_result_log="AI 返回空结果",
            result_empty_check=lambda r: (r or "").strip(),
            success_log=lambda r: f"得到结果: {r}",
        )
        assert result is None
        assert ("WARNING", "AI 返回空结果") in logs

    @pytest.mark.asyncio
    async def test_non_empty_result_passes_through(self):
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))

        async def ai_call():
            return "有效内容"

        result = await signer._execute_ai_action(
            method="test_method",
            ai_call=ai_call,
            model="test-model",
            request_meta={},
            result_meta={},
            action_log="开始 AI 调用",
            empty_result_log="AI 返回空结果",
            result_empty_check=lambda r: (r or "").strip(),
            success_log=lambda r: f"得到结果: {r}",
        )
        assert result == "有效内容"
        assert ("WARNING", "AI 返回空结果") not in logs
        assert any(
            level == "DEBUG" and "得到结果: 有效内容" in msg
            for level, msg in logs
        )


class TestUserMonitorOnMessage:
    """监控消息处理：Server酱 推送隔离（T3）"""

    @pytest.mark.asyncio
    async def test_server_chan_push_failure_does_not_break_match_loop(
        self, monkeypatch, caplog
    ):
        sent = []
        monitor = UserMonitor.__new__(UserMonitor)

        async def fake_forward(_cfg, _msg):
            return None

        async def fake_get_send_text(_cfg, _msg):
            return "回复文本"

        async def fake_send(chat_id, text, delete_after=None):
            sent.append((chat_id, text))

        async def fake_push(*_args, **_kwargs):
            raise RuntimeError("network down")

        monitor.log = lambda msg, level="INFO", **kw: None
        monitor.forward_to_external = fake_forward
        monitor.get_send_text = fake_get_send_text
        monitor.send_message = fake_send
        monkeypatch.setattr("tg_signer.core.monitor.sc_send", fake_push)

        cfg1 = SimpleNamespace(
            match=lambda _m: True,
            external_forwards=[],
            push_via_server_chan=True,
            server_chan_send_key="sctp123t",
            chat_id=111,
            forward_to_chat_id=1,
            delete_after=None,
        )
        cfg2 = SimpleNamespace(
            match=lambda _m: True,
            external_forwards=[],
            push_via_server_chan=False,
            chat_id=222,
            forward_to_chat_id=2,
            delete_after=None,
        )
        monitor.config = SimpleNamespace(match_cfgs=[cfg1, cfg2])

        class Msg:
            chat = SimpleNamespace(id=100)
            text = "hello"

        with caplog.at_level(logging.WARNING, logger="tg-signer"):
            await monitor.on_message(None, Msg())

        # 第一个监控项推送失败被隔离，第二个监控项仍完成发送
        assert sent == [(1, "回复文本"), (2, "回复文本")]
        assert "Server酱推送失败" in caplog.text


class TestClickInlineButton:
    """按钮点击：死分支清理后按文本位置参数点击（T5）"""

    @pytest.mark.asyncio
    async def test_clicks_by_text_in_single_attempt(self):
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))

        clicked = []

        class Btn:
            callback_data = None
            text = "开始"

        class Msg:
            chat = SimpleNamespace(id=1)
            id = 2

            async def click(self, *args, **kwargs):
                clicked.append((args, kwargs))
                return True

        ok = await signer._click_inline_button(Msg(), Btn())
        assert ok is True
        # 仅按文本位置参数点击一次，不再尝试无效的 text= 关键字分支
        assert clicked == [(("开始",), {})]
        assert any("点击完成" in msg for _, msg in logs)

    @pytest.mark.asyncio
    async def test_click_inline_button_unconfirmed_tolerated(self):
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))
        signer.app = SimpleNamespace()
        signer.context = SimpleNamespace(last_callback_unconfirmed=True)

        async def fake_request_callback_answer(*args, **kwargs):
            return None

        signer.request_callback_answer = fake_request_callback_answer

        class Btn:
            callback_data = b"cb_data"
            text = "打印机"

        class Msg:
            chat = SimpleNamespace(id=1)
            id = 2

            async def click(self, *args, **kwargs):
                raise AssertionError("Message.click should not be called when callback_data exists")

        ok = await signer._click_inline_button(Msg(), Btn())
        assert ok is True
        assert any("未收到 API 显式回调" in msg for _, msg in logs)

    @pytest.mark.asyncio
    async def test_click_inline_button_strict_mode_rejects(self, monkeypatch):
        monkeypatch.setenv("TG_SIGNER_STRICT_CALLBACK_CONFIRMATION", "1")
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))
        signer.app = SimpleNamespace()
        signer.context = SimpleNamespace(last_callback_unconfirmed=True)

        async def fake_request_callback_answer(*args, **kwargs):
            return None

        signer.request_callback_answer = fake_request_callback_answer

        class Btn:
            callback_data = b"cb_data"
            text = "打印机"

        class Msg:
            chat = SimpleNamespace(id=1)
            id = 2

        ok = await signer._click_inline_button(Msg(), Btn())
        assert ok is False

    @pytest.mark.asyncio
    async def test_request_callback_answer_timeout_marks_unconfirmed(self, monkeypatch):
        monkeypatch.setenv("TG_SIGNER_CALLBACK_MAX_RETRIES", "1")
        monkeypatch.setenv("TG_SIGNER_CALLBACK_TIMEOUT", "1.0")
        logs = []
        signer = UserSigner.__new__(UserSigner)
        signer.log = lambda msg, level="INFO", **kw: logs.append((level, msg))
        signer.context = SimpleNamespace(last_callback_unconfirmed=False, last_callback_answer=None)

        call_count = 0

        class FakeClient:
            async def request_callback_answer(self, chat_id, message_id, callback_data, timeout):
                nonlocal call_count
                call_count += 1
                raise TimeoutError('Failed to invoke "messages.GetBotCallbackAnswer" after 0 retries')

        res = await signer.request_callback_answer(
            FakeClient(),
            chat_id=123,
            message_id=456,
            callback_data=b"test",
        )
        assert res is None
        assert call_count == 1
        assert signer.context.last_callback_unconfirmed is True
        assert any("未收到 API 显式应答" in msg for _, msg in logs)

    def test_selected_options_no_duplicate_when_single_choice(self):
        options = ["打印机", "口罩", "丝袜", "美女"]
        result = [1]
        selected_options = [
            options[0]
            if idx == 0
            else (
                options[idx - 1]
                if 1 <= idx <= len(options)
                else options[idx]
            )
            for idx in (result or [])
            if idx == 0
            or (1 <= idx <= len(options))
            or (0 <= idx < len(options))
        ]
        assert selected_options == ["打印机"]


class TestCreateLoggedTask:
    """后台任务 done 回调：on_done 异常时仍取出任务异常（T4）"""

    @pytest.mark.asyncio
    async def test_done_callback_failure_still_retrieves_task_exception(self, caplog):
        async def failing():
            raise ValueError("boom")

        def bad_on_done(_task):
            raise RuntimeError("on_done boom")

        with caplog.at_level(logging.ERROR, logger="tg_signer.async_utils"):
            task = create_logged_task(
                failing(),
                description="test-task",
                on_done=bad_on_done,
            )
            with pytest.raises(ValueError, match="boom"):
                await task
            await asyncio.sleep(0)  # 让 done 回调执行
        assert "收尾回调执行失败 test-task" in caplog.text
        # 即使 on_done 异常，任务自身的异常仍被取出并记录，不丢失
        assert "test-task 执行失败: boom" in caplog.text


class TestClientLockLifecycle:
    """客户端异步锁生命周期：退出后锁保留，避免互斥失效（T6）"""

    @pytest.mark.asyncio
    async def test_aexit_retains_lock_while_clearing_refs_and_instances(self):
        key = "test-lock-retain"
        _CLIENT_REFS[key] = 1
        _CLIENT_INSTANCES[key] = object()
        _CLIENT_ASYNC_LOCKS[key] = asyncio.Lock()

        client = Client.__new__(Client)
        client.key = key
        client.name = "test-client"
        stopped = []

        async def fake_stop():
            stopped.append(True)

        client.stop = fake_stop

        await client.__aexit__(None, None, None)

        # 锁保留：并发 __aenter__ 与本次退出持有同一锁对象，互斥不失效
        assert key in _CLIENT_ASYNC_LOCKS
        # 引用计数与实例已清理
        assert key not in _CLIENT_REFS
        assert key not in _CLIENT_INSTANCES
        assert stopped == [True]

        _CLIENT_ASYNC_LOCKS.pop(key, None)


class TestClientAenterRollback:
    """__aenter__ 连接失败/任务取消时原子回滚引用计数（T7）"""

    @staticmethod
    def _make_stop_recorder(stopped: list):
        async def _stop():
            stopped.append(True)

        return _stop

    @pytest.mark.asyncio
    async def test_cancelled_rolls_back_refs_without_stop(self):
        key = "test-aenter-cancel"
        _CLIENT_INSTANCES[key] = object()
        _CLIENT_ASYNC_LOCKS[key] = asyncio.Lock()
        stopped: list = []

        client = Client.__new__(Client)
        client.key = key
        client.name = "test-client"
        client.is_connected = False
        client.stop = self._make_stop_recorder(stopped)

        async def raise_cancelled():
            raise asyncio.CancelledError()

        client.connect = raise_cancelled

        try:
            with pytest.raises(asyncio.CancelledError):
                await client.__aenter__()

            # 引用计数与实例已回滚清理；未连接成功不触发 stop
            assert key not in _CLIENT_REFS
            assert key not in _CLIENT_INSTANCES
            assert stopped == []
        finally:
            _CLIENT_ASYNC_LOCKS.pop(key, None)

    @pytest.mark.asyncio
    async def test_session_invalid_rolls_back_and_stops(self):
        key = "test-aenter-session"
        _CLIENT_INSTANCES[key] = object()
        _CLIENT_ASYNC_LOCKS[key] = asyncio.Lock()
        stopped: list = []

        client = Client.__new__(Client)
        client.key = key
        client.name = "test-client"
        client.is_connected = True  # 模拟连接已建立后校验失败
        client.stop = self._make_stop_recorder(stopped)

        async def raise_invalid():
            raise pyrogram_errors.AuthKeyUnregistered()

        client.get_me = raise_invalid

        try:
            with pytest.raises(ConnectionError) as excinfo:
                await client.__aenter__()

            assert is_session_invalid_error(excinfo.value)

            # 已连接：回滚时执行 stop 清理
            assert key not in _CLIENT_REFS
            assert key not in _CLIENT_INSTANCES
            assert stopped == [True]
        finally:
            _CLIENT_ASYNC_LOCKS.pop(key, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("exc_factory", "expected_type"),
        [
            (
                lambda: TypeError(
                    "object NoneType can't be used in 'await' expression"
                ),
                "TypeError",
            ),
            (lambda: asyncio.TimeoutError("request timed out"), "TimeoutError"),
        ],
        ids=["库解析故障", "网络超时"],
    )
    async def test_get_me_failure_is_not_reported_as_session_invalid(
        self, exc_factory, expected_type
    ):
        """回归：get_me() 的非授权失败（库版本不兼容/网络等）不得标记为会话失效。

        修复前统一包装成 ``ConnectionError("Session invalid: ...")``，使解析/网络故障
        被上层误判为需要重新登录。
        """
        key = "test-aenter-parse-failure"
        _CLIENT_INSTANCES[key] = object()
        _CLIENT_ASYNC_LOCKS[key] = asyncio.Lock()
        stopped: list = []

        client = Client.__new__(Client)
        client.key = key
        client.name = "test-client"
        client.is_connected = True
        client.stop = self._make_stop_recorder(stopped)

        async def raise_failure():
            raise exc_factory()

        client.get_me = raise_failure

        try:
            with pytest.raises(ConnectionError) as excinfo:
                await client.__aenter__()

            err = excinfo.value
            assert not is_session_invalid_error(err)
            assert "Session invalid" not in str(err)
            assert f"Session check failed ({expected_type})" in str(err)
            assert isinstance(err.__cause__, type(exc_factory()))

            assert key not in _CLIENT_REFS
            assert key not in _CLIENT_INSTANCES
            assert stopped == [True]
        finally:
            _CLIENT_ASYNC_LOCKS.pop(key, None)


class TestCloseClientDualMode:
    """close_client_by_name 同时清理文件模式与内存模式双实例（T8）"""

    @staticmethod
    def _make_stop_recorder(stopped: list):
        async def _stop():
            stopped.append(True)

        return _stop

    @pytest.mark.asyncio
    async def test_closes_base_and_memory_keys(self, tmp_path):
        workdir = str(tmp_path)
        base_key = str(pathlib.Path(workdir).joinpath("acc1").resolve())
        mem_key = f"{base_key}::memory"
        stopped: list = []

        base_client = Client.__new__(Client)
        base_client.key = base_key
        base_client.is_connected = True
        base_client.stop = self._make_stop_recorder(stopped)

        mem_client = Client.__new__(Client)
        mem_client.key = mem_key
        mem_client.is_connected = False
        mem_client.stop = self._make_stop_recorder(stopped)

        _CLIENT_INSTANCES[base_key] = base_client
        _CLIENT_INSTANCES[mem_key] = mem_client
        _CLIENT_REFS[base_key] = 1
        _CLIENT_REFS[mem_key] = 1
        _CLIENT_ASYNC_LOCKS[base_key] = asyncio.Lock()
        _CLIENT_ASYNC_LOCKS[mem_key] = asyncio.Lock()

        try:
            await close_client_by_name("acc1", workdir=workdir)

            assert base_key not in _CLIENT_INSTANCES
            assert mem_key not in _CLIENT_INSTANCES
            assert base_key not in _CLIENT_REFS
            assert mem_key not in _CLIENT_REFS
            assert base_key not in _CLIENT_ASYNC_LOCKS
            assert mem_key not in _CLIENT_ASYNC_LOCKS
            # 仅已连接的文件模式实例执行 stop
            assert stopped == [True]
        finally:
            _CLIENT_INSTANCES.pop(base_key, None)
            _CLIENT_INSTANCES.pop(mem_key, None)
            _CLIENT_REFS.pop(base_key, None)
            _CLIENT_REFS.pop(mem_key, None)
            _CLIENT_ASYNC_LOCKS.pop(base_key, None)
            _CLIENT_ASYNC_LOCKS.pop(mem_key, None)

    @pytest.mark.asyncio
    async def test_no_instances_is_safe(self, tmp_path):
        workdir = str(tmp_path)
        base_key = str(pathlib.Path(workdir).joinpath("ghost").resolve())

        await close_client_by_name("ghost", workdir=workdir)

        assert base_key not in _CLIENT_INSTANCES
        assert base_key not in _CLIENT_REFS
        assert base_key not in _CLIENT_ASYNC_LOCKS
