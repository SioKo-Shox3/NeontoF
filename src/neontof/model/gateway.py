"""公開入力を一回のFixture呼出しへ渡し、予算と観測を管理するLocal Gateway。"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import ValidationError

from neontof.contracts.ids import ModelCallId
from neontof.model.gateway_models import (
    GatewayFailure,
    GatewayFixtureCase,
    GatewayOutcome,
    GatewayRequest,
    GatewaySuccess,
    ProviderDiceResult,
    ProviderRequest,
    SessionBudget,
)
from neontof.model.model_invoker import (
    InvalidJsonStep,
    ModelErrorStep,
    ModelResponse,
    ModelUsage,
    ProviderStep,
    Role,
    SuccessStep,
    TimeoutStep,
)
from neontof.model.recorded_fixture import (
    RecordedFixtureV1,
    SanitizedProviderCallLogEntry,
)
from neontof.observability.records import TelemetryRecord, TranscriptRecord
from neontof.persistence.observation_store import ObservationStore

_GATEWAY_ROLES: tuple[Role, ...] = (
    "referee",
    "world_simulator",
    "npc_actor",
    "narrator",
)
_FIXTURE_PROVIDER = "gateway_fixture"
_FIXTURE_MODEL = "recorded_fixture"
_OCCURRED_AT = "1970-01-01T00:00:00Z"

type GatewayErrorCode = Literal["budget_exceeded", "timeout", "model_error", "invalid_json"]


class _FixtureModelError(RuntimeError):
    """Hide fixture error details at the Gateway boundary."""

    def __init__(self) -> None:
        super().__init__("model invocation failed")


class _FixtureRequestMismatchError(ValueError):
    """Hide expected and received provider envelopes from callers and logs."""

    def __init__(self) -> None:
        super().__init__("fixture request rejected")


class _FixtureInvalidJsonError(ValueError):
    """Carry only the safe byte length of a rejected fixture response."""

    def __init__(self, body: str) -> None:
        self.byte_length = len(body.encode("utf-8", errors="replace"))
        super().__init__("model response JSON is invalid")


def _validate_timeout(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("gateway timeout must be finite and positive")
    return float(value)


def _validate_gateway_request(request: GatewayRequest) -> GatewayRequest:
    try:
        return GatewayRequest.model_validate(request, strict=True)
    except AttributeError, TypeError, ValueError, ValidationError:
        raise ValueError("gateway request validation failed") from None


def _model_call_id(turn_id: str) -> ModelCallId:
    digest = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()
    return f"model-call:{digest}"


def _entry_id(prefix: str, turn_id: str, kind: str) -> str:
    digest = hashlib.sha256(f"{turn_id}:{kind}".encode()).hexdigest()
    return f"{prefix}:{digest}"


def _response_digest(response: ModelResponse) -> str:
    payload_bytes = json.dumps(
        response.payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


def _calculate_cost(response: ModelResponse, budget: SessionBudget) -> int:
    usage = response.usage
    return (
        usage.input_tokens * budget.input_microusd_per_million_tokens
        + usage.output_tokens * budget.output_microusd_per_million_tokens
        + usage.cached_tokens * budget.cached_microusd_per_million_tokens
        + 999_999
    ) // 1_000_000


def build_provider_request(
    *,
    request: GatewayRequest,
    model_call_id: ModelCallId,
) -> ProviderRequest:
    """Build the complete public-only Provider envelope for one model call."""

    validated_request = _validate_gateway_request(request)
    if validated_request.public_context.publication_visibility == "gm_only":
        raise ValueError("gateway provider context must be public")
    return ProviderRequest(
        model_call_id=model_call_id,
        turn_id=validated_request.turn_id,
        roles=_GATEWAY_ROLES,
        public_context=validated_request.public_context,
        player_input=validated_request.player_input,
        dice_result=ProviderDiceResult(
            action_id=validated_request.dice_result.action_id,
            roll_index=validated_request.dice_result.roll_index,
            formula=validated_request.dice_result.formula,
            result=validated_request.dice_result.result,
        ),
        max_narrative_chars=validated_request.max_narrative_chars,
        output_schema="semantic-result-v1",
    )


class GatewayFixtureProvider:
    """Exchangeable Fake / Recorded adapter with exact request matching."""

    def __init__(self, *, cases: tuple[GatewayFixtureCase, ...]) -> None:
        self._cases = tuple(GatewayFixtureCase.model_validate(case, strict=True) for case in cases)
        self._next_case_index = 0
        self._calls: list[SanitizedProviderCallLogEntry] = []

    def _append_call(
        self,
        request: ProviderRequest,
        *,
        status: Literal["succeeded", "failed", "timed_out", "rejected"],
        usage: ModelUsage | None,
        error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None,
    ) -> None:
        self._calls.append(
            SanitizedProviderCallLogEntry(
                request_id=request.model_call_id,
                attempt=sum(call.request_id == request.model_call_id for call in self._calls) + 1,
                publication_visibility=request.public_context.publication_visibility,
                context_digest=request.public_context.context_digest,
                context_item_count=len(request.public_context.projection.facts),
                usage=usage,
                status=status,
                error_code=error_code,
            )
        )

    def invoke(
        self,
        request: ProviderRequest,
        *,
        timeout_seconds: float,
    ) -> ModelResponse:
        _validate_timeout(timeout_seconds)
        try:
            validated_request = ProviderRequest.model_validate(request, strict=True)
        except AttributeError, TypeError, ValueError, ValidationError:
            raise ValueError("provider request validation failed") from None

        if self._next_case_index >= len(self._cases):
            self._append_call(
                validated_request,
                status="rejected",
                usage=None,
                error_code="script_exhausted",
            )
            raise _FixtureModelError()

        case = self._cases[self._next_case_index]
        if validated_request != case.expected_request:
            raise _FixtureRequestMismatchError()
        self._next_case_index += 1

        step: ProviderStep = case.step
        if isinstance(step, SuccessStep):
            response = ModelResponse.model_validate(step.response, strict=True)
            self._append_call(
                validated_request,
                status="succeeded",
                usage=response.usage,
                error_code=None,
            )
            return response
        if isinstance(step, ModelErrorStep):
            self._append_call(
                validated_request,
                status="failed",
                usage=None,
                error_code="model_error",
            )
            raise _FixtureModelError()
        if isinstance(step, TimeoutStep):
            self._append_call(
                validated_request,
                status="timed_out",
                usage=None,
                error_code="timeout",
            )
            raise TimeoutError("model invocation timed out")
        if isinstance(step, InvalidJsonStep):
            self._append_call(
                validated_request,
                status="rejected",
                usage=None,
                error_code="invalid_json",
            )
            raise _FixtureInvalidJsonError(step.body)
        raise _FixtureModelError()

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]:
        return tuple(self._calls)


def create_gateway_fake_provider(
    *,
    expected_request: ProviderRequest,
    step: ProviderStep,
) -> GatewayFixtureProvider:
    """Create one exact-match case for a deterministic Fake provider."""

    return GatewayFixtureProvider(
        cases=(GatewayFixtureCase(expected_request=expected_request, step=step),)
    )


def create_gateway_recorded_provider(
    *,
    expected_requests: tuple[ProviderRequest, ...],
    fixture: RecordedFixtureV1,
) -> GatewayFixtureProvider:
    """Adapt typed Recorded Fixture steps through the same concrete provider."""

    validated_fixture = RecordedFixtureV1.model_validate(fixture, strict=True)
    if len(expected_requests) != len(
        validated_fixture.steps
    ) or validated_fixture.expected_call_count != len(validated_fixture.steps):
        raise ValueError("recorded fixture request count does not match its steps")
    cases = tuple(
        GatewayFixtureCase(expected_request=expected_request, step=step)
        for expected_request, step in zip(expected_requests, validated_fixture.steps, strict=True)
    )
    return GatewayFixtureProvider(cases=cases)


class ModelGateway:
    def __init__(
        self,
        *,
        provider: GatewayFixtureProvider,
        observations: ObservationStore,
        budget: SessionBudget,
        timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._observations = observations
        self._budget = SessionBudget.model_validate(budget, strict=True)
        self._timeout_seconds = _validate_timeout(timeout_seconds)

    def _append_request_transcript(
        self,
        request: GatewayRequest,
        model_call_id: str,
    ) -> None:
        projection = request.public_context.projection
        self._observations.append_transcript(
            TranscriptRecord(
                entry_id=_entry_id("transcript", request.turn_id, "model-request"),
                campaign_id=projection.campaign_id,
                session_id=projection.session_id,
                turn_id=request.turn_id,
                model_call_id=model_call_id,
                kind="model_request",
                occurred_at=_OCCURRED_AT,
                data={
                    "context_digest": request.public_context.context_digest,
                    "context_item_count": len(projection.facts),
                    "output_schema": "semantic-result-v1",
                },
            )
        )

    def _append_response_transcript(
        self,
        request: GatewayRequest,
        model_call_id: str,
        response: ModelResponse,
    ) -> None:
        projection = request.public_context.projection
        narrative_bytes = len(response.payload.narrative.encode("utf-8"))
        self._observations.append_transcript(
            TranscriptRecord(
                entry_id=_entry_id("transcript", request.turn_id, "model-response"),
                campaign_id=projection.campaign_id,
                session_id=projection.session_id,
                turn_id=request.turn_id,
                model_call_id=model_call_id,
                kind="model_response",
                occurred_at=_OCCURRED_AT,
                data={
                    "response_digest": _response_digest(response),
                    "narrative_byte_length": narrative_bytes,
                    "proposed_event_count": len(response.payload.proposed_events),
                    "proposed_fact_count": len(response.payload.proposed_facts),
                },
            )
        )

    def _append_error_transcript(
        self,
        request: GatewayRequest,
        model_call_id: str | None,
        code: GatewayErrorCode,
        *,
        byte_length: int = 0,
    ) -> None:
        projection = request.public_context.projection
        self._observations.append_transcript(
            TranscriptRecord(
                entry_id=_entry_id("transcript", request.turn_id, f"error-{code}"),
                campaign_id=projection.campaign_id,
                session_id=projection.session_id,
                turn_id=request.turn_id,
                model_call_id=model_call_id,
                kind="error",
                occurred_at=_OCCURRED_AT,
                data={
                    "error_code": code,
                    "digest": request.public_context.context_digest,
                    "byte_length": byte_length,
                },
            )
        )

    def _append_telemetry(
        self,
        request: GatewayRequest,
        model_call_id: str,
        *,
        status: Literal["succeeded", "failed", "timed_out", "rejected"],
        code: GatewayErrorCode | None,
        response: ModelResponse | None,
        cost_microusd: int,
    ) -> None:
        projection = request.public_context.projection
        usage = response.usage if response is not None else None
        self._observations.append_telemetry(
            TelemetryRecord(
                entry_id=_entry_id("telemetry", request.turn_id, code or "success"),
                campaign_id=projection.campaign_id,
                session_id=projection.session_id,
                turn_id=request.turn_id,
                model_call_id=model_call_id,
                provider=_FIXTURE_PROVIDER,
                model=_FIXTURE_MODEL,
                roles=_GATEWAY_ROLES,
                attempt=1,
                status=status,
                input_tokens=usage.input_tokens if usage is not None else 0,
                output_tokens=usage.output_tokens if usage is not None else 0,
                cached_tokens=usage.cached_tokens if usage is not None else 0,
                latency_ms=0,
                cost_microusd=cost_microusd,
                error_code=code,
                occurred_at=_OCCURRED_AT,
            )
        )

    def _failure(
        self,
        request: GatewayRequest,
        model_call_id: str,
        code: GatewayErrorCode,
        *,
        status: Literal["failed", "timed_out", "rejected"],
        byte_length: int = 0,
        response: ModelResponse | None = None,
        cost_microusd: int = 0,
    ) -> GatewayFailure:
        self._append_error_transcript(request, model_call_id, code, byte_length=byte_length)
        self._append_telemetry(
            request,
            model_call_id,
            status=status,
            code=code,
            response=response,
            cost_microusd=cost_microusd,
        )
        return GatewayFailure(type="failure", code=code, attempts=1)

    def invoke(self, request: GatewayRequest) -> GatewayOutcome:
        validated_request = _validate_gateway_request(request)
        projection = validated_request.public_context.projection
        if (
            projection.campaign_id != self._budget.campaign_id
            or projection.session_id != self._budget.session_id
        ):
            raise ValueError("gateway request scope does not match session budget")

        current_cost = self._observations.session_cost_microusd(
            self._budget.campaign_id,
            self._budget.session_id,
        )
        if current_cost >= self._budget.limit_microusd:
            self._append_error_transcript(validated_request, None, "budget_exceeded")
            return GatewayFailure(type="failure", code="budget_exceeded", attempts=0)

        model_call_id = _model_call_id(validated_request.turn_id)
        provider_request = build_provider_request(
            request=validated_request,
            model_call_id=model_call_id,
        )
        self._append_request_transcript(validated_request, model_call_id)

        try:
            response = self._provider.invoke(
                provider_request,
                timeout_seconds=self._timeout_seconds,
            )
        except TimeoutError:
            return self._failure(
                validated_request,
                model_call_id,
                "timeout",
                status="timed_out",
            )
        except _FixtureInvalidJsonError as error:
            return self._failure(
                validated_request,
                model_call_id,
                "invalid_json",
                status="rejected",
                byte_length=error.byte_length,
            )
        except AttributeError, RuntimeError, TypeError, ValueError:
            return self._failure(
                validated_request,
                model_call_id,
                "model_error",
                status="failed",
            )

        try:
            validated_response = ModelResponse.model_validate(response, strict=True)
        except AttributeError, TypeError, ValueError, ValidationError:
            return self._failure(
                validated_request,
                model_call_id,
                "invalid_json",
                status="rejected",
            )

        cost_microusd = _calculate_cost(validated_response, self._budget)
        try:
            self._append_response_transcript(validated_request, model_call_id, validated_response)
        except UnicodeEncodeError:
            return self._failure(
                validated_request,
                model_call_id,
                "invalid_json",
                status="rejected",
                response=validated_response,
                cost_microusd=cost_microusd,
            )
        self._append_telemetry(
            validated_request,
            model_call_id,
            status="succeeded",
            code=None,
            response=validated_response,
            cost_microusd=cost_microusd,
        )
        return GatewaySuccess(
            type="success",
            response=validated_response,
            attempts=1,
            cost_microusd=cost_microusd,
        )


__all__ = (
    "GatewayFixtureProvider",
    "ModelGateway",
    "build_provider_request",
    "create_gateway_fake_provider",
    "create_gateway_recorded_provider",
)
