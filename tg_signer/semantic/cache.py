from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time
import urllib.parse
from collections import Counter, OrderedDict
from dataclasses import replace
from typing import Any

from tg_signer.semantic.models import Decision, DecisionRequest

# 敏感词模式匹配（含密钥/密码/认证Token/敏感系统路径，支持蛇形与驼峰）
SENSITIVE_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|apiKey|access[_-]?token|accessToken|client[_-]?secret|clientSecret|"
        r"secret[_-]?key|secretKey|auth[_-]?token|authToken|refresh[_-]?token|refreshToken|"
        r"password|passwd|credentials|private[_-]?key|privateKey|id_rsa|id_ed25519)\b"
    ),
    re.compile(r"(\.env|\.jev_config\.json|/etc/shadow|/etc/passwd|/proc/|~?/\.ssh)"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{6,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{8,}"),
]

SENSITIVE_KEY_NAMES = frozenset(
    {
        "apikey",
        "accesstoken",
        "clientsecret",
        "secretkey",
        "authtoken",
        "refreshtoken",
        "password",
        "passwd",
        "credentials",
        "privatekey",
        "secret",
        "token",
    }
)


def shannon_entropy(data: str) -> float:
    """计算字符串的香农信息熵。"""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    for count in Counter(data).values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def is_high_entropy_opaque_string(s: str) -> bool:
    """检测是否为高熵不透明凭据（如随机 API Token、Hex Hash、Base64 密文）。"""
    s = s.strip()
    if not s or " " in s or "\n" in s or "\t" in s:
        return False
    if len(s) >= 16 and re.fullmatch(r"[\x21-\x7e]+", s):
        ent = shannon_entropy(s)
        # 32位以上 Hex/字符 且熵 >= 3.4
        if len(s) >= 32 and ent >= 3.4:
            return True
        # 16位以上且熵 >= 3.5
        if len(s) >= 16 and ent >= 3.5:
            return True
    return False


def _check_text_sensitive(text: str) -> bool:
    if not text:
        return False
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True
    if is_high_entropy_opaque_string(text):
        return True
    return False


def is_sensitive_value(val: Any) -> bool:
    """递归检查值中是否包含密钥或敏感信息（支持 URL 解码、Base64 解码与高熵检测）。"""
    if isinstance(val, str):
        # 1. 原始文本检查
        if _check_text_sensitive(val):
            return True

        # 2. URL 解码检查
        if "%" in val:
            try:
                unquoted = urllib.parse.unquote(val)
                if unquoted != val and _check_text_sensitive(unquoted):
                    return True
            except Exception:
                pass

        # 3. Base64 解码检查
        cleaned_b64 = val.strip()
        if len(cleaned_b64) >= 12 and re.fullmatch(r"[A-Za-z0-9+/=_\-]+", cleaned_b64):
            try:
                # 标准 base64 或 urlsafe base64 补齐
                pad_len = (4 - len(cleaned_b64) % 4) % 4
                padded = cleaned_b64 + ("=" * pad_len)
                decoded_bytes = base64.b64decode(padded, validate=False)
                decoded_str = decoded_bytes.decode("utf-8", errors="ignore")
                if len(decoded_str) >= 4 and _check_text_sensitive(decoded_str):
                    return True
            except Exception:
                pass

        # 4. 内嵌 JSON 检查
        if (val.startswith("{") and val.endswith("}")) or (val.startswith("[") and val.endswith("]")):
            try:
                parsed = json.loads(val)
                if is_sensitive_value(parsed):
                    return True
            except Exception:
                pass

    elif isinstance(val, dict):
        for k, v in val.items():
            k_norm = str(k).lower().replace("_", "").replace("-", "")
            if k_norm in SENSITIVE_KEY_NAMES:
                return True
            if is_sensitive_value(k) or is_sensitive_value(v):
                return True
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            if is_sensitive_value(item):
                return True
    return False


def is_sensitive_request(request: DecisionRequest) -> bool:
    """含密钥/敏感路径/高熵不透明凭据的请求不进缓存。"""
    if is_sensitive_value(request.state):
        return True
    if is_sensitive_value(request.choices):
        return True
    if is_sensitive_value(request.instructions):
        return True
    return False


def compute_cache_key(
    request: DecisionRequest,
    model: str = "",
    base_url: str = "",
) -> str:
    """计算缓存键：包含 scope/任务、model、base_url、config_revision、规范化 state 摘要与 question 指纹。"""
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

    # 3. 维度复合哈希（scope, revision, model, base_url）
    scope = request.scope or ""
    rev = request.config_revision or ""
    prefix = f"{scope}|{rev}|{model.strip()}|{base_url.strip()}"
    prefix_digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]

    return f"{prefix_digest}:{state_digest}:{q_fingerprint}"


class JevDecisionCache:
    """JEV 语义决策短 TTL LRU 缓存。

    - 默认 TTL: 60s
    - 容量上限: 500
    - 淘汰策略: LRU
    - 支持命名空间隔离（配置代际切换时建立全新命名空间）
    """

    def __init__(self, maxsize: int = 500, ttl: float = 60.0, namespace: str = "") -> None:
        self.maxsize = max(1, maxsize)
        self.ttl = max(0.1, ttl)
        self.namespace = namespace
        self._cache: OrderedDict[str, tuple[float, Decision]] = OrderedDict()
        self.hits: int = 0
        self.misses: int = 0

    def _qualify_key(self, key: str) -> str:
        if self.namespace:
            return f"{self.namespace}:{key}"
        return key

    def get(self, key: str, now: float | None = None) -> Decision | None:
        q_key = self._qualify_key(key)
        if now is None:
            now = time.monotonic()
        if q_key not in self._cache:
            self.misses += 1
            return None

        entry_time, decision = self._cache[q_key]
        if now - entry_time > self.ttl:
            # 缓存过期
            del self._cache[q_key]
            self.misses += 1
            return None

        # 命中并移到 LRU 队尾（最近使用）
        self._cache.move_to_end(q_key)
        self.hits += 1
        return replace(decision, cache_hit=True)

    def set(self, key: str, decision: Decision, now: float | None = None) -> None:
        q_key = self._qualify_key(key)
        if now is None:
            now = time.monotonic()
        if q_key in self._cache:
            self._cache.move_to_end(q_key)
        else:
            if len(self._cache) >= self.maxsize:
                # 弹出最久未使用项
                self._cache.popitem(last=False)
        self._cache[q_key] = (now, decision)

    def with_namespace(self, namespace: str) -> JevDecisionCache:
        """派生或创建指定命名空间的缓存实例。"""
        sub = JevDecisionCache(maxsize=self.maxsize, ttl=self.ttl, namespace=namespace)
        sub._cache = self._cache
        return sub

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
            "namespace": self.namespace,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
        }
