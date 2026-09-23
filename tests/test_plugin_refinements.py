import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import get_current_user
from backend.main import app
from backend.models.user import User
from tg_signer.core.plugins import (
    PluginRegistry,
    PluginStorageBackend,
    PluginStorageClient,
    audit_plugin_source,
)

client = TestClient(app)


def mock_admin_user():
    return User(username="admin")


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[get_current_user] = mock_admin_user
    yield
    app.dependency_overrides.clear()


def test_storage_backend_keys_and_get_all(tmp_path: Path):
    db_file = tmp_path / "test_storage.db"
    backend = PluginStorageBackend(db_path=db_file)
    ns = "12345:my_plugin"

    # Initially empty
    assert backend.keys(ns) == []
    assert backend.get_all(ns) == {}

    # Set some keys
    backend.set(ns, "token", "abc")
    backend.set(ns, "user_count", 42)
    backend.set(ns, "temp_code", "xyz", ttl=0.05)
    backend.set("99999:other_plugin", "other_key", 1)

    assert backend.keys(ns) == ["temp_code", "token", "user_count"]
    assert backend.keys(ns, prefix="user") == ["user_count"]
    all_data = backend.get_all(ns)
    assert all_data["token"] == "abc"
    assert all_data["user_count"] == 42
    assert all_data["temp_code"] == "xyz"

    # Test TTL expiration purge
    time.sleep(0.08)
    assert backend.keys(ns) == ["token", "user_count"]
    purged_data = backend.get_all(ns)
    assert "temp_code" not in purged_data
    assert purged_data["token"] == "abc"

    # Test list_namespaces
    namespaces = backend.list_namespaces(plugin_name="my_plugin")
    assert ns in namespaces
    assert "99999:other_plugin" not in namespaces

    # Test get_all_records
    records = backend.get_all_records(ns)
    assert len(records) == 2
    keys = [r["key"] for r in records]
    assert "token" in keys
    assert "user_count" in keys


@pytest.mark.asyncio
async def test_storage_client_keys_and_get_all(tmp_path: Path):
    db_file = tmp_path / "client_storage.db"
    backend = PluginStorageBackend(db_path=db_file)
    client_storage = PluginStorageClient(namespace="42:demo_plugin", backend=backend)

    await client_storage.set("k1", "v1")
    await client_storage.set("k2", {"foo": "bar"})

    keys = await client_storage.keys()
    assert keys == ["k1", "k2"]

    data = await client_storage.get_all()
    assert data["k1"] == "v1"
    assert data["k2"] == {"foo": "bar"}


def test_api_plugin_storage_endpoints(tmp_path: Path):
    from backend.api.routes.plugins import _plugin_test_namespace

    db_file = tmp_path / "api_storage.db"
    with patch("tg_signer.core.plugins.os.getenv", return_value=str(db_file)):
        backend = PluginStorageBackend(db_path=db_file)
        prod_ns = "1001:math_solver"
        test_ns = _plugin_test_namespace(1001, "math_solver")

        backend.set(prod_ns, "prod_key", "prod_val")
        backend.set(test_ns, "test_key", "test_val")

        # GET /api/plugins/{name}/storage
        resp = client.get("/api/plugins/math_solver/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plugin_name"] == "math_solver"
        assert data["total_records"] >= 2
        ns_names = [n["namespace"] for n in data["namespaces"]]
        assert prod_ns in ns_names
        assert test_ns in ns_names

        # DELETE specific key in test namespace
        del_key_resp = client.delete(f"/api/plugins/math_solver/storage?namespace={test_ns}&key=test_key")
        assert del_key_resp.status_code == 200
        assert del_key_resp.json()["deleted_count"] == 1
        assert backend.get(test_ns, "test_key") is None

        # DELETE all storage for plugin
        del_all_resp = client.delete("/api/plugins/math_solver/storage")
        assert del_all_resp.status_code == 200
        assert del_all_resp.json()["deleted_count"] >= 1
        assert backend.get(prod_ns, "prod_key") is None


def test_api_plugins_metadata_includes_category_and_tags():
    PluginRegistry.reload_all_plugins()
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    plugins = resp.json()

    math = next((p for p in plugins if p["name"] == "math_solver"), None)
    assert math is not None
    assert math["category"] == "utility"
    assert "math" in math["tags"]
    assert math["icon"] == "calculator"

    webhook = next((p for p in plugins if p["name"] == "webhook_pusher"), None)
    assert webhook is not None
    assert webhook["category"] == "notification"
    assert "webhook" in webhook["tags"]
    assert webhook["icon"] == "send"


def test_plugin_json_auto_loading(tmp_path: Path):
    plugin_dir = tmp_path / "custom_manifest_plugin"
    plugin_dir.mkdir(parents=True)

    manifest = {
        "name": "custom_manifest_plugin",
        "category": "entertainment",
        "tags": ["fun", "game"],
        "icon": "dice",
        "homepage": "https://example.com/plugin",
        "author": "Alice",
        "version": "2.1.0",
        "description": "A fun game plugin",
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    code = '''
from tg_signer.core.plugins import PluginContext, PluginRegistry

@PluginRegistry.register(name="custom_manifest_plugin", mode="reactive")
async def handler(ctx: PluginContext):
    return True
'''
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")

    loaded = PluginRegistry.load_plugins_from_dir(tmp_path)
    assert loaded >= 1

    meta = PluginRegistry.get("custom_manifest_plugin")
    assert meta is not None
    assert meta.category == "entertainment"
    assert meta.tags == ["fun", "game"]
    assert meta.icon == "dice"
    assert meta.homepage == "https://example.com/plugin"
    assert meta.author == "Alice"
    assert meta.version == "2.1.0"
    assert meta.description == "A fun game plugin"


def test_inspect_plugin_dependencies_with_package_mapping():
    from backend.api.routes.plugins import _inspect_plugin_dependencies

    code = '''
import yaml
import bs4
from PIL import Image
import cv2
import os
'''
    with patch("importlib.util.find_spec", return_value=None):
        deps = _inspect_plugin_dependencies(code)
        dep_mods = {d["module"]: d for d in deps}

        assert "yaml" in dep_mods
        assert dep_mods["yaml"]["installed"] is False
        assert dep_mods["yaml"]["install_command"] == "pip install pyyaml"

        assert "bs4" in dep_mods
        assert dep_mods["bs4"]["installed"] is False
        assert dep_mods["bs4"]["install_command"] == "pip install beautifulsoup4"

        assert "PIL" in dep_mods
        assert dep_mods["PIL"]["installed"] is False
        assert dep_mods["PIL"]["install_command"] == "pip install pillow"

        assert "cv2" in dep_mods
        assert dep_mods["cv2"]["installed"] is False
        assert dep_mods["cv2"]["install_command"] == "pip install opencv-python"


def test_security_audit_visitor_enhanced():
    code_eval = "eval('1 + 1')"
    w_eval = audit_plugin_source(code_eval)
    assert any("eval" in w["rule"] for w in w_eval)

    code_unlink = "import os\nos.unlink('/etc/passwd')"
    w_unlink = audit_plugin_source(code_unlink)
    assert any("dangerous-system-call:os.unlink" in w["rule"] for w in w_unlink)

    code_check_output = "import subprocess\nsubprocess.check_output(['ls', '-l'])"
    w_proc = audit_plugin_source(code_check_output)
    assert any("process-execution:subprocess.check_output" in w["rule"] for w in w_proc)

    code_import_module = "import importlib\nimportlib.import_module('shutil')"
    w_dyn = audit_plugin_source(code_import_module)
    assert any("disallowed-call:importlib.import_module" in w["rule"] for w in w_dyn)


def test_storage_backend_purge_expired(tmp_path: Path):
    db_file = tmp_path / "purge_storage.db"
    backend = PluginStorageBackend(db_path=db_file)
    ns1 = "user1:plugin_a"
    ns2 = "user2:plugin_b"

    backend.set(ns1, "exp_key1", "val1", ttl=0.05)
    backend.set(ns1, "keep_key1", "val2")
    backend.set(ns2, "exp_key2", "val3", ttl=0.05)

    time.sleep(0.08)
    purged = backend.purge_expired(namespace=ns1)
    assert purged == 1
    assert backend.get(ns1, "exp_key1") is None
    assert backend.get(ns1, "keep_key1") == "val2"
    # ns2 still has expired record until purged
    assert backend.purge_expired() == 1
    assert backend.get(ns2, "exp_key2") is None


def test_storage_backend_list_namespaces_special_characters(tmp_path: Path):
    db_file = tmp_path / "special_ns.db"
    backend = PluginStorageBackend(db_path=db_file)

    # Namespaces where plugin name has underscore
    backend.set("chat1:plug_a", "k", "v")
    backend.set("chat1:plug_ab", "k", "v")
    backend.set("chat1:plug%a", "k", "v")

    # Matching exact 'plug_a' should NOT match 'plug_ab'
    ns_list = backend.list_namespaces(plugin_name="plug_a")
    assert "chat1:plug_a" in ns_list
    assert "chat1:plug_ab" not in ns_list

    # Matching exact 'plug%a'
    ns_percent = backend.list_namespaces(plugin_name="plug%a")
    assert "chat1:plug%a" in ns_percent
    assert "chat1:plug_a" not in ns_percent


def test_inspect_plugin_dependencies_ignores_local_files(tmp_path: Path):
    from backend.api.routes.plugins import _inspect_plugin_dependencies

    plugin_dir = tmp_path / "complex_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "helpers.py").write_text("def do_work(): pass", encoding="utf-8")
    sub_dir = plugin_dir / "subpkg"
    sub_dir.mkdir()
    (sub_dir / "__init__.py").write_text("", encoding="utf-8")

    code = "\n".join([
        "import helpers",
        "import subpkg",
        "import yaml",
    ])
    with patch("importlib.util.find_spec", return_value=None):
        deps = _inspect_plugin_dependencies(code, plugin_dir=plugin_dir)
        dep_names = [d["module"] for d in deps]
        assert "helpers" not in dep_names
        assert "subpkg" not in dep_names
        assert "yaml" in dep_names


def test_security_audit_visitor_pickle_and_builtins():
    code_pickle = "import pickle\npickle.loads(b'data')"
    w_pickle = audit_plugin_source(code_pickle)
    assert any("disallowed-call:pickle.loads" in w["rule"] for w in w_pickle)

    code_builtins_eval = "import builtins\nbuiltins.eval('1+1')"
    w_eval = audit_plugin_source(code_builtins_eval)
    assert any("disallowed-call:builtins.eval" in w["rule"] for w in w_eval)


def test_api_plugins_filter_parameters():
    PluginRegistry.reload_all_plugins()

    # Filter by mode=active
    resp = client.get("/api/plugins?mode=active")
    assert resp.status_code == 200
    active_plugins = resp.json()
    assert len(active_plugins) >= 1
    assert all(p["mode"] == "active" for p in active_plugins)

    # Filter by category=utility
    resp = client.get("/api/plugins?category=utility")
    assert resp.status_code == 200
    utility_plugins = resp.json()
    assert any(p["name"] == "math_solver" for p in utility_plugins)
    assert all(p["category"] == "utility" for p in utility_plugins)

    # Filter by search=calculator
    resp = client.get("/api/plugins?search=calculator")
    assert resp.status_code == 200
    search_plugins = resp.json()
    assert any(p["name"] == "math_solver" for p in search_plugins)

    # Filter by search=math_solver
    resp = client.get("/api/plugins?search=math_solver")
    assert resp.status_code == 200
    assert any(p["name"] == "math_solver" for p in resp.json())


def test_storage_backend_prefix_wildcard_escaping(tmp_path: Path):
    db_file = tmp_path / "prefix_test.db"
    backend = PluginStorageBackend(db_path=db_file)
    ns = "test:plug"

    backend.set(ns, "u_key", "val1")
    backend.set(ns, "user_key", "val2")
    backend.set(ns, "u%key", "val3")

    # prefix 'u_' should only match 'u_key', not 'user_key'
    res = backend.keys(ns, prefix="u_")
    assert "u_key" in res
    assert "user_key" not in res

    # prefix 'u%' should only match 'u%key'
    res_percent = backend.keys(ns, prefix="u%")
    assert "u%key" in res_percent
    assert "user_key" not in res_percent

    # get_all with prefix 'u_'
    all_res = backend.get_all(ns, prefix="u_")
    assert "u_key" in all_res
    assert "user_key" not in all_res


def test_clear_plugin_storage_security_and_validation():
    # 1. Providing key without namespace should return 400
    resp = client.delete("/api/plugins/math_solver/storage?key=foo")
    assert resp.status_code == 400
    assert "必须同时提供 namespace" in resp.json()["detail"]

    # 2. Providing cross-namespace belonging to another plugin should return 400
    resp = client.delete("/api/plugins/math_solver/storage?namespace=123:other_plugin")
    assert resp.status_code == 400
    assert "不属于插件" in resp.json()["detail"]

    # 3. Providing valid namespace belonging to math_solver should succeed
    resp = client.delete("/api/plugins/math_solver/storage?namespace=123:math_solver")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_security_audit_visitor_shutil_move_high_severity():
    code = "import shutil\nshutil.move('/etc/passwd', '/tmp/pwn')"
    warnings = audit_plugin_source(code)
    move_warns = [w for w in warnings if "shutil.move" in w.get("rule", "")]
    assert len(move_warns) >= 1
    assert move_warns[0]["severity"] == "high"


def test_storage_backend_closes_connection(tmp_path: Path):
    db_file = tmp_path / "conn_close_test.db"
    backend = PluginStorageBackend(db_path=db_file)

    real_get_conn = backend._get_conn
    created_conns = []

    def spy_get_conn():
        c = real_get_conn()
        created_conns.append(c)
        return c

    with patch.object(backend, "_get_conn", side_effect=spy_get_conn):
        backend.set("ns", "key", "val")
        backend.get("ns", "key")
        backend.delete("ns", "key")

    assert len(created_conns) == 3
    for c in created_conns:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")


def test_load_plugins_from_dir_restores_syspath(tmp_path: Path):
    import sys
    plugin_dir = tmp_path / "my_isolated_plugin"
    plugin_dir.mkdir()
    code = 'from tg_signer.core.plugins import PluginRegistry\n@PluginRegistry.register(name="isolated_p", mode="active")\nasync def h(ctx): return True\n'
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")
    parent_str = str(plugin_dir)
    assert parent_str not in sys.path
    PluginRegistry.load_plugins_from_dir(tmp_path)
    assert parent_str not in sys.path
