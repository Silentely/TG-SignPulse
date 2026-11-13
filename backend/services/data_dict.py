from __future__ import annotations

import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from backend.core.config import get_settings
from backend.services.data_dict_presets import BUILTIN_DATA_DICT_MAP, BUILTIN_DATA_DICTS
from backend.utils.atomic_io import read_json_safe, write_json_atomic

logger = logging.getLogger("backend.data_dict")

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_STATS_FILE = "_stats.json"
_STATS_FLUSH_INTERVAL_SECONDS = 5.0
_instance: Optional[DataDictService] = None
_instance_lock = threading.Lock()


class DataDictService:
    """自动化素材数据字典池服务。

    管理动态素材字典的持久化、校验、随机及轮询 (Round-Robin) 取词。
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = (
            Path(base_dir) if base_dir else get_settings().resolve_base_dir()
        )
        self.dict_dir = self.base_dir / "data_dicts"
        self.dict_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._stats_dirty = False
        self._stats_last_flush = 0.0
        self._load_stats()

    def _dict_file(self, name: str) -> Path:
        if not name or not _NAME_PATTERN.match(name):
            raise ValueError("INVALID_DICT_NAME")
        return self.dict_dir / f"{name}.json"

    def list_dicts(self) -> List[Dict[str, Any]]:
        """列出所有字典元信息（名称、条目数、备注、更新时间）。"""
        results: List[Dict[str, Any]] = []
        with self._lock:
            for path in sorted(self.dict_dir.glob("*.json")):
                if not path.is_file() or path.name == _STATS_FILE:
                    continue
                data = read_json_safe(path)
                if not isinstance(data, dict):
                    continue
                name = path.stem
                entries = data.get("entries") or []
                results.append(
                    {
                        "name": name,
                        "count": len(entries),
                        "remark": str(data.get("remark") or ""),
                        "updated_at": str(data.get("updated_at") or ""),
                    }
                )
        return results

    def list_builtin_dicts(self) -> List[Dict[str, Any]]:
        """列出内置字典预设及是否已被用户引用。"""
        results: List[Dict[str, Any]] = []
        with self._lock:
            for preset in BUILTIN_DATA_DICTS:
                results.append(
                    {
                        "name": preset.name,
                        "count": len(preset.entries),
                        "remark": preset.remark,
                        "entries": list(preset.entries),
                        "exists": self._dict_file(preset.name).exists(),
                    }
                )
        return results

    def create_from_builtin(self, name: str) -> Dict[str, Any]:
        """将内置字典引用为用户字典；同名已存在时拒绝覆盖。"""
        preset = BUILTIN_DATA_DICT_MAP.get(name)
        if preset is None:
            raise ValueError("BUILTIN_DICT_NOT_FOUND")

        file_path = self._dict_file(name)
        with self._lock:
            if file_path.exists():
                raise ValueError("DATA_DICT_EXISTS")
            self.save_dict(preset.name, list(preset.entries), remark=preset.remark)
            logger.info("Created data dict '%s' from builtin preset", name)
        return self.get_dict(name)

    def get_dict(self, name: str) -> Dict[str, Any]:
        """获取指定字典详情及所有条目。"""
        file_path = self._dict_file(name)
        if not file_path.exists():
            raise ValueError("DATA_DICT_NOT_FOUND")

        data = read_json_safe(file_path)
        if not isinstance(data, dict):
            raise ValueError("DATA_DICT_NOT_FOUND")

        entries = data.get("entries") or []
        cursor = data.get("cursor", 0)
        remark = str(data.get("remark") or "")
        updated_at = str(data.get("updated_at") or "")

        return {
            "name": name,
            "entries": entries,
            "cursor": cursor,
            "remark": remark,
            "updated_at": updated_at,
        }

    def save_dict(self, name: str, entries: List[str], remark: str = "") -> None:
        """保存字典（创建或更新）。

        - 校验 name：仅允许字母、数字、下划线、短横线。
        - 过滤空白行，若无有效条目抛出 DATA_DICT_EMPTY。
        - 原子写入保存，保留有效游标。
        """
        file_path = self._dict_file(name)

        if not isinstance(entries, (list, tuple)):
            raise ValueError("DATA_DICT_EMPTY")

        clean_entries: List[str] = [
            str(e).replace("\x00", "").strip()
            for e in entries
            if isinstance(e, (str, int, float)) and str(e).replace("\x00", "").strip()
        ]
        if not clean_entries:
            raise ValueError("DATA_DICT_EMPTY")

        with self._lock:
            cursor = 0
            if file_path.exists():
                existing = read_json_safe(file_path)
                if isinstance(existing, dict) and isinstance(
                    existing.get("cursor"), int
                ):
                    cursor = max(0, int(existing["cursor"])) % len(clean_entries)

            now_iso = datetime.now(timezone.utc).isoformat()
            dict_data = {
                "name": name,
                "entries": clean_entries,
                "cursor": cursor,
                "remark": remark.strip(),
                "updated_at": now_iso,
            }
            write_json_atomic(file_path, dict_data)
            logger.info(
                "Saved data dict '%s' with %d entries", name, len(clean_entries)
            )

    def delete_dict(self, name: str) -> bool:
        """删除指定字典。若不存在返回 False。"""
        file_path = self._dict_file(name)
        with self._lock:
            if not file_path.exists():
                return False
            try:
                file_path.unlink()
                self._stats.pop(name, None)
                self._stats_dirty = True
                logger.info("Deleted data dict '%s'", name)
                return True
            except OSError as exc:
                logger.error("Failed to delete data dict '%s': %s", name, exc)
                return False

    def get_entry(
        self,
        name: str,
        mode: Literal["random", "round_robin"] = "random",
        *,
        record: bool = True,
    ) -> str:
        """抽取词条。

        - random: 随机返回一条
        - round_robin: 并发锁保护下递增游标并持久化保存
        - record: 是否计入使用统计（采样预览等场景传 False）
        """
        file_path = self._dict_file(name)
        if not file_path.exists():
            raise ValueError("DATA_DICT_NOT_FOUND")

        with self._lock:
            data = read_json_safe(file_path)
            if not isinstance(data, dict):
                raise ValueError("DATA_DICT_NOT_FOUND")

            entries: List[str] = data.get("entries") or []
            if not entries:
                raise ValueError("DATA_DICT_EMPTY")

            if mode == "round_robin":
                cursor = max(0, int(data.get("cursor", 0))) % len(entries)
                selected = entries[cursor]
                data["cursor"] = (cursor + 1) % len(entries)
                write_json_atomic(file_path, data)
            else:
                selected = random.choice(entries)

            if record:
                self._record_usage(name)
                self._maybe_flush_stats()
            return selected

    def _stats_file(self) -> Path:
        return self.dict_dir / _STATS_FILE

    def _load_stats(self) -> None:
        """加载持久化的使用统计（异常时以空统计继续）。"""
        try:
            data = read_json_safe(self._stats_file())
            if isinstance(data, dict):
                for name, record in data.items():
                    if (
                        isinstance(name, str)
                        and isinstance(record, dict)
                        and isinstance(record.get("count"), int)
                    ):
                        self._stats[name] = {
                            "count": max(0, int(record["count"])),
                            "last_used": str(record.get("last_used") or ""),
                        }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load data dict stats: %s", exc)

    def _record_usage(self, name: str) -> None:
        """内存中递增某字典的使用次数，并记录最近使用时间。"""
        now_iso = datetime.now(timezone.utc).isoformat()
        stat = self._stats.get(name)
        if stat is None:
            self._stats[name] = {"count": 1, "last_used": now_iso}
        else:
            stat["count"] += 1
            stat["last_used"] = now_iso
        self._stats_dirty = True

    def _maybe_flush_stats(self) -> None:
        """按节流间隔把内存统计写入磁盘，避免写放大。"""
        now = time.monotonic()
        if (
            not self._stats_dirty
            or now - self._stats_last_flush < _STATS_FLUSH_INTERVAL_SECONDS
        ):
            return
        self._flush_stats(now)

    def _flush_stats(self, now: Optional[float] = None) -> None:
        if not self._stats_dirty:
            return
        if now is None:
            now = time.monotonic()
        try:
            write_json_atomic(self._stats_file(), dict(self._stats))
            self._stats_dirty = False
            self._stats_last_flush = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to flush data dict stats: %s", exc)

    def get_usage_stats(self) -> Dict[str, Dict[str, Any]]:
        """返回各字典的使用统计（次数 + 最近使用时间）。"""
        with self._lock:
            self._flush_stats()
            return {
                name: {
                    "count": int(rec.get("count", 0)),
                    "last_used": rec.get("last_used", ""),
                }
                for name, rec in self._stats.items()
            }


def get_data_dict_service() -> DataDictService:
    """获取 DataDictService 单例。"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DataDictService()
                try:
                    from tg_signer.core.template import set_data_dict_resolver

                    set_data_dict_resolver(
                        lambda name, mode: _instance.get_entry(name, mode=mode)
                    )
                except Exception:
                    pass
    return _instance
