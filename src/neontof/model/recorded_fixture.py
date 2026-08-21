"""Typed Recorded Fixture loading and sanitized test-provider observation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol, TypeAlias

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import LowercaseSha256, ModelCallId
from neontof.contracts.semantic_result import (
    PROPOSED_EVENT_ADAPTER,
    SEMANTIC_RESULT_ADAPTER,
    NonNegativeStrictInt,
    PositiveStrictInt,
    ProposedEvent,
    PublicationVisibility,
)
from neontof.model.model_invoker import (
    PROVIDER_STEP_ADAPTER,
    InvalidJsonStep,
    ModelErrorStep,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderCallLogMeta,
    ProviderStep,
    SuccessStep,
    TimeoutStep,
)


class SanitizedProviderCallLogEntry(ContractModel):
    request_id: ModelCallId
    attempt: PositiveStrictInt
    publication_visibility: PublicationVisibility
    context_digest: LowercaseSha256
    context_item_count: NonNegativeStrictInt
    usage: ModelUsage | None
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None


ProviderCallLogEntry: TypeAlias = SanitizedProviderCallLogEntry  # noqa: UP040


class RecordedFixtureV1(ContractModel):
    fixture_version: Literal[1]
    name: str
    steps: tuple[ProviderStep, ...]
    expected_call_count: NonNegativeStrictInt
    expected_final_outcome: Literal["success", "model_error", "timeout", "invalid_json"]
    expected_proposed_events: tuple[ProposedEvent, ...]


class TestProvider(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse: ...

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]: ...


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject JSON object's duplicate keys instead of accepting a last-wins value."""

    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("recorded fixture contains duplicate object keys")
        document[key] = value
    return document


def _require_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("recorded fixture JSON value must be an object")
    document: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise TypeError("recorded fixture object keys must be strings")
        document[key] = item
    return document


def _require_array(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("recorded fixture JSON value must be an array")
    return [item for item in value]


def _typed_steps(value: object) -> tuple[ProviderStep, ...]:
    step_values = _require_array(value)
    steps: list[ProviderStep] = []
    for step_value in step_values:
        step_document = _require_object(step_value)
        if step_document.get("type") == "success":
            response_document = _require_object(step_document.get("response"))
            payload_bytes = json.dumps(
                response_document.get("payload"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            semantic_payload = SEMANTIC_RESULT_ADAPTER.validate_json(payload_bytes)
            transformed_response = dict(response_document)
            transformed_response["payload"] = semantic_payload
            transformed_step = dict(step_document)
            transformed_step["response"] = transformed_response
            steps.append(PROVIDER_STEP_ADAPTER.validate_python(transformed_step, strict=True))
        else:
            steps.append(PROVIDER_STEP_ADAPTER.validate_python(step_document, strict=True))
    return tuple(steps)


def _typed_proposed_events(value: object) -> tuple[ProposedEvent, ...]:
    event_values = _require_array(value)
    return tuple(
        PROPOSED_EVENT_ADAPTER.validate_python(event_value, strict=True)
        for event_value in event_values
    )


def load_recorded_fixture(source: bytes) -> RecordedFixtureV1:
    """Decode and strictly validate one JSON Recorded Fixture document."""

    try:
        if type(source) is not bytes:
            raise TypeError("recorded fixture source must be bytes")
        decoded = json.loads(source, object_pairs_hook=_reject_duplicate_object_keys)
        document = _require_object(decoded)
        transformed_document = dict(document)
        transformed_document["steps"] = _typed_steps(document.get("steps"))
        transformed_document["expected_proposed_events"] = _typed_proposed_events(
            document.get("expected_proposed_events")
        )
        return RecordedFixtureV1.model_validate(transformed_document, strict=True)
    except RecursionError, TypeError, UnicodeDecodeError, ValueError:
        raise ValueError("recorded fixture is invalid") from None


def sanitize_provider_call_log(
    input_request: ModelRequest,
    meta: ProviderCallLogMeta,
) -> SanitizedProviderCallLogEntry:
    """Create the fixed safe observation record for one provider attempt."""

    context_json = [fact.model_dump(mode="json") for fact in input_request.context]
    context_bytes = json.dumps(
        context_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    context_digest = hashlib.sha256(context_bytes).hexdigest()
    return SanitizedProviderCallLogEntry(
        request_id=input_request.model_call_id,
        attempt=meta.attempt,
        publication_visibility=input_request.publication_visibility,
        context_digest=context_digest,
        context_item_count=meta.context_item_count,
        usage=meta.usage,
        status=meta.status,
        error_code=meta.error_code,
    )


class _RecordedFixtureProvider:
    def __init__(self, steps: tuple[ProviderStep, ...]) -> None:
        self._steps = steps
        self._next_step_index = 0
        self._calls: list[SanitizedProviderCallLogEntry] = []

    def _append_call(
        self,
        request: ModelRequest,
        *,
        status: Literal["succeeded", "failed", "timed_out", "rejected"],
        usage: ModelUsage | None,
        error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None,
    ) -> None:
        meta = ProviderCallLogMeta(
            attempt=len(self._calls) + 1,
            status=status,
            usage=usage,
            context_item_count=len(request.context),
            error_code=error_code,
        )
        self._calls.append(sanitize_provider_call_log(request, meta))

    def invoke(self, request: ModelRequest) -> ModelResponse:
        if self._next_step_index >= len(self._steps):
            self._append_call(
                request,
                status="rejected",
                usage=None,
                error_code="script_exhausted",
            )
            raise RuntimeError("script exhausted")

        step = self._steps[self._next_step_index]
        self._next_step_index += 1
        if isinstance(step, SuccessStep):
            self._append_call(
                request,
                status="succeeded",
                usage=step.response.usage,
                error_code=None,
            )
            return step.response
        if isinstance(step, ModelErrorStep):
            self._append_call(
                request,
                status="failed",
                usage=None,
                error_code="model_error",
            )
            raise RuntimeError("model invocation failed")  # noqa: TRY004
        if isinstance(step, TimeoutStep):
            self._append_call(
                request,
                status="timed_out",
                usage=None,
                error_code="timeout",
            )
            raise TimeoutError("model invocation timed out")
        if isinstance(step, InvalidJsonStep):
            self._append_call(
                request,
                status="rejected",
                usage=None,
                error_code="invalid_json",
            )
            raise ValueError("model response JSON is invalid")  # noqa: TRY004
        raise RuntimeError("script exhausted")

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]:
        return tuple(self._calls)


def create_recorded_fixture_provider(source: bytes) -> TestProvider:
    """Load a fixture once and return its instance-local recorded provider."""

    fixture = load_recorded_fixture(source)
    return _RecordedFixtureProvider(fixture.steps)


__all__ = (
    "ProviderCallLogEntry",
    "RecordedFixtureV1",
    "SanitizedProviderCallLogEntry",
    "TestProvider",
    "create_recorded_fixture_provider",
    "load_recorded_fixture",
    "sanitize_provider_call_log",
)
