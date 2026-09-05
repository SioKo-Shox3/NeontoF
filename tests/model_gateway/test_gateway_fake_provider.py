"""FakeとRecorded Fixtureを交換するLocal Gatewayの検証。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from neontof.model.gateway import (
    ModelGateway,
    build_provider_request,
    create_gateway_fake_provider,
    create_gateway_recorded_provider,
)
from neontof.model.gateway_models import (
    GatewayRequest,
    ProviderRequest,
    PublicContext,
    PublicProjection,
    PublicResourceProjection,
    SessionBudget,
)
from neontof.model.model_invoker import SuccessStep
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


def _source() -> bytes:
    return (
        Path(__file__).parents[1] / "fixtures" / "providers" / "normal-turn.v1.json"
    ).read_bytes()


def _store(tmp_path: Path, name: str) -> Any:
    from neontof.persistence.observation_store import ObservationStore
    from neontof.persistence.sqlite_database import SqliteDatabase

    database = SqliteDatabase(tmp_path / name)
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


def test_recorded_fixture_can_replace_fake_provider(tmp_path: Path) -> None:
    request = _request()
    expected = _expected(request)
    fixture = load_recorded_fixture(_source())
    step = fixture.steps[0]
    assert isinstance(step, SuccessStep)

    fake = create_gateway_fake_provider(expected_request=expected, step=step)
    recorded = create_gateway_recorded_provider(
        expected_requests=(expected,),
        fixture=fixture,
    )
    fake_gateway = ModelGateway(
        provider=fake,
        observations=_store(tmp_path, "fake.sqlite3"),
        budget=_budget(),
        timeout_seconds=0.5,
    )
    recorded_gateway = ModelGateway(
        provider=recorded,
        observations=_store(tmp_path, "recorded.sqlite3"),
        budget=_budget(),
        timeout_seconds=0.5,
    )

    fake_outcome = fake_gateway.invoke(request)
    recorded_outcome = recorded_gateway.invoke(request)

    assert type(fake) is type(recorded)
    assert fake_outcome.model_dump(mode="json") == recorded_outcome.model_dump(mode="json")
    assert len(fake.calls) == 1
    assert len(recorded.calls) == 1
