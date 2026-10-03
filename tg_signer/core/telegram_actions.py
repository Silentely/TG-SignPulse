from __future__ import annotations

import logging
from typing import Any, Callable

from tg_signer.compat import errors
from tg_signer.core.client import _is_callback_data_invalid

logger = logging.getLogger(__name__)


def _log(
    log_func: Callable[..., Any] | None,
    msg: str,
    level: str = "INFO",
) -> None:
    if not log_func:
        return
    try:
        log_func(msg, level=level)
    except TypeError:
        try:
            log_func(msg, level)
        except TypeError:
            try:
                log_func(msg)
            except Exception:
                pass
    except Exception:
        pass


async def click_inline_button_unified(
    message: Any,
    button: Any,
    log_func: Callable[..., Any] | None = None,
) -> bool:
    """Click an inline button on a message in a unified, safe manner.

    Prioritizes button callback_data (str or bytes), falling back to button text.
    Guards against missing attributes without raising AttributeError or TypeError.
    Catches Pyrogram RPC exceptions and unexpected errors, returning False.
    """
    if message is None or button is None:
        return False

    click = getattr(message, "click", None)
    if not callable(click):
        return False

    callback_data = getattr(button, "callback_data", None)
    target = callback_data if callback_data is not None else getattr(button, "text", None)

    if target is None:
        return False

    try:
        res = await click(target)
        _log(log_func, "点击完成", level="INFO")
        return False if res is False else True
    except (AttributeError, TypeError):
        return False
    except (errors.RPCError, Exception) as exc:
        if _is_callback_data_invalid(exc):
            _log(
                log_func,
                "Message.click 也无法确认按钮回调，继续等待机器人后续消息确认",
                level="WARNING",
            )
        else:
            _log(
                log_func,
                f"Message.click 无法确认按钮回调: {exc}",
                level="WARNING",
            )
        return False
