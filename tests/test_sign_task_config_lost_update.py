"""config.json 并发写丢失更新测试。

两个线程各自 read→mutate→write 同一 config.json 时，若无跨序列的路径锁，
后写者会用自己读到的旧快照覆盖先写者的字段。用 threading.Event 做确定性交错，
断言两项更改都存活。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from backend.utils.atomic_io import path_write_lock, read_json_safe, write_json_atomic


class TestPathWriteLock:
    def test_same_path_returns_same_lock(self, tmp_path: Path):
        p = tmp_path / "config.json"
        p.write_text("{}")
        assert path_write_lock(p) is path_write_lock(p)
        # 相对/绝对路径与是否存在都应归一到同一把锁
        assert path_write_lock(tmp_path / "sub" / ".." / "config.json") is path_write_lock(p)

    def test_different_paths_get_different_locks(self, tmp_path: Path):
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text("{}")
        b.write_text("{}")
        assert path_write_lock(a) is not path_write_lock(b)

    def test_lock_is_reentrant(self, tmp_path: Path):
        p = tmp_path / "config.json"
        p.write_text("{}")
        lock = path_write_lock(p)
        with lock:
            with lock:
                pass

    def test_lock_serializes_cross_thread_writes(self, tmp_path: Path):
        """两线程竞争同一路径时，锁保证写互不穿插。"""
        p = tmp_path / "config.json"
        write_json_atomic(p, {"n": 0})

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            for _ in range(20):
                with path_write_lock(p):
                    data = read_json_safe(p, default={}) or {}
                    data["n"] = data.get("n", 0) + 1
                    write_json_atomic(p, data)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert read_json_safe(p, default={})["n"] == 40


class TestNoLostUpdate:
    """确定性交错：证明无锁时会丢失更新，持锁时各项更改都存活。

    无锁场景用事件把时序钉死（第一方读完 → 第二方写完 → 第一方写回），
    复现「后写者用旧快照覆盖先写者」的缺陷；持锁场景改为并发各写一个字段，
    由路径锁串行化，断言两项更改都存活。
    """

    @pytest.fixture
    def config_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "config.json"
        write_json_atomic(p, {"name": "task", "sign_at": "08:00", "jitter_seconds": 0})
        return p

    def test_without_lock_second_write_is_lost(self, config_file):
        """无锁时第二方的更改被第一方的旧快照覆盖（复现缺陷）。"""
        first_read = threading.Event()
        second_done = threading.Event()

        def first():
            data = read_json_safe(config_file, default={}) or {}
            first_read.set()
            second_done.wait(timeout=10)
            data["jitter_seconds"] = 30
            write_json_atomic(config_file, data)

        def second():
            first_read.wait(timeout=10)
            data = read_json_safe(config_file, default={}) or {}
            data["sign_at"] = "09:00"
            write_json_atomic(config_file, data)
            second_done.set()

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()
        t1.join(timeout=20)
        t2.join(timeout=20)
        assert not t1.is_alive() and not t2.is_alive()

        result = read_json_safe(config_file, default={}) or {}
        assert result["jitter_seconds"] == 30
        assert result["sign_at"] == "08:00", "预期复现丢失更新：第二方的更改被覆盖"

    def test_with_lock_both_changes_survive(self, config_file):
        """持路径锁并发读-改-写不同字段时，两项更改都存活。"""
        barrier = threading.Barrier(2)

        def write_field(field: str, value):
            barrier.wait()
            with path_write_lock(config_file):
                data = read_json_safe(config_file, default={}) or {}
                data[field] = value
                write_json_atomic(config_file, data)

        threads = [
            threading.Thread(target=write_field, args=("sign_at", "09:00")),
            threading.Thread(target=write_field, args=("jitter_seconds", 30)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        assert not any(t.is_alive() for t in threads)

        result = read_json_safe(config_file, default={}) or {}
        assert result["sign_at"] == "09:00"
        assert result["jitter_seconds"] == 30
        assert result["name"] == "task"

    def test_concurrent_locked_updates_all_survive(self, tmp_path: Path):
        """多线程并发持锁读-改-写时，每次自增都不丢。"""
        p = tmp_path / "config.json"
        write_json_atomic(p, {"n": 0})

        workers = 4
        rounds = 15
        barrier = threading.Barrier(workers)

        def worker():
            barrier.wait()
            for _ in range(rounds):
                with path_write_lock(p):
                    data = read_json_safe(p, default={}) or {}
                    data["n"] = data.get("n", 0) + 1
                    write_json_atomic(p, data)

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert read_json_safe(p, default={})["n"] == workers * rounds


class TestSignTaskMetadataUsesLock:
    """_set_task_last_run_metadata 的读-改-写必须在路径锁内。"""

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
        from backend.core import config as config_module
        from backend.services import sign_tasks as sign_tasks_module
        from backend.services.sign_tasks import get_sign_task_service

        config_module.get_settings.cache_clear()
        # 服务是进程内单例：先清掉，避免复用其他用例绑定过的 data_dir
        monkeypatch.setattr(sign_tasks_module, "_sign_task_service", None)
        svc = get_sign_task_service()
        svc.invalidate_tasks_cache()
        return svc

    def _create_task(self, svc, monkeypatch):
        import backend.services.sign_tasks as st_module

        monkeypatch.setattr(st_module, "list_account_names", lambda: ["acc1"])
        svc.create_task(
            task_name="t",
            sign_at="08:00",
            chats=[],
            account_name="acc1",
            account_names=["acc1"],
        )
        return svc.signs_dir / "acc1" / "t" / "config.json"

    def test_metadata_write_blocks_while_lock_held(self, service, monkeypatch):
        """他人持锁期间 _set_task_last_run_metadata 必须阻塞，证明它走了路径锁。"""
        config_file = self._create_task(service, monkeypatch)
        lock = path_write_lock(config_file)

        held = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def holder():
            with lock:
                held.set()
                release.wait(timeout=10)

        def writer():
            held.wait(timeout=10)
            service._set_task_last_run_metadata(
                "t", "acc1", {"time": "2026-09-28T08:00:00Z", "success": True}
            )
            finished.set()

        t_hold = threading.Thread(target=holder)
        t_write = threading.Thread(target=writer)
        t_hold.start()
        t_write.start()

        held.wait(timeout=10)
        # 锁仍被持有：写入方必须还在等待，不能提前完成
        assert finished.wait(timeout=0.5) is False, "写入未受路径锁保护"

        release.set()
        t_hold.join(timeout=10)
        t_write.join(timeout=10)
        assert not t_hold.is_alive() and not t_write.is_alive()

        stored = json.loads(config_file.read_text(encoding="utf-8"))
        assert stored["last_run"]["time"] == "2026-09-28T08:00:00Z"

    def test_metadata_write_does_not_clobber_concurrent_field(self, service, monkeypatch):
        """并发字段写与 last_run 回写都存活（无丢失更新）。"""
        config_file = self._create_task(service, monkeypatch)
        barrier = threading.Barrier(2)

        def metadata_writer():
            barrier.wait()
            service._set_task_last_run_metadata(
                "t", "acc1", {"time": "2026-09-28T08:00:00Z", "success": True}
            )

        def field_writer():
            barrier.wait()
            with path_write_lock(config_file):
                data = read_json_safe(config_file, default={}) or {}
                data["sign_at"] = "10:00"
                write_json_atomic(config_file, data)

        threads = [
            threading.Thread(target=metadata_writer),
            threading.Thread(target=field_writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        assert not any(t.is_alive() for t in threads)

        stored = json.loads(config_file.read_text(encoding="utf-8"))
        assert stored["sign_at"] == "10:00"
        assert stored["last_run"]["time"] == "2026-09-28T08:00:00Z"
