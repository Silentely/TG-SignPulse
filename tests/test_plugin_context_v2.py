from dataclasses import asdict
from types import SimpleNamespace

import pytest

from tg_signer.core import plugin_runtime, plugins


def identity(account="a"):
    return plugins.PluginExecutionIdentity(
        account_id=account,
        task_id="daily",
        run_id="run",
        step_id="step",
        chat_id=123,
        thread_id=9,
        event_id="42",
        event_revision="edited-2",
    )


def test_v2_storage_is_account_scoped_and_legacy_namespace_is_unchanged():
    a = plugins.PluginContext(
        app=None,
        chat_id=123,
        plugin_name="demo",
        identity=identity(),
        context_version=2,
    )
    b = plugins.PluginContext(
        app=None,
        chat_id=123,
        plugin_name="demo",
        identity=identity("b"),
        context_version=2,
    )
    assert a.storage.namespace != b.storage.namespace
    assert a.storage_for("account").namespace != b.storage_for("account").namespace
    assert a.storage_for("task").namespace != a.storage_for("account").namespace
    assert (
        plugins.PluginContext(
            app=None, chat_id=123, plugin_name="demo"
        ).storage.namespace
        == "123:demo"
    )
    with pytest.raises(ValueError):
        a.storage_for("arbitrary:namespace")


@pytest.mark.asyncio
async def test_v2_context_lazily_migrates_legacy_chat_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from tg_signer.core.plugin_storage import PluginStore

    store = PluginStore()
    store.set("123:demo", "count", 7)
    context = plugins.PluginContext(
        app=None,
        chat_id=123,
        plugin_name="demo",
        identity=identity(),
        context_version=2,
    )

    assert await context.storage.get("count") == 7
    assert store.get(context.storage.namespace, "count") == 7


def test_parameter_resolver_applies_required_defaults_and_rejects_invalid_enum():
    meta = SimpleNamespace(
        context_version=2,
        params_schema=[
            {"name": "count", "type": "int", "required": True, "default": 3},
            {"name": "choice", "type": "select", "options": ["a", "b"], "default": "a"},
        ],
    )
    assert plugins.resolve_plugin_params(meta, {}) == {"count": 3, "choice": "a"}
    assert plugins.resolve_plugin_params(meta, {"count": "4"})["count"] == 4
    with pytest.raises(ValueError, match="PLUGIN_PARAMS_INVALID"):
        plugins.resolve_plugin_params(meta, {"choice": "bad"})


def test_legacy_true_is_handled_without_business_confirmation():
    result = plugin_runtime.adapt_plugin_result(True)
    assert result.handled is True
    assert result.outcome == "unknown"
    assert result.outputs == {}
    assert result.evidence == []


def test_typed_outputs_are_json_bounded_and_cannot_forge_host_evidence():
    raw = {
        "handled": True,
        "outcome": "confirmed",
        "outputs": {"count": 2},
        "evidence": [{"event_id": "42", "event_revision": "edited-2"}],
    }
    result = plugin_runtime.adapt_plugin_result(raw, identity=identity())
    assert result.outputs == {"count": 2}
    assert result.outcome == "confirmed"
    for invalid in [
        {**raw, "handled": "yes"},
        {**raw, "outputs": {"object": object()}},
        {**raw, "outputs": {"value": float("nan")}},
        {**raw, "outputs": {"text": "😀" * 20000}},
        {**raw, "evidence": [{"source": "host", "event_id": "42"}]},
        {**raw, "evidence": [{"event_id": "forged", "event_revision": "edited-2"}]},
    ]:
        with pytest.raises(ValueError, match="PLUGIN_RESULT_INVALID"):
            plugin_runtime.adapt_plugin_result(invalid, identity=identity())


def test_worker_proxy_keeps_host_identity_and_explicit_storage_scope():
    from tg_signer.core.plugin_worker import ProxyPluginContext

    proxy = ProxyPluginContext(
        chat_id=123,
        message=None,
        params={"account_id": "spoof"},
        rpc_requester=lambda *a, **k: None,
        logger_sink=lambda _: None,
        plugin_name="demo",
        identity=asdict(identity()),
        context_version=2,
    )
    assert proxy.identity.account_id == "a"
    assert proxy.storage.namespace.startswith("v2:")
    assert proxy.storage_for("task").namespace != proxy.storage_for("account").namespace
