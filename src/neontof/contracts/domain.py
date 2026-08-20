"""Strict v1 Event envelopes, payloads, and the dice seed contract."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import Field, StrictInt, StringConstraints, TypeAdapter, model_validator

from neontof.contracts.base import ContractModel, FrozenJsonValue
from neontof.contracts.ids import (
    ActionId,
    CampaignId,
    CharacterId,
    ClockId,
    EntityId,
    EventId,
    FactHolder,
    FactId,
    FactKind,
    LocationId,
    LowercaseSha256,
    OccurredAt,
    ResourceId,
    ScenarioId,
    SceneEndReason,
    SceneId,
    SessionEndReason,
    SessionId,
    TelemetryId,
    TranscriptId,
    TurnId,
    TurnRequestId,
    Visibility,
)

type NonEmptyString = Annotated[str, StringConstraints(strict=True, min_length=1)]
type NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]
type PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]


def derive_dice_seed(
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: StrictInt,
) -> LowercaseSha256:
    """Derive a reproducible seed from the complete, ordered input tuple."""

    if type(roll_index) is not int or roll_index < 0:
        raise ValueError("roll_index must be a non-negative strict integer")
    preimage = (
        b"neontof:dice-seed:v1\0"
        + campaign_seed.encode("ascii")
        + b"\0"
        + turn_id.encode("ascii")
        + b"\0"
        + action_id.encode("ascii")
        + b"\0"
        + str(roll_index).encode("ascii")
    )
    return hashlib.sha256(preimage).hexdigest()


class CampaignCreatedPayload(ContractModel):
    name: NonEmptyString


class SessionStartedPayload(ContractModel):
    scenario_id: ScenarioId | None
    title: NonEmptyString


class SceneStartedPayload(ContractModel):
    label: NonEmptyString


class SceneEndedPayload(ContractModel):
    reason: SceneEndReason


class PlayerInputAcceptedPayload(ContractModel):
    turn_request_id: TurnRequestId
    input_digest: LowercaseSha256


class DiceRolledPayload(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    derived_seed: LowercaseSha256
    formula: NonEmptyString
    result: StrictInt


class ResourceChangedPayload(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    delta: StrictInt


class CharacterMovedPayload(ContractModel):
    character_id: CharacterId
    from_location_id: LocationId | None
    to_location_id: LocationId


class ClockAdvancedPayload(ContractModel):
    clock_id: ClockId
    delta: PositiveStrictInt


class FactAssertedPayload(ContractModel):
    kind: FactKind
    holder: FactHolder
    subject_id: EntityId | None
    predicate: NonEmptyString
    value: FrozenJsonValue


class FactSupersededPayload(ContractModel):
    target_fact_id: FactId


class TurnAwaitingPlayerPayload(ContractModel):
    turn_request_id: TurnRequestId


class TurnResumedPayload(ContractModel):
    turn_request_id: TurnRequestId


class TurnAbortedPayload(ContractModel):
    turn_request_id: TurnRequestId
    reason: Literal["failed", "cancelled", "table_correction"]


class TurnCommittedPayload(ContractModel):
    turn_request_id: TurnRequestId


class TurnRevertedPayload(ContractModel):
    target_turn_id: TurnId


class SessionEndedPayload(ContractModel):
    reason: SessionEndReason


class DomainEventBase(ContractModel):
    type: str
    event_id: EventId
    event_version: Literal[1]
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    sequence: StrictInt
    occurred_at: OccurredAt
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility
    payload: ContractModel

    @model_validator(mode="after")
    def validate_context(self) -> DomainEventBase:
        context = {
            "CampaignCreated": (False, False, False),
            "SessionStarted": (True, False, False),
            "SceneStarted": (True, True, False),
            "SceneEnded": (True, True, False),
            "PlayerInputAccepted": (True, True, True),
            "DiceRolled": (True, True, True),
            "ResourceChanged": (True, True, True),
            "CharacterMoved": (True, True, True),
            "ClockAdvanced": (True, True, True),
            "FactAsserted": (True, None, None),
            "FactSuperseded": (True, None, None),
            "TurnAwaitingPlayer": (True, True, True),
            "TurnResumed": (True, True, True),
            "TurnAborted": (True, True, True),
            "TurnCommitted": (True, True, True),
            "TurnReverted": (True, None, None),
            "SessionEnded": (True, False, False),
        }
        expected = context.get(self.type)
        if expected is None:
            raise ValueError("unknown event type")
        session_required, scene_required, turn_required = expected
        if (self.session_id is not None) is not session_required:
            raise ValueError("event context does not match type")
        if scene_required is True and self.scene_id is None:
            raise ValueError("event context does not match type")
        if scene_required is False and self.scene_id is not None:
            raise ValueError("event context does not match type")
        if turn_required is True and self.turn_id is None:
            raise ValueError("event context does not match type")
        if turn_required is False and self.turn_id is not None:
            raise ValueError("event context does not match type")
        return self


class CampaignCreatedEvent(DomainEventBase):
    type: Literal["CampaignCreated"]
    payload: CampaignCreatedPayload


class SessionStartedEvent(DomainEventBase):
    type: Literal["SessionStarted"]
    payload: SessionStartedPayload


class SceneStartedEvent(DomainEventBase):
    type: Literal["SceneStarted"]
    payload: SceneStartedPayload


class SceneEndedEvent(DomainEventBase):
    type: Literal["SceneEnded"]
    payload: SceneEndedPayload


class PlayerInputAcceptedEvent(DomainEventBase):
    type: Literal["PlayerInputAccepted"]
    payload: PlayerInputAcceptedPayload


class DiceRolledEvent(DomainEventBase):
    type: Literal["DiceRolled"]
    payload: DiceRolledPayload

    @model_validator(mode="after")
    def validate_derived_seed(self) -> DiceRolledEvent:
        if self.turn_id is not None:
            expected = derive_dice_seed(
                self.payload.campaign_seed,
                self.turn_id,
                self.payload.action_id,
                self.payload.roll_index,
            )
            if self.payload.derived_seed != expected:
                raise ValueError("derived_seed does not match dice seed inputs")
        return self


class ResourceChangedEvent(DomainEventBase):
    type: Literal["ResourceChanged"]
    payload: ResourceChangedPayload


class CharacterMovedEvent(DomainEventBase):
    type: Literal["CharacterMoved"]
    payload: CharacterMovedPayload


class ClockAdvancedEvent(DomainEventBase):
    type: Literal["ClockAdvanced"]
    payload: ClockAdvancedPayload


class FactAssertedEvent(DomainEventBase):
    type: Literal["FactAsserted"]
    payload: FactAssertedPayload


class FactSupersededEvent(DomainEventBase):
    type: Literal["FactSuperseded"]
    payload: FactSupersededPayload


class TurnAwaitingPlayerEvent(DomainEventBase):
    type: Literal["TurnAwaitingPlayer"]
    payload: TurnAwaitingPlayerPayload


class TurnResumedEvent(DomainEventBase):
    type: Literal["TurnResumed"]
    payload: TurnResumedPayload


class TurnAbortedEvent(DomainEventBase):
    type: Literal["TurnAborted"]
    payload: TurnAbortedPayload


class TurnCommittedEvent(DomainEventBase):
    type: Literal["TurnCommitted"]
    payload: TurnCommittedPayload


class TurnRevertedEvent(DomainEventBase):
    type: Literal["TurnReverted"]
    origin: Literal["table_correction"]
    payload: TurnRevertedPayload


class SessionEndedEvent(DomainEventBase):
    type: Literal["SessionEnded"]
    payload: SessionEndedPayload


type DomainEvent = (
    CampaignCreatedEvent
    | SessionStartedEvent
    | SceneStartedEvent
    | SceneEndedEvent
    | PlayerInputAcceptedEvent
    | DiceRolledEvent
    | ResourceChangedEvent
    | CharacterMovedEvent
    | ClockAdvancedEvent
    | FactAssertedEvent
    | FactSupersededEvent
    | TurnAwaitingPlayerEvent
    | TurnResumedEvent
    | TurnAbortedEvent
    | TurnCommittedEvent
    | TurnRevertedEvent
    | SessionEndedEvent
)


class TranscriptEntry(ContractModel):
    entry_id: TranscriptId
    text: NonEmptyString


class TelemetryEntry(ContractModel):
    entry_id: TelemetryId
    name: NonEmptyString


_DOMAIN_EVENT_ADAPTER: TypeAdapter[DomainEvent] = TypeAdapter(
    Annotated[DomainEvent, Field(discriminator="type")]
)


def revalidate_domain_event(event: DomainEvent) -> DomainEvent:
    """Re-run strict validation on typed values before a reducer consumes them."""

    return _DOMAIN_EVENT_ADAPTER.validate_python(event, strict=True)


# Short aliases keep the public names useful without introducing alternate models.
CampaignCreated = CampaignCreatedEvent
SessionStarted = SessionStartedEvent
SceneStarted = SceneStartedEvent
SceneEnded = SceneEndedEvent
PlayerInputAccepted = PlayerInputAcceptedEvent
DiceRolled = DiceRolledEvent
ResourceChanged = ResourceChangedEvent
CharacterMoved = CharacterMovedEvent
ClockAdvanced = ClockAdvancedEvent
FactAsserted = FactAssertedEvent
FactSuperseded = FactSupersededEvent
TurnAwaitingPlayer = TurnAwaitingPlayerEvent
TurnResumed = TurnResumedEvent
TurnAborted = TurnAbortedEvent
TurnCommitted = TurnCommittedEvent
TurnReverted = TurnRevertedEvent
SessionEnded = SessionEndedEvent
