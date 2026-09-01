"""Normalize validated authoring documents into the initial Event batch."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import TypeAdapter, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.character_sheet import CharacterSheetV1
from neontof.contracts.domain import FactAssertedPayload, NonEmptyString
from neontof.contracts.ids import (
    VISIBILITY_ADAPTER,
    CampaignId,
    CharacterId,
    ClueId,
    EntityId,
    EventId,
    ItemId,
    LowercaseSha256,
    OccurredAt,
    SceneId,
    SecretId,
    SessionId,
    TurnId,
    TurnRequestId,
    Visibility,
)
from neontof.contracts.scenario import ScenarioV1
from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody

_SCENE_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(SceneId)
_ENTITY_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(EntityId)
_ITEM_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(ItemId)
_SECRET_ID_ADAPTER: TypeAdapter[str] = TypeAdapter(SecretId)


class BootstrapInput(ContractModel):
    """Server-owned, validated input for one initial campaign Event batch."""

    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    campaign_seed: LowercaseSha256
    campaign_name: NonEmptyString
    session_title: NonEmptyString
    scene_label: NonEmptyString
    character: CharacterSheetV1
    scenario: ScenarioV1

    @model_validator(mode="after")
    def validate_scene_id(self) -> Self:
        if self.scene_id != self.scenario.initial_scene.id:
            raise ValueError("scene_id must match scenario.initial_scene.id")
        return self

    @model_validator(mode="after")
    def validate_input_digest(self) -> Self:
        expected = derive_bootstrap_input_digest(
            campaign_id=self.campaign_id,
            session_id=self.session_id,
            scene_id=self.scene_id,
            turn_id=self.turn_id,
            turn_request_id=self.turn_request_id,
            campaign_seed=self.campaign_seed,
            campaign_name=self.campaign_name,
            session_title=self.session_title,
            scene_label=self.scene_label,
        )
        if self.input_digest != expected:
            raise ValueError("input_digest does not match server-owned bootstrap input")
        return self


def derive_bootstrap_input_digest(
    *,
    campaign_id: CampaignId,
    session_id: SessionId,
    scene_id: SceneId,
    turn_id: TurnId,
    turn_request_id: TurnRequestId,
    campaign_seed: LowercaseSha256,
    campaign_name: NonEmptyString,
    session_title: NonEmptyString,
    scene_label: NonEmptyString,
) -> LowercaseSha256:
    """Derive the stable digest from the fixed server-owned input preimage."""

    values = (
        campaign_id,
        session_id,
        scene_id,
        turn_id,
        turn_request_id,
        campaign_seed,
        campaign_name,
        session_title,
        scene_label,
    )
    preimage = b"neontof/bootstrap-input/v1\0" + b"\0".join(
        value.encode("utf-8") for value in values
    )
    return hashlib.sha256(preimage).hexdigest()


def _stable_suffix(value: str) -> str:
    return value.split(":", 1)[1].lower()


def derive_bootstrap_event_ids(input_value: BootstrapInput) -> tuple[EventId, ...]:
    """Derive ordered, server-owned Event IDs for the bootstrap batch."""

    count = 16 + len(input_value.character.initial_items)
    if input_value.scenario.clock.initial > 0:
        count += 1
    prefix = (
        f"event:bootstrap-{_stable_suffix(input_value.campaign_id)}-"
        f"{_stable_suffix(input_value.turn_id)}-"
    )
    return tuple(f"{prefix}{ordinal}" for ordinal in range(1, count + 1))


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
    session_id: SessionId | None,
    scene_id: SceneId | None,
    turn_id: TurnId | None,
    occurred_at: OccurredAt,
    payload: object,
    visibility: Visibility = "player_visible",
) -> EventDraft:
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
            origin="in_world",
            visibility=visibility,
            payload_json=_json_bytes(payload),
        )
    )


def _entity_for_character(character_id: CharacterId) -> EntityId:
    return f"entity:character-{_stable_suffix(character_id)}"


def _entity_for_clue(clue_id: ClueId) -> EntityId:
    return f"entity:clue-{_stable_suffix(clue_id)}"


def _validate_id(adapter: TypeAdapter[str], value: object) -> bool:
    try:
        adapter.validate_python(value, strict=True)
    except TypeError, ValueError:
        return False
    return True


def _is_character_entity(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("entity:character-")
        and _validate_id(_ENTITY_ID_ADAPTER, value)
    )


def _is_clue_entity(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("entity:clue-")
        and _validate_id(_ENTITY_ID_ADAPTER, value)
    )


def _validate_bootstrap_fact(
    *,
    payload: FactAssertedPayload,
    visibility: Visibility,
) -> None:
    """Enforce the closed bootstrap Fact predicate/value allowlist."""

    if payload.kind != "fact":
        raise ValueError("bootstrap facts must use kind fact")
    try:
        VISIBILITY_ADAPTER.validate_python(visibility, strict=True)
    except TypeError, ValueError:
        raise ValueError("invalid bootstrap fact visibility") from None

    common_world = payload.holder == "world" and payload.subject_id is None
    common_character = payload.holder == "player_character" and _is_character_entity(
        payload.subject_id
    )
    if payload.predicate == "inventory_item":
        if (
            not common_character
            or visibility != "player_visible"
            or not _validate_id(_ITEM_ID_ADAPTER, payload.value)
        ):
            raise ValueError("invalid inventory_item bootstrap fact")
    elif payload.predicate == "character_schema_version":
        if not common_character or visibility != "player_visible":
            raise ValueError("invalid character_schema_version bootstrap fact")
        if type(payload.value) is not int or payload.value != 1:
            raise ValueError("invalid character schema version")
    elif payload.predicate == "objective":
        if (
            not common_world
            or visibility != "player_visible"
            or not _validate_id(_SCENE_ID_ADAPTER, payload.value)
        ):
            raise ValueError("invalid objective bootstrap fact")
    elif payload.predicate == "scenario_version":
        if not common_world or visibility != "player_visible" or type(payload.value) is not str:
            raise ValueError("invalid scenario_version bootstrap fact")
    elif payload.predicate == "secret":
        if (
            not common_world
            or visibility != "gm_only"
            or not _validate_id(_SECRET_ID_ADAPTER, payload.value)
        ):
            raise ValueError("invalid secret bootstrap fact")
    elif payload.predicate == "clue":
        if not common_world or not _is_clue_entity(payload.value):
            raise ValueError("invalid clue bootstrap fact")
    elif payload.predicate == "target_number":
        if not common_world or visibility != "player_visible":
            raise ValueError("invalid target_number bootstrap fact")
        if type(payload.value) is not int or not 2 <= payload.value <= 12:
            raise ValueError("invalid target number")
    elif payload.predicate == "condition":
        if not common_character or visibility != "player_visible":
            raise ValueError("invalid condition bootstrap fact")
        if type(payload.value) is not str or payload.value not in {"injured", "shaken"}:
            raise ValueError("invalid condition")
    elif payload.predicate == "scenario_outcome":
        if (
            not common_world
            or visibility != "player_visible"
            or type(payload.value) is not str
            or payload.value not in {"success", "failure"}
        ):
            raise ValueError("invalid scenario_outcome bootstrap fact")
    else:
        raise ValueError("unknown bootstrap fact predicate")


def build_bootstrap_events(
    input_value: BootstrapInput,
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
) -> EventBatch:
    """Build the ordered bootstrap Event drafts without assigning sequences."""

    ids = tuple(event_ids)
    expected_count = 16 + len(input_value.character.initial_items)
    if input_value.scenario.clock.initial > 0:
        expected_count += 1
    if len(ids) != expected_count or len(ids) != len(set(ids)):
        raise ValueError("bootstrap Event ID count does not match the Event batch")

    drafts: list[EventDraft] = []
    cursor = 0

    def append_draft(
        *,
        event_type: str,
        campaign_id: CampaignId,
        session_id: SessionId | None,
        scene_id: SceneId | None,
        turn_id: TurnId | None,
        occurred_at: OccurredAt,
        payload: object,
        visibility: Visibility = "player_visible",
    ) -> None:
        nonlocal cursor
        drafts.append(
            _draft(
                event_id=ids[cursor],
                event_type=event_type,
                campaign_id=campaign_id,
                session_id=session_id,
                scene_id=scene_id,
                turn_id=turn_id,
                occurred_at=occurred_at,
                payload=payload,
                visibility=visibility,
            )
        )
        cursor += 1

    append_draft(
        event_type="CampaignCreated",
        campaign_id=input_value.campaign_id,
        session_id=None,
        scene_id=None,
        turn_id=None,
        occurred_at=occurred_at,
        payload={"name": input_value.campaign_name},
    )
    append_draft(
        event_type="SessionStarted",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=None,
        turn_id=None,
        occurred_at=occurred_at,
        payload={"scenario_id": input_value.scenario.id, "title": input_value.session_title},
    )
    append_draft(
        event_type="SceneStarted",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=None,
        occurred_at=occurred_at,
        payload={"label": input_value.scene_label},
    )
    append_draft(
        event_type="PlayerInputAccepted",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={
            "turn_request_id": input_value.turn_request_id,
            "input_digest": input_value.input_digest,
        },
    )
    append_draft(
        event_type="TurnResumed",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={"turn_request_id": input_value.turn_request_id},
    )
    character_entity = _entity_for_character(input_value.character.id)
    append_draft(
        event_type="ResourceChanged",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={
            "resource_id": "resource:hp",
            "entity_id": character_entity,
            "delta": input_value.character.hp.current,
        },
    )
    append_draft(
        event_type="ResourceChanged",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={
            "resource_id": input_value.character.resource.id,
            "entity_id": character_entity,
            "delta": input_value.character.resource.current,
        },
    )
    append_draft(
        event_type="CharacterMoved",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={
            "character_id": input_value.character.id,
            "from_location_id": None,
            "to_location_id": input_value.character.initial_location_id,
        },
    )
    if input_value.scenario.clock.initial > 0:
        append_draft(
            event_type="ClockAdvanced",
            campaign_id=input_value.campaign_id,
            session_id=input_value.session_id,
            scene_id=input_value.scene_id,
            turn_id=input_value.turn_id,
            occurred_at=occurred_at,
            payload={
                "clock_id": input_value.scenario.clock.id,
                "delta": input_value.scenario.clock.initial,
            },
        )

    for item in input_value.character.initial_items:
        drafts.append(
            _fact_draft_at(
                event_id=ids[cursor],
                input_value=input_value,
                occurred_at=occurred_at,
                predicate="inventory_item",
                value=item.id,
                holder="player_character",
                subject_id=character_entity,
                visibility="player_visible",
            )
        )
        cursor += 1
    drafts.append(
        _fact_draft_at(
            event_id=ids[cursor],
            input_value=input_value,
            occurred_at=occurred_at,
            predicate="character_schema_version",
            value=input_value.character.schema_version,
            holder="player_character",
            subject_id=character_entity,
            visibility="player_visible",
        )
    )
    cursor += 1
    drafts.append(
        _fact_draft_at(
            event_id=ids[cursor],
            input_value=input_value,
            occurred_at=occurred_at,
            predicate="objective",
            value=input_value.scenario.initial_scene.id,
            holder="world",
            subject_id=None,
            visibility="player_visible",
        )
    )
    cursor += 1
    drafts.append(
        _fact_draft_at(
            event_id=ids[cursor],
            input_value=input_value,
            occurred_at=occurred_at,
            predicate="scenario_version",
            value=input_value.scenario.version,
            holder="world",
            subject_id=None,
            visibility="player_visible",
        )
    )
    cursor += 1
    drafts.append(
        _fact_draft_at(
            event_id=ids[cursor],
            input_value=input_value,
            occurred_at=occurred_at,
            predicate="secret",
            value=input_value.scenario.secret.id,
            holder="world",
            subject_id=None,
            visibility="gm_only",
        )
    )
    cursor += 1
    for clue in input_value.scenario.clues:
        drafts.append(
            _fact_draft_at(
                event_id=ids[cursor],
                input_value=input_value,
                occurred_at=occurred_at,
                predicate="clue",
                value=_entity_for_clue(clue.id),
                holder="world",
                subject_id=None,
                visibility=clue.visibility,
            )
        )
        cursor += 1

    append_draft(
        event_type="TurnCommitted",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=input_value.scene_id,
        turn_id=input_value.turn_id,
        occurred_at=occurred_at,
        payload={"turn_request_id": input_value.turn_request_id},
    )
    if cursor != len(ids):
        raise ValueError("bootstrap Event ID cursor did not consume the Event batch")
    return EventBatch(campaign_id=input_value.campaign_id, drafts=tuple(drafts))


def _fact_draft_at(
    *,
    event_id: EventId,
    input_value: BootstrapInput,
    occurred_at: OccurredAt,
    predicate: str,
    value: object,
    holder: Literal["world", "player_character"],
    subject_id: EntityId | None,
    visibility: Visibility,
) -> EventDraft:
    payload = FactAssertedPayload(
        kind="fact",
        holder=holder,
        subject_id=subject_id,
        predicate=predicate,
        value=value,
    )
    _validate_bootstrap_fact(payload=payload, visibility=visibility)
    return _draft(
        event_id=event_id,
        event_type="FactAsserted",
        campaign_id=input_value.campaign_id,
        session_id=input_value.session_id,
        scene_id=None,
        turn_id=None,
        occurred_at=occurred_at,
        payload=payload.model_dump(),
        visibility=visibility,
    )


__all__ = (
    "BootstrapInput",
    "build_bootstrap_events",
    "derive_bootstrap_event_ids",
    "derive_bootstrap_input_digest",
)
