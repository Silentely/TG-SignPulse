"""
backend/services/sign_task_runner.py 单元测试

覆盖范围：
- 运行中重入拦截
- 任务配置缺失的失败路径与失败通知
- 账号预检失效：跳过执行且不再发失败通知
- 成功主链路：阶段推进/冷却等待/凭据解析/补抓最后消息/成功通知
- database is locked 重试与最终失败
- 执行超时 → FailureCategory.TIMEOUT
- 回复含失败关键词且强失败 → 成功翻转
- 关键词监听刷新成功与失败分支
- file/string 双 session 模式与 SIGN_TASK_FORCE_IN_MEMORY 分支
- 补抓最后消息超时跳过分支

策略：svc 使用行为可编程的 FakeSvc；Telegram 相关 seam 全部 monkeypatch；
asyncio.sleep 默认替换为 no-op 加速，依赖真实超时的用例用 Event().wait() 悬挂。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from backend.services.sign_task_run_status import (
    PHASE_CHECKING_ACCOUNT,
    PHASE_COOLDOWN,
    PHASE_FINALIZING,
    PHASE_RUNNING,
    PHASE_WAITING_LOCK,
)
from backend.services.sign_task_runner import execute_sign_task


class FakeSvc:
    """可编程的 SignTaskService 替身：仅提供 runner 依赖的行为"""

    def __init__(self, task_cfg: Optional[Dict[str, Any]] = None):
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._active_tasks: Dict[str, bool] = {}
        self._active_logs: Dict[str, List[str]] = {}
        self._cleanup_tasks: Dict[str, Any] = {}
        self._account_last_run_end: Dict[str, float] = {}
        self._account_cooldown_seconds = 0.0
        self.workdir = "/tmp/workdir"
        self.task_cfg = task_cfg
        self.requires_updates = False
        self.keyword_monitor = False
        self.proxy = None
        self.strong_failure = False
        self.fetch_last: Optional[str] = "抓到的最后消息"
        self.fetch_hangs = False
        # 观测点
        self.phases: List[str] = []
        self.saved: List[Dict[str, Any]] = []

    def is_task_running(self, task_name: str, account_name: str) -> bool:
        return False

    def _task_key(self, account_name: str, task_name: str) -> str:
        return f"{account_name}::{task_name}"

    def _update_run_phase(self, account_name: str, task_name: str, **kw: Any) -> None:
        self.phases.append(kw.get("phase"))

    def _resolve_task_dir(self, task_name: str, account_name: str):
        return "/fake/dir" if self.task_cfg is not None else None

    def _load_task_config(self, task_dir):
        return self.task_cfg

    def _task_requires_updates(self, cfg) -> bool:
        return self.requires_updates

    def _task_has_keyword_monitor(self, cfg) -> bool:
        return self.keyword_monitor

    def _get_effective_proxy(self, account_name: str):
        return self.proxy

    def _load_raw_task_config_dict(self, task_name: str, account_name: str):
        return {}

    def _is_invalid_session_error(self, e: Exception) -> bool:
        return False

    def _save_run_info(self, task_name, success, msg, account_name, flow_logs=None):
        self.saved.append(
            {
                "task": task_name,
                "success": success,
                "msg": msg,
                "account": account_name,
                "logs": list(flow_logs or []),
            }
        )

    def _message_indicates_strong_failure(self, msg: str) -> bool:
        return self.strong_failure

    async def _fetch_last_target_message_from_chat_history(self, signer, task_cfg):
        if self.fetch_hangs:
            await asyncio.Event().wait()  # 悬挂，等待外层 wait_for 取消
        return self.fetch_last

    def _prune_stale_entries(self) -> None:
        return None


class FakeSigner:
    """BackendUserSigner 替身：run_once 行为由类属性 behavior 编程"""

    instances: List["FakeSigner"] = []
    behavior = None  # async def behavior(run_calls: int) -> None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.run_calls = 0
        FakeSigner.instances.append(self)

    async def run_once(self, num_of_dialogs: int = 20):
        self.run_calls += 1
        if FakeSigner.behavior is not None:
            await FakeSigner.behavior(self.run_calls)


class _DummyTask:
    def done(self):
        return True

    def cancel(self):
        return None


class _FakeSettings:
    def __init__(self, session_dir):
        self._session_dir = session_dir

    def resolve_session_dir(self):
        return self._session_dir


class _FakeConfigService:
    def get_telegram_config(self):
        return {"api_id": "12345", "api_hash": "fake-hash"}


async def _noop_sleep(_seconds):
    return None


def _fake_create_logged_task(coro, **kwargs):
    # 不在后台保留 60s 清理协程，直接关闭防止悬挂告警
    coro.close()
    return _DummyTask()


@pytest.fixture
def runner_env(monkeypatch, tmp_path):
    """统一装配 runner 的全部外部 seam，返回观测字典"""

    class Env:
        def __init__(self):
            self.check_account_result: Optional[str] = None
            self.notifications: List[tuple] = []
            self.success_notifications: List[dict] = []
            self.invalid_marks: List[dict] = []
            self.monitor_restarts = 0
            self.monitor_fails = False
            self.session_mode = "string"
            self.session_string: Optional[str] = "session-str"
            self.session_string_file: Optional[str] = None
            self.execution_timeout = 5.0
            self.fast_sleep = True

    env = Env()

    async def fake_check_account_before_task(**kwargs):
        return env.check_account_result

    async def fake_send_failure_notification(**kwargs):
        env.notifications.append(("failure", kwargs))

    async def fake_send_success_notification(**kwargs):
        env.success_notifications.append(kwargs)

    async def fake_mark_account_invalid(**kwargs):
        env.invalid_marks.append(kwargs)

    class _FakeMonitorService:
        async def restart_from_tasks(self):
            env.monitor_restarts += 1
            if env.monitor_fails:
                raise RuntimeError("monitor restart boom")

    async def _apply():
        return None

    monkeypatch.setattr(
        "backend.services.sign_task_notify.check_account_before_task",
        fake_check_account_before_task,
    )
    monkeypatch.setattr(
        "backend.services.sign_task_notify.send_failure_notification",
        fake_send_failure_notification,
    )
    monkeypatch.setattr(
        "backend.services.sign_task_notify.send_success_notification",
        fake_send_success_notification,
    )
    monkeypatch.setattr(
        "backend.services.sign_task_notify.mark_account_invalid",
        fake_mark_account_invalid,
    )
    monkeypatch.setattr(
        "backend.services.keyword_monitor.get_keyword_monitor_service",
        lambda: _FakeMonitorService(),
    )
    monkeypatch.setattr(
        "backend.services.config.get_config_service", lambda: _FakeConfigService()
    )
    monkeypatch.setattr(
        "backend.services.sign_task_backend.BackendUserSigner", FakeSigner
    )
    monkeypatch.setattr(
        "backend.services.runtime_settings.get_execution_timeout",
        lambda: env.execution_timeout,
    )
    monkeypatch.setattr(
        "backend.services.runtime_settings.get_flow_retry_attempts", lambda: 3
    )
    monkeypatch.setattr(
        "backend.services.sign_tasks.settings", _FakeSettings(tmp_path)
    )
    monkeypatch.setattr(
        "backend.utils.tg_session.get_session_mode", lambda: env.session_mode
    )
    monkeypatch.setattr(
        "backend.utils.tg_session.get_account_session_string",
        lambda account: env.session_string,
    )
    monkeypatch.setattr(
        "backend.utils.tg_session.load_session_string_file",
        lambda session_dir, account: env.session_string_file,
    )
    monkeypatch.setattr(
        "tg_signer.async_utils.create_logged_task", _fake_create_logged_task
    )
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)

    # asyncio.sleep 加速在最后装配，允许单测关闭
    original_sleep = asyncio.sleep

    def _install_fast_sleep():
        monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    env._install_fast_sleep = _install_fast_sleep  # type: ignore[attr-defined]
    env._original_sleep = original_sleep  # type: ignore[attr-defined]
    _install_fast_sleep()

    FakeSigner.instances = []
    FakeSigner.behavior = None

    yield env

    FakeSigner.instances = []
    FakeSigner.behavior = None


class TestEarlyReturn:
    """运行中重入拦截"""

    @pytest.mark.asyncio
    async def test_already_running_returns_immediately(self, runner_env):
        class RunningSvc(FakeSvc):
            def is_task_running(self, task_name, account_name):
                return True

        svc = RunningSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert "已经在运行中" in result["error"]
        assert result["failure_category"] is None
        assert svc.saved == []


class TestConfigMissing:
    """任务配置缺失的失败路径"""

    @pytest.mark.asyncio
    async def test_missing_config_fails_and_notifies(self, runner_env):
        svc = FakeSvc(task_cfg=None)
        result = await execute_sign_task(svc, "acc", "ghost")
        assert result["success"] is False
        assert "does not exist" in result["error"]
        assert result["timed_out"] is False
        # 失败通知已发、运行记录已写、清理状态收敛
        assert len(runner_env.notifications) == 1
        assert svc.saved[0]["success"] is False
        assert svc._active_tasks[svc._task_key("acc", "ghost")] is False


class TestAccountPrecheck:
    """账号预检失效：跳过执行主体且不再发失败通知"""

    @pytest.mark.asyncio
    async def test_invalid_account_skips_execution(self, runner_env):
        runner_env.check_account_result = "AuthKeyUnregistered"
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert "登录已失效" in result["error"]
        # 未进入执行阶段，未发失败通知（账号失效自有专门通道）
        assert FakeSigner.instances == []
        assert runner_env.notifications == []
        assert PHASE_FINALIZING not in svc.phases


class TestSuccessPath:
    """成功主链路"""

    @pytest.mark.asyncio
    async def test_happy_path_full_flow(self, runner_env):
        svc = FakeSvc(task_cfg={"name": "t", "actions": []})
        result = await execute_sign_task(svc, "acc", "t", run_id="r-1")
        assert result["success"] is True
        assert result["timed_out"] is False
        # 阶段推进完整
        for phase in (
            PHASE_CHECKING_ACCOUNT,
            PHASE_WAITING_LOCK,
            PHASE_RUNNING,
            PHASE_FINALIZING,
        ):
            assert phase in svc.phases
        # signer 按预期装配并以 string 模式拿到会话
        signer = FakeSigner.instances[0]
        assert signer.run_calls == 1
        assert signer.kwargs["session_string"] == "session-str"
        assert signer.kwargs["in_memory"] is True
        assert signer.kwargs["api_id"] == 12345  # 走 config 路径（env 已清除）
        # 补抓最后消息并写入日志流
        assert "任务对象最后一条消息: 抓到的最后消息" in result["output"]
        # 成功通知与运行记录
        assert runner_env.success_notifications[0]["message"] == "抓到的最后消息"
        assert svc.saved[0]["success"] is True
        assert svc._active_tasks[svc._task_key("acc", "t")] is False

    @pytest.mark.asyncio
    async def test_cooldown_wait_updates_phase(self, runner_env):
        import time as _time

        svc = FakeSvc(task_cfg={"name": "t"})
        svc._account_cooldown_seconds = 10.0
        svc._account_last_run_end["acc"] = _time.time()
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert PHASE_COOLDOWN in svc.phases
        assert "等待账号冷却" in result["output"]

    @pytest.mark.asyncio
    async def test_keyword_monitor_refresh_success_log(self, runner_env):
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.keyword_monitor = True
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert runner_env.monitor_restarts == 1
        assert "关键词监听说明" in result["output"]

    @pytest.mark.asyncio
    async def test_keyword_monitor_refresh_failure_logged(self, runner_env):
        runner_env.monitor_fails = True
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.keyword_monitor = True
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "关键词后台监听刷新失败" in result["output"]


class TestSessionModes:
    """session 模式分支"""

    @pytest.mark.asyncio
    async def test_file_mode_with_fallback_string(self, runner_env):
        runner_env.session_mode = "file"
        runner_env.session_string_file = "file-fallback-str"
        svc = FakeSvc(task_cfg={"name": "t"})
        await execute_sign_task(svc, "acc", "t")
        signer = FakeSigner.instances[0]
        assert signer.kwargs["session_string"] == "file-fallback-str"
        assert signer.kwargs["in_memory"] is True

    @pytest.mark.asyncio
    async def test_file_mode_without_string(self, runner_env):
        runner_env.session_mode = "file"
        runner_env.session_string_file = None
        svc = FakeSvc(task_cfg={"name": "t"})
        await execute_sign_task(svc, "acc", "t")
        signer = FakeSigner.instances[0]
        assert signer.kwargs["session_string"] is None
        assert signer.kwargs["in_memory"] is False

    @pytest.mark.asyncio
    async def test_force_in_memory_disabled_env(self, runner_env, monkeypatch):
        # 显式关闭 in-memory：即使存在 .session_string 也不用
        runner_env.session_mode = "file"
        runner_env.session_string_file = "file-fallback-str"
        monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "0")
        svc = FakeSvc(task_cfg={"name": "t"})
        await execute_sign_task(svc, "acc", "t")
        signer = FakeSigner.instances[0]
        assert signer.kwargs["session_string"] is None
        assert signer.kwargs["in_memory"] is False

    @pytest.mark.asyncio
    async def test_string_mode_missing_session_fails(self, runner_env):
        runner_env.session_string = None
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert "session_string 不存在" in result["error"]
        # 账号被判失效并走专门标记通道
        assert len(runner_env.invalid_marks) == 1


class TestDatabaseLockedRetry:
    """database is locked 重试"""

    @pytest.mark.asyncio
    async def test_retry_until_success(self, runner_env):
        async def behavior(run_calls: int):
            if run_calls < 3:
                raise Exception("database is locked")

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert FakeSigner.instances[0].run_calls == 3
        assert "Session 被锁定" in result["output"]

    @pytest.mark.asyncio
    async def test_retry_exhausted_fails(self, runner_env):
        async def behavior(run_calls: int):
            raise Exception("database is locked")

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert FakeSigner.instances[0].run_calls == 5  # 五次尝试后抛出
        assert len(runner_env.notifications) == 1


class TestTimeout:
    """执行超时"""

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self, runner_env):
        runner_env.execution_timeout = 0.05

        async def behavior(run_calls: int):
            await asyncio.Event().wait()  # 悬挂等待外层取消

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert result["timed_out"] is True
        assert result["failure_category"] == "timeout"
        assert "超时" in result["error"]
        assert len(runner_env.notifications) == 1


class TestStrongFailureFlip:
    """回复含失败关键词且强失败 → 成功翻转"""

    @pytest.mark.asyncio
    async def test_reply_failure_keywords_flip_success(self, runner_env):
        import logging

        async def behavior(run_calls: int):
            logging.getLogger("tg-signer").info(
                "收到来自「签到Bot」的消息: Message: text: 签到失败，请稍后再试"
            )

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.strong_failure = True
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is False
        assert "机器人回复疑似失败" in result["error"]
        assert "机器人回复疑似失败" in result["output"]
        assert len(runner_env.notifications) == 1

    @pytest.mark.asyncio
    async def test_reply_without_strong_failure_stays_success(self, runner_env):
        import logging

        async def behavior(run_calls: int):
            logging.getLogger("tg-signer").info(
                "收到来自「签到Bot」的消息: Message: text: 本次没有失败关键词判定"
            )

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.strong_failure = False
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        # last_reply 提取自日志行
        assert result["error"] == ""

    @pytest.mark.asyncio
    async def test_reply_broad_keywords_no_longer_flip_success(self, runner_env):
        """ narrowed keyword list should not flip on generic words like 错误/异常 """
        import logging

        async def behavior(run_calls: int):
            logging.getLogger("tg-signer").info(
                "收到来自「签到Bot」的消息: Message: text: 验证码错误，但签到成功"
            )

        FakeSigner.behavior = behavior
        svc = FakeSvc(task_cfg={"name": "t"})
        # strong_failure=True 会让 _message_indicates_strong_failure 返回 True，
        # 但 runner 侧 failure_keywords 已不再含"错误"/"异常"，因此不应翻转。
        svc.strong_failure = True
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "机器人回复疑似失败" not in result.get("error", "")


class TestFetchLastTargetTimeout:
    """补抓最后消息超时跳过"""

    @pytest.mark.asyncio
    async def test_fetch_timeout_is_skipped(self, runner_env, monkeypatch):
        monkeypatch.setenv("SIGN_TASK_LAST_TARGET_FETCH_TIMEOUT", "0.05")
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.fetch_hangs = True
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "补抓任务对象最后消息超时" in result["output"]
        # 无最后消息行
        assert "任务对象最后一条消息" not in result["output"]

    @pytest.mark.asyncio
    async def test_fetch_generic_error_falls_back_empty(self, runner_env):
        async def _boom(self, signer, task_cfg):
            raise RuntimeError("fetch boom")

        svc = FakeSvc(task_cfg={"name": "t"})
        svc._fetch_last_target_message_from_chat_history = _boom.__get__(svc)
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "任务对象最后一条消息" not in result["output"]

    @pytest.mark.asyncio
    async def test_fetch_timeout_disabled_zero(self, runner_env, monkeypatch):
        # timeout<=0 时不包 wait_for，直接 await
        monkeypatch.setenv("SIGN_TASK_LAST_TARGET_FETCH_TIMEOUT", "0")
        svc = FakeSvc(task_cfg={"name": "t"})
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "任务对象最后一条消息: 抓到的最后消息" in result["output"]


class TestMiscBranches:
    """其余零散分支收尾"""

    @pytest.mark.asyncio
    async def test_proxy_applied_to_signer(self, runner_env):
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.proxy = "http://127.0.0.1:7890"
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        proxy = FakeSigner.instances[0].kwargs["proxy"]
        assert proxy is not None
        assert isinstance(proxy, dict)

    @pytest.mark.asyncio
    async def test_existing_account_lock_is_reused(self, runner_env):
        svc = FakeSvc(task_cfg={"name": "t"})
        pre_existing = asyncio.Lock()
        svc._account_locks["acc"] = pre_existing
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        # 锁被复用而非重建
        assert svc._account_locks["acc"] is pre_existing

    @pytest.mark.asyncio
    async def test_reply_image_branch_extracted(self, runner_env, monkeypatch):
        import logging

        async def behavior(run_calls: int):
            logging.getLogger("tg-signer").info(
                "收到来自「签到Bot」的消息: Message: text: \n图片: reward.png"
            )

        FakeSigner.behavior = behavior
        # text: 空内容的日志行必然被 extract_last_target_message 的 text 循环捞走，
        # 为隔离 runner 自身的回复解析结果，打桩提取器与补抓返回空
        # （runner 为函数内局部导入，运行时取模块属性，打桩模块即生效）
        monkeypatch.setattr(
            "backend.utils.task_logs.extract_last_target_message", lambda logs: ""
        )
        svc = FakeSvc(task_cfg={"name": "t"})
        svc.fetch_last = None
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert result["error"] == ""
        # last_reply 走 [图片] 分支，进入成功通知
        assert runner_env.success_notifications[0]["message"] == "[图片] reward.png"

    @pytest.mark.asyncio
    async def test_pending_cleanup_task_cancelled(self, runner_env):
        class _PendingTask:
            def __init__(self):
                self.cancelled = False

            def done(self):
                return False

            def cancel(self):
                self.cancelled = True

        pending = _PendingTask()
        svc = FakeSvc(task_cfg={"name": "t"})
        svc._cleanup_tasks[svc._task_key("acc", "t")] = pending
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert pending.cancelled is True

    @pytest.mark.asyncio
    async def test_cooldown_elapsed_no_wait_log(self, runner_env):
        import time as _time

        svc = FakeSvc(task_cfg={"name": "t"})
        svc._account_cooldown_seconds = 10.0
        svc._account_last_run_end["acc"] = _time.time() - 60  # 冷却已过
        result = await execute_sign_task(svc, "acc", "t")
        assert result["success"] is True
        assert "等待账号冷却" not in result["output"]
