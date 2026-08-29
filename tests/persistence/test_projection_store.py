"""P1-01b projection snapshot and rebuild contract tests."""

from __future__ import annotations

import json
import sqlite3
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "events"


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime" / "projection-store.sqlite3"
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    return path


def _store(tmp_path: Path) -> tuple[Any, Any, Any, Path]:
    from neontof.persistence.event_store import EventStore
    from neontof.persistence.projection_store import ProjectionStore
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    database = SqliteDatabase(path)
    database.migrate()
    event_store = EventStore(database)
    return database, event_store, ProjectionStore(database, event_store), path


def _connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _event_rows(path: Path) -> list[tuple[Any, ...]]:
    connection = _connection(path)
    try:
        return connection.execute(
            "SELECT campaign_id, sequence, event_id, type, event_version, session_id, "
            "scene_id, turn_id, occurred_at, origin, visibility, event_json "
            "FROM events ORDER BY campaign_id, sequence"
        ).fetchall()
    finally:
        connection.close()


def _snapshot_row(path: Path, campaign_id: str) -> tuple[Any, ...] | None:
    connection = _connection(path)
    try:
        row = connection.execute(
            "SELECT campaign_id, through_sequence, projection_json "
            "FROM projection_snapshots WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return None if row is None else tuple(row)
    finally:
        connection.close()


def _body(
    event_id: str,
    event_type: str = "CampaignCreated",
    *,
    campaign_id: str = "campaign:alpha",
    session_id: str | None = None,
    scene_id: str | None = None,
    turn_id: str | None = None,
    turn_request_id: str = "turn-request:first",
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

    payload: dict[str, object]
    if event_type == "CampaignCreated":
        payload = {"name": "NeontoF"}
    elif event_type == "SessionStarted":
        payload = {"scenario_id": None, "title": "Opening"}
    elif event_type == "PlayerInputAccepted":
        payload = {"turn_request_id": turn_request_id, "input_digest": "a" * 64}
    elif event_type in {"TurnResumed", "TurnCommitted"}:
        payload = {"turn_request_id": turn_request_id}
    elif event_type == "TurnReverted":
        payload = {"target_turn_id": "turn:first"}
    else:
        raise AssertionError(f"test helper has no payload for {event_type}")

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


def _append_campaign_created(event_store: Any, *, campaign_id: str = "campaign:alpha") -> None:
    event_store.append(
        _batch(
            _draft("event:created", campaign_id=campaign_id),
            campaign_id=campaign_id,
        )
    )


def _append_campaign_and_session(event_store: Any, *, campaign_id: str = "campaign:alpha") -> None:
    event_store.append(
        _batch(
            _draft("event:created", campaign_id=campaign_id),
            _draft(
                "event:session",
                "SessionStarted",
                campaign_id=campaign_id,
                session_id="session:main",
            ),
            campaign_id=campaign_id,
        )
    )


def _projection_json(snapshot: Any) -> bytes:
    serialized = snapshot.projection.model_dump_json()
    if not isinstance(serialized, str):
        raise TypeError("projection JSON serializer returned a non-string value")
    return serialized.encode("utf-8")


def _assert_snapshot_schema_error(error: BaseException, sentinel: str | None = None) -> None:
    surfaces = (
        str(error),
        repr(error),
        repr(error.args),
        repr(getattr(error, "input", None)),
        repr(getattr(error, "issues", None)),
        repr(getattr(error, "__dict__", {})),
        repr(error.__cause__),
        repr(error.__context__),
        "".join(traceback.format_exception(type(error), error, error.__traceback__)),
    )
    if sentinel is not None:
        assert all(sentinel not in surface for surface in surfaces)
    issues = getattr(error, "issues", None)
    assert isinstance(issues, tuple)
    assert len(issues) == 1
    assert issues[0].path == "projection_snapshot"
    assert issues[0].code == "schema"
    assert issues[0].message == "projection snapshot validation failed"
    assert error.__cause__ is None
    assert error.__context__ is None


def _replace_snapshot(
    path: Path,
    *,
    campaign_id: str,
    through_sequence: int,
    projection_json: bytes,
) -> None:
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE projection_snapshots SET through_sequence = ?, projection_json = ? "
            "WHERE campaign_id = ?",
            (through_sequence, sqlite3.Binary(projection_json), campaign_id),
        )
        connection.commit()
    finally:
        connection.close()


def _insert_fixture_events(path: Path) -> None:
    raw_events = json.loads((FIXTURE_ROOT / "minimal-session.v1.json").read_text(encoding="utf-8"))
    connection = _connection(path)
    try:
        for event in raw_events:
            envelope = {
                "type": event["type"],
                "event_id": event["event_id"],
                "event_version": event["event_version"],
                "campaign_id": event["campaign_id"],
                "session_id": event["session_id"],
                "scene_id": event["scene_id"],
                "turn_id": event["turn_id"],
                "sequence": event["sequence"],
                "occurred_at": event["occurred_at"],
                "origin": event["origin"],
                "visibility": event["visibility"],
                "payload": event["payload"],
            }
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event["campaign_id"],
                    event["sequence"],
                    event["event_id"],
                    event["type"],
                    event["event_version"],
                    event["session_id"],
                    event["scene_id"],
                    event["turn_id"],
                    event["occurred_at"],
                    event["origin"],
                    event["visibility"],
                    sqlite3.Binary(json.dumps(envelope, separators=(",", ":")).encode("utf-8")),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def test_delete_projection_does_not_delete_events(tmp_path: Path) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_and_session(event_store)
    before = _event_rows(path)

    projection_store.rebuild("campaign:alpha")
    projection_store.delete("campaign:alpha")

    assert _event_rows(path) == before
    assert [event.event_id for event in event_store.read_campaign("campaign:alpha")] == [
        "event:created",
        "event:session",
    ]
    assert _snapshot_row(path, "campaign:alpha") is None


def test_rebuild_after_delete_returns_identical_projection(tmp_path: Path) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_and_session(event_store)

    first = projection_store.rebuild("campaign:alpha")
    first_bytes = _projection_json(first)
    projection_store.delete("campaign:alpha")
    second = projection_store.rebuild("campaign:alpha")

    assert second.through_sequence == 2
    assert _projection_json(second) == first_bytes
    assert _snapshot_row(path, "campaign:alpha") == (
        "campaign:alpha",
        2,
        first_bytes,
    )


def test_snapshot_through_sequence_matches_event_log(tmp_path: Path) -> None:
    _, event_store, projection_store, _ = _store(tmp_path)

    empty = projection_store.rebuild("campaign:empty")
    assert empty.campaign_id == "campaign:empty"
    assert empty.through_sequence == 0

    _append_campaign_created(event_store)
    one = projection_store.rebuild("campaign:alpha")
    assert one.through_sequence == 1

    event_store.append(
        _batch(
            _draft(
                "event:session",
                "SessionStarted",
                session_id="session:main",
            )
        )
    )
    many = projection_store.rebuild("campaign:alpha")
    assert many.through_sequence == 2

    event_store.append(
        _batch(
            _draft("event:other-created", campaign_id="campaign:other"),
            campaign_id="campaign:other",
        )
    )
    other = projection_store.rebuild("campaign:other")
    assert other.campaign_id == "campaign:other"
    assert other.through_sequence == 1
    assert projection_store.read("campaign:alpha").through_sequence == 2


def test_projection_store_has_no_state_mutation_method(tmp_path: Path) -> None:
    _, _, projection_store, _ = _store(tmp_path)

    public_methods = {name for name in dir(type(projection_store)) if not name.startswith("_")}
    assert public_methods == {"delete", "read", "rebuild"}
    assert not any(name in public_methods for name in ("append", "update", "set_state"))


def test_reverted_turn_is_removed_after_rebuild(tmp_path: Path) -> None:
    _, _, projection_store, path = _store(tmp_path)
    _insert_fixture_events(path)

    snapshot = projection_store.rebuild("campaign:alpha")

    assert snapshot.through_sequence == 27
    assert "turn:two" in snapshot.projection.reverted_turn_ids
    assert "turn:three" not in snapshot.projection.reverted_turn_ids


def test_rebuild_reads_complete_campaign_before_pure_projection(tmp_path: Path) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_and_session(event_store)
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE events SET event_json = ? WHERE event_id = 'event:session'",
            (sqlite3.Binary(b"not-json"),),
        )
        connection.commit()
    finally:
        connection.close()
    rows_before_rebuild = _event_rows(path)

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError):
        projection_store.rebuild("campaign:alpha")

    assert _event_rows(path) == rows_before_rebuild
    assert _snapshot_row(path, "campaign:alpha") is None


@pytest.mark.parametrize(
    ("raw", "sentinel"),
    (
        (b'{"secret":"SNAPSHOT_JSON_SECRET"', "SNAPSHOT_JSON_SECRET"),
        (b"\xffSNAPSHOT_UTF8_SECRET", "SNAPSHOT_UTF8_SECRET"),
    ),
)
def test_corrupt_snapshot_read_is_sanitized(tmp_path: Path, raw: bytes, sentinel: str) -> None:
    _, _, projection_store, path = _store(tmp_path)
    connection = _connection(path)
    try:
        connection.execute(
            "INSERT INTO projection_snapshots "
            "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?)",
            ("campaign:alpha", 0, sqlite3.Binary(raw)),
        )
        connection.commit()
    finally:
        connection.close()

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError) as raised:
        projection_store.read("campaign:alpha")

    _assert_snapshot_schema_error(raised.value, sentinel)


@pytest.mark.parametrize(
    ("row_through_sequence", "projection_field", "projection_value"),
    (
        (2, None, None),
        (1, "campaign_id", "campaign:other"),
        (1, "campaign_id", None),
    ),
)
def test_snapshot_row_and_projection_metadata_mismatch_is_schema_error(
    tmp_path: Path,
    row_through_sequence: int,
    projection_field: str | None,
    projection_value: str | None,
) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_created(event_store)
    snapshot = projection_store.rebuild("campaign:alpha")
    projection_json = json.loads(_projection_json(snapshot))
    if projection_field is not None:
        projection_json[projection_field] = projection_value
    _replace_snapshot(
        path,
        campaign_id="campaign:alpha",
        through_sequence=row_through_sequence,
        projection_json=json.dumps(projection_json, separators=(",", ":")).encode("utf-8"),
    )

    from neontof.contracts.event_parser import DomainEventValidationError

    with pytest.raises(DomainEventValidationError) as raised:
        projection_store.read("campaign:alpha")

    _assert_snapshot_schema_error(raised.value)


def test_stale_rebuild_does_not_overwrite_newer_snapshot(tmp_path: Path) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_and_session(event_store)
    initial = projection_store.rebuild("campaign:alpha")
    newer_json = json.loads(_projection_json(initial))
    newer_json["campaign_name"] = "stored-newer"
    newer_json["applied_through_sequence"] = 99
    newer_bytes = json.dumps(newer_json, separators=(",", ":")).encode("utf-8")

    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE projection_snapshots SET through_sequence = ?, projection_json = ? "
            "WHERE campaign_id = ?",
            (99, sqlite3.Binary(newer_bytes), "campaign:alpha"),
        )
        connection.commit()
    finally:
        connection.close()

    result = projection_store.rebuild("campaign:alpha")

    assert result.through_sequence == 99
    assert _snapshot_row(path, "campaign:alpha") == (
        "campaign:alpha",
        99,
        newer_bytes,
    )


def test_equal_rebuild_does_not_overwrite_equal_snapshot(tmp_path: Path) -> None:
    _, event_store, projection_store, path = _store(tmp_path)
    _append_campaign_created(event_store)
    initial = projection_store.rebuild("campaign:alpha")
    equal_json = json.loads(_projection_json(initial))
    equal_json["campaign_name"] = "stored-equal"
    equal_bytes = json.dumps(equal_json, separators=(",", ":")).encode("utf-8")

    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE projection_snapshots SET projection_json = ? WHERE campaign_id = ?",
            (sqlite3.Binary(equal_bytes), "campaign:alpha"),
        )
        connection.commit()
    finally:
        connection.close()

    result = projection_store.rebuild("campaign:alpha")

    assert result.through_sequence == 1
    assert _snapshot_row(path, "campaign:alpha") == (
        "campaign:alpha",
        1,
        equal_bytes,
    )


def test_projection_rebuild_barrier_preserves_monotonic_through_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event_store, projection_store, _ = _store(tmp_path)
    _append_campaign_created(event_store)

    from neontof.contracts.projection import rebuild_projection as real_rebuild_projection
    from neontof.persistence import projection_store as projection_store_module

    rebuild_entered = threading.Event()
    release_rebuild = threading.Event()

    def blocked_rebuild(events: Any) -> Any:
        rebuild_entered.set()
        if not release_rebuild.wait(timeout=5):
            raise AssertionError("rebuild barrier was not released")
        return real_rebuild_projection(events)

    monkeypatch.setattr(projection_store_module, "rebuild_projection", blocked_rebuild)
    real_append = event_store.append
    append_entered = threading.Event()

    def observed_append(batch: Any) -> Any:
        append_entered.set()
        return real_append(batch)

    monkeypatch.setattr(event_store, "append", observed_append)
    with ThreadPoolExecutor(max_workers=2) as executor:
        rebuild_future = executor.submit(projection_store.rebuild, "campaign:alpha")
        assert rebuild_entered.wait(timeout=5)
        append_future = executor.submit(
            event_store.append,
            _batch(
                _draft("event:session", "SessionStarted", session_id="session:main"),
            ),
        )
        assert append_entered.wait(timeout=5)
        try:
            with pytest.raises(TimeoutError):
                append_future.result(timeout=0.2)
        finally:
            release_rebuild.set()

        rebuilt = rebuild_future.result(timeout=5)
        append_result = append_future.result(timeout=5)

    assert append_result is not None
    final = projection_store.rebuild("campaign:alpha")
    assert rebuilt.through_sequence == 1
    assert final.through_sequence == 2
    assert final.through_sequence >= rebuilt.through_sequence


def test_projection_rebuild_does_not_use_filtered_event_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, event_store, projection_store, _ = _store(tmp_path)
    _append_campaign_created(event_store)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("filtered or snapshot read was used as rebuild input")

    monkeypatch.setattr(event_store, "read_session", forbidden)
    monkeypatch.setattr(event_store, "read_turn", forbidden)
    monkeypatch.setattr(event_store, "find_turn_by_request", forbidden)
    monkeypatch.setattr(projection_store, "read", forbidden)

    rebuilt = projection_store.rebuild("campaign:alpha")

    assert rebuilt.through_sequence == 1


def test_rebuild_uses_the_same_write_connection_for_complete_event_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, event_store, projection_store, _ = _store(tmp_path)
    _append_campaign_created(event_store)

    opened_connections: list[sqlite3.Connection] = []
    read_connections: list[sqlite3.Connection] = []
    real_open_connection = database._open_connection

    def observed_open_connection() -> sqlite3.Connection:
        connection = real_open_connection()
        assert isinstance(connection, sqlite3.Connection)
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr(database, "_open_connection", observed_open_connection)

    def forbidden_public_read(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("rebuild must not call public EventStore.read_campaign")

    monkeypatch.setattr(event_store, "read_campaign", forbidden_public_read)
    real_read_on_connection = event_store._read_campaign_on_connection

    def observed_read_on_connection(
        connection: sqlite3.Connection, campaign_id: str
    ) -> tuple[Any, ...]:
        read_connections.append(connection)
        events = real_read_on_connection(connection, campaign_id)
        assert isinstance(events, tuple)
        return events

    monkeypatch.setattr(event_store, "_read_campaign_on_connection", observed_read_on_connection)

    rebuilt = projection_store.rebuild("campaign:alpha")

    assert rebuilt.through_sequence == 1
    assert len(opened_connections) == 1
    assert read_connections == [opened_connections[0]]
