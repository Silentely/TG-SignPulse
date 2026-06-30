from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Monkeypatch sqlite3.connect to increase default timeout
_original_sqlite3_connect = sqlite3.connect


def _patched_sqlite3_connect(*args, **kwargs):
    # Force timeout to be at least 10 seconds, even if Pyrogram sets it to 1
    if "timeout" in kwargs:
        if kwargs["timeout"] < 10:
            kwargs["timeout"] = 10
    else:
        kwargs["timeout"] = 30
    return _original_sqlite3_connect(*args, **kwargs)


sqlite3.connect = _patched_sqlite3_connect

from backend.api import router as api_router  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.database import (  # noqa: E402
    Base,
    get_engine,
    get_session_local,
    init_engine,
)
from backend.scheduler import (  # noqa: E402
    init_scheduler,
    shutdown_scheduler,
    sync_jobs,
)
from backend.services.users import ensure_admin  # noqa: E402
from backend.utils.paths import ensure_data_dirs  # noqa: E402
from tg_signer.async_utils import create_logged_task  # noqa: E402


# Silence /health check logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return (
            "/health" not in msg
            and "/healthz" not in msg
            and "/readyz" not in msg
        )


class AccessLogLevelFilter(logging.Filter):
    """将 uvicorn access log 的级别从 INFO 强制转换为 DEBUG"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.INFO:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


# 配置后端日志等级，支持 LOG_LEVEL 环境变量
def _configure_backend_logging():
    """配置后端日志等级，从环境变量 LOG_LEVEL 读取，默认为 INFO

    日志等级说明：
    - DEBUG: 详细的调试信息，包括 uvicorn 访问日志（过滤健康检查端点）
    - INFO: 应用常规运行信息（默认）
    - WARNING: 警告信息
    - ERROR: 错误信息
    - CRITICAL: 严重错误

    访问日志处理：
    直接删除 uvicorn.access 的所有 handler，从根源禁用访问日志输出。
    DEBUG 模式下重新启用，但过滤健康检查端点以减少噪音。
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    level_no = logging.getLevelName(log_level)

    # 验证日志等级有效性
    if not isinstance(level_no, int):
        logging.warning(f"Invalid LOG_LEVEL '{log_level}', falling back to INFO")
        level_no = logging.INFO

    # 配置根日志器和主要模块日志器
    root = logging.getLogger()
    root.setLevel(level_no)
    # 确保 root logger 有 handler，否则 INFO 级别消息会被 lastResort 静默丢弃
    if not root.handlers:
        _handler = logging.StreamHandler()
        _handler.setLevel(level_no)
        _handler.setFormatter(logging.Formatter(
            "[%(levelname)s] [%(name)s] %(asctime)s - %(message)s"
        ))
        root.addHandler(_handler)
    logging.getLogger("backend").setLevel(level_no)
    logging.getLogger("uvicorn").setLevel(level_no)

    # 暴力删除 uvicorn.access 的所有 handler，从根源禁用
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

    # 只在 DEBUG 模式下重新启用访问日志
    if level_no <= logging.DEBUG:
        access_logger.disabled = False
        access_logger.setLevel(logging.DEBUG)
        # DEBUG 模式下过滤健康检查端点，减少日志噪音
        access_logger.addFilter(HealthCheckFilter())
        # 将 INFO 级别的访问日志强制转换为 DEBUG
        access_logger.addFilter(AccessLogLevelFilter())
        # 添加 stderr handler 输出访问日志（使用详细格式）
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "[%(levelname)s] [%(name)s] %(asctime)s - %(message)s"
        ))
        access_logger.addHandler(handler)


# 注意：不在此处调用 _configure_backend_logging()
# 因为 uvicorn 启动后会重置 logging 配置，需要在 on_startup 事件中重新配置

settings = get_settings()

@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    await on_startup()
    try:
        yield
    finally:
        await on_shutdown()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.state.ready = False


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器：仅捕获未处理的异常，不拦截 HTTPException"""
    # FastAPI 的 HTTPException（401/403/404 等）应由框架正常处理
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    if isinstance(exc, FastAPIHTTPException):
        raise exc

    logging.getLogger("backend.exception").error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error"},
    )

app.add_middleware(GZipMiddleware, minimum_size=1000)



app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# API 路由必须在静态文件挂载之前注册，并使用 /api 前缀
app.include_router(api_router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def health_checkz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def ready_check(response: Response) -> dict[str, str]:
    if app.state.ready:
        return {"status": "ready"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "starting"}


# 静态前端托管（Mode A: 单容器，FastAPI 提供静态文件）
# 挂载 Next.js 静态资源
web_dir = Path("/web")
next_static_dir = web_dir / "_next"
frontend_dev_url = os.getenv("FRONTEND_DEV_SERVER_URL", "http://127.0.0.1:3000")

if next_static_dir.exists():
    app.mount(
        "/_next",
        StaticFiles(directory=str(next_static_dir)),
        name="nextjs_static",
    )


def _resolve_web_file(full_path: str) -> Path | None:
    """安全解析文件路径，防止路径遍历攻击"""
    web_root = web_dir.resolve()
    candidate = (web_root / full_path).resolve()
    try:
        candidate.relative_to(web_root)
    except ValueError:
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


# Catch-all 路由：处理所有前端路由，返回 index.html
# 注意：FastAPI 的 /docs、/redoc、/openapi.json 在此路由之前已自动注册，
# 因此不会被此 catch-all 拦截。无需额外排除。


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    SPA fallback: 对于所有非 API 路由，返回 index.html
    这样刷新页面时不会 404
    """
    # 检查是否是静态文件请求（带路径遍历防护）
    file_path = _resolve_web_file(full_path)
    if file_path is not None:
        return FileResponse(file_path)

    # 尝试添加 .html 后缀
    html_path = _resolve_web_file(f"{full_path}.html")
    if html_path is not None:
        return FileResponse(html_path)

    # 否则返回 index.html（SPA 路由）
    index_path = web_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    # 如果 index.html 也不存在，开发模式下重定向到前端开发服务器，生产环境返回 404
    if os.getenv("FRONTEND_DEV_SERVER_URL"):
        normalized_path = full_path if full_path.startswith("/") else f"/{full_path}"
        if not normalized_path:
            normalized_path = "/"

        parsed_frontend = urlsplit(frontend_dev_url)
        redirect_target = urlunsplit(
            (
                parsed_frontend.scheme,
                parsed_frontend.netloc,
                normalized_path,
                "",
                "",
            )
        )
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return Response(content="Not Found", status_code=status.HTTP_404_NOT_FOUND)


async def on_startup() -> None:
    # 重新应用日志配置（uvicorn 启动后会重新配置 logging，覆盖之前的设置）
    _configure_backend_logging()

    # 版本标记
    _git_branch = os.getenv("GIT_BRANCH", "dev")
    _git_sha = os.getenv("GIT_SHA", "dev")[:7]
    logging.getLogger("backend.startup").info(
        "TG-SignPulse version=%s-%s", _git_branch, _git_sha
    )

    ensure_data_dirs(settings)
    init_engine()
    Base.metadata.create_all(bind=get_engine())
    with get_session_local()() as db:
        ensure_admin(db)
    await init_scheduler(sync_on_startup=False)

    # Pre-export session strings from .session files to avoid SQLite locks during task execution
    _pre_export_session_strings()

    async def _post_startup() -> None:
        try:
            await sync_jobs()
            from backend.services.keyword_monitor import get_keyword_monitor_service

            await get_keyword_monitor_service().restart_from_tasks()
        except Exception as exc:
            logging.getLogger("backend.startup").error(
                f"Delayed scheduler sync failed: {exc}"
            )
        finally:
            app.state.ready = True

    app.state.startup_task = create_logged_task(
        _post_startup(),
        logger=logging.getLogger("backend.startup"),
        description="backend delayed startup sync",
    )


def _pre_export_session_strings() -> None:
    """Export session strings from all .session files at startup to enable in-memory mode."""
    from backend.utils.tg_session import (
        get_session_mode,
        load_session_string_file,
    )

    session_dir = settings.resolve_session_dir()
    logger = logging.getLogger("backend.startup")

    # Clean up any stray "*" directories (legacy bug from update_task wildcard handling)
    try:
        signs_dir = settings.resolve_workdir() / "signs"
        wildcard_dir = signs_dir / "*"
        if wildcard_dir.exists() and wildcard_dir.is_dir():
            import shutil
            shutil.rmtree(wildcard_dir)
            logger.info("Cleaned up stray '*' task directory")
    except Exception as exc:
        logger.warning(f"Failed to clean wildcard dir: {exc}")

    # Only needed in file mode - string mode already has session strings
    if get_session_mode() == "string":
        return

    # Export for all accounts that have .session files
    exported = 0
    for session_file in session_dir.glob("*.session"):
        account_name = session_file.stem
        # load_session_string_file will auto-export if .session_string doesn't exist
        result = load_session_string_file(session_dir, account_name)
        if result:
            exported += 1

    if exported:
        logger.info(f"Pre-exported {exported} session strings for in-memory task execution")


async def on_shutdown() -> None:
    startup_task = getattr(app.state, "startup_task", None)
    if startup_task is not None and not startup_task.done():
        startup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await startup_task
    shutdown_scheduler()
    try:
        from backend.services.keyword_monitor import get_keyword_monitor_service

        await get_keyword_monitor_service().stop()
    except Exception:
        logging.getLogger("backend.shutdown").exception("Keyword monitor shutdown failed")
