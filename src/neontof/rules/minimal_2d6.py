"""最小Rulesetの2d6判定と状態変更境界を提供する。"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, StrictInt, TypeAdapter

from neontof.contracts.base import ContractModel
from neontof.contracts.domain import derive_dice_seed
from neontof.contracts.ids import (
    ActionId,
    EntityId,
    LowercaseSha256,
    ResourceId,
    TurnId,
)
from neontof.contracts.projection import Projection
from neontof.contracts.semantic_result import ProposedResourceChanged

type NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]
type PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]
type TargetNumber = Annotated[StrictInt, Field(ge=2, le=12)]
type StatusCondition = Literal["injured", "shaken"]


class DiceResult(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: Annotated[StrictInt, Field(ge=2, le=12)]


class PublicDiceView(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: Annotated[StrictInt, Field(ge=2, le=12)]


class ResourceLimit(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    minimum: NonNegativeStrictInt
    maximum: NonNegativeStrictInt


class RuleValidationIssue(ContractModel):
    path: str
    code: Literal[
        "out_of_bounds",
        "unsupported_formula",
        "unknown_resource",
        "invalid_target_number",
        "invalid_condition",
        "unknown_clock",
    ]
    message: str


class CheckResult(ContractModel):
    dice: DiceResult
    target: TargetNumber
    success: bool


_TARGET_NUMBER_ADAPTER: TypeAdapter[TargetNumber] = TypeAdapter(TargetNumber)
_STATUS_CONDITION_ADAPTER: TypeAdapter[StatusCondition] = TypeAdapter(StatusCondition)


def resolve_2d6(
    *,
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: NonNegativeStrictInt,
) -> DiceResult:
    derived_seed = derive_dice_seed(campaign_seed, turn_id, action_id, roll_index)
    # 判定間で乱数状態を共有しないため、導出済みdigestから呼び出し単位の生成器を作る。
    generator = random.Random(derived_seed)
    result = generator.randint(1, 6) + generator.randint(1, 6)
    return DiceResult(
        campaign_seed=campaign_seed,
        action_id=action_id,
        roll_index=roll_index,
        derived_seed=derived_seed,
        formula="2d6",
        result=result,
    )


def resolve_2d6_check(
    *,
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: NonNegativeStrictInt,
    target: TargetNumber,
) -> CheckResult:
    validated_target = validate_target_number(target)
    dice = resolve_2d6(
        campaign_seed=campaign_seed,
        turn_id=turn_id,
        action_id=action_id,
        roll_index=roll_index,
    )
    return CheckResult(
        dice=dice,
        target=validated_target,
        success=dice.result >= validated_target,
    )


def validate_target_number(value: StrictInt) -> TargetNumber:
    return _TARGET_NUMBER_ADAPTER.validate_python(value, strict=True)


def validate_status_condition(value: str) -> StatusCondition:
    return _STATUS_CONDITION_ADAPTER.validate_python(value, strict=True)


def validate_resource_changes(
    *,
    projection: Projection,
    proposals: Sequence[ProposedResourceChanged],
    limits: Sequence[ResourceLimit],
) -> tuple[RuleValidationIssue, ...]:
    resource_values: dict[tuple[ResourceId, EntityId], int] = {
        (resource.resource_id, resource.entity_id): resource.value
        for resource in projection.resources
    }
    resource_limits = {(limit.resource_id, limit.entity_id): limit for limit in limits}
    issues: list[RuleValidationIssue] = []

    for index, proposal in enumerate(proposals):
        resource_id = proposal.payload.resource_id
        entity_id = proposal.payload.entity_id
        key = (resource_id, entity_id)
        path = f"proposals[{index}].payload"
        current = resource_values.get(key)
        limit = resource_limits.get(key)
        if current is None or limit is None:
            issues.append(
                RuleValidationIssue(
                    path=path,
                    code="unknown_resource",
                    message="resource must exist in the projection and have a limit",
                )
            )
            continue

        next_value = current + proposal.payload.delta
        if next_value < limit.minimum or next_value > limit.maximum:
            issues.append(
                RuleValidationIssue(
                    path=path,
                    code="out_of_bounds",
                    message="resource change would leave its allowed bounds",
                )
            )
            continue
        # 連続proposalも同じEvent列の効果順で検証し、Projection自体は変更しない。
        resource_values[key] = next_value

    return tuple(issues)


def validate_clock_advance(
    *,
    current: NonNegativeStrictInt,
    delta: PositiveStrictInt,
    maximum: PositiveStrictInt,
) -> tuple[RuleValidationIssue, ...]:
    issues: list[RuleValidationIssue] = []
    if type(current) is not int or current < 0:
        issues.append(
            RuleValidationIssue(
                path="current",
                code="out_of_bounds",
                message="clock current must be a non-negative strict integer",
            )
        )
    if type(delta) is not int or delta <= 0:
        issues.append(
            RuleValidationIssue(
                path="delta",
                code="out_of_bounds",
                message="clock delta must be a positive strict integer",
            )
        )
    if type(maximum) is not int or maximum <= 0:
        issues.append(
            RuleValidationIssue(
                path="maximum",
                code="out_of_bounds",
                message="clock maximum must be a positive strict integer",
            )
        )
    if issues:
        return tuple(issues)

    if current + delta > maximum:
        issues.append(
            RuleValidationIssue(
                path="current + delta",
                code="out_of_bounds",
                message="clock advance would exceed its maximum",
            )
        )
    return tuple(issues)
