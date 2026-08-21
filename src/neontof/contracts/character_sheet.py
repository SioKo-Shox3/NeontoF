"""Validated Character Sheet contracts for the initial character snapshot."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, TypeAdapter, field_validator, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import CharacterId, ItemId, LocationId, ResourceId, Visibility

__all__ = (
    "CHARACTER_SHEET_ADAPTER",
    "CharacterRuleset",
    "CharacterSheetV1",
    "HitPoints",
    "InitialItem",
    "ResourceState",
    "SpeechStyle",
)


def _copy_exact_yaml_sequence(value: object) -> object:
    """Copy built-in list/tuple inputs to a fresh tuple to block input aliasing/mutation.

    Reject generators and arbitrary Iterables so the contract is not loosened implicitly.
    """

    if isinstance(value, list):
        if type(value) is not list:
            raise ValueError("sequence must be an exact list or tuple")
        return tuple(item for item in value)
    if isinstance(value, tuple):
        if type(value) is not tuple:
            raise ValueError("sequence must be an exact list or tuple")
        return tuple(item for item in value)
    raise ValueError("sequence must be an exact list or tuple")


type _ExactStringSequence = Annotated[tuple[str, ...], BeforeValidator(_copy_exact_yaml_sequence)]


class HitPoints(ContractModel):
    current: int
    max: int

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.current < 0 or self.max < 0 or self.current > self.max:
            raise ValueError("current must be between zero and max")
        return self


class ResourceState(ContractModel):
    id: ResourceId
    label: str
    current: int
    max: int

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.current < 0 or self.max < 0 or self.current > self.max:
            raise ValueError("current must be between zero and max")
        return self


class SpeechStyle(ContractModel):
    first_person: str
    second_person: str
    endings: _ExactStringSequence
    forbidden_patterns: _ExactStringSequence


class InitialItem(ContractModel):
    id: ItemId
    canonical_name: str


type _ExactInitialItemSequence = Annotated[
    tuple[InitialItem, ...], BeforeValidator(_copy_exact_yaml_sequence)
]


class CharacterRuleset(ContractModel):
    id: Literal["ruleset:neontof-minimal-2d6-v1"]
    action_modifier: int


class CharacterSheetV1(ContractModel):
    schema_version: Literal[1]
    id: CharacterId
    canonical_name: str
    aliases: _ExactStringSequence
    description: str
    hp: HitPoints
    resource: ResourceState
    initial_items: _ExactInitialItemSequence
    initial_location_id: LocationId
    visibility: Visibility
    speech_style: SpeechStyle | None = None
    ruleset: CharacterRuleset

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version must be the strict integer 1")
        return value

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, aliases: tuple[str, ...]) -> tuple[str, ...]:
        if any(alias == "" for alias in aliases):
            raise ValueError("aliases must not contain empty strings")
        if len(aliases) != len(set(aliases)):
            raise ValueError("aliases must not contain duplicates")
        return aliases


CHARACTER_SHEET_ADAPTER: TypeAdapter[CharacterSheetV1] = TypeAdapter(CharacterSheetV1)
