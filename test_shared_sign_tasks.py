import importlib


def _load_sign_task_service(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    import backend.core.config as core_config
    import backend.scheduler as scheduler_module
    import backend.services.sign_tasks as sign_tasks_module

    core_config.get_settings.cache_clear()
    importlib.reload(sign_tasks_module)
    sign_tasks_module._sign_task_service = None

    monkeypatch.setattr(scheduler_module, "add_or_update_sign_task_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduler_module, "remove_sign_task_job", lambda *args, **kwargs: None)

    return sign_tasks_module.get_sign_task_service()


def test_shared_task_raw_records_keep_their_own_account(monkeypatch, tmp_path):
    service = _load_sign_task_service(monkeypatch, tmp_path)
    service.create_task(
        task_name="shared-demo",
        sign_at="08:00:08",
        account_name="acc1",
        account_names=["acc1", "acc2", "acc3"],
        chats=[
            {
                "chat_id": -1001,
                "name": "Demo",
                "actions": [{"action": 1, "text": "/checkin"}],
                "action_interval": 1,
            }
        ],
    )

    tasks = service.list_tasks(aggregate=False)

    assert {task["account_name"] for task in tasks} == {"acc1", "acc2", "acc3"}
    assert all(task["account_names"] == ["acc1", "acc2", "acc3"] for task in tasks)


def test_deleting_shared_task_removes_all_account_copies(monkeypatch, tmp_path):
    service = _load_sign_task_service(monkeypatch, tmp_path)
    service.create_task(
        task_name="shared-demo",
        sign_at="08:00:08",
        account_name="acc1",
        account_names=["acc1", "acc2"],
        chats=[
            {
                "chat_id": -1001,
                "name": "Demo",
                "actions": [{"action": 1, "text": "/checkin"}],
                "action_interval": 1,
            }
        ],
    )
    service.update_task(
        "shared-demo",
        account_name="acc1",
        account_names=["acc1", "acc2", "acc3"],
        execution_mode="range",
        range_start="08:00:08",
        range_end="19:00:09",
    )

    assert service.delete_task("shared-demo", account_name="acc1") is True
    assert service.list_tasks(aggregate=True) == []
    assert not list((tmp_path / ".signer" / "signs").rglob("shared-demo"))


def test_renaming_account_updates_task_configs_and_history(monkeypatch, tmp_path):
    service = _load_sign_task_service(monkeypatch, tmp_path)
    service.create_task(
        task_name="shared-demo",
        sign_at="08:00:08",
        account_name="acc1",
        account_names=["acc1", "acc2"],
        chats=[
            {
                "chat_id": -1001,
                "name": "Demo",
                "actions": [{"action": 1, "text": "/checkin"}],
                "action_interval": 1,
            }
        ],
    )
    service._save_run_info(
        "shared-demo",
        True,
        "ok",
        account_name="acc1",
        flow_logs=["sent"],
    )

    service.rename_account_references("acc1", "acc-renamed")

    renamed_task = service.get_task("shared-demo", account_name="acc-renamed")
    linked_task = service.get_task("shared-demo", account_name="acc2")
    assert renamed_task is not None
    assert linked_task is not None
    assert renamed_task["account_name"] == "acc-renamed"
    assert renamed_task["account_names"] == ["acc-renamed", "acc2"]
    assert linked_task["account_names"] == ["acc-renamed", "acc2"]
    assert (tmp_path / ".signer" / "signs" / "acc-renamed" / "shared-demo").exists()
    assert not (tmp_path / ".signer" / "signs" / "acc1").exists()

    history = service.get_task_history_logs("shared-demo", account_name="acc-renamed")
    assert history[0]["account_name"] == "acc-renamed"
    assert not (tmp_path / ".signer" / "history" / "acc1__shared-demo.json").exists()
    assert (tmp_path / ".signer" / "history" / "acc-renamed__shared-demo.json").exists()
