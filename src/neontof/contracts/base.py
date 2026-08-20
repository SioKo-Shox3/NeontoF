"""Pydantic contracts shared by the domain boundary and the HTTP adapter."""

from __future__ import annotations

import math
from typing import Annotated, TypeAlias

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
)


def _contract_config() -> ConfigDict:
    return ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )


class ContractModel(BaseModel):
    """The canonical immutable and strict base for public contracts."""

    model_config = _contract_config()


def _freeze_json(value: object) -> object:
    """Copy JSON containers so no mutable input object can alias a contract."""

    return _freeze_json_value(value, set())


def _freeze_json_value(value: object, active_containers: set[int]) -> object:
    """Freeze one JSON value while rejecting recursive container graphs."""

    value_type = type(value)
    if value is None or value_type is str or value_type is bool:
        return value
    if value_type is int:
        return value
    if isinstance(value, float):
        if value_type is not float:
            raise ValueError("value is not immutable JSON")
        if not math.isfinite(value):
            raise ValueError("JSON float must be finite")
        return value
    if isinstance(value, list):
        if value_type is not list:
            raise ValueError("value is not immutable JSON")
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError("JSON value must not contain cycles")
        active_containers.add(container_id)
        try:
            return tuple(_freeze_json_value(item, active_containers) for item in value)
        finally:
            active_containers.remove(container_id)
    if isinstance(value, dict):
        if value_type is not dict:
            raise ValueError("value is not immutable JSON")
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError("JSON value must not contain cycles")
        active_containers.add(container_id)
        try:
            frozen_items = tuple(
                (key, _freeze_json_value(item, active_containers))
                for key, item in sorted(value.items(), key=lambda item: item[0])
            )
            return frozen_items
        finally:
            active_containers.remove(container_id)
    if isinstance(value, tuple):
        if value_type is not tuple:
            raise ValueError("value is not immutable JSON")
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError("JSON value must not contain cycles")
        active_containers.add(container_id)
        try:
            return tuple(_freeze_json_value(item, active_containers) for item in value)
        finally:
            active_containers.remove(container_id)
    raise ValueError("value is not immutable JSON")


# Explicit TypeAlias preserves TypeAdapter inference across module boundaries.
FrozenJsonValue: TypeAlias = Annotated[object, BeforeValidator(_freeze_json)]  # noqa: UP040
