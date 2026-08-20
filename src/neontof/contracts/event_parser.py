"""Raw JSON parsing and sanitized validation errors for canonical Domain Events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Literal, Never

from pydantic import Field, TypeAdapter, ValidationError

from neontof.contracts.base import ContractModel
from neontof.contracts.domain import DomainEvent

type IssueCode = Literal[
    "schema",
    "unknown_field",
    "unknown_event",
    "unknown_version",
    "invalid_id",
    "invalid_sequence",
    "invalid_payload",
]


class DomainEventValidationIssue(ContractModel):
    """A deliberately small error record that never stores input values."""

    path: str
    code: IssueCode
    message: str


class DomainEventValidationError(ValueError):
    """Validation failure with only sanitized, read-only issue details."""

    _issues: tuple[DomainEventValidationIssue, ...]
    __slots__ = ("_issues",)

    def __init__(self, issues: tuple[DomainEventValidationIssue, ...]) -> None:
        object.__setattr__(self, "_issues", issues)
        ValueError.__init__(self, "domain event validation failed")

    @property
    def issues(self) -> tuple[DomainEventValidationIssue, ...]:
        return self._issues


# These are the only adapters at the raw JSON boundary.  The first probes an
# object without accepting a decoded mapping as a public API; the second is
# the discriminated v1 contract; the third validates a JSON array of objects.
_RAW_EVENT_ADAPTER = TypeAdapter(dict[str, object])
_DOMAIN_EVENT_V1_ADAPTER: TypeAdapter[DomainEvent] = TypeAdapter(
    Annotated[DomainEvent, Field(discriminator="type")]
)
_SEQUENCE_JSON_ADAPTER = TypeAdapter(tuple[dict[str, object], ...])


_ID_PATHS = {
    "event_id",
    "campaign_id",
    "session_id",
    "scene_id",
    "turn_id",
    "visibility",
    "input_digest",
    "campaign_seed",
    "derived_seed",
    "scenario_id",
    "turn_request_id",
    "action_id",
    "resource_id",
    "entity_id",
    "character_id",
    "from_location_id",
    "to_location_id",
    "clock_id",
    "target_fact_id",
    "target_turn_id",
}
_EVENT_MODEL_NAMES = {
    "CampaignCreatedEvent",
    "SessionStartedEvent",
    "SceneStartedEvent",
    "SceneEndedEvent",
    "PlayerInputAcceptedEvent",
    "DiceRolledEvent",
    "ResourceChangedEvent",
    "CharacterMovedEvent",
    "ClockAdvancedEvent",
    "FactAssertedEvent",
    "FactSupersededEvent",
    "TurnAwaitingPlayerEvent",
    "TurnResumedEvent",
    "TurnAbortedEvent",
    "TurnCommittedEvent",
    "TurnRevertedEvent",
    "SessionEndedEvent",
}
_EVENT_TYPE_NAMES = {
    "CampaignCreated",
    "SessionStarted",
    "SceneStarted",
    "SceneEnded",
    "PlayerInputAccepted",
    "DiceRolled",
    "ResourceChanged",
    "CharacterMoved",
    "ClockAdvanced",
    "FactAsserted",
    "FactSuperseded",
    "TurnAwaitingPlayer",
    "TurnResumed",
    "TurnAborted",
    "TurnCommitted",
    "TurnReverted",
    "SessionEnded",
}
_TOP_LEVEL_PATH_SEGMENTS = {
    "type",
    "event_id",
    "event_version",
    "campaign_id",
    "session_id",
    "scene_id",
    "turn_id",
    "sequence",
    "occurred_at",
    "origin",
    "visibility",
    "payload",
}
_PAYLOAD_PATH_SEGMENTS = {
    "name",
    "scenario_id",
    "title",
    "label",
    "reason",
    "turn_request_id",
    "input_digest",
    "campaign_seed",
    "action_id",
    "roll_index",
    "derived_seed",
    "formula",
    "result",
    "resource_id",
    "entity_id",
    "delta",
    "character_id",
    "from_location_id",
    "to_location_id",
    "clock_id",
    "kind",
    "holder",
    "subject_id",
    "predicate",
    "value",
    "target_fact_id",
    "target_turn_id",
}
_REDACTED_PATH_SEGMENT = "field"


def _path_from_location(location: tuple[object, ...]) -> str:
    parts = list(location)
    while parts and (parts[0] in _EVENT_MODEL_NAMES or parts[0] in _EVENT_TYPE_NAMES):
        parts.pop(0)
    rendered: list[str] = []
    in_payload = False
    for part in parts:
        if isinstance(part, int):
            rendered.append(f"[{part}]")
        else:
            if part == "payload":
                safe_part = part
                in_payload = True
            else:
                known_segments = _PAYLOAD_PATH_SEGMENTS if in_payload else _TOP_LEVEL_PATH_SEGMENTS
                safe_part = (
                    part
                    if isinstance(part, str) and part in known_segments
                    else _REDACTED_PATH_SEGMENT
                )
            if rendered and not rendered[-1].endswith("]"):
                rendered.append(".")
            rendered.append(safe_part)
    return "".join(rendered)


def _issue_path(location: tuple[object, ...]) -> str:
    path = _path_from_location(location)
    return path or "event"


def _classify_validation_error(detail: Mapping[str, object], path: str) -> IssueCode:
    error_type = str(detail.get("type", ""))
    if error_type == "extra_forbidden":
        return "unknown_field"
    if path in {"type", "event"} and error_type in {
        "union_tag_invalid",
        "union_tag_not_found",
        "literal_error",
    }:
        return "unknown_event"
    if path == "event_version" and error_type in {
        "missing",
        "int_type",
        "int_parsing",
        "literal_error",
    }:
        return "unknown_version"
    if path.rsplit(".", 1)[-1] in _ID_PATHS:
        return "invalid_id"
    if error_type == "missing":
        return "schema"
    return "invalid_payload"


def _issues_from_validation_error(error: ValidationError) -> tuple[DomainEventValidationIssue, ...]:
    issues: list[DomainEventValidationIssue] = []
    for detail in error.errors(
        include_input=False,
        include_url=False,
        include_context=False,
    ):
        location = tuple(detail.get("loc", ()))
        path = _issue_path(location)
        if not location and detail.get("type") == "union_tag_invalid":
            path = "type"
        code = _classify_validation_error(detail, path)
        if code == "unknown_field":
            message = "unknown field"
        elif code == "unknown_event":
            message = "unknown event type"
        elif code == "unknown_version":
            message = "unknown event version"
        elif code == "invalid_id":
            message = f"invalid ID at {path}"
        elif code == "invalid_sequence":
            message = "invalid event sequence"
        elif code == "schema":
            message = "schema validation failed"
        else:
            message = f"invalid payload at {path}"
        issues.append(DomainEventValidationIssue(path=path, code=code, message=message))
    if not issues:
        issues.append(
            DomainEventValidationIssue(
                path="event",
                code="schema",
                message="schema validation failed",
            )
        )
    return tuple(issues)


def _ensure_raw(raw: object) -> str | bytes:
    if type(raw) is not str and type(raw) is not bytes:
        raise TypeError("raw must be str or bytes")
    return raw


def _version_issue(probe: dict[str, object]) -> tuple[DomainEventValidationIssue, ...] | None:
    if "event_version" not in probe:
        return None
    version = probe["event_version"]
    if type(version) is not int or version != 1:
        return (
            DomainEventValidationIssue(
                path="event_version",
                code="unknown_version",
                message="unknown event version",
            ),
        )
    return None


def parse_domain_event(raw: str | bytes) -> DomainEvent:
    """Parse one UTF-8 JSON object through the versioned contract boundary."""

    raw_value = _ensure_raw(raw)
    try:
        probe = _RAW_EVENT_ADAPTER.validate_json(raw_value, strict=True)
    except ValidationError as error:
        issues = _issues_from_validation_error(error)
    else:
        version_issue = _version_issue(probe)
        if version_issue is not None:
            return _raise_validation(version_issue)
        try:
            event = _DOMAIN_EVENT_V1_ADAPTER.validate_json(raw_value, strict=True)
        except ValidationError as error:
            issues = _issues_from_validation_error(error)
        else:
            return event
    return _raise_validation(issues)


def _prefix_issue(index: int, issue: DomainEventValidationIssue) -> DomainEventValidationIssue:
    path = f"events[{index}]"
    if issue.path:
        path += f".{issue.path}"
    return DomainEventValidationIssue(path=path, code=issue.code, message=issue.message)


def _sequence_issue(path: str, message: str) -> DomainEventValidationIssue:
    return DomainEventValidationIssue(path=path, code="invalid_sequence", message=message)


def parse_domain_event_sequence(raw: str | bytes) -> tuple[DomainEvent, ...]:
    """Parse a JSON array and validate its campaign-local canonical ordering."""

    raw_value = _ensure_raw(raw)
    try:
        raw_events = _SEQUENCE_JSON_ADAPTER.validate_json(raw_value, strict=True)
    except ValidationError as sequence_error:
        json_sequence_issues = _issues_from_validation_error(sequence_error)
        return _raise_validation(json_sequence_issues)

    parsed: list[DomainEvent] = []
    sequence_issues: list[DomainEventValidationIssue] = []
    for index, raw_event in enumerate(raw_events):
        element_raw = json.dumps(raw_event, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        try:
            parsed.append(parse_domain_event(element_raw))
        except DomainEventValidationError as error:
            sequence_issues.extend(_prefix_issue(index, issue) for issue in error.issues)

    sequence_values = [item.get("sequence") for item in raw_events]
    if sequence_values != list(range(1, len(raw_events) + 1)):
        sequence_issues.append(
            _sequence_issue("sequence", "event sequence must start at 1 without gaps")
        )
    event_ids = [item.get("event_id") for item in raw_events]
    known_event_ids = [event_id for event_id in event_ids if type(event_id) is str]
    if len(known_event_ids) != len(set(known_event_ids)):
        sequence_issues.append(_sequence_issue("event_id", "event IDs must be unique"))
    campaigns = [item.get("campaign_id") for item in raw_events]
    known_campaigns = {campaign for campaign in campaigns if type(campaign) is str}
    if len(known_campaigns) > 1:
        sequence_issues.append(_sequence_issue("campaign_id", "event campaign IDs must match"))

    if sequence_issues:
        return _raise_validation(tuple(sequence_issues))
    return tuple(parsed)


def _raise_validation(issues: tuple[DomainEventValidationIssue, ...]) -> Never:
    raise DomainEventValidationError(issues) from None
