"""P1-03 durable claim and append/rebuild/complete idempotency tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

import pytest

from neontof.application.turn_lifecycle import (
    ActiveTurnRegistry,
    TurnLifecycleCoordinator,
    build_recovery_metadata,
    build_turn_event_batch,
    reserve_recovery_event_ids,
)
from neontof.application.turn_models import (
    CachedTurnResponse,
    FinalTurnRequestRecord,
    PreparedTurn,
    ProcessingTurnRequestRecord,
    RecoveryEventIdSource,
    RecoveryEventMetadata,
    RecoveryMetadataFactory,
    RequestCompletionStatus,
    ResponseRebuilder,
    StoreError,
    TurnEventBatchFactory,
    TurnEventIdSequence,
    TurnRequestIdentity,
    TurnRequestIntent,
    UndoResponseRebuilder,
)
from neontof.contracts.domain import DomainEvent, TurnAbortedEvent
from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody
from neontof.persistence.event_store import EventStore
from neontof.persistence.observation_store import ObservationStore
from neontof.persistence.sqlite_database import SqliteDatabase
from neontof.persistence.turn_request_store import TurnRequestStore

OCCURRED_AT = "2026-08-31T00:00:00Z"


def _intent(**overrides: object) -> TurnRequestIntent:
    values: dict[str, object] = {
        "request_key": b"idempotency-key",
        "request_kind": "submit",
        "requested_media_type": "application/json",
        "turn_request_id": "turn-request:idempotency",
        "campaign_id": "campaign:idempotency",
        "session_id": "session:idempotency",
        "scene_id": "scene:idempotency",
        "turn_id": "turn:idempotency",
        "root_turn_request_id": "turn-request:idempotency",
        "input_digest": "a" * 64,
        "initial_recovery_payload": b"initial-recovery-payload",
    }
    values.update(overrides)
    return TurnRequestIntent.model_validate(values, strict=True)


def _database(tmp_path: Path) -> tuple[EventStore, TurnRequestStore, ObservationStore]:
    database = SqliteDatabase(tmp_path / "runtime" / "idempotency.sqlite3")
    database.migrate()
    event_store = EventStore(database)
    return event_store, TurnRequestStore(database, event_store), ObservationStore(database)


def _body(
    event_id: str,
    event_type: str,
    *,
    campaign_id: str = "campaign:idempotency",
    session_id: str | None = "session:idempotency",
    scene_id: str | None = "scene:idempotency",
    turn_id: str | None = "turn:idempotency",
    payload: Mapping[str, object],
    occurred_at: str = OCCURRED_AT,
    origin: Literal["in_world", "table_correction"] = "in_world",
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
        visibility="player_visible",
        payload_json=json.dumps(payload, separators=(",", ":")).encode(),
    )


def _draft(
    event_id: str,
    event_type: str,
    *,
    campaign_id: str = "campaign:idempotency",
    session_id: str | None = "session:idempotency",
    scene_id: str | None = "scene:idempotency",
    turn_id: str | None = "turn:idempotency",
    payload: Mapping[str, object],
    occurred_at: str = OCCURRED_AT,
    origin: Literal["in_world", "table_correction"] = "in_world",
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
            occurred_at=occurred_at,
            origin=origin,
        )
    )


def _batch(*drafts: EventDraft, campaign_id: str = "campaign:idempotency") -> EventBatch:
    return EventBatch(campaign_id=campaign_id, drafts=tuple(drafts))


def _awaiting_prefix(event_store: EventStore) -> None:
    event_store.append(
        _batch(
            _draft("event:campaign", "CampaignCreated", payload={"name": "NeontoF"}),
            _draft(
                "event:session",
                "SessionStarted",
                payload={"scenario_id": None, "title": "Opening"},
            ),
            _draft("event:scene", "SceneStarted", payload={"label": "Hall"}),
            _draft(
                "event:accepted",
                "PlayerInputAccepted",
                payload={"turn_request_id": "turn-request:idempotency", "input_digest": "a" * 64},
            ),
            _draft(
                "event:resumed",
                "TurnResumed",
                payload={"turn_request_id": "turn-request:idempotency"},
            ),
            _draft(
                "event:awaiting",
                "TurnAwaitingPlayer",
                payload={"turn_request_id": "turn-request:idempotency"},
            ),
        )
    )


def _prepared(status: str = "committed", staged: bytes | None = b"staged-payload") -> PreparedTurn:
    return PreparedTurn(
        effect_candidates=(),
        terminal_status=cast(Literal["awaiting_player", "committed", "aborted"], status),
        scenario_end=None,
        abort_reason="failed" if status == "aborted" else None,
        staged_recovery_payload=staged,
    )


def _ids(identity: TurnRequestIdentity, prepared: PreparedTurn) -> Sequence[str]:
    reservation = reserve_recovery_event_ids(identity)
    ids: list[str] = []
    if identity.request_kind == "submit":
        ids.append(reservation.accepted_event_id)
    ids.append(reservation.resumed_event_id)
    ids.extend(f"event:effect-{index}" for index in range(len(prepared.effect_candidates)))
    if prepared.terminal_status == "committed":
        ids.append(reservation.committed_event_id)
    elif prepared.terminal_status == "aborted":
        ids.append(reservation.aborted_event_id)
    else:
        ids.append(reservation.awaiting_player_event_id)
    return tuple(ids)


def _rebuilder(
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
    status: str,
    payload: bytes,
) -> CachedTurnResponse:
    del campaign_events, status
    return CachedTurnResponse(status_code=200, media_type=record.requested_media_type, body=payload)


def _undo_rebuilder(
    command: object,
    campaign_events: tuple[DomainEvent, ...],
    status: str,
    target_turn_id: str,
    revert_event_id: str,
) -> CachedTurnResponse:
    del command, campaign_events, status, target_turn_id, revert_event_id
    return CachedTurnResponse(status_code=200, media_type="application/json", body=b'{"ok":true}')


def _coordinator(
    event_store: EventStore,
    request_store: TurnRequestStore,
    observation_store: ObservationStore,
    *,
    response_rebuilder: object = _rebuilder,
) -> TurnLifecycleCoordinator:
    return TurnLifecycleCoordinator(
        event_store=event_store,
        request_store=request_store,
        observation_store=observation_store,
        active_turn_registry=ActiveTurnRegistry(),
        response_rebuilder=cast(ResponseRebuilder, response_rebuilder),
        undo_response_rebuilder=cast(UndoResponseRebuilder, _undo_rebuilder),
        turn_event_factory=cast(TurnEventBatchFactory, build_turn_event_batch),
        event_id_sequence=cast(TurnEventIdSequence, _ids),
        utc_occurred_at=lambda: OCCURRED_AT,
        recovery_event_id_source=cast(RecoveryEventIdSource, reserve_recovery_event_ids),
        recovery_metadata_factory=cast(RecoveryMetadataFactory, build_recovery_metadata),
        event_boundary_lock=threading.Lock(),
    )


def test_submit_claim_before_first_event_recovers_with_accepted_then_aborted_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent()
    request_store.claim(intent=intent)
    counts = {"append": 0, "rebuild": 0, "complete": 0, "metadata": 0}
    original_append = event_store.append
    original_stage = request_store.stage_recovery_metadata
    original_complete = request_store.complete

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def stage(
        *, request_key: bytes, metadata: RecoveryEventMetadata
    ) -> ProcessingTurnRequestRecord:
        counts["metadata"] += 1
        return original_stage(request_key=request_key, metadata=metadata)

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        counts["complete"] += 1
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "stage_recovery_metadata", stage)
    monkeypatch.setattr(request_store, "complete", complete)
    result = _coordinator(
        event_store,
        request_store,
        observation_store,
        response_rebuilder=rebuild,
    ).execute(intent=intent, prepare=lambda *_: _prepared())

    assert result.type == "completed"
    assert counts == {"append": 1, "rebuild": 1, "complete": 1, "metadata": 1}
    assert [event.type for event in event_store.read_campaign("campaign:idempotency")] == [
        "PlayerInputAccepted",
        "TurnAborted",
    ]


def test_resume_claim_before_first_owned_event_appends_only_recovery_abort(tmp_path: Path) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    _awaiting_prefix(event_store)
    intent = _intent(
        request_key=b"resume-key",
        request_kind="resume",
        input_digest="b" * 64,
    )
    request_store.claim(intent=intent)
    before = len(event_store.read_campaign("campaign:idempotency"))
    coordinator = _coordinator(event_store, request_store, observation_store)

    coordinator.execute(intent=intent, prepare=lambda *_: _prepared())
    appended = event_store.read_campaign("campaign:idempotency")[before:]

    assert [event.type for event in appended] == ["TurnAborted"]
    assert isinstance(appended[0], TurnAbortedEvent)
    assert appended[0].payload.reason == "failed"


def test_metadata_stage_before_append_crash_sets_deterministic_metadata_then_recovers_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"metadata-stage-crash-key")
    original_append = event_store.append
    original_complete = request_store.complete
    original_stage = request_store.stage_recovery_metadata
    counts = {"append": 0, "rebuild": 0, "complete": 0, "metadata": 0, "prepare": 0}
    fail_after_stage = True
    staged_metadata: RecoveryEventMetadata | None = None

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        counts["complete"] += 1
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    def stage(
        *, request_key: bytes, metadata: RecoveryEventMetadata
    ) -> ProcessingTurnRequestRecord:
        nonlocal fail_after_stage, staged_metadata
        counts["metadata"] += 1
        staged_metadata = metadata
        record = original_stage(request_key=request_key, metadata=metadata)
        if fail_after_stage:
            fail_after_stage = False
            raise RuntimeError("metadata stage crash")
        return record

    def prepare(*_: object) -> PreparedTurn:
        counts["prepare"] += 1
        return _prepared()

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    monkeypatch.setattr(request_store, "stage_recovery_metadata", stage)
    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        response_rebuilder=rebuild,
    )

    with pytest.raises(RuntimeError, match="metadata stage crash"):
        coordinator.execute(intent=intent, prepare=prepare)

    assert counts == {"append": 0, "rebuild": 0, "complete": 0, "metadata": 1, "prepare": 1}
    assert event_store.read_campaign("campaign:idempotency") == ()
    record = request_store.read_processing(campaign_id=intent.campaign_id)
    assert record is not None
    assert staged_metadata is not None
    assert record.recovery_reason == "claim_before_first_event"
    assert record.recovery_selector == "no_lifecycle_events"
    assert record.occurred_at == OCCURRED_AT
    record_ids = (
        record.accepted_event_id,
        record.resumed_event_id,
        record.awaiting_player_event_id,
        record.committed_event_id,
        record.aborted_event_id,
        record.recovery_aborted_event_id,
    )
    metadata_ids = (
        staged_metadata.accepted_event_id,
        staged_metadata.resumed_event_id,
        staged_metadata.awaiting_player_event_id,
        staged_metadata.committed_event_id,
        staged_metadata.aborted_event_id,
        staged_metadata.recovery_aborted_event_id,
    )
    assert record_ids == metadata_ids
    assert all(event_id is not None for event_id in record_ids)
    assert len(set(record_ids)) == 6

    def must_not_prepare(*_: object) -> PreparedTurn:
        raise AssertionError("prepare must not rerun")

    result = coordinator.execute(intent=intent, prepare=must_not_prepare)

    assert result.type == "completed"
    assert result.status == "aborted"
    assert counts == {"append": 1, "rebuild": 1, "complete": 1, "metadata": 1, "prepare": 1}
    events = event_store.read_campaign("campaign:idempotency")
    assert [event.type for event in events] == ["PlayerInputAccepted", "TurnAborted"]
    assert isinstance(events[-1], TurnAbortedEvent)
    assert events[-1].event_id == record.recovery_aborted_event_id
    assert events[-1].payload.turn_request_id == intent.turn_request_id
    assert events[-1].payload.reason == "failed"


def test_normal_committed_append_crash_retries_with_zero_append_one_rebuild_one_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent()
    counts = {"append": 0, "rebuild": 0, "complete": 0}
    original_append = event_store.append
    original_complete = request_store.complete
    fail_complete = True

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        nonlocal fail_complete
        counts["complete"] += 1
        if fail_complete:
            fail_complete = False
            raise RuntimeError("complete crash")
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    coordinator = _coordinator(
        event_store, request_store, observation_store, response_rebuilder=rebuild
    )
    with pytest.raises(RuntimeError, match="complete crash"):
        coordinator.execute(intent=intent, prepare=lambda *_: _prepared())

    before_retry = dict(counts)
    result = coordinator.execute(intent=intent, prepare=lambda *_: _prepared())

    assert result.type == "completed"
    assert counts["append"] - before_retry["append"] == 0
    assert counts["rebuild"] - before_retry["rebuild"] == 1
    assert counts["complete"] - before_retry["complete"] == 1
    assert counts["append"] == 1


def test_awaiting_player_append_crash_retries_with_zero_append_one_rebuild_one_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"awaiting-key")
    original_append = event_store.append
    original_complete = request_store.complete
    counts = {"append": 0, "rebuild": 0, "complete": 0}
    fail_complete = True

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        nonlocal fail_complete
        counts["complete"] += 1
        if fail_complete:
            fail_complete = False
            raise RuntimeError("complete crash")
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    coordinator = _coordinator(
        event_store, request_store, observation_store, response_rebuilder=rebuild
    )
    with pytest.raises(RuntimeError, match="complete crash"):
        coordinator.execute(
            intent=intent,
            prepare=lambda *_: _prepared(status="awaiting_player", staged=None),
        )

    before_retry = dict(counts)
    result = coordinator.execute(
        intent=intent,
        prepare=lambda *_: (_ for _ in ()).throw(AssertionError("prepare must not rerun")),
    )

    assert result.type == "completed"
    assert counts["append"] - before_retry["append"] == 0
    assert counts["rebuild"] - before_retry["rebuild"] == 1
    assert counts["complete"] - before_retry["complete"] == 1
    assert counts["append"] == 1


def test_recovery_abort_double_crash_reuses_actual_id_without_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"recovery-crash-key")
    request_store.claim(intent=intent)
    original_append = event_store.append
    original_complete = request_store.complete
    counts = {"append": 0, "rebuild": 0, "complete": 0}
    fail_complete = True

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        nonlocal fail_complete
        counts["complete"] += 1
        if fail_complete:
            fail_complete = False
            raise RuntimeError("complete crash")
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    coordinator = _coordinator(
        event_store, request_store, observation_store, response_rebuilder=rebuild
    )
    with pytest.raises(RuntimeError, match="complete crash"):
        coordinator.execute(intent=intent, prepare=lambda *_: _prepared())

    first_recovery_abort = [
        event
        for event in event_store.read_campaign("campaign:idempotency")
        if isinstance(event, TurnAbortedEvent)
    ]
    assert len(first_recovery_abort) == 1
    first_recovery_abort_id = first_recovery_abort[0].event_id
    before_retry = dict(counts)
    result = coordinator.execute(
        intent=intent,
        prepare=lambda *_: (_ for _ in ()).throw(AssertionError("prepare must not rerun")),
    )

    assert result.type == "completed"
    assert counts["append"] - before_retry["append"] == 0
    assert counts["rebuild"] - before_retry["rebuild"] == 1
    assert counts["complete"] - before_retry["complete"] == 1
    assert counts["append"] == 1
    second_recovery_abort = [
        event
        for event in event_store.read_campaign("campaign:idempotency")
        if isinstance(event, TurnAbortedEvent)
    ]
    assert [event.event_id for event in second_recovery_abort] == [first_recovery_abort_id]


def test_normal_aborted_append_crash_retries_with_zero_append_one_rebuild_one_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"aborted-crash-key")
    original_append = event_store.append
    original_complete = request_store.complete
    counts = {"append": 0, "rebuild": 0, "complete": 0}
    fail_complete = True

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        counts["rebuild"] += 1
        return _rebuilder(record, campaign_events, status, payload)

    def complete(
        *,
        request_key: bytes,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        nonlocal fail_complete
        counts["complete"] += 1
        if fail_complete:
            fail_complete = False
            raise RuntimeError("complete crash")
        return original_complete(
            request_key=request_key,
            expected_version=expected_version,
            status=status,
            response=response,
        )

    monkeypatch.setattr(event_store, "append", append)
    monkeypatch.setattr(request_store, "complete", complete)
    coordinator = _coordinator(event_store, request_store, observation_store)
    with pytest.raises(RuntimeError, match="complete crash"):
        coordinator.execute(
            intent=intent,
            prepare=lambda *_: _prepared(status="aborted"),
        )

    before_retry = dict(counts)
    result = _coordinator(
        event_store,
        request_store,
        observation_store,
        response_rebuilder=rebuild,
    ).execute(
        intent=intent,
        prepare=lambda *_: (_ for _ in ()).throw(AssertionError("prepare must not rerun")),
    )

    assert result.type == "completed"
    assert result.status == "aborted"
    assert counts["append"] - before_retry["append"] == 0
    assert counts["rebuild"] - before_retry["rebuild"] == 1
    assert counts["complete"] - before_retry["complete"] == 1
    assert counts["append"] == 1


def test_response_rebuild_failure_keeps_processing_for_same_key_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store, request_store, observation_store = _database(tmp_path)
    intent = _intent(request_key=b"response-rebuild-key")
    original_append = event_store.append
    counts = {"append": 0, "rebuild": 0}
    fail_rebuild = True

    def append(batch: EventBatch) -> tuple[object, ...]:
        counts["append"] += 1
        return cast(tuple[object, ...], original_append(batch))

    def rebuild(
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        status: str,
        payload: bytes,
    ) -> CachedTurnResponse:
        nonlocal fail_rebuild
        counts["rebuild"] += 1
        if fail_rebuild:
            fail_rebuild = False
            raise RuntimeError("response rebuild failed")
        return _rebuilder(record, campaign_events, status, payload)

    monkeypatch.setattr(event_store, "append", append)
    coordinator = _coordinator(
        event_store,
        request_store,
        observation_store,
        response_rebuilder=rebuild,
    )
    with pytest.raises(RuntimeError, match="response rebuild failed"):
        coordinator.execute(intent=intent, prepare=lambda *_: _prepared())

    assert request_store.read_processing(campaign_id="campaign:idempotency") is not None
    before_retry = dict(counts)
    result = coordinator.execute(
        intent=intent,
        prepare=lambda *_: (_ for _ in ()).throw(AssertionError("prepare must not rerun")),
    )

    assert result.type == "completed"
    assert counts["append"] == 1
    assert counts["append"] - before_retry["append"] == 0
    assert counts["rebuild"] - before_retry["rebuild"] == 1


def test_normal_terminal_and_recovery_abort_actual_ids_fail_closed(
    tmp_path: Path,
) -> None:
    cases = (
        ("normal-terminal", "TurnCommitted", {"turn_request_id": "turn-request:idempotency"}),
        (
            "recovery-abort",
            "TurnAborted",
            {"turn_request_id": "turn-request:idempotency", "reason": "failed"},
        ),
    )
    for case_name, event_type, payload in cases:
        event_store, request_store, observation_store = _database(tmp_path / case_name)
        intent = _intent(request_key=f"{case_name}-key".encode())
        claim = request_store.claim(intent=intent)
        assert claim.type == "new"
        coordinator = _coordinator(event_store, request_store, observation_store)
        plan = coordinator.recover_processing(record=claim.record, campaign_events=())
        record = plan.record
        event_store.append(
            _batch(
                _draft(
                    "event:actual-id-not-reserved",
                    event_type,
                    payload=payload,
                )
            )
        )

        with pytest.raises(StoreError) as raised:
            coordinator.recover_processing(
                record=record,
                campaign_events=event_store.read_campaign("campaign:idempotency"),
            )

        assert raised.value.code == "recovery_identity_mismatch"
