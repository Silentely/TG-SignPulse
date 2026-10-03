from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_signer.core.signer_actions import SignerActionsMixin


class DummySigner(SignerActionsMixin):
    def __init__(self):
        self.app = MagicMock()
        self.context = SimpleNamespace(
            last_callback_unconfirmed=False,
            last_callback_answer=None,
        )
        self.logs = []

    def log(self, msg, level="INFO", **kwargs):
        self.logs.append((level, msg))


@pytest.mark.asyncio
async def test_click_inline_button_delegates_to_unified_text():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data=None, text="Click Here")
    msg = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        id=200,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("Click Here")


@pytest.mark.asyncio
async def test_click_inline_button_prioritizes_text_in_unified():
    signer = DummySigner()

    # When chat or id is missing, _click_inline_button routes to click_inline_button_unified
    btn = SimpleNamespace(callback_data="cb_payload", text="Button Label")
    msg = SimpleNamespace(
        chat=None,
        id=None,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("Button Label")


@pytest.mark.asyncio
async def test_click_inline_button_fallback_to_callback_when_text_empty():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data="cb_payload", text="")
    msg = SimpleNamespace(
        chat=None,
        id=None,
        click=AsyncMock(return_value=True),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is True
    msg.click.assert_awaited_once_with("cb_payload")


@pytest.mark.asyncio
async def test_click_inline_button_failure_logs():
    signer = DummySigner()

    btn = SimpleNamespace(callback_data=None, text="Click Here")
    msg = SimpleNamespace(
        chat=SimpleNamespace(id=100),
        id=200,
        click=AsyncMock(return_value=False),
    )

    ok = await signer._click_inline_button(msg, btn)
    assert ok is False
    assert any("按钮没有可用 callback_data" in log[1] for log in signer.logs)
