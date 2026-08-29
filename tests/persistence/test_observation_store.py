"""P1-02 typed observation persistence and transaction-boundary tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
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


def _observation_components() -> tuple[type[Any], type[Any], type[Any]]:
    try:
        from neontof.observability.records import TelemetryRecord, TranscriptRecord
        from neontof.persistence.observation_store import ObservationStore
    except ImportError:
        pytest.fail("P1-02 observation production modules are not available")
    return TranscriptRecord, TelemetryRecord, ObservationStore


def _database(tmp_path: Path) -> tuple[Any, Path]:
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = tmp_path / "runtime" / "observations.sqlite3"
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(path)
    database.migrate()
    return database, path


def _store(tmp_path: Path) -> tuple[Any, Any, Path]:
    database, path = _database(tmp_path)
    _, _, observation_store_type = _observation_components()
    return database, observation_store_type(database), path


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


def _transcript(
    kind: str,
    entry_id: str,
    *,
    data: object | None = None,
    campaign_id: str = "campaign:alpha",
    session_id: str | None = "session:main",
    turn_id: str | None = "turn:first",
    model_call_id: str | None = "model-call:first",
) -> Any:
    transcript_type, _, _ = _observation_components()
    payload = _payload(kind) if data is None else data
    return transcript_type(
        entry_id=entry_id,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        model_call_id=model_call_id,
        kind=kind,
        occurred_at=OCCURRED_AT,
        data=payload,
    )


def _telemetry(
    entry_id: str,
    *,
    campaign_id: str = "campaign:alpha",
    session_id: str = "session:main",
    turn_id: str = "turn:first",
    model_call_id: str = "model-call:first",
    status: str = "succeeded",
    error_code: str | None = None,
    cost_microusd: int = 0,
    **overrides: object,
) -> Any:
    _, telemetry_type, _ = _observation_components()
    values: dict[str, object] = {
        "entry_id": entry_id,
        "campaign_id": campaign_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "model_call_id": model_call_id,
        "provider": "fake_provider",
        "model": "test.model",
        "roles": ("referee",),
        "attempt": 1,
        "status": status,
        "input_tokens": 2,
        "output_tokens": 3,
        "cached_tokens": 0,
        "latency_ms": 4,
        "cost_microusd": cost_microusd,
        "error_code": error_code,
        "occurred_at": OCCURRED_AT,
    }
    values.update(overrides)
    return telemetry_type(**values)


def _raw_transcript_data(path: Path, entry_id: str) -> tuple[object, object]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT typeof(data_json), data_json FROM transcript_entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return row[0], row[1]


def _event_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT COUNT(*) FROM events").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


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


def test_observation_store_public_api_is_narrow(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)

    public_methods = {name for name in dir(type(store)) if not name.startswith("_")}

    assert public_methods == {
        "append_transcript",
        "append_telemetry",
        "read_transcript",
        "read_telemetry",
        "session_cost_microusd",
    }


@pytest.mark.parametrize("kind", TRANSCRIPT_KINDS)
def test_each_transcript_kind_is_persisted_with_typed_readback(tmp_path: Path, kind: str) -> None:
    _, store, _ = _store(tmp_path)
    transcript_type, _, _ = _observation_components()
    record = _transcript(kind, f"transcript:{kind.replace('_', '-')}")

    store.append_transcript(record)
    readback = store.read_transcript("campaign:alpha")

    assert isinstance(readback, tuple)
    assert len(readback) == 1
    assert type(readback[0]) is transcript_type
    assert readback[0].kind == kind


def test_tool_call_transcript_kind_is_supported(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    record = _transcript("tool_call", "transcript:tool-call")

    store.append_transcript(record)

    readback = store.read_transcript("campaign:alpha", "turn:first")
    storage_type, raw = _raw_transcript_data(path, "transcript:tool-call")
    assert readback[0].kind == "tool_call"
    assert storage_type == "blob"
    assert type(raw) is bytes
    assert json.loads(raw) == _payload("tool_call")


def test_transcript_and_telemetry_sequences_are_table_local(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    store.append_transcript(_transcript("player_input", "transcript:first"))
    store.append_transcript(_transcript("narrative", "transcript:second"))
    store.append_telemetry(_telemetry("telemetry:first"))
    store.append_telemetry(_telemetry("telemetry:second"))
    store.append_transcript(
        _transcript(
            "player_input",
            "transcript:other-campaign",
            campaign_id="campaign:beta",
        )
    )
    store.append_telemetry(_telemetry("telemetry:other-campaign", campaign_id="campaign:beta"))

    connection = sqlite3.connect(path)
    try:
        transcript_sequences = [
            row[0]
            for row in connection.execute(
                "SELECT append_sequence FROM transcript_entries "
                "WHERE campaign_id = ? ORDER BY append_sequence",
                ("campaign:alpha",),
            )
        ]
        telemetry_sequences = [
            row[0]
            for row in connection.execute(
                "SELECT append_sequence FROM telemetry_entries "
                "WHERE campaign_id = ? ORDER BY append_sequence",
                ("campaign:alpha",),
            )
        ]
        other_transcript_sequence = connection.execute(
            "SELECT append_sequence FROM transcript_entries WHERE campaign_id = ?",
            ("campaign:beta",),
        ).fetchone()[0]
        other_telemetry_sequence = connection.execute(
            "SELECT append_sequence FROM telemetry_entries WHERE campaign_id = ?",
            ("campaign:beta",),
        ).fetchone()[0]
    finally:
        connection.close()

    assert transcript_sequences == [1, 2]
    assert telemetry_sequences == [1, 2]
    assert other_transcript_sequence == 1
    assert other_telemetry_sequence == 1


def test_typed_observation_read_write_filters_by_campaign_and_turn(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    transcript_type, telemetry_type, _ = _observation_components()
    store.append_transcript(_transcript("player_input", "transcript:first"))
    store.append_transcript(_transcript("narrative", "transcript:second", turn_id="turn:second"))
    store.append_telemetry(_telemetry("telemetry:first", cost_microusd=7))
    store.append_telemetry(_telemetry("telemetry:second", turn_id="turn:second", cost_microusd=11))

    all_transcript = store.read_transcript("campaign:alpha")
    turn_transcript = store.read_transcript("campaign:alpha", "turn:first")
    all_telemetry = store.read_telemetry("campaign:alpha")
    turn_telemetry = store.read_telemetry("campaign:alpha", "turn:second")

    assert isinstance(all_transcript, tuple)
    assert all(type(record) is transcript_type for record in all_transcript)
    assert [record.entry_id for record in turn_transcript] == ["transcript:first"]
    assert all(type(record) is telemetry_type for record in all_telemetry)
    assert [record.entry_id for record in turn_telemetry] == ["telemetry:second"]


def test_transcript_data_is_stored_as_a_json_object_after_pydantic_conversion(
    tmp_path: Path,
) -> None:
    _, store, path = _store(tmp_path)
    record = _transcript("player_input", "transcript:object", data={"text": "hello"})

    store.append_transcript(record)

    storage_type, raw = _raw_transcript_data(path, "transcript:object")
    assert storage_type == "blob"
    assert type(raw) is bytes
    decoded = json.loads(raw)
    assert type(decoded) is dict
    assert decoded == {"text": "hello"}
    assert not isinstance(decoded, list)


def test_roles_json_is_an_array_for_empty_roles_and_preserves_role_order(
    tmp_path: Path,
) -> None:
    _, store, path = _store(tmp_path)
    empty_entry_id = "telemetry:empty-roles"
    ordered_entry_id = "telemetry:ordered-roles"
    store.append_telemetry(_telemetry(empty_entry_id, roles=()))
    ordered_roles = ("narrator", "referee", "world_simulator", "npc_actor")
    store.append_telemetry(_telemetry(ordered_entry_id, roles=ordered_roles))

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT entry_id, typeof(roles_json), roles_json FROM telemetry_entries "
            "ORDER BY append_sequence"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (empty_entry_id, "blob", b"[]"),
        (ordered_entry_id, "blob", b'["narrator","referee","world_simulator","npc_actor"]'),
    ]
    readback = store.read_telemetry("campaign:alpha")
    assert readback[0].roles == ()
    assert readback[1].roles == ordered_roles


@pytest.mark.parametrize(
    "key",
    ("raw_provider_body", "raw_provider_error", "cause", "prompt", "api_key"),
)
def test_purpose_allowlist_rejects_raw_provider_body_error_and_cause(
    tmp_path: Path, key: str
) -> None:
    _, store, path = _store(tmp_path)
    payload = _payload("error")
    payload[key] = SENTINEL

    with pytest.raises(OBSERVATION_FAILURES) as raised:
        store.append_transcript(_transcript("error", "transcript:raw", data=payload))

    _assert_safe_failure(raised.value, SENTINEL)
    assert store.read_transcript("campaign:alpha") == ()
    assert _event_count(path) == 0


@pytest.mark.parametrize(
    ("kind", "payload"),
    (
        ("unknown", {"text": "hello"}),
        ("player_input", {"text": "hello", "extra": "unknown"}),
        ("player_input", {"text": "hello", "nested": {"value": "nested"}}),
        (
            "error",
            {"error_code": "model_error", "digest": SHA256, "byte_length": 0, "body": "raw"},
        ),
    ),
)
def test_transcript_data_rejects_unknown_kind_key_nested_object_and_raw_value(
    tmp_path: Path, kind: str, payload: dict[str, object]
) -> None:
    _, store, _ = _store(tmp_path)

    with pytest.raises(OBSERVATION_FAILURES):
        store.append_transcript(_transcript(kind, "transcript:invalid", data=payload))


def test_raw_invalid_model_body_is_not_persisted(tmp_path: Path) -> None:
    _, store, path = _store(tmp_path)
    raw_body = f'{{"error":"{SENTINEL}"}}'
    invalid_payload = {
        "error_code": "invalid_json",
        "digest": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
        "byte_length": len(raw_body.encode("utf-8")),
        "body": raw_body,
    }

    with pytest.raises(OBSERVATION_FAILURES):
        store.append_transcript(
            _transcript("error", "transcript:invalid-body", data=invalid_payload)
        )

    safe_payload = {
        "error_code": "invalid_json",
        "digest": hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
        "byte_length": len(raw_body.encode("utf-8")),
    }
    store.append_transcript(_transcript("error", "transcript:safe-error", data=safe_payload))

    _, raw = _raw_transcript_data(path, "transcript:safe-error")
    assert type(raw) is bytes
    assert SENTINEL.encode("utf-8") not in raw
    assert json.loads(raw) == safe_payload


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
def test_telemetry_status_and_error_code_are_persisted(
    tmp_path: Path, status: str, error_code: str | None
) -> None:
    _, store, _ = _store(tmp_path)
    record = _telemetry(
        f"telemetry:{status.replace('_', '-')}-{(error_code or 'none').replace('_', '-')}",
        status=status,
        error_code=error_code,
    )

    store.append_telemetry(record)

    readback = store.read_telemetry("campaign:alpha")
    assert readback[0].status == status
    assert readback[0].error_code == error_code


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
def test_telemetry_status_and_error_code_mismatch_is_rejected(
    tmp_path: Path, status: str, error_code: str | None
) -> None:
    _, store, _ = _store(tmp_path)

    with pytest.raises(OBSERVATION_FAILURES):
        store.append_telemetry(
            _telemetry(
                "telemetry:mismatch",
                status=status,
                error_code=error_code,
            )
        )


def test_failed_script_exhausted_is_rejected_before_storage(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    valid_record = _telemetry(
        "telemetry:script-exhausted", status="failed", error_code="model_error"
    )
    invalid_record = valid_record.model_copy(
        update={"status": "failed", "error_code": "script_exhausted"}
    )

    with pytest.raises(OBSERVATION_FAILURES) as raised:
        store.append_telemetry(invalid_record)

    _assert_safe_failure(raised.value, SENTINEL)
    assert store.read_telemetry("campaign:alpha") == ()


def test_session_cost_sums_sqlite_integer_max_values_in_python(tmp_path: Path) -> None:
    _, store, _ = _store(tmp_path)
    store.append_telemetry(_telemetry("telemetry:max-cost-one", cost_microusd=MAX_SAFE_INTEGER))
    store.append_telemetry(_telemetry("telemetry:max-cost-two", cost_microusd=MAX_SAFE_INTEGER))

    assert store.session_cost_microusd("campaign:alpha", "session:main") == (MAX_SAFE_INTEGER * 2)


class _NonReentrantLockProbe:
    def __init__(self) -> None:
        self.depth = 0
        self.acquire_count = 0

    def __enter__(self) -> Self:
        if self.depth != 0:
            raise AssertionError("single writer lock was acquired recursively")
        self.depth = 1
        self.acquire_count += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback_value: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc_value, traceback_value
        self.depth = 0
        return False


def test_observation_append_does_not_nested_acquire_single_writer_lock(
    tmp_path: Path,
) -> None:
    database, store, _ = _store(tmp_path)
    lock_probe = _NonReentrantLockProbe()
    database._write_lock = lock_probe

    store.append_transcript(_transcript("player_input", "transcript:lock"))

    assert lock_probe.acquire_count == 1
    assert lock_probe.depth == 0


def test_observation_types_cannot_be_appended_to_event_store(tmp_path: Path) -> None:
    database, _store_instance, path = _store(tmp_path)
    try:
        from neontof.persistence.event_store import EventStore
    except ImportError:
        pytest.fail("P1-01 EventStore is not available")
    event_store = EventStore(database)
    observation = _transcript("player_input", "transcript:not-event")

    with pytest.raises(OBSERVATION_FAILURES):
        event_store.append(observation)

    assert _event_count(path) == 0
    assert not hasattr(event_store, "append_transcript")
    assert not hasattr(event_store, "append_telemetry")
