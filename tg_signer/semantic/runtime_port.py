from __future__ import annotations

from typing import Any, Callable, Optional

_SEMANTIC_RUNTIME_PROVIDER: Optional[Callable[[], Any]] = None


def register_semantic_runtime_provider(provider: Callable[[], Any]) -> None:
    """注册语义运行时适配器提供函数（通常在 backend 服务层启动时注入，以维持 tg_signer 核心纯洁性）"""
    global _SEMANTIC_RUNTIME_PROVIDER
    _SEMANTIC_RUNTIME_PROVIDER = provider


def get_registered_semantic_runtime() -> Optional[Any]:
    """获取已注入的全局语义运行时实例；若未注入或提供者抛错则返回 None"""
    if _SEMANTIC_RUNTIME_PROVIDER is not None:
        try:
            return _SEMANTIC_RUNTIME_PROVIDER()
        except Exception:
            return None
    return None
