import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 14),
    reason="pyrogram is not importable on Python 3.14 in the local test env",
)


class DummyClient:
    def __init__(self, name, *args, **kwargs):
        self.name = name
        self.workdir = Path(kwargs["workdir"])
        self.key = kwargs["key"]
        self.is_connected = False
        self._tg_signpulse_no_updates = kwargs.get("no_updates")


def test_get_client_rebuilds_disconnected_cache_when_no_updates_changes(
    monkeypatch, tmp_path
):
    from tg_signer import core

    monkeypatch.setattr(core, "Client", DummyClient)
    core._CLIENT_INSTANCES.clear()
    core._CLIENT_REFS.clear()
    core._CLIENT_ASYNC_LOCKS.clear()

    first = core.get_client("account", workdir=tmp_path, no_updates=True)
    second = core.get_client("account", workdir=tmp_path, no_updates=False)

    assert second is not first
    assert second._tg_signpulse_no_updates is False


def test_get_client_keeps_connected_cache_when_no_updates_changes(monkeypatch, tmp_path):
    from tg_signer import core

    monkeypatch.setattr(core, "Client", DummyClient)
    core._CLIENT_INSTANCES.clear()
    core._CLIENT_REFS.clear()
    core._CLIENT_ASYNC_LOCKS.clear()

    first = core.get_client("account", workdir=tmp_path, no_updates=True)
    first.is_connected = True
    second = core.get_client("account", workdir=tmp_path, no_updates=False)

    assert second is first
