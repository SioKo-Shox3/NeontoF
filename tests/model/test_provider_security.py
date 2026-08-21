"""Focused tests for provider sanitization, digest stability, and visibility boundaries."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from neontof.contracts.projection import FactRecord
from tests.model.support.filter_context_by_visibility import filter_context_by_visibility
from tests.model.support.run_invocation_scenario import run_invocation_scenario

if TYPE_CHECKING:
    from neontof.model.model_invoker import ModelRequest, PublicationVisibility, Role
    from neontof.model.recorded_fixture import TestProvider

    from neontof.contracts.semantic_result import SemanticValidationContext
    from tests.contracts.support.materialize_proposed_events import FixtureEventContext


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "providers"
EXPECTED_CONTEXT_PREIMAGE = (
    '[{"event_id":"event:fact-source","fact_id":"fact:'
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0",'
    '"holder":"world","kind":"fact","predicate":"status",'
    '"status":"active","subject_id":"entity:hero","value":"public",'
    '"visibility":"player_visible"}]'
)
EXPECTED_CONTEXT_DIGEST = "e88d0b92defd512874ef3955493bc82a3337ec983de178ac5f72c34c64d0ee55"
TOP_SECRET_SENTINEL = "TOP_SECRET_SENTINEL"


def _fixture_source(name: str) -> bytes:
    return (FIXTURE_DIR / f"{name}.v1.json").read_bytes()


def _request(
    *,
    context: tuple[FactRecord, ...] = (),
    model_call_id: str = "model-call:security",
    turn_id: str = "turn:security",
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


def _fact(
    *,
    value: str = "public",
    visibility: str = "player_visible",
    event_id: str = "event:fact-source",
) -> FactRecord:
    return FactRecord(
        fact_id=f"fact:{'a' * 64}:0",
        event_id=event_id,
        kind="fact",
        holder="world",
        subject_id="entity:hero",
        predicate="status",
        value=value,
        visibility=visibility,
        status="active",
    )


def _provider(request: ModelRequest) -> TestProvider:
    from neontof.model.recorded_fixture import create_recorded_fixture_provider

    provider = create_recorded_fixture_provider(_fixture_source("sanitized-call-log"))
    provider.invoke(request)
    return provider


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
        campaign="campaign:security",
        session="session:security",
        scene="scene:security",
        turn="turn:security",
        sequence_start=1,
        occurred_at="2026-08-21T00:00:00Z",
        origin="in_world",
        visibility="player_visible",
    )


def _visibility_facts() -> tuple[FactRecord, ...]:
    return (
        FactRecord(
            fact_id=f"fact:{0:064x}:0",
            event_id="event:visibility-player",
            kind="fact",
            holder="world",
            subject_id=None,
            predicate="visibility",
            value="player",
            visibility="player_visible",
            status="active",
        ),
        FactRecord(
            fact_id=f"fact:{1:064x}:0",
            event_id="event:visibility-gm",
            kind="fact",
            holder="world",
            subject_id=None,
            predicate="visibility",
            value="gm",
            visibility="gm_only",
            status="active",
        ),
        FactRecord(
            fact_id=f"fact:{2:064x}:0",
            event_id="event:visibility-gareth",
            kind="fact",
            holder="npc:gareth",
            subject_id="entity:hero",
            predicate="visibility",
            value="gareth",
            visibility="npc:gareth",
            status="active",
        ),
        FactRecord(
            fact_id=f"fact:{3:064x}:0",
            event_id="event:visibility-other",
            kind="fact",
            holder="npc:other",
            subject_id="entity:hero",
            predicate="visibility",
            value="other",
            visibility="npc:other",
            status="active",
        ),
    )


def test_context_digest_matches_fixed_canonical_vector() -> None:
    request = _request(context=(_fact(),))
    canonical_preimage = json.dumps(
        [fact.model_dump(mode="json") for fact in request.context],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert canonical_preimage == EXPECTED_CONTEXT_PREIMAGE
    assert hashlib.sha256(canonical_preimage.encode("utf-8")).hexdigest() == (
        EXPECTED_CONTEXT_DIGEST
    )
    assert _provider(request).calls[0].context_digest == EXPECTED_CONTEXT_DIGEST


@pytest.mark.parametrize(
    "metadata_case",
    (
        "model_call_id",
        "turn_id",
        "roles",
        "publication_visibility",
    ),
)
def test_context_digest_ignores_request_metadata(metadata_case: str) -> None:
    if metadata_case == "model_call_id":
        request = _request(context=(_fact(),), model_call_id="model-call:changed")
    elif metadata_case == "turn_id":
        request = _request(context=(_fact(),), turn_id="turn:changed")
    elif metadata_case == "roles":
        request = _request(context=(_fact(),), roles=("npc_actor",))
    else:
        request = _request(context=(_fact(),), publication_visibility="npc:gareth")

    assert _provider(request).calls[0].context_digest == EXPECTED_CONTEXT_DIGEST


def test_context_digest_changes_when_context_changes() -> None:
    request = _request(context=(_fact(value="changed"),))

    assert _provider(request).calls[0].context_digest != EXPECTED_CONTEXT_DIGEST


def test_sanitized_call_log_contains_only_safe_observation_fields() -> None:
    serialized = _provider(_request(context=(_fact(),))).calls[0].model_dump(mode="json")

    assert set(serialized) == {
        "request_id",
        "attempt",
        "publication_visibility",
        "context_digest",
        "context_item_count",
        "usage",
        "status",
        "error_code",
    }
    assert serialized["request_id"] == "model-call:security"
    assert serialized["publication_visibility"] == "player_visible"
    assert serialized["context_digest"] == EXPECTED_CONTEXT_DIGEST
    assert serialized["context_item_count"] == 1
    assert serialized["usage"] == {
        "input_tokens": 4,
        "output_tokens": 3,
        "cached_tokens": 0,
    }
    assert serialized["status"] == "succeeded"
    assert serialized["error_code"] is None


def test_sanitize_provider_call_log_returns_only_safe_typed_fields() -> None:
    from neontof.model.model_invoker import ModelUsage, ProviderCallLogMeta
    from neontof.model.recorded_fixture import sanitize_provider_call_log

    request = _request(context=(_fact(),))
    meta = ProviderCallLogMeta.model_validate(
        {
            "attempt": 1,
            "context_item_count": 1,
            "usage": ModelUsage.model_validate(
                {"input_tokens": 4, "output_tokens": 3, "cached_tokens": 0}
            ),
            "status": "succeeded",
            "error_code": None,
        }
    )

    entry = sanitize_provider_call_log(request, meta)
    serialized = entry.model_dump(mode="json")

    assert set(serialized) == {
        "request_id",
        "attempt",
        "publication_visibility",
        "context_digest",
        "context_item_count",
        "usage",
        "status",
        "error_code",
    }
    assert serialized["request_id"] == "model-call:security"
    assert serialized["publication_visibility"] == "player_visible"
    assert serialized["context_digest"] == EXPECTED_CONTEXT_DIGEST
    assert serialized["context_item_count"] == 1
    assert serialized["usage"] == {
        "input_tokens": 4,
        "output_tokens": 3,
        "cached_tokens": 0,
    }


def test_request_and_sanitized_log_never_carry_secret_fields_or_raw_secret() -> None:
    from neontof.model.model_invoker import ModelRequest

    request = _request(context=(_fact(value=TOP_SECRET_SENTINEL),))
    provider = _provider(request)

    assert not any(
        token in field_name.lower()
        for field_name in ModelRequest.model_fields
        for token in ("api", "key", "secret", "credential")
    )
    assert TOP_SECRET_SENTINEL not in provider.calls[0].model_dump_json()
    assert all(
        TOP_SECRET_SENTINEL.encode("utf-8") not in path.read_bytes()
        for path in FIXTURE_DIR.glob("*.json")
    )


@pytest.mark.parametrize(
    "fixture_name, expected_message, expected_code, expected_status, raw_values",
    (
        (
            "model-error",
            "model invocation failed",
            "model_error",
            "failed",
            (
                "upstream_unavailable",
                "upstream said: connection reset by peer",
                "model invocation failed",
            ),
        ),
        (
            "timeout",
            "model invocation timed out",
            "timeout",
            "timed_out",
            ("model invocation timed out",),
        ),
        (
            "invalid-json",
            "model response JSON is invalid",
            "invalid_json",
            "rejected",
            ("not-json", "model response JSON is invalid"),
        ),
    ),
)
def test_failure_mapping_is_fixed_and_redacted(
    fixture_name: str,
    expected_message: str,
    expected_code: str,
    expected_status: str,
    raw_values: tuple[str, ...],
) -> None:
    result = run_invocation_scenario(
        _fixture_source(fixture_name),
        _request(),
        _validation_context(),
        _event_context(),
    )

    assert result.error_message == expected_message
    assert result.response is None
    assert result.events == ()
    assert result.calls[-1].error_code == expected_code
    assert result.calls[-1].status == expected_status
    serialized = result.calls[-1].model_dump_json()
    assert all(raw_value not in serialized for raw_value in raw_values)


@pytest.mark.parametrize(
    "field, value",
    (
        ("input_tokens", -1),
        ("input_tokens", True),
        ("input_tokens", "1"),
        ("output_tokens", -1),
        ("cached_tokens", True),
    ),
)
def test_model_usage_rejects_non_negative_strict_counter_values(field: str, value: object) -> None:
    from neontof.model.model_invoker import ModelUsage

    values: dict[str, object] = {
        "input_tokens": 1,
        "output_tokens": 1,
        "cached_tokens": 0,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError)):
        ModelUsage.model_validate(values)


@pytest.mark.parametrize(
    "field, value",
    (
        ("attempt", 0),
        ("attempt", True),
        ("context_item_count", -1),
        ("context_item_count", True),
        ("context_digest", "A" * 64),
        ("context_digest", "0" * 63),
    ),
)
def test_sanitized_call_log_rejects_invalid_typed_metadata(field: str, value: object) -> None:
    from neontof.model.recorded_fixture import SanitizedProviderCallLogEntry

    values: dict[str, object] = {
        "request_id": "model-call:security",
        "attempt": 1,
        "publication_visibility": "player_visible",
        "context_digest": EXPECTED_CONTEXT_DIGEST,
        "context_item_count": 0,
        "usage": None,
        "status": "succeeded",
        "error_code": None,
    }
    values[field] = value

    with pytest.raises((TypeError, ValueError)):
        SanitizedProviderCallLogEntry.model_validate(values)


def test_success_does_not_emit_secret_to_stdout_stderr_or_logs(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    request = _request(context=(_fact(value=TOP_SECRET_SENTINEL),))

    _provider(request)

    captured = capsys.readouterr()
    emitted = f"{captured.out}\n{captured.err}\n{caplog.text}"
    assert TOP_SECRET_SENTINEL not in emitted


def test_failure_does_not_emit_raw_error_to_stdout_stderr_or_logs(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelErrorStep

    caplog.set_level(logging.DEBUG)
    raw_error = "upstream said: connection reset by peer"
    provider = create_fake_provider(
        ModelErrorStep(type="model_error", code="upstream_unavailable", message=raw_error)
    )

    with pytest.raises(RuntimeError, match="^model invocation failed$"):
        provider.invoke(_request())

    captured = capsys.readouterr()
    emitted = f"{captured.out}\n{captured.err}\n{caplog.text}"
    assert raw_error not in emitted


def test_player_filter_returns_player_visible_facts_only() -> None:
    facts = _visibility_facts()

    filtered = filter_context_by_visibility(facts, "player_visible")

    assert tuple(fact.visibility for fact in filtered) == ("player_visible",)


def test_gm_only_is_never_selected_by_publication_filter() -> None:
    facts = _visibility_facts()

    assert filter_context_by_visibility(facts, "gm_only") == ()


def test_npc_filter_returns_exact_target_and_excludes_other_visibility() -> None:
    facts = _visibility_facts()

    filtered = filter_context_by_visibility(facts, "npc:gareth")

    assert tuple(fact.visibility for fact in filtered) == ("npc:gareth",)


def test_npc_filter_does_not_return_another_npc() -> None:
    facts = _visibility_facts()

    filtered = filter_context_by_visibility(facts, "npc:other")

    assert tuple(fact.visibility for fact in filtered) == ("npc:other",)
    assert all(fact.visibility != "npc:gareth" for fact in filtered)


def test_publication_visibility_filter_stays_test_only() -> None:
    production_path = (
        Path(__file__).parents[2] / "src" / "neontof" / "model" / "publication_visibility.py"
    )

    assert not production_path.exists()
