"""关键词正则灾难性回溯（ReDoS）防护测试。

覆盖三层防线：
1. 静态判据 is_unsafe_keyword_regex 的正反用例
2. 匹配文本截断到 4096 字符后不再冻结
3. regex_match_deadline 到点返回空而非挂起
4. 写入侧（CRUD / 导入 / pydantic 模型）与运行期判据一致
"""
from __future__ import annotations

import time

import pytest

from backend.services.keyword_monitor.rules import (
    _MAX_MATCH_TEXT_CHARS,
    _match_all_keyword_values,
    _RegexDeadlineExceeded,
    is_unsafe_keyword_regex,
    regex_match_deadline,
)


class TestStaticCriterion:
    """静态判据必须拒绝实测会指数回溯的模式，并放行常见常规模式。"""

    # 实测在 41 字符失败输入下 >0.25s 仍未完成的灾难性模式
    CATASTROPHIC = [
        r"^(\w+\s?)*$",
        r"^(a+)+$",
        r"^(a|a)*$",
        r"^(\s*)*$",
        r"^(?:[a-z]+)+$",
        r"^(a{1,3})+$",
        r"^(x+x+)+y$",
        r"^(\s*\w+)+$",
    ]

    # 常见且实测 <0.2ms 的常规模式（含 IP、日期、邮箱、URL 等真实场景）
    REGULAR = [
        r"^\d{4}-\d{2}-\d{2}$",
        r"(?i)hello",
        r"^\w+@\w+\.\w+$",
        r"https?://\S+",
        r"^(\d{1,3}\.){3}\d{1,3}$",
        r"^\d{1,3}(,\d{3})*$",
        r"\b(?:foo|bar)\b",
        r"^[\w.+-]+$",
        r"^(\d\d\d,)*$",
    ]

    @pytest.mark.parametrize("pattern", CATASTROPHIC)
    def test_catastrophic_patterns_are_rejected(self, pattern):
        assert is_unsafe_keyword_regex(pattern) is True

    @pytest.mark.parametrize("pattern", REGULAR)
    def test_regular_patterns_are_allowed(self, pattern):
        assert is_unsafe_keyword_regex(pattern) is False

    @pytest.mark.parametrize(
        "pattern",
        ["", None, 123, r"^\d+$", r"["],
    )
    def test_non_risky_or_invalid_inputs_are_not_flagged(self, pattern):
        """空值/非字符串/非法正则不应被判为高风险（语法问题由编译路径处理）。"""
        assert is_unsafe_keyword_regex(pattern) is False


class TestMatchTruncation:
    def test_unsafe_regex_no_longer_freezes_on_long_text(self):
        """静态判据放行的模式在超长文本下也应被截断保护。"""
        action = {"match_mode": "regex", "keywords": [r"^(\d\d\d,)*$"]}
        started = time.monotonic()
        results = _match_all_keyword_values(action, "12," * 4000)
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"匹配耗时 {elapsed:.2f}s，疑似未被截断保护"
        assert results == []

    def test_haystack_is_truncated_to_max_chars(self):
        """超过上限的文本被截断，命中判定只在前 _MAX_MATCH_TEXT_CHARS 内进行。"""
        action = {"match_mode": "contains", "keywords": ["needle"]}
        text = "x" * (_MAX_MATCH_TEXT_CHARS + 100) + "needle"
        assert _match_all_keyword_values(action, text) == []

        text_head = "needle" + "x" * (_MAX_MATCH_TEXT_CHARS + 100)
        assert _match_all_keyword_values(action, text_head) == ["needle"]

    def test_safe_regex_still_matches_after_truncation(self):
        action = {"match_mode": "regex", "keywords": [r"\d{4}-\d{2}-\d{2}"]}
        text = "a" * 100 + "2026-09-28" + "b" * 5000
        assert _match_all_keyword_values(action, text) == ["2026-09-28"]

    def test_invalid_regex_returns_empty_and_does_not_raise(self):
        action = {"match_mode": "regex", "keywords": [r"^(unclosed"]}
        assert _match_all_keyword_values(action, "anything") == []


class TestRegexDeadline:
    def test_deadline_interrupts_catastrophic_backtracking(self):
        """SIGALRM 能中断灾难性回溯：到点抛 _RegexDeadlineExceeded 而非挂起。"""
        import re

        pattern = r"^(\w+\s?)*$"
        text = "a" * 40 + "!"
        started = time.monotonic()
        with pytest.raises(_RegexDeadlineExceeded):
            with regex_match_deadline(seconds=0.3):
                list(re.finditer(pattern, text))
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"deadline 未生效，耗时 {elapsed:.2f}s"

    def test_deadline_restores_previous_alarm_handler(self):
        import signal

        def _noop(signum, frame):
            pass

        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _noop)
        try:
            with regex_match_deadline(seconds=5.0):
                pass
            assert signal.getsignal(signal.SIGALRM) is _noop
            # itimer 必须被清零，避免泄漏到后续代码（返回 (delay, interval) 二元组）
            remaining = signal.setitimer(signal.ITIMER_REAL, 0)
            assert remaining[0] == 0.0
        finally:
            signal.signal(signal.SIGALRM, previous)

    def test_deadline_is_noop_off_main_thread(self):
        """非主线程无法安装 setitimer，应降级为不中断且不抛错。"""
        import threading

        errors: list[BaseException] = []

        def worker():
            try:
                with regex_match_deadline(seconds=0.2):
                    time.sleep(0.05)
            except BaseException as exc:  # pragma: no cover - 仅失败时记录
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert errors == []

    def test_matcher_swallows_deadline_and_returns_empty(self):
        """匹配路径捕获 deadline 异常，按未命中处理而不是向上抛。"""
        import contextlib

        import backend.services.keyword_monitor.rules as rules_mod

        @contextlib.contextmanager
        def _always_timeout(*args, **kwargs):
            raise _RegexDeadlineExceeded
            yield  # pragma: no cover - 不可达

        original = rules_mod.regex_match_deadline
        rules_mod.regex_match_deadline = _always_timeout
        try:
            action = {"match_mode": "regex", "keywords": [r"anything"]}
            assert _match_all_keyword_values(action, "text") == []
        finally:
            rules_mod.regex_match_deadline = original


class TestUnsafeActionDetection:
    def test_non_regex_mode_is_never_unsafe(self):
        from backend.services.keyword_monitor.rules import (
            _action_has_unsafe_keyword_regex,
        )

        assert _action_has_unsafe_keyword_regex(
            {"match_mode": "contains", "keywords": [r"^(\w+\s?)*$"]}
        ) is False

    def test_regex_mode_detects_unsafe_keyword(self):
        from backend.services.keyword_monitor.rules import (
            _action_has_unsafe_keyword_regex,
        )

        assert _action_has_unsafe_keyword_regex(
            {"match_mode": "regex", "keywords": [r"^\d+$", r"^(a+)+$"]}
        ) is True

    def test_validate_action_raises_with_readable_message(self):
        from backend.services.keyword_monitor.rules import (
            validate_action_regex_safety,
        )

        with pytest.raises(ValueError, match="灾难性回溯"):
            validate_action_regex_safety(
                {"match_mode": "regex", "keywords": [r"^(\w+\s?)*$"]}
            )

    def test_validate_action_allows_safe_regex(self):
        from backend.services.keyword_monitor.rules import (
            validate_action_regex_safety,
        )

        validate_action_regex_safety(
            {"match_mode": "regex", "keywords": [r"^\d{4}-\d{2}-\d{2}$"]}
        )


class TestModelLevelGate:
    def test_keyword_notify_action_rejects_unsafe_regex(self):
        from pydantic import ValidationError

        from tg_signer.config import KeywordNotifyAction

        with pytest.raises(ValidationError, match="灾难性回溯"):
            KeywordNotifyAction(
                action=8,
                keywords=[r"^(\w+\s?)*$"],
                match_mode="regex",
            )

    def test_keyword_notify_action_allows_safe_regex(self):
        from tg_signer.config import KeywordNotifyAction

        action = KeywordNotifyAction(
            action=8,
            keywords=[r"^\d{4}-\d{2}-\d{2}$"],
            match_mode="regex",
        )
        assert action.match_mode == "regex"

    def test_keyword_notify_action_ignores_non_regex_mode(self):
        from tg_signer.config import KeywordNotifyAction

        action = KeywordNotifyAction(
            action=8,
            keywords=[r"^(\w+\s?)*$"],
            match_mode="contains",
        )
        assert action.match_mode == "contains"
