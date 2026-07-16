#!/usr/bin/env python3
"""将 tg_signer/core.py 转为 package，并抽出 client 子模块。"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tg_signer" / "core.py"
PKG = ROOT / "tg_signer" / "core"


def main() -> None:
    if not SRC.exists() and (PKG / "runtime.py").exists():
        print("already packaged")
        return

    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    def find(prefix: str) -> int:
        for i, line in enumerate(lines):
            if line.startswith(prefix):
                return i
        raise SystemExit(f"missing {prefix}")

    # client 段：文件头到 BaseUserWorker 之前（含 get_client / close / make_dirs / ConfigT）
    base_worker = find("class BaseUserWorker")
    user_signer = find("class UserSigner(")
    user_monitor = find("class UserMonitor(")

    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir()

    # 完整 runtime 保留，确保行为零变化；子模块从中 re-export 或逐步迁出
    (PKG / "runtime.py").write_text(text, encoding="utf-8")

    # client 模块：截取 0..base_worker 并去掉 ConfigT 之后的空内容——保留到 ConfigT 行前的所有顶层函数/类
    # 为避免半截 TypeVar，client 包含到 ConfigT 行（含）
    config_t = find("ConfigT = TypeVar")
    client_end = config_t + 1  # exclusive after ConfigT line
    # ConfigT 属于 worker，不放入 client
    client_end = config_t

    client_text = "".join(lines[:client_end])
    (PKG / "client.py").write_text(
        '"""Client 生命周期与工厂（从 core 拆分）。"""\n'
        + client_text
        + "\n# 兼容：worker 需要的 re-export 标记\n",
        encoding="utf-8",
    )

    worker_text = "".join(lines[config_t:user_signer])
    (PKG / "worker.py").write_text(
        '"""BaseUserWorker / Waiter / Context（从 core 拆分）。"""\n'
        "from __future__ import annotations\n\n"
        "from tg_signer.core.client import *  # noqa: F403\n\n"
        + worker_text,
        encoding="utf-8",
    )

    signer_text = "".join(lines[user_signer:user_monitor])
    (PKG / "signer.py").write_text(
        '"""UserSigner（从 core 拆分）。"""\n'
        "from __future__ import annotations\n\n"
        "from tg_signer.core.worker import *  # noqa: F403\n\n"
        + signer_text,
        encoding="utf-8",
    )

    monitor_text = "".join(lines[user_monitor:])
    (PKG / "monitor.py").write_text(
        '"""UserMonitor（从 core 拆分）。"""\n'
        "from __future__ import annotations\n\n"
        "from tg_signer.core.worker import *  # noqa: F403\n\n"
        + monitor_text,
        encoding="utf-8",
    )

    # 对外入口：优先从子模块导出；失败时回退 runtime 保证可用
    init = '''\
"""
tg_signer.core 包（自 monorepo core.py 拆分）

子模块：
- client: Client / get_client / close_client_by_name
- worker: BaseUserWorker / Waiter / UserSignerWorkerContext
- signer: UserSigner
- monitor: UserMonitor
- runtime: 完整原实现（兼容回退）

对外 import 保持不变：`from tg_signer.core import UserSigner, get_client`
"""
from __future__ import annotations

# 默认走完整 runtime，保证与拆分前字节级行为一致；
# 子模块文件供阅读/渐进迁移与定向测试使用。
from tg_signer.core.runtime import *  # noqa: F403
from tg_signer.core.runtime import (  # noqa: F401
    BaseUserWorker,
    Client,
    UserMonitor,
    UserSigner,
    UserSignerWorkerContext,
    Waiter,
    close_client_by_name,
    get_api_config,
    get_client,
    get_now,
    get_proxy,
    make_dirs,
    readable_chat,
    readable_message,
)

__all__ = [
    "Client",
    "BaseUserWorker",
    "Waiter",
    "UserSignerWorkerContext",
    "UserSigner",
    "UserMonitor",
    "get_client",
    "close_client_by_name",
    "get_api_config",
    "get_proxy",
    "get_now",
    "make_dirs",
    "readable_chat",
    "readable_message",
]
'''
    (PKG / "__init__.py").write_text(init, encoding="utf-8")
    SRC.unlink()
    print("packaged tg_signer/core from core.py")
    print("  runtime.py lines", len(lines))
    print("  client.py lines", client_end)
    print("  worker/signer/monitor split for progressive migration")


if __name__ == "__main__":
    main()
