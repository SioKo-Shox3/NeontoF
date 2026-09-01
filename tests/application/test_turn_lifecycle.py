"""P1-03 Turn lifecycle coordinator contract tests."""

from __future__ import annotations

import ast
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, Self, cast

import pytest
from pydantic import ValidationError

from neontof.application import turn_lifecycle
from neontof.application.turn_lifecycle import (
    ActiveTurnRegistry,
    TurnLifecycleCoordinator,
    build_recovery_metadata,
    build_turn_event_batch,
    derive_revert_event_id,
    reserve_recovery_event_ids,
    select_response_payload,
)
from neontof.application.turn_models import (
    CachedTurnResponse,
    FinalTurnRequestRecord,
    PreparedEffect,
    PreparedTurn,
    ProcessingTurnRequestRecord,
    RecoveryEventIdSource,
    RecoveryEventMetadata,
    RecoveryMetadataFactory,
    RequestCompletionStatus,
    ResponseRebuilder,
    RevertedTurnResult,
    StoreError,
    TurnEventBatchFactory,
    TurnEventIdSequence,
    TurnRequestIdentity,
    TurnRequestIntent,
    UndoBlockedResult,
    UndoCommand,
    UndoResponseRebuilder,
)
from neontof.contracts.domain import (
    ClockAdvancedEvent,
    ClockAdvancedPayload,
    DomainEvent,
    SessionEndedEvent,
)
from neontof.contracts.ids import OccurredAt
from neontof.contracts.projection import rebuild_projection
from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody, TurnEventMetadata
from neontof.persistence.event_store import EventStore
from neontof.persistence.observation_store import ObservationStore
from neontof.persistence.sqlite_database import SqliteDatabase
from neontof.persistence.turn_request_store import TurnRequestStore

OCCURRED_AT = "2026-08-31T00:00:00Z"
PAYLOAD = b'{"response":"opaque"}'


def _intent(**overrides: object) -> TurnRequestIntent:
    values: dict[str, object] = {
        "request_key": b"lifecycle-key",
        "request_kind": "submit",
        "requested_media_type": "application/json",
        "turn_request_id": "turn-request:lifecycle",
        "campaign_id": "campaign:lifecycle",
        "session_id": "session:lifecycle",
        "scene_id": "scene:lifecycle",
        "turn_id": "turn:lifecycle",
        "root_turn_request_id": "turn-request:lifecycle",
        "input_digest": "a" * 64,
        "initial_recovery_payload": b"v1-initial-opaque-payload",
    }
    values.update(overrides)
    return TurnRequestIntent.model_validate(values, strict=True)


def _database(
    tmp_path: Path,
) -> tuple[SqliteDatabase, EventStore, TurnRequestStore, ObservationStore]:
    database = SqliteDatabase(tmp_path / "runtime" / "lifecycle.sqlite3")
    database.migrate()
    event_store = EventStore(database)
    return (
        database,
        event_store,
        TurnRequestStore(database, event_store),
        ObservationStore(database),
    )


def _body(
    event_id: str,
    event_type: str,
    *,
    campaign_id: str = "campaign:lifecycle",
    session_id: str | None = "session:lifecycle",
    scene_id: str | None = "scene:lifecycle",
    turn_id: str | None = "turn:lifecycle",
    payload: Mapping[str, object],
    origin: Literal["in_world", "table_correction"] = "in_world",
    visibility: Literal["gm_only", "player_visible"] = "player_visible",
    occurred_at: str = OCCURRED_AT,
) -> EventDraftBody:
    if event_type == "CampaignCreated":
        session_id = None
        scene_id = None
        turn_id = None
    elif event_type == "SessionStarted":
        scene_id = None
        turn_id = None
    elif event_type == "SceneStarted":
        turn_id = None
    if event_type in {"SessionEnded", "TurnReverted"}:
        scene_id = None
        turn_id = None
    return EventDraftBody(
        type=event_type,
        event_id=event_id,
        event_version=1,
        campaign_id=campaign_id,
        session_id=session_id,
        scene_id=scene_id,
        turn_id=turn_id,
        occurred_at=occurred_at,
        origin=origin,
        visibility=visibility,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
    )


def _draft(
    event_id: str,
    event_type: str,
    *,
    campaign_id: str = "campaign:lifecycle",
    session_id: str | None = "session:lifecycle",
    scene_id: str | None = "scene:lifecycle",
    turn_id: str | None = "turn:lifecycle",
    payload: Mapping[str, object],
    origin: Literal["in_world", "table_correction"] = "in_world",
    visibility: Literal["gm_only", "player_visible"] = "player_visible",
    occurred_at: str = OCCURRED_AT,
) -> EventDraft:
    return EventDraft(
        body=_body(
            event_id,
            event_type,
            campaign_id=campaign_id,
            session_id=session_id,
            scene_id=scene_id,
            turn_id=turn_id,
            payload=payload,
            origin=origin,
            visibility=visibility,
            occurred_at=occurred_at,
        )
    )


def _batch(*drafts: EventDraft, campaign_id: str = "campaign:lifecycle") -> EventBatch:
    return EventBatch(campaign_id=campaign_id, drafts=tuple(drafts))


def _seed_turn(
    event_store: EventStore,
    *,
    session_id: str = "session:lifecycle",
    scene_id: str = "scene:lifecycle",
    turn_id: str = "turn:lifecycle",
    turn_request_id: str = "turn-request:lifecycle",
    include_awaiting: bool = False,
    event_prefix: str = "seed",
) -> tuple[DomainEvent, ...]:
    drafts = [
        _draft(f"event:{event_prefix}-campaign", "CampaignCreated", payload={"name": "NeontoF"}),
        _draft(
            f"event:{event_prefix}-session",
            "SessionStarted",
            session_id=session_id,
            payload={"scenario_id": None, "title": "Opening"},
        ),
        _draft(
            f"event:{event_prefix}-scene",
            "SceneStarted",
            session_id=session_id,
            scene_id=scene_id,
            turn_id=None,
            payload={"label": "Hall"},
        ),
        _draft(
            f"event:{event_prefix}-accepted",
            "PlayerInputAccepted",
            session_id=session_id,
            scene_id=scene_id,
            turn_id=turn_id,
            payload={"turn_request_id": turn_request_id, "input_digest": "a" * 64},
        ),
        _draft(
            f"event:{event_prefix}-resumed",
            "TurnResumed",
            session_id=session_id,
            scene_id=scene_id,
            turn_id=turn_id,
            payload={"turn_request_id": turn_request_id},
        ),
    ]
    if include_awaiting:
        drafts.append(
            _draft(
                f"event:{event_prefix}-awaiting",
                "TurnAwaitingPlayer",
                session_id=session_id,
                scene_id=scene_id,
                turn_id=turn_id,
                payload={"turn_request_id": turn_request_id},
            )
        )
    else:
        drafts.append(
            _draft(
                f"event:{event_prefix}-committed",
                "TurnCommitted",
                session_id=session_id,
                scene_id=scene_id,
                turn_id=turn_id,
                payload={"turn_request_id": turn_request_id},
            )
        )
    event_store.append(_batch(*drafts))
    return event_store.read_campaign("campaign:lifecycle")


def _prepared(
    *,
    terminal_status: str = "committed",
    effect_candidates: tuple[PreparedEffect, ...] = (),
    scenario_end: str | None = None,
    staged_recovery_payload: bytes | None = PAYLOAD,
) -> PreparedTurn:
    return PreparedTurn(
        effect_candidates=effect_candidates,
        terminal_status=cast(Literal["awaiting_player", "committed", "aborted"], terminal_status),
        scenario_end=cast(Literal["success", "failure"] | None, scenario_end),
        abort_reason="failed" if terminal_status == "aborted" else None,
        staged_recovery_payload=staged_recovery_payload,
    )


def _event_ids(identity: TurnRequestIdentity, prepared: PreparedTurn) -> tuple[str, ...]:
    count = (2 if identity.request_kind == "submit" else 1) + len(prepared.effect_candidates) + 1
    if prepared.scenario_end is not None:
        count += 1
    return tuple(f"event:generated-{index}" for index in range(1, count + 1))


def _response_rebuilder(
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
    status: str,
    payload: bytes,
) -> CachedTurnResponse:
    del campaign_events, status
    return CachedTurnResponse(status_code=200, media_type=record.requested_media_type, body=payload)


def _undo_response_rebuilder(
    command: UndoCommand,
    campaign_events: tuple[DomainEvent, ...],
    status: str,
    target_turn_id: str,
    revert_event_id: str,
) -> CachedTurnResponse:
    del command, campaign_events, status, target_turn_id, revert_event_id
    return CachedTurnResponse(
        status_code=200, media_type="application/json", body=b'{"undone":true}'
    )


def _coordinator(
    event_store: EventStore,
    request_store: TurnRequestStore,
    observation_store: ObservationStore,
    *,
    registry: ActiveTurnRegistry | None = None,
    response_rebuilder: object = _response_rebuilder,
    undo_response_rebuilder: object = _undo_response_rebuilder,
    turn_event_factory: object = build_turn_event_batch,
    event_id_sequence: object = _event_ids,
    utc_occurred_at: object = lambda: OCCURRED_AT,
    recovery_event_id_source: object = reserve_recovery_event_ids,
    recovery_metadata_factory: object = build_recovery_metadata,
    event_boundary_lock: threading.Lock | None = None,
) -> TurnLifecycleCoordinator:
    return TurnLifecycleCoordinator(
        event_store=event_store,
        request_store=request_store,
        observation_store=observation_store,
        active_turn_registry=registry or ActiveTurnRegistry(),
        response_rebuilder=cast(ResponseRebuilder, response_rebuilder),
        undo_response_rebuilder=cast(UndoResponseRebuilder, undo_response_rebuilder),
        turn_event_factory=cast(TurnEventBatchFactory, turn_event_factory),
        event_id_sequence=cast(TurnEventIdSequence, event_id_sequence),
        utc_occurred_at=cast(Callable[[], OccurredAt], utc_occurred_at),
        recovery_event_id_source=cast(RecoveryEventIdSource, recovery_event_id_source),
        recovery_metadata_factory=cast(RecoveryMetadataFactory, recovery_metadata_factory),
        event_boundary_lock=event_boundary_lock or threading.Lock(),
    )


def test_active_turn_registry_try_acquire_returns_owned_or_existing_with_immutable_intent_and_token() -> (
    None
):
    registry = ActiveTurnRegistry()
    first = registry.try_acquire(intent=_intent())
    second = registry.try_acquire(intent=_intent())

    assert first.type == "owned"
    assert second.type == "existing_active"
    assert first.intent == second.intent
    assert first.token != b""
    assert type(first.token) is bytes
    assert type(second.token) is bytes
    registry.release(token=first.token)


def test_existing_active_returns_processing_without_boundary_lock_or_claim() -> None:
    registry = ActiveTurnRegistry()
    acquisition = registry.try_acquire(intent=_intent())
    assert acquisition.type == "owned"
    coordinator = _coordinator(
        cast(EventStore, object()),
        cast(TurnRequestStore, object()),
        cast(ObservationStore, object()),
        registry=registry,
    )

    result = coordinator.execute(intent=_intent(), prepare=lambda *_: _prepared())

    assert result.type == "processing"
    assert result.status == "processing"
    assert result.http_status_code == 202
    payload_retry = coordinator.execute(
        intent=_intent(initial_recovery_payload=b"different-payload"),
        prepare=lambda *_: _prepared(),
    )
    assert payload_retry.type == "processing"
    registry.release(token=acquisition.token)


def test_owned_active_acquires_boundary_then_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    order: list[str] = []

    class BoundaryProbe:
        def __enter__(self) -> Self:
            order.append("boundary_enter")
            return self

        def __exit__(self, *args: object) -> Literal[False]:
            del args
            order.append("boundary_exit")
            return False

    original_claim = request_store.claim

    def claim(*, intent: TurnRequestIntent) -> object:
        order.append("claim")
        return original_claim(intent=intent)

    monkeypatch.setattr(request_store, "claim", claim)
    result = _coordinator(
        event_store,
        request_store,
        observation_store,
        event_boundary_lock=cast(threading.Lock, BoundaryProbe()),
    ).execute(intent=_intent(), prepare=lambda *_: _prepared())

    assert result.type == "completed"
    assert order[:2] == ["boundary_enter", "claim"]
    assert order[-1] == "boundary_exit"


def test_same_key_active_identity_conflict_is_request_key_conflict() -> None:
    registry = ActiveTurnRegistry()
    acquisition = registry.try_acquire(intent=_intent())
    assert acquisition.type == "owned"
    coordinator = _coordinator(
        cast(EventStore, object()),
        cast(TurnRequestStore, object()),
        cast(ObservationStore, object()),
        registry=registry,
    )

    with pytest.raises(StoreError) as raised:
        coordinator.execute(
            intent=_intent(input_digest="b" * 64),
            prepare=lambda *_: _prepared(),
        )

    assert raised.value.code == "request_key_conflict"
    registry.release(token=acquisition.token)


def test_different_key_active_conflict_is_turn_already_processing() -> None:
    registry = ActiveTurnRegistry()
    acquisition = registry.try_acquire(intent=_intent())
    assert acquisition.type == "owned"
    coordinator = _coordinator(
        cast(EventStore, object()),
        cast(TurnRequestStore, object()),
        cast(ObservationStore, object()),
        registry=registry,
    )

    with pytest.raises(StoreError) as raised:
        coordinator.execute(
            intent=_intent(request_key=b"different-key"),
            prepare=lambda *_: _prepared(),
        )

    assert raised.value.code == "turn_already_processing"
    registry.release(token=acquisition.token)


def test_turn_preparation_receives_full_campaign_events_before_projection_and_materialization(
    tmp_path: Path,
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    event_store.append(
        _batch(_draft("event:campaign", "CampaignCreated", payload={"name": "NeontoF"}))
    )
    campaign_events_before = tuple(event_store.read_campaign("campaign:lifecycle"))
    order: list[str] = []
    observed: list[tuple[DomainEvent, ...]] = []

    def prepare(
        identity: TurnRequestIdentity, campaign_events: tuple[DomainEvent, ...]
    ) -> PreparedTurn:
        order.append("prepare")
        assert identity.campaign_id == "campaign:lifecycle"
        observed.append(campaign_events)
        assert rebuild_projection(campaign_events).campaign_id == "campaign:lifecycle"
        return _prepared()

    def ids(identity: TurnRequestIdentity, prepared: PreparedTurn) -> Sequence[str]:
        del identity, prepared
        order.append("event_id_sequence")
        return ("event:accepted", "event:resumed", "event:committed")

    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        event_id_sequence=ids,
    )
    result = coordinator.execute(intent=_intent(), prepare=prepare)

    assert result.type == "completed"
    assert observed == [campaign_events_before]
    assert order == ["prepare", "event_id_sequence"]


def test_prior_completed_turn_in_prefix_does_not_identify_current_submit_before_first_append(
    tmp_path: Path,
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(
        event_store,
        turn_id="turn:prior",
        turn_request_id="turn-request:prior",
        event_prefix="prior",
    )
    intent = _intent(
        turn_request_id="turn-request:current",
        root_turn_request_id="turn-request:current",
        turn_id="turn:current",
        request_key=b"current-submit",
    )

    result = _coordinator(event_store, request_store, observation_store).execute(
        intent=intent,
        prepare=lambda *_: _prepared(),
    )

    assert result.type == "completed"
    assert [event.type for event in event_store.read_campaign("campaign:lifecycle")[-3:]] == [
        "PlayerInputAccepted",
        "TurnResumed",
        "TurnCommitted",
    ]
    assert event_store.read_campaign("campaign:lifecycle")[-3].turn_id == "turn:current"


def test_submit_emits_player_input_accepted_then_turn_resumed_then_terminal(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)

    result = _coordinator(event_store, request_store, observation_store).execute(
        intent=_intent(),
        prepare=lambda *_: _prepared(),
    )

    assert result.type == "completed"
    assert [event.type for event in event_store.read_campaign("campaign:lifecycle")] == [
        "PlayerInputAccepted",
        "TurnResumed",
        "TurnCommitted",
    ]


def test_resume_does_not_append_second_player_input(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(event_store, include_awaiting=True)
    intent = _intent(
        request_key=b"resume-key",
        request_kind="resume",
        input_digest="b" * 64,
    )
    coordinator = _coordinator(event_store, request_store, observation_store)

    result = coordinator.execute(intent=intent, prepare=lambda *_: _prepared())
    events = event_store.read_campaign("campaign:lifecycle")

    assert result.type == "completed"
    assert [event.type for event in events[-2:]] == ["TurnResumed", "TurnCommitted"]
    assert not any(event.type == "PlayerInputAccepted" and event.sequence > 6 for event in events)

    _, invalid_event_store, invalid_request_store, invalid_observation_store = _database(
        tmp_path / "invalid-resume"
    )
    invalid_before = invalid_event_store.read_campaign("campaign:lifecycle")
    invalid_intent = _intent(
        request_key=b"invalid-resume",
        request_kind="resume",
        input_digest="b" * 64,
    )
    with pytest.raises(StoreError) as raised:
        _coordinator(
            invalid_event_store,
            invalid_request_store,
            invalid_observation_store,
        ).execute(
            intent=invalid_intent,
            prepare=lambda *_: _prepared(
                terminal_status="awaiting_player", staged_recovery_payload=None
            ),
        )

    assert raised.value.code == "recovery_identity_mismatch"
    assert invalid_event_store.read_campaign("campaign:lifecycle") == invalid_before

    identity = TurnRequestIdentity.model_validate(
        {
            **invalid_intent.model_dump(),
            "base_event_sequence": 0,
            "recovery_payload_version": 1,
            "recovery_reason": None,
            "recovery_selector": None,
            "accepted_event_id": None,
            "resumed_event_id": None,
            "awaiting_player_event_id": None,
            "committed_event_id": None,
            "aborted_event_id": None,
            "recovery_aborted_event_id": None,
            "occurred_at": None,
            "staged_recovery_payload": None,
        },
        strict=True,
    )
    with pytest.raises(StoreError) as factory_raised:
        build_turn_event_batch(
            identity,
            _prepared(terminal_status="awaiting_player", staged_recovery_payload=None),
            (),
            OCCURRED_AT,
            ("event:resume", "event:awaiting"),
        )

    assert factory_raised.value.code == "recovery_identity_mismatch"


def test_ambiguous_input_enters_awaiting_player_without_effect_events(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    coordinator = _coordinator(event_store, request_store, observation_store)

    result = coordinator.execute(
        intent=_intent(),
        prepare=lambda *_: _prepared(
            terminal_status="awaiting_player",
            staged_recovery_payload=None,
        ),
    )
    events = event_store.read_campaign("campaign:lifecycle")

    assert result.type == "completed"
    assert result.status == "awaiting_player"
    assert [event.type for event in events] == [
        "PlayerInputAccepted",
        "TurnResumed",
        "TurnAwaitingPlayer",
    ]
    assert not any(event.type in {"ResourceChanged", "FactAsserted"} for event in events)


def test_non_committed_effects_are_rejected_before_append(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    effect = PreparedEffect(
        type="ResourceChanged",
        event_version=1,
        campaign_id="campaign:lifecycle",
        session_id="session:lifecycle",
        scene_id="scene:lifecycle",
        turn_id="turn:lifecycle",
        origin="in_world",
        visibility="player_visible",
        payload_json=b'{"resource_id":"resource:torch","entity_id":"entity:hero","delta":1}',
    )

    def invalid_factory(
        identity: TurnRequestIdentity,
        prepared: PreparedTurn,
        campaign_events: tuple[DomainEvent, ...],
        occurred_at: str,
        event_ids: Sequence[str],
    ) -> tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch]:
        del prepared, campaign_events
        metadata = TurnEventMetadata(
            campaign_id=identity.campaign_id,
            session_id=identity.session_id,
            scene_id=identity.scene_id,
            turn_id=identity.turn_id,
            turn_request_id=identity.turn_request_id,
            root_turn_request_id=identity.root_turn_request_id,
            occurred_at=occurred_at,
            event_ids=tuple(event_ids),
        )
        reservation = reserve_recovery_event_ids(identity)
        recovery = RecoveryEventMetadata(
            request_kind=identity.request_kind,
            recovery_payload_version=identity.recovery_payload_version,
            campaign_id=identity.campaign_id,
            session_id=identity.session_id,
            scene_id=identity.scene_id,
            turn_id=identity.turn_id,
            turn_request_id=identity.turn_request_id,
            root_turn_request_id=identity.root_turn_request_id,
            input_digest=identity.input_digest,
            recovery_reason="claim_before_first_event",
            recovery_selector="no_lifecycle_events",
            occurred_at=occurred_at,
            accepted_event_id=reservation.accepted_event_id,
            resumed_event_id=reservation.resumed_event_id,
            awaiting_player_event_id=reservation.awaiting_player_event_id,
            committed_event_id=reservation.committed_event_id,
            aborted_event_id=reservation.aborted_event_id,
            recovery_aborted_event_id=reservation.recovery_aborted_event_id,
            event_ids=(
                reservation.accepted_event_id,
                reservation.resumed_event_id,
                reservation.awaiting_player_event_id,
                reservation.committed_event_id,
                reservation.aborted_event_id,
                reservation.recovery_aborted_event_id,
            ),
        )
        return (
            metadata,
            recovery,
            _batch(
                _draft(
                    event_ids[0],
                    "PlayerInputAccepted",
                    payload={
                        "turn_request_id": identity.turn_request_id,
                        "input_digest": identity.input_digest,
                    },
                ),
                _draft(
                    event_ids[1],
                    "TurnResumed",
                    payload={"turn_request_id": identity.turn_request_id},
                ),
                EventDraft(
                    body=EventDraftBody(
                        type="ResourceChanged",
                        event_id=event_ids[2],
                        event_version=1,
                        campaign_id=identity.campaign_id,
                        session_id=identity.session_id,
                        scene_id=identity.scene_id,
                        turn_id=identity.turn_id,
                        occurred_at=occurred_at,
                        origin="in_world",
                        visibility="player_visible",
                        payload_json=effect.payload_json,
                    )
                ),
            ),
        )

    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        turn_event_factory=invalid_factory,
        event_id_sequence=lambda *_: ("event:accepted", "event:resumed", "event:effect"),
    )
    with pytest.raises(StoreError):
        coordinator.execute(
            intent=_intent(),
            prepare=lambda *_: _prepared(effect_candidates=(effect,)),
        )

    assert event_store.read_campaign("campaign:lifecycle") == ()


def test_turn_event_factory_appends_session_ended_after_committed_when_scenario_end_is_set(
    tmp_path: Path,
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    seen_ids: list[Sequence[str]] = []

    def ids(identity: TurnRequestIdentity, prepared: PreparedTurn) -> Sequence[str]:
        result = _event_ids(identity, prepared)
        seen_ids.append(result)
        return result

    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        event_id_sequence=ids,
    )
    result = coordinator.execute(
        intent=_intent(),
        prepare=lambda *_: _prepared(scenario_end="success"),
    )
    events = event_store.read_campaign("campaign:lifecycle")

    assert result.type == "completed"
    assert len(seen_ids) == 1
    assert [event.type for event in events[-2:]] == ["TurnCommitted", "SessionEnded"]
    assert events[-1].scene_id is None
    assert events[-1].turn_id is None
    assert isinstance(events[-1], SessionEndedEvent)
    assert events[-1].payload.reason == "completed"


def test_recover_processing_returns_recovery_plan_without_append_rebuild_or_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    claim = request_store.claim(intent=_intent())
    assert claim.type == "new"
    record = claim.record
    calls = {"append": 0, "rebuild": 0, "complete": 0, "response": 0}

    def append(batch: EventBatch) -> tuple[object, ...]:
        del batch
        calls["append"] += 1
        raise AssertionError("recover_processing must not append")

    def rebuild(*_: object) -> object:
        calls["rebuild"] += 1
        raise AssertionError("recover_processing must not rebuild")

    def complete(*_: object, **__: object) -> object:
        calls["complete"] += 1
        raise AssertionError("recover_processing must not complete")

    def response(*_: object) -> CachedTurnResponse:
        calls["response"] += 1
        raise AssertionError("recover_processing must not rebuild a response")

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    monkeypatch.setattr(turn_lifecycle, "rebuild_projection", rebuild)
    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        response_rebuilder=response,
    )

    plan = coordinator.recover_processing(record=record, campaign_events=())

    assert plan.state == "recovery_abort"
    assert plan.candidate_batch is not None
    assert calls == {"append": 0, "rebuild": 0, "complete": 0, "response": 0}


def test_turn_event_batch_factory_is_only_post_id_event_batch_constructor() -> None:
    source_path = Path(__file__).resolve().parents[2] / "src/neontof/application/turn_lifecycle.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    event_batch_constructor_functions = {
        function.name
        for function in tree.body
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "EventBatch"
            for call in ast.walk(function)
        )
    }

    assert event_batch_constructor_functions == {
        "build_turn_event_batch",
        "build_revert_event",
        "build_crash_recovery_batch",
    }
    assert not any(
        isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and function.name == "_helper_event_id"
        for function in tree.body
    )


def test_prepared_turn_rejects_terminal_without_v2_staged_recovery_payload() -> None:
    with pytest.raises(ValidationError):
        PreparedTurn(
            effect_candidates=(),
            terminal_status="committed",
            scenario_end=None,
            abort_reason=None,
            staged_recovery_payload=None,
        )

    awaiting = PreparedTurn(
        effect_candidates=(),
        terminal_status="awaiting_player",
        scenario_end=None,
        abort_reason=None,
        staged_recovery_payload=None,
    )
    assert awaiting.terminal_status == "awaiting_player"


def test_select_response_payload_returns_opaque_outer_bytes_without_decoding() -> None:
    intent = _intent(request_key=b"opaque")
    identity = TurnRequestIdentity(
        **intent.model_dump(),
        base_event_sequence=0,
        recovery_payload_version=2,
        recovery_reason="after_terminal",
        recovery_selector="terminal",
        accepted_event_id="event:accepted",
        resumed_event_id="event:resumed",
        awaiting_player_event_id=None,
        committed_event_id="event:committed",
        aborted_event_id=None,
        recovery_aborted_event_id="event:recovery-aborted",
        occurred_at=OCCURRED_AT,
        staged_recovery_payload=b"\xffopaque-outer-bytes",
    )
    record = ProcessingTurnRequestRecord(
        **identity.model_dump(),
        status="processing",
        response=None,
    )
    events = (
        _materialize(
            _body(
                "event:accepted",
                "PlayerInputAccepted",
                payload={
                    "turn_request_id": identity.turn_request_id,
                    "input_digest": identity.input_digest,
                },
            ),
            1,
        ),
        _materialize(
            _body(
                "event:resumed",
                "TurnResumed",
                payload={"turn_request_id": identity.turn_request_id},
            ),
            2,
        ),
        _materialize(
            _body(
                "event:committed",
                "TurnCommitted",
                payload={"turn_request_id": identity.turn_request_id},
            ),
            3,
        ),
    )

    assert (
        select_response_payload(record=record, campaign_events=events) == b"\xffopaque-outer-bytes"
    )


def _materialize(body: EventDraftBody, sequence: int) -> DomainEvent:
    from neontof.persistence.event_store import _materialize_event_json

    return _materialize_event_json(body=body, sequence=sequence)[1]


def test_coordinator_releases_registry_and_boundary_lock_on_prepare_failure(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    registry = ActiveTurnRegistry()
    boundary = threading.Lock()
    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        registry=registry,
        event_boundary_lock=boundary,
    )

    def fail_prepare(*_: object) -> PreparedTurn:
        raise RuntimeError("prepare failed")

    with pytest.raises(RuntimeError, match="prepare failed"):
        coordinator.execute(intent=_intent(), prepare=fail_prepare)

    reacquired = registry.try_acquire(intent=_intent())
    assert reacquired.type == "owned"
    registry.release(token=reacquired.token)
    assert boundary.acquire(blocking=False)
    boundary.release()


def test_coordinator_releases_registry_and_boundary_lock_on_rebuild_or_complete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for failure in ("rebuild", "complete", "candidate_validation", "append"):
        _, event_store, request_store, observation_store = _database(tmp_path / failure)
        registry = ActiveTurnRegistry()
        boundary = threading.Lock()
        rebuild_calls = 0
        append_calls = 0
        append_failure_pending = failure == "append"
        original_append = event_store.append
        original_complete = request_store.complete

        def rebuild(
            record: ProcessingTurnRequestRecord,
            campaign_events: tuple[DomainEvent, ...],
            status: str,
            payload: bytes,
            *,
            failure_name: str = failure,
        ) -> CachedTurnResponse:
            nonlocal rebuild_calls
            rebuild_calls += 1
            if failure_name == "rebuild":
                raise RuntimeError("rebuild failed")
            return _response_rebuilder(record, campaign_events, status, payload)

        def complete(
            *,
            request_key: bytes,
            expected_version: Literal[1, 2],
            status: RequestCompletionStatus,
            response: CachedTurnResponse,
            failure_name: str = failure,
            complete_method: Callable[..., FinalTurnRequestRecord] = original_complete,
        ) -> FinalTurnRequestRecord:
            if failure_name == "complete":
                raise RuntimeError("complete failed")
            return complete_method(
                request_key=request_key,
                expected_version=expected_version,
                status=status,
                response=response,
            )

        def append(
            batch: EventBatch,
            *,
            append_method: Callable[..., object] = original_append,
        ) -> tuple[object, ...]:
            nonlocal append_calls, append_failure_pending
            append_calls += 1
            if append_failure_pending:
                append_failure_pending = False
                raise RuntimeError("append failed")
            return cast(tuple[object, ...], append_method(batch))

        turn_event_factory: object = build_turn_event_batch
        if failure == "candidate_validation":

            def invalid_factory(
                identity: TurnRequestIdentity,
                prepared: PreparedTurn,
                campaign_events: tuple[DomainEvent, ...],
                occurred_at: str,
                event_ids: Sequence[str],
            ) -> tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch]:
                metadata, recovery, valid_batch = build_turn_event_batch(
                    identity,
                    prepared,
                    campaign_events,
                    occurred_at,
                    event_ids,
                )
                return (
                    metadata,
                    recovery,
                    EventBatch(
                        campaign_id=valid_batch.campaign_id,
                        drafts=valid_batch.drafts[:-1],
                    ),
                )

            turn_event_factory = invalid_factory

        monkeypatch.setattr(event_store, "append", append)
        monkeypatch.setattr(request_store, "complete", complete)
        intent = _intent(request_key=f"{failure}-key".encode())
        coordinator = _coordinator(
            event_store,
            request_store,
            observation_store,
            registry=registry,
            event_boundary_lock=boundary,
            response_rebuilder=rebuild,
            turn_event_factory=turn_event_factory,
        )
        if failure == "candidate_validation":
            with pytest.raises(StoreError) as raised:
                coordinator.execute(intent=intent, prepare=lambda *_: _prepared())
            assert raised.value.code == "recovery_identity_mismatch"
        else:
            with pytest.raises(RuntimeError, match=f"{failure} failed"):
                coordinator.execute(intent=intent, prepare=lambda *_: _prepared())

        assert rebuild_calls == (0 if failure in {"candidate_validation", "append"} else 1)
        assert append_calls == (0 if failure == "candidate_validation" else 1)
        assert boundary.acquire(blocking=False)
        boundary.release()
        reacquired = registry.try_acquire(intent=intent)
        assert reacquired.type == "owned"
        assert reacquired.intent == intent
        registry.release(token=reacquired.token)


def test_latest_committed_turn_can_be_reverted(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(event_store)
    command = UndoCommand(
        campaign_id="campaign:lifecycle",
        session_id="session:lifecycle",
        request_key=b"undo-key",
        occurred_at=OCCURRED_AT,
    )
    coordinator = _coordinator(event_store, request_store, observation_store)

    result = coordinator.revert_latest(command=command)
    events = event_store.read_campaign("campaign:lifecycle")

    assert isinstance(result, RevertedTurnResult)
    assert result.target_turn_id == "turn:lifecycle"
    assert events[-1].type == "TurnReverted"
    assert events[-1].payload.target_turn_id == "turn:lifecycle"


def test_undo_processing_guard_returns_fixed_409_blocked_result(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    request_store.claim(intent=_intent())
    coordinator = _coordinator(event_store, request_store, observation_store)

    result = coordinator.revert_latest(
        command=UndoCommand(
            campaign_id="campaign:lifecycle",
            session_id="session:lifecycle",
            request_key=b"undo-key",
            occurred_at=OCCURRED_AT,
        )
    )

    assert isinstance(result, UndoBlockedResult)
    assert result.type == "blocked"
    assert result.http_status_code == 409
    assert result.code == "turn_already_processing"
    assert result.response is None


def test_non_latest_turn_cannot_be_reverted(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(
        event_store,
        turn_id="turn:first",
        turn_request_id="turn-request:first",
        event_prefix="first",
    )
    event_store.append(
        _batch(
            _draft(
                "event:second-accepted",
                "PlayerInputAccepted",
                turn_id="turn:second",
                payload={"turn_request_id": "turn-request:second", "input_digest": "a" * 64},
            ),
            _draft(
                "event:second-resumed",
                "TurnResumed",
                turn_id="turn:second",
                payload={"turn_request_id": "turn-request:second"},
            ),
            _draft(
                "event:second-committed",
                "TurnCommitted",
                turn_id="turn:second",
                payload={"turn_request_id": "turn-request:second"},
            ),
        )
    )

    result = _coordinator(event_store, request_store, observation_store).revert_latest(
        command=UndoCommand(
            campaign_id="campaign:lifecycle",
            session_id="session:lifecycle",
            request_key=b"undo-second",
            occurred_at=OCCURRED_AT,
        )
    )

    assert isinstance(result, RevertedTurnResult)
    assert result.target_turn_id == "turn:second"
    assert [
        event.payload.target_turn_id
        for event in event_store.read_campaign("campaign:lifecycle")
        if event.type == "TurnReverted"
    ] == ["turn:second"]


def test_global_latest_committed_turn_is_selected_before_session_check(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    event_store.append(
        _batch(
            _draft("event:campaign", "CampaignCreated", payload={"name": "NeontoF"}),
            _draft(
                "event:session-main",
                "SessionStarted",
                payload={"scenario_id": None, "title": "Main"},
            ),
            _draft("event:scene-main", "SceneStarted", payload={"label": "Main"}),
            _draft(
                "event:accepted-main",
                "PlayerInputAccepted",
                payload={"turn_request_id": "turn-request:main", "input_digest": "a" * 64},
            ),
            _draft(
                "event:resumed-main",
                "TurnResumed",
                payload={"turn_request_id": "turn-request:main"},
            ),
            _draft(
                "event:committed-main",
                "TurnCommitted",
                payload={"turn_request_id": "turn-request:main"},
            ),
            _draft(
                "event:session-other",
                "SessionStarted",
                session_id="session:other",
                payload={"scenario_id": None, "title": "Other"},
            ),
            _draft(
                "event:scene-other",
                "SceneStarted",
                session_id="session:other",
                scene_id="scene:other",
                payload={"label": "Other"},
            ),
            _draft(
                "event:accepted-other",
                "PlayerInputAccepted",
                session_id="session:other",
                scene_id="scene:other",
                turn_id="turn:other",
                payload={"turn_request_id": "turn-request:other", "input_digest": "a" * 64},
            ),
            _draft(
                "event:resumed-other",
                "TurnResumed",
                session_id="session:other",
                scene_id="scene:other",
                turn_id="turn:other",
                payload={"turn_request_id": "turn-request:other"},
            ),
            _draft(
                "event:committed-other",
                "TurnCommitted",
                session_id="session:other",
                scene_id="scene:other",
                turn_id="turn:other",
                payload={"turn_request_id": "turn-request:other"},
            ),
        )
    )
    coordinator = _coordinator(event_store, request_store, observation_store)

    with pytest.raises(StoreError) as raised:
        coordinator.revert_latest(
            command=UndoCommand(
                campaign_id="campaign:lifecycle",
                session_id="session:lifecycle",
                request_key=b"undo-key",
                occurred_at=OCCURRED_AT,
            )
        )

    assert raised.value.code == "turn_not_in_session"
    assert len(event_store.read_campaign("campaign:lifecycle")) == 11


def test_existing_revert_requires_full_context_match(tmp_path: Path) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(event_store)
    revert_id = derive_revert_event_id(
        campaign_id="campaign:lifecycle",
        request_key=b"undo-key",
    )
    event_store.append(
        _batch(
            _draft(
                revert_id,
                "TurnReverted",
                session_id="session:wrong",
                scene_id=None,
                turn_id=None,
                payload={"target_turn_id": "turn:lifecycle"},
                origin="table_correction",
            )
        )
    )
    coordinator = _coordinator(event_store, request_store, observation_store)

    with pytest.raises(StoreError) as raised:
        coordinator.revert_latest(
            command=UndoCommand(
                campaign_id="campaign:lifecycle",
                session_id="session:lifecycle",
                request_key=b"undo-key",
                occurred_at=OCCURRED_AT,
            )
        )

    assert raised.value.code == "undo_conflict"

    _, target_event_store, target_request_store, target_observation_store = _database(
        tmp_path / "target-context"
    )
    _seed_turn(
        target_event_store,
        session_id="session:target",
        scene_id="scene:target",
        event_prefix="target",
    )
    target_event_store.append(
        _batch(
            _draft(
                revert_id,
                "TurnReverted",
                session_id="session:lifecycle",
                scene_id=None,
                turn_id=None,
                payload={"target_turn_id": "turn:lifecycle"},
                origin="table_correction",
            )
        )
    )

    with pytest.raises(StoreError) as target_raised:
        _coordinator(
            target_event_store,
            target_request_store,
            target_observation_store,
        ).revert_latest(
            command=UndoCommand(
                campaign_id="campaign:lifecycle",
                session_id="session:lifecycle",
                request_key=b"undo-key",
                occurred_at=OCCURRED_AT,
            )
        )

    assert target_raised.value.code == "undo_conflict"


def test_undo_retry_after_rebuild_later_turn_and_clock_has_zero_append_and_one_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    _seed_turn(event_store)
    append_calls = 0
    undo_rebuild_calls = 0
    original_append = event_store.append

    def append(batch: EventBatch) -> tuple[object, ...]:
        nonlocal append_calls
        append_calls += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        command: UndoCommand,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        target_turn_id: str,
        revert_event_id: str,
    ) -> CachedTurnResponse:
        nonlocal undo_rebuild_calls
        undo_rebuild_calls += 1
        if undo_rebuild_calls == 1:
            raise RuntimeError("undo response rebuild failed")
        return _undo_response_rebuilder(
            command,
            campaign_events,
            status,
            target_turn_id,
            revert_event_id,
        )

    monkeypatch.setattr(event_store, "append", append)
    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        undo_response_rebuilder=rebuild,
    )
    command = UndoCommand(
        campaign_id="campaign:lifecycle",
        session_id="session:lifecycle",
        request_key=b"undo-key",
        occurred_at=OCCURRED_AT,
    )
    with pytest.raises(RuntimeError, match="undo response rebuild failed"):
        coordinator.revert_latest(command=command)

    first_revert = [
        event
        for event in event_store.read_campaign("campaign:lifecycle")
        if event.type == "TurnReverted"
    ]
    assert len(first_revert) == 1
    revert_event_id = first_revert[0].event_id
    target_turn_id = first_revert[0].payload.target_turn_id

    event_store.append(
        _batch(
            _draft(
                "event:later-accepted",
                "PlayerInputAccepted",
                turn_id="turn:later",
                occurred_at="2026-09-01T00:00:00Z",
                payload={
                    "turn_request_id": "turn-request:later",
                    "input_digest": "b" * 64,
                },
            ),
            _draft(
                "event:later-resumed",
                "TurnResumed",
                turn_id="turn:later",
                occurred_at="2026-09-01T00:00:00Z",
                payload={"turn_request_id": "turn-request:later"},
            ),
            _draft(
                "event:later-clock",
                "ClockAdvanced",
                turn_id="turn:later",
                occurred_at="2026-09-01T00:00:00Z",
                payload=ClockAdvancedPayload(
                    clock_id="clock:session",
                    delta=1,
                ).model_dump(),
            ),
            _draft(
                "event:later-committed",
                "TurnCommitted",
                turn_id="turn:later",
                occurred_at="2026-09-01T00:00:00Z",
                payload={"turn_request_id": "turn-request:later"},
            ),
        )
    )
    events_after_later_turn = event_store.read_campaign("campaign:lifecycle")
    clock_events = tuple(
        event for event in events_after_later_turn if isinstance(event, ClockAdvancedEvent)
    )
    assert len(clock_events) == 1
    clock_event = clock_events[0]
    assert isinstance(clock_event.payload, ClockAdvancedPayload)
    assert clock_event.payload.clock_id == "clock:session"
    assert clock_event.payload.delta >= 1
    assert (
        clock_event.campaign_id,
        clock_event.session_id,
        clock_event.scene_id,
        clock_event.turn_id,
    ) == (
        "campaign:lifecycle",
        "session:lifecycle",
        "scene:lifecycle",
        "turn:later",
    )
    rebuild_projection(events_after_later_turn)
    before_retry_append_calls = append_calls
    before_retry_rebuild_calls = undo_rebuild_calls

    result = coordinator.revert_latest(
        command=UndoCommand(
            campaign_id="campaign:lifecycle",
            session_id="session:lifecycle",
            request_key=b"undo-key",
            occurred_at="2026-09-02T00:00:00Z",
        )
    )

    assert isinstance(result, RevertedTurnResult)
    assert result.revert_event_id == revert_event_id
    assert result.target_turn_id == target_turn_id
    assert append_calls - before_retry_append_calls == 0
    assert undo_rebuild_calls - before_retry_rebuild_calls == 1
    assert [
        event.event_id
        for event in event_store.read_campaign("campaign:lifecycle")
        if event.type == "TurnReverted"
    ] == [revert_event_id]


def test_recovery_metadata_reserves_recovery_abort_id_without_event_membership(
    tmp_path: Path,
) -> None:
    _, event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"normal-terminal-key")

    result = _coordinator(event_store, request_store, observation_store).execute(
        intent=intent,
        prepare=lambda *_: _prepared(),
    )

    assert result.type == "completed"
    assert result.status == "committed"
    record = request_store.read(request_key=intent.request_key)
    assert isinstance(record, FinalTurnRequestRecord)
    assert record.recovery_aborted_event_id is not None

    owned_suffix = tuple(
        event
        for event in event_store.read_campaign("campaign:lifecycle")
        if event.sequence > record.base_event_sequence
    )
    normal_terminal = tuple(
        event for event in owned_suffix if event.event_id == record.committed_event_id
    )
    assert len(normal_terminal) == 1
    assert normal_terminal[0].type == "TurnCommitted"
    assert not any(event.event_id == record.recovery_aborted_event_id for event in owned_suffix)


def test_revert_event_id_known_answer_vectors() -> None:
    assert derive_revert_event_id(campaign_id="campaign:alpha", request_key=b"idem-v1-alpha") == (
        "event:2d0292a9b4ed5d419b02934e39d9a3665b7218609d3a8372036fcb2021d9f424"
    )
    assert derive_revert_event_id(campaign_id="campaign:beta", request_key=b"idem-v1-alpha") == (
        "event:6c20c0f38ed22254404d1a18a8e07544ad7e33769b57a0eee3509875f15a002e"
    )
    assert derive_revert_event_id(campaign_id="campaign:alpha", request_key="再送-α".encode()) == (
        "event:7eb0347547f6c03c11173ef6b5ddac520b9ac46cfe6f7274215946c5adbe31c8"
    )
