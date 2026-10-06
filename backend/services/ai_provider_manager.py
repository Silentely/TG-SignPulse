"""多节点 AI 故障转移引擎（后端兼容再导出）。

实现已下沉到 tg_signer/core/ai_failover.py，供核心包与后端共用；
这里保留原模块路径与公开符号，避免既有导入方（含测试）失效。
"""

from __future__ import annotations

from tg_signer.core.ai_failover import (
    AIAllProvidersFailedError,
    AIProviderConfigError,
    AIProviderManager,
    AIProviderResponseError,
    ProviderConfig,
    as_attribute_object,
    build_provider_configs,
)

__all__ = [
    "AIAllProvidersFailedError",
    "AIProviderConfigError",
    "AIProviderManager",
    "AIProviderResponseError",
    "ProviderConfig",
    "as_attribute_object",
    "build_provider_configs",
]
