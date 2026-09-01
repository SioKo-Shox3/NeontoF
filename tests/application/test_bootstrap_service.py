"""P1-05 bootstrap application and Event boundary tests."""

from __future__ import annotations

import inspect
import sqlite3
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest
from neontof.application.bootstrap_service import (
    BootstrapApplicationService,
    BootstrapEventBuilder,
)
from neontof.authoring.bootstrap import BootstrapInput, build_bootstrap_events
from neontof.authoring.character_loader import load_character_sheet
from neontof.authoring.scenario_loader import load_scenario

from neontof.application.turn_lifecycle import (
    ActiveTurnRegistry,
    BootstrapPreparation,
    TurnLifecycleCoordinator,
)
from neontof.application.turn_models import (
    RecoveryEventIdSource,
    RecoveryMetadataFactory,
    ResponseRebuilder,
    TurnEventBatchFactory,
    TurnEventIdSequence,
    UndoResponseRebuilder,
)
from neontof.contracts.domain import DomainEvent
from neontof.contracts.ids import CampaignId, EventId, OccurredAt
from neontof.event_metadata import EventBatch, StoredEvent
from neontof.persistence.event_store import EventStore, EventStoreConstraintError
from neontof.persistence.observation_store import ObservationStore
from neontof.persistence.sqlite_database import SqliteDatabase
from neontof.persistence.turn_request_store import TurnRequestStore

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


def _bootstrap_input() -> BootstrapInput:
    return BootstrapInput(
        campaign_id="campaign:bootstrap",
        session_id="session:bootstrap",
        scene_id="scene:opening",
        turn_id="turn:bootstrap",
        turn_request_id="turn-request:bootstrap",
        input_digest=INPUT_DIGEST,
        campaign_seed="b" * 64,
        campaign_name="Minimal campaign",
        session_title="Opening session",
        scene_label="Forest edge",
        character=load_character_sheet(CHARACTER_FIXTURE),
        scenario=load_scenario(SCENARIO_FIXTURE),
    )


def _coordinator(
    event_store: EventStore,
    event_boundary_lock: threading.Lock,
) -> TurnLifecycleCoordinator:
    return TurnLifecycleCoordinator(
        event_store=event_store,
        request_store=cast(TurnRequestStore, object()),
        observation_store=cast(ObservationStore, object()),
        active_turn_registry=ActiveTurnRegistry(),
        response_rebuilder=cast(ResponseRebuilder, object()),
        undo_response_rebuilder=cast(UndoResponseRebuilder, object()),
        turn_event_factory=cast(TurnEventBatchFactory, object()),
        event_id_sequence=cast(TurnEventIdSequence, object()),
        utc_occurred_at=cast(Callable[[], OccurredAt], object()),
        recovery_event_id_source=cast(RecoveryEventIdSource, object()),
        recovery_metadata_factory=cast(RecoveryMetadataFactory, object()),
        event_boundary_lock=event_boundary_lock,
    )


def _runtime(
    tmp_path: Path,
) -> tuple[Path, EventStore, TurnLifecycleCoordinator, threading.Lock]:
    database_path = tmp_path / "runtime" / "bootstrap.sqlite3"
    database = SqliteDatabase(database_path)
    database.migrate()
    event_store = EventStore(database)
    event_boundary_lock = threading.Lock()
    return (
        database_path,
        event_store,
        _coordinator(event_store, event_boundary_lock),
        event_boundary_lock,
    )


def _batch() -> EventBatch:
    return build_bootstrap_events(_bootstrap_input(), OCCURRED_AT, EVENT_IDS)


def test_bootstrap_batch_is_atomic(tmp_path: Path) -> None:
    database_path, event_store, coordinator, event_boundary_lock = _runtime(tmp_path)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "CREATE TRIGGER fail_bootstrap_insert BEFORE INSERT ON events "
            "WHEN NEW.event_id = 'event:bootstrap-bootstrap-bootstrap-10' "
            "BEGIN SELECT RAISE(ABORT, 'bootstrap failure'); END"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(EventStoreConstraintError):
        coordinator.append_bootstrap(
            campaign_id="campaign:bootstrap",
            prepare=_batch,
        )

    assert event_store.read_campaign("campaign:bootstrap") == ()
    assert event_boundary_lock.acquire(blocking=False)
    event_boundary_lock.release()


def test_append_bootstrap_rejects_existing_events_and_prepares_once(tmp_path: Path) -> None:
    _, event_store, coordinator, event_boundary_lock = _runtime(tmp_path)
    prepare_calls = 0

    def prepare() -> EventBatch:
        nonlocal prepare_calls
        prepare_calls += 1
        return _batch()

    stored = coordinator.append_bootstrap(
        campaign_id="campaign:bootstrap",
        prepare=prepare,
    )
    assert len(stored) == 17
    assert prepare_calls == 1

    with pytest.raises(ValueError):
        coordinator.append_bootstrap(
            campaign_id="campaign:bootstrap",
            prepare=prepare,
        )

    assert prepare_calls == 1
    assert len(event_store.read_campaign("campaign:bootstrap")) == 17
    assert event_boundary_lock.acquire(blocking=False)
    event_boundary_lock.release()


def test_append_bootstrap_validates_predicted_sequence_and_rereads_all_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, event_store, coordinator, _ = _runtime(tmp_path)
    valid_batch = _batch()
    invalid_batch = EventBatch(
        campaign_id=valid_batch.campaign_id,
        drafts=(valid_batch.drafts[-1],) + valid_batch.drafts[:-1],
    )
    read_lengths: list[int] = []
    append_calls = 0
    real_read_campaign = event_store.read_campaign
    real_append = event_store.append

    def recording_read_campaign(campaign_id: CampaignId) -> tuple[DomainEvent, ...]:
        events = real_read_campaign(campaign_id)
        read_lengths.append(len(events))
        return events

    def recording_append(batch: EventBatch) -> tuple[StoredEvent, ...]:
        nonlocal append_calls
        append_calls += 1
        return real_append(batch)

    monkeypatch.setattr(event_store, "read_campaign", recording_read_campaign)
    monkeypatch.setattr(event_store, "append", recording_append)

    with pytest.raises(ValueError):
        coordinator.append_bootstrap(
            campaign_id="campaign:bootstrap",
            prepare=lambda: invalid_batch,
        )
    assert append_calls == 0
    assert real_read_campaign("campaign:bootstrap") == ()

    stored = coordinator.append_bootstrap(
        campaign_id="campaign:bootstrap",
        prepare=lambda: valid_batch,
    )

    assert len(stored) == 17
    assert append_calls == 1
    assert read_lengths == [0, 0, 17]
    assert tuple(event.event_id for event in real_read_campaign("campaign:bootstrap")) == EVENT_IDS


def test_bootstrap_application_service_delegates_batch_to_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, event_store, coordinator, _ = _runtime(tmp_path)
    order: list[str] = []
    observed_batches: list[EventBatch] = []
    real_append_bootstrap = coordinator.append_bootstrap

    def recording_builder(
        input_value: BootstrapInput,
        occurred_at: OccurredAt,
        event_ids: Sequence[EventId],
    ) -> EventBatch:
        order.append("builder")
        return build_bootstrap_events(input_value, occurred_at, event_ids)

    def recording_append_bootstrap(
        *,
        campaign_id: CampaignId,
        prepare: BootstrapPreparation,
    ) -> tuple[StoredEvent, ...]:
        order.append("coordinator")
        batch = prepare()
        observed_batches.append(batch)
        return real_append_bootstrap(campaign_id=campaign_id, prepare=lambda: batch)

    monkeypatch.setattr(coordinator, "append_bootstrap", recording_append_bootstrap)
    service = BootstrapApplicationService(
        coordinator,
        cast(BootstrapEventBuilder, recording_builder),
    )

    stored = service.create_campaign(
        input_value=_bootstrap_input(),
        occurred_at=OCCURRED_AT,
        event_ids=EVENT_IDS,
    )

    assert order == ["coordinator", "builder"]
    assert len(observed_batches) == 1
    assert observed_batches[0].campaign_id == "campaign:bootstrap"
    assert tuple(draft.body.event_id for draft in observed_batches[0].drafts) == EVENT_IDS
    assert tuple(item.event for item in stored) == event_store.read_campaign("campaign:bootstrap")


def test_bootstrap_application_service_has_no_event_store_writer_or_lock(tmp_path: Path) -> None:
    _, event_store, coordinator, _ = _runtime(tmp_path)
    service = BootstrapApplicationService(coordinator, build_bootstrap_events)

    assert tuple(inspect.signature(BootstrapApplicationService.__init__).parameters) == (
        "self",
        "coordinator",
        "build_bootstrap_events",
    )
    assert set(vars(service)) == {"_coordinator", "_build_bootstrap_events"}
    assert vars(service)["_coordinator"] is coordinator
    assert vars(service)["_build_bootstrap_events"] is build_bootstrap_events
    assert not any(isinstance(value, EventStore) for value in vars(service).values())
    assert event_store.read_campaign("campaign:bootstrap") == ()
