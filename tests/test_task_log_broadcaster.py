import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.services.sign_tasks import get_sign_task_service
from backend.services.stream_tickets import (
    PURPOSE_TASK_RUN_WS,
    get_stream_ticket_store,
)
from backend.services.task_log_broadcaster import (
    StreamKey,
    TaskLogBroadcaster,
    get_task_log_broadcaster,
    set_task_log_broadcaster,
)


@pytest.mark.asyncio
async def test_task_log_broadcaster_isolation_and_replay():
    broadcaster = TaskLogBroadcaster(max_queue_size=2)
    key_main = StreamKey(account_name="acc1", task_name="task1", run_id="r1")
    key_diff_acc = StreamKey(account_name="acc2", task_name="task1", run_id="r1")
    key_diff_task = StreamKey(account_name="acc1", task_name="task2", run_id="r1")
    key_diff_run = StreamKey(account_name="acc1", task_name="task1", run_id="r2")

    q_main = broadcaster.subscribe(key_main)
    q_diff_acc = broadcaster.subscribe(key_diff_acc)
    q_diff_task = broadcaster.subscribe(key_diff_task)
    q_diff_run = broadcaster.subscribe(key_diff_run)

    # Publish to main key
    await broadcaster.publish(key_main, {"seq": 1, "text": "log 1"})
    await broadcaster.publish(key_main, {"seq": 2, "text": "log 2"})
    await broadcaster.publish(
        key_main, {"seq": 3, "text": "log 3"}
    )  # triggers drop in q_main

    # Triplet isolation verification
    assert q_diff_acc.empty(), "Leaked to different account!"
    assert q_diff_task.empty(), "Leaked to different task!"
    assert q_diff_run.empty(), "Leaked to different run_id!"

    # Dropped count verification
    assert broadcaster.get_dropped_count(key_main, q_main) == 1

    # Snapshot replay verification with after_seq
    q_replay = broadcaster.subscribe(key_main, after_seq=1)
    e_replay = await q_replay.get()
    assert e_replay["seq"] == 2

    broadcaster.unsubscribe(key_main, q_main)
    broadcaster.unsubscribe(key_main, q_replay)
    assert not broadcaster.has_subscribers(key_main)


@pytest.mark.asyncio
async def test_task_log_broadcaster_backpressure_drop_oldest():
    broadcaster = TaskLogBroadcaster(max_queue_size=3)
    key = StreamKey(account_name="test_acc", task_name="test_task", run_id="run_123")
    queue = broadcaster.subscribe(key)

    for i in range(1, 7):
        await broadcaster.publish(key, {"seq": i, "text": f"line {i}"})

    assert broadcaster.get_dropped_count(key, queue) == 3

    # Remaining items in queue should be the newest 3: 4, 5, 6
    items = []
    while not queue.empty():
        items.append(await queue.get())

    assert len(items) == 3
    assert [it["seq"] for it in items] == [4, 5, 6]


@pytest.mark.asyncio
async def test_task_log_broadcaster_does_not_exceed_history_stream_cap():
    broadcaster = TaskLogBroadcaster(max_streams=2)
    active_keys = [
        StreamKey(account_name="acc", task_name=f"task-{i}", run_id="run")
        for i in range(3)
    ]
    queues = [broadcaster.subscribe(key) for key in active_keys]

    for index, key in enumerate(active_keys):
        await broadcaster.publish(key, {"text": f"line-{index}"})

    assert len(broadcaster._history) == 2
    assert not broadcaster._history.get(active_keys[2])

    for key, queue in zip(active_keys, queues, strict=True):
        broadcaster.unsubscribe(key, queue)


@pytest.mark.asyncio
async def test_task_log_broadcaster_terminal_event_and_cleanup():
    broadcaster = TaskLogBroadcaster(max_queue_size=10)
    key = StreamKey(account_name="acc", task_name="task", run_id="r1")
    queue = broadcaster.subscribe(key)

    await broadcaster.publish(key, {"type": "logs", "text": "hello"})
    await broadcaster.publish_done(key, {"type": "done", "state": "success"})

    item1 = await queue.get()
    assert item1["type"] == "logs"
    item2 = await queue.get()
    assert item2["type"] == "done"
    assert item2["state"] == "success"

    broadcaster.unsubscribe(key, queue)
    assert not broadcaster.has_subscribers(key)
    assert broadcaster.get_dropped_count(key, queue) == 0


@pytest.mark.asyncio
async def test_task_log_broadcaster_singleton():
    orig = get_task_log_broadcaster()
    try:
        custom = TaskLogBroadcaster(max_queue_size=5)
        set_task_log_broadcaster(custom)
        assert get_task_log_broadcaster() is custom
    finally:
        set_task_log_broadcaster(orig)


@pytest.mark.asyncio
async def test_sign_task_service_append_active_log_publishes_event():
    svc = get_sign_task_service()
    broadcaster = get_task_log_broadcaster()

    task_key = ("my_account", "my_task")
    run_id = "run_abc"
    svc._set_run_status("my_account", "my_task", run_id=run_id, state="running")

    stream_key = StreamKey(
        account_name="my_account", task_name="my_task", run_id=run_id
    )
    queue = broadcaster.subscribe(stream_key)

    try:
        svc._append_active_log(task_key, "Test log message from runner")
        assert not queue.empty()
        event = await queue.get()
        assert event["type"] == "logs"
        assert "Test log message from runner" in event["data"]
        assert event["run_id"] == run_id

        # Terminal status transition
        svc._set_run_status("my_account", "my_task", run_id=run_id, state="success")
        assert not queue.empty()
        done_event = await queue.get()
        assert done_event["type"] == "done"
        assert done_event["state"] == "success"
    finally:
        broadcaster.unsubscribe(stream_key, queue)


def test_sign_task_logs_ws_unauthorized():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/sign-tasks/ws/test_task?ticket=invalid_ticket"
        ):
            pass
    assert exc_info.value.code == 1008


def test_sign_task_logs_ws_streaming_and_disconnect():
    client = TestClient(app)
    ticket_store = get_stream_ticket_store()
    task_name = "ws_test_task"
    account_name = "ws_test_account"
    run_id = "ws_run_1"

    svc = get_sign_task_service()
    svc._set_run_status(account_name, task_name, run_id=run_id, state="running")

    ticket = ticket_store.issue(
        user_id=1,
        username="admin",
        purpose=PURPOSE_TASK_RUN_WS,
        resource=task_name,
    )

    broadcaster = get_task_log_broadcaster()
    stream_key = StreamKey(
        account_name=account_name, task_name=task_name, run_id=run_id
    )

    url = f"/api/sign-tasks/ws/{task_name}?ticket={ticket}&account_name={account_name}&run_id={run_id}"
    with client.websocket_connect(url) as ws:
        # Broadcaster should now have a subscriber
        assert broadcaster.has_subscribers(stream_key)

        # Emit log
        svc._append_active_log((account_name, task_name), "WS live line 1")
        msg = ws.receive_json()
        assert msg["type"] == "logs"
        assert "WS live line 1" in msg["data"]

        # Emit second log
        svc._append_active_log((account_name, task_name), "WS live line 2")
        msg2 = ws.receive_json()
        assert msg2["type"] == "logs"
        assert "WS live line 2" in msg2["data"]

        # Finish task
        svc._set_run_status(account_name, task_name, run_id=run_id, state="success")
        done_msg = ws.receive_json()
        assert done_msg["type"] == "done"
        assert done_msg["state"] == "success"

    # After websocket closes, subscriber should be cleaned up
    assert not broadcaster.has_subscribers(stream_key)


def test_task_log_handler_sink_publishes_real_execution_logs():
    """TaskLogHandler 经 sink 走 _append_active_log，执行日志必须进广播器。

    回归：早期 TaskLogHandler.emit 直接 append 列表，绕过广播器，
    导致 WebSocket 实时流只推编排日志、拿不到真正的执行日志。
    """
    import logging

    from backend.services.sign_task_backend import TaskLogHandler

    svc = get_sign_task_service()
    broadcaster = get_task_log_broadcaster()
    task_key = ("sink_acc", "sink_task")
    run_id = "sink_run"
    svc._active_logs[task_key] = []
    svc._set_run_status("sink_acc", "sink_task", run_id=run_id, state="running")

    stream_key = StreamKey(
        account_name="sink_acc", task_name="sink_task", run_id=run_id
    )
    queue = broadcaster.subscribe(stream_key)
    logger = logging.getLogger("tg-signer-sink-test")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = TaskLogHandler(
        svc._active_logs[task_key],
        max_lines=2000,
        sink=lambda line: svc._append_active_log(task_key, line, run_id),
    )
    logger.addHandler(handler)
    try:
        logger.info("real execution log via sink")
    finally:
        logger.removeHandler(handler)

    try:
        assert svc._active_logs[task_key][-1] == "real execution log via sink"
        assert not queue.empty(), "handler 日志未进入广播器"
        event = queue.get_nowait()
        assert event["type"] == "logs"
        assert "real execution log via sink" in event["data"]
        assert event["run_id"] == run_id
    finally:
        broadcaster.unsubscribe(stream_key, queue)


def test_task_log_handler_without_sink_keeps_legacy_list_behavior():
    """未传 sink 时保持旧行为：仅写入列表，供既有调用方使用。"""
    import logging

    from backend.services.sign_task_backend import TaskLogHandler

    logs: list[str] = []
    logger = logging.getLogger("tg-signer-legacy-test")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = TaskLogHandler(logs, max_lines=2)
    logger.addHandler(handler)
    try:
        logger.info("l1")
        logger.info("l2")
        logger.info("l3")
    finally:
        logger.removeHandler(handler)

    assert len(logs) == 2
    assert logs[-1] == "l3"


@pytest.mark.asyncio
async def test_publish_from_worker_thread_delivers_to_subscriber():
    """跨线程发布（如同步取消路由走 threadpool）必须投递到订阅队列。"""
    import threading

    broadcaster = TaskLogBroadcaster(max_queue_size=10)
    key = StreamKey(account_name="thr_acc", task_name="thr_task", run_id="thr_run")
    queue = broadcaster.subscribe(key)

    done = threading.Event()

    def worker():
        broadcaster.publish_nowait(key, {"type": "logs", "text": "from-worker"})
        done.set()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert done.is_set()

    # call_soon_threadsafe 需要事件循环转一圈
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event["text"] == "from-worker"

    broadcaster.unsubscribe(key, queue)
