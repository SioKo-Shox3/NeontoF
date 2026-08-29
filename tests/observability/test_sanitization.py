"""P1-02 observation payload, redaction, and strict contract tests."""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import Any

import pytest

MAX_SAFE_INTEGER = 9_223_372_036_854_775_807
SHA256 = "a" * 64
OCCURRED_AT = "2026-08-25T00:00:00Z"
SENTINEL = "TOP_SECRET_OBSERVATION_SENTINEL"
OBSERVATION_FAILURES = (AssertionError, AttributeError, TypeError, ValueError, RuntimeError)
TRANSCRIPT_KINDS = (
    "player_input",
    "model_request",
    "model_response",
    "narrative",
    "error",
    "retry",
    "correction",
    "tool_call",
)


def _observation_types() -> tuple[type[Any], type[Any], Callable[[Any], Any]]:
    try:
        from neontof.observability.records import TelemetryRecord, TranscriptRecord
        from neontof.observability.sanitization import sanitize_observation
    except ImportError:
        pytest.fail("P1-02 observation production modules are not available")
    return TranscriptRecord, TelemetryRecord, sanitize_observation


def _payload(kind: str) -> dict[str, object]:
    if kind in {"player_input", "narrative", "correction"}:
        return {"text": "hello"}
    if kind == "model_request":
        return {
            "context_digest": SHA256,
            "context_item_count": 0,
            "output_schema": "semantic-result-v1",
        }
    if kind == "model_response":
        return {
            "response_digest": SHA256,
            "narrative_byte_length": 5,
            "proposed_event_count": 0,
            "proposed_fact_count": 0,
        }
    if kind == "error":
        return {"error_code": "model_error", "digest": SHA256, "byte_length": 0}
    if kind == "retry":
        return {"error_code": "model_error", "attempt": 1}
    if kind == "tool_call":
        return {
            "tool_name": "roll_dice",
            "arguments_digest": SHA256,
            "arguments_byte_length": 0,
            "outcome": "accepted",
        }
    raise AssertionError(f"unknown test kind: {kind}")


def _transcript(kind: str, data: object, *, entry_id: str = "transcript:test") -> Any:
    transcript_type, _, _ = _observation_types()
    return transcript_type(
        entry_id=entry_id,
        campaign_id="campaign:alpha",
        session_id="session:main",
        turn_id="turn:first",
        model_call_id="model-call:first",
        kind=kind,
        occurred_at=OCCURRED_AT,
        data=data,
    )


def _telemetry(**overrides: object) -> Any:
    _, telemetry_type, _ = _observation_types()
    values: dict[str, object] = {
        "entry_id": "telemetry:test",
        "campaign_id": "campaign:alpha",
        "session_id": "session:main",
        "turn_id": "turn:first",
        "model_call_id": "model-call:first",
        "provider": "fake_provider",
        "model": "test.model",
        "roles": ("referee",),
        "attempt": 1,
        "status": "succeeded",
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "latency_ms": 0,
        "cost_microusd": 0,
        "error_code": None,
        "occurred_at": OCCURRED_AT,
    }
    values.update(overrides)
    return telemetry_type(**values)


def _assert_safe_failure(error: BaseException, sentinel: str) -> None:
    surfaces = [
        str(error),
        repr(error),
        repr(error.args),
        repr(getattr(error, "__dict__", {})),
        repr(error.__cause__),
        repr(error.__context__),
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    ]
    for attribute in ("detail", "log", "stdout", "stderr"):
        surfaces.append(repr(getattr(error, attribute, None)))
    errors = getattr(error, "errors", None)
    if callable(errors):
        try:
            surfaces.append(repr(errors()))
        except (AttributeError, TypeError, ValueError, RuntimeError) as nested_error:
            surfaces.append(repr(nested_error))
    elif errors is not None:
        surfaces.append(repr(errors))
    assert all(sentinel not in surface for surface in surfaces)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert len(error.args) == 1
    assert type(error.args[0]) is str


def test_transcript_validation_entry_points_have_the_same_sanitized_failure_boundary(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript_type, _, _ = _observation_types()
    from pydantic import TypeAdapter

    invalid_data: dict[str, object] = {
        "text": "safe",
        "raw_provider_body": SENTINEL,
        "raw_provider_error": SENTINEL,
        "api_key": SENTINEL,
        "cause": SENTINEL,
    }
    invalid_input: dict[str, object] = {
        "entry_id": "transcript:validation-entry-point",
        "campaign_id": "campaign:alpha",
        "session_id": "session:main",
        "turn_id": "turn:first",
        "model_call_id": "model-call:first",
        "kind": "player_input",
        "occurred_at": OCCURRED_AT,
        "data": invalid_data,
    }
    string_input = dict(invalid_input)
    string_input["data"] = dict(invalid_data)
    entry_points: tuple[tuple[str, Callable[[], Any]], ...] = (
        ("constructor", lambda: transcript_type(**invalid_input)),
        ("model_validate", lambda: transcript_type.model_validate(invalid_input)),
        (
            "model_validate_json",
            lambda: transcript_type.model_validate_json(json.dumps(invalid_input)),
        ),
        ("model_validate_strings", lambda: transcript_type.model_validate_strings(string_input)),
        (
            "type_adapter",
            lambda: TypeAdapter(transcript_type).validate_python(invalid_input),
        ),
    )

    for name, entry_point in entry_points:
        caplog.clear()
        with pytest.raises(OBSERVATION_FAILURES) as raised:
            entry_point()

        _assert_safe_failure(raised.value, SENTINEL)
        captured = capsys.readouterr()
        assert SENTINEL not in f"{captured.out}\n{captured.err}\n{caplog.text}", name


def test_supported_transcript_json_boundary_sanitizes_malformed_json(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        from neontof.observability.records import parse_transcript_json
    except ImportError:
        pytest.fail("P1-02 supported transcript JSON boundary is not available")

    malformed_json = (
        '{"entry_id":"transcript:malformed-json","data":{"raw_provider_body":"' + SENTINEL + '"'
    )
    with pytest.raises(OBSERVATION_FAILURES) as raised:
        parse_transcript_json(malformed_json)

    _assert_safe_failure(raised.value, SENTINEL)
    captured = capsys.readouterr()
    assert SENTINEL not in f"{captured.out}\n{captured.err}\n{caplog.text}"


@pytest.mark.parametrize("kind", TRANSCRIPT_KINDS)
def test_all_eight_transcript_kinds_are_supported(kind: str) -> None:
    record = _transcript(kind, _payload(kind))

    assert record.kind == kind


def test_transcript_root_object_is_checked_before_frozen_json_conversion() -> None:
    record = _transcript("player_input", {"text": "hello"})
    assert record.kind == "player_input"

    with pytest.raises(OBSERVATION_FAILURES):
        _transcript("player_input", [["text", "hello"]])
    with pytest.raises(OBSERVATION_FAILURES):
        _transcript("player_input", (("text", "hello"),))


def test_recursive_redaction_is_defense_not_primary_boundary() -> None:
    _, _, sanitize_observation = _observation_types()
    candidate = {
        "safe": "visible",
        "nested": {
            "api_key": SENTINEL,
            "authorization": f"Bearer {SENTINEL}",
            "token": SENTINEL,
            "secret": SENTINEL,
            "deeper": [{"api_key": SENTINEL}],
        },
    }

    sanitized = sanitize_observation(candidate)

    assert "visible" in repr(sanitized)
    assert SENTINEL not in repr(sanitized)
    json.dumps(sanitized, ensure_ascii=False)


@pytest.mark.parametrize(
    "value",
    (True, 1, 1.0, b"hello", "x" * 65_537, "あ" * 21_846),
    ids=("bool", "int", "float", "bytes", "ascii_over_limit", "utf8_over_limit"),
)
def test_transcript_text_is_strict_utf8_bounded(value: object) -> None:
    with pytest.raises(OBSERVATION_FAILURES):
        _transcript("player_input", {"text": value})

    accepted = _transcript("player_input", {"text": "x" * 65_536})
    assert accepted.kind == "player_input"


@pytest.mark.parametrize(
    "value",
    (True, 1, 1.0, "Roll", "a" * 65, "a-b", "_roll", "9roll", "ロール"),
)
def test_tool_name_is_strict_ascii_and_bounded(value: object) -> None:
    with pytest.raises(OBSERVATION_FAILURES):
        _transcript(
            "tool_call",
            {
                "tool_name": value,
                "arguments_digest": SHA256,
                "arguments_byte_length": 0,
                "outcome": "accepted",
            },
        )


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    (
        ("model_request", "context_digest", "A" * 64),
        ("model_request", "context_digest", "a" * 63),
        ("model_request", "context_digest", "g" * 64),
        ("model_response", "narrative_byte_length", True),
        ("model_response", "proposed_event_count", 1.0),
        ("model_response", "proposed_fact_count", "1"),
        ("model_response", "narrative_byte_length", -1),
        ("model_response", "proposed_event_count", MAX_SAFE_INTEGER + 1),
        ("retry", "attempt", 0),
        ("retry", "attempt", -1),
        ("retry", "attempt", True),
        ("retry", "attempt", "1"),
        ("error", "error_code", "unknown"),
        ("model_request", "output_schema", "free-form"),
        ("tool_call", "outcome", "unknown"),
    ),
)
def test_transcript_payload_scalars_are_strict_and_allowlisted(
    kind: str, field: str, value: object
) -> None:
    payload = _payload(kind)
    payload[field] = value

    with pytest.raises(OBSERVATION_FAILURES):
        _transcript(kind, payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", True),
        ("provider", "Fake Provider"),
        ("provider", "9provider"),
        ("provider", "a" * 65),
        ("provider", "プロバイダ"),
        ("model", True),
        ("model", "model name"),
        ("model", "é-model"),
        ("model", "a" * 129),
    ),
)
def test_telemetry_provider_and_model_are_strict_ascii(field: str, value: object) -> None:
    with pytest.raises(OBSERVATION_FAILURES):
        _telemetry(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    tuple(
        (field, value)
        for field in (
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "latency_ms",
            "cost_microusd",
        )
        for value in (-1, True, 1.0, "1", MAX_SAFE_INTEGER + 1)
    )
    + (("attempt", 0), ("attempt", -1), ("attempt", True), ("attempt", "1")),
)
def test_telemetry_counters_and_attempt_are_strict(field: str, value: object) -> None:
    with pytest.raises(OBSERVATION_FAILURES):
        _telemetry(**{field: value})


@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        ("succeeded", None),
        ("timed_out", "timeout"),
        ("failed", "model_error"),
        ("rejected", "invalid_json"),
        ("rejected", "script_exhausted"),
        ("rejected", "budget_exceeded"),
    ),
)
def test_telemetry_status_and_error_code_mapping(status: str, error_code: str | None) -> None:
    record = _telemetry(status=status, error_code=error_code)

    assert record.status == status
    assert record.error_code == error_code


@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        ("succeeded", "model_error"),
        ("timed_out", None),
        ("timed_out", "model_error"),
        ("failed", "timeout"),
        ("failed", "script_exhausted"),
        ("rejected", "model_error"),
        ("rejected", "timeout"),
        ("rejected", "unknown"),
    ),
)
def test_telemetry_rejects_invalid_status_error_code_mapping(
    status: str, error_code: str | None
) -> None:
    with pytest.raises(OBSERVATION_FAILURES):
        _telemetry(status=status, error_code=error_code)


def test_failed_script_exhausted_is_rejected_at_record_boundary() -> None:
    with pytest.raises(OBSERVATION_FAILURES) as raised:
        _telemetry(status="failed", error_code="script_exhausted")

    _assert_safe_failure(raised.value, SENTINEL)


def test_fixed_validation_failure_does_not_leak_raw_input(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level("DEBUG")
    payload = {
        "text": "safe",
        "raw_provider_body": SENTINEL,
        "cause": SENTINEL,
        "api_key": SENTINEL,
    }

    with pytest.raises(OBSERVATION_FAILURES) as raised:
        _transcript("player_input", payload)

    _assert_safe_failure(raised.value, SENTINEL)
    captured = capsys.readouterr()
    assert SENTINEL not in f"{captured.out}\n{captured.err}\n{caplog.text}"
