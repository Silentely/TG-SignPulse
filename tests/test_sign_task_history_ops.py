"""
backend/services/sign_task_history_ops.py 单元测试

覆盖 SignTaskHistoryMixin 的落盘主路径：
- _save_run_info：写历史文件 / 失败分类 / 保留条数截断 / 任务配置 last_run 回写 /
  内存缓存更新 / 轻量索引追加 / 损坏历史容错
- _set_task_last_run_metadata：配置回写与缓存同步

背景：sign_task_runner 侧对 _save_run_info 使用 FakeSvc 替身，
导致真实落盘路径（曾含 write_json_atomic 未导入的 F821 潜伏 bug）长期无覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.sign_task_history_io import history_file_path
from backend.services.sign_task_history_ops import SignTaskHistoryMixin


class _StubHistoryService(SignTaskHistoryMixin):
    """仅提供 _save_run_info 依赖的宿主属性/方法的替身。"""

    def __init__(self, base_dir: Path):
        self.run_history_dir = base_dir / "history"
        self.signs_dir = base_dir / "signs"
        self._repair_mojibake = lambda s: s
        self._history_max_flow_lines = 500
        self._history_max_line_chars = 3000
        self._history_max_entries = 20
        self._tasks_cache: List[Dict[str, Any]] = []
        self._task_configs: Dict[tuple, Optional[Dict[str, Any]]] = {}
        self._known_tasks: List[Dict[str, Any]] = []

    def register_task(self, task_name: str, account_name: str) -> None:
        """登记一个已知任务，供 clear_account_history_logs 枚举。"""
        self._known_tasks.append({"name": task_name, "account_name": account_name})

    def list_tasks(self, account_name: str = ""):
        if account_name:
            return [
                t for t in self._known_tasks if t.get("account_name") == account_name
            ]
        return list(self._known_tasks)

    def get_task(self, task_name: str, account_name: str = ""):
        return self._task_configs.get((task_name, account_name))

    def _resolve_task_dir(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Path]:
        if account_name:
            account_task_dir = self.signs_dir / account_name / task_name
            if (account_task_dir / "config.json").exists():
                return account_task_dir
        legacy_task_dir = self.signs_dir / task_name
        if (legacy_task_dir / "config.json").exists():
            return legacy_task_dir
        return None

    def _history_file_path(self, task_name: str, account_name: str = "") -> Path:
        return history_file_path(self.run_history_dir, task_name, account_name)

    def _sync_tasks_list_ttl(self) -> None:
        return None


def _make_service(tmp_path: Path) -> _StubHistoryService:
    svc = _StubHistoryService(tmp_path)
    return svc


def _read_history(svc: _StubHistoryService, task: str, account: str = "") -> List[dict]:
    path = svc._history_file_path(task, account)
    assert path.exists(), f"历史文件未生成: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_save_run_info_writes_history_and_index(tmp_path: Path):
    """成功路径：历史文件、索引、内存缓存三处同时落盘。"""
    svc = _make_service(tmp_path)
    svc._tasks_cache = [{"name": "t1", "account_name": "acc", "last_run": None}]

    svc._save_run_info(
        "t1",
        success=True,
        message="签到完成",
        account_name="acc",
        flow_logs=["开始执行", "发送消息成功"],
    )

    history = _read_history(svc, "t1", "acc")
    assert len(history) == 1
    entry = history[0]
    assert entry["success"] is True
    assert entry["message"] == "签到完成"
    assert entry["account_name"] == "acc"
    assert entry["flow_logs"] == ["开始执行", "发送消息成功"]
    assert entry["failure_category"] == "none"

    # 轻量索引追加（SSE / 最近日志 O(1) 读取依赖）
    index_file = svc.run_history_dir / "_recent_index.jsonl"
    assert index_file.exists()
    lines = index_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    index_entry = json.loads(lines[0])
    assert index_entry["task_name"] == "t1"
    assert index_entry["account_name"] == "acc"
    assert index_entry["success"] is True

    # 内存任务缓存 last_run 已就地更新
    assert svc._tasks_cache[0]["last_run"] is not None
    assert svc._tasks_cache[0]["last_run"]["success"] is True


def test_save_run_info_failure_classified(tmp_path: Path):
    """失败路径：按消息归类 failure_category 并写入。"""
    svc = _make_service(tmp_path)

    svc._save_run_info(
        "t1",
        success=False,
        message="任务执行出错: 账号已注销",
        account_name="acc",
    )

    entry = _read_history(svc, "t1", "acc")[0]
    assert entry["success"] is False
    assert entry["failure_category"]


def test_save_run_info_appends_and_truncates(tmp_path: Path):
    """多次落盘：新记录置顶且总条数不超过 _history_max_entries。"""
    svc = _make_service(tmp_path)
    svc._history_max_entries = 3

    for i in range(5):
        svc._save_run_info("t1", success=True, message=f"第 {i} 次", account_name="acc")

    history = _read_history(svc, "t1", "acc")
    assert len(history) == 3
    assert history[0]["message"] == "第 4 次"
    assert history[-1]["message"] == "第 2 次"


def test_save_run_info_updates_task_config_last_run(tmp_path: Path):
    """任务配置存在时：config.json 的 last_run 同步回写。"""
    svc = _make_service(tmp_path)
    task_dir = svc.signs_dir / "acc" / "t1"
    task_dir.mkdir(parents=True)
    config_file = task_dir / "config.json"
    config_file.write_text(json.dumps({"name": "t1"}), encoding="utf-8")
    svc._task_configs[("t1", "acc")] = {"name": "t1"}

    svc._save_run_info("t1", success=True, message="ok", account_name="acc")

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    assert config["last_run"]["success"] is True


def test_save_run_info_corrupt_history_recovers(tmp_path: Path):
    """历史文件损坏（非法 JSON）：告警后丢弃旧数据并正常写入新记录。"""
    svc = _make_service(tmp_path)
    history_file = svc._history_file_path("t1", "acc")
    history_file.parent.mkdir(parents=True)
    history_file.write_text("{ 这不是合法 JSON", encoding="utf-8")

    svc._save_run_info("t1", success=True, message="恢复后写入", account_name="acc")

    history = _read_history(svc, "t1", "acc")
    assert len(history) == 1
    assert history[0]["message"] == "恢复后写入"


def test_set_task_last_run_metadata_updates_cache_and_config(tmp_path: Path):
    """_set_task_last_run_metadata：配置文件与内存缓存同步，last_run 为空时清除。"""
    svc = _make_service(tmp_path)
    task_dir = svc.signs_dir / "acc" / "t1"
    task_dir.mkdir(parents=True)
    config_file = task_dir / "config.json"
    config_file.write_text(
        json.dumps({"name": "t1", "last_run": {"success": True}}), encoding="utf-8"
    )
    svc._tasks_cache = [
        {"name": "t1", "account_name": "acc", "last_run": {"success": True}}
    ]

    # 写入新 last_run
    svc._set_task_last_run_metadata(
        "t1", account_name="acc", last_run={"success": False, "message": "新记录"}
    )
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    assert config["last_run"]["success"] is False
    assert svc._tasks_cache[0]["last_run"]["message"] == "新记录"

    # last_run=None 时清除两处
    svc._set_task_last_run_metadata("t1", account_name="acc", last_run=None)
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    assert "last_run" not in config
    assert "last_run" not in svc._tasks_cache[0]


def test_save_run_info_no_account_single_file(tmp_path: Path):
    """无账号名时历史文件落在单任务文件名（历史兼容布局）。"""
    svc = _make_service(tmp_path)
    svc._save_run_info("t1", success=True, message="ok")
    history = _read_history(svc, "t1")
    assert history[0]["account_name"] == ""


class TestHistoryAccountIsolation:
    """历史文件名必须单射，清账号历史不得误删其他账号的数据。"""

    def _seed(self, svc: _StubHistoryService, task: str, account: str, message: str):
        svc.register_task(task, account)
        svc._save_run_info(
            task,
            success=True,
            message=message,
            account_name=account,
            flow_logs=["ok"],
        )

    def test_colliding_names_get_distinct_files(self, tmp_path: Path):
        """(a__b, c) 与 (a, b__c) 曾撞到同一文件名，现在必须分开。"""
        svc = _make_service(tmp_path)
        self._seed(svc, "c", "a__b", "first")
        self._seed(svc, "b__c", "a", "second")

        left = svc._history_file_path("c", "a__b")
        right = svc._history_file_path("b__c", "a")
        assert left != right
        assert left.exists() and right.exists()
        assert len(_read_history(svc, "c", "a__b")) == 1
        assert len(_read_history(svc, "b__c", "a")) == 1

    def test_clear_account_does_not_touch_similarly_named_account(self, tmp_path: Path):
        """清账号 a 的历史时，账号 a__b 的数据必须完好。"""
        svc = _make_service(tmp_path)
        self._seed(svc, "t", "a", "mine")
        self._seed(svc, "t", "a__b", "theirs")

        result = svc.clear_account_history_logs("a")

        assert result["removed_entries"] >= 1
        # 账号 a 的历史已清
        assert not svc._history_file_path("t", "a").exists()
        # 账号 a__b 的历史必须保留
        assert svc._history_file_path("t", "a__b").exists()
        kept = _read_history(svc, "t", "a__b")
        assert len(kept) == 1
        assert kept[0]["message"] == "theirs"

    def test_clear_account_only_unlinks_when_all_entries_belong_to_it(
        self, tmp_path: Path
    ):
        """文件里混有其他账号条目时不得整文件删除，只移除属于该账号的条目。"""
        svc = _make_service(tmp_path)
        svc.register_task("t", "a")
        shared = svc._history_file_path("t", "a")
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text(
            json.dumps(
                [
                    {"time": "2026-01-01T00:00:00Z", "account_name": "a"},
                    {"time": "2026-01-02T00:00:00Z", "account_name": "b"},
                ]
            ),
            encoding="utf-8",
        )

        svc.clear_account_history_logs("a")

        assert shared.exists(), "混有他人条目的文件不得整文件删除"
        kept = _read_history(svc, "t", "a")
        assert [e["account_name"] for e in kept] == ["b"]

    def test_delete_history_log_respects_owner(self, tmp_path: Path):
        """删除单条历史时，无 account_name 的旧格式条目仅宿主账号可删。"""
        svc = _make_service(tmp_path)
        target = svc._history_file_path("t", "a")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                [
                    {"time": "2026-01-02T00:00:00Z", "account_name": "a"},
                    {"time": "2026-01-01T00:00:00Z"},
                ]
            ),
            encoding="utf-8",
        )

        assert svc.delete_history_log("a", "t", "2026-01-02T00:00:00Z") is True
        kept = _read_history(svc, "t", "a")
        assert [e["time"] for e in kept] == ["2026-01-01T00:00:00Z"]

        # 非宿主账号请求删除该文件中的旧格式条目必须失败
        assert svc.delete_history_log("other", "t", "2026-01-01T00:00:00Z") is False


class TestLegacyHistoryMigration:
    """升级前编码路径（未转义 _ / %）的历史在回写后必须仍然可见。"""

    def _seed_legacy(
        self, svc: _StubHistoryService, task: str, account: str, message: str
    ):
        from backend.services.sign_task_history_io import legacy_history_file_path

        legacy = legacy_history_file_path(svc.run_history_dir, task, account)
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps(
                [
                    {
                        "time": "2026-09-01T00:00:00Z",
                        "account_name": account,
                        "message": message,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return legacy

    def test_save_run_info_migrates_legacy_file(self, tmp_path: Path):
        """名称含 "_" 时新旧文件名不同，回写先迁移，旧条目不得被新文件顶掉。"""
        svc = _make_service(tmp_path)
        legacy = self._seed_legacy(svc, "daily_task", "acct_1", "old")

        svc._save_run_info(
            "daily_task", success=True, message="new", account_name="acct_1"
        )

        history = _read_history(svc, "daily_task", "acct_1")
        assert [e["message"] for e in history] == ["new", "old"]
        assert not legacy.exists()

    def test_get_last_run_info_reads_legacy_file(self, tmp_path: Path):
        """last_run 读取需兼容旧编码路径，否则面板显示为「从未运行」。"""
        svc = _make_service(tmp_path)
        self._seed_legacy(svc, "daily_task", "acct_1", "old")
        task_dir = svc.signs_dir / "acct_1" / "daily_task"
        task_dir.mkdir(parents=True, exist_ok=True)

        info = svc._get_last_run_info(task_dir, account_name="acct_1")

        assert info is not None
        assert info["message"] == "old"

    def test_clear_account_history_removes_legacy_file(self, tmp_path: Path):
        """清账号历史必须覆盖旧编码的账号维度文件，否则孤儿历史残留在磁盘。"""
        svc = _make_service(tmp_path)
        svc.register_task("daily_task", "acct_1")
        legacy = self._seed_legacy(svc, "daily_task", "acct_1", "old")

        svc.clear_account_history_logs("acct_1")

        assert not legacy.exists()
