"""Full regression test suite for TG-SignPulse community plugins catalog.

Validates all official community plugins against schema, packaging guidelines,
security AST audit, and runtime registration.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.version import Version

from scripts.build_marketplace import validate_plugin
from tg_signer.core.plugins import (
    BUILTIN_LEGACY_PLUGINS_WHITELIST,
    PluginRegistry,
    audit_plugin_source,
)

jsonschema = pytest.importorskip("jsonschema")

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMUNITY_PLUGINS_DIR = REPO_ROOT / "community_plugins"
SCHEMA_PATH = COMMUNITY_PLUGINS_DIR / "schema.json"

EXPECTED_COMMUNITY_PLUGINS = {
    "auto_read_marker",
    "bing_daily_quote",
    "chat_cleaner",
    "checkin_observer",
    "crypto_price_tracker",
    "dice_roller",
    "jitter_delay",
    "mini_app_claim",
    "typing_simulator",
}


def _discover_plugin_dirs() -> list[Path]:
    """Find all valid plugin directories, ignoring templates and dotfiles."""
    return sorted(
        [
            d
            for d in COMMUNITY_PLUGINS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith((".", "_"))
        ],
        key=lambda p: p.name,
    )


@pytest.fixture(scope="module")
def schema_manifest() -> dict:
    """Load JSON Schema definition for community plugins."""
    assert SCHEMA_PATH.is_file(), f"Missing schema file: {SCHEMA_PATH}"
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clean_plugin_registry():
    """Ensure PluginRegistry state is completely clean before and after each test."""
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()


def test_community_plugins_discovery_exact_catalog():
    """Verify that all expected community plugins exist and no unrecognized entries are present."""
    plugin_dirs = _discover_plugin_dirs()
    discovered_ids = {d.name for d in plugin_dirs}
    assert discovered_ids == EXPECTED_COMMUNITY_PLUGINS, (
        f"Plugin catalog mismatch. Expected: {EXPECTED_COMMUNITY_PLUGINS}, Got: {discovered_ids}"
    )
    assert len(plugin_dirs) == 9


@pytest.mark.parametrize("plugin_dir", _discover_plugin_dirs(), ids=lambda p: p.name)
def test_plugin_json_schema_validation(plugin_dir: Path, schema_manifest: dict):
    """Verify plugin.json strictly conforms to community_plugins/schema.json."""
    plugin_json_path = plugin_dir / "plugin.json"
    assert plugin_json_path.is_file(), f"Missing plugin.json in {plugin_dir}"

    manifest = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    # Validate against JSON schema
    jsonschema.validate(instance=manifest, schema=schema_manifest)


@pytest.mark.parametrize("plugin_dir", _discover_plugin_dirs(), ids=lambda p: p.name)
def test_plugin_context_and_min_app_version(plugin_dir: Path):
    """Verify context_version == 2 and min_app_version >= 1.9.0 for all community plugins."""
    manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))

    # Verify context_version == 2
    assert manifest.get("context_version") == 2, (
        f"Plugin {plugin_dir.name} context_version must be 2, got {manifest.get('context_version')}"
    )

    # Verify min_app_version >= 1.9.0
    min_app_ver_str = manifest.get("min_app_version")
    assert min_app_ver_str is not None, (
        f"Plugin {plugin_dir.name} missing min_app_version"
    )
    assert Version(min_app_ver_str) >= Version("1.9.0"), (
        f"Plugin {plugin_dir.name} min_app_version must be >= 1.9.0, got {min_app_ver_str}"
    )

    # Verify plugin_api is set
    assert manifest.get("plugin_api") == "2.0", (
        f"Plugin {plugin_dir.name} plugin_api must be '2.0', got {manifest.get('plugin_api')}"
    )


@pytest.mark.parametrize("plugin_dir", _discover_plugin_dirs(), ids=lambda p: p.name)
def test_plugin_python_sources_pass_ast_audit(plugin_dir: Path):
    """Verify all Python modules in plugin directory pass AST security audit cleanly."""
    main_py = plugin_dir / "main.py"
    assert main_py.is_file(), f"Missing main.py in {plugin_dir}"

    py_files = sorted(plugin_dir.glob("**/*.py"))
    assert len(py_files) >= 1

    for py_file in py_files:
        code_text = py_file.read_text(encoding="utf-8")
        warnings = audit_plugin_source(code_text)
        high_severity = [
            w
            for w in warnings
            if w.get("severity") in ("high", "critical")
            or "subprocess" in str(w.get("message", "")).lower()
            or "os.system" in str(w.get("message", "")).lower()
        ]
        assert not high_severity, (
            f"AST security audit failed in {py_file.relative_to(plugin_dir)}: {high_severity}"
        )


@pytest.mark.parametrize("plugin_dir", _discover_plugin_dirs(), ids=lambda p: p.name)
def test_build_marketplace_validate_plugin_passes(plugin_dir: Path):
    """Verify build_marketplace.validate_plugin returns success for each community plugin."""
    is_valid, errors, manifest = validate_plugin(plugin_dir)
    assert is_valid, f"validate_plugin failed for {plugin_dir.name}: {errors}"
    assert not errors
    assert manifest.get("id") == plugin_dir.name


def test_plugin_registry_load_all_community_plugins_cleanly():
    """Verify PluginRegistry.load_plugins_from_dir registers all 8 plugins cleanly."""
    loaded_count = PluginRegistry.load_plugins_from_dir(COMMUNITY_PLUGINS_DIR)
    assert loaded_count == 9, f"Expected 9 plugins loaded, got {loaded_count}"

    registered = PluginRegistry.list_plugins()
    assert set(registered.keys()) == EXPECTED_COMMUNITY_PLUGINS
    assert len(PluginRegistry._load_errors) == 0, (
        f"Plugin load errors detected: {PluginRegistry._load_errors}"
    )

    for pid in EXPECTED_COMMUNITY_PLUGINS:
        meta = registered[pid]
        assert meta.context_version == 2
        assert meta.min_app_version == "1.9.0"
        assert meta.plugin_api == "2.0"
        assert meta.isolation_mode == "subprocess"


def _write_community_gate_plugin(root: Path) -> None:
    plugin_dir = root / "community_gate_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "community_gate_plugin",
                "name": "Community Gate Plugin",
                "version": "1.0.0",
                "mode": "active",
                "category": "utility",
                "description": "A test plugin for the community loading gate.",
                "author": "Test Author",
                "min_app_version": "1.9.0",
                "context_version": 2,
                "plugin_api": "2.0",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        '@PluginRegistry.register(name="community_gate_plugin", mode="active", context_version=2, plugin_api="2.0", min_app_version="1.9.0")\n'
        "async def handle(ctx):\n    return True\n",
        encoding="utf-8",
    )


def _write_gate_plugin(root: Path, plugin_name: str) -> None:
    plugin_dir = root / plugin_name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "main.py").write_text(
        "from tg_signer.core.plugins import PluginRegistry\n"
        f'@PluginRegistry.register(name="{plugin_name}", mode="active", context_version=2, plugin_api="2.0", min_app_version="1.9.0")\n'
        "async def handle(ctx):\n    return True\n",
        encoding="utf-8",
    )


def test_community_plugins_are_not_loaded_when_disabled(monkeypatch, tmp_path):
    community_dir = tmp_path / "community_plugins"
    _write_community_gate_plugin(community_dir)
    monkeypatch.setenv("COMMUNITY_PLUGINS_DIR", str(community_dir))
    monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
    monkeypatch.setattr(
        PluginRegistry, "get_builtin_directories", classmethod(lambda cls: [])
    )
    monkeypatch.setattr(
        PluginRegistry, "get_search_directories", classmethod(lambda cls: [])
    )

    assert PluginRegistry.load_all_configured_plugins() == 0
    assert "community_gate_plugin" not in PluginRegistry.list_plugins()


def test_community_plugins_load_with_explicit_warning(monkeypatch, tmp_path, caplog):
    community_dir = tmp_path / "community_plugins"
    _write_community_gate_plugin(community_dir)
    monkeypatch.setenv("COMMUNITY_PLUGINS_DIR", str(community_dir))
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
    monkeypatch.setattr(
        PluginRegistry, "get_builtin_directories", classmethod(lambda cls: [])
    )
    monkeypatch.setattr(
        PluginRegistry, "get_search_directories", classmethod(lambda cls: [])
    )
    monkeypatch.setattr(
        PluginRegistry,
        "get_community_directories",
        classmethod(lambda cls: [community_dir]),
    )
    caplog.set_level(logging.WARNING, logger="tg_signer.plugins")

    assert PluginRegistry.load_all_configured_plugins() == 1
    assert "community_gate_plugin" in PluginRegistry.list_plugins()
    assert "可读写宿主文件与网络" in caplog.text


def test_mini_app_readme_has_working_bilingual_anchors():
    readme = (COMMUNITY_PLUGINS_DIR / "mini_app_claim" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "[简体中文](#chinese)" in readme
    assert '<span id="chinese"></span>' in readme
    assert "[English](#english)" in readme


def test_plugin_loading_matrix_keeps_custom_plugins_and_gates_community(
    monkeypatch, tmp_path
):
    builtin_dir = tmp_path / "builtin"
    custom_dir = tmp_path / "custom"
    community_dir = tmp_path / "community"
    for directory in (builtin_dir, custom_dir, community_dir):
        directory.mkdir()
    _write_gate_plugin(builtin_dir, "builtin_gate_plugin")
    _write_gate_plugin(custom_dir, "custom_gate_plugin")
    _write_gate_plugin(community_dir, "community_gate_plugin")

    monkeypatch.setattr(
        PluginRegistry,
        "get_builtin_directories",
        classmethod(lambda cls: [builtin_dir]),
    )
    monkeypatch.setattr(
        PluginRegistry,
        "get_search_directories",
        classmethod(lambda cls: [builtin_dir, custom_dir]),
    )
    monkeypatch.setattr(
        PluginRegistry,
        "get_community_directories",
        classmethod(lambda cls: [community_dir]),
    )

    monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
    assert PluginRegistry.load_all_configured_plugins() == 2
    assert set(PluginRegistry.list_plugins()) == {
        "builtin_gate_plugin",
        "custom_gate_plugin",
    }

    PluginRegistry.clear()
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
    assert PluginRegistry.load_all_configured_plugins() == 3
    assert set(PluginRegistry.list_plugins()) == {
        "builtin_gate_plugin",
        "custom_gate_plugin",
        "community_gate_plugin",
    }


def test_negative_context_version_fails_schema(schema_manifest: dict):
    """Verify a plugin manifest with context_version=1 fails jsonschema validation."""
    invalid_manifest = {
        "id": "legacy_mock_plugin",
        "name": "Legacy Mock Plugin",
        "version": "1.0.0",
        "mode": "reactive",
        "category": "utility",
        "description": "A simulated legacy plugin with context_version 1",
        "author": "Mock Author",
        "min_app_version": "1.9.0",
        "context_version": 1,
        "plugin_api": "2.0",
    }
    with pytest.raises(jsonschema.ValidationError) as exc_info:
        jsonschema.validate(instance=invalid_manifest, schema=schema_manifest)

    assert "context_version" in str(exc_info.value) or "1 is not one of [2]" in str(
        exc_info.value
    )


def test_negative_context_version_fails_marketplace_check():
    """Verify validate_plugin rejects context_version != 2 when not whitelisted."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / "sample_v1_plugin"
        fake_plugin.mkdir()
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "sample_v1_plugin",
                    "name": "Sample V1 Plugin",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Simulated v1 plugin",
                    "author": "Tester",
                    "min_app_version": "1.9.0",
                    "context_version": 1,
                    "plugin_api": "2.0",
                }
            ),
            encoding="utf-8",
        )
        (fake_plugin / "main.py").write_text(
            "def handle():\n    pass\n", encoding="utf-8"
        )
        (fake_plugin / "README.md").write_text("# Readme", encoding="utf-8")

        # Copy schema into parent so validate_plugin finds it if checked
        shutil.copy(SCHEMA_PATH, Path(tmp_dir) / "schema.json")

        is_valid, errors, _ = validate_plugin(fake_plugin)
        assert not is_valid
        assert any("context_version" in err for err in errors)


def test_negative_context_version_rejected_by_runtime_loader():
    """Verify runtime loader rejects context_version=1 for non-whitelisted plugin."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / "sample_legacy_loader"
        fake_plugin.mkdir()
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "sample_legacy_loader",
                    "name": "Sample Legacy Loader",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Simulated legacy plugin",
                    "author": "Tester",
                    "min_app_version": "1.9.0",
                    "context_version": 1,
                    "plugin_api": "2.0",
                }
            ),
            encoding="utf-8",
        )
        (fake_plugin / "main.py").write_text(
            "from tg_signer.core.plugins import PluginRegistry\n"
            '@PluginRegistry.register("sample_legacy_loader", mode="reactive", description="test", version="1.0.0", context_version=1)\n'
            "async def handle(ctx):\n    pass\n",
            encoding="utf-8",
        )

        loaded_count = PluginRegistry.load_plugins_from_dir(Path(tmp_dir))
        assert loaded_count == 0
        assert "sample_legacy_loader" not in PluginRegistry.list_plugins()

        error_keys = list(PluginRegistry._load_errors.keys())
        assert len(error_keys) == 1
        load_err = PluginRegistry._load_errors[error_keys[0]]
        assert "requires context_version >= 2" in load_err.error_message


def test_negative_context_version_whitelisted_legacy_bypass():
    """Verify whitelisted legacy plugin is allowed with context_version=1."""
    plugin_name = "legacy_whitelisted_demo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / plugin_name
        fake_plugin.mkdir()
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": plugin_name,
                    "name": "Legacy Whitelisted",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Whitelisted legacy plugin",
                    "author": "Tester",
                    "min_app_version": "1.9.0",
                    "context_version": 1,
                    "plugin_api": "2.0",
                }
            ),
            encoding="utf-8",
        )
        (fake_plugin / "main.py").write_text(
            "from tg_signer.core.plugins import PluginRegistry\n"
            f'@PluginRegistry.register("{plugin_name}", mode="reactive", description="test", version="1.0.0", context_version=1)\n'
            "async def handle(ctx):\n    pass\n",
            encoding="utf-8",
        )

        with (
            patch(
                "tg_signer.core.plugins.BUILTIN_LEGACY_PLUGINS_WHITELIST",
                BUILTIN_LEGACY_PLUGINS_WHITELIST | {plugin_name},
            ),
            patch(
                "tg_signer.core.plugins.PluginRegistry.get_builtin_directories",
                return_value=[Path(tmp_dir)],
            ),
        ):
            loaded_count = PluginRegistry.load_plugins_from_dir(Path(tmp_dir))
            assert loaded_count == 1
            assert plugin_name in PluginRegistry.list_plugins()
            assert len(PluginRegistry._load_errors) == 0
            assert PluginRegistry.list_plugins()[plugin_name].context_version == 1


def test_negative_v1_manifest_without_plugin_api_rejected_in_data_plugins():
    """Verify v1 manifest without plugin_api in data/plugins is strictly rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / "data" / "plugins" / "custom_v1_plugin"
        fake_plugin.mkdir(parents=True)
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "custom_v1_plugin",
                    "name": "Custom V1 Plugin",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Custom v1 without plugin_api in data/plugins",
                    "author": "Tester",
                    "context_version": 1,
                }
            ),
            encoding="utf-8",
        )
        code = (
            "from tg_signer.core.plugins import PluginRegistry\n"
            '@PluginRegistry.register("custom_v1_plugin", mode="reactive", description="test", version="1.0.0", context_version=1)\n'
            "async def handle(ctx):\n    pass\n"
        )
        (fake_plugin / "main.py").write_text(code, encoding="utf-8")

        loaded_count = PluginRegistry.load_plugins_from_dir(fake_plugin.parent)
        assert loaded_count == 0
        assert "custom_v1_plugin" not in PluginRegistry.list_plugins()
        error_keys = list(PluginRegistry._load_errors.keys())
        assert len(error_keys) == 1
        load_err = PluginRegistry._load_errors[error_keys[0]]
        assert "requires context_version >= 2" in load_err.error_message


def test_negative_math_solver_in_community_plugins_v1_rejected():
    """Verify whitelisted name in community_plugins directory is rejected when context_version=1."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / "community_plugins" / "math_solver"
        fake_plugin.mkdir(parents=True)
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "math_solver",
                    "name": "Math Solver Spoof",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Spoofed legacy plugin in community folder",
                    "author": "Tester",
                    "min_app_version": "1.9.0",
                    "context_version": 1,
                    "plugin_api": "2.0",
                }
            ),
            encoding="utf-8",
        )
        code = (
            "from tg_signer.core.plugins import PluginRegistry\n"
            '@PluginRegistry.register("math_solver", mode="reactive", description="test", version="1.0.0", context_version=1)\n'
            "async def handle(ctx):\n    pass\n"
        )
        (fake_plugin / "main.py").write_text(code, encoding="utf-8")
        (fake_plugin / "README.md").write_text("# Readme", encoding="utf-8")
        shutil.copy(SCHEMA_PATH, fake_plugin.parent / "schema.json")

        is_valid, errors, _ = validate_plugin(fake_plugin)
        assert not is_valid
        assert any("context_version" in err for err in errors)

        loaded_count = PluginRegistry.load_plugins_from_dir(fake_plugin.parent)
        assert loaded_count == 0
        assert "math_solver" not in PluginRegistry.list_plugins()


def test_negative_worker_direct_load_v1_rejected():
    """Verify import_single_plugin_source blocks context_version=1 for non-whitelisted path."""
    from tg_signer.core.plugin_worker import import_single_plugin_source

    with tempfile.TemporaryDirectory() as tmp_dir:
        fake_plugin = Path(tmp_dir) / "worker_v1_direct"
        fake_plugin.mkdir()
        (fake_plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "id": "worker_v1_direct",
                    "name": "Worker V1 Direct",
                    "version": "1.0.0",
                    "mode": "reactive",
                    "category": "utility",
                    "description": "Direct worker load attempt",
                    "author": "Tester",
                    "context_version": 1,
                }
            ),
            encoding="utf-8",
        )
        main_file = fake_plugin / "main.py"
        code = (
            "from tg_signer.core.plugins import PluginRegistry\n"
            '@PluginRegistry.register("worker_v1_direct", mode="reactive", description="test", version="1.0.0", context_version=1)\n'
            "async def handle(ctx):\n    pass\n"
        )
        main_file.write_text(code, encoding="utf-8")

        with pytest.raises(ValueError, match="requires context_version >= 2"):
            import_single_plugin_source(str(main_file), "worker_v1_direct")

        assert PluginRegistry.get("worker_v1_direct") is None


def test_negative_host_rpc_grant_rejects_v1_non_whitelisted():
    """Verify host _check_rpc_grant raises PluginPermissionDeniedError for v1 non-whitelisted plugin."""
    from unittest.mock import MagicMock

    from tg_signer.core.plugin_host import PluginProcessHost
    from tg_signer.core.plugins import PluginMeta, PluginPermissionDeniedError

    meta = PluginMeta(
        name="rogue_v1_plugin",
        handler=lambda ctx: None,
        mode="active",
        description="",
        version="1.0.0",
        updated_at="2026-10-31",
        author="tester",
        source_path="/data/plugins/rogue_v1/main.py",
        params_schema=[],
        permissions=[],
        context_version=1,
    )
    PluginRegistry._plugins["rogue_v1_plugin"] = meta
    try:
        host = PluginProcessHost(
            plugin_name="rogue_v1_plugin", ctx=MagicMock(), timeout=1.0
        )
        with pytest.raises(
            PluginPermissionDeniedError,
            match="requires context_version >= 2 and is not whitelisted",
        ):
            host._check_rpc_grant("storage_get", {})
    finally:
        PluginRegistry.unregister("rogue_v1_plugin")
