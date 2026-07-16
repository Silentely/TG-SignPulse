"""后端 Pydantic 兼容层（转发 tg_signer 实现，保持单一来源）。"""
from __future__ import annotations

from tg_signer.pydantic_compat import (  # noqa: F401
    IS_V2,
    model_dump,
    model_dump_json,
    model_validate,
    try_import_field_validator,
)
