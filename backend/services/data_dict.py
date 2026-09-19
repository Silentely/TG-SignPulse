from __future__ import annotations

import logging
import random
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from backend.core.config import get_settings
from backend.utils.atomic_io import read_json_safe, write_json_atomic

logger = logging.getLogger("backend.data_dict")

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_instance: Optional[DataDictService] = None
_instance_lock = threading.Lock()


class DataDictService:
    """自动化素材数据字典池服务。

    管理动态素材字典的持久化、校验、随机及轮询 (Round-Robin) 取词。
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else get_settings().resolve_base_dir()
        self.dict_dir = self.base_dir / "data_dicts"
        self.dict_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _dict_file(self, name: str) -> Path:
        if not name or not _NAME_PATTERN.match(name):
            raise ValueError("INVALID_DICT_NAME")
        return self.dict_dir / f"{name}.json"

    def list_dicts(self) -> List[Dict[str, Any]]:
        """列出所有字典元信息（名称、条目数、备注、更新时间）。"""
        results: List[Dict[str, Any]] = []
        with self._lock:
            for path in sorted(self.dict_dir.glob("*.json")):
                if not path.is_file():
                    continue
                data = read_json_safe(path)
                if not isinstance(data, dict):
                    continue
                name = path.stem
                entries = data.get("entries") or []
                results.append({
                    "name": name,
                    "count": len(entries),
                    "remark": str(data.get("remark") or ""),
                    "updated_at": str(data.get("updated_at") or ""),
                })
        return results

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
            str(e).strip() for e in entries if isinstance(e, (str, int, float)) and str(e).strip()
        ]
        if not clean_entries:
            raise ValueError("DATA_DICT_EMPTY")

        with self._lock:
            cursor = 0
            if file_path.exists():
                existing = read_json_safe(file_path)
                if isinstance(existing, dict) and isinstance(existing.get("cursor"), int):
                    cursor = existing["cursor"] % len(clean_entries)

            now_iso = datetime.now(timezone.utc).isoformat()
            dict_data = {
                "name": name,
                "entries": clean_entries,
                "cursor": cursor,
                "remark": remark.strip(),
                "updated_at": now_iso,
            }
            write_json_atomic(file_path, dict_data)
            logger.info("Saved data dict '%s' with %d entries", name, len(clean_entries))

    def delete_dict(self, name: str) -> bool:
        """删除指定字典。若不存在返回 False。"""
        file_path = self._dict_file(name)
        with self._lock:
            if not file_path.exists():
                return False
            try:
                file_path.unlink()
                logger.info("Deleted data dict '%s'", name)
                return True
            except OSError as exc:
                logger.error("Failed to delete data dict '%s': %s", name, exc)
                return False

    def get_entry(self, name: str, mode: Literal["random", "round_robin"] = "random") -> str:
        """抽取词条。

        - random: 随机返回一条
        - round_robin: 并发锁保护下递增游标并持久化保存
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
                cursor = int(data.get("cursor", 0)) % len(entries)
                selected = entries[cursor]
                data["cursor"] = (cursor + 1) % len(entries)
                write_json_atomic(file_path, data)
                return selected
            else:
                return random.choice(entries)


def get_data_dict_service() -> DataDictService:
    """获取 DataDictService 单例。"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DataDictService()
    return _instance
