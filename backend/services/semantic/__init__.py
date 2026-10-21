from pydantic import BaseModel, Field


class JevServiceConfig(BaseModel):
    enabled: bool = False
    drift_enabled: bool = False
    base_url: str = "https://api.typesafe.ai/v1"
    model: str = "jev-1.13.0"
    api_key: str = ""
    timeout_seconds: float = Field(default=5.0, ge=1.0, le=15.0)
    max_concurrency: int = Field(default=2, ge=1, le=5)
    max_calls_per_run: int = Field(default=6, ge=0, le=30)
    max_calls_per_minute: int = Field(default=60, ge=0, le=600)
    retain_evidence: bool = False
    generation: int = 0
