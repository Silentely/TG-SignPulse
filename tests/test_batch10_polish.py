import pytest

from backend.services.sign_task_chats import search_chats_in_cache
from backend.services.telegram.devices import TelegramDevicesMixin


def test_search_chats_in_cache_numeric_fallback():
    chats = [
        {"id": 123456, "title": "Tech Group", "username": "tech_grp"},
        {"id": 999999, "title": "Room 123", "username": "room"},
    ]
    res = search_chats_in_cache(chats, "123")
    assert res["total"] == 2
    assert len(res["items"]) == 2


@pytest.mark.asyncio
async def test_devices_terminate_invalid_hash():
    class DummyService(TelegramDevicesMixin):
        def _normalize_account_name(self, name):
            return name

        def account_exists(self, name):
            return True

    svc = DummyService()
    with pytest.raises(ValueError, match="无效的授权 hash"):
        await svc.terminate_account_device("acc", "not_a_number")
