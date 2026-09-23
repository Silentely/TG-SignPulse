"""Telegram FloodWait 智能退避与限频保护管理器。

当 Telegram API 返回 FloodWait(seconds) 时，记录账号进入冷却保护期，
防止其它并发或排队任务继续撞频导致封号或惩罚延长。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple

logger = logging.getLogger("backend.flood_backoff")


@dataclass
class FloodCooldownInfo:
    account_name: str
    cooldown_until: float
    duration: int
    reason: str
    created_at: float


class FloodBackoffManager:
    """进程内单例退避管理器。"""

    def __init__(self) -> None:
        self._cooldowns: Dict[str, FloodCooldownInfo] = {}

    def record_flood_wait(
        self,
        account_name: str,
        wait_seconds: int,
        reason: str = "Telegram API FloodWait",
    ) -> FloodCooldownInfo:
        """记录指定账号触发 FloodWait 冷却。"""
        now = time.time()
        # 兜底最小冷却 5 秒，最大限制 86400 秒 (24h)
        duration = max(5, min(int(wait_seconds), 86400))
        until = now + duration
        info = FloodCooldownInfo(
            account_name=account_name,
            cooldown_until=until,
            duration=duration,
            reason=reason,
            created_at=now,
        )
        self._cooldowns[account_name] = info
        logger.warning(
            "账号 [%s] 触发限频退避保护，冷却 %d 秒 (直至 %d): %s",
            account_name,
            duration,
            int(until),
            reason,
        )
        return info

    def is_cooling_down(self, account_name: str) -> Tuple[bool, int]:
        """检查指定账号是否正处于限频冷却保护中。

        返回 (is_cooling, remaining_seconds)。
        """
        now = time.time()
        info = self._cooldowns.get(account_name)
        if not info:
            return False, 0
        remaining = int(info.cooldown_until - now)
        if remaining > 0:
            return True, remaining
        # 已经过期，自动清除
        self._cooldowns.pop(account_name, None)
        return False, 0

    def clear_cooldown(self, account_name: str) -> None:
        """手动清除指定账号的冷却状态。"""
        self._cooldowns.pop(account_name, None)

    def get_all_cooling_accounts(self) -> Dict[str, Dict[str, Any]]:
        """获取所有当前正在冷却中的账号及其状态。"""
        now = time.time()
        active: Dict[str, Dict[str, Any]] = {}
        expired_keys = []
        for name, info in self._cooldowns.items():
            rem = int(info.cooldown_until - now)
            if rem > 0:
                active[name] = {
                    "account_name": name,
                    "remaining_seconds": rem,
                    "duration": info.duration,
                    "reason": info.reason,
                    "cooldown_until": info.cooldown_until,
                }
            else:
                expired_keys.append(name)
        for k in expired_keys:
            self._cooldowns.pop(k, None)
        return active


# 全局单例
_default_manager = FloodBackoffManager()


def get_flood_backoff_manager() -> FloodBackoffManager:
    return _default_manager
