from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import replace
from typing import Any

from tg_signer.semantic.models import Decision, DecisionRequest

# 敏感词模式匹配（含密钥/密码/认证Token/敏感系统路径）
SENSITIVE_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|passwd|auth|bearer|credentials|private_key|id_rsa|id_ed25519)\b"
    ),
    re.compile(r"(\.env|\.jev_config\.json|/etc/shadow|/etc/passwd|/proc/|~?/\.ssh)"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{6,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{8,}"),
]


def is_sensitive_value(val: Any) -> bool:
    """递归检查值中是否包含密钥或敏感信息"""
    if isinstance(val, str):
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(val):
                return True
    elif isinstance(val, dict):
        for k, v in val.items():
            if is_sensitive_value(k) or is_sensitive_value(v):
                return True
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            if is_sensitive_value(item):
                return True
    return False


def is_sensitive_request(request: DecisionRequest) -> bool:
    """含密钥/敏感路径的请求不进缓存"""
    if is_sensitive_value(request.state):
        return True
    if is_sensitive_value(request.choices):
        return True
    if is_sensitive_value(request.instructions):
        return True
    return False


def compute_cache_key(request: DecisionRequest) -> str:
    """计算缓存键：(规范化 state 摘要 + question 指纹)"""
    # 1. 规范化 state 摘要
    try:
        norm_state = json.dumps(
            request.state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        norm_state = str(request.state)
    state_digest = hashlib.sha256(norm_state.encode("utf-8")).hexdigest()[:16]

    # 2. question 指纹 (kind + 规范化 choices + instructions)
    try:
        norm_choices = json.dumps(
            request.choices,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        norm_choices = str(request.choices)
    q_str = f"{request.kind}|{norm_choices}|{request.instructions.strip()}"
    q_fingerprint = hashlib.sha256(q_str.encode("utf-8")).hexdigest()[:16]

    return f"{state_digest}:{q_fingerprint}"


class JevDecisionCache:
    """JEV 语义决策短 TTL LRU 缓存。

    - 默认 TTL: 60s
    - 容量上限: 500
    - 淘汰策略: LRU
    """

    def __init__(self, maxsize: int = 500, ttl: float = 60.0) -> None:
        self.maxsize = max(1, maxsize)
        self.ttl = max(0.1, ttl)
        self._cache: OrderedDict[str, tuple[float, Decision]] = OrderedDict()
        self.hits: int = 0
        self.misses: int = 0

    def get(self, key: str, now: float | None = None) -> Decision | None:
        if now is None:
            now = time.monotonic()
        if key not in self._cache:
            self.misses += 1
            return None

        entry_time, decision = self._cache[key]
        if now - entry_time > self.ttl:
            # 缓存过期
            del self._cache[key]
            self.misses += 1
            return None

        # 命中并移到 LRU 队尾（最近使用）
        self._cache.move_to_end(key)
        self.hits += 1
        return replace(decision, cache_hit=True)

    def set(self, key: str, decision: Decision, now: float | None = None) -> None:
        if now is None:
            now = time.monotonic()
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.maxsize:
                # 弹出最久未使用项
                self._cache.popitem(last=False)
        self._cache[key] = (now, decision)

    def clear(self) -> None:
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._cache),
            "maxsize": self.maxsize,
            "ttl": self.ttl,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
        }
