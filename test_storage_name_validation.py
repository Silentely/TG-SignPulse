import importlib

import pytest


def test_sign_task_service_rejects_path_traversal_names(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    import backend.core.config as config_module
    import backend.services.sign_tasks as sign_tasks_module

    config_module.get_settings.cache_clear()
    importlib.reload(sign_tasks_module)
    sign_tasks_module._sign_task_service = None
    service = sign_tasks_module.get_sign_task_service()

    with pytest.raises(ValueError):
        service.create_task(
            task_name="ok",
            sign_at="08:00:08",
            account_name="..",
            chats=[],
        )

    with pytest.raises(ValueError):
        service.create_task(
            task_name="../escape",
            sign_at="08:00:08",
            account_name="acc1",
            chats=[],
        )


def test_telegram_service_rejects_path_traversal_account_name(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))

    import backend.core.config as config_module
    import backend.services.telegram as telegram_module

    config_module.get_settings.cache_clear()
    importlib.reload(telegram_module)
    service = telegram_module.TelegramService()

    with pytest.raises(ValueError):
        service.account_exists("../escape")
