"""Bot 通知 HTML 格式化回归：转义安全、标签完整、parse_mode 传递与长度保护。"""

from __future__ import annotations

import httpx
import pytest

from backend.services.push_notifications import (
    _html_escape,
    _safe_msg_truncate,
    build_html_notification,
    send_auto_backup_failure_notification,
    send_keyword_push,
    send_login_notification,
    send_task_success_notification,
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

    def test_over_limit_appends_truncation_marker(self):
        """逐行丢弃时必须留下截断标记，避免残缺内容被误当完整内容。"""
        big = "x" * 3000
        text = build_html_notification(
            title="T", fields=[("大字段1", big), ("大字段2", big)], footer=big
        )
        assert len(text) <= 3900
        assert text.endswith("详情见面板日志）")
        assert text.count("<code>") == text.count("</code>")

    def test_single_oversized_line_falls_back_to_marker_only(self):
        """单行即占满预算（超长标题）时退回纯标记，且不空转。"""
        text = build_html_notification(title="T" * 5000, fields=[("k", "v")])
        assert len(text) <= 3900
        assert "已截断" in text

    def test_within_limit_has_no_marker(self):
        text = build_html_notification(title="T", fields=[("k", "v")], footer="f")
        assert "已截断" not in text


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
    async def test_transient_network_failure_retries_once(self, monkeypatch):
        calls = {"n": 0}

        class _FakeResp:
            def raise_for_status(self):
                return None

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise httpx.ConnectError("connection reset")
                return _FakeResp()

        async def _noop_sleep(_seconds):
            return None

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient, raising=False)
        # 缩短重试等待，避免测试挂 1 秒
        monkeypatch.setattr("asyncio.sleep", _noop_sleep, raising=False)

        await send_telegram_bot_message(bot_token="tok", chat_id="chat", text="hi")
        assert calls["n"] == 2

    @pytest.mark.asyncio()
    async def test_4xx_error_not_retried(self, monkeypatch):
        calls = {"n": 0}

        class _FakeResp:
            def __init__(self, status_code):
                self.status_code = status_code

            def raise_for_status(self):
                raise httpx.HTTPStatusError(
                    "400 Bad Request", request=None, response=self
                )

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, **kwargs):
                calls["n"] += 1
                return _FakeResp(400)

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient, raising=False)
        with pytest.raises(httpx.HTTPStatusError):
            await send_telegram_bot_message(bot_token="tok", chat_id="chat", text="hi")
        assert calls["n"] == 1


class TestNotificationTimeLabels:
    @staticmethod
    def _settings(**overrides):
        settings = {
            "telegram_bot_notify_enabled": True,
            "telegram_bot_login_notify_enabled": True,
            "telegram_bot_task_success_enabled": True,
            "telegram_bot_quiet_hours_enabled": False,
            "telegram_bot_token": "tok",
            "telegram_bot_chat_id": "chat",
        }
        settings.update(overrides)
        return settings

    @pytest.mark.asyncio()
    async def test_login_notification_marks_time_as_utc(self, monkeypatch):
        sent = {}

        async def _fake_send(**kwargs):
            sent.update(kwargs)

        monkeypatch.setattr(
            "backend.services.push_notifications.send_telegram_bot_message",
            _fake_send,
        )
        await send_login_notification(
            self._settings(), username="admin", ip_address="127.0.0.1"
        )

        assert "<b>时间 (UTC)</b>" in sent["text"]

    @pytest.mark.asyncio()
    async def test_success_notification_marks_time_as_utc(self, monkeypatch):
        sent = {}

        async def _fake_send(**kwargs):
            sent.update(kwargs)

        monkeypatch.setattr(
            "backend.services.push_notifications.send_telegram_bot_message",
            _fake_send,
        )
        await send_task_success_notification(
            self._settings(), account_name="acc1", task_name="daily"
        )

        assert "<b>时间 (UTC)</b>" in sent["text"]

    @pytest.mark.asyncio()
    async def test_backup_failure_notification_marks_time_as_utc(self, monkeypatch):
        sent = {}

        async def _fake_send(**kwargs):
            sent.update(kwargs)

        monkeypatch.setattr(
            "backend.services.push_notifications.send_telegram_bot_message",
            _fake_send,
        )
        await send_auto_backup_failure_notification(
            self._settings(), error="WebDAV 上传失败"
        )

        assert "<b>时间 (UTC)</b>" in sent["text"]

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


class TestServerChanScSend:
    """Server酱 sc_send：HTTP 状态检查与非 JSON 响应兜底。"""

    @pytest.mark.asyncio()
    async def test_sc_send_raises_on_http_error(self, monkeypatch):
        class _FakeResp:
            status_code = 500

            def raise_for_status(self):
                raise httpx.HTTPStatusError(
                    "500 Server Error", request=None, response=self
                )

        async def _fake_post(self, url, json=None):
            return _FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post, raising=False)
        from tg_signer.notification.server_chan import sc_send

        with pytest.raises(httpx.HTTPStatusError):
            await sc_send("key-123", "标题", "内容")

    @pytest.mark.asyncio()
    async def test_sc_send_non_json_response_returns_raw(self, monkeypatch):
        class _FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("not json")

            @property
            def text(self):
                return "<html>gateway error</html>"

        async def _fake_post(self, url, json=None):
            return _FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post, raising=False)
        from tg_signer.notification.server_chan import sc_send

        result = await sc_send("key-123", "标题")
        assert result.get("raw") == "<html>gateway error</html>"


class TestHttpPostRetryOnce:
    """HTTP 推送统一重试：瞬时故障重试一次，4xx 不重试直接抛。"""

    @staticmethod
    async def _noop_sleep(_seconds):
        return None

    @pytest.mark.asyncio()
    async def test_transient_failure_retries_once(self, monkeypatch):
        calls = {"n": 0}

        class _FakeResp:
            def raise_for_status(self):
                return None

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, json=None, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise httpx.ConnectError("boom", request=None)
                return _FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient, raising=False)
        monkeypatch.setattr("asyncio.sleep", self._noop_sleep, raising=False)

        from backend.services.push_notifications import _http_post_retry_once

        await _http_post_retry_once(url="https://x", channel="Bark", json_body={})
        assert calls["n"] == 2

    @pytest.mark.asyncio()
    async def test_4xx_not_retried(self, monkeypatch):
        calls = {"n": 0}

        class _FakeResp:
            status_code = 400

            def raise_for_status(self):
                raise httpx.HTTPStatusError(
                    "400 Bad Request", request=None, response=self
                )

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, json=None, **kwargs):
                calls["n"] += 1
                return _FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient, raising=False)
        monkeypatch.setattr("asyncio.sleep", self._noop_sleep, raising=False)

        from backend.services.push_notifications import _http_post_retry_once

        with pytest.raises(httpx.HTTPStatusError):
            await _http_post_retry_once(url="https://x", channel="自定义推送", json_body={})
        assert calls["n"] == 1

    @pytest.mark.asyncio()
    async def test_get_method_uses_get(self, monkeypatch):
        methods = []

        class _FakeResp:
            def raise_for_status(self):
                return None

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url, **kwargs):
                methods.append("GET")
                return _FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient, raising=False)

        from backend.services.push_notifications import _http_post_retry_once

        await _http_post_retry_once(url="https://x", channel="自定义推送", method="GET")
        assert methods == ["GET"]
