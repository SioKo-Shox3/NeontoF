"""Stable identifier grammars, visibility, and event metadata literals."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator, StringConstraints, TypeAdapter

type CampaignId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^campaign:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type SessionId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^session:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type SceneId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^scene:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type TurnId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^turn:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type TurnRequestId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^turn-request:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type EventId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^event:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type FactId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^fact:[0-9a-f]{64}:(0|[1-9][0-9]*)$")
]
type NpcId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^npc:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type EntityId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^entity:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type FactSubjectId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^fact-subject:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type CharacterId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^character:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type LocationId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^location:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ItemId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^item:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ClockId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^clock:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ResourceId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^resource:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ActionId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^action:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ScenarioId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^scenario:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type SecretId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^secret:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ClueId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^clue:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type InvariantId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^invariant:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type EndConditionId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^end-condition:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type TranscriptId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^transcript:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type TelemetryId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^telemetry:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type ModelCallId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^model-call:[a-z0-9]+(?:-[a-z0-9]+)*$")
]
type LowercaseSha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]

type Visibility = Literal["gm_only", "player_visible"] | NpcId
VISIBILITY_ADAPTER: TypeAdapter[Visibility] = TypeAdapter(Visibility)

type FactKind = Literal["fact", "ruling", "agreement", "plan", "promise"]
type FactHolder = Literal["world", "player_character", "rumor"] | NpcId
type SceneEndReason = Literal["completed", "aborted", "table_correction"]
type SessionEndReason = Literal["completed", "aborted", "table_correction"]


def validate_occurred_at(value: object) -> str:
    """Accept only an ASCII, second-precision UTC timestamp with a real date."""

    if (
        type(value) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None
    ):
        raise ValueError("occurred_at must be an ASCII UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("occurred_at must be an ASCII UTC timestamp") from None
    return value


type OccurredAt = Annotated[str, BeforeValidator(validate_occurred_at)]
