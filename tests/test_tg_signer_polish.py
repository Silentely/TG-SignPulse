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
from types import SimpleNamespace

import pytest

from tg_signer.async_utils import create_logged_task
from tg_signer.core.client import (
    _CLIENT_ASYNC_LOCKS,
    _CLIENT_INSTANCES,
    _CLIENT_REFS,
    Client,
)
from tg_signer.core.runtime import UserMonitor, UserSigner


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
        monkeypatch.setattr("tg_signer.core.runtime.sc_send", fake_push)

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
        assert "Failed to finalize test-task" in caplog.text
        # 即使 on_done 异常，任务自身的异常仍被取出并记录，不丢失
        assert "test-task failed: boom" in caplog.text


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
