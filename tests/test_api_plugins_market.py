"""Tests for plugin marketplace API endpoints."""

from __future__ import annotations

import hashlib

import pytest

from tests.test_api import _auth, _login
from tg_signer.core.plugins import PluginRegistry

pytest_plugins = ("tests.test_api",)


@pytest.fixture
def market_gate_on(monkeypatch):
    """市场安装/更新与社区插件加载共用开关，这些用例需要显式开启。"""
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")


@pytest.mark.asyncio
async def test_market_catalog_does_not_count_repository_community_source_as_installed(
    monkeypatch, tmp_path
):
    from backend.services import plugins as plugins_service
    from backend.services.plugins import PluginService
    from tg_signer.core.plugins import PluginMeta

    async def fake_fetch(refresh=False):
        return (
            {
                "plugins": [
                    {
                        "id": "community_only_plugin",
                        "name": "Community Only",
                        "version": "1.0.0",
                    }
                ]
            },
            "local",
            "local://marketplace.json",
            False,
        )

    async def handler(ctx):
        return True

    monkeypatch.setattr(
        plugins_service, "_get_fetch_market_catalog", lambda: fake_fetch
    )
    monkeypatch.setattr(
        PluginRegistry,
        "list_plugins",
        lambda: {
            "community_only_plugin": PluginMeta(
                name="community_only_plugin",
                handler=handler,
                version="1.0.0",
                source_path=str(
                    tmp_path / "community_plugins" / "community_only_plugin" / "main.py"
                ),
                builtin=False,
            )
        },
    )
    monkeypatch.setattr(PluginRegistry, "get_search_directories", lambda: [])
    monkeypatch.setattr(
        PluginRegistry,
        "get_community_directories",
        lambda: [tmp_path / "community_plugins"],
    )

    response = await PluginService().list_market_catalog(refresh=True)
    item = response.plugins[0]
    assert item.installed is False
    assert item.loaded is True
    assert item.status == "loaded"


def test_market_endpoints_require_auth(api_client):
    """Verify all market endpoints enforce authentication."""
    resp = api_client.get("/api/plugins/market")
    assert resp.status_code == 401

    resp = api_client.get("/api/plugins/market/source")
    assert resp.status_code == 401

    resp = api_client.put("/api/plugins/market/source", json={"source_type": "local"})
    assert resp.status_code == 401

    resp = api_client.get("/api/plugins/market/dice_roller/readme")
    assert resp.status_code == 401

    resp = api_client.post("/api/plugins/market/dice_roller/install")
    assert resp.status_code == 401

    resp = api_client.post("/api/plugins/market/dice_roller/update")
    assert resp.status_code == 401

    resp = api_client.delete("/api/plugins/market/dice_roller/uninstall")
    assert resp.status_code == 401


def test_market_list_and_source_config(api_client):
    """Test retrieving market catalog and updating source configurations."""
    token = _login(api_client)
    headers = _auth(token)

    # 1. Switch to local source for deterministic offline testing
    resp = api_client.put(
        "/api/plugins/market/source",
        headers=headers,
        json={"source_type": "local"},
    )
    assert resp.status_code == 200
    src_data = resp.json()
    assert src_data["source_type"] == "local"

    # 2. Get source info
    resp = api_client.get("/api/plugins/market/source", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["source_type"] == "local"

    # 3. List market catalog
    resp = api_client.get("/api/plugins/market?refresh=true", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    plugin_ids = [p["id"] for p in data["plugins"]]
    assert "bing_daily_quote" in plugin_ids
    assert "dice_roller" in plugin_ids
    assert "crypto_price_tracker" in plugin_ids


def test_market_readme_endpoint(api_client):
    """Test retrieving README document for a market plugin."""
    token = _login(api_client)
    headers = _auth(token)

    resp = api_client.get(
        "/api/plugins/market/bing_daily_quote/readme", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "bing_daily_quote"
    assert "必应每日一图" in data["readme"]


def test_market_install_update_and_uninstall(api_client, monkeypatch):
    """Test full plugin lifecycle: install, update, check status, uninstall."""
    token = _login(api_client)
    headers = _auth(token)

    # Ensure local source（该接口会整包保存全局设置，需在开启开关前调用）
    api_client.put(
        "/api/plugins/market/source", headers=headers, json={"source_type": "local"}
    )
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")

    # 1. Install dice_roller
    resp = api_client.post("/api/plugins/market/dice_roller/install", headers=headers)
    assert resp.status_code == 200
    plugin_info = resp.json()
    assert plugin_info["name"] == "dice_roller"
    assert plugin_info["mode"] == "reactive"
    assert PluginRegistry.get("dice_roller") is not None

    # 2. Verify status in marketplace catalog
    resp = api_client.get("/api/plugins/market", headers=headers)
    assert resp.status_code == 200
    market_plugins = {p["id"]: p for p in resp.json()["plugins"]}
    assert market_plugins["dice_roller"]["installed"] is True
    assert market_plugins["dice_roller"]["status"] == "installed"

    # 3. Update plugin
    resp = api_client.post("/api/plugins/market/dice_roller/update", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "dice_roller"

    # 4. Uninstall plugin（关闭开关后再卸载，避免仓库副本重新加载）
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "false")
    resp = api_client.delete(
        "/api/plugins/market/dice_roller/uninstall", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert PluginRegistry.get("dice_roller") is None


def test_market_install_blocked_when_community_gate_off(api_client, monkeypatch):
    """关闭社区插件开关时，市场安装与更新必须被拒绝。"""
    monkeypatch.delenv("PLUGINS_ALLOW_COMMUNITY", raising=False)
    token = _login(api_client)
    headers = _auth(token)

    api_client.put(
        "/api/plugins/market/source", headers=headers, json={"source_type": "local"}
    )
    resp = api_client.post("/api/plugins/market/dice_roller/install", headers=headers)
    assert resp.status_code == 409
    assert "允许加载社区插件" in resp.text

    resp = api_client.post("/api/plugins/market/dice_roller/update", headers=headers)
    assert resp.status_code == 409


def test_market_installed_plugin_unloads_when_gate_off(api_client, monkeypatch):
    """市场安装标记让插件在关闭开关后不再加载，重新开启后恢复。"""
    from backend.services.plugins import _get_custom_plugins_dir
    from tg_signer.core.plugins import MARKET_PLUGIN_MARKER

    token = _login(api_client)
    headers = _auth(token)

    api_client.put(
        "/api/plugins/market/source", headers=headers, json={"source_type": "local"}
    )
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
    resp = api_client.post("/api/plugins/market/dice_roller/install", headers=headers)
    assert resp.status_code == 200

    plugin_dir = _get_custom_plugins_dir() / "dice_roller"
    assert (plugin_dir / MARKET_PLUGIN_MARKER).is_file()

    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "false")
    PluginRegistry.reload_all_plugins()
    assert PluginRegistry.get("dice_roller") is None

    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "true")
    PluginRegistry.reload_all_plugins()
    assert PluginRegistry.get("dice_roller") is not None

    # 关闭开关时市场仍应识别本地已安装副本（只是未加载）
    monkeypatch.setenv("PLUGINS_ALLOW_COMMUNITY", "false")
    PluginRegistry.reload_all_plugins()
    resp = api_client.get("/api/plugins/market", headers=headers)
    assert resp.status_code == 200
    item = next(p for p in resp.json()["plugins"] if p["id"] == "dice_roller")
    assert item["installed"] is True
    assert item["loaded"] is False


def test_market_install_nonexistent_returns_404(api_client, market_gate_on):
    """Attempting to install a nonexistent plugin returns 404."""
    token = _login(api_client)
    headers = _auth(token)

    resp = api_client.post(
        "/api/plugins/market/no_such_plugin_999/install", headers=headers
    )
    assert resp.status_code == 404


def test_market_uninstall_builtin_forbidden(api_client):
    """Attempting to uninstall a builtin plugin returns 403."""
    token = _login(api_client)
    headers = _auth(token)

    # math_solver is a builtin plugin
    resp = api_client.delete(
        "/api/plugins/market/math_solver/uninstall", headers=headers
    )
    assert resp.status_code == 403


def test_market_source_ssrf_blocked(api_client):
    """Setting a private/loopback URL as custom market source must be rejected with 400."""
    token = _login(api_client)
    headers = _auth(token)

    # SSRF to localhost
    resp = api_client.put(
        "/api/plugins/market/source",
        headers=headers,
        json={
            "source_type": "custom",
            "custom_url": "http://127.0.0.1:8000/marketplace.json",
        },
    )
    assert resp.status_code == 400
    assert "不安全" in resp.json()["detail"]


def test_uninstall_market_plugin_invalid_id_blocked(api_client):
    """Calling uninstall with path traversal or invalid characters must be blocked with 400."""
    token = _login(api_client)
    headers = _auth(token)

    for bad_id in ["..", "foo/bar", "foo\\bar", "foo..bar", "bad id"]:
        resp = api_client.delete(
            f"/api/plugins/market/{bad_id}/uninstall", headers=headers
        )
        assert resp.status_code in (400, 404, 405)


def test_install_market_plugin_zip_slip_blocked(
    api_client, monkeypatch, market_gate_on
):
    """Plugins containing path-traversing entries (Zip Slip) must be rejected with 400."""
    token = _login(api_client)
    headers = _auth(token)

    import io
    import zipfile

    from backend.api.routes import plugins as plugins_route

    # Create a malicious zip in memory with ../evil.py
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("../evil.py", "# evil code")
    malicious_bytes = bio.getvalue()

    fake_catalog = {
        "version": "1.0",
        "plugins": [
            {
                "id": "malicious_zip_plugin",
                "name": "Malicious Plugin",
                "version": "1.0.0",
                "mode": "reactive",
                "category": "utility",
                "download_url": "local://malicious.zip",
                "sha256": hashlib.sha256(malicious_bytes).hexdigest(),
            }
        ],
    }

    async def fake_fetch(refresh=False):
        return fake_catalog, "local", "local://marketplace.json", False

    monkeypatch.setattr(plugins_route, "_fetch_market_catalog", fake_fetch)

    # Mock zip reading to return our malicious archive
    def fake_read_bytes(*args, **kwargs):
        return malicious_bytes

    monkeypatch.setattr("pathlib.Path.read_bytes", fake_read_bytes)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    resp = api_client.post(
        "/api/plugins/market/malicious_zip_plugin/install", headers=headers
    )
    assert resp.status_code == 400
    assert "Zip Slip" in resp.json()["detail"]


def test_install_market_plugin_subprocess_forbidden(
    api_client, monkeypatch, market_gate_on
):
    """Plugins containing subprocess execution must be rejected during AST security audit."""
    token = _login(api_client)
    headers = _auth(token)

    import io
    import zipfile

    from backend.api.routes import plugins as plugins_route

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr(
            "main.py",
            "import subprocess\nfrom tg_signer.core.plugins import PluginRegistry, BasePlugin\n\n"
            "@PluginRegistry.register('subp_plugin', name='Subp', mode='reactive')\n"
            "class SubpPlugin(BasePlugin):\n"
            "    async def run(self, event, context):\n"
            "        subprocess.run(['ls', '-la'])\n",
        )
    subp_bytes = bio.getvalue()

    fake_catalog = {
        "version": "1.0",
        "plugins": [
            {
                "id": "subp_plugin",
                "name": "Subp Plugin",
                "version": "1.0.0",
                "mode": "reactive",
                "category": "utility",
                "download_url": "local://subp.zip",
                "sha256": hashlib.sha256(subp_bytes).hexdigest(),
            }
        ],
    }

    async def fake_fetch(refresh=False):
        return fake_catalog, "local", "local://marketplace.json", False

    monkeypatch.setattr(plugins_route, "_fetch_market_catalog", fake_fetch)
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: subp_bytes)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    resp = api_client.post("/api/plugins/market/subp_plugin/install", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PLUGIN_SECURITY_BLOCKED"


def test_market_source_presets_point_to_main():
    """Verify that official marketplace presets point to main branch, not dev."""
    from backend.api.routes.plugins import MARKET_SOURCE_PRESETS

    assert "main" in MARKET_SOURCE_PRESETS["github"]
    assert "dev" not in MARKET_SOURCE_PRESETS["github"]
    assert "@main" in MARKET_SOURCE_PRESETS["jsdelivr"]
    assert "@dev" not in MARKET_SOURCE_PRESETS["jsdelivr"]
    assert "main" in MARKET_SOURCE_PRESETS["ghproxy"]
    assert "dev" not in MARKET_SOURCE_PRESETS["ghproxy"]


def _market_zip(members: dict) -> bytes:
    """按 {文件名: 内容} 构造 zip 字节。"""
    import io
    import zipfile

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return bio.getvalue()


def _patch_catalog(
    monkeypatch, plugin_id: str, archive_bytes: bytes, sha: str | None = None
):
    """把市场目录替换为仅含指定条目，并让安装读到给定归档字节。"""
    from backend.api.routes import plugins as plugins_route

    if sha is None:
        sha = hashlib.sha256(archive_bytes).hexdigest()

    fake_catalog = {
        "version": "1.0",
        "plugins": [
            {
                "id": plugin_id,
                "name": plugin_id,
                "version": "1.0.0",
                "mode": "reactive",
                "category": "utility",
                "download_url": f"local://{plugin_id}.zip",
                "sha256": sha,
            }
        ],
    }

    async def fake_fetch(refresh=False):
        return fake_catalog, "local", "local://marketplace.json", False

    monkeypatch.setattr(plugins_route, "_fetch_market_catalog", fake_fetch)
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: archive_bytes)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)


_BASIC_PLUGIN = '''"""test"""
from tg_signer.core.plugins import PluginRegistry, BasePlugin


@PluginRegistry.register("{pid}", name="Test", mode="reactive")
class TestPlugin(BasePlugin):
    async def run(self, event, context):
        return True
'''


def test_market_install_rejects_missing_sha256(api_client, monkeypatch, market_gate_on):
    """目录项缺 sha256 时失败关闭：不跳过完整性校验。"""
    token = _login(api_client)
    headers = _auth(token)
    archive = _market_zip({"main.py": _BASIC_PLUGIN.format(pid="nosha_plugin")})
    _patch_catalog(monkeypatch, "nosha_plugin", archive, sha="")

    resp = api_client.post("/api/plugins/market/nosha_plugin/install", headers=headers)
    assert resp.status_code == 400
    assert "sha256" in resp.json()["detail"]


def test_market_install_rejects_empty_sha256_placeholder(
    api_client, monkeypatch, market_gate_on
):
    """本地目录 setdefault("sha256", "") 产生的空串同样必须拒绝。"""
    token = _login(api_client)
    headers = _auth(token)
    archive = _market_zip({"main.py": _BASIC_PLUGIN.format(pid="emptysha_plugin")})
    _patch_catalog(monkeypatch, "emptysha_plugin", archive, sha="   ")

    resp = api_client.post(
        "/api/plugins/market/emptysha_plugin/install", headers=headers
    )
    assert resp.status_code == 400
    assert "sha256" in resp.json()["detail"]


def test_market_install_rejects_sha256_mismatch(
    api_client, monkeypatch, market_gate_on
):
    """摘要不匹配必须拒绝。"""
    token = _login(api_client)
    headers = _auth(token)
    archive = _market_zip({"main.py": _BASIC_PLUGIN.format(pid="mismatch_plugin")})
    _patch_catalog(monkeypatch, "mismatch_plugin", archive, sha="0" * 64)

    resp = api_client.post(
        "/api/plugins/market/mismatch_plugin/install", headers=headers
    )
    assert resp.status_code == 400
    assert "SHA-256 不匹配" in resp.json()["detail"]


def test_market_install_rejects_non_whitelisted_member_suffix(
    api_client, monkeypatch, market_gate_on
):
    """非 .py 成员必须落在数据文件白名单内，.pyc/.so 等一律拒绝。"""
    token = _login(api_client)
    headers = _auth(token)
    archive = _market_zip(
        {
            "main.py": _BASIC_PLUGIN.format(pid="sibling_plugin"),
            "payload.pyc": b"\x00\x01binary",
        }
    )
    _patch_catalog(monkeypatch, "sibling_plugin", archive)

    resp = api_client.post(
        "/api/plugins/market/sibling_plugin/install", headers=headers
    )
    assert resp.status_code == 400
    assert "不允许的文件类型" in resp.json()["detail"]


def test_market_install_rejects_star_import(api_client, monkeypatch, market_gate_on):
    """from shutil import * 使命名空间不可追踪，必须失败关闭。"""
    token = _login(api_client)
    headers = _auth(token)
    source = (
        "from shutil import *\n"
        "from tg_signer.core.plugins import PluginRegistry, BasePlugin\n\n\n"
        "@PluginRegistry.register('star_plugin', name='Star', mode='reactive')\n"
        "class StarPlugin(BasePlugin):\n"
        "    async def run(self, event, context):\n"
        "        return True\n"
    )
    archive = _market_zip({"main.py": source})
    _patch_catalog(monkeypatch, "star_plugin", archive)

    resp = api_client.post("/api/plugins/market/star_plugin/install", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PLUGIN_SECURITY_BLOCKED"


def test_clone_plugin_runs_security_gate(api_client, monkeypatch):
    """克隆落盘前必须过与其余入口一致的安全门禁。"""
    token = _login(api_client)
    headers = _auth(token)

    from backend.api.routes import plugins as plugins_route
    from tg_signer.core.plugins import PluginMeta

    malicious_source = (
        "import subprocess\n"
        "from tg_signer.core.plugins import PluginRegistry\n\n\n"
        "@PluginRegistry.register('evil_src', name='Evil', mode='reactive')\n"
        "async def evil_src_handler(ctx):\n"
        "    subprocess.run(['rm', '-rf', '/'])\n"
        "    return True\n"
    )

    async def _noop_handler(ctx):
        return True

    meta = PluginMeta(
        name="evil_src",
        handler=_noop_handler,
        source_path="/tmp/evil_src.py",
        builtin=False,
    )

    monkeypatch.setattr(plugins_route.PluginRegistry, "get", lambda name: meta)
    monkeypatch.setattr(
        plugins_route.PluginRegistry, "list_plugins", lambda: {"evil_src": meta}
    )
    monkeypatch.setattr(
        "pathlib.Path.read_text", lambda self, *a, **kw: malicious_source
    )
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    resp = api_client.post(
        "/api/plugins/evil_src/clone",
        json={"new_name": "evil_clone"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "PLUGIN_SECURITY_BLOCKED"
