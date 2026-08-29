"""Append-only Transcript and Telemetry persistence outside Event transactions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, NoReturn

from neontof.contracts.ids import CampaignId, SessionId, TurnId
from neontof.model.model_invoker import Role
from neontof.observability.records import (
    ObservationValidationError,
    TelemetryRecord,
    TranscriptRecord,
)
from neontof.observability.sanitization import sanitize_observation
from neontof.persistence.sqlite_database import SqliteDatabase


def _invalid() -> NoReturn:
    raise ObservationValidationError()


def _duplicate_free_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate observation JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    del value
    raise ValueError("invalid observation JSON number")


def _json_ready(value: object) -> object:
    if type(value) is tuple:
        if value and all(
            type(item) is tuple and len(item) == 2 and type(item[0]) is str for item in value
        ):
            return {item[0]: _json_ready(item[1]) for item in value}
        return [_json_ready(item) for item in value]
    if type(value) is list:
        return [_json_ready(item) for item in value]
    return value


def _frozen_object_to_dict(value: object) -> dict[str, object]:
    if type(value) is not tuple:
        _invalid()
    if not all(type(item) is tuple and len(item) == 2 and type(item[0]) is str for item in value):
        _invalid()
    result: dict[str, object] = {}
    for item in value:
        key = item[0]
        if key in result:
            _invalid()
        result[key] = item[1]
    return result


def _canonical_json_bytes(value: object) -> bytes:
    failed = False
    encoded: bytes | None = None
    try:
        ready = _json_ready(sanitize_observation(value))
        encoded = json.dumps(
            ready,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except AttributeError, RecursionError, TypeError, UnicodeError, ValueError:
        failed = True
    if failed or encoded is None:
        _invalid()
    return encoded


def _canonical_json_array_bytes(value: object) -> bytes:
    failed = False
    encoded: bytes | None = None
    try:
        sanitized = sanitize_observation(value)
        if type(sanitized) is not tuple:
            failed = True
        else:
            encoded = json.dumps(
                [_json_ready(item) for item in sanitized],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8", errors="strict")
    except AttributeError, RecursionError, TypeError, UnicodeError, ValueError:
        failed = True
    if failed or encoded is None:
        _invalid()
    return encoded


def _next_sequence(connection: sqlite3.Connection, table: str, campaign_id: str) -> int:
    row = connection.execute(
        f"SELECT COALESCE(MAX(append_sequence), 0) FROM {table} WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    if row is None or type(row[0]) is not int or row[0] < 0:
        _invalid()
    return row[0] + 1


def _revalidate_transcript(record: object) -> TranscriptRecord:
    result: TranscriptRecord | None = None
    validation_failed = False
    try:
        if type(record) is not TranscriptRecord:
            validation_failed = True
        else:
            data = _frozen_object_to_dict(record.data)
            result = TranscriptRecord(
                entry_id=record.entry_id,
                campaign_id=record.campaign_id,
                session_id=record.session_id,
                turn_id=record.turn_id,
                model_call_id=record.model_call_id,
                kind=record.kind,
                occurred_at=record.occurred_at,
                data=data,
            )
    except (
        AttributeError,
        KeyError,
        ObservationValidationError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        validation_failed = True
    if validation_failed or result is None:
        _invalid()
    return result


def _revalidate_telemetry(record: object) -> TelemetryRecord:
    result: TelemetryRecord | None = None
    validation_failed = False
    try:
        if type(record) is not TelemetryRecord:
            validation_failed = True
        else:
            result = TelemetryRecord(
                entry_id=record.entry_id,
                campaign_id=record.campaign_id,
                session_id=record.session_id,
                turn_id=record.turn_id,
                model_call_id=record.model_call_id,
                provider=record.provider,
                model=record.model,
                roles=record.roles,
                attempt=record.attempt,
                status=record.status,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                cached_tokens=record.cached_tokens,
                latency_ms=record.latency_ms,
                cost_microusd=record.cost_microusd,
                error_code=record.error_code,
                occurred_at=record.occurred_at,
            )
    except (
        AttributeError,
        ObservationValidationError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        validation_failed = True
    if validation_failed or result is None:
        _invalid()
    return result


def _decode_json_object(raw: object) -> dict[str, object] | None:
    value: object = None
    parse_failed = False
    try:
        if type(raw) is not bytes:
            parse_failed = True
        else:
            value = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_duplicate_free_object,
                parse_constant=_reject_json_constant,
            )
    except RecursionError, TypeError, UnicodeError, ValueError:
        parse_failed = True
    if parse_failed or type(value) is not dict:
        return None
    return value


def _decode_json_array(raw: object) -> list[object] | None:
    value: object = None
    parse_failed = False
    try:
        if type(raw) is not bytes:
            parse_failed = True
        else:
            value = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_duplicate_free_object,
                parse_constant=_reject_json_constant,
            )
    except RecursionError, TypeError, UnicodeError, ValueError:
        parse_failed = True
    if parse_failed or type(value) is not list:
        return None
    return value


def _role_value(value: object) -> Role | None:
    if value == "referee":
        return "referee"
    if value == "world_simulator":
        return "world_simulator"
    if value == "npc_actor":
        return "npc_actor"
    if value == "narrator":
        return "narrator"
    return None


def _transcript_from_row(row: tuple[Any, ...]) -> TranscriptRecord | None:
    record: TranscriptRecord | None = None
    read_failed = False
    try:
        if len(row) != 9:
            read_failed = True
        else:
            data = _decode_json_object(row[8])
            if data is None:
                read_failed = True
            else:
                record = TranscriptRecord(
                    entry_id=row[2],
                    campaign_id=row[0],
                    session_id=row[3],
                    turn_id=row[4],
                    model_call_id=row[5],
                    kind=row[6],
                    occurred_at=row[7],
                    data=data,
                )
    except (
        AttributeError,
        KeyError,
        ObservationValidationError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        read_failed = True
    if read_failed:
        return None
    return record


def _telemetry_from_row(row: tuple[Any, ...]) -> TelemetryRecord | None:
    record: TelemetryRecord | None = None
    read_failed = False
    try:
        if len(row) != 18:
            read_failed = True
        else:
            roles = _decode_json_array(row[8])
            if roles is None:
                read_failed = True
            else:
                role_values: list[Role] = []
                for role in roles:
                    role_value = _role_value(role)
                    if role_value is None:
                        read_failed = True
                        break
                    role_values.append(role_value)
            if not read_failed and roles is not None:
                record = TelemetryRecord(
                    entry_id=row[2],
                    campaign_id=row[0],
                    session_id=row[3],
                    turn_id=row[4],
                    model_call_id=row[5],
                    provider=row[6],
                    model=row[7],
                    roles=tuple(role_values),
                    attempt=row[9],
                    status=row[10],
                    input_tokens=row[11],
                    output_tokens=row[12],
                    cached_tokens=row[13],
                    latency_ms=row[14],
                    cost_microusd=row[15],
                    error_code=row[16],
                    occurred_at=row[17],
                )
    except (
        AttributeError,
        KeyError,
        ObservationValidationError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        read_failed = True
    if read_failed:
        return None
    return record


class ObservationStore:
    """Own observation tables without entering the Event Store transaction."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def append_transcript(self, record: TranscriptRecord) -> None:
        canonical = _revalidate_transcript(record)
        data = _frozen_object_to_dict(canonical.data)
        data_json = _canonical_json_bytes(data)

        def operation(connection: sqlite3.Connection) -> None:
            append_sequence = _next_sequence(
                connection, "transcript_entries", canonical.campaign_id
            )
            connection.execute(
                "INSERT INTO transcript_entries("
                "campaign_id, append_sequence, entry_id, session_id, turn_id, model_call_id, "
                "kind, occurred_at, data_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    canonical.campaign_id,
                    append_sequence,
                    canonical.entry_id,
                    canonical.session_id,
                    canonical.turn_id,
                    canonical.model_call_id,
                    canonical.kind,
                    canonical.occurred_at,
                    sqlite3.Binary(data_json),
                ),
            )

        self._database._write(operation)

    def append_telemetry(self, record: TelemetryRecord) -> None:
        canonical = _revalidate_telemetry(record)
        roles_json = _canonical_json_array_bytes(list(canonical.roles))

        def operation(connection: sqlite3.Connection) -> None:
            append_sequence = _next_sequence(connection, "telemetry_entries", canonical.campaign_id)
            connection.execute(
                "INSERT INTO telemetry_entries("
                "campaign_id, append_sequence, entry_id, session_id, turn_id, model_call_id, "
                "provider, model, roles_json, attempt, status, input_tokens, output_tokens, "
                "cached_tokens, latency_ms, cost_microusd, error_code, occurred_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    canonical.campaign_id,
                    append_sequence,
                    canonical.entry_id,
                    canonical.session_id,
                    canonical.turn_id,
                    canonical.model_call_id,
                    canonical.provider,
                    canonical.model,
                    sqlite3.Binary(roles_json),
                    canonical.attempt,
                    canonical.status,
                    canonical.input_tokens,
                    canonical.output_tokens,
                    canonical.cached_tokens,
                    canonical.latency_ms,
                    canonical.cost_microusd,
                    canonical.error_code,
                    canonical.occurred_at,
                ),
            )

        self._database._write(operation)

    def read_transcript(
        self, campaign_id: CampaignId, turn_id: TurnId | None = None
    ) -> tuple[TranscriptRecord, ...]:
        if turn_id is None:
            rows = self._database._read(
                lambda connection: connection.execute(
                    "SELECT campaign_id, append_sequence, entry_id, session_id, turn_id, "
                    "model_call_id, kind, occurred_at, data_json FROM transcript_entries "
                    "WHERE campaign_id = ? ORDER BY append_sequence",
                    (campaign_id,),
                ).fetchall()
            )
        else:
            rows = self._database._read(
                lambda connection: connection.execute(
                    "SELECT campaign_id, append_sequence, entry_id, session_id, turn_id, "
                    "model_call_id, kind, occurred_at, data_json FROM transcript_entries "
                    "WHERE campaign_id = ? AND turn_id = ? ORDER BY append_sequence",
                    (campaign_id, turn_id),
                ).fetchall()
            )
        records: list[TranscriptRecord] = []
        read_failed = False
        for row in rows:
            record = _transcript_from_row(tuple(row))
            if record is None:
                read_failed = True
            else:
                records.append(record)
        if read_failed:
            _invalid()
        return tuple(records)

    def read_telemetry(
        self, campaign_id: CampaignId, turn_id: TurnId | None = None
    ) -> tuple[TelemetryRecord, ...]:
        select = (
            "SELECT campaign_id, append_sequence, entry_id, session_id, turn_id, model_call_id, "
            "provider, model, roles_json, attempt, status, input_tokens, output_tokens, "
            "cached_tokens, latency_ms, cost_microusd, error_code, occurred_at "
            "FROM telemetry_entries "
        )
        if turn_id is None:
            rows = self._database._read(
                lambda connection: connection.execute(
                    select + "WHERE campaign_id = ? ORDER BY append_sequence", (campaign_id,)
                ).fetchall()
            )
        else:
            rows = self._database._read(
                lambda connection: connection.execute(
                    select + "WHERE campaign_id = ? AND turn_id = ? ORDER BY append_sequence",
                    (campaign_id, turn_id),
                ).fetchall()
            )
        records: list[TelemetryRecord] = []
        read_failed = False
        for row in rows:
            record = _telemetry_from_row(tuple(row))
            if record is None:
                read_failed = True
            else:
                records.append(record)
        if read_failed:
            _invalid()
        return tuple(records)

    def session_cost_microusd(self, campaign_id: CampaignId, session_id: SessionId) -> int:
        rows = self._database._read(
            lambda connection: connection.execute(
                "SELECT cost_microusd FROM telemetry_entries "
                "WHERE campaign_id = ? AND session_id = ? ORDER BY append_sequence",
                (campaign_id, session_id),
            ).fetchall()
        )
        total = 0
        read_failed = False
        for row in rows:
            if len(row) != 1 or type(row[0]) is not int or row[0] < 0:
                read_failed = True
                break
            total += row[0]
        if read_failed:
            _invalid()
        return total


__all__ = ("ObservationStore",)
