"""Provider-neutral model invocation contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import ModelCallId, TurnId
from neontof.contracts.projection import FactRecord
from neontof.contracts.semantic_result import (
    NonNegativeStrictInt,
    PositiveStrictInt,
    PublicationVisibility,
    SemanticResultV1,
)

Role: TypeAlias = Literal["referee", "world_simulator", "npc_actor", "narrator"]  # noqa: UP040


class ModelRequest(ContractModel):
    model_call_id: ModelCallId
    turn_id: TurnId
    roles: tuple[Role, ...]
    publication_visibility: PublicationVisibility
    context: tuple[FactRecord, ...]
    output_schema: Literal["semantic-result-v1"]


class ModelUsage(ContractModel):
    input_tokens: NonNegativeStrictInt
    output_tokens: NonNegativeStrictInt
    cached_tokens: NonNegativeStrictInt


class ModelResponse(ContractModel):
    payload: SemanticResultV1
    usage: ModelUsage


ModelInvoker: TypeAlias = Callable[[ModelRequest], ModelResponse]  # noqa: UP040


class SuccessStep(ContractModel):
    type: Literal["success"]
    response: ModelResponse


class ModelErrorStep(ContractModel):
    type: Literal["model_error"]
    code: str
    message: str


class TimeoutStep(ContractModel):
    type: Literal["timeout"]


class InvalidJsonStep(ContractModel):
    type: Literal["invalid_json"]
    body: str


ProviderStep: TypeAlias = Annotated[  # noqa: UP040
    SuccessStep | ModelErrorStep | TimeoutStep | InvalidJsonStep,
    Field(discriminator="type"),
]
PROVIDER_STEP_ADAPTER: TypeAdapter[ProviderStep] = TypeAdapter(ProviderStep)


class ProviderCallLogMeta(ContractModel):
    attempt: PositiveStrictInt
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    usage: ModelUsage | None
    context_item_count: NonNegativeStrictInt
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None


__all__ = (
    "PROVIDER_STEP_ADAPTER",
    "InvalidJsonStep",
    "ModelErrorStep",
    "ModelInvoker",
    "ModelRequest",
    "ModelResponse",
    "ModelUsage",
    "ProviderCallLogMeta",
    "ProviderStep",
    "PublicationVisibility",
    "Role",
    "SuccessStep",
    "TimeoutStep",
)
