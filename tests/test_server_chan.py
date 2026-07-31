"""Server 酱推送测试：URL 分支（标准/sctp）、参数合并与返回值透传。"""

from __future__ import annotations

import pytest

from tg_signer.notification import server_chan
from tg_signer.notification.server_chan import sc_send

PAYLOAD = {"errno": 0, "errmsg": "success"}


class _FakeResponse:
    def json(self):
        return PAYLOAD


class _FakeClient:
    """记录构造头与 POST 请求，按 AsyncClient 的 async with 协议工作。"""

    instances: list["_FakeClient"] = []

    def __init__(self, headers=None):
        self.headers = headers
        self.posts: list[tuple] = []
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None):
        self.posts.append((url, json))
        return _FakeResponse()


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(server_chan, "AsyncClient", _FakeClient)
    return _FakeClient


class TestScSend:
    @pytest.mark.asyncio()
    async def test_standard_sendkey_url_and_params(self):
        result = await sc_send("SCT_TEST", "标题", "内容", {"openid": "u1"})
        client = _FakeClient.instances[0]
        assert client.headers == {"Content-Type": "application/json;charset=utf-8"}
        url, params = client.posts[0]
        assert url == "https://sctapi.ftqq.com/SCT_TEST.send"
        assert params == {"title": "标题", "desp": "内容", "openid": "u1"}
        assert result == PAYLOAD

    @pytest.mark.asyncio()
    async def test_sctp_sendkey_uses_numeric_host(self):
        await sc_send("sctp123token", "标题")
        url, params = _FakeClient.instances[0].posts[0]
        assert url == "https://123.push.ft07.com/send/sctp123token.send"
        assert params == {"title": "标题", "desp": ""}

    @pytest.mark.asyncio()
    async def test_invalid_sctp_format_raises(self):
        with pytest.raises(ValueError, match="Invalid sendkey format"):
            await sc_send("sctp_no_number", "标题")

    @pytest.mark.asyncio()
    async def test_options_default_merges_nothing(self):
        await sc_send("KEY", "标题")
        _, params = _FakeClient.instances[0].posts[0]
        assert params == {"title": "标题", "desp": ""}
