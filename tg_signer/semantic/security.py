from __future__ import annotations

import json
import re
from typing import Any

from tg_signer.semantic.models import DecisionRequest

# 超长截断阈值（字节/字符）
MAX_STATE_CHARS: int = 4096
MAX_FIELD_CHARS: int = 2048


def redact_sensitive_text(text: str, key: str | None = None) -> str:
    """脱敏字符串中的密钥、Token 与认证凭据，绝不泄露 key。"""
    if not text:
        return ""
    result = text
    # 精确匹配传入的 api_key
    if key and len(key.strip()) >= 4:
        result = result.replace(key.strip(), "[REDACTED]")

    # Bearer tokens 脱敏
    result = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_\-\.]{6,}",
        r"\1[REDACTED]",
        result,
        flags=re.IGNORECASE,
    )
    # sk- 前缀密钥脱敏
    result = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[REDACTED]", result)
    # 类似 api_key=xxx / secret=xxx 的赋值脱敏
    result = re.sub(
        r"(?i)(api[_-]?key|api[_-]?secret|password|token)\s*[:=]\s*[\"']?[^\s\"',;]+[\"']?",
        r"\1=[REDACTED]",
        result,
    )
    return result


def truncate_state_if_needed(
    state: dict[str, Any],
    max_state_chars: int = MAX_STATE_CHARS,
    max_field_chars: int = MAX_FIELD_CHARS,
) -> tuple[dict[str, Any], bool]:
    """检查并截断过长的 state 字段。

    若字段发生截断，返回 (新 state, True)，否则 (原 state, False)。
    """
    is_truncated = False

    def _truncate_val(val: Any) -> Any:
        nonlocal is_truncated
        if isinstance(val, str):
            if len(val) > max_field_chars:
                is_truncated = True
                return val[:max_field_chars] + "... [TRUNCATED]"
            return val
        elif isinstance(val, dict):
            return {k: _truncate_val(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_truncate_val(item) for item in val]
        return val

    truncated_state = _truncate_val(state)

    try:
        serialized = json.dumps(truncated_state, ensure_ascii=False)
        if len(serialized) > max_state_chars:
            is_truncated = True
    except Exception:
        pass

    return truncated_state, is_truncated


def sanitize_request(request: DecisionRequest) -> DecisionRequest:
    """对 DecisionRequest 进行超长截断与安全性标记。

    若超长则截断并标注 truncated=True。
    """
    new_state, truncated = truncate_state_if_needed(request.state)
    is_truncated = bool(request.truncated or truncated)
    if is_truncated != request.truncated or new_state != request.state:
        from dataclasses import replace

        return replace(request, state=new_state, truncated=is_truncated)
    return request
