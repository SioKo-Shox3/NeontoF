"""Strict v1 Scenario authoring contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, TypeAdapter, field_validator, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import (
    ClockId,
    ClueId,
    EndConditionId,
    InvariantId,
    LocationId,
    NpcId,
    ScenarioId,
    SceneId,
    SecretId,
    Visibility,
)


def _copy_exact_yaml_sequence(value: object) -> object:
    """Copy only a builtin list or tuple into a fresh tuple."""

    if isinstance(value, list) and type(value) is list:
        return tuple(item for item in value)
    if isinstance(value, tuple) and type(value) is tuple:
        return tuple(item for item in value)
    raise ValueError("sequence must be an exact list or tuple")


class ScenarioText(ContractModel):
    text: str
    visibility: Visibility


class SceneDefinition(ContractModel):
    id: SceneId
    location_id: LocationId
    npc_ids: Annotated[
        tuple[NpcId, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    objective: ScenarioText


class LocationDefinition(ContractModel):
    id: LocationId
    canonical_name: str
    description: str
    visibility: Visibility


class NpcDefinition(ContractModel):
    id: NpcId
    canonical_name: str
    aliases: Annotated[
        tuple[str, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    goal: ScenarioText
    knowledge: Annotated[
        tuple[ScenarioText, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]


class WorldInvariant(ContractModel):
    id: InvariantId
    statement: str
    visibility: Visibility


class SecretDefinition(ContractModel):
    id: SecretId
    text: str
    visibility: Literal["gm_only"]


class ClueDefinition(ContractModel):
    id: ClueId
    text: str
    location_ids: Annotated[
        tuple[LocationId, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    visibility: Visibility


class ClockDefinition(ContractModel):
    id: ClockId
    label: str
    segments: int
    initial: int
    visibility: Visibility


class CluesDiscoveredEndCondition(ContractModel):
    type: Literal["clues_discovered"]
    id: EndConditionId
    outcome: Literal["success", "failure"]
    clue_ids: Annotated[
        tuple[ClueId, ClueId, ClueId],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    visibility: Visibility


class ClockReachedEndCondition(ContractModel):
    type: Literal["clock_reached"]
    id: EndConditionId
    outcome: Literal["success", "failure"]
    clock_id: ClockId
    value: int
    visibility: Visibility


type EndCondition = Annotated[
    CluesDiscoveredEndCondition | ClockReachedEndCondition,
    Field(discriminator="type"),
]
END_CONDITION_ADAPTER: TypeAdapter[EndCondition] = TypeAdapter(EndCondition)


class ScenarioV1(ContractModel):
    schema_version: Literal[1]
    id: ScenarioId
    version: str
    initial_scene: SceneDefinition
    locations: Annotated[
        tuple[LocationDefinition, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
        Field(min_length=4, max_length=6),
    ]
    npcs: Annotated[
        tuple[NpcDefinition, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
        Field(min_length=3, max_length=4),
    ]
    world_invariants: Annotated[
        tuple[WorldInvariant, ...],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    secret: SecretDefinition
    clues: Annotated[
        tuple[ClueDefinition, ClueDefinition, ClueDefinition],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]
    clock: ClockDefinition
    end_conditions: Annotated[
        tuple[EndCondition, EndCondition],
        BeforeValidator(_copy_exact_yaml_sequence),
    ]

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be the strict integer 1")
        return value

    @model_validator(mode="after")
    def _validate_end_condition_outcomes(self) -> Self:
        outcomes = tuple(condition.outcome for condition in self.end_conditions)
        if outcomes.count("success") != 1 or outcomes.count("failure") != 1:
            raise ValueError("end_conditions must contain one success and one failure")

        location_ids = {location.id for location in self.locations}
        if len(location_ids) != len(self.locations):
            raise ValueError("locations must not contain duplicate ids")

        npc_ids = {npc.id for npc in self.npcs}
        if len(npc_ids) != len(self.npcs):
            raise ValueError("npcs must not contain duplicate ids")

        invariant_ids = {invariant.id for invariant in self.world_invariants}
        if len(invariant_ids) != len(self.world_invariants):
            raise ValueError("world_invariants must not contain duplicate ids")

        clue_ids = {clue.id for clue in self.clues}
        if len(clue_ids) != len(self.clues):
            raise ValueError("clues must not contain duplicate ids")

        end_condition_ids = {condition.id for condition in self.end_conditions}
        if len(end_condition_ids) != len(self.end_conditions):
            raise ValueError("end_conditions must not contain duplicate ids")

        if self.initial_scene.location_id not in location_ids:
            raise ValueError("initial_scene.location_id must reference a location")
        if len(set(self.initial_scene.npc_ids)) != len(self.initial_scene.npc_ids):
            raise ValueError("initial_scene.npc_ids must not contain duplicate references")
        if not all(npc_id in npc_ids for npc_id in self.initial_scene.npc_ids):
            raise ValueError("initial_scene.npc_ids must reference existing NPCs")

        for clue in self.clues:
            if len(set(clue.location_ids)) != len(clue.location_ids):
                raise ValueError("clue.location_ids must not contain duplicate references")
            if not all(location_id in location_ids for location_id in clue.location_ids):
                raise ValueError("clue.location_ids must reference existing locations")

        for condition in self.end_conditions:
            if isinstance(condition, CluesDiscoveredEndCondition):
                if len(set(condition.clue_ids)) != len(condition.clue_ids):
                    raise ValueError("end condition clue_ids must not contain duplicate references")
                if not all(clue_id in clue_ids for clue_id in condition.clue_ids):
                    raise ValueError("end condition clue_ids must reference existing clues")
            elif condition.clock_id != self.clock.id:
                raise ValueError("end condition clock_id must reference the scenario clock")

        return self


SCENARIO_ADAPTER: TypeAdapter[ScenarioV1] = TypeAdapter(ScenarioV1)
