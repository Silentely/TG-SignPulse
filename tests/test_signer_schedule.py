"""signer_actions.schedule_messages 回归测试。

拆分 runtime.py 时曾把 ``from datetime import datetime`` 误写为
``import datetime``，导致 croniter ``it.next(ret_type=datetime)`` 收到模块
而非类、必抛 TypeError。本测试锁定该回归。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_signer.core import UserSigner


def _make_signer():
    signer = UserSigner.__new__(UserSigner)
    signer.user = object()  # 跳过 login
    app = MagicMock()
    app.send_message = AsyncMock()
    app.__aenter__ = AsyncMock(return_value=app)
    app.__aexit__ = AsyncMock(return_value=False)
    signer.app = app
    signer.log = MagicMock()
    signer._call_with_retry = AsyncMock()
    return signer


@pytest.mark.asyncio
async def test_schedule_messages_returns_iso_timestamps():
    """croniter ret_type=datetime 必须收到类而非模块，否则抛 TypeError。"""
    signer = _make_signer()
    # 固定 now，保证 croniter 可稳定计算下一次触发
    now = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
    signer.get_now = lambda: now

    results = await signer.schedule_messages(
        123, "hello", crontab="*/5 * * * *", next_times=2
    )

    assert len(results) == 2
    for item in results:
        assert item["text"] == "hello"
        # 返回的 at 是可解析的 ISO 时间串
        parsed = datetime.fromisoformat(item["at"])
        assert parsed.tzinfo is not None
    # 两次触发时间依次递增
    ats = [datetime.fromisoformat(r["at"]) for r in results]
    assert ats[1] > ats[0]


@pytest.mark.asyncio
async def test_schedule_messages_uses_random_seconds_offset():
    """random_seconds>0 时 at 与基准触发点相差在随机窗口内。"""
    signer = _make_signer()
    now = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
    with patch("tg_signer.core.signer_actions.get_now", return_value=now):
        results = await signer.schedule_messages(
            123, "hi", crontab="*/5 * * * *", next_times=1, random_seconds=3
        )
    at = datetime.fromisoformat(results[0]["at"])
    base = datetime(2026, 8, 4, 10, 5, tzinfo=timezone.utc)  # 下一次 */5
    assert timedelta(0) <= at - base <= timedelta(seconds=3)
