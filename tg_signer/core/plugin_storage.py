"""PluginStore 模块：基于 SQLite 的线程与多进程安全轻量级持久化 KV 存储后端。

提供完整的 SQLite KV 语义超集，包括：
- 确定性路径寻址解析（显式 db_path -> PLUGIN_STORAGE_PATH -> APP_DATA_DIR / TG_SIGNER_DATA_DIR -> /data -> 当前工作目录）
- WAL 模式与 busy_timeout 锁冲突规避
- 复合主键 (namespace, key) 与过期时间索引
- 惰性读取清扫（Lazy TTL Purge）与主动过期清扫（Active TTL Purge）
- BEGIN IMMEDIATE 原子递增
- 跨插件/跨会话命名空间隔离
"""

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

_logger = logging.getLogger("tg_signer.plugin_storage")


class PluginStore:
    """基于 SQLite 的线程与多进程安全轻量级持久化 KV 存储引擎。"""

    @staticmethod
    def _escape_like(text: str) -> str:
        return text.replace("/", "//").replace("%", "/%").replace("_", "/_")

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
        elif os.getenv("PLUGIN_STORAGE_PATH"):
            self.db_path = Path(os.getenv("PLUGIN_STORAGE_PATH"))
        else:
            base_dir = os.getenv("APP_DATA_DIR") or os.getenv("TG_SIGNER_DATA_DIR")
            if base_dir:
                self.db_path = Path(base_dir) / "plugin_storage.db"
            elif Path("/data").is_dir() and os.access("/data", os.W_OK):
                self.db_path = Path("/data/plugin_storage.db")
            else:
                self.db_path = Path.cwd() / "data" / "plugin_storage.db"

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except Exception as e:
            _logger.warning("初始化插件持久化存储失败 (%s): %s", self.db_path, e)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """显式释放资源（占位保持无状态接口兼容）。"""
        pass

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plugin_kv (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (namespace, key)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_plugin_kv_expires
                ON plugin_kv (expires_at)
                WHERE expires_at IS NOT NULL;
                """
            )
            conn.commit()

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """读取指定命名空间下的单个键值；若已过期则自动惰性清理并返回默认值。"""
        now = time.time()
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT value, expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
                row = cur.fetchone()
                if not row:
                    return default
                val_str, expires_at = row
                if expires_at is not None and expires_at < now:
                    conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                        (namespace, key),
                    )
                    conn.commit()
                    return default
                try:
                    return json.loads(val_str)
                except Exception:
                    return val_str
        except Exception as exc:
            _logger.warning("插件读取存储失败 [%s:%s]: %s", namespace, key, exc)
            return default

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl: Optional[Union[int, float]] = None,
    ) -> bool:
        """写入键值，支持指定 TTL（秒）；成功返回 True，失败返回 False。"""
        now = time.time()
        expires_at = (now + ttl) if (ttl is not None and ttl > 0) else None
        val_str = json.dumps(value, ensure_ascii=False)
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at;
                    """,
                    (namespace, key, val_str, expires_at),
                )
                conn.commit()
                return True
        except Exception as exc:
            _logger.warning("插件写入存储失败 [%s:%s]: %s", namespace, key, exc)
            return False

    def increment(
        self,
        namespace: str,
        key: str,
        amount: int = 1,
        default: int = 0,
        ttl: Optional[Union[int, float]] = None,
        *,
        delta: Optional[int] = None,
    ) -> Optional[int]:
        """在事务锁（BEGIN IMMEDIATE）内原子递增整数值，返回递增后的结果；写入失败返回 None。

        参数同时支持 `amount` 与向后兼容别名 `delta`。
        若指定有效 ttl，将应用新 ttl；若 ttl 为 None 且目标键带有仍有效的 TTL，保留原过期时间；
        若目标键已过期或为新建键且未传 ttl，重置为永久有效。
        """
        step = delta if delta is not None else amount
        now = time.time()
        try:
            with self._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT value, expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                ).fetchone()
                current = default
                existing_exp = None
                if row and (row[1] is None or row[1] >= now):
                    try:
                        parsed = json.loads(row[0])
                        if isinstance(parsed, (int, float)) and not isinstance(
                            parsed, bool
                        ):
                            current = int(parsed)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                    existing_exp = row[1]

                updated = current + int(step)

                if ttl is not None and ttl > 0:
                    target_exp = now + ttl
                elif ttl is not None and ttl <= 0:
                    target_exp = None
                else:
                    target_exp = existing_exp

                conn.execute(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at
                    """,
                    (namespace, key, json.dumps(updated), target_exp),
                )
                conn.commit()
                return updated
        except Exception as exc:
            _logger.warning("插件原子递增存储失败 [%s:%s]: %s", namespace, key, exc)
            return None

    def delete(self, namespace: str, key: str) -> bool:
        """删除指定键；存在并删除成功返回 True，不存在或失败返回 False。"""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                    (namespace, key),
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as exc:
            _logger.warning("插件删除存储失败 [%s:%s]: %s", namespace, key, exc)
            return False

    def clear(self, namespace: Optional[str] = None) -> int:
        """清空指定命名空间（或所有命名空间）的数据，返回被删除的记录数。"""
        try:
            with self._conn() as conn:
                if namespace:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ?", (namespace,)
                    )
                else:
                    cur = conn.execute("DELETE FROM plugin_kv")
                conn.commit()
                return cur.rowcount
        except Exception as exc:
            _logger.warning("插件清空存储失败: %s", exc)
            return 0

    def purge_expired(self, namespace: Optional[str] = None) -> int:
        """主动清理已过期的所有记录，返回被清理的记录数。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if namespace:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE namespace = ? AND expires_at IS NOT NULL AND expires_at < ?",
                        (namespace, now),
                    )
                else:
                    cur = conn.execute(
                        "DELETE FROM plugin_kv WHERE expires_at IS NOT NULL AND expires_at < ?",
                        (now,),
                    )
                conn.commit()
                return cur.rowcount
        except Exception as exc:
            _logger.warning("插件清理过期存储失败: %s", exc)
            return 0

    def list_keys(self, namespace: str, prefix: str = "") -> List[str]:
        """列出指定命名空间下未过期的键名（支持前缀匹配），自动淘汰已过期记录。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if prefix:
                    escaped_prefix = self._escape_like(prefix)
                    cur = conn.execute(
                        "SELECT key, expires_at FROM plugin_kv WHERE namespace = ? AND key LIKE ? ESCAPE '/'",
                        (namespace, f"{escaped_prefix}%"),
                    )
                else:
                    cur = conn.execute(
                        "SELECT key, expires_at FROM plugin_kv WHERE namespace = ?",
                        (namespace,),
                    )
                rows = cur.fetchall()
                valid_keys: List[str] = []
                expired_keys: List[str] = []
                for k, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                    else:
                        valid_keys.append(k)
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return sorted(valid_keys)
        except Exception as exc:
            _logger.warning("插件读取存储键列表失败 [%s]: %s", namespace, exc)
            return []

    def keys(self, namespace: str, prefix: str = "") -> List[str]:
        """`list_keys` 的向后兼容别名。"""
        return self.list_keys(namespace, prefix=prefix)

    def mget(self, namespace: str, keys: List[str]) -> Dict[str, Any]:
        """批量根据指定键列表读取键值对（自动分片规避 SQLite 变量上限，自动过滤与清理过期记录）。"""
        if not keys:
            return {}
        now = time.time()
        res: Dict[str, Any] = {}
        expired_keys: List[str] = []
        CHUNK_SIZE = 500
        key_list = list(keys)
        try:
            with self._conn() as conn:
                for i in range(0, len(key_list), CHUNK_SIZE):
                    chunk = key_list[i : i + CHUNK_SIZE]
                    placeholders = ",".join("?" for _ in chunk)
                    params = [namespace] + chunk
                    cur = conn.execute(
                        f"SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ? AND key IN ({placeholders})",
                        params,
                    )
                    rows = cur.fetchall()
                    for k, val_str, exp in rows:
                        if exp is not None and exp < now:
                            expired_keys.append(k)
                            continue
                        try:
                            res[k] = json.loads(val_str)
                        except Exception:
                            res[k] = val_str

                if expired_keys:
                    for i in range(0, len(expired_keys), CHUNK_SIZE):
                        exp_chunk = expired_keys[i : i + CHUNK_SIZE]
                        del_placeholders = ",".join("?" for _ in exp_chunk)
                        try:
                            conn.execute(
                                f"DELETE FROM plugin_kv WHERE namespace = ? AND key IN ({del_placeholders})",
                                [namespace] + exp_chunk,
                            )
                        except Exception as clean_exc:
                            _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                    conn.commit()
                return res
        except Exception as exc:
            _logger.warning("插件批量按键读取存储失败 [%s]: %s", namespace, exc)
            return {}

    def mset(
        self,
        namespace: str,
        mapping: Dict[str, Any],
        ttl: Optional[Union[int, float]] = None,
    ) -> bool:
        """批量写入键值对，支持统一指定过期时间；成功返回 True，失败返回 False。"""
        if not mapping:
            return True
        now = time.time()
        expires_at = (now + ttl) if (ttl is not None and ttl > 0) else None
        try:
            rows = []
            for k, val in mapping.items():
                val_str = json.dumps(val, ensure_ascii=False)
                rows.append((namespace, k, val_str, expires_at))
            with self._conn() as conn:
                conn.executemany(
                    """
                    INSERT INTO plugin_kv (namespace, key, value, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at
                    """,
                    rows,
                )
                conn.commit()
                return True
        except Exception as exc:
            _logger.warning("插件批量写入存储失败 [%s]: %s", namespace, exc)
            return False

    def get_all(self, namespace: str, prefix: str = "") -> Dict[str, Any]:
        """批量读取指定命名空间下所有未过期的键值对（支持前缀过滤），自动淘汰已过期记录。"""
        now = time.time()
        try:
            with self._conn() as conn:
                if prefix:
                    escaped_prefix = self._escape_like(prefix)
                    cur = conn.execute(
                        "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ? AND key LIKE ? ESCAPE '/'",
                        (namespace, f"{escaped_prefix}%"),
                    )
                else:
                    cur = conn.execute(
                        "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ?",
                        (namespace,),
                    )
                rows = cur.fetchall()
                res: Dict[str, Any] = {}
                expired_keys: List[str] = []
                for k, val_str, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                        continue
                    try:
                        res[k] = json.loads(val_str)
                    except Exception:
                        res[k] = val_str
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return res
        except Exception as exc:
            _logger.warning("插件批量读取存储失败 [%s]: %s", namespace, exc)
            return {}

    def list_namespaces(self, plugin_name: Optional[str] = None) -> List[str]:
        """列出当前数据库中存在的所有命名空间，可根据插件名称进行关联匹配。"""
        try:
            with self._conn() as conn:
                if plugin_name:
                    escaped_name = self._escape_like(plugin_name)
                    cur = conn.execute(
                        """
                        SELECT DISTINCT namespace FROM plugin_kv
                        WHERE namespace = ?
                           OR namespace LIKE ? ESCAPE '/'
                           OR namespace LIKE ? ESCAPE '/'
                        """,
                        (
                            plugin_name,
                            f"%:{escaped_name}",
                            f"__test__:%:{escaped_name}",
                        ),
                    )
                else:
                    cur = conn.execute("SELECT DISTINCT namespace FROM plugin_kv")
                rows = cur.fetchall()
                return sorted([r[0] for r in rows if r[0]])
        except Exception as exc:
            _logger.warning("查询插件存储命名空间失败: %s", exc)
            return []

    def get_all_records(self, namespace: str) -> List[Dict[str, Any]]:
        """获取指定命名空间下的完整结构化记录（含过期时间与剩余 TTL）。"""
        now = time.time()
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ?",
                    (namespace,),
                )
                rows = cur.fetchall()
                records: List[Dict[str, Any]] = []
                expired_keys: List[str] = []
                for k, val_str, exp in rows:
                    if exp is not None and exp < now:
                        expired_keys.append(k)
                        continue
                    try:
                        parsed_val = json.loads(val_str)
                    except Exception:
                        parsed_val = val_str
                    records.append(
                        {
                            "key": k,
                            "value": parsed_val,
                            "expires_at": exp,
                            "ttl_remaining": round(exp - now, 1)
                            if exp is not None
                            else None,
                        }
                    )
                if expired_keys:
                    try:
                        conn.executemany(
                            "DELETE FROM plugin_kv WHERE namespace = ? AND key = ?",
                            [(namespace, ek) for ek in expired_keys],
                        )
                        conn.commit()
                    except Exception as clean_exc:
                        _logger.debug("延迟清理过期记录异常: %s", clean_exc)
                return sorted(records, key=lambda x: x["key"])
        except Exception as exc:
            _logger.warning("插件读取存储记录失败 [%s]: %s", namespace, exc)
            return []
