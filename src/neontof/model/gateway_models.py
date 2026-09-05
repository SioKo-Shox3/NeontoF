"""Local Gatewayが受け渡す公開Context、Dice、予算、結果の契約を定義する。"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StrictStr, TypeAdapter, ValidationError, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import (
    ActionId,
    CampaignId,
    ClockId,
    EntityId,
    EventId,
    FactId,
    ItemId,
    LocationId,
    LowercaseSha256,
    ModelCallId,
    NpcId,
    ResourceId,
    SceneId,
    SessionId,
    TurnId,
    TurnRequestId,
)
from neontof.model.model_invoker import (
    ModelResponse,
    ProviderStep,
    PublicationVisibility,
    Role,
)
from neontof.rules.minimal_2d6 import (
    DiceResult,
    NonNegativeStrictInt,
    PositiveStrictInt,
    StatusCondition,
    TargetNumber,
)


class PublicInventoryItem(ContractModel):
    item_id: ItemId
    label: StrictStr


class PublicStaticData(ContractModel):
    character_id: EntityId
    hp_max: StrictInt
    resource_id: ResourceId
    resource_label: StrictStr
    resource_max: StrictInt
    inventory: tuple[PublicInventoryItem, ...]
    objective_scene_id: SceneId
    objective_text: StrictStr
    clock_id: ClockId
    clock_label: StrictStr
    clock_initial: StrictInt
    clock_max: StrictInt


class PublicResourceCurrent(ContractModel):
    resource_id: ResourceId
    current: StrictInt


class PublicResourceProjection(ContractModel):
    hp_current: StrictInt
    resources: tuple[PublicResourceCurrent, ...]


class PublicLocationProjection(ContractModel):
    location_id: LocationId


class PublicClockProjection(ContractModel):
    clock_id: ClockId
    current: StrictInt


_ENTITY_ID_ADAPTER: TypeAdapter[object] = TypeAdapter(EntityId)
_ITEM_ID_ADAPTER: TypeAdapter[object] = TypeAdapter(ItemId)
_SCENE_ID_ADAPTER: TypeAdapter[object] = TypeAdapter(SceneId)


def _matches(adapter: TypeAdapter[object], value: object) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


type PublicFactValue = (
    EntityId | ItemId | SceneId | TargetNumber | StatusCondition | Literal[1] | StrictStr
)


class PublicFact(ContractModel):
    fact_id: FactId
    kind: Literal["fact"]
    holder: Literal["world", "player_character"]
    subject_id: EntityId | None
    predicate: Literal[
        "inventory_item",
        "objective",
        "clue",
        "scenario_version",
        "character_schema_version",
        "target_number",
        "condition",
    ]
    value: PublicFactValue
    source_event_id: EventId

    @model_validator(mode="after")
    def validate_predicate_shape(self) -> Self:
        if self.predicate == "inventory_item":
            expected_holder, subject_required = "player_character", True
            valid_value = _matches(_ITEM_ID_ADAPTER, self.value)
        elif self.predicate == "objective":
            expected_holder, subject_required = "world", False
            valid_value = _matches(_SCENE_ID_ADAPTER, self.value)
        elif self.predicate == "clue":
            expected_holder, subject_required = "world", False
            valid_value = _matches(_ENTITY_ID_ADAPTER, self.value)
        elif self.predicate == "scenario_version":
            expected_holder, subject_required = "world", False
            valid_value = type(self.value) is str
        elif self.predicate == "character_schema_version":
            expected_holder, subject_required = "player_character", True
            valid_value = type(self.value) is int and self.value == 1
        elif self.predicate == "target_number":
            expected_holder, subject_required = "world", False
            valid_value = type(self.value) is int and 2 <= self.value <= 12
        else:
            expected_holder, subject_required = "player_character", True
            valid_value = self.value in ("injured", "shaken")
        if self.holder != expected_holder:
            raise ValueError("public fact holder does not match predicate")
        if subject_required != (self.subject_id is not None):
            raise ValueError("public fact subject does not match predicate")
        if not valid_value:
            raise ValueError("public fact value does not match predicate")
        return self


type ScenarioOutcome = Literal["success", "failure"]


class ScenarioOutcomeFact(ContractModel):
    fact_id: FactId
    kind: Literal["fact"]
    holder: Literal["world"]
    subject_id: None
    predicate: Literal["scenario_outcome"]
    value: ScenarioOutcome
    visibility: Literal["player_visible"]
    source_event_id: EventId


class PublicProjection(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    location_id: LocationId | None
    resources: PublicResourceProjection
    locations: tuple[PublicLocationProjection, ...]
    clocks: tuple[PublicClockProjection, ...]
    facts: tuple[PublicFact, ...]
    scenario_outcome: ScenarioOutcome | None
    known_entity_ids: tuple[EntityId, ...]


class PublicContext(ContractModel):
    publication_visibility: PublicationVisibility
    projection: PublicProjection
    known_location_ids: tuple[LocationId, ...]
    known_npc_ids: tuple[NpcId, ...]
    known_clock_ids: tuple[ClockId, ...]
    context_digest: LowercaseSha256


class SessionBudget(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    limit_microusd: Annotated[StrictInt, Field(ge=0)]
    input_microusd_per_million_tokens: Annotated[StrictInt, Field(ge=0)]
    output_microusd_per_million_tokens: Annotated[StrictInt, Field(ge=0)]
    cached_microusd_per_million_tokens: Annotated[StrictInt, Field(ge=0)]
    max_attempts: Literal[1] = 1


class ProviderDiceResult(ContractModel):
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    formula: Literal["2d6"]
    result: Annotated[StrictInt, Field(ge=2, le=12)]


class GatewayRequest(ContractModel):
    turn_id: TurnId
    public_context: PublicContext
    player_input: StrictStr
    dice_result: DiceResult
    max_narrative_chars: PositiveStrictInt


class ProviderRequest(ContractModel):
    model_call_id: ModelCallId
    turn_id: TurnId
    roles: tuple[Role, ...]
    public_context: PublicContext
    player_input: StrictStr
    dice_result: ProviderDiceResult
    max_narrative_chars: PositiveStrictInt
    output_schema: Literal["semantic-result-v1"]


class GatewayFixtureCase(ContractModel):
    expected_request: ProviderRequest
    step: ProviderStep


class GatewaySuccess(ContractModel):
    type: Literal["success"]
    response: ModelResponse
    attempts: Literal[1]
    cost_microusd: Annotated[StrictInt, Field(ge=0)]


class GatewayFailure(ContractModel):
    type: Literal["failure"]
    code: Literal[
        "budget_exceeded",
        "timeout",
        "model_error",
        "invalid_json",
    ]
    attempts: Literal[0, 1]

    @model_validator(mode="after")
    def validate_attempts(self) -> Self:
        expected_attempts = 0 if self.code == "budget_exceeded" else 1
        if self.attempts != expected_attempts:
            raise ValueError("gateway failure attempts do not match code")
        return self


type GatewayOutcome = GatewaySuccess | GatewayFailure


__all__ = (
    "GatewayFailure",
    "GatewayFixtureCase",
    "GatewayOutcome",
    "GatewayRequest",
    "GatewaySuccess",
    "ProviderDiceResult",
    "ProviderRequest",
    "PublicClockProjection",
    "PublicContext",
    "PublicFact",
    "PublicFactValue",
    "PublicInventoryItem",
    "PublicLocationProjection",
    "PublicProjection",
    "PublicResourceCurrent",
    "PublicResourceProjection",
    "PublicStaticData",
    "ScenarioOutcome",
    "ScenarioOutcomeFact",
    "SessionBudget",
)
