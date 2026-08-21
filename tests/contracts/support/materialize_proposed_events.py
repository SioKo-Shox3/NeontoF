"""Test-only deterministic Semantic Result to Domain Event materializer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from neontof.contracts.semantic_result import (
        AcceptedSemanticResult,
        ProposedCharacterMoved,
        ProposedClockAdvanced,
        ProposedFact,
        ProposedResourceChanged,
    )
from pydantic import Field, StrictInt

from neontof.contracts.base import ContractModel
from neontof.contracts.domain import (
    CharacterMovedEvent,
    CharacterMovedPayload,
    ClockAdvancedEvent,
    ClockAdvancedPayload,
    DomainEvent,
    FactAssertedEvent,
    FactAssertedPayload,
    ResourceChangedEvent,
    ResourceChangedPayload,
)
from neontof.contracts.ids import (
    CampaignId,
    OccurredAt,
    SceneId,
    SessionId,
    TurnId,
    Visibility,
)


class FixtureEventContext(ContractModel):
    """Fixed envelope values used by the test-only Event materializer."""

    campaign: CampaignId
    session: SessionId
    scene: SceneId
    turn: TurnId
    sequence_start: StrictInt = Field(gt=0)
    occurred_at: OccurredAt
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility


def materialize_semantic_result_for_test(
    result: AcceptedSemanticResult,
    context: FixtureEventContext,
) -> tuple[DomainEvent, ...]:
    """Materialize only accepted state proposals into deterministic Domain Events."""

    from neontof.contracts.semantic_result import (
        AcceptedSemanticResult,
        ProposedCharacterMoved,
        ProposedClockAdvanced,
        ProposedFact,
        ProposedResourceChanged,
    )

    if not isinstance(result, AcceptedSemanticResult):
        raise TypeError("materializer requires AcceptedSemanticResult")

    proposals: tuple[
        ProposedResourceChanged | ProposedCharacterMoved | ProposedClockAdvanced | ProposedFact,
        ...,
    ] = tuple(result.value.proposed_events) + tuple(result.value.proposed_facts)
    materialized: list[DomainEvent] = []
    ordinal: int
    proposal: (
        ProposedResourceChanged | ProposedCharacterMoved | ProposedClockAdvanced | ProposedFact
    )
    for ordinal, proposal in enumerate(proposals):
        sequence: int = context.sequence_start + ordinal
        event_id = f"event:fixture-{sequence}"

        if isinstance(proposal, ProposedResourceChanged):
            materialized.append(
                ResourceChangedEvent(
                    type="ResourceChanged",
                    event_id=event_id,
                    event_version=1,
                    campaign_id=context.campaign,
                    session_id=context.session,
                    scene_id=context.scene,
                    turn_id=context.turn,
                    sequence=sequence,
                    occurred_at=context.occurred_at,
                    origin=context.origin,
                    visibility=context.visibility,
                    payload=ResourceChangedPayload(
                        resource_id=proposal.payload.resource_id,
                        entity_id=proposal.payload.entity_id,
                        delta=proposal.payload.delta,
                    ),
                )
            )
        elif isinstance(proposal, ProposedCharacterMoved):
            materialized.append(
                CharacterMovedEvent(
                    type="CharacterMoved",
                    event_id=event_id,
                    event_version=1,
                    campaign_id=context.campaign,
                    session_id=context.session,
                    scene_id=context.scene,
                    turn_id=context.turn,
                    sequence=sequence,
                    occurred_at=context.occurred_at,
                    origin=context.origin,
                    visibility=context.visibility,
                    payload=CharacterMovedPayload(
                        character_id=proposal.payload.character_id,
                        from_location_id=proposal.payload.from_location_id,
                        to_location_id=proposal.payload.to_location_id,
                    ),
                )
            )
        elif isinstance(proposal, ProposedClockAdvanced):
            materialized.append(
                ClockAdvancedEvent(
                    type="ClockAdvanced",
                    event_id=event_id,
                    event_version=1,
                    campaign_id=context.campaign,
                    session_id=context.session,
                    scene_id=context.scene,
                    turn_id=context.turn,
                    sequence=sequence,
                    occurred_at=context.occurred_at,
                    origin=context.origin,
                    visibility=context.visibility,
                    payload=ClockAdvancedPayload(
                        clock_id=proposal.payload.clock_id,
                        delta=proposal.payload.delta,
                    ),
                )
            )
        elif isinstance(proposal, ProposedFact):
            materialized.append(
                FactAssertedEvent(
                    type="FactAsserted",
                    event_id=event_id,
                    event_version=1,
                    campaign_id=context.campaign,
                    session_id=context.session,
                    scene_id=context.scene,
                    turn_id=context.turn,
                    sequence=sequence,
                    occurred_at=context.occurred_at,
                    origin=context.origin,
                    visibility=proposal.visibility,
                    payload=FactAssertedPayload(
                        kind=proposal.kind,
                        holder=proposal.holder,
                        subject_id=proposal.subject_id,
                        predicate=proposal.predicate,
                        value=proposal.value,
                    ),
                )
            )
        else:
            raise TypeError("unsupported Semantic Result proposal")

    return tuple(materialized)
