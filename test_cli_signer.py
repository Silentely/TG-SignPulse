from __future__ import annotations

from types import SimpleNamespace

import backend.cli.signer as signer_module


def test_login_account_passes_text_input(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(signer_module.subprocess, "run", fake_run)

    signer_module.login_account("demo", code="12345", password="secret")

    assert captured["args"][-2:] == ["login", "demo"]
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["input"] == "12345\nsecret\n"
