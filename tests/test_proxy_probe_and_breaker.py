from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.config import get_settings
from backend.services.config import ConfigService
from backend.services.telegram.accounts import TelegramAccountsMixin
from backend.utils.proxy import (
    DEFAULT_PROBE_ENDPOINTS,
    ProxyProbeStatus,
    clear_proxy_probe_cache,
    probe_proxy_exit,
)
from backend.utils.tg_session import _account_store_cache, set_account_profile


@pytest.fixture(autouse=True)
def reset_cache():
    clear_proxy_probe_cache()
    _account_store_cache.clear()
    get_settings.cache_clear()
    yield
    clear_proxy_probe_cache()
    _account_store_cache.clear()
    get_settings.cache_clear()


class DummyTelegramService(TelegramAccountsMixin):
    def __init__(self, session_dir: Path, workdir: Path):
        self.session_dir = session_dir
        self.workdir = workdir
        self._accounts_cache = None


@pytest.mark.asyncio
async def test_global_require_proxy_blocks_unproxied_account(tmp_path, monkeypatch):
    """全局开启 require_proxy_for_telegram 时，无代理账号在 _build_account_client / 门禁前被硬阻断。"""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    workdir = tmp_path / "data"
    workdir.mkdir(parents=True)

    session_file = session_dir / "unproxied_acc.session"
    session_file.write_text("dummy")

    cfg_svc = ConfigService()
    cfg_svc.save_global_settings({"require_proxy_for_telegram": True, "global_proxy": None})

    tg_svc = DummyTelegramService(session_dir, workdir)

    with patch("backend.services.config.get_config_service", return_value=cfg_svc):
        with pytest.raises(RuntimeError, match="PROXY_REQUIRED_BLOCKED"):
            tg_svc._build_account_client("unproxied_acc")

        with pytest.raises(RuntimeError, match="PROXY_REQUIRED_BLOCKED"):
            await tg_svc.verify_account_proxy("unproxied_acc")

        with pytest.raises(RuntimeError, match="PROXY_REQUIRED_BLOCKED"):
            await tg_svc.download_account_avatar("unproxied_acc")

        with pytest.raises(RuntimeError, match="PROXY_REQUIRED_BLOCKED"):
            await tg_svc.download_chat_avatar("unproxied_acc", 12345)


@pytest.mark.asyncio
async def test_probe_proxy_failed_when_exit_matches_host_ip(tmp_path, monkeypatch):
    """当探针探测到代理出口 IP 等于宿主机直连出口 IP 时，判定为 PROXY_PROBE_FAILED 并硬熔断。"""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    workdir = tmp_path / "data"
    workdir.mkdir(parents=True)

    session_file = session_dir / "leaking_acc.session"
    session_file.write_text("dummy")

    proxy_dict = {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080}
    set_account_profile("leaking_acc", proxy="socks5://127.0.0.1:1080")

    host_ip = "198.51.100.42"

    # probe_proxy_exit 直接调用验证
    with patch("backend.utils.proxy._fetch_ip_via_proxy", new_callable=AsyncMock) as mock_proxy_ip, \
         patch("backend.utils.proxy.get_host_direct_ip", new_callable=AsyncMock) as mock_host_ip:
        mock_host_ip.return_value = host_ip
        mock_proxy_ip.return_value = host_ip  # 泄漏：出口 IP 与宿主机一致

        status, ip = await probe_proxy_exit(proxy_dict)
        assert status == ProxyProbeStatus.FAILED
        assert ip == host_ip

    # 门禁调用验证：即使配置 policy="warn"，FAILED 也必须无条件硬熔断
    set_account_profile("leaking_acc", proxy="socks5://127.0.0.1:1080", proxy_probe_policy="warn")
    cfg_svc = ConfigService()

    tg_svc = DummyTelegramService(session_dir, workdir)
    with patch("backend.services.config.get_config_service", return_value=cfg_svc), \
         patch("backend.utils.proxy.probe_proxy_exit", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = (ProxyProbeStatus.FAILED, host_ip)
        with pytest.raises(RuntimeError, match="PROXY_PROBE_FAILED: Proxy leaks host IP"):
            await tg_svc.verify_account_proxy("leaking_acc", proxy_dict)


@pytest.mark.asyncio
async def test_probe_proxy_unavailable_strict_blocks(tmp_path, monkeypatch):
    """当探针不可达且账号策略为 strict（默认）时，触发阻断。"""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    workdir = tmp_path / "data"
    workdir.mkdir(parents=True)

    session_file = session_dir / "strict_acc.session"
    session_file.write_text("dummy")

    proxy_dict = {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080}
    set_account_profile("strict_acc", proxy="socks5://127.0.0.1:1080", proxy_probe_policy="strict")

    tg_svc = DummyTelegramService(session_dir, workdir)
    cfg_svc = ConfigService()

    with patch("backend.services.config.get_config_service", return_value=cfg_svc), \
         patch("backend.utils.proxy.probe_proxy_exit", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = (ProxyProbeStatus.UNAVAILABLE, "Connection timed out")
        with pytest.raises(RuntimeError, match="PROXY_PROBE_UNAVAILABLE"):
            await tg_svc.verify_account_proxy("strict_acc", proxy_dict)


@pytest.mark.asyncio
async def test_probe_proxy_unavailable_warn_policy_allows(tmp_path, monkeypatch):
    """当探针不可达但账号策略为 warn 时，记录警告并放行。"""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    workdir = tmp_path / "data"
    workdir.mkdir(parents=True)

    session_file = session_dir / "warn_acc.session"
    session_file.write_text("dummy")

    proxy_dict = {"scheme": "socks5", "hostname": "127.0.0.1", "port": 1080}
    set_account_profile("warn_acc", proxy="socks5://127.0.0.1:1080", proxy_probe_policy="warn")

    tg_svc = DummyTelegramService(session_dir, workdir)
    cfg_svc = ConfigService()

    with patch("backend.services.config.get_config_service", return_value=cfg_svc), \
         patch("backend.utils.proxy.probe_proxy_exit", new_callable=AsyncMock) as mock_probe, \
         patch("backend.services.telegram.accounts.logger.warning") as mock_warn:
        mock_probe.return_value = (ProxyProbeStatus.UNAVAILABLE, "Connection timed out")
        # 不抛异常，平稳放行
        await tg_svc.verify_account_proxy("warn_acc", proxy_dict)
        mock_warn.assert_called()


@pytest.mark.asyncio
async def test_probe_proxy_cached_within_ttl():
    """验证相同代理探测结果在 600s TTL 内直接复用缓存，不重复发网络请求。"""
    proxy_dict = {"scheme": "socks5", "hostname": "10.0.0.1", "port": 1080}

    with patch("backend.utils.proxy._fetch_ip_via_proxy", new_callable=AsyncMock) as mock_proxy_ip, \
         patch("backend.utils.proxy.get_host_direct_ip", new_callable=AsyncMock) as mock_host_ip:
        mock_host_ip.return_value = "1.1.1.1"
        mock_proxy_ip.return_value = "2.2.2.2"

        status1, ip1 = await probe_proxy_exit(proxy_dict)
        assert status1 == ProxyProbeStatus.OK
        assert ip1 == "2.2.2.2"
        assert mock_proxy_ip.call_count == 1

        # 第二次探测相同代理：命中缓存
        status2, ip2 = await probe_proxy_exit(proxy_dict)
        assert status2 == ProxyProbeStatus.OK
        assert ip2 == "2.2.2.2"
        assert mock_proxy_ip.call_count == 1  # 依然是 1，未重复调用


@pytest.mark.asyncio
async def test_probe_proxy_unavailable_is_cached():
    """代理不可达的探测结果同样入缓存，避免每次账号操作都重复阻塞探测。"""
    proxy_dict = {"scheme": "socks5", "hostname": "10.0.0.2", "port": 1080}

    with patch("backend.utils.proxy._fetch_ip_via_proxy", new_callable=AsyncMock) as mock_proxy_ip, \
         patch("backend.utils.proxy.get_host_direct_ip", new_callable=AsyncMock) as mock_host_ip:
        mock_host_ip.return_value = "1.1.1.1"
        mock_proxy_ip.return_value = None  # 两个端点均不可达

        status1, _ = await probe_proxy_exit(proxy_dict)
        assert status1 == ProxyProbeStatus.UNAVAILABLE
        assert mock_proxy_ip.call_count == len(DEFAULT_PROBE_ENDPOINTS)

        status2, _ = await probe_proxy_exit(proxy_dict)
        assert status2 == ProxyProbeStatus.UNAVAILABLE
        # 命中缓存：不再重复探测
        assert mock_proxy_ip.call_count == len(DEFAULT_PROBE_ENDPOINTS)


@pytest.mark.asyncio
async def test_check_account_status_reports_invalid_proxy_as_blocked(tmp_path, monkeypatch):
    """代理字符串非法时必须返回 blocked 状态与稳定错误码，而不是静默降级为直连。"""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    session_dir = tmp_path / "sessions"
    session_dir.mkdir(parents=True)
    workdir = tmp_path / "data"
    workdir.mkdir(parents=True)

    (session_dir / "bad_proxy_acc.session").write_text("dummy")
    set_account_profile("bad_proxy_acc", proxy="not-a-valid-proxy-url")

    tg_svc = DummyTelegramService(session_dir, workdir)

    with patch("backend.services.config.get_config_service", return_value=ConfigService()):
        result = await tg_svc.check_account_status("bad_proxy_acc", timeout_seconds=1.0)

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["code"] == "PROXY_INVALID_BLOCKED"
