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
import threading
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker


def test_reproduce_disk_concurrency_lock():
    """
    Step 1 & 2: Baseline reproduction.
    Using standard rollback journal (DELETE) and 0s busy timeout, concurrent threads
    performing exclusive transactions synchronized by a barrier against a disk file
    will reliably encounter 'database is locked'.
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

        num_threads = 16
        barrier = threading.Barrier(num_threads)
        lock_errors = []

        def worker(w_id: int):
            barrier.wait()
            try:
                # timeout=0.0 to force immediate failure if lock is held
                conn = sqlite3.connect(db_path, timeout=0.0)
                for _ in range(5):
                    conn.execute("BEGIN EXCLUSIVE")
                    cur = conn.execute("SELECT val FROM counter WHERE id=1")
                    val = cur.fetchone()[0]
                    time.sleep(0.01)  # hold write lock to guarantee collision
                    conn.execute("UPDATE counter SET val=? WHERE id=1", (val + 1,))
                    conn.commit()
                conn.close()
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    lock_errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least one thread should have encountered 'database is locked'
        assert len(lock_errors) > 0, "Expected lock contention under zero busy_timeout and DELETE journal"
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
            conn.execute(text("CREATE TABLE test_data (id INTEGER PRIMARY KEY, counter INTEGER)"))
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
                            text("UPDATE test_data SET counter = counter + 1 WHERE id=1")
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
            final_count = conn.execute(text("SELECT counter FROM test_data WHERE id=1")).scalar()
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
