import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from tg_signer.core.plugins import PluginRegistry, PluginMeta


def test_plugin_meta_permissions():
    @PluginRegistry.register(
        name="test_perm_plugin",
        mode="reactive",
        description="Permission test plugin",
        permissions=["send_message", "click_button"],
    )
    def my_handler(ctx):
        pass

    meta = PluginRegistry.get("test_perm_plugin")
    assert meta is not None
    assert meta.permissions == ["send_message", "click_button"]


@pytest.mark.asyncio
async def test_install_remote_plugin(tmp_path: Path):
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
from tg_signer.core.plugins import PluginRegistry

@PluginRegistry.register(name="downloaded_plugin", mode="reactive", description="Downloaded from remote", permissions=["storage"])
def handler(ctx):
    ctx.log("running downloaded plugin")
"""

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("tg_signer.core.plugins.PluginRegistry.get_search_directories", return_value=[tmp_path]):

        mock_get.return_value = mock_resp
        req = InstallRemotePluginRequest(
            url="https://raw.githubusercontent.com/example/repo/main/my_plugin.py",
            filename="downloaded_test.py",
        )
        res = await install_remote_plugin(req, _user=fake_user)
        assert res.name == "downloaded_plugin"
        assert res.permissions == ["storage"]
        assert (tmp_path / "downloaded_test.py").exists()


@pytest.mark.asyncio
async def test_install_remote_plugin_ssrf_blocked():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User
    from fastapi import HTTPException

    fake_user = User(username="admin")
    req = InstallRemotePluginRequest(url="http://127.0.0.1:8000/evil.py")
    with pytest.raises(HTTPException) as exc_info:
        await install_remote_plugin(req, _user=fake_user)
    assert exc_info.value.status_code == 400
    assert "安全限制" in exc_info.value.detail
