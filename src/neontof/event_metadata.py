"""未採番Event draftとTurn lifecycle metadataのneutral contract。"""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import StrictBytes, StrictStr

from neontof.contracts.base import ContractModel
from neontof.contracts.domain import DomainEvent
from neontof.contracts.ids import (
    CampaignId,
    EventId,
    OccurredAt,
    SceneId,
    SessionId,
    TurnId,
    TurnRequestId,
    Visibility,
)

RawEventPayloadJson: TypeAlias = StrictBytes  # noqa: UP040


class EventAppendMetadata(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    occurred_at: OccurredAt


class EventDraftBody(ContractModel):
    """Event Storeへsequenceを割り当てる前のwire envelope。"""

    type: StrictStr
    event_id: EventId
    event_version: Literal[1]
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    occurred_at: OccurredAt
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility
    payload_json: RawEventPayloadJson


class EventDraft(ContractModel):
    body: EventDraftBody


class EventBatch(ContractModel):
    campaign_id: CampaignId
    drafts: tuple[EventDraft, ...]


class StoredEvent(ContractModel):
    campaign_id: CampaignId
    sequence: int
    event: DomainEvent


class TurnEventMetadata(EventAppendMetadata):
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    root_turn_request_id: TurnRequestId
    event_ids: tuple[EventId, ...]


class RevertEventMetadata(EventAppendMetadata):
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    event_ids: tuple[EventId, ...]


EventMaterializationInput: TypeAlias = TurnEventMetadata  # noqa: UP040
