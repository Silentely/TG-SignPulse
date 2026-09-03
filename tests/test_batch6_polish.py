from unittest.mock import MagicMock

import pytest

from backend.core.rate_limit import compose_rate_limit_key
from backend.services.keyword_monitor.hits import _csv_cell, list_keyword_hits
from backend.services.telegram.sessions import _release_login_session
from tg_signer.core.signer_matchers import SignerMatchersMixin
from tg_signer.security import is_masked_secret


def test_keyword_hits_csv_cell_and_query_guards():
    # Formula injection guard
    assert _csv_cell("=1+1") == "'=1+1"
    assert _csv_cell("+100") == "+100"  # pure number prefix preserved
    assert _csv_cell("+100abc") == "'+100abc"
    assert _csv_cell(123) == "123"
    assert _csv_cell(None) == ""

    # list_keyword_hits type safety
    res = list_keyword_hits(limit="invalid", offset="invalid", max_limit="invalid")  # type: ignore[arg-type]
    assert res["limit"] > 0
    assert res["offset"] == 0


def test_is_masked_secret_whitespace():
    assert is_masked_secret("********") is True
    assert is_masked_secret("  ********  ") is True
    assert is_masked_secret("other") is False
    assert is_masked_secret(None) is False


def test_compose_rate_limit_key_guards():
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    key = compose_rate_limit_key(req, "  ADMIN  ", None, "   ", 123)  # type: ignore[arg-type]
    assert key == "127.0.0.1|admin|123"


def test_signer_matchers_describe_action_none():
    mixin = SignerMatchersMixin()
    assert mixin._describe_action(None) == "未知动作"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_release_login_session_non_dict():
    # Shouldn't raise any exception when receiving non-dict
    await _release_login_session(None)
    await _release_login_session("string")
