from backend.core.rate_limit import InMemoryRateLimiter


def test_rate_limiter_blocks_then_resets():
    limiter = InMemoryRateLimiter()

    limiter.hit(
        scope="auth.login",
        key="127.0.0.1|tester",
        max_attempts=1,
        window_seconds=60,
        block_seconds=60,
        detail="blocked",
    )

    try:
        limiter.hit(
            scope="auth.login",
            key="127.0.0.1|tester",
            max_attempts=1,
            window_seconds=60,
            block_seconds=60,
            detail="blocked",
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 429
    else:
        raise AssertionError("expected rate limit exception")

    limiter.reset("auth.login", "127.0.0.1|tester")
    limiter.hit(
        scope="auth.login",
        key="127.0.0.1|tester",
        max_attempts=1,
        window_seconds=60,
        block_seconds=60,
        detail="blocked",
    )


def test_openai_config_manager_has_config_with_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from tg_signer.ai_tools import OpenAIConfigManager

    manager = OpenAIConfigManager(tmp_path)
    manager.save_config("sk-test", base_url="https://example.com", model="gpt-4o")

    assert manager.has_config() is True
