"""
后端签到执行适配层：日志 Handler 与非交互 UserSigner。
"""

from __future__ import annotations

import logging
from typing import List

from backend.utils.task_logs import normalize_log_line
from tg_signer.core import UserSigner


class TaskLogHandler(logging.Handler):
    """将日志实时写入内存列表，供 WebSocket / 轮询读取。"""

    def __init__(self, log_list: List[str]):
        super().__init__()
        self.log_list = log_list

    def emit(self, record):
        try:
            msg = normalize_log_line(self.format(record)) or record.getMessage()
            self.log_list.append(msg)
            if len(self.log_list) > 1000:
                self.log_list.pop(0)
        except Exception:
            self.handleError(record)


class BackendUserSigner(UserSigner):
    """
    后端专用 UserSigner：适配 signs_dir/account/task 目录结构，禁止交互式输入。
    """

    @property
    def task_dir(self):
        account_task_dir = self.tasks_dir / self._account / self.task_name
        if (account_task_dir / "config.json").exists():
            return account_task_dir
        legacy_task_dir = self.tasks_dir / self.task_name
        if (legacy_task_dir / "config.json").exists():
            return legacy_task_dir
        return account_task_dir

    def ask_for_config(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def reconfig(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def ask_one(self):
        raise ValueError("后端模式下禁止交互式输入")
