"""Turn lifecycle coordination at the append-only Event Log boundary."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import Annotated, Literal, cast

from pydantic import Field, StrictBytes, ValidationError

from neontof.application.turn_models import (
    CachedTurnResponse,
    CompletedTurnResult,
    CoordinatorResult,
    ExistingFinalClaim,
    ExistingFinalTurnResult,
    ExistingProcessingClaim,
    NewClaim,
    OpaqueRequestKey,
    PreparedTurn,
    ProcessingTurnRequestRecord,
    ProcessingTurnResult,
    RecoveryEventIdReservation,
    RecoveryEventIdSource,
    RecoveryEventMetadata,
    RecoveryEventRole,
    RecoveryMetadataFactory,
    RecoveryMetadataInputs,
    RecoveryPlan,
    RecoveryPlanState,
    RecoveryReason,
    RecoverySelector,
    RequestCompletionStatus,
    ResponseRebuilder,
    RevertedTurnResult,
    StoreError,
    TurnEventBatchFactory,
    TurnEventIdSequence,
    TurnPreparation,
    TurnRequestIdentity,
    TurnRequestIntent,
    UndoBlockedResult,
    UndoCommand,
    UndoResponseRebuilder,
    UndoResult,
)
from neontof.contracts.base import ContractModel
from neontof.contracts.domain import (
    DomainEvent,
    PlayerInputAcceptedEvent,
    TurnAbortedEvent,
    TurnAwaitingPlayerEvent,
    TurnCommittedEvent,
    TurnResumedEvent,
    TurnRevertedEvent,
    TurnRevertedPayload,
)
from neontof.contracts.event_parser import DomainEventValidationError
from neontof.contracts.ids import (
    CampaignId,
    EventId,
    OccurredAt,
    TurnId,
    TurnRequestId,
    Visibility,
)
from neontof.contracts.projection import rebuild_projection
from neontof.contracts.turn_status import TurnStatus, project_turn_status
from neontof.event_metadata import (
    EventBatch,
    EventDraft,
    EventDraftBody,
    RevertEventMetadata,
    StoredEvent,
    TurnEventMetadata,
)
from neontof.persistence.event_store import EventStore, _materialize_event_json
from neontof.persistence.observation_store import ObservationStore
from neontof.persistence.turn_request_store import TurnRequestStore

_LIFECYCLE_TYPES = {
    "PlayerInputAccepted",
    "TurnResumed",
    "TurnAwaitingPlayer",
    "TurnCommitted",
    "TurnAborted",
}
_EFFECT_TYPES = {
    "DiceRolled",
    "ResourceChanged",
    "CharacterMoved",
    "ClockAdvanced",
    "FactAsserted",
    "FactSuperseded",
}
_ROLE_FIELDS: dict[RecoveryEventRole, str] = {
    "accepted": "accepted_event_id",
    "resumed": "resumed_event_id",
    "awaiting_player": "awaiting_player_event_id",
    "committed": "committed_event_id",
    "aborted": "aborted_event_id",
    "recovery_aborted": "recovery_aborted_event_id",
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def _draft(
    *,
    event_id: EventId,
    event_type: str,
    campaign_id: CampaignId,
    session_id: str | None,
    scene_id: str | None,
    turn_id: str | None,
    occurred_at: OccurredAt,
    payload: object,
    origin: Literal["in_world", "table_correction"] = "in_world",
    visibility: Visibility = "player_visible",
    payload_json: bytes | None = None,
) -> EventDraft:
    if event_type in {"CampaignCreated", "SessionStarted", "SessionEnded", "TurnReverted"}:
        if event_type in {"CampaignCreated", "SessionStarted"}:
            session_id = None if event_type == "CampaignCreated" else session_id
            scene_id = None
            turn_id = None
        else:
            scene_id = None
            turn_id = None
    return EventDraft(
        body=EventDraftBody(
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
            payload_json=_json_bytes(payload) if payload_json is None else payload_json,
        )
    )


def _identity_from_record(record: ProcessingTurnRequestRecord) -> TurnRequestIdentity:
    values = record.model_dump(exclude={"status", "response"})
    return TurnRequestIdentity.model_validate(values, strict=True)


def _record_has_metadata(record: ProcessingTurnRequestRecord) -> bool:
    return (
        record.recovery_reason is not None
        and record.recovery_selector is not None
        and record.occurred_at is not None
    )


def _strict_response(response: CachedTurnResponse) -> CachedTurnResponse:
    try:
        validated = CachedTurnResponse.model_validate(response, strict=True)
        validated.body.decode("utf-8", errors="strict")
    except UnicodeDecodeError, TypeError, ValidationError, ValueError:
        raise StoreError("invalid_response") from None
    return validated


def _event_request_id(event: DomainEvent) -> TurnRequestId | None:
    if isinstance(
        event,
        (
            PlayerInputAcceptedEvent,
            TurnAwaitingPlayerEvent,
            TurnResumedEvent,
            TurnAbortedEvent,
            TurnCommittedEvent,
        ),
    ):
        return event.payload.turn_request_id
    return None


def _event_role(
    event: DomainEvent, record: ProcessingTurnRequestRecord
) -> RecoveryEventRole | None:
    if isinstance(event, PlayerInputAcceptedEvent):
        return "accepted"
    if isinstance(event, TurnResumedEvent):
        return "resumed"
    if isinstance(event, TurnAwaitingPlayerEvent):
        return "awaiting_player"
    if isinstance(event, TurnCommittedEvent):
        return "committed"
    if isinstance(event, TurnAbortedEvent):
        if record.recovery_aborted_event_id == event.event_id:
            return "recovery_aborted"
        return "aborted"
    return None


def _same_envelope(event: DomainEvent, record: ProcessingTurnRequestRecord) -> bool:
    return (
        event.campaign_id == record.campaign_id
        and event.session_id == record.session_id
        and event.scene_id == record.scene_id
        and event.turn_id == record.turn_id
    )


def matches_current_turn_identity(
    event: DomainEvent,
    *,
    record: ProcessingTurnRequestRecord,
) -> bool:
    """Match an Event using only fields that exist in the Event contract."""

    if not _same_envelope(event, record):
        return False
    request_id = _event_request_id(event)
    if request_id is not None and request_id != record.turn_request_id:
        return False
    if isinstance(event, PlayerInputAcceptedEvent) and record.request_kind == "submit":
        return event.payload.input_digest == record.input_digest
    return True


def _assert_context_consistency(
    events: Sequence[DomainEvent], record: ProcessingTurnRequestRecord
) -> None:
    for event in events:
        if not _same_envelope(event, record):
            continue
        request_id = _event_request_id(event)
        if request_id is not None and request_id != record.turn_request_id:
            raise StoreError("recovery_identity_mismatch")
        if (
            isinstance(event, PlayerInputAcceptedEvent)
            and record.request_kind == "submit"
            and event.payload.input_digest != record.input_digest
        ):
            raise StoreError("recovery_identity_mismatch")


def _split_events(
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
) -> tuple[tuple[DomainEvent, ...], tuple[DomainEvent, ...]]:
    prefix = tuple(
        event for event in campaign_events if event.sequence <= record.base_event_sequence
    )
    owned_suffix = tuple(
        event for event in campaign_events if event.sequence > record.base_event_sequence
    )
    return prefix, owned_suffix


def _current_events(
    record: ProcessingTurnRequestRecord,
    events: Sequence[DomainEvent],
) -> tuple[DomainEvent, ...]:
    return tuple(event for event in events if matches_current_turn_identity(event, record=record))


def _selector_from_events(events: Sequence[DomainEvent]) -> RecoverySelector:
    if any(isinstance(event, (TurnCommittedEvent, TurnAbortedEvent)) for event in events):
        return "terminal"
    if any(isinstance(event, TurnAwaitingPlayerEvent) for event in events):
        return "awaiting_player"
    if any(isinstance(event, TurnResumedEvent) for event in events):
        return "resumed_without_terminal"
    if any(isinstance(event, PlayerInputAcceptedEvent) for event in events):
        return "accepted_without_terminal"
    return "no_lifecycle_events"


def _reason_for_selector(selector: RecoverySelector) -> RecoveryReason:
    values: dict[RecoverySelector, RecoveryReason] = {
        "no_lifecycle_events": "claim_before_first_event",
        "accepted_without_terminal": "after_player_input_accepted",
        "resumed_without_terminal": "after_turn_resumed",
        "awaiting_player": "after_turn_awaiting_player",
        "terminal": "after_terminal",
    }
    return values[selector]


def _reservation_value(reservation: RecoveryEventIdReservation, role: RecoveryEventRole) -> EventId:
    if role == "accepted":
        return reservation.accepted_event_id
    if role == "resumed":
        return reservation.resumed_event_id
    if role == "awaiting_player":
        return reservation.awaiting_player_event_id
    if role == "committed":
        return reservation.committed_event_id
    if role == "aborted":
        return reservation.aborted_event_id
    return reservation.recovery_aborted_event_id


def _record_value(record: ProcessingTurnRequestRecord, role: RecoveryEventRole) -> EventId | None:
    if role == "accepted":
        return record.accepted_event_id
    if role == "resumed":
        return record.resumed_event_id
    if role == "awaiting_player":
        return record.awaiting_player_event_id
    if role == "committed":
        return record.committed_event_id
    if role == "aborted":
        return record.aborted_event_id
    return record.recovery_aborted_event_id


def _first_role_event(
    events: Sequence[DomainEvent],
    role: RecoveryEventRole,
    record: ProcessingTurnRequestRecord,
) -> DomainEvent | None:
    values = tuple(event for event in events if _event_role(event, record) == role)
    if len(values) > 1:
        raise StoreError("recovery_identity_mismatch")
    return values[0] if values else None


def _validate_owned_event_ids(
    record: ProcessingTurnRequestRecord,
    events: Sequence[DomainEvent],
) -> None:
    _validate_record_role_ids(record)
    seen_roles: set[RecoveryEventRole] = set()
    reserved = {
        value
        for value in (
            record.accepted_event_id,
            record.resumed_event_id,
            record.awaiting_player_event_id,
            record.committed_event_id,
            record.aborted_event_id,
            record.recovery_aborted_event_id,
        )
        if value is not None
    }
    for event in events:
        role = _event_role(event, record)
        if role is None:
            if event.event_id in reserved:
                raise StoreError("recovery_identity_mismatch")
            continue
        expected = _record_value(record, role)
        if expected != event.event_id or role in seen_roles:
            raise StoreError("recovery_identity_mismatch")
        seen_roles.add(role)
    if any(
        _record_value(record, "aborted") is not None
        and _record_value(record, "recovery_aborted") is not None
        and _record_value(record, "aborted") == _record_value(record, "recovery_aborted")
        for _ in (0,)
    ):
        raise StoreError("recovery_identity_mismatch")


def _validate_record_role_ids(record: ProcessingTurnRequestRecord) -> None:
    values = tuple(
        value
        for value in (
            record.accepted_event_id,
            record.resumed_event_id,
            record.awaiting_player_event_id,
            record.committed_event_id,
            record.aborted_event_id,
            record.recovery_aborted_event_id,
        )
        if value is not None
    )
    if len(values) != len(set(values)):
        raise StoreError("recovery_identity_mismatch")


def _recovery_metadata_ids(
    record: ProcessingTurnRequestRecord,
    prefix_events: Sequence[DomainEvent],
    reservation: RecoveryEventIdReservation,
) -> dict[str, EventId]:
    values: dict[str, EventId] = {}
    for role, field in _ROLE_FIELDS.items():
        event = _first_role_event(prefix_events, role, record)
        values[field] = (
            event.event_id if event is not None else _reservation_value(reservation, role)
        )
    return values


def _derived_event_ids(
    *,
    accepted_event_id: EventId | None,
    resumed_event_id: EventId | None,
    awaiting_player_event_id: EventId | None,
    committed_event_id: EventId | None,
    aborted_event_id: EventId | None,
    recovery_aborted_event_id: EventId | None,
) -> tuple[EventId, ...]:
    return tuple(
        event_id
        for event_id in (
            accepted_event_id,
            resumed_event_id,
            awaiting_player_event_id,
            committed_event_id,
            aborted_event_id,
            recovery_aborted_event_id,
        )
        if event_id is not None
    )


def build_recovery_metadata(
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
    inputs: RecoveryMetadataInputs,
) -> RecoveryEventMetadata:
    """Build all recovery metadata from the validated prefix and one reservation."""

    if record.status != "processing":
        raise StoreError("request_not_processing")
    _assert_context_consistency(campaign_events, record)
    prefix_events, owned_suffix = _split_events(record, campaign_events)
    current_prefix = _current_events(record, prefix_events)
    current_owned_suffix = _current_events(record, owned_suffix)
    _validate_owned_event_ids(record, current_owned_suffix)
    selector = _selector_from_events(current_prefix)
    reason = _reason_for_selector(selector)
    role_ids = _recovery_metadata_ids(record, current_prefix, inputs.reservation)
    return RecoveryEventMetadata(
        request_kind=record.request_kind,
        recovery_payload_version=record.recovery_payload_version,
        campaign_id=record.campaign_id,
        session_id=record.session_id,
        scene_id=record.scene_id,
        turn_id=record.turn_id,
        turn_request_id=record.turn_request_id,
        root_turn_request_id=record.root_turn_request_id,
        input_digest=record.input_digest,
        recovery_reason=reason,
        recovery_selector=selector,
        occurred_at=inputs.occurred_at,
        accepted_event_id=role_ids["accepted_event_id"],
        resumed_event_id=role_ids["resumed_event_id"],
        awaiting_player_event_id=role_ids["awaiting_player_event_id"],
        committed_event_id=role_ids["committed_event_id"],
        aborted_event_id=role_ids["aborted_event_id"],
        recovery_aborted_event_id=role_ids["recovery_aborted_event_id"],
        event_ids=_derived_event_ids(
            accepted_event_id=role_ids["accepted_event_id"],
            resumed_event_id=role_ids["resumed_event_id"],
            awaiting_player_event_id=role_ids["awaiting_player_event_id"],
            committed_event_id=role_ids["committed_event_id"],
            aborted_event_id=role_ids["aborted_event_id"],
            recovery_aborted_event_id=role_ids["recovery_aborted_event_id"],
        ),
    )


def derive_recovery_event_id(
    identity: TurnRequestIdentity,
    role: RecoveryEventRole,
) -> EventId:
    """Derive one stable recovery Event ID without capturing persistence state."""

    key = bytes(identity.request_key)
    preimage = (
        b"NEONTOF:TURN-RECOVERY:v1\0"
        + str(len(key)).encode("ascii")
        + b":"
        + key
        + b"\0"
        + role.encode("ascii")
    )
    return "event:" + hashlib.sha256(preimage).hexdigest()


def reserve_recovery_event_ids(identity: TurnRequestIdentity) -> RecoveryEventIdReservation:
    return RecoveryEventIdReservation(
        accepted_event_id=derive_recovery_event_id(identity, "accepted"),
        resumed_event_id=derive_recovery_event_id(identity, "resumed"),
        awaiting_player_event_id=derive_recovery_event_id(identity, "awaiting_player"),
        committed_event_id=derive_recovery_event_id(identity, "committed"),
        aborted_event_id=derive_recovery_event_id(identity, "aborted"),
        recovery_aborted_event_id=derive_recovery_event_id(identity, "recovery_aborted"),
    )


def _normal_drafts(
    identity: TurnRequestIdentity,
    prepared: PreparedTurn,
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
) -> tuple[EventDraft, ...]:
    cursor = 0
    drafts: list[EventDraft] = []
    if identity.request_kind == "submit":
        drafts.append(
            _draft(
                event_id=event_ids[cursor],
                event_type="PlayerInputAccepted",
                campaign_id=identity.campaign_id,
                session_id=identity.session_id,
                scene_id=identity.scene_id,
                turn_id=identity.turn_id,
                occurred_at=occurred_at,
                payload={
                    "turn_request_id": identity.turn_request_id,
                    "input_digest": identity.input_digest,
                },
            )
        )
        cursor += 1
    drafts.append(
        _draft(
            event_id=event_ids[cursor],
            event_type="TurnResumed",
            campaign_id=identity.campaign_id,
            session_id=identity.session_id,
            scene_id=identity.scene_id,
            turn_id=identity.turn_id,
            occurred_at=occurred_at,
            payload={"turn_request_id": identity.turn_request_id},
        )
    )
    cursor += 1
    for effect in prepared.effect_candidates:
        drafts.append(
            EventDraft(
                body=EventDraftBody(
                    type=effect.type,
                    event_id=event_ids[cursor],
                    event_version=effect.event_version,
                    campaign_id=effect.campaign_id,
                    session_id=effect.session_id,
                    scene_id=effect.scene_id,
                    turn_id=effect.turn_id,
                    occurred_at=occurred_at,
                    origin=effect.origin,
                    visibility=effect.visibility,
                    payload_json=effect.payload_json,
                )
            )
        )
        cursor += 1
    if prepared.terminal_status == "committed":
        event_type = "TurnCommitted"
        payload: object = {"turn_request_id": identity.turn_request_id}
    elif prepared.terminal_status == "aborted":
        event_type = "TurnAborted"
        payload = {
            "turn_request_id": identity.turn_request_id,
            "reason": prepared.abort_reason or "failed",
        }
    else:
        event_type = "TurnAwaitingPlayer"
        payload = {"turn_request_id": identity.turn_request_id}
    drafts.append(
        _draft(
            event_id=event_ids[cursor],
            event_type=event_type,
            campaign_id=identity.campaign_id,
            session_id=identity.session_id,
            scene_id=identity.scene_id,
            turn_id=identity.turn_id,
            occurred_at=occurred_at,
            payload=payload,
        )
    )
    cursor += 1
    if prepared.scenario_end is not None:
        drafts.append(
            _draft(
                event_id=event_ids[cursor],
                event_type="SessionEnded",
                campaign_id=identity.campaign_id,
                session_id=identity.session_id,
                scene_id=None,
                turn_id=None,
                occurred_at=occurred_at,
                payload={"reason": "completed"},
            )
        )
    return tuple(drafts)


def _normal_recovery_metadata(
    identity: TurnRequestIdentity,
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
    prepared: PreparedTurn,
    campaign_events: tuple[DomainEvent, ...],
) -> RecoveryEventMetadata:
    record_values = identity.model_dump()
    record_values.update(status="processing", response=None)
    record = ProcessingTurnRequestRecord.model_validate(record_values, strict=True)
    reservation = reserve_recovery_event_ids(identity)
    origin = build_recovery_metadata(
        record,
        campaign_events,
        RecoveryMetadataInputs(occurred_at=occurred_at, reservation=reservation),
    )
    prefix, _ = _split_events(record, campaign_events)
    current_prefix = _current_events(record, prefix)

    def prefix_event_id(role: RecoveryEventRole) -> EventId | None:
        if identity.request_kind == "resume" and role not in {"accepted", "awaiting_player"}:
            return None
        event = _first_role_event(current_prefix, role, record)
        return event.event_id if event is not None else None

    cursor = 0
    accepted: EventId | None = None
    if identity.request_kind == "submit":
        accepted = event_ids[cursor]
        cursor += 1
    resumed = event_ids[cursor]
    cursor += 1 + len(prepared.effect_candidates)
    terminal = event_ids[cursor]
    accepted_id = prefix_event_id("accepted") or accepted or origin.accepted_event_id
    resumed_id = prefix_event_id("resumed") or resumed
    awaiting_id = prefix_event_id("awaiting_player") or (
        terminal
        if prepared.terminal_status == "awaiting_player"
        else origin.awaiting_player_event_id
    )
    committed_id = prefix_event_id("committed") or (
        terminal if prepared.terminal_status == "committed" else origin.committed_event_id
    )
    aborted_id = prefix_event_id("aborted") or (
        terminal if prepared.terminal_status == "aborted" else origin.aborted_event_id
    )
    recovery_aborted_id = origin.recovery_aborted_event_id
    return RecoveryEventMetadata(
        request_kind=identity.request_kind,
        recovery_payload_version=identity.recovery_payload_version,
        campaign_id=identity.campaign_id,
        session_id=identity.session_id,
        scene_id=identity.scene_id,
        turn_id=identity.turn_id,
        turn_request_id=identity.turn_request_id,
        root_turn_request_id=identity.root_turn_request_id,
        input_digest=identity.input_digest,
        recovery_reason=origin.recovery_reason,
        recovery_selector=origin.recovery_selector,
        occurred_at=occurred_at,
        accepted_event_id=accepted_id,
        resumed_event_id=resumed_id,
        awaiting_player_event_id=awaiting_id,
        committed_event_id=committed_id,
        aborted_event_id=aborted_id,
        recovery_aborted_event_id=recovery_aborted_id,
        event_ids=_derived_event_ids(
            accepted_event_id=accepted_id,
            resumed_event_id=resumed_id,
            awaiting_player_event_id=awaiting_id,
            committed_event_id=committed_id,
            aborted_event_id=aborted_id,
            recovery_aborted_event_id=recovery_aborted_id,
        ),
    )


def build_turn_event_batch(
    identity: TurnRequestIdentity,
    prepared: PreparedTurn,
    campaign_events: tuple[DomainEvent, ...],
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
) -> tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch]:
    """Construct the post-ID normal Event batch and its recovery metadata."""

    if identity.request_kind == "resume" and prepared.terminal_status == "awaiting_player":
        raise StoreError("recovery_identity_mismatch")
    ids = tuple(event_ids)
    expected_count = (
        (2 if identity.request_kind == "submit" else 1)
        + len(prepared.effect_candidates)
        + 1
        + (1 if prepared.scenario_end is not None else 0)
    )
    if len(ids) != expected_count or len(ids) != len(set(ids)):
        raise StoreError("recovery_identity_mismatch")
    drafts = _normal_drafts(identity, prepared, occurred_at, ids)
    metadata = TurnEventMetadata(
        campaign_id=identity.campaign_id,
        session_id=identity.session_id,
        scene_id=identity.scene_id,
        turn_id=identity.turn_id,
        turn_request_id=identity.turn_request_id,
        root_turn_request_id=identity.root_turn_request_id,
        occurred_at=occurred_at,
        event_ids=ids,
    )
    recovery = _normal_recovery_metadata(identity, occurred_at, ids, prepared, campaign_events)
    return metadata, recovery, EventBatch(campaign_id=identity.campaign_id, drafts=drafts)


def build_revert_event(
    metadata: RevertEventMetadata,
    payload: TurnRevertedPayload,
) -> EventBatch:
    if not metadata.event_ids:
        raise ValueError("revert event requires an event ID")
    return EventBatch(
        campaign_id=metadata.campaign_id,
        drafts=(
            _draft(
                event_id=metadata.event_ids[0],
                event_type="TurnReverted",
                campaign_id=metadata.campaign_id,
                session_id=metadata.session_id,
                scene_id=None,
                turn_id=None,
                occurred_at=metadata.occurred_at,
                payload=payload.model_dump(),
                origin="table_correction",
                visibility="player_visible",
            ),
        ),
    )


def build_crash_recovery_batch(
    record: ProcessingTurnRequestRecord,
    campaign_events: Sequence[DomainEvent],
) -> EventBatch:
    if not _record_has_metadata(record):
        raise StoreError("recovery_identity_mismatch")
    prefix, owned_suffix = _split_events(record, tuple(campaign_events))
    current_prefix = _current_events(record, prefix)
    current_owned_suffix = _current_events(record, owned_suffix)
    _validate_owned_event_ids(record, current_prefix)
    _validate_owned_event_ids(record, current_owned_suffix)
    accepted_id = record.accepted_event_id
    recovery_aborted_id = record.recovery_aborted_event_id
    if recovery_aborted_id is None:
        raise StoreError("recovery_identity_mismatch")
    drafts: list[EventDraft] = []
    has_accepted = any(
        isinstance(event, PlayerInputAcceptedEvent)
        for event in (*current_prefix, *current_owned_suffix)
    )
    if record.request_kind == "submit" and not has_accepted and accepted_id is not None:
        drafts.append(
            _draft(
                event_id=accepted_id,
                event_type="PlayerInputAccepted",
                campaign_id=record.campaign_id,
                session_id=record.session_id,
                scene_id=record.scene_id,
                turn_id=record.turn_id,
                occurred_at=cast(OccurredAt, record.occurred_at),
                payload={
                    "turn_request_id": record.turn_request_id,
                    "input_digest": record.input_digest,
                },
            )
        )
    drafts.append(
        _draft(
            event_id=recovery_aborted_id,
            event_type="TurnAborted",
            campaign_id=record.campaign_id,
            session_id=record.session_id,
            scene_id=record.scene_id,
            turn_id=record.turn_id,
            occurred_at=cast(OccurredAt, record.occurred_at),
            payload={"turn_request_id": record.turn_request_id, "reason": "failed"},
        )
    )
    return EventBatch(campaign_id=record.campaign_id, drafts=tuple(drafts))


def _materialize_candidate_events(
    existing_events: tuple[DomainEvent, ...], candidate_batch: EventBatch
) -> tuple[DomainEvent, ...]:
    if any(
        draft.body.campaign_id != candidate_batch.campaign_id for draft in candidate_batch.drafts
    ):
        raise StoreError("recovery_identity_mismatch")
    sequence = existing_events[-1].sequence if existing_events else 0
    candidate_events: list[DomainEvent] = []
    try:
        for offset, draft in enumerate(candidate_batch.drafts, start=1):
            _, event = _materialize_event_json(body=draft.body, sequence=sequence + offset)
            candidate_events.append(event)
    except DomainEventValidationError, TypeError, ValueError:
        raise StoreError("recovery_identity_mismatch") from None
    return tuple(candidate_events)


def validate_and_materialize_candidate(
    existing_events: tuple[DomainEvent, ...], candidate_batch: EventBatch
) -> tuple[DomainEvent, ...]:
    """Validate status and projection against a virtual append before writing."""

    try:
        rebuild_projection(existing_events)
        candidate_events = _materialize_candidate_events(existing_events, candidate_batch)
        virtual_events = existing_events + candidate_events
        effect_events = tuple(event for event in candidate_events if event.type in _EFFECT_TYPES)
        terminal_events = tuple(
            event
            for event in candidate_events
            if isinstance(event, (TurnAwaitingPlayerEvent, TurnCommittedEvent, TurnAbortedEvent))
        )
        session_end_events = tuple(
            event for event in candidate_events if event.type == "SessionEnded"
        )
        if session_end_events and (
            len(session_end_events) != 1
            or candidate_events[-1] is not session_end_events[0]
            or len(terminal_events) != 1
            or not isinstance(terminal_events[0], TurnCommittedEvent)
            or candidate_events.index(terminal_events[0])
            >= candidate_events.index(session_end_events[0])
        ):
            raise StoreError("recovery_identity_mismatch")
        if effect_events:
            if not any(isinstance(event, TurnCommittedEvent) for event in candidate_events):
                raise StoreError("recovery_identity_mismatch")
            if any(
                isinstance(event, (TurnAwaitingPlayerEvent, TurnAbortedEvent))
                for event in candidate_events
            ):
                raise StoreError("recovery_identity_mismatch")
            terminal_index = candidate_events.index(
                next(event for event in candidate_events if isinstance(event, TurnCommittedEvent))
            )
            if any(candidate_events.index(event) > terminal_index for event in effect_events):
                raise StoreError("recovery_identity_mismatch")
        turn_ids = {event.turn_id for event in candidate_events if event.turn_id is not None}
        for turn_id in turn_ids:
            project_turn_status(turn_id, virtual_events)
        rebuild_projection(virtual_events)
    except DomainEventValidationError:
        raise StoreError("recovery_identity_mismatch") from None
    return virtual_events


def select_response_payload(
    *,
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
) -> bytes:
    """Select stored opaque response bytes from current owned Event membership."""

    _assert_context_consistency(campaign_events, record)
    prefix, owned_suffix = _split_events(record, campaign_events)
    current_owned = _current_events(record, owned_suffix)
    _validate_owned_event_ids(record, current_owned)
    normal_terminal = tuple(
        event
        for event in current_owned
        if isinstance(event, (TurnCommittedEvent, TurnAbortedEvent))
        and event.event_id in {record.committed_event_id, record.aborted_event_id}
    )
    recovery_abort = tuple(
        event
        for event in current_owned
        if isinstance(event, TurnAbortedEvent)
        and event.event_id == record.recovery_aborted_event_id
    )
    awaiting = tuple(
        event
        for event in current_owned
        if isinstance(event, TurnAwaitingPlayerEvent)
        and event.event_id == record.awaiting_player_event_id
    )
    if sum(bool(values) for values in (normal_terminal, recovery_abort, awaiting)) > 1:
        raise StoreError("recovery_identity_mismatch")
    if len(normal_terminal) > 1 or len(recovery_abort) > 1 or len(awaiting) > 1:
        raise StoreError("recovery_identity_mismatch")
    if recovery_abort:
        return bytes(record.initial_recovery_payload)
    if awaiting:
        if record.staged_recovery_payload is not None:
            return bytes(record.staged_recovery_payload)
        return bytes(record.initial_recovery_payload)
    if normal_terminal:
        if record.recovery_payload_version != 2 or record.staged_recovery_payload is None:
            raise StoreError("recovery_identity_mismatch")
        return bytes(record.staged_recovery_payload)
    del prefix
    raise StoreError("recovery_identity_mismatch")


def select_latest_committed_turn(campaign_events: Sequence[DomainEvent]) -> TurnCommittedEvent:
    try:
        rebuild_projection(campaign_events)
    except DomainEventValidationError:
        raise StoreError("recovery_identity_mismatch") from None
    reverted = {
        event.payload.target_turn_id for event in campaign_events if event.type == "TurnReverted"
    }
    committed = [
        event
        for event in campaign_events
        if isinstance(event, TurnCommittedEvent) and event.turn_id is not None
    ]
    available = [event for event in committed if event.turn_id not in reverted]
    if not available:
        raise StoreError("turn_not_found")
    return max(available, key=lambda event: event.sequence)


def derive_revert_event_id(*, campaign_id: CampaignId, request_key: OpaqueRequestKey) -> EventId:
    campaign_bytes = str(campaign_id).encode("utf-8")
    request_key_bytes = bytes(request_key)
    preimage = (
        b"NEONTOF:TURN-REVERT:v1\0"
        + str(len(campaign_bytes)).encode("ascii")
        + b":"
        + campaign_bytes
        + b"\0"
        + str(len(request_key_bytes)).encode("ascii")
        + b":"
        + request_key_bytes
    )
    return "event:" + hashlib.sha256(preimage).hexdigest()


ActiveTurnToken = Annotated[StrictBytes, Field(min_length=1)]


class OwnedActiveTurn(ContractModel):
    type: Literal["owned"]
    intent: TurnRequestIntent
    token: ActiveTurnToken


class ExistingActiveTurn(ContractModel):
    type: Literal["existing_active"]
    intent: TurnRequestIntent
    token: ActiveTurnToken


ActiveTurnAcquisition = Annotated[
    OwnedActiveTurn | ExistingActiveTurn,
    Field(discriminator="type"),
]


class ActiveTurnRegistry:
    """Process-lifetime barrier for one active turn per campaign/turn pair."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[tuple[CampaignId, TurnId], tuple[TurnRequestIntent, bytes]] = {}

    def try_acquire(self, *, intent: TurnRequestIntent) -> ActiveTurnAcquisition:
        key = (intent.campaign_id, intent.turn_id)
        with self._lock:
            existing = self._active.get(key)
            if existing is not None:
                existing_intent, token = existing
                return ExistingActiveTurn(
                    type="existing_active", intent=existing_intent, token=token
                )
            token = secrets.token_bytes(32)
            self._active[key] = (intent, token)
            return OwnedActiveTurn(type="owned", intent=intent, token=token)

    def release(self, *, token: ActiveTurnToken) -> None:
        with self._lock:
            for key, (_, active_token) in tuple(self._active.items()):
                if active_token == token:
                    del self._active[key]
                    return


def _intent_matches_active(existing: TurnRequestIntent, incoming: TurnRequestIntent) -> bool:
    return existing.model_dump(exclude={"initial_recovery_payload"}) == incoming.model_dump(
        exclude={"initial_recovery_payload"}
    )


def _as_completion_status(status: TurnStatus) -> RequestCompletionStatus:
    if status not in {"awaiting_player", "committed", "aborted"}:
        raise StoreError("recovery_identity_mismatch")
    return status


class TurnLifecycleCoordinator:
    """Own the application-level claim, validation, append, rebuild, and completion order."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        request_store: TurnRequestStore,
        observation_store: ObservationStore,
        active_turn_registry: ActiveTurnRegistry,
        response_rebuilder: ResponseRebuilder,
        undo_response_rebuilder: UndoResponseRebuilder,
        turn_event_factory: TurnEventBatchFactory,
        event_id_sequence: TurnEventIdSequence,
        utc_occurred_at: Callable[[], OccurredAt],
        recovery_event_id_source: RecoveryEventIdSource,
        recovery_metadata_factory: RecoveryMetadataFactory,
        event_boundary_lock: AbstractContextManager[object],
    ) -> None:
        self._event_store = event_store
        self._request_store = request_store
        self._observation_store = observation_store
        self._active_turn_registry = active_turn_registry
        self._response_rebuilder = response_rebuilder
        self._undo_response_rebuilder = undo_response_rebuilder
        self._turn_event_factory = turn_event_factory
        self._event_id_sequence = event_id_sequence
        self._utc_occurred_at = utc_occurred_at
        self._recovery_event_id_source = recovery_event_id_source
        self._recovery_metadata_factory = recovery_metadata_factory
        self._event_boundary_lock = event_boundary_lock

    def _processing_result(self, intent: TurnRequestIntent) -> ProcessingTurnResult:
        return ProcessingTurnResult(
            type="processing",
            request_key=intent.request_key,
            turn_id=intent.turn_id,
            turn_request_id=intent.turn_request_id,
            status="processing",
            http_status_code=202,
            response=None,
        )

    def _complete_from_events(
        self,
        *,
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        appended_events: tuple[StoredEvent, ...],
    ) -> CompletedTurnResult:
        try:
            rebuild_projection(campaign_events)
        except DomainEventValidationError:
            raise StoreError("recovery_identity_mismatch") from None
        status = project_turn_status(record.turn_id, campaign_events)
        completion_status = _as_completion_status(status)
        payload = select_response_payload(record=record, campaign_events=campaign_events)
        response = _strict_response(
            self._response_rebuilder(record, campaign_events, status, payload)
        )
        completed = self._request_store.complete(
            request_key=record.request_key,
            expected_version=record.recovery_payload_version,
            status=completion_status,
            response=response,
        )
        return CompletedTurnResult(
            type="completed",
            request_key=record.request_key,
            turn_id=record.turn_id,
            turn_request_id=record.turn_request_id,
            status=completed.status,
            response=completed.response,
            appended_events=appended_events,
        )

    def _validate_batch_for_record(
        self,
        *,
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
        candidate_batch: EventBatch,
    ) -> None:
        _validate_record_role_ids(record)
        virtual_events = validate_and_materialize_candidate(campaign_events, candidate_batch)
        candidate_events = virtual_events[len(campaign_events) :]
        status = project_turn_status(record.turn_id, virtual_events)
        if status not in {"awaiting_player", "committed", "aborted"}:
            raise StoreError("recovery_identity_mismatch")
        for event in candidate_events:
            if event.campaign_id != record.campaign_id:
                raise StoreError("recovery_identity_mismatch")
            if event.type not in _LIFECYCLE_TYPES | _EFFECT_TYPES | {"SessionEnded"}:
                raise StoreError("recovery_identity_mismatch")
            if event.type in _LIFECYCLE_TYPES and (
                event.session_id != record.session_id
                or event.scene_id != record.scene_id
                or event.turn_id != record.turn_id
            ):
                raise StoreError("recovery_identity_mismatch")
            if event.type in {"FactAsserted", "FactSuperseded"} and (
                event.session_id != record.session_id
                or event.scene_id is not None
                or event.turn_id is not None
            ):
                raise StoreError("recovery_identity_mismatch")
            if event.type == "SessionEnded" and (
                event.session_id != record.session_id
                or event.scene_id is not None
                or event.turn_id is not None
            ):
                raise StoreError("recovery_identity_mismatch")
            request_id = _event_request_id(event)
            if request_id is not None and request_id != record.turn_request_id:
                raise StoreError("recovery_identity_mismatch")
            if (
                isinstance(event, PlayerInputAcceptedEvent)
                and event.payload.input_digest != record.input_digest
            ):
                raise StoreError("recovery_identity_mismatch")
            role = _event_role(event, record)
            if record.request_kind == "resume" and isinstance(event, TurnAwaitingPlayerEvent):
                raise StoreError("recovery_identity_mismatch")
            if role is not None:
                if _record_value(record, role) != event.event_id:
                    raise StoreError("recovery_identity_mismatch")
                if role == "accepted" and record.request_kind == "resume":
                    raise StoreError("recovery_identity_mismatch")
            elif event.event_id in {
                value
                for value in (
                    record.accepted_event_id,
                    record.resumed_event_id,
                    record.awaiting_player_event_id,
                    record.committed_event_id,
                    record.aborted_event_id,
                    record.recovery_aborted_event_id,
                )
                if value is not None
            }:
                raise StoreError("recovery_identity_mismatch")
            if event.type in {
                "DiceRolled",
                "ResourceChanged",
                "CharacterMoved",
                "ClockAdvanced",
            } and (
                event.session_id != record.session_id
                or event.scene_id != record.scene_id
                or event.turn_id != record.turn_id
            ):
                raise StoreError("recovery_identity_mismatch")

    def execute(
        self,
        *,
        intent: TurnRequestIntent,
        prepare: TurnPreparation,
    ) -> CoordinatorResult:
        acquisition: ActiveTurnAcquisition = self._active_turn_registry.try_acquire(intent=intent)
        if isinstance(acquisition, ExistingActiveTurn):
            if not _intent_matches_active(acquisition.intent, intent):
                if acquisition.intent.request_key == intent.request_key:
                    raise StoreError("request_key_conflict")
                raise StoreError("turn_already_processing")
            return self._processing_result(intent)

        owned = acquisition
        boundary_entered = False
        try:
            self._event_boundary_lock.__enter__()
            boundary_entered = True
            claim = self._request_store.claim(intent=intent)
            record: ProcessingTurnRequestRecord
            candidate_batch: EventBatch | None = None
            appended_events: tuple[StoredEvent, ...] = ()
            if isinstance(claim, ExistingFinalClaim):
                final = claim.record
                return ExistingFinalTurnResult(
                    type="existing_final",
                    request_key=final.request_key,
                    turn_id=final.turn_id,
                    turn_request_id=final.turn_request_id,
                    status=cast(TurnStatus, final.status),
                    response=final.response,
                    appended_events=(),
                )
            if isinstance(claim, ExistingProcessingClaim):
                record = claim.record
                campaign_events = self._event_store.read_campaign(record.campaign_id)
                plan = self.recover_processing(record=record, campaign_events=campaign_events)
                record = plan.record
                candidate_batch = plan.candidate_batch
            elif isinstance(claim, NewClaim):
                record = claim.record
                campaign_events = self._event_store.read_campaign(record.campaign_id)
                identity = _identity_from_record(record)
                prepared = prepare(identity, campaign_events)
                if (
                    identity.request_kind == "resume"
                    and prepared.terminal_status == "awaiting_player"
                ):
                    raise StoreError("recovery_identity_mismatch")
                if prepared.staged_recovery_payload is not None:
                    record = self._request_store.stage(
                        request_key=record.request_key,
                        expected_version=1,
                        staged_recovery_payload=prepared.staged_recovery_payload,
                    )
                    identity = _identity_from_record(record)
                event_ids = self._event_id_sequence(identity, prepared)
                occurred_at = self._utc_occurred_at()
                _, recovery_metadata, candidate_batch = self._turn_event_factory(
                    identity,
                    prepared,
                    campaign_events,
                    occurred_at,
                    event_ids,
                )
                record = self._request_store.stage_recovery_metadata(
                    request_key=record.request_key,
                    metadata=recovery_metadata,
                )
            else:
                raise StoreError("store_integrity_error")

            if candidate_batch is not None:
                self._validate_batch_for_record(
                    record=record,
                    campaign_events=campaign_events,
                    candidate_batch=candidate_batch,
                )
            if candidate_batch is not None and candidate_batch.drafts:
                appended_events = self._event_store.append(candidate_batch)
            campaign_events = self._event_store.read_campaign(record.campaign_id)
            return self._complete_from_events(
                record=record,
                campaign_events=campaign_events,
                appended_events=appended_events,
            )
        finally:
            if boundary_entered:
                self._event_boundary_lock.__exit__(None, None, None)
            self._active_turn_registry.release(token=owned.token)

    def recover_processing(
        self,
        *,
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
    ) -> RecoveryPlan:
        if not _record_has_metadata(record):
            identity = _identity_from_record(record)
            inputs = RecoveryMetadataInputs(
                occurred_at=self._utc_occurred_at(),
                reservation=self._recovery_event_id_source(identity),
            )
            metadata = self._recovery_metadata_factory(record, campaign_events, inputs)
            record = self._request_store.stage_recovery_metadata(
                request_key=record.request_key,
                metadata=metadata,
            )
        prefix, owned_suffix = _split_events(record, campaign_events)
        current_prefix = _current_events(record, prefix)
        current_owned = _current_events(record, owned_suffix)
        _validate_owned_event_ids(record, current_prefix)
        _validate_owned_event_ids(record, current_owned)
        normal_terminal = tuple(
            event
            for event in current_owned
            if isinstance(event, (TurnCommittedEvent, TurnAbortedEvent))
            and event.event_id in {record.committed_event_id, record.aborted_event_id}
        )
        recovery_abort = tuple(
            event
            for event in current_owned
            if isinstance(event, TurnAbortedEvent)
            and event.event_id == record.recovery_aborted_event_id
        )
        awaiting = tuple(
            event
            for event in current_owned
            if isinstance(event, TurnAwaitingPlayerEvent)
            and event.event_id == record.awaiting_player_event_id
        )
        if normal_terminal and recovery_abort:
            raise StoreError("recovery_identity_mismatch")
        state: RecoveryPlanState
        if normal_terminal:
            state = "normal_terminal"
            candidate_batch = None
        elif awaiting:
            if record.request_kind == "resume":
                raise StoreError("recovery_identity_mismatch")
            state = "awaiting_player"
            candidate_batch = None
        elif recovery_abort:
            state = "recovery_abort"
            candidate_batch = None
        else:
            state = "recovery_abort"
            candidate_batch = build_crash_recovery_batch(record, campaign_events)
        return RecoveryPlan(
            record=record,
            campaign_events=campaign_events,
            prefix_events=prefix,
            owned_suffix=owned_suffix,
            state=state,
            recovery_selector=cast(RecoverySelector, record.recovery_selector),
            candidate_batch=candidate_batch,
            accepted_event_id=record.accepted_event_id,
            resumed_event_id=record.resumed_event_id,
            awaiting_player_event_id=record.awaiting_player_event_id,
            committed_event_id=record.committed_event_id,
            aborted_event_id=record.aborted_event_id,
            recovery_aborted_event_id=record.recovery_aborted_event_id,
        )

    def revert_latest(self, *, command: UndoCommand) -> UndoResult:
        boundary_entered = False
        try:
            self._event_boundary_lock.__enter__()
            boundary_entered = True
            processing = self._request_store.read_processing(campaign_id=command.campaign_id)
            if processing is not None:
                return UndoBlockedResult(
                    type="blocked",
                    http_status_code=409,
                    code="turn_already_processing",
                    response=None,
                )
            campaign_events = self._event_store.read_campaign(command.campaign_id)
            revert_event_id = derive_revert_event_id(
                campaign_id=command.campaign_id,
                request_key=command.request_key,
            )
            existing = tuple(
                event
                for event in campaign_events
                if event.type == "TurnReverted" and event.event_id == revert_event_id
            )
            if existing:
                if len(existing) != 1:
                    raise StoreError("undo_conflict")
                revert = existing[0]
                target_turn_id = revert.payload.target_turn_id
                committed = tuple(
                    event
                    for event in campaign_events
                    if isinstance(event, TurnCommittedEvent) and event.turn_id == target_turn_id
                )
                target_context_matches = len(committed) == 1 and (
                    committed[0].campaign_id == command.campaign_id
                    and committed[0].session_id == command.session_id
                    and committed[0].scene_id is not None
                    and committed[0].turn_id == target_turn_id
                )
                if (
                    not target_context_matches
                    or revert.campaign_id != command.campaign_id
                    or revert.session_id != command.session_id
                    or revert.scene_id is not None
                    or revert.turn_id is not None
                    or revert.origin != "table_correction"
                    or revert.visibility != "player_visible"
                ):
                    raise StoreError("undo_conflict")
                try:
                    rebuild_projection(campaign_events)
                except DomainEventValidationError:
                    raise StoreError("recovery_identity_mismatch") from None
                status = project_turn_status(target_turn_id, campaign_events)
                response = _strict_response(
                    self._undo_response_rebuilder(
                        command,
                        campaign_events,
                        status,
                        target_turn_id,
                        revert_event_id,
                    )
                )
                return RevertedTurnResult(
                    target_turn_id=target_turn_id,
                    revert_event_id=revert_event_id,
                    response=response,
                )
            latest = select_latest_committed_turn(campaign_events)
            if (
                latest.campaign_id != command.campaign_id
                or latest.session_id != command.session_id
                or latest.scene_id is None
                or latest.turn_id is None
            ):
                raise StoreError("turn_not_in_session")
            metadata = RevertEventMetadata(
                campaign_id=command.campaign_id,
                session_id=command.session_id,
                scene_id=latest.scene_id,
                turn_id=latest.turn_id,
                turn_request_id=latest.payload.turn_request_id,
                occurred_at=command.occurred_at,
                event_ids=(revert_event_id,),
            )
            candidate_batch = build_revert_event(
                metadata,
                TurnRevertedPayload(target_turn_id=latest.turn_id),
            )
            self._validate_batch_for_revert(campaign_events, candidate_batch)
            appended_events = self._event_store.append(candidate_batch)
            del appended_events
            updated_events = self._event_store.read_campaign(command.campaign_id)
            try:
                rebuild_projection(updated_events)
            except DomainEventValidationError:
                raise StoreError("recovery_identity_mismatch") from None
            status = project_turn_status(latest.turn_id, updated_events)
            response = _strict_response(
                self._undo_response_rebuilder(
                    command,
                    updated_events,
                    status,
                    latest.turn_id,
                    revert_event_id,
                )
            )
            return RevertedTurnResult(
                target_turn_id=latest.turn_id,
                revert_event_id=revert_event_id,
                response=response,
            )
        finally:
            if boundary_entered:
                self._event_boundary_lock.__exit__(None, None, None)

    def _validate_batch_for_revert(
        self,
        campaign_events: tuple[DomainEvent, ...],
        candidate_batch: EventBatch,
    ) -> None:
        virtual_events = validate_and_materialize_candidate(campaign_events, candidate_batch)
        candidate_events = virtual_events[len(campaign_events) :]
        if len(candidate_events) != 1 or not isinstance(candidate_events[0], TurnRevertedEvent):
            raise StoreError("undo_conflict")
        try:
            project_turn_status(candidate_events[0].payload.target_turn_id, virtual_events)
        except DomainEventValidationError:
            raise StoreError("undo_conflict") from None


__all__ = (
    "ActiveTurnAcquisition",
    "ActiveTurnRegistry",
    "ActiveTurnToken",
    "ExistingActiveTurn",
    "OwnedActiveTurn",
    "TurnLifecycleCoordinator",
    "build_crash_recovery_batch",
    "build_recovery_metadata",
    "build_revert_event",
    "build_turn_event_batch",
    "derive_recovery_event_id",
    "derive_revert_event_id",
    "matches_current_turn_identity",
    "reserve_recovery_event_ids",
    "select_latest_committed_turn",
    "select_response_payload",
    "validate_and_materialize_candidate",
)
