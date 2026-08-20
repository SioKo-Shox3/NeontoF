"""Raw JSON parser、sequence validation、redactionの契約テスト。"""

import inspect
import json
import logging
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "events"
EVENT_FIXTURES = (
    "minimal-session.v1.json",
    "invalid-unknown-field.v1.json",
    "invalid-unknown-version.v1.json",
    "invalid-unknown-event.v1.json",
    "invalid-payloads.v1.json",
    "turn-status-sequences.v1.json",
    "same-request-resend.v1.json",
)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _minimal_event(index: int = 0) -> dict[str, Any]:
    decoded = json.loads(_fixture_bytes("minimal-session.v1.json"))
    assert isinstance(decoded, list)
    event = decoded[index]
    assert isinstance(event, dict)
    return {str(key): value for key, value in event.items()}


def _mutate_raw_event(
    event: dict[str, Any],
    path: tuple[str, ...],
    value: object = None,
    *,
    remove: bool = False,
) -> None:
    target = event
    for segment in path[:-1]:
        nested = target[segment]
        assert isinstance(nested, dict)
        target = nested
    if remove:
        del target[path[-1]]
    else:
        target[path[-1]] = value


def _assert_redacted(error: BaseException, sentinels: str | tuple[str, ...]) -> None:
    values = (sentinels,) if isinstance(sentinels, str) else sentinels
    surfaces = (
        str(error),
        repr(error),
        repr(error.args),
        repr(error.__dict__),
        repr(error.__cause__),
        repr(error.__context__),
        str(getattr(error, "issues", ())),
        repr(getattr(error, "issues", ())),
    )
    for sentinel in values:
        assert all(sentinel not in surface for surface in surfaces)
        for issue in getattr(error, "issues", ()):
            assert sentinel not in str(issue)
            assert sentinel not in repr(issue)


def test_public_parser_signatures_accept_only_raw_text_or_bytes() -> None:
    from neontof.contracts.domain import DomainEvent
    from neontof.contracts.event_parser import parse_domain_event, parse_domain_event_sequence

    event_hints = get_type_hints(parse_domain_event)
    sequence_hints = get_type_hints(parse_domain_event_sequence)
    assert event_hints["raw"] == str | bytes
    assert sequence_hints["raw"] == str | bytes
    assert event_hints["return"] is DomainEvent
    assert "Sequence" not in str(inspect.signature(parse_domain_event))
    assert "Mapping" not in str(inspect.signature(parse_domain_event_sequence))


def test_raw_bytes_and_text_parse_at_the_json_boundary() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event,
        parse_domain_event_sequence,
    )

    raw = b"""{
      "type": "CampaignCreated",
      "event_id": "event:single",
      "event_version": 1,
      "campaign_id": "campaign:alpha",
      "session_id": null,
      "scene_id": null,
      "turn_id": null,
      "sequence": 1,
      "occurred_at": "2026-08-19T14:00:01Z",
      "origin": "in_world",
      "visibility": "gm_only",
      "payload": {"name": "NeontoF"}
    }"""

    event_from_bytes = parse_domain_event(raw)
    event_from_text = parse_domain_event(raw.decode("utf-8"))
    assert event_from_bytes == event_from_text
    assert event_from_bytes.event_id == "event:single"

    with pytest.raises(DomainEventValidationError):
        parse_domain_event_sequence(raw)


def test_decoded_mapping_and_wrong_python_types_are_rejected_without_repr_leak() -> None:
    from neontof.contracts.event_parser import parse_domain_event, parse_domain_event_sequence

    mapping_input: Any = {"type": "CampaignCreated", "secret": "mapping-sentinel"}
    sequence_input: Any = [{"type": "CampaignCreated"}]
    with pytest.raises(TypeError) as mapping_raised:
        parse_domain_event(mapping_input)
    assert str(mapping_raised.value) == "raw must be str or bytes"
    assert repr(mapping_input) not in str(mapping_raised.value)
    assert mapping_raised.value.args == ("raw must be str or bytes",)

    with pytest.raises(TypeError) as sequence_raised:
        parse_domain_event_sequence(sequence_input)
    assert str(sequence_raised.value) == "raw must be str or bytes"
    assert repr(sequence_input) not in str(sequence_raised.value)
    assert sequence_raised.value.args == ("raw must be str or bytes",)

    wrong_object: Any = object()
    with pytest.raises(TypeError) as object_raised:
        parse_domain_event(wrong_object)
    assert str(object_raised.value) == "raw must be str or bytes"
    assert repr(wrong_object) not in str(object_raised.value)
    assert object_raised.value.args == ("raw must be str or bytes",)


def test_unknown_fields_version_and_event_are_sanitized_validation_errors() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )

    expected_codes = {
        "invalid-unknown-field.v1.json": {"unknown_field"},
        "invalid-unknown-version.v1.json": {"unknown_version"},
        "invalid-unknown-event.v1.json": {"unknown_event"},
    }
    for filename, required_codes in expected_codes.items():
        raw = _fixture_bytes(filename)
        if filename == "invalid-unknown-field.v1.json":
            decoded = json.loads(raw)
            assert "unexpected_top_level" in decoded[0]
            assert "unexpected_payload" in decoded[1]["payload"]
        with pytest.raises(DomainEventValidationError) as raised:
            parse_domain_event_sequence(raw)
        assert required_codes <= {issue.code for issue in raised.value.issues}
        assert isinstance(raised.value, ValueError)
        assert raised.value.__dict__ == {}
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


def test_invalid_payload_fixture_covers_wire_and_sequence_failures() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )

    raw = _fixture_bytes("invalid-payloads.v1.json")
    assert b"2026-02-30T11:30:02Z" in raw
    assert b"2026-08-19T11:30:03+00:00" in raw
    assert b"2026-08-19T11:30:04.123Z" in raw
    assert b"2026-08-19T11:30:05z" in raw
    assert b'"delta": true' in raw
    assert b'"origin": "system"' in raw
    with pytest.raises(DomainEventValidationError) as raised:
        parse_domain_event_sequence(raw)
    codes = {issue.code for issue in raised.value.issues}
    assert codes & {"invalid_id", "invalid_payload", "schema"}
    assert "invalid_sequence" in codes

    missing_sequence = _fixture_bytes("minimal-session.v1.json").replace(
        b'"sequence": 27', b'"sequence": 28'
    )
    with pytest.raises(DomainEventValidationError) as missing:
        parse_domain_event_sequence(missing_sequence)
    assert "invalid_sequence" in {issue.code for issue in missing.value.issues}

    duplicate_event_id = _fixture_bytes("minimal-session.v1.json").replace(
        b'"event_id": "event:e27"', b'"event_id": "event:e26"'
    )
    with pytest.raises(DomainEventValidationError) as duplicate:
        parse_domain_event_sequence(duplicate_event_id)
    assert "invalid_sequence" in {issue.code for issue in duplicate.value.issues}


@pytest.mark.parametrize(
    ("event_index", "mutations", "expected_code", "expected_path"),
    [
        pytest.param(
            0,
            ((("occurred_at",), "2026-02-30T11:30:02Z", False),),
            "invalid_payload",
            "occurred_at",
            id="nonexistent-utc-timestamp",
        ),
        pytest.param(
            0,
            ((("occurred_at",), "2026-08-19T11:30:03", False),),
            "invalid_payload",
            "occurred_at",
            id="local-time-timestamp",
        ),
        pytest.param(
            0,
            ((("occurred_at",), "2026-08-19T11:30:03+00:00", False),),
            "invalid_payload",
            "occurred_at",
            id="offset-timestamp",
        ),
        pytest.param(
            0,
            ((("occurred_at",), "2026-08-19T11:30:04.123Z", False),),
            "invalid_payload",
            "occurred_at",
            id="fractional-timestamp",
        ),
        pytest.param(
            0,
            ((("occurred_at",), "2026-08-19T11:30:05z", False),),
            "invalid_payload",
            "occurred_at",
            id="lowercase-z-timestamp",
        ),
        pytest.param(
            25,
            ((("origin",), "system", False),),
            "invalid_payload",
            "origin",
            id="system-origin",
        ),
        pytest.param(
            8,
            ((("payload", "delta"), True, False),),
            "invalid_payload",
            "payload.delta",
            id="bool-as-int",
        ),
        pytest.param(
            8,
            ((("payload", "delta"), "1", False),),
            "invalid_payload",
            "payload.delta",
            id="string-numeric-payload",
        ),
        pytest.param(
            0,
            ((("campaign_id",), "Campaign:Alpha", False),),
            "invalid_id",
            "campaign_id",
            id="campaign-id-grammar",
        ),
        pytest.param(
            0,
            ((("event_id",), "event:P08", False),),
            "invalid_id",
            "event_id",
            id="event-id-grammar",
        ),
        pytest.param(
            3,
            ((("turn_id",), "turn:One", False),),
            "invalid_id",
            "turn_id",
            id="turn-id-grammar",
        ),
        pytest.param(
            3,
            ((("payload", "input_digest"), "not-a-sha256", False),),
            "invalid_id",
            "payload.input_digest",
            id="input-digest-grammar",
        ),
        pytest.param(
            1,
            ((("session_id",), "Session:one", False),),
            "invalid_id",
            "session_id",
            id="session-id-grammar",
        ),
        pytest.param(
            2,
            ((("scene_id",), "scene:Hall", False),),
            "invalid_id",
            "scene_id",
            id="scene-id-grammar",
        ),
        pytest.param(
            1,
            ((("payload", "scenario_id"), "scenario:Minimal", False),),
            "invalid_id",
            "payload.scenario_id",
            id="scenario-id-grammar",
        ),
        pytest.param(
            3,
            ((("payload", "turn_request_id"), "turn-request:One", False),),
            "invalid_id",
            "payload.turn_request_id",
            id="turn-request-id-grammar",
        ),
        pytest.param(
            5,
            ((("payload", "action_id"), "action:Open-door", False),),
            "invalid_id",
            "payload.action_id",
            id="action-id-grammar",
        ),
        pytest.param(
            6,
            ((("payload", "resource_id"), "resource:Gold", False),),
            "invalid_id",
            "payload.resource_id",
            id="resource-id-grammar",
        ),
        pytest.param(
            6,
            ((("payload", "entity_id"), "entity:Hero", False),),
            "invalid_id",
            "payload.entity_id",
            id="entity-id-grammar",
        ),
        pytest.param(
            7,
            ((("payload", "character_id"), "character:Hero", False),),
            "invalid_id",
            "payload.character_id",
            id="character-id-grammar",
        ),
        pytest.param(
            16,
            ((("payload", "from_location_id"), "location:Gate", False),),
            "invalid_id",
            "payload.from_location_id",
            id="from-location-id-grammar",
        ),
        pytest.param(
            7,
            ((("payload", "to_location_id"), "location:Gate", False),),
            "invalid_id",
            "payload.to_location_id",
            id="to-location-id-grammar",
        ),
        pytest.param(
            8,
            ((("payload", "clock_id"), "clock:Session", False),),
            "invalid_id",
            "payload.clock_id",
            id="clock-id-grammar",
        ),
        pytest.param(
            20,
            (
                (
                    ("payload", "target_fact_id"),
                    "fact:g27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d0:0",
                    False,
                ),
            ),
            "invalid_id",
            "payload.target_fact_id",
            id="target-fact-id-grammar",
        ),
        pytest.param(
            25,
            ((("payload", "target_turn_id"), "turn:Two", False),),
            "invalid_id",
            "payload.target_turn_id",
            id="target-turn-id-grammar",
        ),
        pytest.param(
            0,
            ((("payload", "name"), None, True),),
            "schema",
            "payload.name",
            id="missing-payload-field",
        ),
        pytest.param(
            0,
            ((("payload", "unexpected_payload"), "rejected", False),),
            "unknown_field",
            "payload.unexpected_payload",
            id="unknown-payload-field",
        ),
        pytest.param(
            0,
            (
                (("type",), "TurnStarted", False),
                (("payload",), {}, False),
            ),
            "unknown_event",
            "type",
            id="unknown-turn-started",
        ),
        pytest.param(
            0,
            (
                (("type",), "EmptyPayload", False),
                (("payload",), {}, False),
            ),
            "unknown_event",
            "type",
            id="unknown-empty-payload",
        ),
        pytest.param(
            0,
            ((("unexpected_top_level",), "rejected", False),),
            "unknown_field",
            "unexpected_top_level",
            id="unknown-top-level-field",
        ),
        pytest.param(
            0,
            ((("event_version",), 2, False),),
            "unknown_version",
            "event_version",
            id="unknown-version",
        ),
    ],
)
def test_each_invalid_payload_is_rejected_independently(
    event_index: int,
    mutations: tuple[tuple[tuple[str, ...], object, bool], ...],
    expected_code: str,
    expected_path: str,
) -> None:
    from neontof.contracts.event_parser import DomainEventValidationError, parse_domain_event

    event = _minimal_event(event_index)
    for path, value, remove in mutations:
        _mutate_raw_event(event, path, value, remove=remove)

    with pytest.raises(DomainEventValidationError) as raised:
        parse_domain_event(json.dumps(event).encode("utf-8"))

    assert any(
        issue.code == expected_code and issue.path == expected_path for issue in raised.value.issues
    )


def test_validation_issue_is_frozen_and_has_only_sanitized_fields() -> None:
    from neontof.contracts.event_parser import DomainEventValidationIssue

    issue = DomainEventValidationIssue(
        path="payload.delta",
        code="invalid_payload",
        message="invalid payload",
    )
    assert tuple(issue.model_fields) == ("path", "code", "message")
    assert set(issue.__dict__) == {"path", "code", "message"}
    with pytest.raises(ValidationError):
        issue.message = "changed"
    with pytest.raises(ValidationError):
        DomainEventValidationIssue.model_validate(
            {
                "path": "payload.delta",
                "code": "invalid_payload",
                "message": "invalid payload",
                "input_value": "must not be retained",
            }
        )


def test_json_decode_and_validation_errors_redact_every_observable_surface(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from neontof.contracts.event_parser import DomainEventValidationError, parse_domain_event

    sentinel = "RAW_INPUT_SECRET_SENTINEL"
    malformed_json = b'{"type":"CampaignCreated","campaign_id":"' + sentinel.encode() + b'"'
    with pytest.raises(DomainEventValidationError) as raised:
        parse_domain_event(malformed_json)
    error = raised.value
    _assert_redacted(error, sentinel)
    assert error.__dict__ == {}
    assert error.__cause__ is None
    assert error.__context__ is None
    assert isinstance(error.issues, tuple)
    with pytest.raises(AttributeError):
        object.__setattr__(error, "issues", ())

    caplog.set_level(logging.ERROR)
    logging.getLogger("neontof.contracts").error("validation failed: %s", error)
    assert sentinel not in caplog.text


def test_valid_json_schema_and_payload_errors_redact_secret_api_key_and_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from neontof.contracts.event_parser import DomainEventValidationError, parse_domain_event

    secret = "VALID_JSON_SECRET_SENTINEL"
    api_key = "sk-valid-json-api-key-sentinel"
    url = "https://valid-json.example.test/secret"
    event = _minimal_event()
    event["payload"] = {
        "name": {"secret": secret, "api_key": api_key, "url": url},
    }
    raw = json.dumps(event).encode("utf-8")
    json.loads(raw)

    with pytest.raises(DomainEventValidationError) as raised:
        parse_domain_event(raw)
    error = raised.value
    assert any(
        issue.path == "payload.name" and issue.code in {"schema", "invalid_payload"}
        for issue in error.issues
    )
    _assert_redacted(error, (secret, api_key, url))
    assert error.__dict__ == {}
    assert error.__cause__ is None
    assert error.__context__ is None

    caplog.set_level(logging.ERROR)
    logging.getLogger("neontof.contracts").error("validation failed: %s", error)
    for sentinel in (secret, api_key, url):
        assert sentinel not in caplog.text


def test_wrong_timestamp_forms_and_strict_bool_are_rejected_from_raw_fixture() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )

    raw = _fixture_bytes("invalid-payloads.v1.json")
    with pytest.raises(DomainEventValidationError) as raised:
        parse_domain_event_sequence(raw)
    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "occurred_at" in messages or "invalid" in messages
    assert any(issue.path.endswith("delta") for issue in raised.value.issues)


@pytest.mark.parametrize("filename", EVENT_FIXTURES)
def test_event_fixtures_are_valid_json_without_secret_material(filename: str) -> None:
    raw_text = _fixture_bytes(filename).decode("utf-8")
    json.loads(raw_text)
    lower_text = raw_text.lower()
    for forbidden in (
        "secret",
        "narrative",
        "transcript",
        "telemetry",
        "raw_input",
        "api_key",
        "api-key",
        "api key",
    ):
        assert forbidden not in lower_text


def test_invalid_fixture_files_are_still_valid_utf8_json() -> None:
    for filename in EVENT_FIXTURES[1:]:
        decoded = json.loads(_fixture_bytes(filename))
        assert isinstance(decoded, list)
