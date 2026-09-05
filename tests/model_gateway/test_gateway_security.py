"""Local Gatewayの公開境界と秘密の非伝播を検証する。"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from neontof.model.gateway import (
    GatewayFixtureProvider,
    ModelGateway,
)
from neontof.model.gateway_models import (
    GatewayFixtureCase,
    GatewayRequest,
    ProviderDiceResult,
    ProviderRequest,
    PublicContext,
    PublicProjection,
    PublicResourceProjection,
    SessionBudget,
)
from neontof.model.model_invoker import ModelResponse, SuccessStep
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
    return ProviderRequest(
        model_call_id=model_call_id,
        turn_id=request.turn_id,
        roles=("referee", "world_simulator", "npc_actor", "narrator"),
        public_context=request.public_context,
        player_input=request.player_input,
        dice_result=ProviderDiceResult(
            action_id=request.dice_result.action_id,
            roll_index=request.dice_result.roll_index,
            formula=request.dice_result.formula,
            result=request.dice_result.result,
        ),
        max_narrative_chars=request.max_narrative_chars,
        output_schema="semantic-result-v1",
    )


def _success_step() -> SuccessStep:
    source = (
        Path(__file__).parents[1] / "fixtures" / "providers" / "normal-turn.v1.json"
    ).read_bytes()
    fixture = load_recorded_fixture(source)
    step = fixture.steps[0]
    assert isinstance(step, SuccessStep)
    return step


class _SpyProvider(GatewayFixtureProvider):
    def __init__(self, expected_request: ProviderRequest, step: SuccessStep) -> None:
        super().__init__(
            cases=(
                # 完全envelope照合を維持したまま、境界直前の入力を記録する。
                GatewayFixtureCase(expected_request=expected_request, step=step),
            )
        )
        self.received: list[ProviderRequest] = []

    def invoke(self, request: ProviderRequest, *, timeout_seconds: float) -> ModelResponse:
        self.received.append(request)
        return super().invoke(request, timeout_seconds=timeout_seconds)


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


def test_api_key_sentinel_never_reaches_request_response_or_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "TOP_SECRET_API_KEY_SENTINEL"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)
    request = _request()
    provider = _SpyProvider(_expected(request), _success_step())
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )
    caplog.set_level(logging.DEBUG)

    outcome = gateway.invoke(request)
    records = observations.read_transcript("campaign:alpha") + observations.read_telemetry(
        "campaign:alpha"
    )
    surfaces = [
        json.dumps(outcome.model_dump(mode="json"), ensure_ascii=False),
        json.dumps([call.model_dump(mode="json") for call in provider.calls], ensure_ascii=False),
        json.dumps(
            [call.model_dump(mode="json") for call in provider.received],
            ensure_ascii=False,
        ),
        json.dumps([record.model_dump(mode="json") for record in records], ensure_ascii=False),
        caplog.text,
    ]

    assert outcome.type == "success"
    assert all(sentinel not in surface for surface in surfaces)


def test_provider_spy_receives_public_only_request_with_player_input_and_dice(
    tmp_path: Path,
) -> None:
    request = _request(player_input="search the sealed room")
    expected = _expected(request)
    step = _success_step()

    provider = _SpyProvider(expected, step)
    observations = _store(tmp_path)
    gateway = ModelGateway(
        provider=provider,
        observations=observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    outcome = gateway.invoke(request)

    assert outcome.type == "success"
    assert len(provider.received) == 1
    received = provider.received[0]
    assert received.player_input == "search the sealed room"
    assert received.dice_result.model_dump(mode="json") == {
        "action_id": "action:open-door",
        "roll_index": 0,
        "formula": "2d6",
        "result": 7,
    }
    serialized = json.dumps(received.model_dump(mode="json"), ensure_ascii=False)
    assert "campaign_seed" not in serialized
    assert "derived_seed" not in serialized
    assert "gm_only" not in serialized

    different_input_request = _request(player_input="search the hidden passage")
    different_input_provider = _SpyProvider(expected, step)
    different_input_path = tmp_path / "different-input"
    different_input_path.mkdir()
    different_input_observations = _store(different_input_path)
    different_input_gateway = ModelGateway(
        provider=different_input_provider,
        observations=different_input_observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    different_input_outcome = different_input_gateway.invoke(different_input_request)

    assert different_input_outcome.type == "failure"
    assert different_input_outcome.code == "model_error"
    assert different_input_outcome.attempts == 1
    assert len(different_input_provider.received) == 1
    assert different_input_provider.received[0].player_input == ("search the hidden passage")

    different_dice_request = request.model_copy(
        deep=True,
        update={
            "dice_result": request.dice_result.model_copy(update={"result": 8}),
        },
    )
    different_dice_provider = _SpyProvider(expected, step)
    different_dice_path = tmp_path / "different-dice"
    different_dice_path.mkdir()
    different_dice_observations = _store(different_dice_path)
    different_dice_gateway = ModelGateway(
        provider=different_dice_provider,
        observations=different_dice_observations,
        budget=_budget(),
        timeout_seconds=0.5,
    )

    different_dice_outcome = different_dice_gateway.invoke(different_dice_request)

    assert different_dice_outcome.type == "failure"
    assert different_dice_outcome.code == "model_error"
    assert different_dice_outcome.attempts == 1
    assert len(different_dice_provider.received) == 1
    assert different_dice_provider.received[0].dice_result.result == 8
