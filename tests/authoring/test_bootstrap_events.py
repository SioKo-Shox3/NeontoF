"""P1-05 authoring documents to bootstrap Event contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from neontof.authoring.bootstrap import (
    BootstrapInput,
    _validate_bootstrap_fact,
    build_bootstrap_events,
    derive_bootstrap_event_ids,
    derive_bootstrap_input_digest,
)
from neontof.authoring.character_loader import load_character_sheet
from neontof.authoring.scenario_loader import load_scenario
from pydantic import ValidationError

from neontof.contracts.domain import (
    CampaignCreatedEvent,
    CharacterMovedEvent,
    DomainEvent,
    FactAssertedEvent,
    FactAssertedPayload,
    PlayerInputAcceptedEvent,
    ResourceChangedEvent,
    SceneStartedEvent,
    SessionStartedEvent,
    TurnCommittedEvent,
    TurnResumedEvent,
)
from neontof.contracts.ids import Visibility
from neontof.contracts.projection import rebuild_projection
from neontof.contracts.turn_status import project_turn_status
from neontof.event_metadata import EventDraftBody
from neontof.persistence.event_store import EventStore
from neontof.persistence.sqlite_database import SqliteDatabase

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures"
CHARACTER_FIXTURE = FIXTURE_ROOT / "characters" / "minimal-character.v1.yaml"
SCENARIO_FIXTURE = FIXTURE_ROOT / "scenarios" / "minimal-scenario.v1.yaml"
OCCURRED_AT = "2026-09-02T00:00:00Z"
INPUT_DIGEST = "b66acd2df24149dcc4337c62038a998cad594098407a8302e8356b094decc1b9"
EVENT_IDS = (
    "event:bootstrap-bootstrap-bootstrap-1",
    "event:bootstrap-bootstrap-bootstrap-2",
    "event:bootstrap-bootstrap-bootstrap-3",
    "event:bootstrap-bootstrap-bootstrap-4",
    "event:bootstrap-bootstrap-bootstrap-5",
    "event:bootstrap-bootstrap-bootstrap-6",
    "event:bootstrap-bootstrap-bootstrap-7",
    "event:bootstrap-bootstrap-bootstrap-8",
    "event:bootstrap-bootstrap-bootstrap-9",
    "event:bootstrap-bootstrap-bootstrap-10",
    "event:bootstrap-bootstrap-bootstrap-11",
    "event:bootstrap-bootstrap-bootstrap-12",
    "event:bootstrap-bootstrap-bootstrap-13",
    "event:bootstrap-bootstrap-bootstrap-14",
    "event:bootstrap-bootstrap-bootstrap-15",
    "event:bootstrap-bootstrap-bootstrap-16",
    "event:bootstrap-bootstrap-bootstrap-17",
)


def _bootstrap_input_values() -> dict[str, object]:
    return {
        "campaign_id": "campaign:bootstrap",
        "session_id": "session:bootstrap",
        "scene_id": "scene:opening",
        "turn_id": "turn:bootstrap",
        "turn_request_id": "turn-request:bootstrap",
        "input_digest": INPUT_DIGEST,
        "campaign_seed": "b" * 64,
        "campaign_name": "Minimal campaign",
        "session_title": "Opening session",
        "scene_label": "Forest edge",
        "character": load_character_sheet(CHARACTER_FIXTURE),
        "scenario": load_scenario(SCENARIO_FIXTURE),
    }


def _bootstrap_input() -> BootstrapInput:
    return BootstrapInput.model_validate(_bootstrap_input_values(), strict=True)


def _materialized_events(tmp_path: Path) -> tuple[DomainEvent, ...]:
    database = SqliteDatabase(tmp_path / "runtime" / "bootstrap-events.sqlite3")
    database.migrate()
    batch = build_bootstrap_events(_bootstrap_input(), OCCURRED_AT, EVENT_IDS)
    stored = EventStore(database).append(batch)
    return tuple(item.event for item in stored)


def test_bootstrap_uses_only_existing_domain_event_types(tmp_path: Path) -> None:
    events = _materialized_events(tmp_path)

    assert tuple(type(event) for event in events) == (
        CampaignCreatedEvent,
        SessionStartedEvent,
        SceneStartedEvent,
        PlayerInputAcceptedEvent,
        TurnResumedEvent,
        ResourceChangedEvent,
        ResourceChangedEvent,
        CharacterMovedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        FactAssertedEvent,
        TurnCommittedEvent,
    )
    assert tuple(event.type for event in events) == (
        "CampaignCreated",
        "SessionStarted",
        "SceneStarted",
        "PlayerInputAccepted",
        "TurnResumed",
        "ResourceChanged",
        "ResourceChanged",
        "CharacterMoved",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "FactAsserted",
        "TurnCommitted",
    )
    campaign_created = events[0]
    session_started = events[1]
    scene_started = events[2]
    accepted = events[3]
    resumed = events[4]
    committed = events[-1]
    assert isinstance(campaign_created, CampaignCreatedEvent)
    assert campaign_created.payload.name == "Minimal campaign"
    assert campaign_created.session_id is None
    assert campaign_created.scene_id is None
    assert campaign_created.turn_id is None
    assert isinstance(session_started, SessionStartedEvent)
    assert session_started.payload.scenario_id == "scenario:minimal"
    assert session_started.payload.title == "Opening session"
    assert isinstance(scene_started, SceneStartedEvent)
    assert scene_started.scene_id == "scene:opening"
    assert scene_started.payload.label == "Forest edge"
    assert isinstance(accepted, PlayerInputAcceptedEvent)
    assert accepted.payload.turn_request_id == "turn-request:bootstrap"
    assert accepted.payload.input_digest == INPUT_DIGEST
    assert isinstance(resumed, TurnResumedEvent)
    assert resumed.payload.turn_request_id == "turn-request:bootstrap"
    assert isinstance(committed, TurnCommittedEvent)
    assert committed.payload.turn_request_id == "turn-request:bootstrap"

    facts = tuple(event for event in events if isinstance(event, FactAssertedEvent))
    assert tuple(
        (
            event.payload.kind,
            event.payload.holder,
            event.payload.subject_id,
            event.payload.predicate,
            event.payload.value,
            event.visibility,
        )
        for event in facts
    ) == (
        (
            "fact",
            "player_character",
            "entity:character-hana",
            "inventory_item",
            "item:lantern",
            "player_visible",
        ),
        (
            "fact",
            "player_character",
            "entity:character-hana",
            "character_schema_version",
            1,
            "player_visible",
        ),
        ("fact", "world", None, "objective", "scene:opening", "player_visible"),
        ("fact", "world", None, "scenario_version", "v1", "player_visible"),
        ("fact", "world", None, "secret", "secret:inner-chamber", "gm_only"),
        (
            "fact",
            "world",
            None,
            "clue",
            "entity:clue-broken-seal",
            "player_visible",
        ),
        ("fact", "world", None, "clue", "entity:clue-astral-mark", "gm_only"),
        ("fact", "world", None, "clue", "entity:clue-silver-key", "npc:warden"),
    )
    assert not any(event.type in {"ClockAdvanced", "ClockInitialized"} for event in events)
    assert not any(
        isinstance(event, FactAssertedEvent) and event.payload.predicate == "location"
        for event in events
    )


def test_bootstrap_returns_event_batch_with_event_ids_and_occurred_at() -> None:
    input_value = _bootstrap_input()

    assert (
        derive_bootstrap_input_digest(
            campaign_id="campaign:bootstrap",
            session_id="session:bootstrap",
            scene_id="scene:opening",
            turn_id="turn:bootstrap",
            turn_request_id="turn-request:bootstrap",
            campaign_seed="b" * 64,
            campaign_name="Minimal campaign",
            session_title="Opening session",
            scene_label="Forest edge",
        )
        == INPUT_DIGEST
    )
    assert derive_bootstrap_event_ids(input_value) == EVENT_IDS

    batch = build_bootstrap_events(input_value, OCCURRED_AT, EVENT_IDS)

    assert batch.campaign_id == "campaign:bootstrap"
    assert tuple(draft.body.event_id for draft in batch.drafts) == EVENT_IDS
    assert tuple(draft.body.occurred_at for draft in batch.drafts) == (OCCURRED_AT,) * 17
    assert "sequence" not in EventDraftBody.model_fields

    with pytest.raises(ValueError):
        build_bootstrap_events(input_value, OCCURRED_AT, EVENT_IDS[:-1])
    with pytest.raises(ValueError):
        build_bootstrap_events(
            input_value,
            OCCURRED_AT,
            EVENT_IDS + ("event:bootstrap-bootstrap-bootstrap-18",),
        )

    bad_digest = _bootstrap_input_values()
    bad_digest["input_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        BootstrapInput.model_validate(bad_digest, strict=True)


def test_bootstrap_events_rebuild_initial_hp_resource_location_and_clock(tmp_path: Path) -> None:
    events = _materialized_events(tmp_path)

    projection = rebuild_projection(events)

    assert projection.campaign_id == "campaign:bootstrap"
    assert projection.scenario_id == "scenario:minimal"
    assert projection.scene_id == "scene:opening"
    assert projection.scene_label == "Forest edge"
    assert {
        (resource.resource_id, resource.entity_id): resource.value
        for resource in projection.resources
    } == {
        ("resource:hp", "entity:character-hana"): 7,
        ("resource:stamina", "entity:character-hana"): 3,
    }
    assert tuple(
        (location.character_id, location.location_id) for location in projection.locations
    ) == (("character:hana", "location:forest-edge"),)
    assert projection.clocks == ()
    assert len(projection.facts) == 8
    assert all(fact.status == "active" for fact in projection.facts)
    assert project_turn_status("turn:bootstrap", events) == "committed"


def test_bootstrap_secret_fact_is_gm_only(tmp_path: Path) -> None:
    events = _materialized_events(tmp_path)
    fact_events = tuple(event for event in events if isinstance(event, FactAssertedEvent))
    secret = tuple(event for event in fact_events if event.payload.predicate == "secret")
    clues = tuple(event for event in fact_events if event.payload.predicate == "clue")

    assert len(secret) == 1
    assert secret[0].payload.value == "secret:inner-chamber"
    assert secret[0].payload.subject_id is None
    assert secret[0].visibility == "gm_only"
    assert {event.payload.value: event.visibility for event in clues} == {
        "entity:clue-broken-seal": "player_visible",
        "entity:clue-astral-mark": "gm_only",
        "entity:clue-silver-key": "npc:warden",
    }
    assert "The inner chamber is sealed from visitors." not in repr(events)

    projection = rebuild_projection(events)
    player_visible_values = tuple(
        fact.value for fact in projection.facts if fact.visibility == "player_visible"
    )
    assert "secret:inner-chamber" not in player_visible_values
    assert "entity:clue-astral-mark" not in player_visible_values
    assert "entity:clue-silver-key" not in player_visible_values
    assert "entity:clue-broken-seal" in player_visible_values


def test_fact_allowlist_accepts_only_closed_scenario_outcome_shape() -> None:
    secret = FactAssertedPayload(
        kind="fact",
        holder="world",
        subject_id=None,
        predicate="secret",
        value="secret:inner-chamber",
    )
    success = FactAssertedPayload(
        kind="fact",
        holder="world",
        subject_id=None,
        predicate="scenario_outcome",
        value="success",
    )
    failure = FactAssertedPayload(
        kind="fact",
        holder="world",
        subject_id=None,
        predicate="scenario_outcome",
        value="failure",
    )

    _validate_bootstrap_fact(payload=secret, visibility="gm_only")
    _validate_bootstrap_fact(payload=success, visibility="player_visible")
    _validate_bootstrap_fact(payload=failure, visibility="player_visible")

    rejected: tuple[tuple[FactAssertedPayload, Visibility], ...] = (
        (
            FactAssertedPayload(
                kind="fact",
                holder="world",
                subject_id=None,
                predicate="unknown_predicate",
                value="unknown",
            ),
            "player_visible",
        ),
        (
            FactAssertedPayload(
                kind="fact",
                holder="world",
                subject_id=None,
                predicate="location",
                value="location:forest-edge",
            ),
            "player_visible",
        ),
        (secret, "player_visible"),
        (
            FactAssertedPayload(
                kind="fact",
                holder="world",
                subject_id=None,
                predicate="scenario_outcome",
                value="draw",
            ),
            "player_visible",
        ),
    )
    for payload, visibility in rejected:
        with pytest.raises(ValueError):
            _validate_bootstrap_fact(payload=payload, visibility=visibility)
