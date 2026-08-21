"""P0-04 transport boundary contracts for validated Semantic Results."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any, get_args, get_origin, get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from .support.evaluate_semantic_contract import (
    base_result,
    evaluate_semantic_result,
    load_fixture,
    make_context,
)


def _alias_contains(alias: object, target: object) -> bool:
    if alias is target or get_origin(alias) is target:
        return True
    return any(_alias_contains(argument, target) for argument in get_args(alias))


def _accepted_result() -> Any:
    raw = load_fixture("valid-control.v1.json")
    from neontof.contracts.semantic_result import AcceptedSemanticResult

    outcome = evaluate_semantic_result(
        raw,
        make_context(),
    )
    assert isinstance(outcome, AcceptedSemanticResult)
    return outcome


def test_transport_builders_accept_only_accepted_semantic_results() -> None:
    from neontof.contracts.semantic_result import (
        AcceptedSemanticResult,
        RejectedSemanticResult,
        SemanticResultV1,
        ValidationIssue,
    )
    from neontof.contracts.transport import (
        TransportFrame,
        build_buffered_response,
        build_sse_frames,
    )

    buffered_hints = get_type_hints(build_buffered_response, include_extras=True)
    sse_hints = get_type_hints(build_sse_frames, include_extras=True)
    assert buffered_hints["result"] is AcceptedSemanticResult
    assert sse_hints["result"] is AcceptedSemanticResult
    assert buffered_hints["return"] == tuple[TransportFrame, ...]
    assert sse_hints["return"] == tuple[TransportFrame, ...]
    assert "SemanticResultV1" not in str(inspect.signature(build_buffered_response))

    raw_model = SemanticResultV1.model_validate(base_result())
    with pytest.raises((TypeError, ValidationError)):
        build_buffered_response(raw_model)
    with pytest.raises((TypeError, ValidationError)):
        build_sse_frames(raw_model)

    rejected = RejectedSemanticResult(
        type="rejected",
        issues=(ValidationIssue(path="schema", code="schema", message="schema validation failed"),),
        next_status="aborted",
    )
    with pytest.raises((TypeError, ValidationError)):
        build_buffered_response(rejected)
    with pytest.raises((TypeError, ValidationError)):
        build_sse_frames(rejected)


def test_public_transport_frame_alias_and_adapter_validate_discriminators() -> None:
    transport = importlib.import_module("neontof.contracts.transport")
    from neontof.contracts.transport import (
        TRANSPORT_FRAME_ADAPTER,
        DoneFrame,
        NarrativeFrame,
        SemanticResultFrame,
        TransportFrame,
    )

    assert TRANSPORT_FRAME_ADAPTER is transport.TRANSPORT_FRAME_ADAPTER
    assert isinstance(TRANSPORT_FRAME_ADAPTER, TypeAdapter)
    assert _alias_contains(TransportFrame, SemanticResultFrame)
    assert _alias_contains(TransportFrame, NarrativeFrame)
    assert _alias_contains(TransportFrame, DoneFrame)

    frames = (
        (SemanticResultFrame(type="semantic_result", data=True), SemanticResultFrame),
        (NarrativeFrame(type="narrative", data="A validated narrative."), NarrativeFrame),
        (DoneFrame(type="done", data="running"), DoneFrame),
    )
    for frame, expected_type in frames:
        parsed = TRANSPORT_FRAME_ADAPTER.validate_python(
            frame.model_dump(mode="python"),
            strict=True,
        )
        assert isinstance(parsed, expected_type)

    with pytest.raises(ValidationError):
        TRANSPORT_FRAME_ADAPTER.validate_python(
            {"type": 1, "data": "invalid discriminator type"},
            strict=True,
        )
    with pytest.raises(ValidationError):
        TRANSPORT_FRAME_ADAPTER.validate_python(
            {"type": "unknown", "data": "invalid discriminator value"},
            strict=True,
        )


def test_turn_post_request_is_strict_frozen_and_keeps_input_at_request_boundary() -> None:
    from neontof.contracts.transport import TurnPostRequest

    assert TurnPostRequest.model_config["strict"] is True
    assert TurnPostRequest.model_config["extra"] == "forbid"
    assert TurnPostRequest.model_config["frozen"] is True
    assert TurnPostRequest.model_config["revalidate_instances"] == "always"

    request = TurnPostRequest(
        type="turn_post",
        turn_request_id="turn-request:one",
        input_text="The player input exists only at this boundary.",
    )
    assert request.input_text.startswith("The player input")
    with pytest.raises(ValidationError):
        request.input_text = "changed"
    with pytest.raises(ValidationError):
        TurnPostRequest(
            type="turn_post",
            turn_request_id="turn-request:one",
            input_text="input",
            unexpected="field",
        )

    corrupted = TurnPostRequest.model_construct(
        type="turn_post",
        turn_request_id="turn-request:one",
        input_text="input",
    )
    object.__setattr__(corrupted, "input_text", 17)
    with pytest.raises(ValidationError):
        TurnPostRequest.model_validate(corrupted)


def test_transport_frames_are_semantic_result_then_narrative_then_done() -> None:
    from neontof.contracts.base import FrozenJsonValue
    from neontof.contracts.transport import (
        DoneFrame,
        NarrativeFrame,
        SemanticResultFrame,
        build_buffered_response,
        build_sse_frames,
    )

    accepted = _accepted_result()
    buffered = build_buffered_response(accepted)
    sse = build_sse_frames(accepted)
    assert tuple(frame.type for frame in buffered) == (
        "semantic_result",
        "narrative",
        "done",
    )
    assert tuple(frame.type for frame in sse) == (
        "semantic_result",
        "narrative",
        "done",
    )
    expected_semantic = TypeAdapter(FrozenJsonValue).validate_python(
        accepted.value.model_dump(mode="python"),
        strict=True,
    )
    assert buffered == (
        SemanticResultFrame(type="semantic_result", data=expected_semantic),
        NarrativeFrame(type="narrative", data=accepted.value.narrative),
        DoneFrame(type="done", data=accepted.next_status),
    )
    assert sse == (
        SemanticResultFrame(type="semantic_result", data=expected_semantic),
        NarrativeFrame(type="narrative", data=accepted.value.narrative),
        DoneFrame(type="done", data=accepted.next_status),
    )


def test_transport_does_not_send_unvalidated_narrative_or_raw_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from neontof.contracts.semantic_result import SemanticResultV1
    from neontof.contracts.transport import build_buffered_response, build_sse_frames

    raw_secret = "UNVALIDATED_NARRATIVE_SECRET_SENTINEL"
    raw = base_result()
    raw["narrative"] = raw_secret
    semantic_model = SemanticResultV1.model_validate(raw)
    caplog.set_level(logging.DEBUG)
    with pytest.raises((TypeError, ValidationError)) as buffered_error:
        build_buffered_response(semantic_model)
    with pytest.raises((TypeError, ValidationError)) as sse_error:
        build_sse_frames(semantic_model)
    assert raw_secret not in str(buffered_error.value)
    assert raw_secret not in repr(buffered_error.value)
    assert raw_secret not in str(sse_error.value)
    assert raw_secret not in repr(sse_error.value)
    assert raw_secret not in caplog.text

    accepted = _accepted_result()
    payloads = tuple(frame.model_dump(mode="python") for frame in build_sse_frames(accepted))
    assert raw_secret not in repr(payloads)
    assert "input_text" not in repr(payloads)


def test_transport_frame_contracts_are_strict_frozen_and_extra_forbid() -> None:
    from neontof.contracts.transport import (
        DoneFrame,
        NarrativeFrame,
        SemanticResultFrame,
    )

    frames = (
        SemanticResultFrame(type="semantic_result", data=True),
        NarrativeFrame(type="narrative", data="A validated narrative."),
        DoneFrame(type="done", data="running"),
    )
    for frame in frames:
        assert frame.model_config["strict"] is True
        assert frame.model_config["extra"] == "forbid"
        assert frame.model_config["frozen"] is True
        assert frame.model_config["revalidate_instances"] == "always"
        with pytest.raises(ValidationError):
            frame.model_validate({**frame.model_dump(), "unexpected": "field"})

        corrupted = frame.model_copy()
        object.__setattr__(corrupted, "data", object())
        with pytest.raises(ValidationError):
            type(frame).model_validate(corrupted)


def test_sse_and_buffered_payloads_are_equal_for_a_nested_frozen_value() -> None:
    from neontof.contracts.transport import build_buffered_response, build_sse_frames

    raw = base_result()
    raw["narrative"] = "Nested values are retained in the semantic frame."
    raw["mentioned_details"] = [
        {
            "id": "entity:door",
            "kind": "object",
            "label": "door",
            "scene_id": "scene:hall",
            "visibility": "player_visible",
        }
    ]
    from neontof.contracts.semantic_result import AcceptedSemanticResult

    outcome = evaluate_semantic_result(raw, make_context())
    assert isinstance(outcome, AcceptedSemanticResult)
    assert tuple(frame.model_dump(mode="python") for frame in build_sse_frames(outcome)) == tuple(
        frame.model_dump(mode="python") for frame in build_buffered_response(outcome)
    )
