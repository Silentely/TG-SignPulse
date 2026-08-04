"""拆分包 import 健康检查。

防止再出现：
1. `import *` 漏掉下划线私有名（accounts NameError）
2. core 子模块 star-import 残缺导致 import 即 NameError
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

CRITICAL_MODULES = [
    "backend.main",
    "backend.api.routes.accounts",
    "backend.api.routes.accounts_schemas",
    "backend.api.routes.logs",
    "backend.api.routes.sign_tasks_v2",
    "backend.services.sign_tasks",
    "backend.services.telegram",
    "backend.services.keyword_monitor",
    "backend.services.keyword_monitor.runtime",
    "tg_signer.core",
    "tg_signer.core.client",
    "tg_signer.core.runtime",
    "tg_signer.cli.signer",
    "tg_signer.cli.monitor",
]


@pytest.mark.parametrize("module_name", CRITICAL_MODULES)
def test_critical_module_imports(module_name: str):
    importlib.import_module(module_name)


def test_accounts_extract_helper_is_bound_on_routes_module():
    """回归：schemas 私有 helper 必须显式导入到 accounts 路由。"""
    accounts = importlib.import_module("backend.api.routes.accounts")
    schemas = importlib.import_module("backend.api.routes.accounts_schemas")

    assert hasattr(accounts, "_extract_last_bot_message")
    assert accounts._extract_last_bot_message is schemas._extract_last_bot_message
    assert accounts._extract_last_bot_message({"last_target_message": "ok"}) == "ok"


def test_core_package_reexports_runtime_identity():
    """core 包级 re-export 必须与 runtime 真源保持同一对象。"""
    runtime = importlib.import_module("tg_signer.core.runtime")
    client = importlib.import_module("tg_signer.core.client")
    core = importlib.import_module("tg_signer.core")
    monitor = importlib.import_module("tg_signer.core.monitor")

    assert core.BaseUserWorker is runtime.BaseUserWorker
    assert core.UserSigner is runtime.UserSigner
    assert core.UserMonitor is monitor.UserMonitor
    assert core.Client is client.Client


def test_keyword_monitor_private_helpers_injected():
    """rules 私有函数经 injection 后须可在 runtime 命名空间访问。"""
    runtime = importlib.import_module("backend.services.keyword_monitor.runtime")
    rules = importlib.import_module("backend.services.keyword_monitor.rules")

    assert hasattr(runtime, "_extract_tg_start_links")
    assert runtime._extract_tg_start_links is rules._extract_tg_start_links
    assert hasattr(runtime, "_parse_keywords")
    assert hasattr(runtime, "_message_text")


def test_backend_and_tg_signer_package_walk_imports():
    """全量 walk import：任一子模块 import 失败即视为带病。"""
    failed: list[str] = []
    for pkg_name in ("backend", "tg_signer"):
        pkg = importlib.import_module(pkg_name)
        if not hasattr(pkg, "__path__"):
            continue
        for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
            try:
                importlib.import_module(info.name)
            except Exception as exc:  # noqa: BLE001 — 收集全部失败再断言
                failed.append(f"{info.name}: {type(exc).__name__}: {exc}")

    assert not failed, "import failed:\n" + "\n".join(failed)
