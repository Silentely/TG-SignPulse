"""签到任务失败分类纯逻辑测试。

覆盖 classify_failure / message_indicates_strong_failure / failure_category_label
三个公开函数的正常流程、边界条件与错误恢复。
"""
from __future__ import annotations

from backend.services.sign_task_failure import (
    FailureCategory,
    classify_failure,
    failure_category_label,
    message_indicates_strong_failure,
)

# ─── classify_failure 正常流程 ───


def test_classify_success_true_returns_none():
    """success=True 时无论错误文本都返回 NONE。"""
    assert classify_failure(error="任意错误", success=True) == FailureCategory.NONE


def test_classify_session_invalid_by_english():
    assert classify_failure(error="invalid session", success=False) == FailureCategory.SESSION_INVALID


def test_classify_session_invalid_by_chinese():
    assert classify_failure(error="会话失效", success=False) == FailureCategory.SESSION_INVALID


def test_classify_flood_wait():
    assert classify_failure(error="FloodWait detected", success=False) == FailureCategory.FLOOD_WAIT


def test_classify_ai_timeout():
    assert classify_failure(error="AI timeout", success=False) == FailureCategory.AI_TIMEOUT


def test_classify_ai_error():
    assert classify_failure(error="openai quota exceeded", success=False) == FailureCategory.AI_ERROR


def test_classify_button_not_found():
    assert classify_failure(error="未找到按钮", success=False) == FailureCategory.BUTTON_NOT_FOUND


def test_classify_target_not_found():
    assert classify_failure(error="peer id invalid", success=False) == FailureCategory.TARGET_NOT_FOUND


def test_classify_network_proxy():
    assert classify_failure(error="connection reset by peer", success=False) == FailureCategory.NETWORK_PROXY


def test_classify_timeout_keyword():
    assert classify_failure(error="请求超时", success=False) == FailureCategory.TIMEOUT


def test_classify_output_text_also_scanned():
    """output 文本也应参与分类。"""
    assert classify_failure(output="session 失效", success=False) == FailureCategory.SESSION_INVALID


def test_classify_error_and_output_combined():
    assert classify_failure(error="error: proxy refused", output="socks5 failure", success=False) == FailureCategory.NETWORK_PROXY


# ─── 边界条件 ───


def test_classify_no_text_success_false_returns_unknown():
    """无文本且 success=False 时返回 UNKNOWN。"""
    assert classify_failure(success=False) == FailureCategory.UNKNOWN


def test_classify_no_text_success_none_returns_none():
    """无文本且 success=None 时返回 NONE（既非成功也非失败）。"""
    assert classify_failure() == FailureCategory.NONE


def test_classify_empty_strings_treated_as_no_text():
    assert classify_failure(error="", output="", success=False) == FailureCategory.UNKNOWN


def test_classify_whitespace_only_text():
    assert classify_failure(error="   \n  ", success=False) == FailureCategory.UNKNOWN


def test_classify_unknown_failure_when_no_keyword_match():
    """有文本但无关键词命中且非强失败语义 → UNKNOWN。"""
    assert classify_failure(error="something random", success=False) == FailureCategory.UNKNOWN


# ─── 强失败语义（message_indicates_strong_failure）───


def test_strong_failure_chinese_pattern():
    assert message_indicates_strong_failure("签到失败，请稍后重试") is True


def test_strong_failure_english_pattern():
    assert message_indicates_strong_failure("task failed: timed out") is True


def test_strong_failure_skipped_when_success_marker_present():
    """含成功标记时不判为强失败。"""
    assert message_indicates_strong_failure("签到失败，但已签到完成") is False


def test_strong_failure_empty_text():
    assert message_indicates_strong_failure("") is False


def test_strong_failure_none_text():
    assert message_indicates_strong_failure(None) is False  # type: ignore[arg-type]


def test_classify_strong_failure_branch():
    """无关键词命中但语义为强失败 → STRONG_FAILURE。"""
    assert classify_failure(error="执行失败", success=False) == FailureCategory.STRONG_FAILURE


# ─── failure_category_label ───


def test_label_none():
    assert failure_category_label(FailureCategory.NONE) == "正常"


def test_label_all_categories_have_chinese_label():
    """每个枚举值都应有中文标签。"""
    for category in FailureCategory:
        label = failure_category_label(category)
        assert isinstance(label, str)
        assert label  # 非空


def test_label_fallback_to_enum_value():
    """未知枚举值回退到 enum.value（防御性）。"""
    # 构造一个不在 labels 中的假枚举值
    fake = type("Fake", (), {"value": "fake_value"})()
    assert failure_category_label(fake) == "fake_value"  # type: ignore[arg-type]


# ─── 枚举值契约 ───


def test_failure_category_is_str_enum():
    """FailureCategory 应为 str 枚举，value 即字符串。"""
    assert FailureCategory.SESSION_INVALID == "session_invalid"
    assert FailureCategory.FLOOD_WAIT == "flood_wait"
    assert isinstance(FailureCategory.NONE.value, str)
