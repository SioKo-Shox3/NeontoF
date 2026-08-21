"""Pure transport contracts for validated Semantic Result frames."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, TypeAdapter, ValidationError

from neontof.contracts.base import ContractModel, FrozenJsonValue
from neontof.contracts.ids import TurnRequestId
from neontof.contracts.semantic_result import AcceptedSemanticResult


class TurnPostRequest(ContractModel):
    type: Literal["turn_post"]
    turn_request_id: TurnRequestId
    input_text: str


JsonValue: TypeAlias = FrozenJsonValue  # noqa: UP040


class SemanticResultFrame(ContractModel):
    type: Literal["semantic_result"]
    data: JsonValue


class NarrativeFrame(ContractModel):
    type: Literal["narrative"]
    data: str


class DoneFrame(ContractModel):
    type: Literal["done"]
    data: Literal["running", "awaiting_player", "aborted"]


TransportFrame: TypeAlias = Annotated[  # noqa: UP040
    SemanticResultFrame | NarrativeFrame | DoneFrame,
    Field(discriminator="type"),
]
TRANSPORT_FRAME_ADAPTER: TypeAdapter[TransportFrame] = TypeAdapter(TransportFrame)


def _validated_accepted_result(result: object) -> AcceptedSemanticResult:
    if not isinstance(result, AcceptedSemanticResult):
        raise TypeError("builder requires AcceptedSemanticResult")
    try:
        return AcceptedSemanticResult.model_validate(result, strict=True)
    except AttributeError, TypeError, ValueError, ValidationError:
        raise TypeError("builder requires a valid AcceptedSemanticResult") from None


def _build_frames(result: AcceptedSemanticResult) -> tuple[TransportFrame, ...]:
    validated_result = _validated_accepted_result(result)
    try:
        semantic_data = TypeAdapter(FrozenJsonValue).validate_python(
            validated_result.value.model_dump(mode="python"),
            strict=True,
        )
        return (
            SemanticResultFrame(type="semantic_result", data=semantic_data),
            NarrativeFrame(type="narrative", data=validated_result.value.narrative),
            DoneFrame(type="done", data=validated_result.next_status),
        )
    except AttributeError, TypeError, ValueError, ValidationError, RecursionError:
        raise TypeError("could not build validated transport frames") from None


def build_buffered_response(result: AcceptedSemanticResult) -> tuple[TransportFrame, ...]:
    """Build the buffered response sequence for an accepted result."""

    return _build_frames(result)


def build_sse_frames(result: AcceptedSemanticResult) -> tuple[TransportFrame, ...]:
    """Build the SSE-equivalent frame sequence for an accepted result."""

    return _build_frames(result)


__all__ = (
    "TRANSPORT_FRAME_ADAPTER",
    "DoneFrame",
    "JsonValue",
    "NarrativeFrame",
    "SemanticResultFrame",
    "TransportFrame",
    "TurnPostRequest",
    "build_buffered_response",
    "build_sse_frames",
)
