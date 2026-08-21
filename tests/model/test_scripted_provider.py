"""Focused tests for the deterministic Scripted Provider contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neontof.contracts.semantic_result import SEMANTIC_RESULT_ADAPTER

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "providers"


def test_scripted_provider_consumes_steps_in_order() -> None:
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    first_response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    second_response = ModelResponse(
        payload=first_response.payload,
        usage=ModelUsage(input_tokens=20, output_tokens=10, cached_tokens=1),
    )
    provider = create_scripted_provider(
        (
            SuccessStep(type="success", response=first_response),
            SuccessStep(type="success", response=second_response),
        )
    )

    first_request = ModelRequest(
        model_call_id="model-call:first",
        turn_id="turn:first",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )
    second_request = ModelRequest(
        model_call_id="model-call:second",
        turn_id="turn:second",
        roles=("narrator",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    assert provider.invoke(first_request) == first_response
    assert provider.invoke(second_request) == second_response
    assert tuple(call.request_id for call in provider.calls) == (
        "model-call:first",
        "model-call:second",
    )
    assert tuple(call.attempt for call in provider.calls) == (1, 2)


def test_scripted_provider_keeps_success_before_a_later_failure() -> None:
    from neontof.model.model_invoker import (
        ModelErrorStep,
        ModelRequest,
        ModelResponse,
        ModelUsage,
        SuccessStep,
    )
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    provider = create_scripted_provider(
        (
            SuccessStep(type="success", response=response),
            ModelErrorStep(type="model_error", code="temporary_failure", message="raw detail"),
        )
    )
    request = ModelRequest(
        model_call_id="model-call:sequence",
        turn_id="turn:sequence",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    assert provider.invoke(request) == response
    with pytest.raises(RuntimeError) as error:
        provider.invoke(request)

    assert str(error.value) == "model invocation failed"
    assert tuple(call.status for call in provider.calls) == ("succeeded", "failed")
    assert tuple(call.error_code for call in provider.calls) == (None, "model_error")


def test_scripted_provider_records_script_exhaustion_as_rejected() -> None:
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    provider = create_scripted_provider((SuccessStep(type="success", response=response),))
    request = ModelRequest(
        model_call_id="model-call:exhaustion",
        turn_id="turn:exhaustion",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    provider.invoke(request)
    with pytest.raises(RuntimeError) as error:
        provider.invoke(request)

    assert str(error.value) == "script exhausted"
    call = provider.calls[1]
    assert call.status == "rejected"
    assert call.error_code == "script_exhausted"
    assert call.usage is None


def test_scripted_provider_calls_are_instance_local() -> None:
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    steps = (SuccessStep(type="success", response=response),)
    first_provider = create_scripted_provider(steps)
    second_provider = create_scripted_provider(steps)
    request = ModelRequest(
        model_call_id="model-call:isolated",
        turn_id="turn:isolated",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    first_provider.invoke(request)

    assert len(first_provider.calls) == 1
    assert second_provider.calls == ()


def test_scripted_provider_runs_retry_then_success_sequence() -> None:
    from neontof.model.model_invoker import (
        ModelErrorStep,
        ModelRequest,
        ModelResponse,
        ModelUsage,
        SuccessStep,
    )
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "retry-then-success.v1.json").read_text(encoding="utf-8"))
    failure_data = fixture["steps"][0]
    response_data = fixture["steps"][1]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    provider = create_scripted_provider(
        (
            ModelErrorStep(
                type="model_error",
                code=failure_data["code"],
                message=failure_data["message"],
            ),
            SuccessStep(type="success", response=response),
        )
    )
    request = ModelRequest(
        model_call_id="model-call:retry",
        turn_id="turn:retry",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(RuntimeError, match="^model invocation failed$"):
        provider.invoke(request)
    assert provider.invoke(request) == response
    assert len(provider.calls) == 2
    assert tuple(call.attempt for call in provider.calls) == (1, 2)
    assert tuple(call.status for call in provider.calls) == ("failed", "succeeded")
    assert tuple(call.error_code for call in provider.calls) == ("model_error", None)


def test_scripted_provider_maps_invalid_json_step_before_following_success() -> None:
    from neontof.model.model_invoker import (
        InvalidJsonStep,
        ModelRequest,
        ModelResponse,
        ModelUsage,
        SuccessStep,
    )
    from neontof.model.scripted_provider import create_scripted_provider

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    provider = create_scripted_provider(
        (
            InvalidJsonStep(type="invalid_json", body="raw invalid response"),
            SuccessStep(type="success", response=response),
        )
    )
    request = ModelRequest(
        model_call_id="model-call:invalid-sequence",
        turn_id="turn:invalid-sequence",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(ValueError) as error:
        provider.invoke(request)
    assert str(error.value) == "model response JSON is invalid"
    assert provider.invoke(request) == response
    assert tuple(call.status for call in provider.calls) == ("rejected", "succeeded")
    assert tuple(call.error_code for call in provider.calls) == ("invalid_json", None)


def test_scripted_provider_maps_timeout_step_to_fixed_exception_and_sanitized_call() -> None:
    from neontof.model.model_invoker import ModelRequest, TimeoutStep
    from neontof.model.scripted_provider import create_scripted_provider

    provider = create_scripted_provider((TimeoutStep(type="timeout"),))
    request = ModelRequest(
        model_call_id="model-call:scripted-timeout",
        turn_id="turn:scripted-timeout",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(TimeoutError) as error:
        provider.invoke(request)

    assert str(error.value) == "model invocation timed out"
    call = provider.calls[0]
    assert call.status == "timed_out"
    assert call.error_code == "timeout"
    assert call.usage is None
