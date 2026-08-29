"""Atomic append-only Event Store and complete campaign Event reads."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal, NoReturn

from neontof.contracts.domain import DomainEvent
from neontof.contracts.event_parser import (
    DomainEventValidationError,
    DomainEventValidationIssue,
    parse_domain_event,
)
from neontof.contracts.ids import CampaignId, SessionId, TurnId, TurnRequestId
from neontof.event_metadata import EventBatch, EventDraftBody, StoredEvent
from neontof.persistence.sqlite_database import SqliteDatabase

type EventStoreIssueCode = Literal["duplicate_event_id", "event_constraint_violation"]
type _ValidationIssueCode = Literal["schema", "invalid_payload", "invalid_sequence"]


class EventStoreConstraintError(ValueError):
    """Sanitized Event Store constraint failure."""

    __slots__ = ("code",)
    code: EventStoreIssueCode

    def __init__(self, code: EventStoreIssueCode) -> None:
        self.code = code
        ValueError.__init__(self, "event store constraint violation")


class _DuplicateObjectKeyError(ValueError):
    pass


def _duplicate_free_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateObjectKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    del value
    raise ValueError


def _validation_error(
    path: str,
    code: _ValidationIssueCode,
    message: str,
) -> DomainEventValidationError:
    issue = DomainEventValidationIssue(path=path, code=code, message=message)
    return DomainEventValidationError((issue,))


def _json_scalar(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _assemble_envelope(body: EventDraftBody, sequence: int) -> bytes:
    fields = (
        ("type", body.type),
        ("event_id", body.event_id),
        ("event_version", body.event_version),
        ("campaign_id", body.campaign_id),
        ("session_id", body.session_id),
        ("scene_id", body.scene_id),
        ("turn_id", body.turn_id),
        ("sequence", sequence),
        ("occurred_at", body.occurred_at),
        ("origin", body.origin),
        ("visibility", body.visibility),
    )
    pieces = [b"{"]
    for index, (name, value) in enumerate(fields):
        if index:
            pieces.append(b",")
        pieces.append(_json_scalar(name))
        pieces.append(b":")
        pieces.append(_json_scalar(value))
    pieces.extend((b',"payload":', body.payload_json, b"}"))
    return b"".join(pieces)


def _assert_event_scalar_fields(body: EventDraftBody, sequence: int, event: DomainEvent) -> None:
    expected = (
        ("type", body.type),
        ("event_id", body.event_id),
        ("event_version", body.event_version),
        ("campaign_id", body.campaign_id),
        ("session_id", body.session_id),
        ("scene_id", body.scene_id),
        ("turn_id", body.turn_id),
        ("sequence", sequence),
        ("occurred_at", body.occurred_at),
        ("origin", body.origin),
        ("visibility", body.visibility),
    )
    if any(
        type(getattr(event, field)) is not type(value) or getattr(event, field) != value
        for field, value in expected
    ):
        raise _validation_error("event", "invalid_payload", "event envelope validation failed")


def _assert_payload_span(assembled: bytes, payload_json: bytes) -> None:
    marker = b',"payload":'
    marker_start = assembled.find(marker)
    if marker_start < 0 or not assembled.endswith(b"}"):
        raise _validation_error("event", "invalid_payload", "payload boundary validation failed")
    payload_start = marker_start + len(marker)
    if assembled[payload_start:-1] != payload_json:
        raise _validation_error("event", "invalid_payload", "payload boundary validation failed")


def _parse_unique_json_object(raw: bytes) -> dict[str, object]:
    parse_failed = False
    value: object = None
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_free_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        parse_failed = True
    if parse_failed:
        raise _validation_error(
            "event", "invalid_payload", "event JSON validation failed"
        ) from None
    if not isinstance(value, dict):
        raise _validation_error("event", "invalid_payload", "event JSON validation failed")
    return value


def _materialize_event_json(
    *,
    body: EventDraftBody,
    sequence: int,
) -> tuple[bytes, DomainEvent]:
    """Validate raw payload bytes and assemble one assigned-sequence Event envelope."""

    parse_failed = False
    payload_value: object = None
    try:
        payload_text = body.payload_json.decode("utf-8", errors="strict")
        payload_value = json.loads(
            payload_text,
            object_pairs_hook=_duplicate_free_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError, json.JSONDecodeError, ValueError:
        parse_failed = True
    if parse_failed:
        raise _validation_error(
            "payload", "invalid_payload", "payload must be one JSON object"
        ) from None
    if not isinstance(payload_value, dict):
        raise _validation_error("payload", "invalid_payload", "payload must be one JSON object")
    if type(sequence) is not int or sequence <= 0:
        raise _validation_error("sequence", "invalid_sequence", "invalid event sequence")

    assembled = _assemble_envelope(body, sequence)
    _parse_unique_json_object(assembled)
    event = parse_domain_event(assembled)
    _assert_event_scalar_fields(body, sequence, event)
    _assert_payload_span(assembled, body.payload_json)
    return assembled, event


def _readback_event(row: tuple[Any, ...], expected_sequence: int) -> DomainEvent:
    if len(row) != 12:
        raise _validation_error("event", "schema", "event readback validation failed")
    (
        campaign_id,
        sequence,
        event_id,
        event_type,
        event_version,
        session_id,
        scene_id,
        turn_id,
        occurred_at,
        origin,
        visibility,
        event_json,
    ) = row
    if type(event_json) is not bytes:
        raise _validation_error("event", "invalid_payload", "invalid event JSON storage")
    _parse_unique_json_object(event_json)
    event = parse_domain_event(event_json)
    if type(sequence) is not int or sequence != expected_sequence:
        raise _validation_error("sequence", "invalid_sequence", "invalid event sequence")
    expected = (
        ("campaign_id", campaign_id),
        ("sequence", sequence),
        ("event_id", event_id),
        ("type", event_type),
        ("event_version", event_version),
        ("session_id", session_id),
        ("scene_id", scene_id),
        ("turn_id", turn_id),
        ("occurred_at", occurred_at),
        ("origin", origin),
        ("visibility", visibility),
    )
    if any(
        type(getattr(event, field)) is not type(value) or getattr(event, field) != value
        for field, value in expected
    ):
        raise _validation_error("event", "invalid_payload", "event readback validation failed")
    return event


class EventStore:
    """The sole owner of DomainEvent append and typed Event Log reads."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def append(self, batch: EventBatch) -> tuple[StoredEvent, ...]:
        if any(draft.body.campaign_id != batch.campaign_id for draft in batch.drafts):
            raise _validation_error(
                "campaign_id", "invalid_sequence", "event campaign IDs must match"
            )
        if not batch.drafts:
            return ()

        def operation(connection: sqlite3.Connection) -> tuple[StoredEvent, ...]:
            existing_ids: set[str] = set()
            for draft in batch.drafts:
                event_id = draft.body.event_id
                if event_id in existing_ids:
                    raise EventStoreConstraintError("duplicate_event_id")
                existing_ids.add(event_id)
                if (
                    connection.execute(
                        "SELECT 1 FROM events WHERE event_id = ?", (event_id,)
                    ).fetchone()
                    is not None
                ):
                    raise EventStoreConstraintError("duplicate_event_id")

            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE campaign_id = ?",
                (batch.campaign_id,),
            ).fetchone()
            last_sequence = sequence_row[0] if sequence_row is not None else 0
            if type(last_sequence) is not int or last_sequence < 0:
                raise _validation_error("sequence", "invalid_sequence", "invalid event sequence")

            stored: list[StoredEvent] = []
            for offset, draft in enumerate(batch.drafts, start=1):
                sequence = last_sequence + offset
                event_json, event = _materialize_event_json(
                    body=draft.body,
                    sequence=sequence,
                )
                integrity_failed = False
                try:
                    connection.execute(
                        "INSERT INTO events("
                        "campaign_id, sequence, event_id, type, event_version, session_id, "
                        "scene_id, turn_id, occurred_at, origin, visibility, event_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            batch.campaign_id,
                            sequence,
                            event.event_id,
                            event.type,
                            event.event_version,
                            event.session_id,
                            event.scene_id,
                            event.turn_id,
                            event.occurred_at,
                            event.origin,
                            event.visibility,
                            sqlite3.Binary(event_json),
                        ),
                    )
                except sqlite3.IntegrityError:
                    integrity_failed = True
                if integrity_failed:
                    raise EventStoreConstraintError("event_constraint_violation")
                stored.append(
                    StoredEvent(
                        campaign_id=batch.campaign_id,
                        sequence=sequence,
                        event=event,
                    )
                )
            return tuple(stored)

        return self._database._write(operation)

    def read_campaign(self, campaign_id: CampaignId) -> tuple[DomainEvent, ...]:
        return self._database._read(
            lambda connection: self._read_campaign_on_connection(connection, campaign_id)
        )

    def read_session(
        self, campaign_id: CampaignId, session_id: SessionId
    ) -> tuple[DomainEvent, ...]:
        events = self.read_campaign(campaign_id)
        return tuple(event for event in events if event.session_id == session_id)

    def read_turn(self, campaign_id: CampaignId, turn_id: TurnId) -> tuple[DomainEvent, ...]:
        events = self.read_campaign(campaign_id)
        return tuple(
            event
            for event in events
            if event.turn_id == turn_id
            or (
                event.type == "TurnReverted"
                and getattr(event.payload, "target_turn_id", None) == turn_id
            )
        )

    def find_turn_by_request(
        self, campaign_id: CampaignId, turn_request_id: TurnRequestId
    ) -> tuple[DomainEvent, ...]:
        events = self.read_campaign(campaign_id)
        return tuple(
            event
            for event in events
            if event.type == "PlayerInputAccepted"
            and getattr(event.payload, "turn_request_id", None) == turn_request_id
        )

    def _read_campaign_on_connection(
        self,
        connection: sqlite3.Connection,
        campaign_id: CampaignId,
    ) -> tuple[DomainEvent, ...]:
        rows = connection.execute(
            "SELECT campaign_id, sequence, event_id, type, event_version, session_id, "
            "scene_id, turn_id, occurred_at, origin, visibility, event_json "
            "FROM events WHERE campaign_id = ? ORDER BY sequence ASC",
            (campaign_id,),
        ).fetchall()
        validated: list[DomainEvent] = []
        for expected_sequence, row in enumerate(rows, start=1):
            validated.append(_readback_event(tuple(row), expected_sequence))
        return tuple(validated)
