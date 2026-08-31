from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from neontof.application.turn_models import StoreError
from neontof.persistence.sqlite_database import SqliteOperationError


def _database(tmp_path: Path) -> Any:
    from neontof.persistence.sqlite_database import SqliteDatabase

    database = SqliteDatabase(tmp_path / "event-store.sqlite3")
    database.migrate()
    return database


def _store(tmp_path: Path) -> tuple[Any, Any, Any]:
    from neontof.persistence.event_store import EventStore
    from neontof.persistence.turn_request_store import TurnRequestStore

    database = _database(tmp_path)
    event_store = EventStore(database)
    return database, event_store, TurnRequestStore(database, event_store)


def _intent(**overrides: Any) -> Any:
    from neontof.application.turn_models import TurnRequestIntent

    values: dict[str, Any] = {
        "request_key": b"request-key-1",
        "request_kind": "submit",
        "requested_media_type": "application/json",
        "turn_request_id": "turn-request:first",
        "campaign_id": "campaign:test",
        "session_id": "session:test",
        "scene_id": "scene:test",
        "turn_id": "turn:test",
        "root_turn_request_id": "turn-request:first",
        "input_digest": "a" * 64,
        "initial_recovery_payload": b"opaque-recovery-payload",
    }
    values.update(overrides)
    return TurnRequestIntent(**values)


def _response(**overrides: Any) -> Any:
    from neontof.application.turn_models import CachedTurnResponse

    values: dict[str, Any] = {
        "status_code": 200,
        "media_type": "application/json",
        "body": b'{"ok":true}',
    }
    values.update(overrides)
    return CachedTurnResponse(**values)


def _metadata(record: Any, **overrides: Any) -> Any:
    from neontof.application.turn_models import RecoveryEventMetadata

    values: dict[str, Any] = {
        "request_kind": record.request_kind,
        "recovery_payload_version": record.recovery_payload_version,
        "campaign_id": record.campaign_id,
        "session_id": record.session_id,
        "scene_id": record.scene_id,
        "turn_id": record.turn_id,
        "turn_request_id": record.turn_request_id,
        "root_turn_request_id": record.root_turn_request_id,
        "input_digest": record.input_digest,
        "recovery_reason": "claim_before_first_event",
        "recovery_selector": "no_lifecycle_events",
        "accepted_event_id": None,
        "resumed_event_id": None,
        "awaiting_player_event_id": None,
        "committed_event_id": None,
        "aborted_event_id": None,
        "recovery_aborted_event_id": None,
        "occurred_at": "2026-08-31T00:00:00Z",
    }
    values.update(overrides)
    values["event_ids"] = tuple(
        event_id
        for event_id in (
            values["accepted_event_id"],
            values["resumed_event_id"],
            values["awaiting_player_event_id"],
            values["committed_event_id"],
            values["aborted_event_id"],
            values["recovery_aborted_event_id"],
        )
        if event_id is not None
    )
    return RecoveryEventMetadata(**values)


def _record_metadata(record: Any) -> Any:
    return _metadata(
        record,
        recovery_reason=record.recovery_reason,
        recovery_selector=record.recovery_selector,
        accepted_event_id=record.accepted_event_id,
        resumed_event_id=record.resumed_event_id,
        awaiting_player_event_id=record.awaiting_player_event_id,
        committed_event_id=record.committed_event_id,
        aborted_event_id=record.aborted_event_id,
        recovery_aborted_event_id=record.recovery_aborted_event_id,
        occurred_at=record.occurred_at,
    )


def _claim(store: Any, **overrides: Any) -> Any:
    return store.claim(intent=_intent(**overrides))


def _event_draft(event_id: str, campaign_id: str = "campaign:test") -> Any:
    from neontof.event_metadata import EventDraft, EventDraftBody

    return EventDraft(
        body=EventDraftBody(
            type="CampaignCreated",
            event_id=event_id,
            event_version=1,
            campaign_id=campaign_id,
            session_id=None,
            scene_id=None,
            turn_id=None,
            occurred_at="2026-08-31T00:00:00Z",
            origin="in_world",
            visibility="player_visible",
            payload_json=b'{"name":"NeontoF"}',
        )
    )


def _lifecycle_event_draft(
    event_id: str,
    event_type: str,
    *,
    campaign_id: str = "campaign:test",
    session_id: str | None,
    scene_id: str | None,
    turn_id: str | None,
    payload_json: bytes,
) -> Any:
    from neontof.event_metadata import EventDraft, EventDraftBody

    return EventDraft(
        body=EventDraftBody(
            type=event_type,
            event_id=event_id,
            event_version=1,
            campaign_id=campaign_id,
            session_id=session_id,
            scene_id=scene_id,
            turn_id=turn_id,
            occurred_at="2026-08-31T00:00:00Z",
            origin="in_world",
            visibility="player_visible",
            payload_json=payload_json,
        )
    )


def test_new_request_is_claimed_once(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    result = _claim(store)

    assert result.type == "new"
    assert result.record.status == "processing"
    assert result.record.base_event_sequence == 0
    assert result.record.response is None


def test_duplicate_processing_request_returns_existing_record(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    first = _claim(store)
    second = _claim(store)

    assert first.record == second.record
    assert second.type == "existing_processing"


def test_request_key_is_database_wide_and_opaque(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    _claim(store, request_key=b"opaque-key")
    with pytest.raises(StoreError) as error:
        _claim(
            store,
            request_key=b"opaque-key",
            campaign_id="campaign:other",
            session_id="session:other",
            scene_id="scene:other",
            turn_id="turn:other",
        )

    assert getattr(error.value, "code", None) == "request_key_conflict"


def test_request_key_conflict_compares_full_identity(tmp_path: Path) -> None:
    _, event_store, store = _store(tmp_path)

    _claim(store, request_key=b"same-key")
    with pytest.raises(StoreError) as error:
        _claim(store, request_key=b"same-key", input_digest="b" * 64)

    assert getattr(error.value, "code", None) == "request_key_conflict"

    store.complete(
        request_key=b"same-key",
        expected_version=1,
        status="committed",
        response=_response(),
    )
    original_read = event_store._read_campaign_on_connection

    def inject_request_key_conflict(connection: Any, campaign_id: str) -> Any:
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
            )
            SELECT ?, request_kind, requested_media_type, turn_request_id,
                   campaign_id, session_id, scene_id, turn_id, root_turn_request_id,
                   input_digest, base_event_sequence, status, recovery_reason,
                   recovery_selector, accepted_event_id, resumed_event_id,
                   awaiting_player_event_id, committed_event_id, aborted_event_id,
                   recovery_aborted_event_id, occurred_at, initial_recovery_payload,
                   staged_recovery_payload, recovery_payload_version,
                   response_status_code, response_media_type, response_body
            FROM turn_requests WHERE request_key = ?
            """,
            (b"raced-key", b"same-key"),
        )
        return original_read(connection, campaign_id)

    event_store._read_campaign_on_connection = inject_request_key_conflict
    with pytest.raises(StoreError) as raced_error:
        _claim(store, request_key=b"raced-key")
    event_store._read_campaign_on_connection = original_read

    assert getattr(raced_error.value, "code", None) == "request_key_conflict"


def test_request_key_conflict_is_sanitized_and_does_not_return_cached_body(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    sentinel = b"private-cached-body"

    _claim(store, request_key=b"same-key")
    store.complete(
        request_key=b"same-key",
        expected_version=1,
        status="committed",
        response=_response(body=sentinel),
    )
    with pytest.raises(StoreError) as error:
        _claim(store, request_key=b"same-key", input_digest="b" * 64)

    message = str(error.value)
    assert getattr(error.value, "code", None) == "request_key_conflict"
    assert sentinel.decode() not in message
    assert "campaign:test" not in message


def test_existing_claim_compares_only_immutable_identity_not_current_base_sequence(
    tmp_path: Path,
) -> None:
    database, event_store, store = _store(tmp_path)

    _claim(store)
    database._write(
        lambda connection: connection.execute(
            "UPDATE turn_requests SET base_event_sequence = 3 WHERE request_key = ?",
            (b"request-key-1",),
        )
    )

    result = _claim(store)

    assert result.type == "existing_processing"
    assert result.record.base_event_sequence == 3
    assert event_store.read_campaign("campaign:test") == ()


def test_same_key_final_replay_is_byte_for_byte_and_never_conflicts(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    response = _response(body=b"\x00\x01")

    _claim(store)
    completed = store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=response,
    )
    replay = _claim(store)

    assert completed.response is not None
    assert completed.response.body == response.body
    assert replay.type == "existing_final"
    assert replay.record.response is not None
    assert replay.record.response.body == b"\x00\x01"


def test_request_key_is_blob_between_one_and_256_bytes(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    with pytest.raises(ValidationError):
        _claim(store, request_key=b"")
    _claim(store, request_key=b"x" * 256)
    with pytest.raises(ValidationError):
        _claim(store, request_key=b"x" * 257)
    with pytest.raises(ValidationError):
        _claim(store, request_key="text-key")


def test_canonical_turn_request_id_is_campaign_scoped(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    first = _claim(store, request_key=b"campaign-a", campaign_id="campaign:a")
    second = _claim(store, request_key=b"campaign-b", campaign_id="campaign:b")

    assert first.type == "new"
    assert second.type == "new"
    assert first.record.turn_request_id == second.record.turn_request_id


def test_claim_selects_campaign_processing_row_on_same_write_connection(
    tmp_path: Path,
) -> None:
    database, event_store, store = _store(tmp_path)
    opened: list[Any] = []
    read_connections: list[Any] = []
    original_open = database._open_connection
    original_read = event_store._read_campaign_on_connection

    def open_connection() -> Any:
        connection = original_open()
        opened.append(connection)
        return connection

    def read_campaign(connection: Any, campaign_id: str) -> Any:
        read_connections.append(connection)
        return original_read(connection, campaign_id)

    database._open_connection = open_connection
    event_store._read_campaign_on_connection = read_campaign
    _claim(store)

    assert len(opened) == 1
    assert read_connections == opened


def test_claim_result_distinguishes_new_processing_and_final_branches(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)

    new = _claim(store)
    processing = _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(),
    )
    final = _claim(store)

    assert new.type == "new"
    assert processing.type == "existing_processing"
    assert final.type == "existing_final"


def test_preclaim_intent_has_no_caller_supplied_base_sequence_or_staged_payload() -> None:
    from neontof.application.turn_models import TurnRequestIntent

    assert "base_event_sequence" not in TurnRequestIntent.model_fields
    assert "staged_recovery_payload" not in TurnRequestIntent.model_fields


def test_base_event_sequence_is_derived_from_full_campaign_read(tmp_path: Path) -> None:
    _, event_store, store = _store(tmp_path)

    from neontof.event_metadata import EventBatch

    event_store.append(
        EventBatch(
            campaign_id="campaign:test",
            drafts=(
                _event_draft("event:campaign-created"),
                _event_draft("event:campaign-created-2"),
            ),
        )
    )

    result = _claim(store)

    assert result.record.base_event_sequence == 2


def test_campaign_processing_partial_unique_maps_to_turn_already_processing(
    tmp_path: Path,
) -> None:
    _, event_store, store = _store(tmp_path)

    _claim(store, request_key=b"first")
    with pytest.raises(StoreError) as error:
        _claim(store, request_key=b"second")

    assert getattr(error.value, "code", None) == "turn_already_processing"

    store.complete(
        request_key=b"first",
        expected_version=1,
        status="committed",
        response=_response(),
    )

    original_read = event_store._read_campaign_on_connection

    def inject_processing_conflict(connection: Any, campaign_id: str) -> Any:
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
            )
            SELECT ?, request_kind, requested_media_type, turn_request_id,
                   campaign_id, session_id, scene_id, turn_id, root_turn_request_id,
                   input_digest, base_event_sequence, 'processing', recovery_reason,
                   recovery_selector, accepted_event_id, resumed_event_id,
                   awaiting_player_event_id, committed_event_id, aborted_event_id,
                   recovery_aborted_event_id, occurred_at, initial_recovery_payload,
                   staged_recovery_payload, recovery_payload_version,
                   NULL, NULL, NULL
            FROM turn_requests WHERE request_key = ?
            """,
            (b"raced-processing", b"first"),
        )
        return original_read(connection, campaign_id)

    event_store._read_campaign_on_connection = inject_processing_conflict
    with pytest.raises(StoreError) as raced_error:
        _claim(store, request_key=b"raced-processing")
    event_store._read_campaign_on_connection = original_read

    assert getattr(raced_error.value, "code", None) == "turn_already_processing"
    assert store.read_processing(campaign_id="campaign:test") is None

    after_final = _claim(store, request_key=b"third")

    assert after_final.type == "new"


def test_integrity_errors_map_to_fixed_store_codes_without_sqlite_message(
    tmp_path: Path,
) -> None:
    database, _, store = _store(tmp_path)
    database._write(
        lambda connection: connection.execute(
            """
            CREATE TRIGGER leak_test BEFORE INSERT ON turn_requests
            BEGIN SELECT RAISE(ABORT, 'secret sqlite detail'); END
            """
        )
    )

    with pytest.raises(StoreError) as error:
        _claim(store)

    assert getattr(error.value, "code", None) == "store_integrity_error"
    assert "secret sqlite detail" not in str(error.value)
    assert error.value.args == ("store_integrity_error",)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None

    not_null_database, _, not_null_store = _store(tmp_path / "not-null")
    not_null_database._write(
        lambda connection: connection.execute("CREATE TABLE not_null_probe (value TEXT NOT NULL)")
    )
    not_null_database._write(
        lambda connection: connection.execute(
            """
            CREATE TRIGGER not_null_failure BEFORE INSERT ON turn_requests
            BEGIN INSERT INTO not_null_probe(value) VALUES (NULL); END
            """
        )
    )

    with pytest.raises(StoreError) as not_null_error:
        _claim(not_null_store)

    assert getattr(not_null_error.value, "code", None) == "store_integrity_error"
    assert not_null_error.value.__cause__ is None
    assert not_null_error.value.__context__ is None
    assert not_null_store.read_processing(campaign_id="campaign:test") is None

    check_database, _, check_store = _store(tmp_path / "check")
    _claim(check_store, request_key=b"check-key")
    check_database._write(
        lambda connection: connection.execute(
            "CREATE TABLE check_probe (value INTEGER NOT NULL CHECK (value = 1))"
        )
    )
    check_database._write(
        lambda connection: connection.execute(
            """
            CREATE TRIGGER check_failure BEFORE UPDATE OF status ON turn_requests
            BEGIN INSERT INTO check_probe(value) VALUES (0); END
            """
        )
    )

    with pytest.raises(StoreError) as check_error:
        check_store.complete(
            request_key=b"check-key",
            expected_version=1,
            status="committed",
            response=_response(),
        )

    assert getattr(check_error.value, "code", None) == "invalid_record"
    assert check_error.value.__cause__ is None
    assert check_error.value.__context__ is None
    assert check_store.read(request_key=b"check-key").status == "processing"


def test_recovery_payload_version_and_identity_mismatch_is_fixed_error(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record

    with pytest.raises(StoreError) as error:
        store.stage_recovery_metadata(
            request_key=record.request_key,
            metadata=_metadata(record, recovery_payload_version=2),
        )

    assert getattr(error.value, "code", None) == "recovery_identity_mismatch"


def test_request_record_persists_requested_media_type_and_base_sequence(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)

    result = _claim(store, requested_media_type="text/event-stream")
    record = store.read(request_key=b"request-key-1")

    assert record is not None
    assert record.requested_media_type == "text/event-stream"
    assert record.base_event_sequence == result.record.base_event_sequence


def test_processing_and_final_records_persist_recovery_version_and_metadata(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record
    metadata = _metadata(record, recovery_reason="after_terminal", recovery_selector="terminal")

    staged = store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=metadata,
    )
    completed = store.complete(
        request_key=record.request_key,
        expected_version=1,
        status="committed",
        response=_response(),
    )

    assert staged.recovery_payload_version == 1
    assert _record_metadata(staged) == metadata
    assert completed.recovery_payload_version == 1
    assert _record_metadata(completed) == metadata


def test_stage_recovery_metadata_is_one_time_cas_and_same_metadata_is_idempotent(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record
    metadata = _metadata(record)

    first = store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=metadata,
    )
    second = store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=metadata,
    )

    assert first == second
    assert _record_metadata(second) == metadata


def test_stage_recovery_metadata_conflict_is_sanitized_and_does_not_change_payload(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record
    first_metadata = _metadata(record)
    second_metadata = _metadata(record, recovery_selector="terminal")

    first = store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=first_metadata,
    )
    with pytest.raises(StoreError) as error:
        store.stage_recovery_metadata(
            request_key=record.request_key,
            metadata=second_metadata,
        )
    after = store.read(request_key=record.request_key)

    assert getattr(error.value, "code", None) == "recovery_identity_mismatch"
    assert after == first


def test_recovery_reason_selector_event_ids_and_timestamp_are_durable(
    tmp_path: Path,
) -> None:
    database, _, store = _store(tmp_path)
    record = _claim(store).record
    metadata = _metadata(
        record,
        recovery_reason="after_terminal",
        recovery_selector="terminal",
        accepted_event_id="event:accepted",
        resumed_event_id="event:resumed",
        awaiting_player_event_id="event:awaiting",
        committed_event_id="event:committed",
        aborted_event_id=None,
        recovery_aborted_event_id=None,
        occurred_at="2026-08-31T12:34:56Z",
    )

    store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=metadata,
    )
    restarted = type(store)(database, store._event_store)
    persisted = restarted.read(request_key=record.request_key)

    assert persisted is not None
    assert _record_metadata(persisted) == metadata
    assert _record_metadata(persisted).event_ids == (
        "event:accepted",
        "event:resumed",
        "event:awaiting",
        "event:committed",
    )


def test_recovery_metadata_shape_matches_sql_record_and_event_ids_are_memory_derived(
    tmp_path: Path,
) -> None:
    database, _, store = _store(tmp_path)
    record = _claim(store).record
    metadata = _metadata(record, accepted_event_id="event:accepted")
    store.stage_recovery_metadata(
        request_key=record.request_key,
        metadata=metadata,
    )

    columns = database._read(
        lambda connection: tuple(
            row[1] for row in connection.execute("PRAGMA table_info(turn_requests)")
        )
    )
    persisted = store.read(request_key=record.request_key)

    assert "event_ids" not in columns
    assert persisted is not None
    assert _record_metadata(persisted).event_ids == ("event:accepted",)


def test_duplicate_committed_request_returns_cached_response(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(),
    )

    result = _claim(store)

    assert result.type == "existing_final"
    assert result.record.response is not None


def test_cached_response_replays_status_media_type_and_body_exactly(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    response = _response(body='{"message":"日本語"}'.encode())
    _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="awaiting_player",
        response=response,
    )

    replay = _claim(store)

    assert replay.record.response is not None
    assert replay.record.response.model_dump() == response.model_dump()


def test_cached_response_body_is_non_empty_and_media_bound(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)

    with pytest.raises(ValidationError):
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="committed",
            response=_response(body=b""),
        )
    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="committed",
            response=_response(media_type="text/event-stream"),
        )

    assert getattr(error.value, "code", None) == "invalid_response"
    assert store.read(request_key=b"request-key-1").status == "processing"


def test_cached_response_rejects_invalid_utf8_before_complete(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)

    response = _response(body=b"\xff")
    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="committed",
            response=response,
        )

    assert getattr(error.value, "code", None) == "invalid_response"
    assert error.value.args == ("invalid_response",)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert store.read(request_key=b"request-key-1").status == "processing"


def test_valid_japanese_response_is_strict_utf8_and_completes(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    body = "こんにちは、世界".encode()
    _claim(store)

    completed = store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(body=body),
    )

    assert completed.response is not None
    assert completed.response.body == body


def test_cached_response_replays_valid_utf8_bytes_byte_for_byte(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    body = "日本語".encode()
    _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(body=body),
    )

    assert store.read(request_key=b"request-key-1").response.body == body


def test_complete_missing_request_raises_request_not_found(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)

    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"missing",
            expected_version=1,
            status="committed",
            response=_response(),
        )

    assert getattr(error.value, "code", None) == "request_not_found"


def test_complete_non_processing_raises_safe_error(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(),
    )

    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="aborted",
            response=_response(),
        )

    assert getattr(error.value, "code", None) in {
        "request_not_processing",
        "response_conflict",
    }
    assert "campaign:test" not in str(error.value)


def test_complete_same_response_is_idempotent(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)
    response = _response()

    first = store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=response,
    )
    second = store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=response,
    )

    assert first == second


def test_complete_conflicting_response_raises_response_conflict(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)
    store.complete(
        request_key=b"request-key-1",
        expected_version=1,
        status="committed",
        response=_response(),
    )

    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="committed",
            response=_response(body=b"different"),
        )

    assert getattr(error.value, "code", None) == "response_conflict"


def test_complete_updates_only_status_and_response_with_immutable_identity_and_recovery(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    before = _claim(store).record
    metadata = _metadata(before)
    store.stage_recovery_metadata(
        request_key=before.request_key,
        metadata=metadata,
    )
    before_final = store.read(request_key=before.request_key)

    after = store.complete(
        request_key=before.request_key,
        expected_version=1,
        status="committed",
        response=_response(),
    )

    before_values = before_final.model_dump()
    after_values = after.model_dump()
    assert after_values["status"] == "committed"
    assert after_values["response"] is not None
    for field in before_values:
        if field not in {"status", "response"}:
            assert after_values[field] == before_values[field]


def test_stage_is_compare_and_set_and_moves_recovery_payload_version_one_to_two(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record

    staged = store.stage(
        request_key=record.request_key,
        expected_version=1,
        staged_recovery_payload=b"second-opaque-payload",
    )

    assert staged.recovery_payload_version == 2
    assert staged.staged_recovery_payload == b"second-opaque-payload"


def test_stage_rejects_lost_update_without_partial_write(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    record = _claim(store).record
    first = store.stage(
        request_key=record.request_key,
        expected_version=1,
        staged_recovery_payload=b"second-opaque-payload",
    )

    with pytest.raises(StoreError) as error:
        store.stage(
            request_key=record.request_key,
            expected_version=1,
            staged_recovery_payload=b"third-opaque-payload",
        )
    after = store.read(request_key=record.request_key)

    assert getattr(error.value, "code", None) == "stage_conflict"
    assert after == first


def test_read_processing_survives_process_restart(tmp_path: Path) -> None:
    database, event_store, store = _store(tmp_path)
    record = _claim(store).record
    restarted = type(store)(database, event_store)

    processing = restarted.read_processing(campaign_id="campaign:test")

    assert processing is not None
    assert processing.request_key == record.request_key
    assert processing.response is None


def test_read_processing_is_campaign_scoped_and_returns_at_most_one_row(
    tmp_path: Path,
) -> None:
    _, _, store = _store(tmp_path)
    _claim(store, request_key=b"campaign-a", campaign_id="campaign:a")
    _claim(store, request_key=b"campaign-b", campaign_id="campaign:b")

    first = store.read_processing(campaign_id="campaign:a")
    second = store.read_processing(campaign_id="campaign:b")

    assert first is not None and first.request_key == b"campaign-a"
    assert second is not None and second.request_key == b"campaign-b"


def test_processing_record_cannot_carry_response(tmp_path: Path) -> None:
    database, _, store = _store(tmp_path)
    _claim(store)

    with pytest.raises(SqliteOperationError) as error:
        database._write(
            lambda connection: connection.execute(
                """
                UPDATE turn_requests
                SET response_status_code = 200,
                    response_media_type = requested_media_type,
                    response_body = x'78'
                WHERE request_key = ?
                """,
                (b"request-key-1",),
            )
        )

    assert getattr(error.value, "code", None) == "other"

    def write_invalid_record(connection: Any) -> None:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            UPDATE turn_requests
            SET response_status_code = 200,
                response_media_type = requested_media_type,
                response_body = x'78'
            WHERE request_key = ?
            """,
            (b"request-key-1",),
        )
        connection.execute("PRAGMA ignore_check_constraints = OFF")

    database._write(write_invalid_record)
    with pytest.raises(StoreError) as invalid_record_error:
        store.read(request_key=b"request-key-1")

    assert getattr(invalid_record_error.value, "code", None) == "invalid_record"


def test_complete_cannot_accept_processing_status(tmp_path: Path) -> None:
    _, _, store = _store(tmp_path)
    _claim(store)

    with pytest.raises(StoreError) as error:
        store.complete(
            request_key=b"request-key-1",
            expected_version=1,
            status="processing",
            response=_response(),
        )

    assert getattr(error.value, "code", None) == "invalid_response"
    assert store.read(request_key=b"request-key-1").status == "processing"


def test_resume_with_prior_campaign_events_partitions_prefix_and_owned_suffix(
    tmp_path: Path,
) -> None:
    _, event_store, store = _store(tmp_path)

    from neontof.contracts.turn_status import project_turn_status
    from neontof.event_metadata import EventBatch

    event_store.append(
        EventBatch(
            campaign_id="campaign:orphan",
            drafts=(_event_draft("event:orphan", campaign_id="campaign:orphan"),),
        )
    )

    with pytest.raises(StoreError) as orphan_error:
        _claim(
            store,
            request_key=b"resume-orphan",
            request_kind="resume",
            campaign_id="campaign:orphan",
            session_id="session:orphan",
            scene_id="scene:orphan",
            turn_id="turn:orphan",
            turn_request_id="turn-request:orphan",
            root_turn_request_id="turn-request:orphan",
        )

    assert getattr(orphan_error.value, "code", None) == "recovery_identity_mismatch"
    assert store.read_processing(campaign_id="campaign:orphan") is None

    event_store.append(
        EventBatch(
            campaign_id="campaign:test",
            drafts=(
                _event_draft("event:campaign-created"),
                _lifecycle_event_draft(
                    "event:session-started",
                    "SessionStarted",
                    session_id="session:test",
                    scene_id=None,
                    turn_id=None,
                    payload_json=b'{"scenario_id":null,"title":"Test"}',
                ),
                _lifecycle_event_draft(
                    "event:scene-started",
                    "SceneStarted",
                    session_id="session:test",
                    scene_id="scene:test",
                    turn_id=None,
                    payload_json=b'{"label":"Test"}',
                ),
                _lifecycle_event_draft(
                    "event:accepted",
                    "PlayerInputAccepted",
                    session_id="session:test",
                    scene_id="scene:test",
                    turn_id="turn:test",
                    payload_json=(
                        b'{"turn_request_id":"turn-request:first",'
                        b'"input_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                        b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
                    ),
                ),
                _lifecycle_event_draft(
                    "event:resumed",
                    "TurnResumed",
                    session_id="session:test",
                    scene_id="scene:test",
                    turn_id="turn:test",
                    payload_json=b'{"turn_request_id":"turn-request:first"}',
                ),
                _lifecycle_event_draft(
                    "event:awaiting",
                    "TurnAwaitingPlayer",
                    session_id="session:test",
                    scene_id="scene:test",
                    turn_id="turn:test",
                    payload_json=b'{"turn_request_id":"turn-request:first"}',
                ),
            ),
        )
    )

    events = event_store.read_campaign("campaign:test")
    assert project_turn_status("turn:test", events) == "awaiting_player"

    result = _claim(
        store,
        request_key=b"resume-key",
        request_kind="resume",
        input_digest="b" * 64,
    )

    assert result.type == "new"
    assert result.record.base_event_sequence == 6

    store.complete(
        request_key=b"resume-key",
        expected_version=1,
        status="awaiting_player",
        response=_response(),
    )

    invalid_cases = (
        {"session_id": "session:wrong"},
        {"scene_id": "scene:wrong"},
        {"turn_id": "turn:wrong"},
        {
            "turn_request_id": "turn-request:other",
            "root_turn_request_id": "turn-request:other",
        },
        {"root_turn_request_id": "turn-request:other"},
    )
    for index, overrides in enumerate(invalid_cases):
        with pytest.raises(StoreError) as error:
            _claim(
                store,
                request_key=f"resume-invalid-{index}".encode(),
                request_kind="resume",
                **overrides,
            )
        assert getattr(error.value, "code", None) == "recovery_identity_mismatch"

    assert store.read_processing(campaign_id="campaign:test") is None
