"""P1-01a atomic Event Store, payload boundary, and SQLite ownership tests."""

from __future__ import annotations

import inspect
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime" / "event-store.sqlite3"
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    return path


def _make_database(tmp_path: Path) -> tuple[Any, Path]:
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    database = SqliteDatabase(path)
    database.migrate()
    return database, path


def _body(
    event_id: str,
    event_type: str = "CampaignCreated",
    *,
    campaign_id: str = "campaign:alpha",
    session_id: str | None = None,
    scene_id: str | None = None,
    turn_id: str | None = None,
    turn_request_id: str = "turn-request:first",
    payload_json: bytes | None = None,
) -> Any:
    from neontof.event_metadata import EventDraftBody

    if event_type not in {"CampaignCreated", "SessionStarted"} and session_id is None:
        session_id = "session:main"
    if event_type not in {"CampaignCreated", "SessionStarted"} and scene_id is None:
        scene_id = "scene:hall"
    if (
        event_type
        in {
            "PlayerInputAccepted",
            "DiceRolled",
            "ResourceChanged",
            "CharacterMoved",
            "ClockAdvanced",
            "TurnAwaitingPlayer",
            "TurnResumed",
            "TurnAborted",
            "TurnCommitted",
        }
        and turn_id is None
    ):
        turn_id = "turn:first"
    if event_type == "TurnReverted":
        scene_id = None
        turn_id = None

    payload: dict[str, Any]
    if event_type == "CampaignCreated":
        payload = {"name": "NeontoF"}
    elif event_type == "SessionStarted":
        payload = {"scenario_id": None, "title": "Opening"}
    elif event_type == "SceneStarted":
        payload = {"label": "Hall"}
    elif event_type == "SceneEnded":
        payload = {"reason": "completed"}
    elif event_type == "PlayerInputAccepted":
        payload = {"turn_request_id": turn_request_id, "input_digest": "a" * 64}
    elif event_type == "TurnReverted":
        payload = {"target_turn_id": "turn:first"}
    elif event_type in {"TurnAwaitingPlayer", "TurnResumed", "TurnCommitted"}:
        payload = {"turn_request_id": turn_request_id}
    elif event_type == "TurnAborted":
        payload = {"turn_request_id": turn_request_id, "reason": "failed"}
    elif event_type == "FactAsserted":
        payload = {
            "kind": "fact",
            "holder": "world",
            "subject_id": None,
            "predicate": "has-symbol",
            "value": {"symbol": "sun"},
        }
    else:
        raise AssertionError(f"test helper has no payload for {event_type}")

    if payload_json is None:
        payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return EventDraftBody(
        type=event_type,
        event_id=event_id,
        event_version=1,
        campaign_id=campaign_id,
        session_id=session_id,
        scene_id=scene_id,
        turn_id=turn_id,
        occurred_at="2026-08-25T00:00:00Z",
        origin="table_correction" if event_type == "TurnReverted" else "in_world",
        visibility="player_visible",
        payload_json=payload_json,
    )


def _draft(event_id: str, event_type: str = "CampaignCreated", **kwargs: Any) -> Any:
    from neontof.event_metadata import EventDraft

    return EventDraft(body=_body(event_id, event_type, **kwargs))


def _batch(*drafts: Any, campaign_id: str = "campaign:alpha") -> Any:
    from neontof.event_metadata import EventBatch

    return EventBatch(campaign_id=campaign_id, drafts=tuple(drafts))


def _store(tmp_path: Path) -> tuple[Any, Any, Path]:
    from neontof.persistence.event_store import EventStore

    database, path = _make_database(tmp_path)
    return database, EventStore(database), path


def _connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _rows(path: Path) -> list[tuple[Any, ...]]:
    connection = _connection(path)
    try:
        return connection.execute(
            "SELECT campaign_id, sequence, event_id, type, event_version, session_id, "
            "scene_id, turn_id, occurred_at, origin, visibility, event_json "
            "FROM events ORDER BY campaign_id, sequence"
        ).fetchall()
    finally:
        connection.close()


def _add_abort_trigger(path: Path, event_id: str, message: str = "trigger failure") -> None:
    connection = _connection(path)
    try:
        quoted_event_id = event_id.replace("'", "''")
        quoted_message = message.replace("'", "''")
        connection.execute(
            "CREATE TRIGGER fail_event_insert BEFORE INSERT ON events "
            f"WHEN NEW.event_id = '{quoted_event_id}' "
            f"BEGIN SELECT RAISE(ABORT, '{quoted_message}'); END"
        )
        connection.commit()
    finally:
        connection.close()


def _assert_sanitized(error: BaseException, sentinel: str) -> None:
    surfaces = (
        str(error),
        repr(error),
        repr(error.args),
        repr(getattr(error, "__dict__", {})),
        repr(error.__cause__),
        repr(error.__context__),
    )
    assert all(sentinel not in surface for surface in surfaces)


def test_append_persists_events_in_sequence(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    stored = store.append(_batch(_draft("event:first"), _draft("event:second")))

    assert [item.sequence for item in stored] == [1, 2]
    assert [item.event.event_id for item in stored] == ["event:first", "event:second"]
    assert [row[1] for row in _rows(path)] == [1, 2]


def test_append_rolls_back_every_event_when_second_insert_fails(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    _add_abort_trigger(path, "event:second", "SECOND_INSERT_SECRET")
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(EventStoreConstraintError) as raised:
        store.append(_batch(_draft("event:first"), _draft("event:second")))

    assert raised.value.code == "event_constraint_violation"
    assert _rows(path) == []


def test_sequence_is_allocated_inside_append_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, store, _ = _store(tmp_path)

    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    stored = store.append(_batch(_draft("event:inside")))
    normalized = [statement.lower() for statement in traces]
    begin_index = next(
        index for index, statement in enumerate(normalized) if "begin immediate" in statement
    )
    sequence_index = next(
        index for index, statement in enumerate(normalized) if "max(sequence)" in statement
    )

    assert stored[0].sequence == 1
    assert begin_index < sequence_index
    assert "sequence" not in database.__class__.__dict__


def test_read_campaign_validates_every_row_before_returning(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:first"), _draft("event:second")))
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:second'",
            (b'{"not":"an event"}',),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_campaign("campaign:alpha")


@pytest.mark.parametrize(
    ("event_json", "sentinel"),
    [
        (
            b'{"name":"READ_MALFORMED_JSON_SECRET_SENTINEL"',
            "READ_MALFORMED_JSON_SECRET_SENTINEL",
        ),
        (
            b'{"name":"READ_INVALID_UTF8_SECRET_SENTINEL",\xff}',
            "READ_INVALID_UTF8_SECRET_SENTINEL",
        ),
    ],
)
def test_read_campaign_sanitizes_persisted_json_parse_failures(
    tmp_path: Path, event_json: bytes, sentinel: str
) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:stored")))
    original_row = _rows(path)[0]
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:stored'",
            (event_json,),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError) as raised:
        store.read_campaign("campaign:alpha")

    assert isinstance(raised.value, DomainEventValidationError)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    _assert_sanitized(raised.value, sentinel)
    rows_after_failure = _rows(path)
    assert len(rows_after_failure) == 1
    assert rows_after_failure[0][:-1] == original_row[:-1]
    assert rows_after_failure[0][-1] == event_json


def test_read_campaign_requires_contiguous_sequence(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:first"), _draft("event:second")))
    connection = _connection(path)
    try:
        connection.execute("DELETE FROM events WHERE sequence = 1")
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_campaign("campaign:alpha")


def test_read_session_filters_only_after_complete_campaign_read(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(
        _batch(
            _draft("event:main", "SessionStarted", session_id="session:main"),
            _draft("event:other", "SessionStarted", session_id="session:other"),
        )
    )
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:other'",
            (b"not-json",),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_session("campaign:alpha", "session:main")


def test_read_turn_matches_turn_id_or_revert_target(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    store.append(
        _batch(
            _draft("event:turn", "PlayerInputAccepted"),
            _draft("event:revert", "TurnReverted"),
        )
    )

    events = store.read_turn("campaign:alpha", "turn:first")

    assert [event.event_id for event in events] == ["event:turn", "event:revert"]


def test_find_turn_by_request_uses_validated_player_input_payload(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    store.append(
        _batch(
            _draft(
                "event:accepted",
                "PlayerInputAccepted",
                turn_request_id="turn-request:find-me",
            ),
            _draft("event:other", "PlayerInputAccepted", turn_request_id="turn-request:other"),
        )
    )

    events = store.find_turn_by_request("campaign:alpha", "turn-request:find-me")

    assert [event.event_id for event in events] == ["event:accepted"]


def test_filtered_read_fails_closed_on_corrupt_out_of_scope_row(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(
        _batch(
            _draft("event:target", "PlayerInputAccepted"),
            _draft("event:other", "PlayerInputAccepted", turn_id="turn:other"),
        )
    )
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:other'",
            (b"corrupt-out-of-scope",),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_turn("campaign:alpha", "turn:first")


def test_duplicate_event_id_leaves_database_unchanged(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:duplicate")))
    before = _rows(path)
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(EventStoreConstraintError) as raised:
        store.append(_batch(_draft("event:duplicate")))

    assert raised.value.code == "duplicate_event_id"
    assert _rows(path) == before


def test_connection_is_not_reused_across_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, store, _ = _store(tmp_path)

    connections: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def recording_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    store.append(_batch(_draft("event:one")))
    store.read_campaign("campaign:alpha")
    database._read(lambda connection: connection.execute("SELECT 1").fetchone())

    assert len(connections) == 3
    assert len({id(connection) for connection in connections}) == 3


def test_event_store_has_no_public_next_sequence() -> None:
    from neontof.persistence.event_store import EventStore

    public_names = {name for name in dir(EventStore) if not name.startswith("_")}
    assert not any("sequence" in name.lower() for name in public_names)
    assert "append" in public_names
    assert "next_sequence" not in inspect.signature(EventStore.append).parameters


def test_sqlite_database_has_no_public_generic_read_or_write() -> None:
    from neontof.persistence.sqlite_database import SqliteDatabase

    public_names = {name for name in dir(SqliteDatabase) if not name.startswith("_")}
    assert public_names == {"migrate"}
    assert not hasattr(SqliteDatabase, "read")
    assert not hasattr(SqliteDatabase, "write")


def test_typed_store_reads_are_the_only_public_reads() -> None:
    from neontof.persistence.event_store import EventStore

    public_names = {
        name
        for name in dir(EventStore)
        if not name.startswith("_") and callable(getattr(EventStore, name))
    }
    assert public_names == {
        "append",
        "read_campaign",
        "read_session",
        "read_turn",
        "find_turn_by_request",
    }
    assert "read" not in public_names
    assert "write" not in public_names


def test_sqlite_connections_use_fixed_pragmas(tmp_path: Path) -> None:
    database, path = _make_database(tmp_path)
    connection = database._open_connection()
    try:
        assert connection.isolation_level is None
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()
    assert path.is_file()


def test_migrate_and_write_share_process_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import sqlite_database
    from neontof.persistence.sqlite_database import SqliteDatabase

    class RecordingLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.enter_count = 0

        def __enter__(self) -> None:
            self._lock.acquire()
            self.enter_count += 1

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            del exc_type, exc_value, traceback
            self._lock.release()

    shared_lock = RecordingLock()
    monkeypatch.setattr(sqlite_database, "_WRITE_LOCK", shared_lock)
    first = SqliteDatabase(_database_path(tmp_path))
    second = SqliteDatabase(tmp_path / "runtime" / "other.sqlite3")

    first.migrate()
    second.migrate()
    assert first._write(lambda connection: connection.execute("SELECT 1").fetchone()[0]) == 1
    assert shared_lock.enter_count == 3


def test_read_uses_separate_connection_outside_write_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import sqlite_database

    database, _ = _make_database(tmp_path)

    class RejectingLock:
        def __enter__(self) -> None:
            raise AssertionError("read must not acquire the write lock")

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            del exc_type, exc_value, traceback

    monkeypatch.setattr(database, "_write_lock", RejectingLock())
    monkeypatch.setattr(sqlite_database, "_WRITE_LOCK", RejectingLock())
    assert database._read(lambda connection: connection.execute("SELECT 1").fetchone()[0]) == 1


def test_read_connection_enables_query_only_as_defense_in_depth(tmp_path: Path) -> None:
    database, _ = _make_database(tmp_path)

    query_only = database._read(
        lambda connection: connection.execute("PRAGMA query_only").fetchone()[0]
    )

    assert query_only == 1


def test_event_json_persists_exact_assembled_bytes(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    payload = b'{ "name" : "NeontoF" }'
    store.append(_batch(_draft("event:exact", payload_json=payload)))
    connection = _connection(path)
    try:
        raw = connection.execute("SELECT event_json FROM events").fetchone()[0]
    finally:
        connection.close()

    expected = (
        b'{"type":"CampaignCreated","event_id":"event:exact",'
        b'"event_version":1,"campaign_id":"campaign:alpha",'
        b'"session_id":null,"scene_id":null,"turn_id":null,"sequence":1,'
        b'"occurred_at":"2026-08-25T00:00:00Z","origin":"in_world",'
        b'"visibility":"player_visible","payload":{ "name" : "NeontoF" }}'
    )

    assert type(raw) is bytes
    assert raw == expected
    assert payload in raw
    assert raw.count(payload) == 1


def test_materialized_domain_event_matches_body_and_assigned_sequence() -> None:
    from neontof.persistence.event_store import _materialize_event_json

    body = _body("event:materialized")
    raw, event = _materialize_event_json(body=body, sequence=7)
    expected = (
        b'{"type":"CampaignCreated","event_id":"event:materialized",'
        b'"event_version":1,"campaign_id":"campaign:alpha",'
        b'"session_id":null,"scene_id":null,"turn_id":null,"sequence":7,'
        b'"occurred_at":"2026-08-25T00:00:00Z","origin":"in_world",'
        b'"visibility":"player_visible","payload":{"name":"NeontoF"}}'
    )

    assert event.type == body.type
    assert event.event_id == body.event_id
    assert event.event_version == body.event_version
    assert event.campaign_id == body.campaign_id
    assert event.session_id == body.session_id
    assert event.scene_id == body.scene_id
    assert event.turn_id == body.turn_id
    assert event.sequence == 7
    assert event.occurred_at == body.occurred_at
    assert event.origin == body.origin
    assert event.visibility == body.visibility
    assert raw == expected
    assert body.payload_json in raw
    assert raw.count(body.payload_json) == 1


@pytest.mark.parametrize(
    "payload_json",
    [b"[]", b'"scalar"', b"1", b"null"],
)
def test_payload_json_requires_single_root_object(payload_json: bytes) -> None:
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import _materialize_event_json

    with pytest.raises(DomainEventValidationError):
        _materialize_event_json(body=_body("event:root", payload_json=payload_json), sequence=1)


def test_payload_json_rejects_invalid_utf8() -> None:
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import _materialize_event_json

    with pytest.raises(DomainEventValidationError):
        _materialize_event_json(
            body=_body("event:utf8", payload_json=b'{"name":"\xff"}'), sequence=1
        )


@pytest.mark.parametrize(
    ("payload_json", "sentinel"),
    [
        (
            b'{"name":"MALFORMED_PAYLOAD_SECRET_SENTINEL"',
            "MALFORMED_PAYLOAD_SECRET_SENTINEL",
        ),
        (
            b'{"name":"INVALID_UTF8_PAYLOAD_SECRET_SENTINEL",\xff}',
            "INVALID_UTF8_PAYLOAD_SECRET_SENTINEL",
        ),
    ],
)
def test_append_sanitizes_payload_parse_failures_and_rolls_back(
    tmp_path: Path, payload_json: bytes, sentinel: str
) -> None:
    _, store, path = _store(tmp_path)
    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError) as raised:
        store.append(_batch(_draft("event:invalid-payload", payload_json=payload_json)))

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    _assert_sanitized(raised.value, sentinel)
    assert _rows(path) == []


@pytest.mark.parametrize(
    "payload_json",
    [
        b'{"name":"NeontoF","sequence":99}',
        b'{"name":"NeontoF","event_id":"event:other"}',
        b'{"name":"NeontoF","campaign_id":"campaign:other"}',
    ],
)
def test_payload_fragment_cannot_override_sequence_event_id_or_context(payload_json: bytes) -> None:
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import _materialize_event_json

    with pytest.raises(DomainEventValidationError):
        _materialize_event_json(body=_body("event:fragment", payload_json=payload_json), sequence=3)


def test_payload_json_rejects_trailing_tokens() -> None:
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import _materialize_event_json

    with pytest.raises(DomainEventValidationError):
        _materialize_event_json(
            body=_body("event:trailing", payload_json=b'{"name":"NeontoF"}{"name":"extra"}'),
            sequence=1,
        )


def test_payload_json_rejects_duplicate_object_keys_at_any_depth() -> None:
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import _materialize_event_json

    with pytest.raises(DomainEventValidationError):
        _materialize_event_json(
            body=_body(
                "event:duplicate-key",
                payload_json=b'{"name":"NeontoF","nested":{"key":1,"key":2}}',
            ),
            sequence=1,
        )


def test_nested_payload_object_and_array_shapes_remain_distinct() -> None:
    from neontof.persistence.event_store import _materialize_event_json

    object_payload = b'{"kind":"fact","holder":"world","subject_id":null,"predicate":"shape","value":{"items":[1,2]}}'
    array_payload = (
        b'{"kind":"fact","holder":"world","subject_id":null,"predicate":"shape","value":[1,2]}'
    )
    object_raw, _ = _materialize_event_json(
        body=_body("event:object", "FactAsserted", payload_json=object_payload), sequence=1
    )
    array_raw, _ = _materialize_event_json(
        body=_body("event:array", "FactAsserted", payload_json=array_payload), sequence=2
    )

    assert object_payload in object_raw
    assert array_payload in array_raw
    assert object_raw != array_raw


def test_payload_boundary_allows_nested_payload_named_values() -> None:
    from neontof.persistence.event_store import _materialize_event_json

    payload = (
        b'{"kind":"fact","holder":"world","subject_id":null,"predicate":"shape",'
        b'"value":{"name":"nested","payload":{"name":"inner"}}}'
    )

    raw, _ = _materialize_event_json(
        body=_body("event:nested-payload", "FactAsserted", payload_json=payload), sequence=1
    )

    assert payload in raw
    assert raw.count(payload) == 1


def test_payload_boundary_failure_rolls_back_entire_batch(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.append(
            _batch(
                _draft("event:valid"),
                _draft("event:invalid", payload_json=b'{"name":1}'),
            )
        )

    assert _rows(path) == []


def test_unsequenced_envelope_materialization_stays_inside_event_store() -> None:
    from neontof.event_metadata import EventDraftBody
    from neontof.persistence.event_store import EventStore, _materialize_event_json

    assert "sequence" not in EventDraftBody.model_fields
    assert _materialize_event_json.__module__ == "neontof.persistence.event_store"
    assert not any(name == "materialize_event_json" for name in dir(EventStore))


def test_runtime_and_test_databases_stay_outside_repository_tree(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())


def test_duplicate_event_id_becomes_sanitized_event_store_constraint_error(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    store.append(_batch(_draft("event:duplicate-safe")))
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(EventStoreConstraintError) as raised:
        store.append(_batch(_draft("event:duplicate-safe")))

    assert raised.value.code == "duplicate_event_id"
    assert "sqlite" not in str(raised.value).lower()


def test_other_integrity_error_becomes_generic_event_constraint_violation(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    sentinel = "INTEGRITY_SECRET_SENTINEL"
    _add_abort_trigger(path, "event:integrity", sentinel)
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(EventStoreConstraintError) as raised:
        store.append(_batch(_draft("event:integrity")))

    assert raised.value.code == "event_constraint_violation"
    _assert_sanitized(raised.value, sentinel)


def test_domain_event_validation_error_keeps_phase_zero_issue_codes(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(DomainEventValidationError) as raised:
        store.append(_batch(_draft("event:invalid-payload", payload_json=b'{"name":1}')))

    assert {issue.code for issue in raised.value.issues} <= {
        "schema",
        "unknown_field",
        "unknown_event",
        "unknown_version",
        "invalid_id",
        "invalid_sequence",
        "invalid_payload",
    }
    assert not isinstance(raised.value, EventStoreConstraintError)


def test_database_error_becomes_safe_sqlite_operation_error(tmp_path: Path) -> None:
    database, _ = _make_database(tmp_path)
    sentinel = "DATABASE_SECRET_SENTINEL"
    from neontof.persistence.sqlite_database import SqliteOperationError

    with pytest.raises(SqliteOperationError) as raised:
        database._read(lambda connection: connection.execute(f"SELECT * FROM {sentinel}"))

    assert raised.value.code in {"locked", "io", "corrupt", "other"}
    _assert_sanitized(raised.value, sentinel)


def test_domain_event_validation_error_is_not_wrapped(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    from neontof.contracts.event_parser import DomainEventValidationError
    from neontof.persistence.event_store import EventStoreConstraintError

    with pytest.raises(DomainEventValidationError) as raised:
        store.append(_batch(_draft("event:not-wrapped", payload_json=b'{"name":true}')))

    assert not isinstance(raised.value, EventStoreConstraintError)
    assert raised.value.__cause__ is None


def test_read_campaign_rejects_duplicate_outer_json_keys(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:duplicate-outer")))
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:duplicate-outer'",
            (
                (
                    b'{"type":"CampaignCreated","type":"CampaignCreated",'
                    b'"event_id":"event:duplicate-outer","event_version":1,'
                    b'"campaign_id":"campaign:alpha","session_id":null,'
                    b'"scene_id":null,"turn_id":null,"sequence":1,'
                    b'"occurred_at":"2026-08-25T00:00:00Z","origin":"in_world",'
                    b'"visibility":"player_visible","payload":{"name":"NeontoF"}}'
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_campaign("campaign:alpha")


def test_read_campaign_rejects_derived_column_mismatch_even_when_json_is_valid(
    tmp_path: Path,
) -> None:
    _, store, path = _store(tmp_path)
    store.append(_batch(_draft("event:derived")))
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET occurred_at = '2026-08-26T00:00:00Z' WHERE event_id = 'event:derived'"
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        store.read_campaign("campaign:alpha")
