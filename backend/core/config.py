from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, Field

from backend.utils.storage import get_initial_data_dir, get_writable_base_dir


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                values[key] = value
    except OSError:
        return {}
    return values


def _merged_env() -> dict[str, str]:
    return {**_load_env_file(Path(".env")), **os.environ}


def _read_env(
    env: Mapping[str, str],
    *names: str,
    default: Optional[str] = None,
) -> Optional[str]:
    for name in names:
        value = str(env.get(name, "")).strip()
        if value:
            return value
    return default


def _read_int_env(env: Mapping[str, str], *names: str, default: int) -> int:
    raw = _read_env(env, *names)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_path_env(env: Mapping[str, str], *names: str) -> Optional[Path]:
    raw = _read_env(env, *names)
    if raw is None:
        return None
    return Path(raw).expanduser()


def get_default_secret_key(env: Optional[Mapping[str, str]] = None) -> str:
    env_map = env or os.environ
    env_secret = _read_env(env_map, "APP_SECRET_KEY")
    if env_secret:
        return env_secret

    data_dir = _read_path_env(env_map, "APP_DATA_DIR")
    base_dir = data_dir or get_initial_data_dir()
    if str(base_dir) == "/data":
        base_dir = get_writable_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    secret_file = base_dir / ".app_secret_key"

    try:
        existing = secret_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass

    generated = secrets.token_urlsafe(48)
    try:
        secret_file.write_text(generated, encoding="utf-8")
    except OSError:
        pass
    return generated


class Settings(BaseModel):
    app_name: str = "tg-signer-panel"
    host: str = "127.0.0.1"
    port: int = 3000
    cors_allow_origins_raw: str = (
        "http://127.0.0.1:3000,http://localhost:3000"
    )
    secret_key: str = Field(default_factory=get_default_secret_key)
    access_token_expire_hours: int = 12
    timezone: str = "Asia/Hong_Kong"
    data_dir: Path = Field(default_factory=get_initial_data_dir)
    db_path: Optional[Path] = None
    signer_workdir: Optional[Path] = None
    session_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None

    @classmethod
    def from_environment(cls) -> "Settings":
        env = _merged_env()
        return cls(
            app_name=_read_env(env, "APP_APP_NAME", "APP_NAME", default="tg-signer-panel"),
            host=_read_env(env, "APP_HOST", default="127.0.0.1"),
            port=_read_int_env(env, "APP_PORT", default=3000),
            cors_allow_origins_raw=_read_env(
                env,
                "APP_CORS_ALLOW_ORIGINS",
                default="http://127.0.0.1:3000,http://localhost:3000",
            ),
            secret_key=get_default_secret_key(env),
            access_token_expire_hours=_read_int_env(
                env,
                "APP_ACCESS_TOKEN_EXPIRE_HOURS",
                default=12,
            ),
            timezone=_read_env(env, "TZ", "APP_TIMEZONE", default="Asia/Hong_Kong"),
            data_dir=_read_path_env(env, "APP_DATA_DIR") or get_initial_data_dir(),
            db_path=_read_path_env(env, "APP_DB_PATH"),
            signer_workdir=_read_path_env(env, "APP_SIGNER_WORKDIR"),
            session_dir=_read_path_env(env, "APP_SESSION_DIR"),
            logs_dir=_read_path_env(env, "APP_LOGS_DIR"),
        )

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.resolve_db_path()}?check_same_thread=False"

    def resolve_db_path(self) -> Path:
        return self.db_path or self.resolve_base_dir() / "db.sqlite"

    def resolve_workdir(self) -> Path:
        return self.signer_workdir or self.resolve_base_dir() / ".signer"

    def resolve_session_dir(self) -> Path:
        return self.session_dir or self.resolve_base_dir() / "sessions"

    def resolve_logs_dir(self) -> Path:
        return self.logs_dir or self.resolve_base_dir() / "logs"

    def resolve_base_dir(self) -> Path:
        if self.data_dir and str(self.data_dir) != "/data":
            return self.data_dir
        return get_writable_base_dir()

    @property
    def cors_allow_origins(self) -> list[str]:
        origins = [
            item.strip()
            for item in str(self.cors_allow_origins_raw or "").split(",")
            if item.strip()
        ]
        return origins or ["http://127.0.0.1:3000", "http://localhost:3000"]


@lru_cache()
def get_settings() -> Settings:
    return Settings.from_environment()
