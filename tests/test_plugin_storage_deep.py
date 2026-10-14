import asyncio
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from tg_signer.core.plugin_storage import PluginStore
from tg_signer.core.plugins import (
    PluginContext,
    PluginStorageBackend,
    PluginStorageClient,
)
from tg_signer.core.plugin_worker import ProxyStorageClient


def test_schema_and_pragmas(tmp_path):
    db_file = tmp_path / "test_store.db"
    store = PluginStore(db_path=db_file)

    conn = sqlite3.connect(str(db_file))
    try:
        # Check journal_mode
        cur = conn.execute("PRAGMA journal_mode;")
        journal_mode = cur.fetchone()[0]
        assert journal_mode.lower() == "wal"

        # Check per-connection pragmas on connections opened via store
        with store._conn() as s_conn:
            sync_mode = s_conn.execute("PRAGMA synchronous;").fetchone()[0]
            assert sync_mode in (1, "1", "NORMAL", "normal")
            timeout_res = s_conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            assert int(timeout_res) == 10000

        # Check table schema
        table_info = conn.execute("PRAGMA table_info(plugin_kv);").fetchall()
        # Columns: (cid, name, type, notnull, dflt_value, pk)
        cols = {row[1]: {"type": row[2].upper(), "pk": row[5]} for row in table_info}
        assert "namespace" in cols
        assert "key" in cols
        assert "value" in cols
        assert "expires_at" in cols
        assert cols["namespace"]["pk"] == 1
        assert cols["key"]["pk"] == 2

        # Check index
        indices = conn.execute("PRAGMA index_list(plugin_kv);").fetchall()
        idx_names = [idx[1] for idx in indices]
        assert "idx_plugin_kv_expires" in idx_names
    finally:
        conn.close()
        store.close()


def test_path_resolution(tmp_path, monkeypatch):
    # 1. Explicit db_path
    explicit_path = tmp_path / "explicit" / "store.db"
    s1 = PluginStore(db_path=explicit_path)
    assert s1.db_path == explicit_path
    assert explicit_path.is_file()

    # 2. PLUGIN_STORAGE_PATH
    env_path = tmp_path / "env" / "store.db"
    monkeypatch.setenv("PLUGIN_STORAGE_PATH", str(env_path))
    s2 = PluginStore()
    assert s2.db_path == env_path
    assert env_path.is_file()
    monkeypatch.delenv("PLUGIN_STORAGE_PATH")

    # 3. APP_DATA_DIR / TG_SIGNER_DATA_DIR
    app_data = tmp_path / "app_data"
    monkeypatch.setenv("APP_DATA_DIR", str(app_data))
    s3 = PluginStore()
    assert s3.db_path == app_data / "plugin_storage.db"
    assert (app_data / "plugin_storage.db").is_file()
    monkeypatch.delenv("APP_DATA_DIR")

    monkeypatch.setenv("TG_SIGNER_DATA_DIR", str(app_data / "sub"))
    s4 = PluginStore()
    assert s4.db_path == app_data / "sub" / "plugin_storage.db"
    assert (app_data / "sub" / "plugin_storage.db").is_file()
    monkeypatch.delenv("TG_SIGNER_DATA_DIR")


def test_crud_and_json_types(tmp_path):
    store = PluginStore(db_path=tmp_path / "crud.db")

    # String
    assert store.set("ns1", "str_key", "hello world")
    assert store.get("ns1", "str_key") == "hello world"

    # Int & Float
    store.set("ns1", "num_key", 42)
    assert store.get("ns1", "num_key") == 42
    store.set("ns1", "float_key", 3.1415)
    assert store.get("ns1", "float_key") == 3.1415

    # Dict & List
    complex_data = {"a": [1, 2, 3], "b": {"nested": True}}
    store.set("ns1", "complex", complex_data)
    assert store.get("ns1", "complex") == complex_data

    # Default value
    assert store.get("ns1", "non_existent", "my_default") == "my_default"

    # Delete
    assert store.delete("ns1", "str_key") is True
    assert store.delete("ns1", "str_key") is False
    assert store.get("ns1", "str_key") is None

    # Clear namespace
    store.set("ns2", "other_key", "keep_me")
    cleared = store.clear("ns1")
    assert cleared >= 2
    assert store.get("ns1", "num_key") is None
    assert store.get("ns2", "other_key") == "keep_me"


def test_lazy_ttl_purge_and_records(tmp_path):
    store = PluginStore(db_path=tmp_path / "ttl.db")
    ns = "ttl_ns"

    # Set keys with short TTL
    store.set(ns, "k_short", "expires_soon", ttl=0.1)
    store.set(ns, "k_long", "stays_alive", ttl=100.0)
    store.set(ns, "k_perm", "permanent")

    time.sleep(0.15)

    # 1. get() triggers lazy purge
    assert store.get(ns, "k_short", "default") == "default"

    # 2. list_keys() and keys() filter and lazy purge
    store.set(ns, "k_short2", "temp2", ttl=0.05)
    time.sleep(0.08)
    keys_list = store.list_keys(ns)
    assert "k_short2" not in keys_list
    assert "k_long" in keys_list
    assert "k_perm" in keys_list
    assert store.keys(ns) == keys_list

    # 3. get_all() filters and lazy purges
    all_data = store.get_all(ns)
    assert "k_short" not in all_data
    assert "k_short2" not in all_data
    assert all_data["k_long"] == "stays_alive"
    assert all_data["k_perm"] == "permanent"

    # 4. get_all_records() returns structured records with ttl_remaining
    records = store.get_all_records(ns)
    assert len(records) == 2
    rec_map = {r["key"]: r for r in records}
    assert rec_map["k_perm"]["ttl_remaining"] is None
    assert rec_map["k_perm"]["expires_at"] is None
    assert rec_map["k_long"]["ttl_remaining"] is not None
    assert rec_map["k_long"]["ttl_remaining"] > 50.0

    # 5. mget filters and lazy purges
    store.set(ns, "k_short3", "temp3", ttl=0.05)
    time.sleep(0.08)
    mget_res = store.mget(ns, ["k_short3", "k_long", "k_perm"])
    assert "k_short3" not in mget_res
    assert mget_res["k_long"] == "stays_alive"
    assert mget_res["k_perm"] == "permanent"


def test_active_purge_expired(tmp_path):
    store = PluginStore(db_path=tmp_path / "active_purge.db")
    store.set("ns1", "expired1", "val", ttl=0.05)
    store.set("ns1", "valid1", "val", ttl=100)
    store.set("ns2", "expired2", "val", ttl=0.05)
    store.set("ns2", "valid2", "val", ttl=100)

    time.sleep(0.08)
    # Purge only ns1
    purged_ns1 = store.purge_expired("ns1")
    assert purged_ns1 == 1

    # ns2 still has expired2 in raw db until purged
    purged_all = store.purge_expired()
    assert purged_all == 1


def test_atomic_increment_and_concurrency(tmp_path):
    store = PluginStore(db_path=tmp_path / "increment.db")
    ns = "atomic_ns"

    # Non-existent key increments from default
    res = store.increment(ns, "cnt", amount=5, default=10)
    assert res == 15

    # Increment again
    res = store.increment(ns, "cnt", amount=3)
    assert res == 18

    # Backward compatible keyword 'delta'
    res = store.increment(ns, "cnt", delta=2)
    assert res == 20

    # TTL retention test: set with TTL, increment without specifying TTL preserves original TTL
    store.set(ns, "ttl_cnt", 100, ttl=50.0)
    recs_before = store.get_all_records(ns)
    orig_exp = [r for r in recs_before if r["key"] == "ttl_cnt"][0]["expires_at"]

    store.increment(ns, "ttl_cnt", amount=1)
    assert store.get(ns, "ttl_cnt") == 101

    recs_after = store.get_all_records(ns)
    after_exp = [r for r in recs_after if r["key"] == "ttl_cnt"][0]["expires_at"]
    assert after_exp == orig_exp

    # New TTL if specified on increment
    store.increment(ns, "ttl_cnt", amount=1, ttl=200.0)
    recs_new = store.get_all_records(ns)
    new_exp = [r for r in recs_new if r["key"] == "ttl_cnt"][0]["expires_at"]
    assert new_exp > orig_exp

    # Concurrency test: 10 threads each incrementing 20 times
    def worker():
        for _ in range(20):
            store.increment(ns, "threaded_cnt", amount=1, default=0)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.get(ns, "threaded_cnt") == 200


def test_namespace_isolation_and_listing(tmp_path):
    store = PluginStore(db_path=tmp_path / "ns.db")
    store.set("pluginA", "k", "val_A")
    store.set("123:pluginA", "k", "val_user_A")
    store.set("456:pluginB", "k", "val_user_B")
    store.set("global:pluginA", "k", "val_global_A")

    assert store.get("pluginA", "k") == "val_A"
    assert store.get("123:pluginA", "k") == "val_user_A"
    assert store.get("456:pluginB", "k") == "val_user_B"

    # list_namespaces
    all_ns = store.list_namespaces()
    assert all_ns == ["123:pluginA", "456:pluginB", "global:pluginA", "pluginA"]

    # filter by plugin_name
    a_ns = store.list_namespaces(plugin_name="pluginA")
    assert "123:pluginA" in a_ns
    assert "pluginA" in a_ns
    assert "global:pluginA" in a_ns
    assert "456:pluginB" not in a_ns


def test_backward_compatibility_plugin_storage_backend(tmp_path):
    # Verify PluginStorageBackend is subclass of PluginStore
    assert issubclass(PluginStorageBackend, PluginStore)

    backend = PluginStorageBackend(db_path=tmp_path / "compat.db")
    assert isinstance(backend, PluginStore)

    backend.set("test_ns", "key1", "val1")
    assert backend.get("test_ns", "key1") == "val1"
    assert backend.increment("test_ns", "num", delta=3, default=1) == 4
    assert backend.keys("test_ns") == ["key1", "num"]
    assert backend.list_keys("test_ns") == ["key1", "num"]


@pytest.mark.asyncio
async def test_plugin_storage_client_async(tmp_path):
    store = PluginStore(db_path=tmp_path / "client.db")
    client = PluginStorageClient(namespace="client_ns", backend=store)

    await client.set("key1", {"x": 10}, ttl=60)
    val = await client.get("key1")
    assert val == {"x": 10}

    num = await client.increment("counter", amount=5, default=10)
    assert num == 15
    num2 = await client.increment("counter", delta=2)
    assert num2 == 17

    keys = await client.list_keys()
    assert sorted(keys) == ["counter", "key1"]

    all_data = await client.get_all()
    assert all_data["counter"] == 17
    assert all_data["key1"] == {"x": 10}

    await client.mset({"k2": 2, "k3": 3})
    m_res = await client.mget(["k2", "k3"])
    assert m_res == {"k2": 2, "k3": 3}

    deleted = await client.delete("k2")
    assert deleted is True

    cleared = await client.clear()
    assert cleared >= 3
    assert await client.get("counter") is None


@pytest.mark.asyncio
async def test_triparty_idempotency_roundtrip(tmp_path):
    """Worker ProxyStorageClient -> Host RPC handler -> PluginStore roundtrip."""
    store = PluginStore(db_path=tmp_path / "triparty.db")

    class MockContext:
        def __init__(self, ns: str, g_ns: str):
            self.storage = PluginStorageClient(namespace=ns, store=store)
            self.global_storage = PluginStorageClient(namespace=g_ns, store=store)

    ctx = MockContext(ns="chat_100:my_plugin", g_ns="global:my_plugin")

    # Host RPC handler simulating PluginHost._handle_rpc
    async def host_rpc(method: str, **params: Any) -> Any:
        is_global = bool(params.pop("is_global", False))
        target_storage = ctx.global_storage if is_global else ctx.storage
        if method == "storage_get":
            return await target_storage.get(
                params.get("key", ""), default=params.get("default", None)
            )
        elif method == "storage_set":
            await target_storage.set(
                params.get("key", ""),
                params.get("value", None),
                ttl=params.get("ttl", None),
            )
            return True
        elif method == "storage_increment":
            return await target_storage.increment(
                params.get("key", ""),
                amount=params.get("amount", params.get("delta", 1)),
                default=params.get("default", 0),
                ttl=params.get("ttl", None),
            )
        elif method == "storage_delete":
            return await target_storage.delete(params.get("key", ""))
        elif method == "storage_clear":
            return await target_storage.clear()
        elif method in ("storage_keys", "storage_list_keys"):
            return await target_storage.keys(prefix=params.get("prefix", ""))
        elif method == "storage_get_all":
            return await target_storage.get_all(prefix=params.get("prefix", ""))
        elif method == "storage_mget":
            return await target_storage.mget(params.get("keys", []))
        elif method == "storage_mset":
            await target_storage.mset(
                params.get("mapping", {}), ttl=params.get("ttl", None)
            )
            return True
        else:
            raise ValueError(f"Unknown RPC method: {method}")

    # Worker ProxyStorageClient instances
    worker_session_storage = ProxyStorageClient(
        host_rpc, is_global=False, namespace="chat_100:my_plugin"
    )
    worker_global_storage = ProxyStorageClient(
        host_rpc, is_global=True, namespace="global:my_plugin"
    )

    # 1. Session storage set & get
    await worker_session_storage.set("task_state", "in_progress")
    assert await worker_session_storage.get("task_state") == "in_progress"

    # Global storage should not see session storage keys
    assert await worker_global_storage.get("task_state") is None

    # 2. Global storage set & get
    await worker_global_storage.set("global_counter", 100)
    assert await worker_global_storage.get("global_counter") == 100
    assert await worker_session_storage.get("global_counter") is None

    # 3. Increment roundtrip
    cnt = await worker_session_storage.increment("attempts", delta=1)
    assert cnt == 1
    cnt = await worker_session_storage.increment("attempts", amount=4)
    assert cnt == 5

    # 4. Keys & get_all roundtrip
    keys = await worker_session_storage.keys()
    assert sorted(keys) == ["attempts", "task_state"]

    all_data = await worker_session_storage.get_all()
    assert all_data == {"attempts": 5, "task_state": "in_progress"}

    # 5. Direct verification in underlying PluginStore
    assert store.get("chat_100:my_plugin", "attempts") == 5
    assert store.get("global:my_plugin", "global_counter") == 100
