"""Persistence contracts for durable turn request coordination."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import Field, StrictBytes, StrictInt, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import (
    CampaignId,
    EventId,
    LowercaseSha256,
    OccurredAt,
    SceneId,
    SessionId,
    TurnId,
    TurnRequestId,
)

RequestKind = Literal["submit", "resume"]
RequestCompletionStatus = Literal["awaiting_player", "committed", "aborted"]
RequestedMediaType = Literal["application/json", "text/event-stream"]
RecoveryReason = Literal[
    "claim_before_first_event",
    "after_player_input_accepted",
    "after_turn_resumed",
    "after_turn_awaiting_player",
    "after_terminal",
]
RecoverySelector = Literal[
    "no_lifecycle_events",
    "accepted_without_terminal",
    "resumed_without_terminal",
    "awaiting_player",
    "terminal",
]
StoreErrorCode = Literal[
    "request_key_conflict",
    "turn_already_processing",
    "request_not_found",
    "request_not_processing",
    "stage_conflict",
    "response_conflict",
    "invalid_record",
    "store_integrity_error",
    "invalid_response",
    "turn_not_found",
    "turn_not_in_session",
    "undo_conflict",
    "recovery_identity_mismatch",
]
OpaqueRequestKey = Annotated[StrictBytes, Field(min_length=1, max_length=256)]
RequestKey = OpaqueRequestKey
NonEmptyBytes = Annotated[StrictBytes, Field(min_length=1)]


class StoreError(ValueError):
    """Sanitized, stable failure from the turn request store."""

    __slots__ = ("code",)

    code: StoreErrorCode

    def __init__(self, code: StoreErrorCode) -> None:
        self.code = code
        ValueError.__init__(self, code)


class CachedTurnResponse(ContractModel):
    status_code: Literal[200]
    media_type: RequestedMediaType
    body: NonEmptyBytes


class TurnRequestIdentity(ContractModel):
    request_key: OpaqueRequestKey
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    base_event_sequence: Annotated[StrictInt, Field(ge=0)]
    recovery_payload_version: Literal[1, 2]
    recovery_reason: RecoveryReason | None
    recovery_selector: RecoverySelector | None
    accepted_event_id: EventId | None
    resumed_event_id: EventId | None
    awaiting_player_event_id: EventId | None
    committed_event_id: EventId | None
    aborted_event_id: EventId | None
    recovery_aborted_event_id: EventId | None
    occurred_at: OccurredAt | None
    initial_recovery_payload: NonEmptyBytes
    staged_recovery_payload: NonEmptyBytes | None


class TurnRequestIntent(ContractModel):
    request_key: OpaqueRequestKey
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    initial_recovery_payload: NonEmptyBytes


class ProcessingTurnRequestRecord(TurnRequestIdentity):
    status: Literal["processing"]
    response: None


class FinalTurnRequestRecord(TurnRequestIdentity):
    status: RequestCompletionStatus
    response: CachedTurnResponse


CompletedTurnRequestRecord = FinalTurnRequestRecord

TurnRequestRecord = Annotated[
    ProcessingTurnRequestRecord | FinalTurnRequestRecord,
    Field(discriminator="status"),
]


class NewClaim(ContractModel):
    type: Literal["new"]
    record: ProcessingTurnRequestRecord


class ExistingProcessingClaim(ContractModel):
    type: Literal["existing_processing"]
    record: ProcessingTurnRequestRecord


class ExistingFinalClaim(ContractModel):
    type: Literal["existing_final"]
    record: FinalTurnRequestRecord


ClaimResult = Annotated[
    NewClaim | ExistingProcessingClaim | ExistingFinalClaim,
    Field(discriminator="type"),
]


class RecoveryEventMetadata(ContractModel):
    request_kind: RequestKind
    recovery_payload_version: Literal[1, 2]
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    recovery_reason: RecoveryReason
    recovery_selector: RecoverySelector
    occurred_at: OccurredAt
    accepted_event_id: EventId | None
    resumed_event_id: EventId | None
    awaiting_player_event_id: EventId | None
    committed_event_id: EventId | None
    aborted_event_id: EventId | None
    recovery_aborted_event_id: EventId | None
    event_ids: tuple[EventId, ...]

    @model_validator(mode="before")
    @classmethod
    def derive_event_ids(cls, values: Any) -> Any:
        if not isinstance(values, dict) or "event_ids" in values:
            return values
        copied = dict(values)
        copied["event_ids"] = tuple(
            event_id
            for event_id in (
                copied.get("accepted_event_id"),
                copied.get("resumed_event_id"),
                copied.get("awaiting_player_event_id"),
                copied.get("committed_event_id"),
                copied.get("aborted_event_id"),
                copied.get("recovery_aborted_event_id"),
            )
            if event_id is not None
        )
        return copied

    @model_validator(mode="after")
    def require_derived_event_ids(self) -> Self:
        expected = tuple(
            event_id
            for event_id in (
                self.accepted_event_id,
                self.resumed_event_id,
                self.awaiting_player_event_id,
                self.committed_event_id,
                self.aborted_event_id,
                self.recovery_aborted_event_id,
            )
            if event_id is not None
        )
        if self.event_ids != expected:
            raise ValueError("event_ids must be derived from role-specific event IDs")
        return self
