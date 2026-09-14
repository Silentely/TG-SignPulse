"""Tests for plugin marketplace API endpoints."""

from __future__ import annotations

from tests.test_api import _auth, _login
from tg_signer.core.plugins import PluginRegistry

pytest_plugins = ("tests.test_api",)


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

    resp = api_client.get("/api/plugins/market/bing_daily_quote/readme", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "bing_daily_quote"
    assert "必应每日一图" in data["readme"]


def test_market_install_update_and_uninstall(api_client):
    """Test full plugin lifecycle: install, update, check status, uninstall."""
    token = _login(api_client)
    headers = _auth(token)

    # Ensure local source
    api_client.put("/api/plugins/market/source", headers=headers, json={"source_type": "local"})

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

    # 4. Uninstall plugin
    resp = api_client.delete("/api/plugins/market/dice_roller/uninstall", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert PluginRegistry.get("dice_roller") is None


def test_market_install_nonexistent_returns_404(api_client):
    """Attempting to install a nonexistent plugin returns 404."""
    token = _login(api_client)
    headers = _auth(token)

    resp = api_client.post("/api/plugins/market/no_such_plugin_999/install", headers=headers)
    assert resp.status_code == 404


def test_market_uninstall_builtin_forbidden(api_client):
    """Attempting to uninstall a builtin plugin returns 403."""
    token = _login(api_client)
    headers = _auth(token)

    # math_solver is a builtin plugin
    resp = api_client.delete("/api/plugins/market/math_solver/uninstall", headers=headers)
    assert resp.status_code == 403


def test_market_source_ssrf_blocked(api_client):
    """Setting a private/loopback URL as custom market source must be rejected with 400."""
    token = _login(api_client)
    headers = _auth(token)

    # SSRF to localhost
    resp = api_client.put(
        "/api/plugins/market/source",
        headers=headers,
        json={"source_type": "custom", "custom_url": "http://127.0.0.1:8000/marketplace.json"},
    )
    assert resp.status_code == 400
    assert "不安全" in resp.json()["detail"]


def test_uninstall_market_plugin_invalid_id_blocked(api_client):
    """Calling uninstall with path traversal or invalid characters must be blocked with 400."""
    token = _login(api_client)
    headers = _auth(token)

    for bad_id in ["..", "foo/bar", "foo\\bar", "foo..bar", "bad id"]:
        resp = api_client.delete(f"/api/plugins/market/{bad_id}/uninstall", headers=headers)
        assert resp.status_code in (400, 404, 405)


def test_install_market_plugin_zip_slip_blocked(api_client, monkeypatch):
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
            }
        ]
    }

    async def fake_fetch(refresh=False):
        return fake_catalog, "local", "local://marketplace.json", False

    monkeypatch.setattr(plugins_route, "_fetch_market_catalog", fake_fetch)

    # Mock zip reading to return our malicious archive
    def fake_read_bytes(*args, **kwargs):
        return malicious_bytes

    monkeypatch.setattr("pathlib.Path.read_bytes", fake_read_bytes)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    resp = api_client.post("/api/plugins/market/malicious_zip_plugin/install", headers=headers)
    assert resp.status_code == 400
    assert "Zip Slip" in resp.json()["detail"]


def test_install_market_plugin_subprocess_forbidden(api_client, monkeypatch):
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
            "        subprocess.run(['ls', '-la'])\n"
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
            }
        ]
    }

    async def fake_fetch(refresh=False):
        return fake_catalog, "local", "local://marketplace.json", False

    monkeypatch.setattr(plugins_route, "_fetch_market_catalog", fake_fetch)
    monkeypatch.setattr("pathlib.Path.read_bytes", lambda self: subp_bytes)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)

    resp = api_client.post("/api/plugins/market/subp_plugin/install", headers=headers)
    assert resp.status_code == 400
    assert "安全审计未通过" in resp.json()["detail"]
