import httpx
import pytest

from tg_signer.semantic.client import JevClient, normalize_base_url
from tg_signer.semantic.models import Decision, DecisionRequest
from tg_signer.semantic.policy import accept_decision


def test_decision_request_fields():
    req = DecisionRequest(
        kind="result",
        scope="test_scope",
        state={"message": "hello"},
        choices={"success": "成功", "failure": "失败"},
        instructions="判断是否成功",
        request_key="req_1",
        config_revision="rev_1",
    )
    assert req.kind == "result"
    assert req.choices["success"] == "成功"


def test_policy_accept_decision():
    d = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.98, "failure": 0.02},
        confidence=0.98,
    )
    assert accept_decision(d, min_probability=0.97, min_margin=0.25)

    d_close = Decision(
        status="ok",
        selected="success",
        probabilities={"success": 0.55, "failure": 0.45},
        confidence=0.55,
    )
    assert not accept_decision(d_close, min_probability=0.50, min_margin=0.20)


def test_normalize_base_url():
    """测试 base_url 规范化与体验优化：
    - 统一补齐 /v1
    - 去除多余尾部斜杠
    - 若误填完整路径包含 /systemone，剥离避免重复拼接
    """
    assert normalize_base_url("https://api.example.com") == "https://api.example.com/v1"
    assert (
        normalize_base_url("https://api.example.com/") == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1") == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1/")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/v1/systemone")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("https://api.example.com/systemone")
        == "https://api.example.com/v1"
    )
    assert (
        normalize_base_url("  https://api.example.com/v1/  ")
        == "https://api.example.com/v1"
    )
    assert normalize_base_url("") == "https://api.typesafe.ai/v1"
    assert normalize_base_url(None) == "https://api.typesafe.ai/v1"


@pytest.mark.asyncio
async def test_jev_client_request_url_normalization(monkeypatch):
    """① 验收测试：自定义 base_url 时请求 URL 正确（含 /v1 规范化、不重复拼接）"""
    recorded_urls: list[str] = []
    recorded_timeouts: list[httpx.Timeout] = []

    async def fake_post(self, url, json=None, headers=None, timeout=None):
        recorded_urls.append(str(url))
        recorded_timeouts.append(timeout)
        return httpx.Response(
            status_code=200,
            json={
                "answers": {
                    "decision": {
                        "choice": "pong",
                        "confidence": 0.99,
                        "probabilities": {"pong": 0.99},
                    }
                }
            },
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    req = DecisionRequest(
        kind="result",
        scope="test",
        state={"text": "PING"},
        choices={"pong": "pong"},
        instructions="Say pong",
        request_key="test_key",
        config_revision="test_rev",
    )

    test_cases = [
        ("https://api.example.com", "https://api.example.com/v1/systemone"),
        ("https://api.example.com/v1", "https://api.example.com/v1/systemone"),
        ("https://api.example.com/v1/", "https://api.example.com/v1/systemone"),
        (
            "https://api.example.com/v1/systemone",
            "https://api.example.com/v1/systemone",
        ),
        ("https://api.example.com/systemone", "https://api.example.com/v1/systemone"),
    ]

    for input_url, expected_req_url in test_cases:
        client = JevClient(
            api_key="test_key",
            base_url=input_url,
            timeout=8.0,
        )
        dec = await client.query_choice(req)
        await client.close()
        assert dec.status == "ok"
        assert dec.http_status == 200
        assert recorded_urls[-1] == expected_req_url
        # 验证超时走 httpx.Timeout(8.0, connect=3.0, read=8.0)
        to = recorded_timeouts[-1]
        assert isinstance(to, httpx.Timeout)
        assert to.connect == 3.0
        assert to.read == 8.0
