"""sign_task_backend 适配层测试：TaskLogHandler 日志写入与 BackendUserSigner 目录解析/交互禁令。"""

from __future__ import annotations

import logging

import pytest

from backend.services import sign_task_backend
from backend.services.sign_task_backend import BackendUserSigner, TaskLogHandler
from backend.services.sign_tasks import SignTaskService


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, None)


class TestTaskLogHandler:
    """验证日志规范化写入、溢出裁剪与异常容忍。"""

    def test_emit_strips_timestamp_prefix(self):
        logs: list[str] = []
        TaskLogHandler(logs).emit(_make_record("2026-07-31 10:00:00 - 签到成功"))
        assert logs == ["签到成功"]

    def test_emit_falls_back_to_raw_message_when_normalized_empty(self):
        logs: list[str] = []
        TaskLogHandler(logs).emit(_make_record("2026-07-31 10:00:00 - "))
        # 规范化后为空串时保留原始消息，避免日志凭空丢失
        assert logs == ["2026-07-31 10:00:00 - "]

    def test_emit_trims_to_max_lines_default(self):
        logs: list[str] = [f"old-{i}" for i in range(2000)]
        TaskLogHandler(logs).emit(_make_record("新日志"))
        assert len(logs) == 2000
        assert logs[0] == "old-1"
        assert logs[-1] == "新日志"

    def test_emit_respects_custom_max_lines(self):
        logs: list[str] = [f"old-{i}" for i in range(5)]
        TaskLogHandler(logs, max_lines=5).emit(_make_record("新日志"))
        assert len(logs) == 5
        assert logs[0] == "old-1"
        assert logs[-1] == "新日志"

    def test_emit_error_goes_to_handle_error(self, monkeypatch):
        logs: list[str] = []
        handled: list[logging.LogRecord] = []

        def _boom(_value):
            raise RuntimeError("format exploded")

        monkeypatch.setattr(sign_task_backend, "normalize_log_line", _boom)
        handler = TaskLogHandler(logs)
        monkeypatch.setattr(handler, "handleError", handled.append)
        record = _make_record("任意消息")
        handler.emit(record)
        assert logs == []
        assert handled == [record]


def _bare_signer(tmp_path, account: str = "acct", task_name: str = "task1"):
    """绕过 UserSigner.__init__（其会创建 Pyrogram 客户端），手工装配目录属性。"""

    signer = object.__new__(BackendUserSigner)
    signer._workdir = tmp_path
    signer._account = account
    signer.task_name = task_name
    return signer


class TestTaskDirResolution:
    """task_dir 三级解析：账号目录优先，其次 legacy 目录，最后回退账号目录。"""

    def test_prefers_account_dir_with_config(self, tmp_path):
        signer = _bare_signer(tmp_path)
        account_dir = tmp_path / "signs" / "acct" / "task1"
        legacy_dir = tmp_path / "signs" / "task1"
        for d in (account_dir, legacy_dir):
            d.mkdir(parents=True)
            (d / "config.json").write_text("{}", encoding="utf-8")
        assert signer.task_dir == account_dir

    def test_falls_back_to_legacy_dir(self, tmp_path):
        signer = _bare_signer(tmp_path)
        legacy_dir = tmp_path / "signs" / "task1"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.json").write_text("{}", encoding="utf-8")
        assert signer.task_dir == legacy_dir

    def test_defaults_to_account_dir_when_no_config(self, tmp_path):
        signer = _bare_signer(tmp_path)
        assert signer.task_dir == tmp_path / "signs" / "acct" / "task1"


class TestInteractiveGuards:
    """后端模式下所有交互式入口必须直接抛错。"""

    def test_ask_for_config_raises(self, tmp_path):
        signer = _bare_signer(tmp_path)
        with pytest.raises(ValueError, match="禁止交互式输入"):
            signer.ask_for_config()

    def test_reconfig_raises(self, tmp_path):
        signer = _bare_signer(tmp_path)
        with pytest.raises(ValueError, match="禁止交互式输入"):
            signer.reconfig()

    def test_ask_one_raises(self, tmp_path):
        signer = _bare_signer(tmp_path)
        with pytest.raises(ValueError, match="禁止交互式输入"):
            signer.ask_one()


class TestActiveLogCap:
    """运行中实时日志封顶：_append_active_log 超限时从头部裁剪。"""

    def _svc(self) -> SignTaskService:
        svc = object.__new__(SignTaskService)
        svc._active_logs = {}
        return svc

    def test_appends_and_creates_key(self):
        svc = self._svc()
        svc._append_active_log(("a", "t"), "第一行")
        assert svc._active_logs[("a", "t")] == ["第一行"]

    def test_trims_head_over_cap(self):
        svc = self._svc()
        key = ("a", "t")
        for i in range(svc.MAX_ACTIVE_LOG_LINES + 10):
            svc._append_active_log(key, f"line-{i}")
        logs = svc._active_logs[key]
        assert len(logs) == svc.MAX_ACTIVE_LOG_LINES
        assert logs[0] == "line-10"  # 最旧的 10 行被裁剪
        assert logs[-1] == f"line-{svc.MAX_ACTIVE_LOG_LINES + 9}"


class TestActiveLogsSince:
    """增量日志拉取：总数未变 O(1) 短路、新增切片、裁剪后全量重推。"""

    def _svc(self) -> SignTaskService:
        svc = object.__new__(SignTaskService)
        svc._active_logs = {}
        svc._append_active_log(("a", "t"), "L1")
        svc._append_active_log(("a", "t"), "L2")
        svc._append_active_log(("a", "t"), "L3")
        return svc

    def test_no_change_returns_empty_with_same_total(self):
        svc = self._svc()
        logs, total = svc.get_active_logs_since("t", "a", 3)
        assert logs == []
        assert total == 3

    def test_new_lines_slice_increment(self):
        svc = self._svc()
        svc._append_active_log(("a", "t"), "L4")
        logs, total = svc.get_active_logs_since("t", "a", 3)
        assert logs == ["L4"]
        assert total == 4

    def test_total_shrink_retriggers_full(self):
        """头部裁剪导致 total 回退时全量重推（last_idx 越界兜底）。"""
        svc = self._svc()
        # 模拟头部裁剪：直接替换为更短的列表
        svc._active_logs[("a", "t")] = ["X1", "X2"]
        logs, total = svc.get_active_logs_since("t", "a", 3)
        assert total == 2
        assert logs == ["X1", "X2"]

    def test_account_none_matches_first_same_name_task(self):
        svc = self._svc()
        svc._append_active_log(("b", "t"), "other")
        logs, total = svc.get_active_logs_since("t", None, 3)
        assert logs == []
        assert total == 3  # 命中第一个同名任务的 3 行
