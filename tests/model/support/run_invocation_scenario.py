"""Test-only driver for recorded model invocation scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from neontof.model.model_invoker import ModelRequest, ModelResponse
    from neontof.model.recorded_fixture import (
        RecordedFixtureV1,
        SanitizedProviderCallLogEntry,
    )

    from neontof.contracts.domain import DomainEvent
    from neontof.contracts.semantic_result import (
        SemanticValidationContext,
        SemanticValidationOutcome,
    )
    from tests.contracts.support.materialize_proposed_events import FixtureEventContext


FailureMessage = Literal[
    "model invocation failed",
    "model invocation timed out",
    "model response JSON is invalid",
    "script exhausted",
]


@dataclass(frozen=True, slots=True)
class InvocationScenarioResult:
    """Validated scenario result and the provider's sanitized observations."""

    fixture: RecordedFixtureV1
    response: ModelResponse | None
    outcome: SemanticValidationOutcome | None
    events: tuple[DomainEvent, ...]
    calls: tuple[SanitizedProviderCallLogEntry, ...]
    error_message: FailureMessage | None


def run_invocation_scenario(
    source: bytes,
    request: ModelRequest,
    validation_context: SemanticValidationContext,
    event_context: FixtureEventContext,
) -> InvocationScenarioResult:
    """Replay one fixture, validate a success, and materialize accepted proposals."""

    from neontof.model.recorded_fixture import (
        create_recorded_fixture_provider,
        load_recorded_fixture,
    )

    from neontof.contracts.semantic_result import (
        AcceptedSemanticResult,
        validate_semantic_result,
    )
    from tests.contracts.support.materialize_proposed_events import (
        materialize_semantic_result_for_test,
    )

    fixture = load_recorded_fixture(source)
    provider = create_recorded_fixture_provider(source)
    response: ModelResponse | None = None
    outcome: SemanticValidationOutcome | None = None
    events: tuple[DomainEvent, ...] = ()
    error_message: FailureMessage | None = None
    last_error_code: str | None = None

    for _ in range(fixture.expected_call_count):
        try:
            response = provider.invoke(request)
        except RuntimeError, TimeoutError, ValueError:
            last_error_code = provider.calls[-1].error_code if provider.calls else None
            continue
        break

    if response is None:
        error_messages: dict[str, FailureMessage] = {
            "model_error": "model invocation failed",
            "timeout": "model invocation timed out",
            "invalid_json": "model response JSON is invalid",
            "script_exhausted": "script exhausted",
        }
        if not provider.calls:
            last_error_code = "script_exhausted"
        error_code = last_error_code if last_error_code is not None else "model_error"
        error_message = error_messages.get(error_code, "model invocation failed")
        return InvocationScenarioResult(
            fixture=fixture,
            response=None,
            outcome=None,
            events=(),
            calls=provider.calls,
            error_message=error_message,
        )

    outcome = validate_semantic_result(response.payload, validation_context)
    if isinstance(outcome, AcceptedSemanticResult):
        events = materialize_semantic_result_for_test(outcome, event_context)

    return InvocationScenarioResult(
        fixture=fixture,
        response=response,
        outcome=outcome,
        events=events,
        calls=provider.calls,
        error_message=None,
    )
