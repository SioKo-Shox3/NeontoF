"""Focused tests for the versioned Recorded Fixture boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from neontof.contracts.domain import ResourceChangedEvent, ResourceChangedPayload
from neontof.contracts.projection import FactRecord
from tests.model.support.run_invocation_scenario import run_invocation_scenario

if TYPE_CHECKING:
    from collections.abc import Callable

    from neontof.model.model_invoker import ModelRequest, PublicationVisibility, Role
    from neontof.model.recorded_fixture import RecordedFixtureV1, TestProvider

    from neontof.contracts.semantic_result import SemanticValidationContext
    from tests.contracts.support.materialize_proposed_events import FixtureEventContext


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "providers"

_RESOURCE_PROPOSAL = {
    "type": "ResourceChanged",
    "payload": {
        "resource_id": "resource:gold",
        "entity_id": "entity:hero",
        "delta": 2,
    },
}

_FIXTURE_CASES = (
    ("normal-turn", ("success",), ("SuccessStep",), 1, "success", (_RESOURCE_PROPOSAL,)),
    ("model-error", ("model_error",), ("ModelErrorStep",), 1, "model_error", ()),
    ("timeout", ("timeout",), ("TimeoutStep",), 1, "timeout", ()),
    ("invalid-json", ("invalid_json",), ("InvalidJsonStep",), 1, "invalid_json", ()),
    (
        "retry-then-success",
        ("model_error", "success"),
        ("ModelErrorStep", "SuccessStep"),
        2,
        "success",
        (_RESOURCE_PROPOSAL,),
    ),
    (
        "sanitized-call-log",
        ("success",),
        ("SuccessStep",),
        1,
        "success",
        (),
    ),
)

_LOSSLESS_FIXTURE = b"""
{
  "fixture_version": 1,
  "name": "lossless-values",
  "steps": [
    {
      "type": "success",
      "response": {
        "payload": {
          "schema_version": 1,
          "rulings": [],
          "proposed_events": [
            {
              "type": "ResourceChanged",
              "payload": {
                "resource_id": "resource:gold",
                "entity_id": "entity:hero",
                "delta": 1
              }
            },
            {
              "type": "ResourceChanged",
              "payload": {
                "resource_id": "resource:silver",
                "entity_id": "entity:hero",
                "delta": -1
              }
            }
          ],
          "proposed_facts": [
            {
              "kind": "fact",
              "holder": "world",
              "subject_id": null,
              "predicate": "mixed-values",
              "value": [true, 1, "1", null],
              "visibility": "player_visible"
            }
          ],
          "knowledge_changes": [],
          "visibility_changes": [],
          "clarification_request": null,
          "rejection": null,
          "narrative_plan": [],
          "narrative": "lossless",
          "mentioned_details": [],
          "evidence": [],
          "suggested_actions": []
        },
        "usage": {
          "input_tokens": 0,
          "output_tokens": 0,
          "cached_tokens": 0
        }
      }
    }
  ],
  "expected_call_count": 1,
  "expected_final_outcome": "success",
  "expected_proposed_events": [
    {
      "type": "ResourceChanged",
      "payload": {
        "resource_id": "resource:gold",
        "entity_id": "entity:hero",
        "delta": 1
      }
    },
    {
      "type": "ResourceChanged",
      "payload": {
        "resource_id": "resource:silver",
        "entity_id": "entity:hero",
        "delta": -1
      }
    }
  ]
}
"""

_DUPLICATE_KEY_FIXTURE = b"""
{
  "fixture_version": 1,
  "name": "duplicate-key",
  "steps": [],
  "expected_call_count": 0,
  "expected_call_count": 1,
  "expected_final_outcome": "success",
  "expected_proposed_events": []
}
"""

_SCALAR_TYPE_FIXTURE = b"""
{
  "fixture_version": 1,
  "name": "strict-scalar",
  "steps": [],
  "expected_call_count": true,
  "expected_final_outcome": "success",
  "expected_proposed_events": []
}
"""


def _fixture_source(name: str) -> bytes:
    return (FIXTURE_DIR / f"{name}.v1.json").read_bytes()


def _normal_turn_variant(
    *,
    narrative: str | None = None,
    narrative_plan: list[dict[str, str]] | None = None,
    proposed_event_delta: int | None = None,
) -> bytes:
    document = json.loads(_fixture_source("normal-turn"))
    payload = document["steps"][0]["response"]["payload"]
    if narrative is not None:
        payload["narrative"] = narrative
    if narrative_plan is not None:
        payload["narrative_plan"] = narrative_plan
    if proposed_event_delta is not None:
        payload["proposed_events"][0]["payload"]["delta"] = proposed_event_delta
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fixture_api() -> tuple[
    Callable[[bytes], RecordedFixtureV1],
    Callable[[bytes], TestProvider],
]:
    from neontof.model.recorded_fixture import (
        create_recorded_fixture_provider,
        load_recorded_fixture,
    )

    return load_recorded_fixture, create_recorded_fixture_provider


def _request(
    *,
    context: tuple[FactRecord, ...] = (),
    model_call_id: str = "model-call:fixture",
    turn_id: str = "turn:fixture",
    roles: tuple[Role, ...] = ("referee",),
    publication_visibility: PublicationVisibility = "player_visible",
) -> ModelRequest:
    from neontof.model.model_invoker import ModelRequest

    return ModelRequest(
        model_call_id=model_call_id,
        turn_id=turn_id,
        roles=roles,
        publication_visibility=publication_visibility,
        context=context,
        output_schema="semantic-result-v1",
    )


def _validation_context() -> SemanticValidationContext:
    from neontof.contracts.semantic_result import SemanticValidationContext

    return SemanticValidationContext(
        known_entity_ids=frozenset({"entity:hero"}),
        known_npc_ids=frozenset({"npc:gareth"}),
        known_fact_subject_ids=frozenset({"entity:hero"}),
        known_resource_ids=frozenset({"resource:gold"}),
        known_character_ids=frozenset(),
        known_location_ids=frozenset(),
        known_clock_ids=frozenset(),
        facts_by_id=(),
        current_turn_status="running",
        publication_visibility="player_visible",
    )


def _event_context() -> FixtureEventContext:
    from tests.contracts.support.materialize_proposed_events import FixtureEventContext

    return FixtureEventContext(
        campaign="campaign:fixture",
        session="session:fixture",
        scene="scene:fixture",
        turn="turn:fixture",
        sequence_start=1,
        occurred_at="2026-08-21T00:00:00Z",
        origin="in_world",
        visibility="player_visible",
    )


def _expected_resource_event() -> ResourceChangedEvent:
    return ResourceChangedEvent(
        type="ResourceChanged",
        event_id="event:fixture-1",
        event_version=1,
        campaign_id="campaign:fixture",
        session_id="session:fixture",
        scene_id="scene:fixture",
        turn_id="turn:fixture",
        sequence=1,
        occurred_at="2026-08-21T00:00:00Z",
        origin="in_world",
        visibility="player_visible",
        payload=ResourceChangedPayload(
            resource_id="resource:gold",
            entity_id="entity:hero",
            delta=2,
        ),
    )


@pytest.mark.parametrize(
    "fixture_name, expected_steps, expected_classes, expected_calls, expected_outcome, expected_events",
    _FIXTURE_CASES,
)
def test_loads_all_recorded_fixtures_with_typed_steps_and_expectations(
    fixture_name: str,
    expected_steps: tuple[str, ...],
    expected_classes: tuple[str, ...],
    expected_calls: int,
    expected_outcome: str,
    expected_events: tuple[dict[str, object], ...],
) -> None:
    load_recorded_fixture, _ = _fixture_api()

    fixture = load_recorded_fixture(_fixture_source(fixture_name))

    assert fixture.fixture_version == 1
    assert fixture.name == fixture_name
    assert tuple(step.type for step in fixture.steps) == expected_steps
    assert tuple(type(step).__name__ for step in fixture.steps) == expected_classes
    assert fixture.expected_call_count == expected_calls
    assert fixture.expected_final_outcome == expected_outcome
    assert (
        tuple(event.model_dump(mode="json") for event in fixture.expected_proposed_events)
        == expected_events
    )


@pytest.mark.parametrize(
    "fixture_name",
    ("normal-turn", "retry-then-success", "sanitized-call-log"),
)
def test_success_step_payload_is_semantic_result_model(fixture_name: str) -> None:
    load_recorded_fixture, _ = _fixture_api()
    fixture = load_recorded_fixture(_fixture_source(fixture_name))

    from neontof.contracts.semantic_result import SemanticResultV1

    success_steps = tuple(step for step in fixture.steps if step.type == "success")
    assert len(success_steps) == 1
    payload = success_steps[0].response.payload
    assert isinstance(payload, SemanticResultV1)
    assert not isinstance(payload, dict)
    assert payload.schema_version == 1


def test_normal_turn_driver_returns_accepted_result_and_materialized_events() -> None:
    result = run_invocation_scenario(
        _fixture_source("normal-turn"),
        _request(),
        _validation_context(),
        _event_context(),
    )

    from neontof.contracts.semantic_result import AcceptedSemanticResult

    assert result.fixture.expected_call_count == len(result.calls) == 1
    assert result.response is not None
    assert isinstance(result.outcome, AcceptedSemanticResult)
    assert result.outcome.value == result.response.payload
    assert result.events == (_expected_resource_event(),)
    assert tuple(
        {
            "type": event.type,
            "payload": event.payload.model_dump(mode="json"),
        }
        for event in result.events
    ) == tuple(event.model_dump(mode="json") for event in result.fixture.expected_proposed_events)
    assert result.error_message is None
    assert result.calls[0].status == "succeeded"
    assert result.calls[0].error_code is None


def test_narrative_changes_never_change_materialized_events() -> None:
    base = run_invocation_scenario(
        _fixture_source("normal-turn"),
        _request(),
        _validation_context(),
        _event_context(),
    )
    narrative_variant = run_invocation_scenario(
        _normal_turn_variant(
            narrative="a completely different narrative",
            narrative_plan=[{"text": "a completely different narrative plan"}],
        ),
        _request(),
        _validation_context(),
        _event_context(),
    )
    event_variant = run_invocation_scenario(
        _normal_turn_variant(proposed_event_delta=3),
        _request(),
        _validation_context(),
        _event_context(),
    )

    from neontof.contracts.semantic_result import AcceptedSemanticResult

    assert isinstance(base.outcome, AcceptedSemanticResult)
    assert isinstance(narrative_variant.outcome, AcceptedSemanticResult)
    assert isinstance(event_variant.outcome, AcceptedSemanticResult)
    assert narrative_variant.events == base.events
    assert event_variant.events != base.events


def test_retry_then_success_driver_replays_all_steps_and_materializes_once() -> None:
    result = run_invocation_scenario(
        _fixture_source("retry-then-success"),
        _request(),
        _validation_context(),
        _event_context(),
    )

    from neontof.contracts.semantic_result import AcceptedSemanticResult

    assert result.fixture.expected_call_count == len(result.calls) == 2
    assert result.response is not None
    assert isinstance(result.outcome, AcceptedSemanticResult)
    assert result.outcome.value == result.response.payload
    assert result.events == (_expected_resource_event(),)
    assert tuple(
        {
            "type": event.type,
            "payload": event.payload.model_dump(mode="json"),
        }
        for event in result.events
    ) == tuple(event.model_dump(mode="json") for event in result.fixture.expected_proposed_events)
    assert result.error_message is None
    assert tuple(call.status for call in result.calls) == ("failed", "succeeded")
    assert result.calls[0].error_code == "model_error"
    assert result.calls[1].error_code is None


@pytest.mark.parametrize(
    "fixture_name, error_message, error_code, status",
    (
        ("model-error", "model invocation failed", "model_error", "failed"),
        ("timeout", "model invocation timed out", "timeout", "timed_out"),
        ("invalid-json", "model response JSON is invalid", "invalid_json", "rejected"),
    ),
)
def test_failure_fixtures_create_no_response_or_events(
    fixture_name: str,
    error_message: str,
    error_code: str,
    status: str,
) -> None:
    result = run_invocation_scenario(
        _fixture_source(fixture_name),
        _request(),
        _validation_context(),
        _event_context(),
    )

    assert result.response is None
    assert result.outcome is None
    assert result.events == ()
    assert result.error_message == error_message
    assert len(result.calls) == result.fixture.expected_call_count == 1
    assert result.calls[0].error_code == error_code
    assert result.calls[0].status == status


def test_same_recorded_fixture_is_deterministic_through_driver() -> None:
    first = run_invocation_scenario(
        _fixture_source("normal-turn"),
        _request(),
        _validation_context(),
        _event_context(),
    )
    second = run_invocation_scenario(
        _fixture_source("normal-turn"),
        _request(),
        _validation_context(),
        _event_context(),
    )

    assert first.response == second.response
    assert first.outcome == second.outcome
    assert first.events == second.events
    assert first.calls == second.calls


def test_invalid_json_step_never_returns_a_success_model_response() -> None:
    _, create_recorded_fixture_provider = _fixture_api()
    provider = create_recorded_fixture_provider(_fixture_source("invalid-json"))

    with pytest.raises(ValueError, match=r"^model response JSON is invalid$"):
        provider.invoke(_request())

    assert provider.calls[-1].status == "rejected"
    assert provider.calls[-1].error_code == "invalid_json"


def test_recorded_provider_reports_script_exhaustion_with_sanitized_call() -> None:
    _, create_recorded_fixture_provider = _fixture_api()
    provider = create_recorded_fixture_provider(_fixture_source("normal-turn"))
    request = _request()

    provider.invoke(request)
    with pytest.raises(RuntimeError, match=r"^script exhausted$"):
        provider.invoke(request)

    assert len(provider.calls) == 2
    assert provider.calls[-1].status == "rejected"
    assert provider.calls[-1].error_code == "script_exhausted"


def test_json_bytes_preserve_array_order_and_scalar_types() -> None:
    load_recorded_fixture, _ = _fixture_api()
    fixture = load_recorded_fixture(_LOSSLESS_FIXTURE)

    payload = fixture.steps[0].response.payload
    assert tuple(event.payload.resource_id for event in payload.proposed_events) == (
        "resource:gold",
        "resource:silver",
    )
    mixed_values = payload.proposed_facts[0].value
    assert mixed_values == (True, 1, "1", None)
    assert tuple(type(value) for value in mixed_values) == (bool, int, str, type(None))


def test_loader_does_not_silently_overwrite_duplicate_json_keys() -> None:
    load_recorded_fixture, _ = _fixture_api()

    with pytest.raises((TypeError, ValueError)):
        load_recorded_fixture(_DUPLICATE_KEY_FIXTURE)


def test_loader_rejects_scalar_types_in_strict_numeric_fields() -> None:
    load_recorded_fixture, _ = _fixture_api()

    with pytest.raises((TypeError, ValueError)):
        load_recorded_fixture(_SCALAR_TYPE_FIXTURE)
