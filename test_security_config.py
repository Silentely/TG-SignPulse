import importlib


def test_default_secret_key_is_generated_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)

    import backend.core.config as config_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)

    first = config_module.get_default_secret_key()
    second = config_module.get_default_secret_key()

    assert first
    assert first == second
    assert (tmp_path / ".app_secret_key").read_text(encoding="utf-8").strip() == first


def test_cors_allow_origins_parses_csv(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "APP_CORS_ALLOW_ORIGINS",
        "https://a.example, http://127.0.0.1:3000 ,https://b.example",
    )

    import backend.core.config as config_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)

    settings = config_module.get_settings()
    assert settings.cors_allow_origins == [
        "https://a.example",
        "http://127.0.0.1:3000",
        "https://b.example",
    ]


def test_bootstrap_admin_password_is_generated_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    import backend.core.config as config_module
    import backend.services.users as users_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)
    importlib.reload(users_module)

    first, password_file = users_module._get_or_create_bootstrap_password()
    second, second_file = users_module._get_or_create_bootstrap_password()

    assert first
    assert first == second
    assert password_file == second_file
    assert password_file.read_text(encoding="utf-8").strip() == first
