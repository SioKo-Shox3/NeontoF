"""Local Gatewayの予算境界と観測記録を検証する。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from neontof.model.gateway import ModelGateway, build_provider_request, create_gateway_fake_provider
from neontof.model.gateway_models import (
    GatewayFailure,
    GatewayRequest,
    ProviderRequest,
    PublicContext,
    PublicProjection,
    PublicResourceProjection,
    SessionBudget,
)
from neontof.model.model_invoker import ModelErrorStep, SuccessStep
from neontof.model.recorded_fixture import load_recorded_fixture


def _context() -> PublicContext:
    return PublicContext(
        publication_visibility="player_visible",
        projection=PublicProjection(
            campaign_id="campaign:alpha",
            session_id="session:main",
            scene_id="scene:main",
            turn_id=None,
            turn_request_id=None,
            location_id="location:hall",
            resources=PublicResourceProjection(hp_current=10, resources=()),
            locations=(),
            clocks=(),
            facts=(),
            scenario_outcome=None,
            known_entity_ids=(),
        ),
        known_location_ids=(),
        known_npc_ids=(),
        known_clock_ids=(),
        context_digest="a" * 64,
    )


def _request(*, player_input: str = "open the door") -> GatewayRequest:
    from neontof.rules.minimal_2d6 import DiceResult

    return GatewayRequest(
        turn_id="turn:main",
        public_context=_context(),
        player_input=player_input,
        dice_result=DiceResult(
            campaign_seed="b" * 64,
            action_id="action:open-door",
            roll_index=0,
            derived_seed="c" * 64,
            formula="2d6",
            result=7,
        ),
        max_narrative_chars=400,
    )


def _expected(request: GatewayRequest) -> ProviderRequest:
    model_call_id = f"model-call:{hashlib.sha256(request.turn_id.encode('utf-8')).hexdigest()}"
    return build_provider_request(request=request, model_call_id=model_call_id)


def _success_step() -> SuccessStep:
    source = (
        Path(__file__).parents[1] / "fixtures" / "providers" / "normal-turn.v1.json"
    ).read_bytes()
    fixture = load_recorded_fixture(source)
    step = fixture.steps[0]
    assert isinstance(step, SuccessStep)
    return step


def _store(tmp_path: Path) -> Any:
    from neontof.persistence.observation_store import ObservationStore
    from neontof.persistence.sqlite_database import SqliteDatabase

    database_path = tmp_path / "observations.sqlite3"
    database = SqliteDatabase(database_path)
    database.migrate()
    return ObservationStore(database)


def _budget(*, limit_microusd: int) -> SessionBudget:
    return SessionBudget(
        campaign_id="campaign:alpha",
        session_id="session:main",
        limit_microusd=limit_microusd,
        input_microusd_per_million_tokens=100_000,
        output_microusd_per_million_tokens=200_000,
        cached_microusd_per_million_tokens=300_000,
    )


def test_budget_is_checked_before_first_attempt(tmp_path: Path) -> None:
    request = _request()
    provider = create_gateway_fake_provider(
        expected_request=_expected(request),
        step=_success_step(),
    )
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(limit_microusd=0),
        timeout_seconds=1.0,
    )

    outcome = gateway.invoke(request)

    assert isinstance(outcome, GatewayFailure)
    assert outcome.code == "budget_exceeded"
    assert outcome.attempts == 0
    assert provider.calls == ()
    assert observations.read_telemetry("campaign:alpha", "turn:main") == ()
    transcripts = observations.read_transcript("campaign:alpha", "turn:main")
    assert len(transcripts) == 1
    assert transcripts[0].kind == "error"
    assert transcripts[0].model_call_id is None
    assert transcripts[0].data == (
        ("byte_length", 0),
        ("digest", "a" * 64),
        ("error_code", "budget_exceeded"),
    )


def test_success_records_usage_and_cost(tmp_path: Path) -> None:
    request = _request()
    step = _success_step()
    provider = create_gateway_fake_provider(
        expected_request=_expected(request),
        step=step,
    )
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(limit_microusd=100),
        timeout_seconds=1.0,
    )

    outcome = gateway.invoke(request)

    expected_cost = (
        step.response.usage.input_tokens * 100_000
        + step.response.usage.output_tokens * 200_000
        + step.response.usage.cached_tokens * 300_000
        + 999_999
    ) // 1_000_000
    assert outcome.type == "success"
    assert outcome.response == step.response
    assert outcome.attempts == 1
    assert outcome.cost_microusd == expected_cost
    assert len(provider.calls) == 1
    telemetry = observations.read_telemetry("campaign:alpha", "turn:main")
    assert len(telemetry) == 1
    assert telemetry[0].status == "succeeded"
    assert telemetry[0].input_tokens == step.response.usage.input_tokens
    assert telemetry[0].output_tokens == step.response.usage.output_tokens
    assert telemetry[0].cached_tokens == step.response.usage.cached_tokens
    assert telemetry[0].cost_microusd == expected_cost
    transcripts = observations.read_transcript("campaign:alpha", "turn:main")
    assert [record.kind for record in transcripts] == ["model_request", "model_response"]
    assert transcripts[0].data == (
        ("context_digest", "a" * 64),
        ("context_item_count", 0),
        ("output_schema", "semantic-result-v1"),
    )
    assert tuple(key for key, _ in transcripts[1].data) == (
        "narrative_byte_length",
        "proposed_event_count",
        "proposed_fact_count",
        "response_digest",
    )


def test_failed_attempt_cost_is_not_rolled_back(tmp_path: Path) -> None:
    from neontof.observability.records import TelemetryRecord

    request = _request()
    provider = create_gateway_fake_provider(
        expected_request=_expected(request),
        step=ModelErrorStep(
            type="model_error",
            code="upstream_unavailable",
            message="upstream unavailable",
        ),
    )
    observations = _store(tmp_path)
    observations.append_telemetry(
        TelemetryRecord(
            entry_id="telemetry:existing",
            campaign_id="campaign:alpha",
            session_id="session:main",
            turn_id="turn:previous",
            model_call_id="model-call:previous",
            provider="gateway_fixture",
            model="recorded_fixture",
            roles=("referee",),
            attempt=1,
            status="succeeded",
            input_tokens=1,
            output_tokens=1,
            cached_tokens=0,
            latency_ms=0,
            cost_microusd=7,
            error_code=None,
            occurred_at="2026-08-25T00:00:00Z",
        )
    )
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(limit_microusd=100),
        timeout_seconds=1.0,
    )

    outcome = gateway.invoke(request)

    assert isinstance(outcome, GatewayFailure)
    assert outcome.code == "model_error"
    assert outcome.attempts == 1
    telemetry = observations.read_telemetry("campaign:alpha")
    assert len(telemetry) == 2
    assert sum(record.cost_microusd for record in telemetry) == 7
    assert telemetry[-1].status == "failed"
    assert telemetry[-1].cost_microusd == 0

    surrogate_request = _request(player_input="observe the room")
    surrogate_step_data = _success_step().model_dump(mode="python")
    surrogate_step_data["response"]["payload"]["narrative"] = "\ud800"
    surrogate_step = SuccessStep.model_validate(surrogate_step_data, strict=True)
    surrogate_provider = create_gateway_fake_provider(
        expected_request=_expected(surrogate_request),
        step=surrogate_step,
    )
    surrogate_path = tmp_path / "surrogate"
    surrogate_path.mkdir()
    surrogate_observations = _store(surrogate_path)
    surrogate_gateway = ModelGateway(
        provider=surrogate_provider,
        observations=surrogate_observations,
        budget=_budget(limit_microusd=100),
        timeout_seconds=1.0,
    )

    surrogate_outcome = surrogate_gateway.invoke(surrogate_request)

    assert isinstance(surrogate_outcome, GatewayFailure)
    assert surrogate_outcome.code == "invalid_json"
    assert surrogate_outcome.attempts == 1
    assert len(surrogate_provider.calls) == 1
    assert surrogate_provider.calls[0].usage is not None
    assert (
        surrogate_provider.calls[0].usage.input_tokens,
        surrogate_provider.calls[0].usage.output_tokens,
        surrogate_provider.calls[0].usage.cached_tokens,
    ) == (12, 8, 0)
    expected_surrogate_cost = (12 * 100_000 + 8 * 200_000 + 0 * 300_000 + 999_999) // 1_000_000
    assert (
        surrogate_observations.session_cost_microusd("campaign:alpha", "session:main")
        == expected_surrogate_cost
    )
    surrogate_telemetry = surrogate_observations.read_telemetry("campaign:alpha")
    assert len(surrogate_telemetry) == 1
    assert surrogate_telemetry[0].status == "rejected"
    assert surrogate_telemetry[0].error_code == "invalid_json"
    assert surrogate_telemetry[0].input_tokens == 12
    assert surrogate_telemetry[0].output_tokens == 8
    assert surrogate_telemetry[0].cached_tokens == 0
    assert surrogate_telemetry[0].cost_microusd == expected_surrogate_cost
    surrogate_transcripts = surrogate_observations.read_transcript("campaign:alpha", "turn:main")
    assert [record.kind for record in surrogate_transcripts] == [
        "model_request",
        "error",
    ]
    assert surrogate_transcripts[1].data == (
        ("byte_length", 0),
        ("digest", "a" * 64),
        ("error_code", "invalid_json"),
    )
