import socket

import httpx
import pytest


def test_transport_pins_dns_preserves_host_and_sni(monkeypatch):
    from backend.services.webdav_client import _PinnedTransport

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    with httpx.Client(
        transport=_PinnedTransport(httpx.MockTransport(handler))
    ) as client:
        client.get("https://dav.example/backup")
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "dav.example"
    assert seen[0].extensions["sni_hostname"] == "dav.example"


def test_transport_blocks_redirect_to_private_and_dns_rebinding(monkeypatch):
    from backend.services.webdav_client import _PinnedTransport

    calls = []
    answers = iter(["93.184.216.34", "127.0.0.1"])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers), 443))
        ],
    )

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://dav.example/internal"})

    with httpx.Client(
        transport=_PinnedTransport(httpx.MockTransport(handler)), follow_redirects=True
    ) as client:
        with pytest.raises(ValueError, match="public"):
            client.get("https://dav.example/backup")
    assert len(calls) == 1


def test_transport_forbids_cross_origin_redirect_credentials(monkeypatch):
    from backend.services.webdav_client import _PinnedTransport

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://evil.example/steal"})

    with httpx.Client(
        transport=_PinnedTransport(httpx.MockTransport(handler)),
        follow_redirects=True,
        auth=("u", "secret"),
    ) as client:
        with pytest.raises(ValueError, match="origin"):
            client.put("https://dav.example/backup", content=b"sensitive archive")
    assert len(calls) == 1


def test_tls_skip_does_not_grant_private_access():
    from backend.services.webdav_client import check_webdav_connection

    with pytest.raises(ValueError):
        check_webdav_connection(
            base_url="https://127.0.0.1/dav",
            username="u",
            password="p",
            remote_dir="",
            skip_ssl_verify=True,
        )


def test_allow_private_is_independent_of_tls_verification(monkeypatch):
    from backend.services.webdav_client import _PinnedTransport

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with httpx.Client(
        transport=_PinnedTransport(
            httpx.MockTransport(lambda request: httpx.Response(200)), allow_private=True
        )
    ) as client:
        assert client.get("https://localhost/dav").status_code == 200
