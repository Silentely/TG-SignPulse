import time

from backend.services.flood_backoff import (
    FloodBackoffManager,
)


def test_flood_backoff_manager_basic():
    mgr = FloodBackoffManager()
    acc = "test_acc_1"
    assert mgr.is_cooling_down(acc) == (False, 0)

    # 记录 10 秒冷却
    info = mgr.record_flood_wait(acc, wait_seconds=10, reason="test rate limit")
    assert info.account_name == acc
    assert info.duration == 10

    cooling, rem = mgr.is_cooling_down(acc)
    assert cooling is True
    assert 8 <= rem <= 10

    all_cooling = mgr.get_all_cooling_accounts()
    assert acc in all_cooling
    assert all_cooling[acc]["duration"] == 10

    # 清除冷却
    mgr.clear_cooldown(acc)
    assert mgr.is_cooling_down(acc) == (False, 0)


def test_flood_backoff_expiration():
    mgr = FloodBackoffManager()
    acc = "test_acc_expired"
    # 手动注入一个已经过去的冷却
    mgr.record_flood_wait(acc, wait_seconds=5)
    mgr._cooldowns[acc].cooldown_until = time.time() - 1

    cooling, rem = mgr.is_cooling_down(acc)
    assert cooling is False
    assert rem == 0
    assert acc not in mgr._cooldowns
