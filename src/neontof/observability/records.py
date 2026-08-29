"""Strict, purpose-specific Transcript and Telemetry observation records."""

from __future__ import annotations

import re
from typing import Any, Literal, NoReturn, Self, TypeAlias

from pydantic import TypeAdapter, ValidationError, model_validator
from pydantic_core import core_schema

from neontof.contracts.base import ContractModel, FrozenJsonValue
from neontof.contracts.ids import (
    CampaignId,
    LowercaseSha256,
    ModelCallId,
    OccurredAt,
    SessionId,
    TelemetryId,
    TranscriptId,
    TurnId,
)
from neontof.model.model_invoker import Role

MAX_SAFE_INTEGER = 9_223_372_036_854_775_807
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_LOWERCASE_SHA256_ADAPTER: TypeAdapter[LowercaseSha256] = TypeAdapter(LowercaseSha256)

TranscriptKind: TypeAlias = Literal[  # noqa: UP040
    "player_input",
    "model_request",
    "model_response",
    "narrative",
    "error",
    "retry",
    "correction",
    "tool_call",
]
TelemetryStatus: TypeAlias = Literal[  # noqa: UP040
    "succeeded",
    "failed",
    "timed_out",
    "rejected",
]
TelemetryErrorCode: TypeAlias = Literal[  # noqa: UP040
    "model_error",
    "timeout",
    "invalid_json",
    "script_exhausted",
    "budget_exceeded",
]

_TRANSCRIPT_KINDS = frozenset(
    {
        "player_input",
        "model_request",
        "model_response",
        "narrative",
        "error",
        "retry",
        "correction",
        "tool_call",
    }
)
_ERROR_CODES = frozenset(
    {"model_error", "timeout", "invalid_json", "script_exhausted", "budget_exceeded"}
)
_ROLES = frozenset({"referee", "world_simulator", "npc_actor", "narrator"})
_STATUS_ERROR_CODES = {
    "succeeded": frozenset({None}),
    "timed_out": frozenset({"timeout"}),
    "failed": frozenset({"model_error"}),
    "rejected": frozenset({"invalid_json", "script_exhausted", "budget_exceeded"}),
}


class ObservationValidationError(RuntimeError):
    """Fixed, detail-free failure for invalid observation input."""

    __slots__ = ()

    def __init__(self) -> None:
        RuntimeError.__init__(self, "observation validation failed")


def _invalid() -> NoReturn:
    raise ValueError("observation validation failed")


def _validate_exact_keys(value: dict[str, object], expected: frozenset[str]) -> None:
    keys = tuple(value.keys())
    if any(type(key) is not str for key in keys):
        _invalid()
    if len(keys) != len(expected) or frozenset(keys) != expected:
        _invalid()


def _validate_text(value: object) -> None:
    if type(value) is not str:
        _invalid()
    try:
        byte_length = len(value.encode("utf-8", errors="strict"))
    except UnicodeError:
        _invalid()
    if byte_length > 65_536:
        _invalid()


def _validate_digest(value: object) -> None:
    validation_failed = False
    try:
        _LOWERCASE_SHA256_ADAPTER.validate_python(value, strict=True)
    except AttributeError, TypeError, ValueError, ValidationError:
        validation_failed = True
    if validation_failed:
        _invalid()


def _validate_counter(value: object) -> None:
    if type(value) is not int or value < 0 or value > MAX_SAFE_INTEGER:
        _invalid()


def _validate_attempt(value: object) -> None:
    if type(value) is not int or value < 1 or value > MAX_SAFE_INTEGER:
        _invalid()


def _validate_tool_name(value: object) -> None:
    if type(value) is not str or not value.isascii() or _TOOL_NAME_PATTERN.fullmatch(value) is None:
        _invalid()


def _validate_error_code(value: object) -> None:
    if type(value) is not str or value not in _ERROR_CODES:
        _invalid()


def _validate_provider(value: object) -> None:
    if type(value) is not str or not value.isascii() or _PROVIDER_PATTERN.fullmatch(value) is None:
        _invalid()


def _validate_model(value: object) -> None:
    if type(value) is not str or not value.isascii() or _MODEL_PATTERN.fullmatch(value) is None:
        _invalid()


def _validate_roles(value: object) -> None:
    if type(value) is not tuple or any(
        type(role) is not str or role not in _ROLES for role in value
    ):
        _invalid()


def _validate_status_and_error(status: object, error_code: object) -> None:
    if type(status) is not str or status not in _STATUS_ERROR_CODES:
        _invalid()
    if error_code is not None and (type(error_code) is not str or error_code not in _ERROR_CODES):
        _invalid()
    if error_code not in _STATUS_ERROR_CODES[status]:
        _invalid()


def _validate_transcript_data(kind: object, data: object) -> None:
    if type(kind) is not str or kind not in _TRANSCRIPT_KINDS or type(data) is not dict:
        _invalid()
    payload = data
    if kind in {"player_input", "narrative", "correction"}:
        _validate_exact_keys(payload, frozenset({"text"}))
        _validate_text(payload["text"])
        return
    if kind == "model_request":
        _validate_exact_keys(
            payload, frozenset({"context_digest", "context_item_count", "output_schema"})
        )
        _validate_digest(payload["context_digest"])
        _validate_counter(payload["context_item_count"])
        if (
            type(payload["output_schema"]) is not str
            or payload["output_schema"] != "semantic-result-v1"
        ):
            _invalid()
        return
    if kind == "model_response":
        _validate_exact_keys(
            payload,
            frozenset(
                {
                    "response_digest",
                    "narrative_byte_length",
                    "proposed_event_count",
                    "proposed_fact_count",
                }
            ),
        )
        _validate_digest(payload["response_digest"])
        _validate_counter(payload["narrative_byte_length"])
        _validate_counter(payload["proposed_event_count"])
        _validate_counter(payload["proposed_fact_count"])
        return
    if kind == "error":
        _validate_exact_keys(payload, frozenset({"error_code", "digest", "byte_length"}))
        _validate_error_code(payload["error_code"])
        _validate_digest(payload["digest"])
        _validate_counter(payload["byte_length"])
        return
    if kind == "retry":
        _validate_exact_keys(payload, frozenset({"error_code", "attempt"}))
        _validate_error_code(payload["error_code"])
        _validate_attempt(payload["attempt"])
        return
    if kind == "tool_call":
        _validate_exact_keys(
            payload,
            frozenset({"tool_name", "arguments_digest", "arguments_byte_length", "outcome"}),
        )
        _validate_tool_name(payload["tool_name"])
        _validate_digest(payload["arguments_digest"])
        _validate_counter(payload["arguments_byte_length"])
        if type(payload["outcome"]) is not str or payload["outcome"] not in {
            "accepted",
            "rejected",
            "failed",
        }:
            _invalid()
        return
    _invalid()


def _validate_transcript_input(value: object) -> object:
    if type(value) is not dict:
        _invalid()
    _validate_transcript_data(value.get("kind"), value.get("data"))
    return value


def _validate_telemetry_input(value: object) -> object:
    if type(value) is not dict:
        _invalid()
    _validate_provider(value.get("provider"))
    _validate_model(value.get("model"))
    _validate_roles(value.get("roles"))
    _validate_attempt(value.get("attempt"))
    _validate_status_and_error(value.get("status"), value.get("error_code"))
    for field in (
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "latency_ms",
        "cost_microusd",
    ):
        _validate_counter(value.get(field))
    return value


class _SafeObservationModel(ContractModel):
    """Keep Pydantic's useful validation while exposing only fixed failures."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        inner_schema = handler(source_type)

        def validate(value: Any, next_handler: Any) -> Any:
            result: Any = None
            validation_failed = False
            try:
                result = next_handler(value)
            except (
                AttributeError,
                RecursionError,
                RuntimeError,
                TypeError,
                ValueError,
                ValidationError,
            ):
                validation_failed = True
            if validation_failed or result is None:
                raise ObservationValidationError()
            return result

        return core_schema.no_info_wrap_validator_function(validate, inner_schema)

    def __init__(self, **data: Any) -> None:
        validation_failed = False
        try:
            super().__init__(**data)
        except AttributeError, RecursionError, RuntimeError, TypeError, ValueError, ValidationError:
            validation_failed = True
        if validation_failed:
            raise ObservationValidationError()

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
        result: Self | None = None
        validation_failed = False
        try:
            result = super().model_validate(obj, **kwargs)
        except AttributeError, RecursionError, RuntimeError, TypeError, ValueError, ValidationError:
            validation_failed = True
        if validation_failed or result is None:
            raise ObservationValidationError()
        return result

    @classmethod
    def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
        result: Self | None = None
        validation_failed = False
        try:
            result = super().model_validate_json(json_data, **kwargs)
        except AttributeError, RecursionError, RuntimeError, TypeError, ValueError, ValidationError:
            validation_failed = True
        if validation_failed or result is None:
            raise ObservationValidationError()
        return result

    @classmethod
    def model_validate_strings(cls, obj: Any, **kwargs: Any) -> Self:
        result: Self | None = None
        validation_failed = False
        try:
            result = super().model_validate_strings(obj, **kwargs)
        except AttributeError, RecursionError, RuntimeError, TypeError, ValueError, ValidationError:
            validation_failed = True
        if validation_failed or result is None:
            raise ObservationValidationError()
        return result


class TranscriptRecord(_SafeObservationModel):
    """One purpose-specific, immutable Transcript entry."""

    entry_id: TranscriptId
    campaign_id: CampaignId
    session_id: SessionId | None
    turn_id: TurnId | None
    model_call_id: ModelCallId | None
    kind: TranscriptKind
    occurred_at: OccurredAt
    data: FrozenJsonValue

    @model_validator(mode="before")
    @classmethod
    def _validate_before_freezing(cls, value: object) -> object:
        return _validate_transcript_input(value)


def parse_transcript_json(json_data: str | bytes | bytearray, **kwargs: Any) -> TranscriptRecord:
    """Validate one TranscriptRecord JSON document at the safe records boundary."""

    result: TranscriptRecord | None = None
    validation_failed = False
    try:
        result = TranscriptRecord.model_validate_json(json_data, **kwargs)
    except (
        AttributeError,
        RecursionError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
        ValidationError,
    ):
        validation_failed = True
    if validation_failed or result is None:
        raise ObservationValidationError()
    return result


class TelemetryRecord(_SafeObservationModel):
    """One immutable provider-neutral usage and outcome entry."""

    entry_id: TelemetryId
    campaign_id: CampaignId
    session_id: SessionId
    turn_id: TurnId
    model_call_id: ModelCallId
    provider: str
    model: str
    roles: tuple[Role, ...]
    attempt: int
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    cost_microusd: int
    error_code: str | None
    occurred_at: OccurredAt

    @model_validator(mode="before")
    @classmethod
    def _validate_before_pydantic(cls, value: object) -> object:
        return _validate_telemetry_input(value)


__all__ = (
    "MAX_SAFE_INTEGER",
    "ObservationValidationError",
    "TelemetryErrorCode",
    "TelemetryRecord",
    "TelemetryStatus",
    "TranscriptKind",
    "TranscriptRecord",
    "parse_transcript_json",
)
