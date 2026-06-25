"""内存监控工具

提供进程内存使用监控、阈值告警和自动垃圾回收能力。
适用于长期运行的后端服务，防止内存泄漏导致 OOM。
"""

from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import psutil

logger = logging.getLogger("backend.memory_monitor")


@dataclass
class MemorySnapshot:
    """某一时刻的内存快照"""

    timestamp: float
    rss_bytes: int
    vms_bytes: int
    percent: float
    available_bytes: int

    @property
    def rss_mb(self) -> float:
        """RSS 内存（MB）"""
        return self.rss_bytes / (1024 * 1024)

    @property
    def vms_mb(self) -> float:
        """虚拟内存（MB）"""
        return self.vms_bytes / (1024 * 1024)

    @property
    def available_mb(self) -> float:
        """系统可用内存（MB）"""
        return self.available_bytes / (1024 * 1024)


@dataclass
class AlertRecord:
    """告警记录"""

    timestamp: float
    rss_mb: float
    threshold_mb: float
    message: str


@dataclass
class GCRecord:
    """垃圾回收记录"""

    timestamp: float
    rss_before_mb: float
    rss_after_mb: float
    freed_mb: float
    collected_objects: int


@dataclass
class MemoryMonitor:
    """内存监控器

    提供以下核心能力：
    - 周期性采集内存快照
    - 基于 RSS 阈值触发告警回调
    - 阈值超限时自动触发垃圾回收
    - 记录告警和 GC 历史

    参数:
        threshold_mb: 告警阈值（MB），超过此值触发告警和自动 GC
        gc_enabled: 是否启用自动垃圾回收
        alert_callback: 告警回调函数，接收 AlertRecord 参数
        max_history: 最大历史记录条数
        check_interval: 检查间隔秒数，用于 start/stop 自动监控
    """

    threshold_mb: float = 512.0
    gc_enabled: bool = True
    alert_callback: Optional[Callable[[AlertRecord], Any]] = None
    max_history: int = 100
    check_interval: float = 30.0

    # 内部状态
    _process: Optional[psutil.Process] = field(
        default=None, init=False, repr=False
    )
    _snapshots: List[MemorySnapshot] = field(
        default_factory=list, init=False, repr=False
    )
    _alerts: List[AlertRecord] = field(
        default_factory=list, init=False, repr=False
    )
    _gc_records: List[GCRecord] = field(
        default_factory=list, init=False, repr=False
    )
    _last_gc_forced: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """初始化 psutil 进程句柄"""
        self._process = psutil.Process()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def snapshot(self) -> MemorySnapshot:
        """采集当前进程内存快照

        返回:
            包含 RSS、VMS、内存占比和系统可用内存的快照对象
        """
        mem = self._process.memory_info()
        system = psutil.virtual_memory()
        snap = MemorySnapshot(
            timestamp=time.time(),
            rss_bytes=mem.rss,
            vms_bytes=mem.vms,
            percent=system.percent,
            available_bytes=system.available,
        )
        self._append_snapshot(snap)
        return snap

    def check(self) -> Optional[AlertRecord]:
        """执行一次内存检查：采集快照、判断阈值、按需触发 GC

        返回:
            如果超过阈值则返回告警记录，否则返回 None
        """
        snap = self.snapshot()
        if snap.rss_mb >= self.threshold_mb:
            alert = self._trigger_alert(snap)
            if self.gc_enabled:
                self._do_gc(snap)
            return alert
        return None

    def force_gc(self) -> GCRecord:
        """手动强制执行垃圾回收

        不经过阈值判断，直接执行 GC 并返回回收记录。
        """
        snap_before = self.snapshot()
        return self._do_gc(snap_before)

    @property
    def current_rss_mb(self) -> float:
        """当前 RSS 内存（MB），不产生历史记录"""
        return self._process.memory_info().rss / (1024 * 1024)

    @property
    def snapshots(self) -> List[MemorySnapshot]:
        """历史内存快照列表（只读副本）"""
        return list(self._snapshots)

    @property
    def alerts(self) -> List[AlertRecord]:
        """历史告警记录列表（只读副本）"""
        return list(self._alerts)

    @property
    def gc_records(self) -> List[GCRecord]:
        """历史 GC 记录列表（只读副本）"""
        return list(self._gc_records)

    def clear_history(self) -> None:
        """清空所有历史记录"""
        self._snapshots.clear()
        self._alerts.clear()
        self._gc_records.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计摘要

        返回:
            包含当前内存、阈值、历史快照数、告警数、GC 数等信息的字典
        """
        return {
            "current_rss_mb": round(self.current_rss_mb, 2),
            "threshold_mb": self.threshold_mb,
            "gc_enabled": self.gc_enabled,
            "snapshot_count": len(self._snapshots),
            "alert_count": len(self._alerts),
            "gc_count": len(self._gc_records),
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _append_snapshot(self, snap: MemorySnapshot) -> None:
        """追加快照，超出容量时淘汰最旧记录"""
        self._snapshots.append(snap)
        if len(self._snapshots) > self.max_history:
            self._snapshots = self._snapshots[-self.max_history :]

    def _trigger_alert(self, snap: MemorySnapshot) -> AlertRecord:
        """生成告警记录并调用回调"""
        alert = AlertRecord(
            timestamp=snap.timestamp,
            rss_mb=round(snap.rss_mb, 2),
            threshold_mb=self.threshold_mb,
            message=(
                f"内存使用 {snap.rss_mb:.1f} MB 超过阈值 "
                f"{self.threshold_mb:.1f} MB"
            ),
        )
        self._alerts.append(alert)
        if len(self._alerts) > self.max_history:
            self._alerts = self._alerts[-self.max_history :]

        logger.warning(alert.message)

        if self.alert_callback is not None:
            try:
                self.alert_callback(alert)
            except Exception:
                logger.exception("告警回调执行失败")

        return alert

    def _do_gc(self, snap_before: MemorySnapshot) -> GCRecord:
        """执行垃圾回收并记录结果"""
        rss_before_mb = snap_before.rss_mb
        collected = gc.collect()
        # GC 完成后重新采样
        rss_after_bytes = self._process.memory_info().rss
        rss_after_mb = rss_after_bytes / (1024 * 1024)
        freed_mb = rss_before_mb - rss_after_mb

        record = GCRecord(
            timestamp=time.time(),
            rss_before_mb=round(rss_before_mb, 2),
            rss_after_mb=round(rss_after_mb, 2),
            freed_mb=round(freed_mb, 2),
            collected_objects=collected,
        )
        self._gc_records.append(record)
        if len(self._gc_records) > self.max_history:
            self._gc_records = self._gc_records[-self.max_history :]

        if freed_mb > 0:
            logger.info(
                "GC 完成：回收 %d 个对象，释放 %.2f MB（%.1f -> %.1f MB）",
                collected,
                freed_mb,
                rss_before_mb,
                rss_after_mb,
            )
        else:
            logger.debug(
                "GC 完成：回收 %d 个对象，内存未显著下降（%.1f MB）",
                collected,
                rss_after_mb,
            )

        return record
