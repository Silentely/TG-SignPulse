from pathlib import Path

from backend.core.config import Settings


def ensure_data_dirs(settings: Settings) -> None:
    base = settings.resolve_base_dir()
    base.mkdir(parents=True, exist_ok=True)
    (settings.resolve_workdir()).mkdir(parents=True, exist_ok=True)
    (settings.resolve_session_dir()).mkdir(parents=True, exist_ok=True)
    (settings.resolve_logs_dir()).mkdir(parents=True, exist_ok=True)

    db_path: Path = settings.resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

def is_safe_subpath(parent: Path, child: Path) -> bool:
    """检验 child 是否为 parent 内部的安全子路径（防止符号链接逃逸与跨目录穿越）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, RuntimeError):
        return False

