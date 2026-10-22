import urllib.parse
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from backend.core.auth import get_current_user
from backend.core.config import get_settings
from backend.services.semantic.config import JevConfigStore
from backend.services.semantic.store import SemanticStore
from backend.services.sign_tasks import get_sign_task_service
from tg_signer.semantic.client import JevClient
from tg_signer.semantic.models import DecisionRequest
from tg_signer.semantic.security import redact_sensitive_text, validate_ssrf_and_host

router = APIRouter(prefix="/semantic", tags=["semantic"])


def get_jev_store() -> JevConfigStore:
    workdir = get_settings().resolve_workdir()
    return JevConfigStore(workdir)


def get_semantic_store() -> SemanticStore:
    workdir = get_settings().resolve_workdir()
    return SemanticStore(workdir)


@router.get("/config")
def get_config(
    store: JevConfigStore = Depends(get_jev_store),
    sem_store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    sanitized = store.get_sanitized_config()
    sanitized["monitor_keys_usage"] = sem_store.get_capacity_stats()
    from backend.services.semantic.runtime import get_active_semantic_runtime

    runtime = get_active_semantic_runtime()
    if runtime:
        sanitized["stats"] = runtime.get_stats()
    return sanitized


@router.get("/stats")
def get_stats(
    _: Any = Depends(get_current_user),
):
    from backend.services.semantic.runtime import get_active_semantic_runtime

    runtime = get_active_semantic_runtime()
    if runtime:
        return runtime.get_stats()
    return {
        "total_calls": 0,
        "success_calls": 0,
        "failed_calls": 0,
        "escalate_calls": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_hit_rate": 0.0,
        "breaker": {"state": "closed", "consecutive_failures": 0},
        "cache": {"size": 0, "hits": 0, "misses": 0, "hit_rate": 0.0},
    }


@router.patch("/config")
def update_config(
    patch: dict[str, Any] = Body(...),
    store: JevConfigStore = Depends(get_jev_store),
    sem_store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    try:
        store.save_patch(patch)
        sanitized = store.get_sanitized_config()
        sanitized["monitor_keys_usage"] = sem_store.get_capacity_stats()
        from backend.services.semantic.runtime import get_active_semantic_runtime

        runtime = get_active_semantic_runtime()
        if runtime:
            sanitized["stats"] = runtime.get_stats()
        return sanitized
    except Exception as e:
        safe_detail = redact_sensitive_text(str(e))
        raise HTTPException(status_code=422, detail=safe_detail)


@router.post("/test")
async def test_connection(
    body: dict[str, Any] | None = Body(default=None),
    store: JevConfigStore = Depends(get_jev_store),
    _: Any = Depends(get_current_user),
):
    cfg = store.load()
    payload = body or {}
    req_base_url = payload.get("base_url") or cfg.base_url
    raw_api_key = payload.get("api_key")
    req_api_key = (
        raw_api_key.strip()
        if isinstance(raw_api_key, str) and raw_api_key.strip()
        else None
    )

    # 1. 目标 URL SSRF 检查
    is_valid, ssrf_err = validate_ssrf_and_host(req_base_url)
    if not is_valid:
        raise HTTPException(status_code=400, detail=ssrf_err)

    # 2. 凭据外送面保护：只有显式提供 api_key 才允许自定义 base_url；否则 base_url 的 host 必须与已保存配置一致，不一致直接 400
    if not req_api_key:
        cfg_host = (urllib.parse.urlparse(cfg.base_url).hostname or "").lower()
        req_host = (urllib.parse.urlparse(req_base_url).hostname or "").lower()
        if cfg_host != req_host:
            raise HTTPException(
                status_code=400,
                detail=f"UNTRUSTED_HOST: Custom base_url '{req_base_url}' requires explicit api_key. Cannot forward saved key to host '{req_host}'.",
            )
        api_key = cfg.api_key
    else:
        api_key = req_api_key

    if not api_key:
        raise HTTPException(status_code=400, detail="MISSING_API_KEY")

    model = payload.get("model") or cfg.model
    timeout = float(payload.get("timeout_seconds") or cfg.timeout_seconds)

    client = JevClient(
        api_key=api_key,
        base_url=req_base_url,
        model=model,
        timeout=timeout,
        is_saved_key=not bool(req_api_key),
    )
    req = DecisionRequest(
        kind="result",
        scope="test",
        state={"text": "PING"},
        choices={"pong": "文本包含 PING", "other": "其他文本"},
        instructions="Say pong",
        request_key="test_key",
        config_revision="test_rev",
    )
    try:
        decision = await client.query_choice(req)
        await client.close()
        success = decision.status == "ok"
        http_status = decision.http_status or (200 if success else None)
        error_summary = decision.error_message or decision.reason_code or ""
        return {
            "success": success,
            "status": decision.status,
            "http_status": http_status,
            "selected": decision.selected,
            "elapsed_ms": decision.elapsed_ms,
            "reason_code": decision.reason_code,
            "error_message": error_summary,
        }
    except Exception as exc:
        await client.close()
        safe_msg = redact_sensitive_text(f"{type(exc).__name__}: {exc}", api_key)
        return {
            "success": False,
            "status": "invalid",
            "http_status": None,
            "selected": "unknown",
            "elapsed_ms": 0.0,
            "reason_code": f"EXCEPTION_{type(exc).__name__}",
            "error_message": safe_msg,
        }


@router.get("/observations")
def list_observations(
    account_name: str = Query(""),
    task_name: str = Query(""),
    kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    scope = f"{account_name}:{task_name}" if (account_name or task_name) else ""
    return store.list_observations(scope=scope, kind=kind, limit=limit, offset=offset)


@router.put("/observations/{id}/label")
def label_observation(
    id: str,
    body: dict[str, Any] = Body(...),
    store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    account_name = body.get("account_name", "")
    task_name = body.get("task_name", "")
    label = body.get("label")
    if not label or not isinstance(label, str) or len(label) > 64:
        raise HTTPException(status_code=422, detail="INVALID_OR_MISSING_LABEL")

    scope = f"{account_name}:{task_name}" if (account_name or task_name) else ""
    reviewer_intent = body.get("reviewer_intent")
    if reviewer_intent and len(str(reviewer_intent)) > 1000:
        raise HTTPException(status_code=422, detail="REVIEWER_INTENT_TOO_LONG")

    try:
        return store.label(id, scope=scope, label=label)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="OBSERVATION_NOT_FOUND")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/suggestions")
def list_suggestions(
    account_name: str = Query(""),
    task_name: str = Query(""),
    status: str = Query(""),
    store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    scope = f"{account_name}:{task_name}" if (account_name or task_name) else ""
    return store.list_suggestions(scope=scope, status=status)


@router.post("/suggestions/{id}/dismiss")
def dismiss_suggestion(
    id: str,
    body: dict[str, Any] | None = Body(default=None),
    store: SemanticStore = Depends(get_semantic_store),
    _: Any = Depends(get_current_user),
):
    payload = body or {}
    account_name = payload.get("account_name", "")
    task_name = payload.get("task_name", "")
    scope = f"{account_name}:{task_name}" if (account_name or task_name) else ""
    try:
        return store.dismiss(id, scope=scope)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="SUGGESTION_NOT_FOUND")
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/suggestions/{id}/apply")
def apply_suggestion(
    id: str,
    background_tasks: BackgroundTasks,
    body: dict[str, Any] | None = Body(default=None),
    store: SemanticStore = Depends(get_semantic_store),
    sign_task_service: Any = Depends(get_sign_task_service),
    current_user: Any = Depends(get_current_user),
):
    from backend.services.task_config_io import TaskConfigConflict

    suggestion = store.get_suggestion(id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="SUGGESTION_NOT_FOUND")

    if suggestion.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"SUGGESTION_NOT_PENDING: 建议当前状态为 {suggestion.get('status')}，不可重复应用",
        )

    payload = body or {}
    base_revision = suggestion.get("base_revision") or ""
    patch = suggestion.get("patch") or {}

    expected_acc = suggestion.get("account_name") or ""
    expected_task = suggestion.get("task_name") or ""
    if not expected_acc or not expected_task:
        scope = suggestion.get("scope", "")
        if ":" in scope:
            parts = scope.split(":")
            expected_acc, expected_task = parts[0], parts[1]

    req_acc = payload.get("account_name")
    req_task = payload.get("task_name")
    if req_acc and req_acc != expected_acc:
        raise HTTPException(
            status_code=400,
            detail=f"ACCOUNT_MISMATCH: Suggestion targets account '{expected_acc}', cannot apply to '{req_acc}'",
        )
    if req_task and req_task != expected_task:
        raise HTTPException(
            status_code=400,
            detail=f"TASK_MISMATCH: Suggestion targets task '{expected_task}', cannot apply to '{req_task}'",
        )

    account_name = expected_acc
    task_name = expected_task
    if not account_name or not task_name:
        raise HTTPException(status_code=422, detail="MISSING_TARGET_TASK")

    username = (
        current_user.get("username", "user")
        if isinstance(current_user, dict)
        else "user"
    )

    try:
        updated_task = sign_task_service.apply_semantic_patch(
            account_name=account_name,
            task_name=task_name,
            expected_revision=base_revision,
            patch=patch,
        )
    except TaskConfigConflict as e:
        raise HTTPException(
            status_code=409,
            detail=f"SEMANTIC_CONFIG_CHANGED: 任务配置已被修改，建议已失效，请重新审阅 ({e})",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"APPLY_FAILED: {e}") from e

    store.mark_suggestion_applied(id, applied_by=username)

    async def _safe_background_sync() -> None:
        try:
            from backend.services.sync_helpers import sync_jobs_and_restart_monitors

            await sync_jobs_and_restart_monitors(context="语义建议应用")
        except Exception as exc:
            import logging

            logging.getLogger("backend.semantic_api").warning(
                "语义建议应用后同步失败: %s", exc
            )

    background_tasks.add_task(_safe_background_sync)

    return {
        "status": "applied",
        "suggestion_id": id,
        "task": updated_task,
    }
