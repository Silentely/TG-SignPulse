"""历史条目格式化纯函数测试。"""

from __future__ import annotations

from backend.services.sign_task_history_format import (
    build_history_list_item,
    clamp_limit,
    normalize_flow_logs,
)
from backend.utils.task_logs import extract_last_target_message


def test_clamp_limit():
    assert clamp_limit(0) == 1
    assert clamp_limit(50) == 50
    assert clamp_limit(9999, maximum=200) == 200
    assert clamp_limit("x") == 1


def test_normalize_flow_logs():
    assert normalize_flow_logs(None) == []
    assert normalize_flow_logs(["a"]) == ["a"]


def test_build_history_run_entry_and_prepend():
    from backend.services.sign_task_history_format import (
        build_history_run_entry,
        prepend_history_entry,
    )

    entry = build_history_run_entry(
        success=True,
        message="ok",
        account_name="a1",
        timestamp="t1",
        normalized_logs=["l1"],
        flow_truncated=False,
        flow_line_count=1,
        last_target_message="bot",
        failure_category="",
        repair=lambda s: s,
    )
    assert entry["time"] == "t1"
    assert entry["flow_logs"] == ["l1"]
    hist = prepend_history_entry([{"time": "old"}], entry, max_entries=2)
    assert hist[0]["time"] == "t1"
    assert len(hist) == 2
    hist2 = prepend_history_entry(None, entry, max_entries=1)
    assert len(hist2) == 1


def test_normalize_and_trim_flow_logs():
    from backend.services.sign_task_history_format import normalize_and_trim_flow_logs

    lines, truncated, total = normalize_and_trim_flow_logs(
        ["a", "b", "c"],
        repair=lambda s: s,
        max_lines=2,
        max_line_chars=10,
    )
    assert total == 3
    assert truncated is True
    assert lines == ["b", "c"]

    long_lines, long_trunc, _ = normalize_and_trim_flow_logs(
        ["x" * 20],
        repair=lambda s: s,
        max_line_chars=5,
    )
    assert long_trunc is True
    assert long_lines[0].endswith("…")
    assert len(long_lines[0]) == 5


def test_build_history_list_item():
    item = {
        "time": "2026-07-16T10:00:00",
        "success": False,
        "message": "fail",
        "flow_logs": ["line1"],
        "failure_category": "timeout",
    }
    out = build_history_list_item(
        item,
        task_name="t1",
        account_name="a1",
        repair=lambda s: s,
        extract_last_target=lambda logs: "target",
    )
    assert out["task_name"] == "t1"
    assert out["account_name"] == "a1"
    assert out["created_at"] == "2026-07-16T10:00:00"
    assert out["failure_category"] == "timeout"
    assert out["last_target_message"] == "target"


def test_extract_last_target_message_multiline_robot_reply():
    """测试多行回复与冒号后换行场景下的正确提取。"""
    flow_logs = [
        "消息更新监听: 开启",
        "开始执行任务: emby-厂妹 (账号: dahao)",
        "步骤 [step_0] 开始执行：Action-step_0",
        "文本消息到 1429576125: /checkin",
        "签到命令已发送",
        "步骤 [step_0] 执行完成（成功）",
        "步骤 [step_1] 开始执行：Action-step_1",
        "收到回复：请在 30 秒内点击图中事物的按钮以完成签到 / 每天只有一次机会，失败或者过期当天不可重试 | 按钮: 外星人 | 口罩 | 路由器 | 键盘",
        "AI 正在分析图片并匹配可点击按钮",
        "AI 请求 | method=choose_options_by_image",
        "AI 响应 | selected=[路由器]",
        "点击完成",
        "步骤 [step_1] 执行完成（成功）",
        "步骤 [step_1_wait] 开始执行：Wait_event-step_1_wait",
        "等待机器人回复确认，超时 90 秒",
        "收到机器人回复：\n🎉 签到成功，获得了 3 积分\n总分: 1354",
        "命中成功规则：\n签到成功",
        "机器人已确认签到成功",
        "步骤 [step_1_wait] 执行完成（成功）",
        "PulseFlow (v4) 执行成功：共推进 3 个节点，耗时 9134.5ms",
    ]
    extracted = extract_last_target_message(flow_logs)
    assert extracted == "🎉 签到成功，获得了 3 积分\n总分: 1354"


def test_format_history_entry_prefers_final_confirmation_over_stale_captcha():
    """测试历史记录中即使被错误保存为中间验证码提示，展示时优先提取最终确认结果。"""
    flow_logs = [
        "收到回复：请在 30 秒内点击图中事物的按钮以完成签到 | 按钮: 外星人 | 口罩",
        "步骤 [step_1_wait] 开始执行",
        "收到机器人回复：\n🎉 签到成功，获得了 3 积分\n总分: 1354",
        "命中成功规则：签到成功",
        "机器人已确认签到成功",
    ]
    item = {
        "time": "2026-11-20T12:27:00",
        "success": True,
        "message": "🎉 签到成功，获得了 3 积分 总分: 1354",
        "flow_logs": flow_logs,
        # 模拟旧代码遗留的错误中间步骤记录
        "last_target_message": "请在 30 秒内点击图中事物的按钮以完成签到 | 按钮: 外星人 | 口罩",
    }
    formatted = build_history_list_item(
        item,
        task_name="emby-厂妹",
        account_name="dahao",
        repair=lambda s: s,
        extract_last_target=extract_last_target_message,
    )
    assert formatted["last_target_message"] == "🎉 签到成功，获得了 3 积分\n总分: 1354"
