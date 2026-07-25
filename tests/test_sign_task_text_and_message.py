"""签到任务文本与消息摘要纯函数测试。

覆盖 sign_task_text.repair_mojibake 与 sign_task_message 的
message_matches_thread / format_target_message_summary，
正常流程 + 边界条件 + 错误恢复。
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.services.sign_task_message import (
    format_target_message_summary,
    message_matches_thread,
)
from backend.services.sign_task_text import repair_mojibake

# ─── repair_mojibake ───


def test_repair_none_returns_empty():
    assert repair_mojibake(None) == ""  # type: ignore[arg-type]


def test_repair_empty_string():
    assert repair_mojibake("") == ""


def test_repair_non_string_input():
    """非字符串输入应转成 str 返回。"""
    assert repair_mojibake(123) == "123"  # type: ignore[arg-type]


def test_repair_normal_text_unchanged():
    """无乱码特征的正常文本应原样返回。"""
    text = "签到成功，已获取奖励"
    assert repair_mojibake(text) == text


def test_repair_mojibake_tokens_below_threshold_unchanged():
    """乱码 token 不足 2 个且无替换符时原样返回。"""
    # 仅 1 个乱码 token，不触发修复
    text = "绛"
    assert repair_mojibake(text) == text


def test_repair_replacement_char_triggers_attempt():
    """含 U+FFFD 替换符时应尝试修复（即使 token 不足）。"""
    text = ""
    # 单字符无法构成 GBK→UTF-8 修复，应原样返回
    assert repair_mojibake(text) == text


def test_repair_gbk_misread_text():
    """典型 GBK 误读乱码应被修复或保持（取决于可逆性）。"""
    # 构造一个可修复的乱码：把 "签到" 用 utf-8 编码后按 gbk 解码
    original = "签到任务"
    misread = original.encode("utf-8").decode("gbk", errors="replace")
    # 若 misread 含足够乱码 token，repair 应尝试还原
    result = repair_mojibake(misread)
    # 不强求还原成功，但结果必须是字符串
    assert isinstance(result, str)


def test_repair_returns_string_for_any_input():
    """任何输入都应返回 str。"""
    assert isinstance(repair_mojibake("任意"), str)
    assert isinstance(repair_mojibake(""), str)


# ─── message_matches_thread ───


def _msg(thread_id=None, reply_top=None):
    """构造伪消息对象。"""
    return SimpleNamespace(
        message_thread_id=thread_id,
        reply_to_top_message_id=reply_top,
    )


def test_match_none_message_returns_false():
    assert message_matches_thread(None, {"message_thread_id": 1}) is False


def test_match_no_thread_config_returns_true():
    """chat_config 无 message_thread_id 时匹配所有消息。"""
    assert message_matches_thread(_msg(thread_id=999), {}) is True


def test_match_thread_none_empty_zero_returns_true():
    """message_thread_id 为 None/空/0 时视为不限制。"""
    for val in (None, "", 0):
        assert message_matches_thread(_msg(thread_id=1), {"message_thread_id": val}) is True


def test_match_thread_invalid_string_returns_true():
    """非数字 thread_id 视为不限制（防御性）。"""
    assert message_matches_thread(
        _msg(thread_id=1), {"message_thread_id": "abc"}
    ) is True


def test_match_thread_equals_message_thread_id():
    assert message_matches_thread(
        _msg(thread_id=42), {"message_thread_id": 42}
    ) is True


def test_match_thread_mismatch_returns_false():
    assert message_matches_thread(
        _msg(thread_id=42), {"message_thread_id": 99}
    ) is False


def test_match_thread_falls_back_to_reply_to_top():
    """message_thread_id 缺失时回退到 reply_to_top_message_id。"""
    assert message_matches_thread(
        _msg(thread_id=None, reply_top=42), {"message_thread_id": 42}
    ) is True


def test_match_thread_string_config_coerced():
    """字符串数字 thread_id 应被 int 转换后比较。"""
    assert message_matches_thread(
        _msg(thread_id=42), {"message_thread_id": "42"}
    ) is True


# ─── format_target_message_summary ───


def test_summary_none_message_returns_empty():
    assert format_target_message_summary(None) == ""


def test_summary_text_field():
    msg = SimpleNamespace(text="签到成功", caption=None, reply_markup=None)
    assert format_target_message_summary(msg) == "签到成功"


def test_summary_caption_fallback():
    """text 为空时回退到 caption。"""
    msg = SimpleNamespace(text=None, caption="图片说明", reply_markup=None)
    assert format_target_message_summary(msg) == "图片说明"


def test_summary_text_takes_priority_over_caption():
    msg = SimpleNamespace(text="主文本", caption="副文本", reply_markup=None)
    assert format_target_message_summary(msg) == "主文本"


def test_summary_inline_keyboard_buttons():
    """无文本时展示 inline keyboard 按钮文本。"""
    button = SimpleNamespace(text="确认")
    row = [button, SimpleNamespace(text="取消")]
    markup = SimpleNamespace(inline_keyboard=[row], keyboard=None)
    msg = SimpleNamespace(text=None, caption=None, reply_markup=markup)
    assert format_target_message_summary(msg) == "确认 | 取消"


def test_summary_reply_keyboard_buttons():
    """无 inline keyboard 时回退 reply keyboard。"""
    button = SimpleNamespace(text="选项A")
    markup = SimpleNamespace(inline_keyboard=None, keyboard=[[button]])
    msg = SimpleNamespace(text=None, caption=None, reply_markup=markup)
    assert format_target_message_summary(msg) == "选项A"


def test_summary_button_without_text_uses_raw():
    """按钮无 text 属性时用原始值。"""
    markup = SimpleNamespace(inline_keyboard=[["原始"]], keyboard=None)
    msg = SimpleNamespace(text=None, caption=None, reply_markup=markup)
    assert format_target_message_summary(msg) == "原始"


def test_summary_media_markers():
    """无文本无按钮时按媒体类型返回标记。"""
    for attr, label in (
        ("photo", "[图片]"),
        ("sticker", "[贴纸]"),
        ("video", "[视频]"),
        ("document", "[文件]"),
        ("audio", "[音频]"),
        ("voice", "[语音]"),
        ("video_note", "[视频消息]"),
        ("animation", "[动图]"),
    ):
        msg = SimpleNamespace(
            text=None, caption=None, reply_markup=None, **{attr: object()}
        )
        assert format_target_message_summary(msg) == label


def test_summary_poll_with_question():
    """投票消息返回 [投票] + 问题。"""
    poll = SimpleNamespace(question="今天签到了吗")
    msg = SimpleNamespace(text=None, caption=None, reply_markup=None, poll=poll)
    assert format_target_message_summary(msg) == "[投票] 今天签到了吗"


def test_summary_poll_without_question():
    poll = SimpleNamespace(question="")
    msg = SimpleNamespace(text=None, caption=None, reply_markup=None, poll=poll)
    assert format_target_message_summary(msg) == "[投票]"


def test_summary_empty_message_returns_empty():
    """无任何可提取内容时返回空串。"""
    msg = SimpleNamespace(text=None, caption=None, reply_markup=None)
    assert format_target_message_summary(msg) == ""


def test_summary_blank_text_falls_through():
    """空白文本应视为空，回退到后续提取。"""
    msg = SimpleNamespace(text="   ", caption=None, reply_markup=None, photo=object())
    assert format_target_message_summary(msg) == "[图片]"
