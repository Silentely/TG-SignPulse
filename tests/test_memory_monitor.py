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
