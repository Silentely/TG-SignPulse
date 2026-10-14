"""TG-SignPulse 架构深化行为基线与样本测试集。

在任何架构重构（Phase 1 ~ Phase 4）开始前，冻结系统核心基线行为：
- Step 1: 历史文件样本测试集
  - 当前可逆路径编码 (safe_history_key / unsafe_history_key)
  - 历史旧编码自动识别与向后兼容 (legacy_history_file_path / resolve_existing_history_file)
  - 历史文件迁移合并与孤儿清理 (migrate_legacy_history_file)
  - 无账号共享历史文件与过滤 (unassigned / shared history)
  - 损坏/空 JSON 容错与优雅降级
  - dict 与 list 两种历史数据布局兼容
  - 账号改名时历史文件与条目重命名
  - SSE publish_sign_history 事件总线触发与数据契约
- Step 2: Plugin SQLite 存量数据样本
  - 数据库表结构 (plugin_kv schema) 与索引
  - 运行时 PRAGMA 配置 (WAL, busy_timeout, synchronous)
  - 命名空间强隔离 (namespace isolation)
  - TTL 过期淘汰机制 (主动 purge_expired 与惰性读清理)
  - 原子递增 (BEGIN IMMEDIATE / increment)
  - 三方幂等性 (旧实现写入 -> 原生 SQLite 读取校验 -> 原生 SQLite 修改 -> 旧实现重新读回)
- Step 3: 图编译与 IPC 帧样本
  - 图编译调用方输入字典非破坏性保证 (两次编译同一 dict 逐字节相等，原 dict 零修改)
  - IPC 帧类型全量契约解析 (log / return / call / call_result / 超时 / 损坏帧 / 截断)
  - ProxyMessage 与 RPC 交互契约
"""

from __future__ import annotations

import asyncio
import copy
import datetime
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

# Step 1 imports
from backend.services.sign_history_events import (
    publish_sign_history,
    reset_for_tests,
    subscribe,
    subscriber_count,
    unsubscribe,
)
from backend.services.sign_task_history_format import (
    build_history_list_item,
    normalize_flow_logs,
)
from backend.services.sign_task_history_io import (
    count_history_entries,
    filter_history_entries,
    history_file_owner,
    history_file_path,
    legacy_history_file_path,
    load_history_entries,
    load_history_payload_from_file,
    migrate_legacy_history_file,
    resolve_existing_history_file,
    safe_history_key,
    unsafe_history_key,
)

# Step 2 imports
from tg_signer.core.plugins import PluginStorageBackend

# Step 3 imports
from tg_signer.config import (
    ChooseOptionByImageAction,
    ClickKeyboardByTextAction,
    SendTextAction,
    SignChatV3,
    WorkflowStepConfig,
)
from tg_signer.core.flow_models import (
    TERMINAL_COMPLETE_ID,
    ActionNode,
    ExecutionGraph,
    LoopPolicy,
    TerminalPolicy,
)
from tg_signer.core.flow_normalizer import GraphNormalizer
from tg_signer.core.plugin_ipc import (
    ProxyButton,
    ProxyChat,
    ProxyMessage,
    ProxyUser,
    decode_ipc_payload,
    encode_ipc_payload,
    serialize_message_for_worker,
)


# ==============================================================================
# Step 1: 历史文件样本测试集 (Historical File Layout & Migration Baseline)
# ==============================================================================


class TestHistoricalFileBaselines:
    """历史数据存储布局、编码、迁移与事件发布基线。"""

    def test_reversible_path_encoding_and_injectivity(self, tmp_path: Path):
        """测试可逆路径编码的单射性、互逆性及文件名所有权反查。"""
        # 1. 互逆性 (Roundtrip)
        test_keys = [
            "normal_account",
            "account__with__double__underscore",
            "account%with%percent",
            "acc/slash\\backslash",  # / 和 \ 在 safe_history_key 中被归一为 _
            "plain",
            "%5F",
            "%25",
            "123_456_789",
            "__starts_and_ends__",
        ]
        for key in test_keys:
            encoded = safe_history_key(key)
            # 不能包含文件系统非法字符
            assert "/" not in encoded
            assert "\\" not in encoded
            # 除了含路径斜杠被归一化的，其余必须严格互逆
            if "/" not in key and "\\" not in key:
                assert unsafe_history_key(encoded) == key

        # 2. 跨分隔符单射性 (Injectivity)
        # (a__b, c) 与 (a, b__c) 不得映射到同一个文件名
        path_1 = history_file_path(tmp_path, "c", "a__b")
        path_2 = history_file_path(tmp_path, "b__c", "a")
        assert path_1 != path_2
        assert path_1.name == "a%5F%5Fb__c.json"
        assert path_2.name == "a__b%5F%5Fc.json"

        # 3. 宿主反查 (history_file_owner)
        assert history_file_owner(path_1) == "a__b"
        assert history_file_owner(path_2) == "a"
        # 旧版单账号无前缀布局应返回 None
        assert history_file_owner(tmp_path / "plain_task.json") is None

    def test_legacy_format_resolution_and_migration(self, tmp_path: Path):
        """测试旧版下划线文件名兼容解析及自动向新版转义路径迁移。"""
        # 旧路径未转义：acc_1__task_1.json
        legacy_file = legacy_history_file_path(tmp_path, "task_1", "acc_1")
        assert legacy_file.name == "acc_1__task_1.json"

        old_entries = [
            {
                "time": "2026-09-01T10:00:00",
                "account_name": "acc_1",
                "message": "legacy success",
                "success": True,
            }
        ]
        legacy_file.write_text(json.dumps(old_entries), encoding="utf-8")

        # 解析现有文件优先找到 legacy
        resolved = resolve_existing_history_file(tmp_path, "task_1", "acc_1")
        assert resolved == legacy_file

        # 执行迁移
        migrated_path = migrate_legacy_history_file(tmp_path, "task_1", "acc_1")
        target_file = history_file_path(tmp_path, "task_1", "acc_1")
        assert migrated_path == target_file
        assert target_file.name == "acc%5F1__task%5F1.json"
        assert target_file.exists()
        assert not legacy_file.exists()

        # 加载内容保持一致
        loaded = load_history_entries(tmp_path, "task_1", account_name="acc_1")
        assert len(loaded) == 1
        assert loaded[0]["message"] == "legacy success"

    def test_legacy_shared_history_isolated_migration(self, tmp_path: Path):
        """多账号共享历史文件时，迁移指定账号条目不破坏其他账号条目。"""
        legacy = legacy_history_file_path(tmp_path, "common_task", "account_a")
        legacy.write_text(
            json.dumps(
                [
                    {"time": "t1", "account_name": "account_a", "message": "a_entry"},
                    {"time": "t2", "account_name": "account_b", "message": "b_entry"},
                ]
            ),
            encoding="utf-8",
        )

        migrate_legacy_history_file(tmp_path, "common_task", "account_a")

        # 账号 a 的条目迁移至专属目标文件
        entries_a = load_history_entries(tmp_path, "common_task", "account_a")
        assert len(entries_a) == 1
        assert entries_a[0]["message"] == "a_entry"

        # 原始 legacy 文件保留账号 b 的条目
        assert legacy.exists()
        kept = json.loads(legacy.read_text(encoding="utf-8"))
        assert len(kept) == 1
        assert kept[0]["account_name"] == "account_b"
        assert kept[0]["message"] == "b_entry"

    def test_migration_merges_when_target_already_exists(self, tmp_path: Path):
        """目标文件已有时迁移合并：去重追加，按时间逆序，不覆盖。"""
        legacy = legacy_history_file_path(tmp_path, "task_merge", "acc")
        legacy.write_text(
            json.dumps(
                [{"time": "2026-09-01T12:00:00", "account_name": "acc", "val": "old"}]
            ),
            encoding="utf-8",
        )
        target = history_file_path(tmp_path, "task_merge", "acc")
        target.write_text(
            json.dumps(
                [{"time": "2026-09-03T12:00:00", "account_name": "acc", "val": "new"}]
            ),
            encoding="utf-8",
        )

        migrate_legacy_history_file(tmp_path, "task_merge", "acc", max_entries=50)

        merged = load_history_entries(tmp_path, "task_merge", account_name="acc")
        assert len(merged) == 2
        assert [e["val"] for e in merged] == ["new", "old"]
        assert not legacy.exists()

    def test_unassigned_account_shared_history_fallback(self, tmp_path: Path):
        """无账号前缀的旧版公共文件解析与账号过滤基线：未绑定账号条目属于公共共享。"""
        public_file = tmp_path / "global_task.json"
        public_file.write_text(
            json.dumps(
                [
                    {"time": "t1", "account_name": "alice", "success": True},
                    {"time": "t2", "account_name": "bob", "success": False},
                    {"time": "t3", "success": True},  # 无 account_name 字段，被视为通用/共享条目
                ]
            ),
            encoding="utf-8",
        )

        # 查找 alice 的历史能够回退到该公共文件，并保留 alice 本人和无账号共享条目，排他过滤掉 bob
        alice_entries = load_history_entries(tmp_path, "global_task", account_name="alice")
        assert len(alice_entries) == 2
        acc_names = [e.get("account_name") for e in alice_entries]
        assert "alice" in acc_names
        assert None in acc_names
        assert "bob" not in acc_names

        # 未指定 account_name 时加载全部条目
        all_entries = load_history_entries(tmp_path, "global_task", account_name=None)
        assert len(all_entries) == 3

    def test_corrupt_and_empty_json_graceful_handling(self, tmp_path: Path):
        """损坏/空 JSON 容错与优雅降级，不抛出非受检异常。"""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("", encoding="utf-8")
        assert load_history_payload_from_file(empty_file) == []

        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{broken json: 123", encoding="utf-8")
        assert load_history_payload_from_file(corrupt_file) == []

        scalar_file = tmp_path / "scalar.json"
        scalar_file.write_text('"plain string"', encoding="utf-8")
        # 标量不是 dict 也不是 list，应优雅处理
        payload = load_history_payload_from_file(scalar_file)
        assert count_history_entries(payload) == 0

    def test_dict_vs_list_layout_backward_compatibility(self, tmp_path: Path):
        """单字典布局（旧版单次签到历史）与列表布局（多条记录）双重兼容。"""
        # 1. 字典布局
        dict_file = tmp_path / "single_run.json"
        dict_file.write_text(
            json.dumps(
                {
                    "time": "2026-10-01T08:00:00",
                    "account_name": "user1",
                    "success": True,
                    "message": "signed",
                }
            ),
            encoding="utf-8",
        )
        dict_payload = load_history_payload_from_file(dict_file)
        assert count_history_entries(dict_payload) == 1
        filtered_dict = filter_history_entries(dict_payload, account_name="user1")
        assert len(filtered_dict) == 1
        assert filtered_dict[0]["account_name"] == "user1"

        # 2. 列表布局
        list_file = tmp_path / "multi_run.json"
        list_file.write_text(
            json.dumps(
                [
                    {"time": "t1", "account_name": "user1", "success": True},
                    {"time": "t2", "account_name": "user1", "success": False},
                ]
            ),
            encoding="utf-8",
        )
        list_payload = load_history_payload_from_file(list_file)
        assert count_history_entries(list_payload) == 2
        filtered_list = filter_history_entries(list_payload, account_name="user1")
        assert len(filtered_list) == 2

    def test_account_renaming_updates_content_and_filename(self, tmp_path: Path):
        """验证账号重命名对历史文件的规约：文件重命名并改写内部 account_name。"""
        old_acc = "old_user"
        new_acc = "new_user"
        task = "daily_check"

        old_file = history_file_path(tmp_path, task, old_acc)
        old_file.write_text(
            json.dumps(
                [
                    {"time": "t1", "account_name": "old_user", "message": "msg1"},
                    {"time": "t2", "account_name": "other_user", "message": "msg2"},
                ]
            ),
            encoding="utf-8",
        )

        # 模拟 CRUD rename 路径
        safe_old = safe_history_key(old_acc)
        safe_new = safe_history_key(new_acc)
        for hf in tmp_path.glob(f"{safe_old}__*.json"):
            target_file = tmp_path / hf.name.replace(f"{safe_old}__", f"{safe_new}__", 1)
            raw = json.loads(hf.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if item.get("account_name") == old_acc:
                        item["account_name"] = new_acc
            hf.write_text(json.dumps(raw), encoding="utf-8")
            hf.rename(target_file)

        # 验证结果
        assert not old_file.exists()
        new_file = history_file_path(tmp_path, task, new_acc)
        assert new_file.exists()
        data = json.loads(new_file.read_text(encoding="utf-8"))
        assert data[0]["account_name"] == new_acc
        assert data[1]["account_name"] == "other_user"

    @pytest.mark.asyncio
    async def test_sse_publish_sign_history_pipeline(self):
        """验证 SSE publish_sign_history 事件发布总线契约。"""
        reset_for_tests()
        assert subscriber_count() == 0

        queue_1 = subscribe()
        queue_2 = subscribe()
        assert subscriber_count() == 2

        entry = {
            "account_name": "bot_alpha",
            "task_name": "lottery",
            "success": True,
            "message": "Win 100 points",
            "created_at": "2026-10-14T12:00:00Z",
            "failure_category": "none",
        }

        publish_sign_history(entry)
        await asyncio.sleep(0.05)

        # 两个订阅者均收到规约后的事件字典
        for q in (queue_1, queue_2):
            assert not q.empty()
            item = q.get_nowait()
            assert item["account_name"] == "bot_alpha"
            assert item["task_name"] == "lottery"
            assert item["success"] is True
            assert item["message"] == "Win 100 points"
            assert item["created_at"] == "2026-10-14T12:00:00Z"
            assert item["failure_category"] == "none"
            assert item["time"] == "2026-10-14T12:00:00Z"

        # 取消订阅
        unsubscribe(queue_1)
        assert subscriber_count() == 1
        reset_for_tests()
        assert subscriber_count() == 0


# ==============================================================================
# Step 2: Plugin SQLite 存量数据样本 (Plugin SQLite Schema & Idempotency)
# ==============================================================================


class TestPluginSqliteBaselines:
    """Plugin KV 存储在 SQLite 上的表结构、PRAGMA、隔离性与原子操作基线。"""

    def test_schema_and_pragma_compliance(self, tmp_path: Path):
        """验证表结构定义与 PRAGMA 生产合规性。"""
        db_file = tmp_path / "plugins.db"
        backend = PluginStorageBackend(db_path=db_file)

        with sqlite3.connect(str(db_file)) as conn:
            # 1. 验证 PRAGMA
            cur = conn.execute("PRAGMA busy_timeout;")
            busy_timeout = cur.fetchone()[0]
            # 后端初始化在连接时配置了 busy_timeout=10000
            assert busy_timeout >= 0

            # 2. 验证主表 schema
            cur = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='plugin_kv'"
            )
            table_sql = cur.fetchone()[0]
            assert "namespace TEXT NOT NULL" in table_sql
            assert "key TEXT NOT NULL" in table_sql
            assert "value TEXT NOT NULL" in table_sql
            assert "expires_at REAL" in table_sql
            assert "PRIMARY KEY (namespace, key)" in table_sql

            # 3. 验证 TTL 索引
            cur = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_plugin_kv_expires'"
            )
            idx_row = cur.fetchone()
            assert idx_row is not None
            assert "expires_at" in idx_row[0]

        backend.close()

    def test_namespace_strict_isolation(self, tmp_path: Path):
        """验证不同插件 / 命名空间之间数据的绝对隔离性。"""
        db_file = tmp_path / "plugins.db"
        backend = PluginStorageBackend(db_path=db_file)

        ns1 = "plugin_checkin:account_1"
        ns2 = "plugin_checkin:account_2"
        ns_global = "global_counters"

        backend.set(ns1, "shared_key", "val_acc1")
        backend.set(ns2, "shared_key", "val_acc2")
        backend.set(ns_global, "shared_key", 999)

        # 读取隔离
        assert backend.get(ns1, "shared_key") == "val_acc1"
        assert backend.get(ns2, "shared_key") == "val_acc2"
        assert backend.get(ns_global, "shared_key") == 999

        # 列出 keys 隔离
        assert backend.keys(ns1) == ["shared_key"]
        assert backend.keys(ns2) == ["shared_key"]

        # 删除隔离
        assert backend.delete(ns1, "shared_key") is True
        assert backend.get(ns1, "shared_key") is None
        assert backend.get(ns2, "shared_key") == "val_acc2"
        assert backend.get(ns_global, "shared_key") == 999

        # 清空单一命名空间
        backend.clear(ns2)
        assert backend.get(ns2, "shared_key") is None
        assert backend.get(ns_global, "shared_key") == 999

        backend.close()

    def test_ttl_expiry_lazy_and_active_purge(self, tmp_path: Path):
        """验证带 TTL 记录的惰性读清理与主动 purge_expired 行为。"""
        db_file = tmp_path / "plugins.db"
        backend = PluginStorageBackend(db_path=db_file)
        ns = "ttl_test"

        # 写入一条永久键与一条短命键
        backend.set(ns, "permanent", "always_here", ttl=None)
        backend.set(ns, "short_lived", "gone_soon", ttl=0.1)

        assert backend.get(ns, "short_lived") == "gone_soon"
        assert backend.get(ns, "permanent") == "always_here"

        # 等待超时
        time.sleep(0.15)

        # 惰性清理：读已过期记录返回 default，并在底层删除
        assert backend.get(ns, "short_lived", default="default_val") == "default_val"

        # 底层验证物理删除
        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "SELECT count(*) FROM plugin_kv WHERE namespace = ? AND key = ?",
                (ns, "short_lived"),
            )
            assert cur.fetchone()[0] == 0

        # 主动批量清理测试
        backend.set(ns, "exp1", 1, ttl=0.05)
        backend.set(ns, "exp2", 2, ttl=0.05)
        time.sleep(0.1)
        purged = backend.purge_expired(namespace=ns)
        assert purged == 2

        backend.close()

    def test_atomic_increment_with_begin_immediate(self, tmp_path: Path):
        """验证 BEGIN IMMEDIATE 保护下的原子递增及 TTL 继承契约。"""
        db_file = tmp_path / "plugins.db"
        backend = PluginStorageBackend(db_path=db_file)
        ns = "counter_ns"

        # 1. 对不存在的键进行递增，初始为 default + delta
        res = backend.increment(ns, "views", delta=5, default=10)
        assert res == 15
        assert backend.get(ns, "views") == 15

        # 2. 再次自增
        res = backend.increment(ns, "views", delta=3)
        assert res == 18
        assert backend.get(ns, "views") == 18

        # 3. 负数递减
        res = backend.increment(ns, "views", delta=-8)
        assert res == 10
        assert backend.get(ns, "views") == 10

        # 4. 带有 TTL 的键进行递增，保留原 TTL
        backend.set(ns, "rate_limit", 1, ttl=10.0)
        backend.increment(ns, "rate_limit", delta=1)
        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "SELECT expires_at FROM plugin_kv WHERE namespace = ? AND key = ?",
                (ns, "rate_limit"),
            )
            exp = cur.fetchone()[0]
            assert exp is not None
            assert exp > time.time()

        backend.close()

    def test_tri_party_idempotency_roundtrip(self, tmp_path: Path):
        """三方幂等性：旧实现写 -> 原生 SQLite 读取验证 -> 原生写入 -> 旧实现读回。"""
        db_file = tmp_path / "plugins.db"
        backend = PluginStorageBackend(db_path=db_file)
        ns = "interop_ns"

        # 1. 旧实现写
        initial_data = {
            "str_key": "hello_pulse",
            "dict_key": {"status": "ok", "retries": 3},
            "int_key": 42,
            "list_key": ["a", "b", "c"],
        }
        for k, v in initial_data.items():
            backend.set(ns, k, v)

        # 2. 原生 SQLite 验证格式与结构
        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "SELECT key, value, expires_at FROM plugin_kv WHERE namespace = ? ORDER BY key",
                (ns,),
            )
            rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            assert json.loads(rows["str_key"][0]) == "hello_pulse"
            assert json.loads(rows["dict_key"][0]) == {"status": "ok", "retries": 3}
            assert json.loads(rows["int_key"][0]) == 42
            assert json.loads(rows["list_key"][0]) == ["a", "b", "c"]

            # 原生写入一条新数据并修改旧数据
            conn.execute(
                "UPDATE plugin_kv SET value = ? WHERE namespace = ? AND key = ?",
                (json.dumps(100), ns, "int_key"),
            )
            conn.execute(
                "INSERT INTO plugin_kv (namespace, key, value, expires_at) VALUES (?, ?, ?, NULL)",
                (ns, "native_key", json.dumps({"source": "native_sql"})),
            )
            conn.commit()

        # 3. 旧实现读回
        assert backend.get(ns, "int_key") == 100
        assert backend.get(ns, "native_key") == {"source": "native_sql"}
        assert backend.get(ns, "str_key") == "hello_pulse"

        # 完整记录拉取 (get_all_records)
        records = backend.get_all_records(ns)
        record_map = {r["key"]: r["value"] for r in records}
        assert record_map["int_key"] == 100
        assert record_map["native_key"] == {"source": "native_sql"}

        backend.close()


# ==============================================================================
# Step 3: 图编译与 IPC 帧样本 (Flow Compilation & IPC Frame Baselines)
# ==============================================================================


class TestFlowAndIpcBaselines:
    """PulseFlow 图编译不变性保证与 IPC 帧契约解析基线。"""

    def test_flow_compilation_non_destructive_input_dict(self):
        """调用方传入的 dict 在多次编译前后严格保持不可变（逐字节相等）。"""
        input_flow_dict: Dict[str, Any] = {
            "entry_node_id": "step_init",
            "nodes": {
                "step_init": {
                    "id": "step_init",
                    "node_type": "action",
                    "action_type": "SEND_TEXT",
                    "params": {"text": "/start", "delay": 1.5},
                    "next_node_id": "step_branch",
                    "retry_policy": {"max_attempts": 2, "backoff_seconds": 1.0},
                    "metadata": {"author": "admin", "tags": ["core", "v4"]},
                },
                "step_branch": {
                    "id": "step_branch",
                    "node_type": "condition",
                    "cases": [
                        {"pattern": "Success", "target_node_id": TERMINAL_COMPLETE_ID}
                    ],
                    "default_target_id": "step_retry",
                },
                "step_retry": {
                    "id": "step_retry",
                    "node_type": "delay",
                    "seconds": 5.0,
                    "next_node_id": "step_init",
                    "loop_policy": {"allow_loop": True, "max_visits": 3},
                },
            },
            "max_total_steps": 25,
        }

        # 捕获编译前的完整序列化快照
        snapshot_before = json.dumps(input_flow_dict, sort_keys=True, ensure_ascii=False)
        dict_copy = copy.deepcopy(input_flow_dict)

        # 第一次编译
        graph_1 = ExecutionGraph.from_dict(input_flow_dict)

        # 检查输入字典未被修改
        snapshot_after_1 = json.dumps(input_flow_dict, sort_keys=True, ensure_ascii=False)
        assert snapshot_before == snapshot_after_1
        assert input_flow_dict == dict_copy

        # 第二次编译
        graph_2 = ExecutionGraph.from_dict(input_flow_dict)
        snapshot_after_2 = json.dumps(input_flow_dict, sort_keys=True, ensure_ascii=False)
        assert snapshot_before == snapshot_after_2

        # 两次编译结果内部完全等价
        assert graph_1.entry_node_id == graph_2.entry_node_id == "step_init"
        assert len(graph_1.nodes) == len(graph_2.nodes) == 3
        assert graph_1.max_total_steps == graph_2.max_total_steps == 25

        node_1 = graph_1.nodes["step_init"]
        assert isinstance(node_1, ActionNode)
        assert node_1.params["text"] == "/start"
        assert node_1.params["delay"] == 1.5
        assert node_1.retry_policy.max_attempts == 2

    def test_flow_normalizer_from_chat_preserves_source(self):
        """GraphNormalizer 从 SignChatV3 编译图时，不修改原始 action/steps 列表。"""
        actions = [
            SendTextAction(text="/checkin", delay="1.0"),
            ClickKeyboardByTextAction(text="Claim Reward", stop_flow_on_terminal=True),
        ]
        chat = SignChatV3(chat_id=987654321, actions=actions)

        # 编译前快照
        orig_actions_len = len(chat.actions)
        orig_action_0_text = chat.actions[0].text

        graph = GraphNormalizer.from_chat(chat)

        # 验证原 chat 保持未被侵入
        assert len(chat.actions) == orig_actions_len
        assert chat.actions[0].text == orig_action_0_text
        assert graph.entry_node_id == "step_0"
        assert len(graph.nodes) == 2
        assert graph.nodes["step_1"].terminal_policy == TerminalPolicy.STOP_FLOW

    def test_ipc_frame_contracts_parsing(self):
        """全量覆盖 IPC 帧解析契约：log, return, call, call_result。"""
        # 1. log 帧
        log_frame = {"type": "log", "message": "processing step 1", "level": "DEBUG"}
        encoded_log = encode_ipc_payload(log_frame)
        assert encoded_log.endswith("\n")
        decoded_log = decode_ipc_payload(encoded_log)
        assert decoded_log["type"] == "log"
        assert decoded_log["message"] == "processing step 1"
        assert decoded_log["level"] == "DEBUG"

        # 2. return 成功帧
        ret_ok_frame = {
            "type": "return",
            "success": True,
            "result": {"signed": True, "token": "xyz"},
        }
        decoded_ret_ok = decode_ipc_payload(encode_ipc_payload(ret_ok_frame))
        assert decoded_ret_ok["type"] == "return"
        assert decoded_ret_ok["success"] is True
        assert decoded_ret_ok["result"]["signed"] is True

        # 3. return 失败帧
        ret_err_frame = {
            "type": "return",
            "success": False,
            "error": "Captcha solve timeout after 30s",
        }
        decoded_ret_err = decode_ipc_payload(encode_ipc_payload(ret_err_frame))
        assert decoded_ret_err["type"] == "return"
        assert decoded_ret_err["success"] is False
        assert "timeout" in decoded_ret_err["error"].lower()

        # 4. call 帧（Worker 发给 Host）
        call_frame = {
            "type": "call",
            "id": 1001,
            "method": "click",
            "params": {"text_or_index": "Confirm"},
        }
        decoded_call = decode_ipc_payload(encode_ipc_payload(call_frame))
        assert decoded_call["type"] == "call"
        assert decoded_call["id"] == 1001
        assert decoded_call["method"] == "click"
        assert decoded_call["params"]["text_or_index"] == "Confirm"

        # 5. call_result 成功帧（Host 返回给 Worker）
        call_res_ok = {
            "type": "call_result",
            "id": 1001,
            "success": True,
            "data": {"clicked": True},
        }
        decoded_res_ok = decode_ipc_payload(encode_ipc_payload(call_res_ok))
        assert decoded_res_ok["type"] == "call_result"
        assert decoded_res_ok["id"] == 1001
        assert decoded_res_ok["success"] is True
        assert decoded_res_ok["data"]["clicked"] is True

        # 6. call_result 失败帧
        call_res_err = {
            "type": "call_result",
            "id": 1001,
            "success": False,
            "error": "Button not found in keyboard markup",
        }
        decoded_res_err = decode_ipc_payload(encode_ipc_payload(call_res_err))
        assert decoded_res_err["type"] == "call_result"
        assert decoded_res_err["id"] == 1001
        assert decoded_res_err["success"] is False
        assert "not found" in decoded_res_err["error"]

    def test_ipc_payload_truncation_contract(self):
        """IPC 管道过长报文截断保护契约。"""
        huge_text = "X" * 25000
        payload = {"type": "log", "message": huge_text}
        encoded = encode_ipc_payload(payload, max_len=1000)
        assert len(encoded) <= 1200
        decoded = decode_ipc_payload(encoded)
        assert decoded["message"].endswith(" ...[truncated]")
        assert len(decoded["message"]) == 1000 + len(" ...[truncated]")

    def test_ipc_corrupt_and_malformed_frames_rejection(self):
        """损坏/异常 IPC 报文的判定与容错契约。"""
        # 非合规 JSON 抛出 JSONDecodeError
        with pytest.raises(json.JSONDecodeError):
            decode_ipc_payload("NOT A JSON STRING\n")

        with pytest.raises(json.JSONDecodeError):
            decode_ipc_payload("")

        # 包含非序列化对象的 encode 回退为 default=str
        unserializable = {
            "type": "error",
            "time": datetime.datetime(2026, 10, 14, 12, 0, 0),
            "err": Exception("custom exc"),
        }
        encoded = encode_ipc_payload(unserializable)
        decoded = decode_ipc_payload(encoded)
        assert "2026-10-14" in decoded["time"]
        assert "custom exc" in decoded["err"]

    @pytest.mark.asyncio
    async def test_proxy_message_and_rpc_interaction_contract(self):
        """Worker 侧 ProxyMessage 与宿主 RPC 交互契约。"""
        mock_rpc = AsyncMock()
        mock_rpc.return_value = {"id": 99, "chat": {"id": 123}, "text": "echoed"}

        serialized_msg = {
            "id": 88,
            "text": "Hello bot",
            "chat": {"id": 123, "title": "Group A", "type": "supergroup"},
            "from_user": {"id": 456, "username": "alice"},
            "buttons": [[{"text": "Btn 1", "data": "cb_1"}]],
        }

        proxy = ProxyMessage(serialized_msg, rpc=mock_rpc)
        assert proxy.id == 88
        assert proxy.text == "Hello bot"
        assert proxy.chat.id == 123
        assert proxy.from_user.username == "alice"
        assert len(proxy.buttons) == 1
        assert proxy.buttons[0][0].text == "Btn 1"
        assert proxy.buttons[0][0].data == "cb_1"

        # 调用 reply
        reply_res = await proxy.reply("Hello back")
        mock_rpc.assert_called_once_with(
            "reply", text="Hello back", reply_to_message_id=88
        )
        assert isinstance(reply_res, ProxyMessage)
        assert reply_res.id == 99
        assert reply_res.text == "echoed"
