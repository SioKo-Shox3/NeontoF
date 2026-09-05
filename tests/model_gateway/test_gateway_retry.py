"""Local Gatewayの単一呼出しと失敗時のretryなし契約を検証する。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from neontof.model.gateway import (
    GatewayFixtureProvider,
    ModelGateway,
    build_provider_request,
    create_gateway_fake_provider,
)
from neontof.model.gateway_models import (
    GatewayFailure,
    GatewayFixtureCase,
    GatewayRequest,
    ProviderRequest,
    PublicContext,
    PublicProjection,
    PublicResourceProjection,
    SessionBudget,
)
from neontof.model.model_invoker import (
    InvalidJsonStep,
    ModelErrorStep,
    SuccessStep,
    TimeoutStep,
)
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


def _request() -> GatewayRequest:
    from neontof.rules.minimal_2d6 import DiceResult

    return GatewayRequest(
        turn_id="turn:main",
        public_context=_context(),
        player_input="open the door",
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

    database = SqliteDatabase(tmp_path / "observations.sqlite3")
    database.migrate()
    return ObservationStore(database)


def _budget() -> SessionBudget:
    return SessionBudget(
        campaign_id="campaign:alpha",
        session_id="session:main",
        limit_microusd=100,
        input_microusd_per_million_tokens=100_000,
        output_microusd_per_million_tokens=200_000,
        cached_microusd_per_million_tokens=300_000,
    )


def test_timeout_aborts_without_retry(tmp_path: Path) -> None:
    request = _request()
    provider = create_gateway_fake_provider(
        expected_request=_expected(request),
        step=TimeoutStep(type="timeout"),
    )
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    outcome = gateway.invoke(request)

    assert isinstance(outcome, GatewayFailure)
    assert outcome.code == "timeout"
    assert outcome.attempts == 1
    assert len(provider.calls) == 1
    telemetry = observations.read_telemetry("campaign:alpha", "turn:main")
    assert len(telemetry) == 1
    assert telemetry[0].status == "timed_out"
    assert telemetry[0].error_code == "timeout"
    assert all(record.kind != "retry" for record in observations.read_transcript("campaign:alpha"))


@pytest.mark.parametrize("failure_code", ("model_error", "invalid_json"))
def test_model_error_aborts_without_retry(failure_code: str, tmp_path: Path) -> None:
    request = _request()
    step: ModelErrorStep | InvalidJsonStep
    if failure_code == "model_error":
        step = ModelErrorStep(
            type="model_error",
            code="upstream_unavailable",
            message="upstream unavailable",
        )
    else:
        step = InvalidJsonStep(type="invalid_json", body="not-json")
    provider = create_gateway_fake_provider(
        expected_request=_expected(request),
        step=step,
    )
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    outcome = gateway.invoke(request)

    assert isinstance(outcome, GatewayFailure)
    assert outcome.code == failure_code
    assert outcome.attempts == 1
    assert len(provider.calls) == 1
    telemetry = observations.read_telemetry("campaign:alpha", "turn:main")
    assert len(telemetry) == 1
    assert telemetry[0].error_code == failure_code
    assert all(record.kind != "retry" for record in observations.read_transcript("campaign:alpha"))


def test_one_turn_uses_one_model_call_id(tmp_path: Path) -> None:
    first_request = _request()
    second_request = first_request.model_copy(update={"turn_id": "turn:second"})
    provider = GatewayFixtureProvider(
        cases=(
            GatewayFixtureCase(
                expected_request=_expected(first_request),
                step=_success_step(),
            ),
            GatewayFixtureCase(
                expected_request=_expected(second_request),
                step=_success_step(),
            ),
        )
    )
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    first_outcome = gateway.invoke(first_request)
    second_outcome = gateway.invoke(second_request)

    assert first_outcome.type == "success"
    assert second_outcome.type == "success"
    assert len(provider.calls) == 2
    expected_first_call_id = (
        f"model-call:{hashlib.sha256(first_request.turn_id.encode('utf-8')).hexdigest()}"
    )
    expected_second_call_id = (
        f"model-call:{hashlib.sha256(second_request.turn_id.encode('utf-8')).hexdigest()}"
    )
    assert provider.calls[0].request_id == expected_first_call_id
    assert provider.calls[0].attempt == 1
    assert provider.calls[1].request_id == expected_second_call_id
    assert provider.calls[1].attempt == 1
    assert expected_first_call_id != expected_second_call_id
    first_telemetry = observations.read_telemetry("campaign:alpha", "turn:main")
    second_telemetry = observations.read_telemetry("campaign:alpha", "turn:second")
    assert len(first_telemetry) == 1
    assert first_telemetry[0].model_call_id == expected_first_call_id
    assert first_telemetry[0].attempt == 1
    assert len(second_telemetry) == 1
    assert second_telemetry[0].model_call_id == expected_second_call_id
    assert second_telemetry[0].attempt == 1
