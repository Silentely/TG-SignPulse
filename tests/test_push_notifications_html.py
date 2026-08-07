"""Bot 通知 HTML 格式化回归：转义安全、标签完整、parse_mode 传递与长度保护。"""

from __future__ import annotations

import pytest

from backend.services.push_notifications import (
    _html_escape,
    _safe_msg_truncate,
    build_html_notification,
    send_keyword_push,
    send_telegram_bot_message,
)


class TestSafeMsgTruncate:
    def test_short_text_unchanged(self):
        assert _safe_msg_truncate("hi") == "hi"

    def test_long_plain_text_cut_at_limit(self):
        text = "x" * 5000
        assert len(_safe_msg_truncate(text)) == 3900

    def test_html_truncate_avoids_cutting_tag(self):
        # 构造 3900 前恰好是 <code> 开始标签的场景
        text = "<b>t</b>: <code>" + "x" * 5000 + "</code>"
        cut = _safe_msg_truncate(text, "HTML")
        assert len(cut) <= 3900
        # 不允许出现未闭合的开始标签
        assert "<code>" not in cut or cut.rfind(">") > cut.rfind("<code>")

    def test_html_truncate_keeps_balanced_tags(self):
        text = ("<b>k</b>: <code>" + "v" * 5000 + "</code>") * 3
        cut = _safe_msg_truncate(text, "HTML")
        assert len(cut) <= 3900
        assert cut.count("<b>") == cut.count("</b>")
        assert cut.count("<code>") == cut.count("</code>")


class TestHtmlEscape:
    def test_escapes_special_chars(self):
        assert _html_escape('a<b>&c"d') == "a&lt;b&gt;&amp;c\"d"

    def test_plain_text_unchanged(self):
        assert _html_escape("账号-123_测试") == "账号-123_测试"


class TestBuildHtmlNotification:
    def test_title_bold_and_fields_code(self):
        text = build_html_notification(
            title="❌ 任务失败",
            fields=[("账号", "acc1"), ("错误", "网络 <超时> & 重试")],
        )
        assert text.startswith("<b>❌ 任务失败</b>")
        assert "<b>账号</b>: <code>acc1</code>" in text
        # 用户内容被转义，避免注入 HTML
        assert "&lt;超时&gt;" in text and "&amp;" in text

    def test_empty_fields_skipped(self):
        text = build_html_notification(title="T", fields=[("空", "")])
        assert "<b>空</b>" not in text

    def test_footer_appended_and_escaped(self):
        text = build_html_notification(title="T", fields=[], footer="a<b>c")
        assert text.endswith("a&lt;b&gt;c")

    def test_long_text_truncated_by_lines(self):
        big = "x" * 5000
        text = build_html_notification(
            title="T", fields=[("大字段", big)], footer=big
        )
        # 逐行累积截断，绝不超限且标签保持闭合
        assert len(text) <= 3900
        assert text.count("<b>") == text.count("</b>")

    def test_html_tags_balanced(self):
        text = build_html_notification(
            title="标题<A>",
            fields=[("k1", "v1&v2"), ("k2", "x<y>z")],
            footer="尾部&尾部",
        )
        assert text.count("<b>") == text.count("</b>")
        assert text.count("<code>") == text.count("</code>")


class TestParseModePropagation:
    @pytest.mark.asyncio()
    async def test_send_message_passes_parse_mode(self, monkeypatch):
        sent: dict = {}

        class _FakeResp:
            def raise_for_status(self):
                return None

        async def _fake_post(self, url, json=None):
            sent.update(json or {})
            return _FakeResp()

        monkeypatch.setattr(
            "httpx.AsyncClient.post", _fake_post, raising=False
        )
        await send_telegram_bot_message(
            bot_token="tok",
            chat_id="chat",
            text="<b>hi</b>",
            parse_mode="HTML",
        )
        assert sent.get("parse_mode") == "HTML"
        assert sent.get("chat_id") == "chat"

    @pytest.mark.asyncio()
    async def test_send_message_no_parse_mode_by_default(self, monkeypatch):
        sent: dict = {}

        class _FakeResp:
            def raise_for_status(self):
                return None

        async def _fake_post(self, url, json=None):
            sent.update(json or {})
            return _FakeResp()

        monkeypatch.setattr(
            "httpx.AsyncClient.post", _fake_post, raising=False
        )
        await send_telegram_bot_message(
            bot_token="tok", chat_id="chat", text="plain"
        )
        assert "parse_mode" not in sent

    @pytest.mark.asyncio()
    async def test_keyword_push_uses_html_for_telegram(self, monkeypatch):
        sent: dict = {}

        class _FakeResp:
            def raise_for_status(self):
                return None

        async def _fake_post(self, url, json=None):
            sent.update(json or {})
            return _FakeResp()

        monkeypatch.setattr(
            "httpx.AsyncClient.post", _fake_post, raising=False
        )
        await send_keyword_push(
            {
                "keyword_monitor_push_channel": "telegram",
                "telegram_bot_token": "tok",
                "telegram_bot_chat_id": "chat",
            },
            {"title": "命中", "body": "body<tag>", "keyword": "k", "account_name": "a"},
        )
        assert sent.get("parse_mode") == "HTML"
        assert "🔔" in sent.get("text", "")
        # body 内的 <tag> 被转义，避免破坏 HTML
        assert "&lt;tag&gt;" in sent.get("text", "")
