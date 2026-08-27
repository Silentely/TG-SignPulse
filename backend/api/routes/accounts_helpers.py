"""
账号路由纯函数：状态检测名单规范化、超时钳制、改名目标解析。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("backend.accounts_helpers")


def normalize_unique_account_names(
    raw_names: Optional[Sequence[Any]],
    *,
    fallback_names: Optional[Iterable[Any]] = None,
) -> List[str]:
    """去空白、去重，保持首次出现顺序；raw 为空时用 fallback。"""
    source: Iterable[Any]
    if raw_names:
        source = raw_names
    elif fallback_names is not None:
        source = fallback_names
    else:
        source = []

    names: List[str] = []
    seen: set[str] = set()
    for name in source:
        normalized = str(name or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return names


def clamp_status_check_timeout(
    timeout_seconds: Any,
    *,
    default: float = 8.0,
    minimum: float = 1.0,
    maximum: float = 20.0,
) -> float:
    """状态检测单账号超时钳制。"""
    try:
        value = float(timeout_seconds if timeout_seconds is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def build_status_check_error_item(account_name: str, exc: BaseException) -> Dict[str, Any]:
    """单账号状态检测异常时的统一结果字典。"""
    return {
        "account_name": account_name,
        "ok": False,
        "status": "error",
        "message": str(exc) or "status check failed",
        "code": "STATUS_CHECK_FAILED",
        "checked_at": None,
        "needs_relogin": False,
    }


def resolve_account_rename_target(
    current_name: str,
    new_account_name: Optional[str],
) -> Tuple[str, bool]:
    """
    解析更新账号时的目标名。

    返回 (target_name, renamed)。
    """
    actual = str(current_name or "").strip()
    if isinstance(new_account_name, str) and new_account_name.strip():
        target = new_account_name.strip()
    else:
        target = actual
    return target, target != actual


def find_account_by_name(
    accounts: Sequence[Dict[str, Any]],
    account_name: str,
) -> Optional[Dict[str, Any]]:
    """按 name 大小写不敏感查找账号字典。"""
    want = str(account_name or "").strip().lower()
    if not want:
        return None
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        if str(acc.get("name") or "").strip().lower() == want:
            return acc
    return None


def qr_uri_to_data_url(qr_uri: str) -> Optional[str]:
    """将扫码登录 URI 渲染为 PNG data URL；依赖缺失或失败返回 None。"""
    text = str(qr_uri or "").strip()
    if not text:
        return None
    try:
        import base64
        from io import BytesIO

        import qrcode

        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(
            "utf-8"
        )
    except Exception as exc:
        # 渲染失败前端只得 qr_image=null 且无服务端线索；留 debug 便于排查
        logger.debug("扫码登录二维码渲染失败: %s", exc, exc_info=True)
        return None
