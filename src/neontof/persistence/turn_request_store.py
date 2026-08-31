"""Durable turn request claims, recovery payloads, and response cache."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from neontof.application.turn_models import (
    CachedTurnResponse,
    ClaimResult,
    ExistingFinalClaim,
    ExistingProcessingClaim,
    FinalTurnRequestRecord,
    NewClaim,
    NonEmptyBytes,
    OpaqueRequestKey,
    ProcessingTurnRequestRecord,
    RecoveryEventMetadata,
    RequestCompletionStatus,
    RequestKey,
    StoreError,
    StoreErrorCode,
    TurnRequestIdentity,
    TurnRequestIntent,
    TurnRequestRecord,
)
from neontof.contracts.domain import (
    DomainEvent,
    PlayerInputAcceptedEvent,
    TurnAbortedEvent,
    TurnAwaitingPlayerEvent,
    TurnCommittedEvent,
    TurnResumedEvent,
)
from neontof.contracts.event_parser import DomainEventValidationError
from neontof.contracts.ids import CampaignId
from neontof.contracts.turn_status import project_turn_status
from neontof.persistence.event_store import EventStore
from neontof.persistence.sqlite_database import SqliteDatabase, SqliteOperationError

_NON_IDENTITY_FIELDS = {
    "base_event_sequence",
    "recovery_payload_version",
    "recovery_reason",
    "recovery_selector",
    "accepted_event_id",
    "resumed_event_id",
    "awaiting_player_event_id",
    "committed_event_id",
    "aborted_event_id",
    "recovery_aborted_event_id",
    "occurred_at",
    "initial_recovery_payload",
    "staged_recovery_payload",
}
_RECORD_COLUMNS = (
    "request_key",
    "request_kind",
    "requested_media_type",
    "turn_request_id",
    "campaign_id",
    "session_id",
    "scene_id",
    "turn_id",
    "root_turn_request_id",
    "input_digest",
    "base_event_sequence",
    "status",
    "recovery_reason",
    "recovery_selector",
    "accepted_event_id",
    "resumed_event_id",
    "awaiting_player_event_id",
    "committed_event_id",
    "aborted_event_id",
    "recovery_aborted_event_id",
    "occurred_at",
    "initial_recovery_payload",
    "staged_recovery_payload",
    "recovery_payload_version",
    "response_status_code",
    "response_media_type",
    "response_body",
)


def _record_from_row(row: tuple[Any, ...] | None) -> TurnRequestRecord | None:
    if row is None:
        return None
    if len(row) != len(_RECORD_COLUMNS):
        raise StoreError("invalid_record")

    (
        request_key,
        request_kind,
        requested_media_type,
        turn_request_id,
        campaign_id,
        session_id,
        scene_id,
        turn_id,
        root_turn_request_id,
        input_digest,
        base_event_sequence,
        status,
        recovery_reason,
        recovery_selector,
        accepted_event_id,
        resumed_event_id,
        awaiting_player_event_id,
        committed_event_id,
        aborted_event_id,
        recovery_aborted_event_id,
        occurred_at,
        initial_recovery_payload,
        staged_recovery_payload,
        recovery_payload_version,
        response_status_code,
        response_media_type,
        response_body,
    ) = row
    if (
        (recovery_payload_version == 1 and staged_recovery_payload is not None)
        or (recovery_payload_version == 2 and staged_recovery_payload is None)
        or (
            any(
                value is not None
                for value in (
                    recovery_reason,
                    recovery_selector,
                    accepted_event_id,
                    resumed_event_id,
                    awaiting_player_event_id,
                    committed_event_id,
                    aborted_event_id,
                    recovery_aborted_event_id,
                    occurred_at,
                )
            )
            and (recovery_reason is None or recovery_selector is None or occurred_at is None)
        )
    ):
        raise StoreError("invalid_record")
    values: dict[str, Any] = {
        "request_key": request_key,
        "request_kind": request_kind,
        "requested_media_type": requested_media_type,
        "turn_request_id": turn_request_id,
        "campaign_id": campaign_id,
        "session_id": session_id,
        "scene_id": scene_id,
        "turn_id": turn_id,
        "root_turn_request_id": root_turn_request_id,
        "input_digest": input_digest,
        "base_event_sequence": base_event_sequence,
        "recovery_payload_version": recovery_payload_version,
        "recovery_reason": recovery_reason,
        "recovery_selector": recovery_selector,
        "accepted_event_id": accepted_event_id,
        "resumed_event_id": resumed_event_id,
        "awaiting_player_event_id": awaiting_player_event_id,
        "committed_event_id": committed_event_id,
        "aborted_event_id": aborted_event_id,
        "recovery_aborted_event_id": recovery_aborted_event_id,
        "occurred_at": occurred_at,
        "initial_recovery_payload": initial_recovery_payload,
        "staged_recovery_payload": staged_recovery_payload,
    }
    construction_failed = False
    record: TurnRequestRecord | None = None
    if status == "processing":
        if (
            response_status_code is not None
            or response_media_type is not None
            or response_body is not None
        ):
            raise StoreError("invalid_record")
        try:
            record = ProcessingTurnRequestRecord(
                **values,
                status=status,
                response=None,
            )
        except ValidationError, TypeError, ValueError:
            construction_failed = True
    elif status in {"awaiting_player", "committed", "aborted"}:
        if response_status_code is None or response_media_type is None or response_body is None:
            raise StoreError("invalid_record")
        try:
            response = CachedTurnResponse(
                status_code=response_status_code,
                media_type=response_media_type,
                body=response_body,
            )
            if response.media_type != requested_media_type:
                construction_failed = True
            else:
                record = FinalTurnRequestRecord(
                    **values,
                    status=status,
                    response=response,
                )
        except ValidationError, TypeError, ValueError:
            construction_failed = True
    else:
        record = None
        construction_failed = True
    if construction_failed or record is None:
        raise StoreError("invalid_record")
    return record


def _identity_matches(record: TurnRequestIdentity, intent: TurnRequestIntent) -> bool:
    record_values = record.model_dump()
    intent_values = intent.model_dump()
    return all(
        record_values[field] == intent_values[field]
        for field in intent_values
        if field not in _NON_IDENTITY_FIELDS
    )


def _metadata_matches_identity(
    record: TurnRequestIdentity, metadata: RecoveryEventMetadata
) -> bool:
    return (
        record.request_kind == metadata.request_kind
        and record.recovery_payload_version == metadata.recovery_payload_version
        and record.campaign_id == metadata.campaign_id
        and record.session_id == metadata.session_id
        and record.scene_id == metadata.scene_id
        and record.turn_id == metadata.turn_id
        and record.turn_request_id == metadata.turn_request_id
        and record.root_turn_request_id == metadata.root_turn_request_id
        and record.input_digest == metadata.input_digest
    )


def _metadata_matches_record(record: TurnRequestIdentity, metadata: RecoveryEventMetadata) -> bool:
    return _metadata_matches_identity(record, metadata) and (
        record.recovery_reason == metadata.recovery_reason
        and record.recovery_selector == metadata.recovery_selector
        and record.accepted_event_id == metadata.accepted_event_id
        and record.resumed_event_id == metadata.resumed_event_id
        and record.awaiting_player_event_id == metadata.awaiting_player_event_id
        and record.committed_event_id == metadata.committed_event_id
        and record.aborted_event_id == metadata.aborted_event_id
        and record.recovery_aborted_event_id == metadata.recovery_aborted_event_id
        and record.occurred_at == metadata.occurred_at
    )


def _recovery_field_values(record: TurnRequestIdentity) -> tuple[Any, ...]:
    return (
        record.recovery_reason,
        record.recovery_selector,
        record.accepted_event_id,
        record.resumed_event_id,
        record.awaiting_player_event_id,
        record.committed_event_id,
        record.aborted_event_id,
        record.recovery_aborted_event_id,
        record.occurred_at,
    )


def _validated_staged_payload(value: object) -> bytes:
    failed = False
    validated: bytes | None = None
    try:
        validated = TypeAdapter(NonEmptyBytes).validate_python(value)
    except ValidationError, TypeError, ValueError:
        failed = True
    if failed or validated is None:
        raise StoreError("stage_conflict")
    return validated


def _response_is_valid(response: object, requested_media_type: object) -> bool:
    if not isinstance(response, CachedTurnResponse):
        return False
    if response.media_type != requested_media_type or response.status_code != 200:
        return False
    try:
        response.body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return True


def _mapped_database_failure(error: SqliteOperationError) -> StoreErrorCode:
    if error.code == "locked":
        return "store_integrity_error"
    if error.code == "io":
        return "store_integrity_error"
    if error.code == "corrupt":
        return "store_integrity_error"
    if error.code == "other":
        return "store_integrity_error"
    raise AssertionError("unknown SQLite operation failure code")


def _mapped_integrity_error(error: sqlite3.IntegrityError) -> StoreErrorCode:
    if error.sqlite_errorname == "SQLITE_CONSTRAINT_CHECK":
        return "invalid_record"
    return "store_integrity_error"


def _mapped_claim_integrity_error(
    error: sqlite3.IntegrityError,
    *,
    processing_exists: bool,
) -> StoreErrorCode:
    if error.sqlite_errorname == "SQLITE_CONSTRAINT_PRIMARYKEY":
        return "request_key_conflict"
    if error.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE" and processing_exists:
        return "turn_already_processing"
    return _mapped_integrity_error(error)


def _validate_resume_context(
    intent: TurnRequestIntent,
    campaign_events: tuple[DomainEvent, ...],
) -> None:
    if intent.request_kind != "resume":
        return
    if intent.root_turn_request_id != intent.turn_request_id:
        raise StoreError("recovery_identity_mismatch")
    status: str | None = None
    validation_failed = False
    try:
        status = project_turn_status(intent.turn_id, campaign_events)
    except DomainEventValidationError:
        validation_failed = True
    if validation_failed or status != "awaiting_player":
        raise StoreError("recovery_identity_mismatch")

    accepted = False
    awaiting_player = False
    for event in campaign_events:
        if not isinstance(
            event,
            (
                PlayerInputAcceptedEvent,
                TurnAwaitingPlayerEvent,
                TurnResumedEvent,
                TurnAbortedEvent,
                TurnCommittedEvent,
            ),
        ):
            continue
        if event.turn_id != intent.turn_id:
            continue
        if (
            event.campaign_id != intent.campaign_id
            or event.session_id != intent.session_id
            or event.scene_id != intent.scene_id
            or event.payload.turn_request_id != intent.turn_request_id
        ):
            raise StoreError("recovery_identity_mismatch")
        if isinstance(event, PlayerInputAcceptedEvent):
            accepted = True
        if isinstance(event, TurnAwaitingPlayerEvent):
            awaiting_player = True
    if not accepted or not awaiting_player:
        raise StoreError("recovery_identity_mismatch")


def _max_campaign_sequence(events: tuple[Any, ...], row: tuple[Any, ...] | None) -> int:
    if row is None or len(row) != 1 or type(row[0]) is not int or row[0] < 0:
        raise StoreError("invalid_record")
    sequence = row[0]
    if len(events) != sequence:
        raise StoreError("recovery_identity_mismatch")
    if events and events[-1].sequence != sequence:
        raise StoreError("recovery_identity_mismatch")
    return sequence


class TurnRequestStore:
    """Own durable request coordination records without owning Event append."""

    def __init__(self, database: SqliteDatabase, event_store: EventStore) -> None:
        self._database = database
        self._event_store = event_store

    def claim(self, *, intent: TurnRequestIntent) -> ClaimResult:
        def operation(connection: sqlite3.Connection) -> ClaimResult:
            row = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (intent.request_key,),
            ).fetchone()
            existing = _record_from_row(tuple(row) if row is not None else None)
            if existing is not None:
                if not _identity_matches(existing, intent):
                    raise StoreError("request_key_conflict")
                if existing.status == "processing":
                    return ExistingProcessingClaim(type="existing_processing", record=existing)
                return ExistingFinalClaim(type="existing_final", record=existing)

            processing = connection.execute(
                "SELECT 1 FROM turn_requests WHERE campaign_id = ? AND status = 'processing' LIMIT 1",
                (intent.campaign_id,),
            ).fetchone()
            if processing is not None:
                raise StoreError("turn_already_processing")
            if intent.root_turn_request_id != intent.turn_request_id:
                raise StoreError("recovery_identity_mismatch")

            campaign_id = intent.campaign_id
            campaign_events = self._event_store._read_campaign_on_connection(
                connection, campaign_id
            )
            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            base_event_sequence = _max_campaign_sequence(campaign_events, sequence_row)
            _validate_resume_context(intent, campaign_events)
            identity_values = {
                "request_key": intent.request_key,
                "request_kind": intent.request_kind,
                "requested_media_type": intent.requested_media_type,
                "turn_request_id": intent.turn_request_id,
                "campaign_id": intent.campaign_id,
                "session_id": intent.session_id,
                "scene_id": intent.scene_id,
                "turn_id": intent.turn_id,
                "root_turn_request_id": intent.root_turn_request_id,
                "input_digest": intent.input_digest,
                "base_event_sequence": base_event_sequence,
                "recovery_payload_version": 1,
                "recovery_reason": None,
                "recovery_selector": None,
                "accepted_event_id": None,
                "resumed_event_id": None,
                "awaiting_player_event_id": None,
                "committed_event_id": None,
                "aborted_event_id": None,
                "recovery_aborted_event_id": None,
                "occurred_at": None,
                "initial_recovery_payload": intent.initial_recovery_payload,
                "staged_recovery_payload": None,
            }
            values = {
                **identity_values,
                "status": "processing",
                "response_status_code": None,
                "response_media_type": None,
                "response_body": None,
            }
            insert_failure_code: StoreErrorCode | None = None
            try:
                connection.execute(
                    """
                    INSERT INTO turn_requests (
                        request_key, request_kind, requested_media_type, turn_request_id,
                        campaign_id, session_id, scene_id, turn_id, root_turn_request_id,
                        input_digest, base_event_sequence, status, recovery_reason,
                        recovery_selector, accepted_event_id, resumed_event_id,
                        awaiting_player_event_id, committed_event_id, aborted_event_id,
                        recovery_aborted_event_id, occurred_at, initial_recovery_payload,
                        staged_recovery_payload, recovery_payload_version,
                        response_status_code, response_media_type, response_body
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(values[column] for column in _RECORD_COLUMNS),
                )
            except sqlite3.IntegrityError as error:
                processing_after = connection.execute(
                    "SELECT 1 FROM turn_requests "
                    "WHERE campaign_id = ? AND status = 'processing' LIMIT 1",
                    (intent.campaign_id,),
                ).fetchone()
                insert_failure_code = _mapped_claim_integrity_error(
                    error, processing_exists=processing_after is not None
                )
            if insert_failure_code is not None:
                raise StoreError(insert_failure_code)
            identity = TurnRequestIdentity(
                request_key=intent.request_key,
                request_kind=intent.request_kind,
                requested_media_type=intent.requested_media_type,
                turn_request_id=intent.turn_request_id,
                campaign_id=intent.campaign_id,
                session_id=intent.session_id,
                scene_id=intent.scene_id,
                turn_id=intent.turn_id,
                root_turn_request_id=intent.root_turn_request_id,
                input_digest=intent.input_digest,
                base_event_sequence=base_event_sequence,
                recovery_payload_version=1,
                recovery_reason=None,
                recovery_selector=None,
                accepted_event_id=None,
                resumed_event_id=None,
                awaiting_player_event_id=None,
                committed_event_id=None,
                aborted_event_id=None,
                recovery_aborted_event_id=None,
                occurred_at=None,
                initial_recovery_payload=intent.initial_recovery_payload,
                staged_recovery_payload=None,
            )
            record = ProcessingTurnRequestRecord(
                **identity.model_dump(), status="processing", response=None
            )
            return NewClaim(type="new", record=record)

        failure_code: StoreErrorCode | None = None
        result: ClaimResult | None = None
        try:
            result = self._database._write(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        except DomainEventValidationError as error:
            del error
            failure_code = "recovery_identity_mismatch"
        if failure_code is not None:
            raise StoreError(failure_code)
        if result is None:
            raise StoreError("store_integrity_error")
        return result

    def stage_recovery_metadata(
        self,
        *,
        request_key: RequestKey,
        metadata: RecoveryEventMetadata,
    ) -> ProcessingTurnRequestRecord:
        def operation(connection: sqlite3.Connection) -> ProcessingTurnRequestRecord:
            row = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            record = _record_from_row(tuple(row) if row is not None else None)
            if record is None:
                raise StoreError("request_not_found")
            if record.status != "processing":
                raise StoreError("request_not_processing")
            if not _metadata_matches_identity(record, metadata):
                raise StoreError("recovery_identity_mismatch")
            if _metadata_matches_record(record, metadata):
                return record
            if any(value is not None for value in _recovery_field_values(record)):
                raise StoreError("recovery_identity_mismatch")

            update_failure_code: StoreErrorCode | None = None
            try:
                connection.execute(
                    """
                    UPDATE turn_requests SET
                        recovery_reason = ?, recovery_selector = ?,
                        accepted_event_id = ?, resumed_event_id = ?,
                        awaiting_player_event_id = ?, committed_event_id = ?,
                        aborted_event_id = ?, recovery_aborted_event_id = ?, occurred_at = ?
                    WHERE request_key = ? AND status = 'processing'
                        AND recovery_reason IS NULL AND recovery_selector IS NULL
                        AND accepted_event_id IS NULL AND resumed_event_id IS NULL
                        AND awaiting_player_event_id IS NULL AND committed_event_id IS NULL
                        AND aborted_event_id IS NULL AND recovery_aborted_event_id IS NULL
                        AND occurred_at IS NULL
                    """,
                    (
                        metadata.recovery_reason,
                        metadata.recovery_selector,
                        metadata.accepted_event_id,
                        metadata.resumed_event_id,
                        metadata.awaiting_player_event_id,
                        metadata.committed_event_id,
                        metadata.aborted_event_id,
                        metadata.recovery_aborted_event_id,
                        metadata.occurred_at,
                        request_key,
                    ),
                )
            except sqlite3.IntegrityError as error:
                update_failure_code = _mapped_integrity_error(error)
            if update_failure_code is not None:
                raise StoreError(update_failure_code)
            updated = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            materialized = _record_from_row(tuple(updated) if updated is not None else None)
            if materialized is None or materialized.status != "processing":
                raise StoreError("invalid_record")
            return materialized

        failure_code: StoreErrorCode | None = None
        result: ProcessingTurnRequestRecord | None = None
        try:
            result = self._database._write(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        if failure_code is not None:
            raise StoreError(failure_code)
        if result is None:
            raise StoreError("store_integrity_error")
        return result

    def stage(
        self,
        *,
        request_key: OpaqueRequestKey,
        expected_version: Literal[1],
        staged_recovery_payload: NonEmptyBytes,
    ) -> ProcessingTurnRequestRecord:
        payload = _validated_staged_payload(staged_recovery_payload)

        def operation(connection: sqlite3.Connection) -> ProcessingTurnRequestRecord:
            row = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            record = _record_from_row(tuple(row) if row is not None else None)
            if record is None:
                raise StoreError("request_not_found")
            if record.status != "processing":
                raise StoreError("request_not_processing")
            if record.recovery_payload_version != expected_version:
                raise StoreError("stage_conflict")
            if record.staged_recovery_payload is not None:
                raise StoreError("stage_conflict")
            update_failure_code: StoreErrorCode | None = None
            try:
                connection.execute(
                    """
                    UPDATE turn_requests
                    SET staged_recovery_payload = ?, recovery_payload_version = 2
                    WHERE request_key = ? AND status = 'processing'
                        AND recovery_payload_version = 1
                        AND staged_recovery_payload IS NULL
                    """,
                    (sqlite3.Binary(payload), request_key),
                )
            except sqlite3.IntegrityError as error:
                update_failure_code = _mapped_integrity_error(error)
            if update_failure_code is not None:
                raise StoreError(update_failure_code)
            updated = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            materialized = _record_from_row(tuple(updated) if updated is not None else None)
            if materialized is None or materialized.status != "processing":
                raise StoreError("invalid_record")
            return materialized

        failure_code: StoreErrorCode | None = None
        result: ProcessingTurnRequestRecord | None = None
        try:
            result = self._database._write(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        if failure_code is not None:
            raise StoreError(failure_code)
        if result is None:
            raise StoreError("store_integrity_error")
        return result

    def read(self, *, request_key: RequestKey) -> TurnRequestRecord | None:
        def operation(connection: sqlite3.Connection) -> TurnRequestRecord | None:
            row = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            return _record_from_row(tuple(row) if row is not None else None)

        failure_code: StoreErrorCode | None = None
        result: TurnRequestRecord | None = None
        try:
            result = self._database._read(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        if failure_code is not None:
            raise StoreError(failure_code)
        return result

    def read_processing(self, *, campaign_id: CampaignId) -> ProcessingTurnRequestRecord | None:
        def operation(connection: sqlite3.Connection) -> ProcessingTurnRequestRecord | None:
            row = connection.execute(
                "SELECT * FROM turn_requests "
                "WHERE campaign_id = ? AND status = 'processing' LIMIT 1",
                (campaign_id,),
            ).fetchone()
            record = _record_from_row(tuple(row) if row is not None else None)
            if record is not None and record.status != "processing":
                raise StoreError("invalid_record")
            return record

        failure_code: StoreErrorCode | None = None
        result: ProcessingTurnRequestRecord | None = None
        try:
            result = self._database._read(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        if failure_code is not None:
            raise StoreError(failure_code)
        return result

    def complete(
        self,
        *,
        request_key: OpaqueRequestKey,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord:
        def operation(connection: sqlite3.Connection) -> FinalTurnRequestRecord:
            row = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            record = _record_from_row(tuple(row) if row is not None else None)
            if record is None:
                raise StoreError("request_not_found")
            if record.status != "processing":
                if (
                    record.status == status
                    and _response_is_valid(response, record.requested_media_type)
                    and record.response == response
                ):
                    return record
                raise StoreError("response_conflict")
            if status not in {"awaiting_player", "committed", "aborted"}:
                raise StoreError("invalid_response")
            if not _response_is_valid(response, record.requested_media_type):
                raise StoreError("invalid_response")
            if expected_version != record.recovery_payload_version:
                raise StoreError("request_not_processing")
            update_failure_code: StoreErrorCode | None = None
            try:
                connection.execute(
                    """
                    UPDATE turn_requests
                    SET status = ?, response_status_code = ?,
                        response_media_type = ?, response_body = ?
                    WHERE request_key = ? AND status = 'processing'
                        AND recovery_payload_version = ?
                    """,
                    (
                        status,
                        response.status_code,
                        response.media_type,
                        sqlite3.Binary(response.body),
                        request_key,
                        expected_version,
                    ),
                )
            except sqlite3.IntegrityError as error:
                update_failure_code = _mapped_integrity_error(error)
            if update_failure_code is not None:
                raise StoreError(update_failure_code)
            updated = connection.execute(
                "SELECT * FROM turn_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            materialized = _record_from_row(tuple(updated) if updated is not None else None)
            if materialized is None or materialized.status == "processing":
                raise StoreError("invalid_record")
            return materialized

        failure_code: StoreErrorCode | None = None
        result: FinalTurnRequestRecord | None = None
        try:
            result = self._database._write(operation)
        except SqliteOperationError as error:
            failure_code = _mapped_database_failure(error)
        if failure_code is not None:
            raise StoreError(failure_code)
        if result is None:
            raise StoreError("store_integrity_error")
        return result
