"""Recursive final-defense redaction for immutable observation values."""

from __future__ import annotations

import math
from typing import NoReturn

from neontof.contracts.base import FrozenJsonValue
from neontof.observability.records import ObservationValidationError

_SENSITIVE_KEYS = frozenset({"api_key", "authorization", "token", "secret"})
_REDACTED = "[REDACTED]"


def _invalid() -> NoReturn:
    raise ObservationValidationError()


def _sanitize(value: object, active_containers: set[int]) -> object:
    value_type = type(value)
    if value is None or value_type is str or value_type is bool or value_type is int:
        return value
    if value_type is float:
        if not isinstance(value, float) or not math.isfinite(value):
            _invalid()
        return value
    if value_type is dict:
        if not isinstance(value, dict):
            _invalid()
        container_id = id(value)
        if container_id in active_containers:
            _invalid()
        active_containers.add(container_id)
        try:
            items: list[tuple[str, object]] = []
            for key, item in value.items():
                if type(key) is not str:
                    _invalid()
                sanitized = (
                    _REDACTED
                    if key.lower() in _SENSITIVE_KEYS
                    else _sanitize(item, active_containers)
                )
                items.append((key, sanitized))
            return tuple(items)
        finally:
            active_containers.remove(container_id)
    if value_type is tuple:
        if not isinstance(value, tuple):
            _invalid()
        container_id = id(value)
        if container_id in active_containers:
            _invalid()
        active_containers.add(container_id)
        try:
            if all(
                type(item) is tuple and len(item) == 2 and type(item[0]) is str for item in value
            ):
                object_items: list[tuple[str, object]] = []
                for item in value:
                    key = item[0]
                    sanitized = (
                        _REDACTED
                        if key.lower() in _SENSITIVE_KEYS
                        else _sanitize(item[1], active_containers)
                    )
                    object_items.append((key, sanitized))
                return tuple(object_items)
            return tuple(_sanitize(item, active_containers) for item in value)
        finally:
            active_containers.remove(container_id)
    if value_type is list:
        if not isinstance(value, list):
            _invalid()
        container_id = id(value)
        if container_id in active_containers:
            _invalid()
        active_containers.add(container_id)
        try:
            return tuple(_sanitize(item, active_containers) for item in value)
        finally:
            active_containers.remove(container_id)
    _invalid()


def sanitize_observation(value: FrozenJsonValue) -> FrozenJsonValue:
    """Redact sensitive keys recursively after purpose-specific validation."""

    return _sanitize(value, set())


__all__ = ("sanitize_observation",)
