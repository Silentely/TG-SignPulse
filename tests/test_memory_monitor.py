"""backend.utils.memory_monitor.MemoryMonitor 单元测试"""

from __future__ import annotations

import pytest

from backend.utils.memory_monitor import MemoryMonitor


def test_snapshot_and_stats():
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=10)
    snap = monitor.snapshot()
    assert snap.rss_bytes > 0
    assert snap.rss_mb > 0
    stats = monitor.get_stats()
    assert stats["snapshot_count"] == 1
    assert stats["threshold_mb"] == 10_000
    assert "current_rss_mb" in stats


def test_check_below_threshold_returns_none():
    monitor = MemoryMonitor(threshold_mb=10_000)
    assert monitor.check() is None
    assert monitor.alerts == []


def test_check_above_threshold_alerts_and_gc():
    alerts = []
    monitor = MemoryMonitor(
        threshold_mb=0.000001,  # 几乎必然超限
        gc_enabled=True,
        alert_callback=alerts.append,
        max_history=5,
    )
    alert = monitor.check()
    assert alert is not None
    assert alert.rss_mb >= alert.threshold_mb
    assert len(monitor.alerts) == 1
    assert len(alerts) == 1
    assert len(monitor.gc_records) >= 1


def test_force_gc_and_clear_history():
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=3)
    monitor.snapshot()
    record = monitor.force_gc()
    assert record.collected_objects >= 0
    assert len(monitor.gc_records) == 1
    monitor.clear_history()
    assert monitor.snapshots == []
    assert monitor.alerts == []
    assert monitor.gc_records == []


def test_invalid_max_history():
    with pytest.raises(ValueError):
        MemoryMonitor(max_history=0)


def test_alert_callback_exception_does_not_propagate():
    """告警回调抛异常时不应影响 check 主流程，应被吞掉并记录日志。"""
    def bad_callback(_alert):
        raise RuntimeError("callback boom")

    monitor = MemoryMonitor(
        threshold_mb=0.000001,
        gc_enabled=False,
        alert_callback=bad_callback,
        max_history=5,
    )
    alert = monitor.check()
    assert alert is not None
    assert len(monitor.alerts) == 1


def test_gc_disabled_skips_gc_but_still_alerts():
    """gc_enabled=False 时只告警不回收。"""
    monitor = MemoryMonitor(
        threshold_mb=0.000001,
        gc_enabled=False,
        max_history=5,
    )
    alert = monitor.check()
    assert alert is not None
    assert monitor.gc_records == []


def test_snapshots_evicted_beyond_max_history():
    """快照超过 max_history 应淘汰最旧。"""
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=2)
    s1 = monitor.snapshot()
    monitor.snapshot()
    s3 = monitor.snapshot()
    snaps = monitor.snapshots
    assert len(snaps) == 2
    assert s1 not in snaps
    assert s3 in snaps


def test_alerts_evicted_beyond_max_history():
    """告警记录超过 max_history 应淘汰最旧。"""
    monitor = MemoryMonitor(
        threshold_mb=0.000001,
        gc_enabled=False,
        max_history=2,
    )
    monitor.check()
    monitor.check()
    monitor.check()
    assert len(monitor.alerts) == 2


def test_current_rss_mb_does_not_record_history():
    """current_rss_mb 不应产生快照历史。"""
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=10)
    before = len(monitor.snapshots)
    _ = monitor.current_rss_mb
    assert len(monitor.snapshots) == before


def test_get_stats_counts():
    monitor = MemoryMonitor(threshold_mb=0.000001, gc_enabled=True, max_history=5)
    monitor.check()
    stats = monitor.get_stats()
    assert stats["snapshot_count"] >= 1
    assert stats["alert_count"] == 1
    assert stats["gc_count"] >= 1
    assert stats["gc_enabled"] is True


def test_force_gc_returns_record_even_without_alert():
    """未超阈值时 force_gc 仍应执行并返回记录。"""
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=5)
    record = monitor.force_gc()
    assert record is not None
    assert record.collected_objects >= 0
    assert len(monitor.gc_records) == 1


def test_snapshot_has_memory_fields():
    """快照字段应含 RSS/VMS/percent/available。"""
    monitor = MemoryMonitor(threshold_mb=10_000, max_history=5)
    snap = monitor.snapshot()
    assert snap.rss_bytes > 0
    assert snap.vms_bytes >= 0
    assert 0 <= snap.percent <= 100
    assert snap.available_bytes >= 0
    assert snap.rss_mb > 0
    assert snap.vms_mb >= 0
    assert snap.available_mb >= 0
