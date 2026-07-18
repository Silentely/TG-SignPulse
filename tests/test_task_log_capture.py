"""
任务过程日志采集回归：确保 UserSigner 过程日志进入 TaskLogHandler / flow_logs。

历史问题：runtime 使用 logger 名 "tg_signer"，后端 TaskLogHandler 挂在 "tg-signer"，
导致面板只剩「开始执行任务 / 消息更新监听 / 任务执行完成」外壳行。
"""

from __future__ import annotations

import logging

from backend.services.sign_task_backend import TaskLogHandler
from backend.utils.task_logs import normalize_log_line
from tg_signer.core import runtime as runtime_mod


def test_runtime_logger_name_matches_task_log_handler_target():
    """runtime 与后端采集必须使用同一 logger 名。"""
    assert runtime_mod.logger.name == "tg-signer"
    assert logging.getLogger("tg-signer") is runtime_mod.logger


def test_task_log_handler_captures_runtime_process_logs():
    """模拟 sign_tasks.run_task_with_logs 的挂载方式，过程日志必须进入列表。"""
    log_list: list[str] = []
    handler = TaskLogHandler(log_list)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))

    tg_logger = logging.getLogger("tg-signer")
    prev_level = tg_logger.level
    tg_logger.addHandler(handler)
    if tg_logger.getEffectiveLevel() > logging.INFO:
        tg_logger.setLevel(logging.INFO)

    try:
        # 与 BaseUserWorker.log 一致的消息形态
        runtime_mod.logger.info("账户「dahao」- 任务「emby-厂妹」: 开始登录...")
        runtime_mod.logger.warning(
            "账户「dahao」- 任务「emby-厂妹」: "
            "Preheated peer with cached username: 1429576125 -> @EmbyPublicBot"
        )
        runtime_mod.logger.info(
            "账户「dahao」- 任务「emby-厂妹」: 开始第 1/3 次脚本流程尝试"
        )
        runtime_mod.logger.info(
            "账户「dahao」- 任务「emby-厂妹」: 第 2/2 步将在 1 秒后执行：识图后点按钮"
        )
        runtime_mod.logger.info("账户「dahao」- 任务「emby-厂妹」: 点击完成")
        runtime_mod.logger.info(
            "账户「dahao」- 任务「emby-厂妹」: 第 2/2 步执行完成：识图后点按钮"
        )
    finally:
        tg_logger.removeHandler(handler)
        tg_logger.setLevel(prev_level)

    joined = "\n".join(log_list)
    assert "开始登录" in joined
    assert "Preheated peer" in joined
    assert "开始第 1/3 次脚本流程尝试" in joined
    assert "识图后点按钮" in joined
    assert "点击完成" in joined

    # 旧错误名不得再收到过程日志（若误挂旧名，列表应为空）
    wrong_list: list[str] = []
    wrong_handler = TaskLogHandler(wrong_list)
    wrong_handler.setLevel(logging.INFO)
    wrong_logger = logging.getLogger("tg_signer")
    wrong_logger.addHandler(wrong_handler)
    try:
        runtime_mod.logger.info("账户「x」- 任务「y」: 不应进入旧 logger")
    finally:
        wrong_logger.removeHandler(wrong_handler)
    assert wrong_list == []


def test_captured_lines_normalize_for_frontend_display():
    """采集行经后端 normalize 后仍含业务文案，供前端二次清洗。"""
    raw = (
        "2026-07-18 20:54:20,896 - "
        "账户「dahao」- 任务「emby-厂妹」: 开始第 1/3 次脚本流程尝试"
    )
    normalized = normalize_log_line(raw)
    assert "开始第 1/3 次脚本流程尝试" in normalized
    assert "账户「dahao」" in normalized
