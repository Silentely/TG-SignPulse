import pytest

from backend.services.sign_task_chats import clamp_chat_search_page
from backend.services.sign_task_failure import FailureCategory, classify_failure
from backend.services.sign_task_history_io import safe_history_key
from tg_signer.core.monitor import close_monitor_http_client
from tg_signer.core.signer_matchers import SignerMatchersMixin


def test_clamp_chat_search_page_types_and_bounds():
    assert clamp_chat_search_page(None, None) == (50, 0)
    assert clamp_chat_search_page("10", "5") == (10, 5)
    assert clamp_chat_search_page("invalid", "bad") == (50, 0)
    assert clamp_chat_search_page(-5, -10) == (1, 0)
    assert clamp_chat_search_page(500, 20) == (200, 20)


def test_classify_failure_network_proxy_extensions():
    cat1 = classify_failure(
        error="socket.gaierror: [Errno 8] nodename nor servname provided",

        success=False,
    )
    assert cat1 == FailureCategory.NETWORK_PROXY

    cat2 = classify_failure(
        error="httpx.RemoteProtocolError: Server disconnected",

        success=False,
    )
    assert cat2 == FailureCategory.NETWORK_PROXY


def test_safe_history_key_null_bytes_and_spaces():
    assert safe_history_key("  foo/bar\\baz  ") == "foo_bar_baz"
    assert safe_history_key("account\x00name") == "accountname"
    assert safe_history_key("   ") == "default"
    assert safe_history_key("") == "default"
    assert safe_history_key(None) == "default"  # type: ignore[arg-type]


def test_normalize_log_text_small_limit():
    mixin = SignerMatchersMixin()
    # When limit is small, safe_limit = 4, so max length won't crash with negative slicing
    res = mixin._normalize_log_text("hello world this is long text", limit=2)
    assert res.endswith("...")
    assert len(res) <= 4

    # None text
    assert mixin._normalize_log_text(None) == ""


@pytest.mark.asyncio
async def test_close_monitor_http_client():
    # Should run cleanly without error even when client is uninitialized
    await close_monitor_http_client()
