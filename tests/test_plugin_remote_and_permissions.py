import socket
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from tg_signer.core.plugins import PluginRegistry, PluginMeta


def _fake_addr(ip: str):
    """构造 getaddrinfo 返回格式的单条解析记录，避免测试依赖真实 DNS。"""
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))


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
         patch("socket.getaddrinfo", return_value=[_fake_addr("93.184.216.34")]), \
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


@pytest.mark.asyncio
async def test_install_remote_plugin_rejects_redirects():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    mock_resp = MagicMock(status_code=302, headers={"location": "http://127.0.0.1/evil.py"})

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("socket.getaddrinfo", return_value=[_fake_addr("93.184.216.34")]):
        mock_get.return_value = mock_resp
        req = InstallRemotePluginRequest(url="https://example.com/plugin.py")
        with pytest.raises(HTTPException) as exc_info:
            await install_remote_plugin(req, _user=fake_user)

    assert exc_info.value.status_code == 400
    assert "重定向" in exc_info.value.detail
    # 请求必须钉扎到已校验的 IP，并保留原主机名用于 Host 头与 SNI/证书校验
    assert mock_get.await_args.args[0] == "https://93.184.216.34/plugin.py"
    assert mock_get.await_args.kwargs["headers"]["Host"] == "example.com"
    assert mock_get.await_args.kwargs["extensions"] == {"sni_hostname": "example.com"}


@pytest.mark.asyncio
async def test_install_remote_plugin_blocks_ipv4_mapped_ipv6():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    req = InstallRemotePluginRequest(url="http://[::ffff:10.0.0.1]/plugin.py")
    with pytest.raises(HTTPException) as exc_info:
        await install_remote_plugin(req, _user=fake_user)

    assert exc_info.value.status_code == 400
    assert "安全限制" in exc_info.value.detail


@pytest.mark.asyncio
async def test_install_remote_plugin_blocks_ipv6_unique_local():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    req = InstallRemotePluginRequest(url="http://[fd00::1]/plugin.py")
    with pytest.raises(HTTPException) as exc_info:
        await install_remote_plugin(req, _user=fake_user)

    assert exc_info.value.status_code == 400
    assert "安全限制" in exc_info.value.detail


@pytest.mark.asyncio
async def test_install_remote_plugin_blocks_multihomed_private_record():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    req = InstallRemotePluginRequest(url="http://evil.example.com/plugin.py")
    with patch("socket.getaddrinfo", return_value=[_fake_addr("93.184.216.34"), _fake_addr("10.0.0.5")]):
        with pytest.raises(HTTPException) as exc_info:
            await install_remote_plugin(req, _user=fake_user)

    assert exc_info.value.status_code == 400
    assert "安全限制" in exc_info.value.detail


@pytest.mark.asyncio
async def test_install_remote_plugin_rejects_unresolvable_host():
    from backend.api.routes.plugins import install_remote_plugin, InstallRemotePluginRequest
    from backend.models.user import User

    fake_user = User(username="admin")
    req = InstallRemotePluginRequest(url="http://nonexistent.invalid/plugin.py")
    with patch("socket.getaddrinfo", side_effect=socket.gaierror(8, "nodename nor servname provided")):
        with pytest.raises(HTTPException) as exc_info:
            await install_remote_plugin(req, _user=fake_user)

    assert exc_info.value.status_code == 400
    assert "无法解析主机" in exc_info.value.detail
