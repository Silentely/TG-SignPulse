"""
配置管理服务
提供任务配置的导入导出功能

领域实现按配置主题拆分在 config_mixins.py：签到任务/导出导入、AI 配置、
全局设置、Telegram 凭据；本文件保留共享基础（JSON 读写、路径解析、单例）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from backend.core.config import get_settings
from backend.services.config_mixins import (
    AIConfigMixin,
    ConfigExportMixin,
    GlobalSettingsMixin,
    SignTaskConfigMixin,
    TelegramConfigMixin,
)
from backend.utils.atomic_io import read_json_safe, write_json_atomic


class ConfigService(
    SignTaskConfigMixin,
    ConfigExportMixin,
    AIConfigMixin,
    GlobalSettingsMixin,
    TelegramConfigMixin,
):
    """配置管理服务类"""

    def _read_json_file(self, path: Path, default: Any = None) -> Any:
        """带进程内锁读取 JSON，避免同进程并发读写交错。"""
        return read_json_safe(path, default)

    def _write_json_file(self, path: Path, data: Any) -> bool:
        """原子写入 JSON，避免异常中断时留下半截配置文件。"""
        try:
            write_json_atomic(path, data)
            return True
        except (OSError, TypeError, ValueError) as exc:
            logging.getLogger("backend.config").exception(
                "Failed to write JSON file: %s (%s)", path, exc
            )
            return False

    def __init__(self):
        # 路径一律经 _ensure_paths / 属性解析，避免单例绑定过期 workdir
        self._workdir: Optional[Path] = None
        self._signs_dir: Optional[Path] = None
        self._monitors_dir: Optional[Path] = None
        self._ensure_paths()

    def _ensure_paths(self) -> None:
        env_data = (os.environ.get("APP_DATA_DIR") or "").strip()
        cached = get_settings()
        if env_data and str(cached.data_dir) != env_data:
            get_settings.cache_clear()
        workdir = get_settings().resolve_workdir()
        if self._workdir != workdir:
            self._workdir = workdir
            self._signs_dir = workdir / "signs"
            self._monitors_dir = workdir / "monitors"
            self._signs_dir.mkdir(parents=True, exist_ok=True)
            self._monitors_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workdir(self) -> Path:
        self._ensure_paths()
        assert self._workdir is not None
        return self._workdir

    @property
    def signs_dir(self) -> Path:
        self._ensure_paths()
        assert self._signs_dir is not None
        return self._signs_dir

    @property
    def monitors_dir(self) -> Path:
        self._ensure_paths()
        assert self._monitors_dir is not None
        return self._monitors_dir


# 创建全局实例
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    else:
        # 环境数据目录变更时重建，避免单例绑定旧 workdir
        _config_service._ensure_paths()
    return _config_service
