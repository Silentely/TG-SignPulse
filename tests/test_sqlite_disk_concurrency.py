"""
Task 10: Real-Disk SQLite WAL Multi-Connection Concurrency Suite.

Verifies:
1. Reproduction: Multi-connection concurrent writes to a disk SQLite database without
   busy timeout / WAL under heavy contention fail with sqlite3.OperationalError (database is locked).
2. Resolution: With WAL mode, synchronous=NORMAL, and busy_timeout=15000 (standard in backend/core/database.py),
   high concurrent transactions across multiple threads execute with 100% success and 0 locks.
"""

import concurrent.futures
import os
import sqlite3
import tempfile
import time

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker


def test_reproduce_disk_concurrency_lock():
    """
    Step 1 & 2: Baseline reproduction (deterministic).

    Using standard rollback journal (DELETE) and 0s busy timeout, a second
    connection attempting BEGIN EXCLUSIVE while another connection holds an
    exclusive write lock must fail with 'database is locked'.

    说明：早期版本用 16 线程 + barrier 制造并发冲突，依赖线程调度时机，
    在高负载全量套件下锁冲突未必发生（flaky）。改为单连接持锁 +
    零超时连接撞锁的确定性复现，结果与负载无关。
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Initialize schema
        init_conn = sqlite3.connect(db_path)
        init_conn.execute("PRAGMA journal_mode=DELETE")
        init_conn.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, val INTEGER)")
        init_conn.execute("INSERT INTO counter VALUES (1, 0)")
        init_conn.commit()
        init_conn.close()

        # Holder 持 EXCLUSIVE 写锁，模拟并发写方占锁
        holder = sqlite3.connect(db_path, timeout=15)
        holder.execute("PRAGMA journal_mode=DELETE")
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("UPDATE counter SET val = val + 1 WHERE id=1")

        # timeout=0.0 的连接在锁被占用时立即失败
        blocked = sqlite3.connect(db_path, timeout=0.0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                blocked.execute("BEGIN EXCLUSIVE")
                blocked.execute("UPDATE counter SET val = val + 1 WHERE id=1")
                blocked.commit()
        finally:
            blocked.close()

        holder.rollback()
        holder.close()

        # 收尾验证：持有锁回滚后，普通连接可正常读写
        check = sqlite3.connect(db_path, timeout=15)
        try:
            check.execute("BEGIN")
            check.execute("UPDATE counter SET val = val + 1 WHERE id=1")
            check.commit()
            val = check.execute("SELECT val FROM counter WHERE id=1").fetchone()[0]
            assert val == 1
        finally:
            check.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_sqlite_wal_and_busy_timeout_stress_suite():
    """
    Step 3 & 4: Production configuration stress test.
    Applies the engine configuration from backend/core/database.py:
    - journal_mode=WAL
    - synchronous=NORMAL
    - busy_timeout=15000 (via connect_args timeout=15)
    Runs 16 concurrent threads performing 10 transactions each (160 total transactions).
    Asserts 100% success rate with exactly 160 updates committed.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 15},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE test_data (id INTEGER PRIMARY KEY, counter INTEGER)")
            )
            conn.execute(text("INSERT INTO test_data (id, counter) VALUES (1, 0)"))

        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        num_threads = 16
        tx_per_thread = 10
        errors = []

        def worker_task(thread_id: int):
            for _ in range(tx_per_thread):
                session = SessionLocal()
                try:
                    # Retry loop inside session if needed, but with WAL + 15s timeout, standard commit succeeds
                    with session.begin():
                        _ = session.execute(
                            text("SELECT counter FROM test_data WHERE id=1")
                        ).scalar()
                        # Small delay to simulate app work
                        time.sleep(0.002)
                        session.execute(
                            text(
                                "UPDATE test_data SET counter = counter + 1 WHERE id=1"
                            )
                        )
                except Exception as exc:
                    errors.append((thread_id, str(exc)))
                finally:
                    session.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Encountered unexpected transaction errors: {errors}"

        # Verify final state matches exactly the total operations
        with engine.connect() as conn:
            final_count = conn.execute(
                text("SELECT counter FROM test_data WHERE id=1")
            ).scalar()
            assert final_count == num_threads * tx_per_thread

            # Verify WAL journal mode is active
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert str(mode).lower() == "wal"

        engine.dispose()
    finally:
        for ext in ["", "-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
