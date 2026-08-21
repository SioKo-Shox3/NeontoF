"""Focused tests for the deterministic Fake Provider contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest

from neontof.contracts.semantic_result import SEMANTIC_RESULT_ADAPTER

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "providers"
EMPTY_CONTEXT_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def test_fake_provider_returns_fixed_success_response_for_different_requests() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep

    fixture = json.loads((FIXTURE_ROOT / "sanitized-call-log.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    provider = create_fake_provider(SuccessStep(type="success", response=response))
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
        roles=("world_simulator", "narrator"),
        publication_visibility="npc:keeper",
        context=(),
        output_schema="semantic-result-v1",
    )

    assert provider.invoke(first_request) == response
    assert provider.invoke(second_request) == response


def test_fake_provider_records_each_attempt_in_sanitized_calls() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    usage = ModelUsage.model_validate(response_data["usage"])
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=usage,
    )
    provider = create_fake_provider(SuccessStep(type="success", response=response))
    for request_id, turn_id in (
        ("model-call:first", "turn:first"),
        ("model-call:second", "turn:second"),
    ):
        provider.invoke(
            ModelRequest(
                model_call_id=request_id,
                turn_id=turn_id,
                roles=("referee",),
                publication_visibility="player_visible",
                context=(),
                output_schema="semantic-result-v1",
            )
        )

    calls = provider.calls
    assert isinstance(calls, tuple)
    assert tuple(call.request_id for call in calls) == (
        "model-call:first",
        "model-call:second",
    )
    assert tuple(call.attempt for call in calls) == (1, 2)
    assert all(call.status == "succeeded" for call in calls)
    assert all(call.error_code is None for call in calls)
    assert all(call.context_digest == EMPTY_CONTEXT_DIGEST for call in calls)
    assert all(call.context_item_count == 0 for call in calls)
    assert all(call.usage == usage for call in calls)
    assert set(calls[0].model_dump(mode="json")) == {
        "request_id",
        "attempt",
        "publication_visibility",
        "context_digest",
        "context_item_count",
        "usage",
        "status",
        "error_code",
    }


def test_fake_provider_calls_are_instance_local() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelRequest, ModelResponse, ModelUsage, SuccessStep

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    response = ModelResponse(
        payload=SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True),
        usage=ModelUsage.model_validate(response_data["usage"]),
    )
    step = SuccessStep(type="success", response=response)
    first_provider = create_fake_provider(step)
    second_provider = create_fake_provider(step)
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


def test_fake_provider_maps_model_error_to_fixed_exception_and_sanitized_call() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelErrorStep, ModelRequest

    fixture = json.loads((FIXTURE_ROOT / "model-error.v1.json").read_text(encoding="utf-8"))
    step_data = fixture["steps"][0]
    provider = create_fake_provider(
        ModelErrorStep(
            type=step_data["type"],
            code=step_data["code"],
            message="raw provider detail",
        )
    )
    request = ModelRequest(
        model_call_id="model-call:model-error",
        turn_id="turn:model-error",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(RuntimeError) as error:
        provider.invoke(request)

    assert str(error.value) == "model invocation failed"
    call = provider.calls[0]
    assert call.status == "failed"
    assert call.error_code == "model_error"
    assert call.usage is None
    assert "raw provider detail" not in str(error.value)
    assert step_data["code"] not in str(call.model_dump(mode="json"))


def test_fake_provider_maps_timeout_to_fixed_exception_and_sanitized_call() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelRequest, TimeoutStep

    fixture = json.loads((FIXTURE_ROOT / "timeout.v1.json").read_text(encoding="utf-8"))
    provider = create_fake_provider(TimeoutStep(type=fixture["steps"][0]["type"]))
    request = ModelRequest(
        model_call_id="model-call:timeout",
        turn_id="turn:timeout",
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


def test_fake_provider_maps_invalid_json_to_fixed_exception_and_sanitized_call() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import InvalidJsonStep, ModelRequest

    fixture = json.loads((FIXTURE_ROOT / "invalid-json.v1.json").read_text(encoding="utf-8"))
    step_data = fixture["steps"][0]
    provider = create_fake_provider(InvalidJsonStep(type=step_data["type"], body=step_data["body"]))
    request = ModelRequest(
        model_call_id="model-call:invalid-json",
        turn_id="turn:invalid-json",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(ValueError) as error:
        provider.invoke(request)

    assert str(error.value) == "model response JSON is invalid"
    call = provider.calls[0]
    assert call.status == "rejected"
    assert call.error_code == "invalid_json"
    assert call.usage is None
    assert step_data["body"] not in str(error.value)


def test_fake_provider_does_not_expose_credentials_or_raw_error_details() -> None:
    from neontof.model.fake_provider import create_fake_provider
    from neontof.model.model_invoker import ModelErrorStep, ModelRequest

    provider = create_fake_provider(
        ModelErrorStep(type="model_error", code="provider_detail", message="raw detail")
    )
    request_fields = set(ModelRequest.model_fields)
    request = ModelRequest(
        model_call_id="model-call:boundary",
        turn_id="turn:boundary",
        roles=("referee",),
        publication_visibility="player_visible",
        context=(),
        output_schema="semantic-result-v1",
    )

    with pytest.raises(RuntimeError):
        provider.invoke(request)

    assert request_fields == {
        "model_call_id",
        "turn_id",
        "roles",
        "publication_visibility",
        "context",
        "output_schema",
    }
    assert request_fields.isdisjoint({"api_key", "secret", "credential"})
    call_dump = provider.calls[0].model_dump(mode="json")
    assert set(call_dump).isdisjoint(
        {"roles", "context", "payload", "body", "message", "code", "api_key", "secret"}
    )


def test_model_invoker_public_contract_stays_narrow_and_discriminated() -> None:
    from neontof.model.model_invoker import (
        PROVIDER_STEP_ADAPTER,
        InvalidJsonStep,
        ModelErrorStep,
        ModelInvoker,
        ModelRequest,
        ModelResponse,
        Role,
        TimeoutStep,
    )

    assert get_origin(Role) is Literal
    assert set(get_args(Role)) == {
        "referee",
        "world_simulator",
        "narrator",
        "npc_actor",
    }

    invoker_args = get_args(ModelInvoker)
    assert get_origin(ModelInvoker) is Callable
    assert invoker_args == ([ModelRequest], ModelResponse)

    timeout = PROVIDER_STEP_ADAPTER.validate_python({"type": "timeout"}, strict=True)
    model_error = PROVIDER_STEP_ADAPTER.validate_python(
        {"type": "model_error", "code": "upstream", "message": "raw detail"},
        strict=True,
    )
    invalid_json = PROVIDER_STEP_ADAPTER.validate_python(
        {"type": "invalid_json", "body": "raw body"},
        strict=True,
    )

    assert type(timeout) is TimeoutStep
    assert type(model_error) is ModelErrorStep
    assert type(invalid_json) is InvalidJsonStep


def test_provider_contract_models_are_strict_immutable_and_revalidate_nested_models() -> None:
    from neontof.model.model_invoker import (
        InvalidJsonStep,
        ModelErrorStep,
        ModelRequest,
        ModelResponse,
        ModelUsage,
        ProviderCallLogMeta,
        SuccessStep,
        TimeoutStep,
    )
    from neontof.model.recorded_fixture import (
        RecordedFixtureV1,
        SanitizedProviderCallLogEntry,
    )
    from pydantic import BaseModel

    contract_models: tuple[type[BaseModel], ...] = (
        ModelRequest,
        ModelUsage,
        ModelResponse,
        SuccessStep,
        ModelErrorStep,
        TimeoutStep,
        InvalidJsonStep,
        ProviderCallLogMeta,
        SanitizedProviderCallLogEntry,
        RecordedFixtureV1,
    )
    for model in contract_models:
        assert model.model_config["strict"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["frozen"] is True
        assert model.model_config["revalidate_instances"] == "always"

    usage_values: dict[str, object] = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cached_tokens": 0,
    }
    usage = ModelUsage.model_validate(usage_values)
    with pytest.raises((TypeError, ValueError)):
        ModelUsage.model_validate(
            {
                "input_tokens": usage_values["input_tokens"],
                "output_tokens": usage_values["output_tokens"],
                "cached_tokens": usage_values["cached_tokens"],
                "unexpected": 3,
            }
        )
    with pytest.raises((TypeError, ValueError)):
        usage.input_tokens = 3

    fixture = json.loads((FIXTURE_ROOT / "normal-turn.v1.json").read_text(encoding="utf-8"))
    response_data = fixture["steps"][0]["response"]
    payload = SEMANTIC_RESULT_ADAPTER.validate_python(response_data["payload"], strict=True)
    broken_usage = usage.model_copy(update={"input_tokens": -1})

    with pytest.raises((TypeError, ValueError)):
        ModelResponse.model_validate({"payload": payload, "usage": broken_usage})


def test_provider_call_log_meta_fields_are_typed() -> None:
    from neontof.model.model_invoker import ModelUsage, ProviderCallLogMeta

    expected_fields = {
        "attempt",
        "context_item_count",
        "usage",
        "status",
        "error_code",
    }
    assert set(ProviderCallLogMeta.model_fields) == expected_fields
    assert all(field.annotation is not Any for field in ProviderCallLogMeta.model_fields.values())

    meta = ProviderCallLogMeta.model_validate(
        {
            "attempt": 1,
            "context_item_count": 0,
            "usage": ModelUsage.model_validate(
                {"input_tokens": 1, "output_tokens": 0, "cached_tokens": 0}
            ),
            "status": "succeeded",
            "error_code": None,
        }
    )
    assert meta.attempt == 1
