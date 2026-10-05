from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from tg_signer.core.plugins import compute_plugin_security_report

FAIL_CLOSED_RULES = {"star-import", "syntax-error", "audit-error"}


def enforce_plugin_security(source_code: str, force: bool = False) -> Dict[str, Any]:
    """统一插件安全门禁。

    检测 Critical/High 风险或不可绕过的 FAIL_CLOSED_RULES 规则（star-import, syntax-error, audit-error）。
    一旦发现阻断级风险，无论 force 是否为 True，直接抛出 HTTP 422 PLUGIN_SECURITY_BLOCKED。
    如果仅存在中低风险警告且未传 force=True，抛出 HTTP 409 PLUGIN_SECURITY_CONFIRMATION_REQUIRED 提示确认。
    """
    sec_report = compute_plugin_security_report(source_code)
    warnings = sec_report.get("warnings", [])

    blocking_warnings = [
        w
        for w in warnings
        if w.get("severity") in {"critical", "high"}
        or w.get("rule") in FAIL_CLOSED_RULES
        or str(w.get("rule", "")).split(":", 1)[0] in FAIL_CLOSED_RULES
    ]

    if blocking_warnings or not sec_report.get("can_save_safely", True):
        # 只要存在阻断级风险，force=True 绝不能越权放行
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PLUGIN_SECURITY_BLOCKED",
                "message": "插件源码包含 Critical/High 严重安全漏洞或语法解析错误，系统拒绝保存",
                "warnings": blocking_warnings or warnings,
            },
        )

    if warnings and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PLUGIN_SECURITY_CONFIRMATION_REQUIRED",
                "message": "插件包含代码质量或中低风险警告，请二次确认后勾选强制保存",
                "warnings": warnings,
            },
        )

    return sec_report
