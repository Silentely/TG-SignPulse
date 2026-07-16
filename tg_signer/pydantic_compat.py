"""
Pydantic v1/v2 兼容层

集中封装 dump/validate 差异，业务代码应优先使用本模块，避免散落版本判断。
"""
from __future__ import annotations

from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

IS_V2 = hasattr(BaseModel, "model_validate")


def model_validate(model_cls: Type[T], data: Any) -> T:
    """v2: model_validate；v1: parse_obj。"""
    validator = getattr(model_cls, "model_validate", None)
    if callable(validator):
        return validator(data)
    return model_cls.parse_obj(data)  # type: ignore[attr-defined]


def model_dump(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    """v2: model_dump；v1: dict。"""
    dumper = getattr(model, "model_dump", None)
    if callable(dumper):
        return dumper(**kwargs)
    return model.dict(**kwargs)  # type: ignore[call-arg]


def model_dump_json(model: BaseModel, **kwargs: Any) -> str:
    """v2: model_dump_json；v1: json。"""
    dumper = getattr(model, "model_dump_json", None)
    if callable(dumper):
        return dumper(**kwargs)
    return model.json(**kwargs)  # type: ignore[call-arg]


def try_import_field_validator():
    """返回 (field_validator 或 None, validator 或 None)。"""
    try:
        from pydantic import field_validator

        return field_validator, None
    except ImportError:  # pragma: no cover
        from pydantic import validator

        return None, validator
