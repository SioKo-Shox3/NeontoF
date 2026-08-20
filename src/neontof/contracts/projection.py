"""Pure Event-log reducer and immutable State Projection contracts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import StrictInt, ValidationError

from neontof.contracts.base import ContractModel, FrozenJsonValue
from neontof.contracts.domain import (
    CampaignCreatedEvent,
    CharacterMovedEvent,
    ClockAdvancedEvent,
    DomainEvent,
    FactAssertedEvent,
    FactSupersededEvent,
    ResourceChangedEvent,
    SceneEndedEvent,
    SceneStartedEvent,
    SessionEndedEvent,
    SessionStartedEvent,
    TurnCommittedEvent,
    TurnRevertedEvent,
    revalidate_domain_event,
)
from neontof.contracts.event_parser import DomainEventValidationError, DomainEventValidationIssue
from neontof.contracts.ids import (
    CampaignId,
    CharacterId,
    ClockId,
    EntityId,
    EventId,
    FactHolder,
    FactId,
    FactKind,
    LocationId,
    ResourceId,
    ScenarioId,
    SceneEndReason,
    SceneId,
    SessionEndReason,
    SessionId,
    TurnId,
    Visibility,
)


class ResourceState(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    value: StrictInt


class CharacterLocation(ContractModel):
    character_id: CharacterId
    location_id: LocationId | None


class ClockState(ContractModel):
    clock_id: ClockId
    value: StrictInt


class FactRecord(ContractModel):
    fact_id: FactId
    event_id: EventId
    kind: FactKind
    holder: FactHolder
    subject_id: EntityId | None
    predicate: str
    value: FrozenJsonValue
    visibility: Visibility
    status: Literal["active", "superseded"]


class Projection(ContractModel):
    campaign_id: CampaignId | None
    campaign_name: str | None
    session_id: SessionId | None
    scenario_id: ScenarioId | None
    session_title: str | None
    scene_id: SceneId | None
    scene_label: str | None
    scene_end_reason: SceneEndReason | None
    session_end_reason: SessionEndReason | None
    resources: tuple[ResourceState, ...]
    locations: tuple[CharacterLocation, ...]
    clocks: tuple[ClockState, ...]
    facts: tuple[FactRecord, ...]
    reverted_turn_ids: frozenset[TurnId]
    applied_through_sequence: StrictInt
    audit_event_ids: tuple[EventId, ...]


def derive_fact_id(event_id: EventId, ordinal: int) -> FactId:
    """Derive a stable Fact ID from its asserting Event and zero-based ordinal."""

    if (
        type(event_id) is not str
        or re.fullmatch(r"^event:[a-z0-9]+(?:-[a-z0-9]+)*$", event_id) is None
    ):
        raise ValueError("event_id must be a valid EventId")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("ordinal must be a non-negative strict integer")
    preimage = (
        b"neontof:fact-id:v1\0" + event_id.encode("ascii") + b"\0" + str(ordinal).encode("ascii")
    )
    digest = hashlib.sha256(preimage).hexdigest()
    return f"fact:{digest}:{ordinal}"


def _issue(
    path: str, code: Literal["schema", "invalid_sequence", "invalid_payload"], message: str
) -> DomainEventValidationIssue:
    return DomainEventValidationIssue(path=path, code=code, message=message)


def _validate_revert_targets(
    events: tuple[DomainEvent, ...],
) -> tuple[DomainEventValidationIssue, ...]:
    committed_turn_counts: dict[TurnId, int] = {}
    reverted_turns: set[TurnId] = set()
    last_committed_turn_id: TurnId | None = None
    issues: list[DomainEventValidationIssue] = []
    for index, event in enumerate(events):
        if isinstance(event, TurnCommittedEvent) and event.turn_id is not None:
            committed_turn_counts[event.turn_id] = committed_turn_counts.get(event.turn_id, 0) + 1
            last_committed_turn_id = event.turn_id
        elif isinstance(event, TurnRevertedEvent):
            target = event.payload.target_turn_id
            committed_count = committed_turn_counts.get(target, 0)
            if committed_count == 0:
                issues.append(
                    _issue(
                        f"events[{index}].payload.target_turn_id",
                        "invalid_sequence",
                        "revert target must have a prior committed turn",
                    )
                )
            elif committed_count != 1:
                issues.append(
                    _issue(
                        f"events[{index}].payload.target_turn_id",
                        "invalid_sequence",
                        "revert target must have exactly one prior committed turn",
                    )
                )
            if last_committed_turn_id is not None and target != last_committed_turn_id:
                issues.append(
                    _issue(
                        f"events[{index}].payload.target_turn_id",
                        "invalid_sequence",
                        "revert target must be the most recently committed turn",
                    )
                )
            if target in reverted_turns:
                issues.append(
                    _issue(
                        f"events[{index}].payload.target_turn_id",
                        "invalid_sequence",
                        "a turn may be reverted only once",
                    )
                )
            reverted_turns.add(target)
    return tuple(issues)


def _validate_canonical_events(events: Sequence[DomainEvent]) -> tuple[DomainEvent, ...]:
    """Validate typed Event values before any reducer or status filter runs."""

    values = tuple(events)
    validated: list[DomainEvent] = []
    issues: list[DomainEventValidationIssue] = []
    for index, event in enumerate(values):
        try:
            validated.append(revalidate_domain_event(event))
        except ValidationError:
            issues.append(
                _issue(
                    f"events[{index}]",
                    "schema",
                    "event failed strict validation",
                )
            )
        except RecursionError, TypeError, ValueError:
            issues.append(
                _issue(
                    f"events[{index}]",
                    "schema",
                    "event failed strict validation",
                )
            )

    if len(validated) == len(values):
        expected_sequences = tuple(range(1, len(validated) + 1))
        actual_sequences = tuple(event.sequence for event in validated)
        if actual_sequences != expected_sequences:
            issues.append(
                _issue(
                    "sequence", "invalid_sequence", "event sequence must start at 1 without gaps"
                )
            )
        event_ids = tuple(event.event_id for event in validated)
        if len(event_ids) != len(set(event_ids)):
            issues.append(_issue("event_id", "invalid_sequence", "event IDs must be unique"))
        campaigns = {event.campaign_id for event in validated}
        if len(campaigns) > 1:
            issues.append(
                _issue("campaign_id", "invalid_sequence", "event campaign IDs must match")
            )
        issues.extend(_validate_revert_targets(tuple(validated)))

    if issues:
        raise DomainEventValidationError(tuple(issues)) from None
    return tuple(validated)


def rebuild_projection(events: Sequence[DomainEvent]) -> Projection:
    """Rebuild the immutable Projection using input sequence order as authority."""

    canonical_events = _validate_canonical_events(events)
    reverted_turns = {
        event.payload.target_turn_id
        for event in canonical_events
        if isinstance(event, TurnRevertedEvent)
    }

    campaign_id: CampaignId | None = None
    campaign_name: str | None = None
    session_id: SessionId | None = None
    scenario_id: ScenarioId | None = None
    session_title: str | None = None
    scene_id: SceneId | None = None
    scene_label: str | None = None
    scene_end_reason: SceneEndReason | None = None
    session_end_reason: SessionEndReason | None = None
    resources: dict[tuple[ResourceId, EntityId], int] = {}
    locations: dict[CharacterId, LocationId | None] = {}
    clocks: dict[ClockId, int] = {}
    facts: dict[FactId, FactRecord] = {}

    for event in canonical_events:
        if event.turn_id is not None and event.turn_id in reverted_turns:
            continue
        if isinstance(event, CampaignCreatedEvent):
            campaign_id = event.campaign_id
            campaign_name = event.payload.name
        elif isinstance(event, SessionStartedEvent):
            session_id = event.session_id
            scenario_id = event.payload.scenario_id
            session_title = event.payload.title
        elif isinstance(event, SceneStartedEvent):
            scene_id = event.scene_id
            scene_label = event.payload.label
            scene_end_reason = None
        elif isinstance(event, SceneEndedEvent):
            scene_end_reason = event.payload.reason
        elif isinstance(event, ResourceChangedEvent):
            key = (event.payload.resource_id, event.payload.entity_id)
            resources[key] = resources.get(key, 0) + event.payload.delta
        elif isinstance(event, CharacterMovedEvent):
            character_id = event.payload.character_id
            current_location = locations.get(character_id)
            if current_location != event.payload.from_location_id:
                issue = _issue(
                    f"events[{event.sequence - 1}].payload.from_location_id",
                    "invalid_payload",
                    "character movement source does not match projection",
                )
                raise DomainEventValidationError((issue,)) from None
            locations[character_id] = event.payload.to_location_id
        elif isinstance(event, ClockAdvancedEvent):
            clock_id = event.payload.clock_id
            clocks[clock_id] = clocks.get(clock_id, 0) + event.payload.delta
        elif isinstance(event, FactAssertedEvent):
            fact_id = derive_fact_id(event.event_id, 0)
            facts[fact_id] = FactRecord(
                fact_id=fact_id,
                event_id=event.event_id,
                kind=event.payload.kind,
                holder=event.payload.holder,
                subject_id=event.payload.subject_id,
                predicate=event.payload.predicate,
                value=event.payload.value,
                visibility=event.visibility,
                status="active",
            )
        elif isinstance(event, FactSupersededEvent):
            target = event.payload.target_fact_id
            fact = facts.get(target)
            if fact is None:
                issue = _issue(
                    f"events[{event.sequence - 1}].payload.target_fact_id",
                    "invalid_payload",
                    "fact supersession target does not exist",
                )
                raise DomainEventValidationError((issue,)) from None
            facts[target] = FactRecord(
                fact_id=fact.fact_id,
                event_id=fact.event_id,
                kind=fact.kind,
                holder=fact.holder,
                subject_id=fact.subject_id,
                predicate=fact.predicate,
                value=fact.value,
                visibility=fact.visibility,
                status="superseded",
            )
        elif isinstance(event, SessionEndedEvent):
            session_end_reason = event.payload.reason

    resource_values = tuple(
        ResourceState(resource_id=resource_id, entity_id=entity_id, value=value)
        for (resource_id, entity_id), value in sorted(resources.items())
    )
    location_values = tuple(
        CharacterLocation(character_id=character_id, location_id=location_id)
        for character_id, location_id in sorted(locations.items())
    )
    clock_values = tuple(
        ClockState(clock_id=clock_id, value=value) for clock_id, value in sorted(clocks.items())
    )
    fact_values = tuple(facts[fact_id] for fact_id in sorted(facts))
    return Projection(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        session_id=session_id,
        scenario_id=scenario_id,
        session_title=session_title,
        scene_id=scene_id,
        scene_label=scene_label,
        scene_end_reason=scene_end_reason,
        session_end_reason=session_end_reason,
        resources=resource_values,
        locations=location_values,
        clocks=clock_values,
        facts=fact_values,
        reverted_turn_ids=frozenset(reverted_turns),
        applied_through_sequence=canonical_events[-1].sequence if canonical_events else 0,
        audit_event_ids=tuple(event.event_id for event in canonical_events),
    )
