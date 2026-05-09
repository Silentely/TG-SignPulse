import asyncio
import importlib

from backend.utils.task_logs import extract_last_target_message


def _load_sign_task_service(monkeypatch, tmp_path, *, scheduler_calls):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    import backend.core.config as core_config
    import backend.scheduler as scheduler_module
    import backend.services.sign_tasks as sign_tasks_module

    core_config.get_settings.cache_clear()
    importlib.reload(sign_tasks_module)
    sign_tasks_module._sign_task_service = None

    monkeypatch.setattr(
        scheduler_module,
        "add_or_update_sign_task_job",
        lambda *args, **kwargs: scheduler_calls["add"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        scheduler_module,
        "remove_sign_task_job",
        lambda *args, **kwargs: scheduler_calls["remove"].append((args, kwargs)),
    )

    return sign_tasks_module.get_sign_task_service()


def _sample_chats():
    return [
        {
            "chat_id": -1001,
            "name": "Demo",
            "actions": [{"action": 1, "text": "/checkin"}],
            "action_interval": 1,
        }
    ]


def test_listen_mode_task_is_not_scheduled(monkeypatch, tmp_path):
    calls = {"add": [], "remove": []}
    service = _load_sign_task_service(monkeypatch, tmp_path, scheduler_calls=calls)

    service.create_task(
        task_name="listen-demo",
        sign_at="08:00:08",
        account_name="acc1",
        account_names=["acc1", "acc2"],
        execution_mode="listen",
        chats=_sample_chats(),
    )

    assert calls["add"] == []
    assert len(calls["remove"]) == 2


def test_updating_task_to_listen_mode_removes_existing_jobs(monkeypatch, tmp_path):
    calls = {"add": [], "remove": []}
    service = _load_sign_task_service(monkeypatch, tmp_path, scheduler_calls=calls)

    service.create_task(
        task_name="listen-demo",
        sign_at="08:00:08",
        account_name="acc1",
        account_names=["acc1", "acc2"],
        execution_mode="fixed",
        chats=_sample_chats(),
    )
    assert len(calls["add"]) == 2

    calls["add"].clear()
    calls["remove"].clear()

    service.update_task(
        "listen-demo",
        account_name="acc1",
        execution_mode="listen",
    )

    assert calls["add"] == []
    assert len(calls["remove"]) == 2


def test_last_target_message_is_persisted_in_history(monkeypatch, tmp_path):
    calls = {"add": [], "remove": []}
    service = _load_sign_task_service(monkeypatch, tmp_path, scheduler_calls=calls)

    service.create_task(
        task_name="history-demo",
        sign_at="08:00:08",
        account_name="acc1",
        chats=_sample_chats(),
    )
    service._save_run_info(
        "history-demo",
        True,
        "ok",
        "acc1",
        flow_logs=[
            "2026-05-08 10:00:00 - text: first reply",
            "2026-05-08 10:00:01 - text: final reply",
        ],
    )

    history = service.get_task_history_logs("history-demo", account_name="acc1", limit=5)

    assert history
    assert history[0]["last_target_message"] == "final reply"


def test_strong_failure_detection_avoids_state_message_false_positive(
    monkeypatch, tmp_path
):
    calls = {"add": [], "remove": []}
    service = _load_sign_task_service(monkeypatch, tmp_path, scheduler_calls=calls)

    assert service._message_indicates_strong_failure("当前状态 | 未注册") is False
    assert service._message_indicates_strong_failure("已签到，欢迎回来") is False
    assert service._message_indicates_strong_failure("签到失败，请稍后再试") is True


def test_background_run_status_tracks_completion(monkeypatch, tmp_path):
    calls = {"add": [], "remove": []}
    service = _load_sign_task_service(monkeypatch, tmp_path, scheduler_calls=calls)

    service.create_task(
        task_name="run-status-demo",
        sign_at="08:00:08",
        account_name="acc1",
        chats=_sample_chats(),
    )

    async def _fake_run_task_with_logs(account_name: str, task_name: str):
        task_key = (account_name, task_name)
        service._active_tasks[task_key] = True
        service._active_logs[task_key] = ["run line 1"]
        await asyncio.sleep(0.02)
        service._active_tasks[task_key] = False
        return {"success": True, "output": "run line 1\nrun line 2", "error": ""}

    monkeypatch.setattr(service, "run_task_with_logs", _fake_run_task_with_logs)

    async def _scenario():
        started = await service.start_task_run("acc1", "run-status-demo")
        assert started["state"] == "running"
        assert started["run_id"]

        for _ in range(100):
            status = service.get_task_run_status(
                "acc1",
                "run-status-demo",
                run_id=started["run_id"],
            )
            if status["state"] == "finished":
                return status
            await asyncio.sleep(0.01)
        raise AssertionError("background run did not finish in time")

    final_status = asyncio.run(_scenario())
    assert final_status["success"] is True
    assert final_status["error"] == ""
    assert "run line 2" in final_status["output"]


def test_extract_last_target_message_prefers_received_reply_lines():
    value = extract_last_target_message(
        [
            "2026-05-08 10:00:00 - 正在执行第 1/3 步：发送文本消息：/start",
            "2026-05-08 10:00:01 - 收到回复：欢迎进入用户面板",
            "2026-05-08 10:00:02 - AI 正在分析图片中的文字",
        ]
    )

    assert value == "欢迎进入用户面板"
