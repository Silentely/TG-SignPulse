from typing import Any

from pydantic import BaseModel, Field, root_validator, validator

from tg_signer.semantic.client import normalize_base_url


class JevServiceConfig(BaseModel):
    enabled: bool = False
    drift_enabled: bool = False
    mode: str = "official"  # "official" | "custom"
    base_url: str = "https://api.typesafe.ai/v1"
    model: str = "jev-1.13.0"
    api_key: str = ""
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)
    max_concurrency: int = Field(default=2, ge=1, le=5)
    max_calls_per_run: int = Field(default=6, ge=0, le=30)
    max_calls_per_minute: int = Field(default=60, ge=0, le=600)
    retain_evidence: bool = False
    generation: int = 0

    @root_validator(pre=True)
    def handle_backward_compatibility(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            return values
        # 向后兼容老配置：若缺失 mode 字段，根据 base_url 是否非官方判断为 custom 还是 official
        if "mode" not in values or not values.get("mode"):
            b_url = values.get("base_url")
            if b_url and str(b_url).rstrip("/") != "https://api.typesafe.ai/v1":
                values["mode"] = "custom"
            else:
                values["mode"] = "official"
        return values

    @validator("base_url", pre=True, always=True)
    def validate_base_url(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            return "https://api.typesafe.ai/v1"
        return normalize_base_url(v)
