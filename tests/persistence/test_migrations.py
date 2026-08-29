"""P1-01a SQLite migration runner and schema contract tests."""

from __future__ import annotations

import hashlib
import inspect
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL_PATH = (
    REPOSITORY_ROOT / "src" / "neontof" / "persistence" / "migrations" / "0001_event_store.sql"
)


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime" / "event-store.sqlite3"
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    return path


def _database(tmp_path: Path) -> Any:
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteDatabase(path)


def _connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _memory_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    assert isinstance(connection, sqlite3.Connection)
    return connection


def _migrate(tmp_path: Path) -> Path:
    database = _database(tmp_path)
    database.migrate()
    return _database_path(tmp_path)


def _migration_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: dict[str, bytes]
) -> None:
    from neontof.persistence import migrations

    directory = tmp_path / "migration-source"
    directory.mkdir(exist_ok=True)
    for name, raw_sql in files.items():
        (directory / name).write_bytes(raw_sql)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIRECTORY", directory)


def _base_migration_files() -> dict[str, bytes]:
    return {"0001_event_store.sql": MIGRATION_SQL_PATH.read_bytes()}


def _schema_migration_rows(path: Path) -> list[tuple[Any, ...]]:
    connection = _connection(path)
    try:
        return connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations"
        ).fetchall()
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
    assert error.args == ("migration failed",)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert getattr(error, "__dict__", {}) == {}


def test_migration_is_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    database.migrate()
    first_rows = _schema_migration_rows(_database_path(tmp_path))

    database.migrate()

    assert _schema_migration_rows(_database_path(tmp_path)) == first_rows


def test_migration_0001_creates_only_schema_migrations_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _migration_dir(monkeypatch, tmp_path, _base_migration_files())
    _database(tmp_path).migrate()
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in tables] == ["events", "schema_migrations"]


def test_migration_0002_creates_only_projection_snapshots(tmp_path: Path) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.sqlite_database import SqliteDatabase

    migration_path = migrations.MIGRATIONS_DIRECTORY / "0002_projection_snapshots.sql"
    assert migration_path.is_file()
    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    SqliteDatabase(path).migrate()

    connection = _connection(path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        rows = connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert tables == {"schema_migrations", "events", "projection_snapshots"}
    assert [row[0] for row in rows] == [1, 2]


def test_projection_snapshots_schema_has_primary_key_sequence_check_and_blob(
    tmp_path: Path,
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.sqlite_database import SqliteDatabase

    migration_path = migrations.MIGRATIONS_DIRECTORY / "0002_projection_snapshots.sql"
    assert migration_path.is_file()
    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    SqliteDatabase(path).migrate()

    connection = _connection(path)
    try:
        columns = connection.execute("PRAGMA table_info(projection_snapshots)").fetchall()
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'projection_snapshots'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO projection_snapshots "
            "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?)",
            ("campaign:alpha", 0, sqlite3.Binary(b"{}")),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO projection_snapshots "
                "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?)",
                ("campaign:alpha", 0, sqlite3.Binary(b"{}")),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO projection_snapshots "
                "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?)",
                ("campaign:negative", -1, sqlite3.Binary(b"{}")),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO projection_snapshots "
                "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?)",
                ("campaign:text", 0, "{}"),
            )
    finally:
        connection.close()

    assert [(row[1], row[2], row[3], row[5]) for row in columns] == [
        ("campaign_id", "TEXT", 0, 1),
        ("through_sequence", "INTEGER", 1, 0),
        ("projection_json", "BLOB", 1, 0),
    ]
    normalized_sql = " ".join(sql.split()).upper()
    assert "PRIMARY KEY" in normalized_sql
    assert "CHECK (THROUGH_SEQUENCE >= 0)" in normalized_sql
    assert "CHECK (TYPEOF(PROJECTION_JSON) = 'BLOB')" in normalized_sql


def test_schema_set_maximum_is_two_without_gap_or_unknown_version(tmp_path: Path) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    SqliteDatabase(path).migrate()
    connection = _connection(path)
    try:
        rows = connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [1, 2]
    assert max(row[0] for row in rows) == 2
    assert [row[0] for row in rows] == list(range(1, 3))
    assert rows[1] == (
        2,
        "0002_projection_snapshots.sql",
        hashlib.sha256(
            (migrations.MIGRATIONS_DIRECTORY / "0002_projection_snapshots.sql").read_bytes()
        ).hexdigest(),
    )


def test_schema_migrations_shape_and_checksum_constraint(tmp_path: Path) -> None:
    path = _migrate(tmp_path)
    connection = _connection(path)
    try:
        columns = connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum_sha256) VALUES (?, ?, ?)",
                (2, "0002_bad.sql", "0" * 63),
            )
    finally:
        connection.close()

    assert [(row[1], row[2], row[3], row[5]) for row in columns] == [
        ("version", "INTEGER", 0, 1),
        ("name", "TEXT", 1, 0),
        ("checksum_sha256", "TEXT", 1, 0),
    ]
    assert "UNIQUE" in sql.upper()
    assert "CHECK" in sql.upper()


def test_schema_migrations_rejects_non_lowercase_hex_checksum(tmp_path: Path) -> None:
    path = _migrate(tmp_path)
    connection = _connection(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE schema_migrations SET checksum_sha256 = ? WHERE version = 1",
                ("A" + "0" * 63,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE schema_migrations SET checksum_sha256 = ? WHERE version = 1",
                ("g" + "0" * 63,),
            )
    finally:
        connection.close()


def test_events_schema_exposes_exact_columns_and_constraints(tmp_path: Path) -> None:
    path = _migrate(tmp_path)
    connection = _connection(path)
    try:
        columns = connection.execute("PRAGMA table_info(events)").fetchall()
        indexes = connection.execute("PRAGMA index_list(events)").fetchall()
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'events'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert [(row[1], row[2], row[3], row[5]) for row in columns] == [
        ("campaign_id", "TEXT", 1, 1),
        ("sequence", "INTEGER", 1, 2),
        ("event_id", "TEXT", 1, 0),
        ("type", "TEXT", 1, 0),
        ("event_version", "INTEGER", 1, 0),
        ("session_id", "TEXT", 0, 0),
        ("scene_id", "TEXT", 0, 0),
        ("turn_id", "TEXT", 0, 0),
        ("occurred_at", "TEXT", 1, 0),
        ("origin", "TEXT", 1, 0),
        ("visibility", "TEXT", 1, 0),
        ("event_json", "BLOB", 1, 0),
    ]
    assert sum(row[2] == 1 for row in indexes) == 2
    assert "PRIMARY KEY (campaign_id, sequence)" in sql
    assert "UNIQUE (event_id)" in sql


def test_schema_introspection_checks_table_info_index_list_index_xinfo_and_sqlite_master_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _migration_dir(monkeypatch, tmp_path, _base_migration_files())
    _database(tmp_path).migrate()
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        table_info = connection.execute("PRAGMA table_info(events)").fetchall()
        index_list = connection.execute("PRAGMA index_list(events)").fetchall()
        index_xinfo = {
            row[1]: connection.execute(f'PRAGMA index_xinfo("{row[1]}")').fetchall()
            for row in index_list
        }
        master_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    finally:
        connection.close()

    assert len(table_info) == 12
    assert len(index_list) == 2
    assert all(rows for rows in index_xinfo.values())
    assert len(master_sql) == 2
    assert all(isinstance(row[0], str) for row in master_sql)


def test_event_schema_rejects_not_null_check_and_unique_sabotage(tmp_path: Path) -> None:
    path = _migrate(tmp_path)
    connection = _connection(path)
    valid = (
        "campaign:alpha",
        1,
        "event:one",
        "CampaignCreated",
        1,
        None,
        None,
        None,
        "2026-08-25T00:00:00Z",
        "in_world",
        "player_visible",
        sqlite3.Binary(b"{}"),
    )
    try:
        connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", valid)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (None, *valid[1:]),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*valid[:1], 0, *valid[2:]),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*valid[:4], 2, *valid[5:]),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*valid[:9], "system", *valid[10:]),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*valid[:2], "event:one", *valid[3:]),
            )
    finally:
        connection.close()


def test_event_json_storage_type_is_blob(tmp_path: Path) -> None:
    path = _migrate(tmp_path)
    connection = _connection(path)
    try:
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "campaign:alpha",
                1,
                "event:blob",
                "CampaignCreated",
                1,
                None,
                None,
                None,
                "2026-08-25T00:00:00Z",
                "in_world",
                "player_visible",
                sqlite3.Binary(b"{}"),
            ),
        )
        storage_type = connection.execute(
            "SELECT typeof(event_json) FROM events WHERE event_id = 'event:blob'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert storage_type == "blob"


def test_schema_set_maximum_is_one_without_gap_or_unknown_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _migration_dir(monkeypatch, tmp_path, _base_migration_files())
    _database(tmp_path).migrate()
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        connection.close()

    assert versions == [1]
    assert max(versions) == 1
    assert versions == list(range(1, max(versions) + 1))
    assert tables == {"schema_migrations", "events"}


def test_migrate_sets_wal_outside_transaction_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    database = _database(tmp_path)
    database.migrate()

    wal_indexes = [
        index
        for index, statement in enumerate(traces)
        if statement.lower().replace(" ", "") == "pragmajournal_mode=wal"
    ]
    begin_indexes = [
        index for index, statement in enumerate(traces) if "begin immediate" in statement.lower()
    ]
    assert len(wal_indexes) == 1
    assert len(begin_indexes) >= 1
    assert wal_indexes[0] < begin_indexes[0]


def test_bootstrap_checks_schema_migrations_existence_before_select(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    _database(tmp_path).migrate()

    normalized = [statement.lower() for statement in traces]
    existence_index = next(
        index
        for index, statement in enumerate(normalized)
        if "from sqlite_master" in statement and "schema_migrations" in statement
    )
    selects = [
        statement
        for statement in normalized[: existence_index + 1]
        if "from schema_migrations" in statement
    ]
    assert not selects


def test_bootstrap_validates_schema_migrations_shape_before_read(tmp_path: Path) -> None:
    path = _database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = _connection(path)
    try:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER NOT NULL)")
        connection.commit()
    finally:
        connection.close()

    from neontof.persistence.migrations import MigrationError

    with pytest.raises(MigrationError):
        _database(tmp_path).migrate()


def test_bootstrap_does_not_swallow_unexpected_no_such_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    _migrate(tmp_path)
    sentinel = "BOOTSTRAP_SECRET_SENTINEL"

    def fail_read(connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
        del connection
        raise sqlite3.OperationalError(f"no such table: schema_migrations {sentinel}")

    monkeypatch.setattr(migrations, "_read_applied_migrations", fail_read)
    with pytest.raises(MigrationError) as raised:
        _database(tmp_path).migrate()

    _assert_sanitized(raised.value, sentinel)


def test_migration_rejects_version_name_drift_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE should_not_exist (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        connection.execute("UPDATE schema_migrations SET name = 'wrong.sql' WHERE version = 1")
        connection.commit()
    finally:
        connection.close()

    rows_before = _schema_migration_rows(path)
    backup_calls: list[Path] = []

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        del connection
        backup_calls.append(database_path)
        raise AssertionError("backup must not run after name drift validation failure")

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "version_name_drift"
    _assert_sanitized(raised.value, "VERSION_NAME_DRIFT_SECRET_SENTINEL")
    assert backup_calls == []
    connection = _connection(path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_not_exist'"
            ).fetchone()
            is None
        )
        assert _schema_migration_rows(path) == rows_before
    finally:
        connection.close()


def test_migration_rejects_checksum_drift_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE should_not_exist (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum_sha256 = ? WHERE version = 1",
            ("0" * 63 + "1",),
        )
        connection.commit()
    finally:
        connection.close()

    rows_before = _schema_migration_rows(path)
    backup_calls: list[Path] = []

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        del connection
        backup_calls.append(database_path)
        raise AssertionError("backup must not run after checksum drift validation failure")

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "checksum_drift"
    _assert_sanitized(raised.value, "CHECKSUM_DRIFT_SECRET_SENTINEL")
    assert backup_calls == []
    connection = _connection(path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_not_exist'"
            ).fetchone()
            is None
        )
        assert _schema_migration_rows(path) == rows_before
    finally:
        connection.close()


def test_discover_migrations_rejects_duplicate_available_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    _migration_dir(
        monkeypatch,
        tmp_path,
        {
            "0001_event_store.sql": MIGRATION_SQL_PATH.read_bytes(),
            "0001_other.sql": b"CREATE TABLE duplicate_version (value TEXT);\n",
        },
    )

    with pytest.raises(MigrationError) as raised:
        migrations._discover_migrations()

    assert raised.value.code == "duplicate"


@pytest.mark.parametrize(
    ("bad_row", "expected_code"),
    [
        (
            (3, "0003_later.sql", "3" * 64),
            "gap",
        ),
        (
            (99, "0099_unknown.sql", "9" * 64),
            "unknown_applied_version",
        ),
    ],
)
def test_real_applied_gap_or_unknown_version_stops_before_ddl_row_or_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_row: tuple[int, str, str],
    expected_code: str,
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE should_not_exist (value TEXT);\n"
    files["0003_later.sql"] = b"CREATE TABLE should_not_exist_later (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        if expected_code == "gap":
            bad_row = (
                bad_row[0],
                bad_row[1],
                hashlib.sha256(files["0003_later.sql"]).hexdigest(),
            )
        connection.execute(
            "INSERT INTO schema_migrations(version, name, checksum_sha256) VALUES (?, ?, ?)",
            bad_row,
        )
        connection.commit()
        rows_before = _schema_migration_rows(path)
    finally:
        connection.close()

    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connected = real_connect(*args, **kwargs)
        assert isinstance(connected, sqlite3.Connection)
        connected.set_trace_callback(traces.append)
        return connected

    backup_calls: list[Path] = []

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        del connection
        backup_calls.append(database_path)
        raise AssertionError("backup must not run after applied-row validation failure")

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == expected_code
    normalized = [statement.lower() for statement in traces]
    assert not any("create table should_not_exist" in statement for statement in normalized)
    assert not any("insert into schema_migrations" in statement for statement in normalized)
    assert backup_calls == []
    assert _schema_migration_rows(path) == rows_before


def test_migration_validation_and_pending_detection_stay_inside_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    _database(tmp_path).migrate()

    normalized = [statement.lower() for statement in traces]
    begin_index = next(
        index for index, statement in enumerate(normalized) if "begin immediate" in statement
    )
    validation_index = next(
        index for index, statement in enumerate(normalized) if "from sqlite_master" in statement
    )
    assert begin_index < validation_index


def test_migration_ddl_and_schema_row_share_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    _database(tmp_path).migrate()
    normalized = [statement.lower() for statement in traces]
    begin = next(
        index for index, statement in enumerate(normalized) if "begin immediate" in statement
    )
    ddl = next(
        index for index, statement in enumerate(normalized) if "create table events" in statement
    )
    row_insert = next(
        index
        for index, statement in enumerate(normalized)
        if "insert into schema_migrations" in statement
    )
    commit = next(index for index, statement in enumerate(normalized) if statement == "commit")
    assert begin < ddl < row_insert < commit


def test_pending_migration_backups_existing_database_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    calls: list[Path] = []
    real_backup = migrations._backup_existing_database

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        backup_path = real_backup(connection, database_path)
        calls.append(backup_path)
        return backup_path

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    database.migrate()

    assert len(calls) == 1
    assert calls[0].is_file()
    assert not calls[0].resolve().is_relative_to(REPOSITORY_ROOT.resolve())


def test_new_database_does_not_create_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    calls: list[tuple[sqlite3.Connection, Path]] = []

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        calls.append((connection, database_path))
        raise AssertionError("backup must not be called for a new database")

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    _database(tmp_path).migrate()
    assert calls == []


def test_noop_migration_does_not_backup_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    database = _database(tmp_path)
    database.migrate()
    backup_calls: list[Path] = []
    monkeypatch.setattr(
        migrations,
        "_backup_existing_database",
        lambda connection, database_path: backup_calls.append(database_path),
    )
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    database.migrate()

    normalized = [statement.lower() for statement in traces]
    assert backup_calls == []
    assert not any("create table" in statement for statement in normalized)
    assert not any("insert into schema_migrations" in statement for statement in normalized)


def test_backup_failure_prevents_ddl_and_schema_row_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE should_not_exist (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    sentinel = "BACKUP_SECRET_SENTINEL"

    def fail_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        del connection, database_path
        raise sqlite3.OperationalError(sentinel)

    monkeypatch.setattr(migrations, "_backup_existing_database", fail_backup)
    with pytest.raises(MigrationError) as raised:
        database.migrate()
    _assert_sanitized(raised.value, sentinel)

    connection = _connection(_database_path(tmp_path))
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_not_exist'"
            ).fetchone()
            is None
        )
        assert _schema_migration_rows(_database_path(tmp_path)) == [
            (1, "0001_event_store.sql", hashlib.sha256(files["0001_event_store.sql"]).hexdigest())
        ]
    finally:
        connection.close()


def test_migration_error_does_not_leak_sqlite_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence.migrations import MigrationError

    sentinel = "MIGRATION_SQL_SECRET_SENTINEL"
    _migration_dir(
        monkeypatch,
        tmp_path,
        {"0001_broken.sql": f"CREATE TABLE broken (value {sentinel};\n".encode()},
    )

    with pytest.raises(MigrationError) as raised:
        _database(tmp_path).migrate()

    assert raised.value.code == "sql_error"
    _assert_sanitized(raised.value, sentinel)


def test_migrate_journal_mode_readback_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    database = _database(tmp_path)
    sentinel = "JOURNAL_MODE_SECRET_SENTINEL"
    reads = 0
    real_read = migrations._read_journal_mode

    def fail_after_journal_mode_set(connection: sqlite3.Connection) -> str:
        nonlocal reads
        reads += 1
        if reads == 2:
            raise migrations._BackupVerificationFailure(sentinel)
        return real_read(connection)

    monkeypatch.setattr(migrations, "_read_journal_mode", fail_after_journal_mode_set)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_failed"
    _assert_sanitized(raised.value, sentinel)
    connection = _connection(_database_path(tmp_path))
    try:
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name = 'events'").fetchone()
            is None
        )
    finally:
        connection.close()


def test_backup_reopen_verification_precedes_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    timeline: list[str] = []
    real_verify = migrations._verify_backup

    def recording_verify(
        migration_connection: sqlite3.Connection,
        backup_path: Path,
        *,
        expected_journal_mode: str,
        deadline_seconds: float = migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        real_verify(
            migration_connection,
            backup_path,
            expected_journal_mode=expected_journal_mode,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        timeline.append("verifier_complete")

    monkeypatch.setattr(migrations, "_verify_backup", recording_verify)
    real_promote = migrations._promote_backup_artifacts

    def recording_promote(partial_path: Path) -> Path:
        verified_path = real_promote(partial_path)
        timeline.append("artifact_promoted")
        return verified_path

    monkeypatch.setattr(migrations, "_promote_backup_artifacts", recording_promote)
    real_backup = migrations._backup_existing_database

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        backup_path = real_backup(connection, database_path)
        timeline.append("backup_verified")
        return backup_path

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)

        def record_statement(statement: str) -> None:
            normalized = statement.lower()
            traces.append(normalized)
            if "create table pending_table" in normalized:
                timeline.append("ddl")
            elif "insert into schema_migrations" in normalized:
                timeline.append("schema_row_insert")
            elif normalized == "commit":
                timeline.append("commit")

        connection.set_trace_callback(record_statement)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    database.migrate()

    ddl_index = next(
        index for index, statement in enumerate(traces) if "create table pending_table" in statement
    )
    assert ddl_index >= 0
    assert timeline.index("verifier_complete") < timeline.index("artifact_promoted")
    assert timeline.index("artifact_promoted") < timeline.index("backup_verified")
    assert timeline.index("backup_verified") < timeline.index("ddl")
    assert timeline.index("ddl") < timeline.index("schema_row_insert")
    assert timeline.index("schema_row_insert") < timeline.index("commit")


def test_migrations_runner_is_private_and_has_the_planned_signature() -> None:
    from neontof.persistence import migrations

    assert not hasattr(migrations, "run_migrations")
    assert hasattr(migrations, "_run_migrations")
    assert list(inspect.signature(migrations._run_migrations).parameters) == [
        "connection",
        "database_path",
    ]


def test_migration_error_codes_are_independent_for_applied_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    database = _database(tmp_path)
    database.migrate()
    path = _database_path(tmp_path)
    pending = _base_migration_files()
    pending["0002_pending.sql"] = b"CREATE TABLE should_not_exist (value TEXT);\n"
    pending["0003_later.sql"] = b"CREATE TABLE should_not_exist_later (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, pending)

    cases = (
        (
            "version_name_drift",
            [(1, "wrong.sql", hashlib.sha256(pending["0001_event_store.sql"]).hexdigest())],
        ),
        ("checksum_drift", [(1, "0001_event_store.sql", "0" * 64)]),
    )

    for expected_code, rows in cases:
        monkeypatch.setattr(
            migrations, "_read_applied_migrations", lambda connection, rows=rows: rows
        )
        with pytest.raises(MigrationError) as raised:
            database.migrate()
        assert raised.value.code == expected_code
        connection = _connection(path)
        try:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'should_not_exist'"
                ).fetchone()
                is None
            )
        finally:
            connection.close()


def test_backup_helper_uses_dedicated_source_and_exact_connection_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    path = _migrate(tmp_path)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real_connect = sqlite3.connect

    def recording_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        calls.append((args, kwargs))
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    database_connection = real_connect(
        path, timeout=5.0, isolation_level=None, check_same_thread=True
    )
    try:
        backup_path = migrations._backup_existing_database(database_connection, path)
    finally:
        database_connection.close()

    assert backup_path.name.startswith(f"{path.name}.migration-")
    assert backup_path.name.endswith(".verified.sqlite3")
    assert all(
        kwargs
        == {
            "timeout": 5.0,
            "isolation_level": None,
            "check_same_thread": True,
            "uri": False,
        }
        for _, kwargs in calls
    )
    assert len(calls) >= 2
    assert calls[0][0][0] != calls[1][0][0]
    assert backup_path.parent == path.resolve().parent / ".neontof-migration-backups"


def test_backup_connections_set_query_only_without_setting_journal_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    path = _migrate(tmp_path)
    traces: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, sqlite3.Connection)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    connection = real_connect(path, timeout=5.0, isolation_level=None, check_same_thread=True)
    try:
        backup_path = migrations._backup_existing_database(connection, path)
    finally:
        connection.close()

    assert backup_path.is_file()
    normalized = [statement.lower().replace(" ", "") for statement in traces]
    assert any(statement == "pragmaquery_only=on" for statement in normalized)
    assert not any("pragmajournal_mode=" in statement for statement in normalized)


def test_backup_connection_readback_failure_is_sanitized_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    sentinel = "BACKUP_OPEN_SECRET_SENTINEL"

    class FakeCursor:
        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConnection:
        closed = False

        def execute(self, statement: str) -> FakeCursor:
            del statement
            return FakeCursor()

        def close(self) -> None:
            self.closed = True
            raise sqlite3.OperationalError(sentinel)

    fake = FakeConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: fake)

    with pytest.raises(MigrationError) as raised:
        migrations._open_backup_connection(tmp_path / "backup.sqlite3", query_only=True)

    assert raised.value.code == "backup_failed"
    assert fake.closed
    _assert_sanitized(raised.value, sentinel)


def test_backup_source_query_only_rejects_write(tmp_path: Path) -> None:
    from neontof.persistence import migrations

    path = _migrate(tmp_path)
    source = migrations._open_backup_connection(path, query_only=True)
    try:
        assert source.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            source.execute("CREATE TABLE source_write_sabotage (value TEXT)")
    finally:
        source.close()


@pytest.mark.parametrize("failing_connection", [0, 1])
def test_backup_source_or_destination_close_failure_is_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_connection: int,
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    path = _migrate(tmp_path)
    migration_connection = _connection(path)
    sentinel = "BACKUP_CLOSE_SECRET_SENTINEL"
    created = 0

    class FailingCloseConnection(sqlite3.Connection):
        fail_on_close = False

        def close(self) -> None:
            if self.fail_on_close:
                self.fail_on_close = False
                raise sqlite3.OperationalError(sentinel)
            super().close()

    real_connect = sqlite3.connect

    def recording_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal created
        kwargs["factory"] = FailingCloseConnection
        connected = real_connect(*args, **kwargs)
        assert isinstance(connected, FailingCloseConnection)
        connected.fail_on_close = created == failing_connection
        created += 1
        return connected

    monkeypatch.setattr(sqlite3, "connect", recording_connect)
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._backup_existing_database(migration_connection, path)
    finally:
        migration_connection.close()

    assert raised.value.code == "backup_failed"
    _assert_sanitized(raised.value, sentinel)


def test_backup_reopen_close_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    path = _migrate(tmp_path)
    migration_connection = _connection(path)
    backup_path = migrations._backup_existing_database(migration_connection, path)
    expected_journal_mode = migration_connection.execute("PRAGMA journal_mode").fetchone()[0]
    sentinel = "REOPEN_CLOSE_SECRET_SENTINEL"

    class FailingCloseConnection(sqlite3.Connection):
        def close(self) -> None:
            raise sqlite3.OperationalError(sentinel)

    real_connect = sqlite3.connect

    def failing_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        kwargs["factory"] = FailingCloseConnection
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, FailingCloseConnection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", failing_connect)
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._verify_backup(
                migration_connection,
                backup_path,
                expected_journal_mode=expected_journal_mode,
            )
    finally:
        migration_connection.close()

    assert raised.value.code == "backup_failed"
    _assert_sanitized(raised.value, sentinel)


def test_backup_cleanup_deletion_failure_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    sentinel = "BACKUP_CLEANUP_SECRET_SENTINEL"

    def fail_after_copy(
        source: sqlite3.Connection,
        destination: sqlite3.Connection,
        *,
        deadline_seconds: float = migrations._BACKUP_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        del source, destination, deadline_seconds, monotonic
        raise migrations._BackupProgressFailure(sentinel)

    monkeypatch.setattr(migrations, "_copy_database_with_deadline", fail_after_copy)
    real_unlink = Path.unlink

    def fail_backup_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if ".neontof-migration-backups" in path.parts:
            raise OSError(sentinel)
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_backup_unlink)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_cleanup_failed"
    _assert_sanitized(raised.value, sentinel)


def test_backup_copy_accepts_sqlite_ok_until_done_and_uses_fixed_arguments() -> None:
    from neontof.persistence import migrations

    calls: list[tuple[Any, ...]] = []

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            calls.append(
                (
                    destination,
                    {
                        "pages": pages,
                        "sleep": sleep,
                        "name": name,
                        "progress": progress,
                    },
                )
            )
            progress(sqlite3.SQLITE_OK, 3, 4)
            progress(sqlite3.SQLITE_DONE, 0, 4)

    destination = _memory_connection()
    try:
        migrations._copy_database_with_deadline(FakeSource(), destination)
    finally:
        destination.close()

    assert calls == [
        (
            calls[0][0],
            {
                "pages": 256,
                "sleep": 0.05,
                "name": "main",
                "progress": calls[0][1]["progress"],
            },
        )
    ]


def test_backup_copy_deadline_applies_while_sqlite_ok_progresses() -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    times = iter((0.0, 0.0, 10.01))

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            del destination, pages, sleep, name
            progress(sqlite3.SQLITE_OK, 3, 4)
            progress(sqlite3.SQLITE_OK, 2, 4)

    destination = _memory_connection()
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._copy_database_with_deadline(
                FakeSource(),
                destination,
                deadline_seconds=10.0,
                monotonic=lambda: next(times),
            )
    finally:
        destination.close()

    assert raised.value.code == "backup_failed"


@pytest.mark.parametrize(
    "status",
    [sqlite3.SQLITE_OK, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_DONE],
)
def test_backup_copy_rejects_any_progress_callback_after_done(status: int) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            del destination, pages, sleep, name
            progress(sqlite3.SQLITE_DONE, 0, 4)
            if status == sqlite3.SQLITE_DONE:
                progress(status, 0, 4)
            else:
                progress(status, 2, 4)

    destination = _memory_connection()
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._copy_database_with_deadline(FakeSource(), destination)
    finally:
        destination.close()

    assert raised.value.code == "backup_failed"


@pytest.mark.parametrize(
    ("status", "remaining", "total"),
    [
        (sqlite3.SQLITE_OK, 4, 4),
        (sqlite3.SQLITE_OK, -1, 4),
        (sqlite3.SQLITE_OK, 5, 4),
        (sqlite3.SQLITE_OK, 0, 0),
        (999, 1, 4),
    ],
)
def test_backup_copy_rejects_invalid_progress(status: int, remaining: int, total: int) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            del destination, pages, sleep, name
            progress(status, remaining, total)

    destination = _memory_connection()
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._copy_database_with_deadline(FakeSource(), destination)
    finally:
        destination.close()

    assert raised.value.code == "backup_failed"


def test_backup_copy_rejects_return_without_done() -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            del destination, pages, sleep, name
            progress(sqlite3.SQLITE_OK, 1, 2)

    destination = _memory_connection()
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._copy_database_with_deadline(FakeSource(), destination)
    finally:
        destination.close()

    assert raised.value.code == "backup_failed"


@pytest.mark.parametrize("status", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED])
def test_backup_copy_bounds_busy_and_locked_retries(status: int) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    callbacks = 0

    class FakeSource:
        def backup(
            self,
            destination: sqlite3.Connection,
            *,
            pages: int,
            sleep: float,
            name: str,
            progress: Callable[[int, int, int], None],
        ) -> None:
            nonlocal callbacks
            del destination, pages, sleep, name
            while callbacks <= migrations._BACKUP_MAX_BUSY_OR_LOCKED_RETRIES:
                callbacks += 1
                progress(status, 1, 2)

    destination = _memory_connection()
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._copy_database_with_deadline(FakeSource(), destination)
    finally:
        destination.close()

    assert raised.value.code == "backup_failed"
    assert callbacks == migrations._BACKUP_MAX_BUSY_OR_LOCKED_RETRIES + 1


def test_backup_verifier_rejects_actual_data_mismatch_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "campaign:alpha",
                1,
                "event:raw",
                "CampaignCreated",
                1,
                None,
                None,
                None,
                "2026-08-25T00:00:00Z",
                "in_world",
                "player_visible",
                sqlite3.Binary(
                    b'{"type":"CampaignCreated","event_id":"event:raw",'
                    b'"event_version":1,"campaign_id":"campaign:alpha",'
                    b'"session_id":null,"scene_id":null,"turn_id":null,'
                    b'"sequence":1,"occurred_at":"2026-08-25T00:00:00Z",'
                    b'"origin":"in_world","visibility":"player_visible",'
                    b'"payload":{"name":"NeontoF"}}'
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    real_verify = migrations._verify_backup

    def sabotage_then_verify(
        migration_connection: sqlite3.Connection,
        backup_path: Path,
        *,
        expected_journal_mode: str,
        deadline_seconds: float = migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        del migration_connection
        sabotage = sqlite3.connect(backup_path)
        try:
            sabotage.execute("UPDATE events SET type = 'SessionStarted'")
            sabotage.commit()
        finally:
            sabotage.close()
        comparison = _connection(path)
        try:
            real_verify(
                comparison,
                backup_path,
                expected_journal_mode=expected_journal_mode,
                deadline_seconds=deadline_seconds,
                monotonic=monotonic,
            )
        finally:
            comparison.close()

    monkeypatch.setattr(migrations, "_verify_backup", sabotage_then_verify)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_failed"
    verification = _connection(path)
    try:
        assert (
            verification.execute(
                "SELECT name FROM sqlite_master WHERE name = 'pending_table'"
            ).fetchone()
            is None
        )
    finally:
        verification.close()


def test_backup_verifier_rejects_actual_schema_mismatch_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)

    real_copy = migrations._copy_database_with_deadline

    def copy_then_corrupt_schema(
        source: sqlite3.Connection,
        destination: sqlite3.Connection,
        *,
        deadline_seconds: float = migrations._BACKUP_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        real_copy(
            source,
            destination,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        destination.execute("CREATE TABLE actual_schema_sabotage (value TEXT)")

    monkeypatch.setattr(migrations, "_copy_database_with_deadline", copy_then_corrupt_schema)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_failed"
    connection = _connection(_database_path(tmp_path))
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('pending_table', 'actual_schema_sabotage')"
            ).fetchall()
            == []
        )
    finally:
        connection.close()


def test_backup_verification_deadline_stops_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    real_verify = migrations._verify_backup

    def verify_with_expired_deadline(
        migration_connection: sqlite3.Connection,
        backup_path: Path,
        *,
        expected_journal_mode: str,
        deadline_seconds: float = migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        del monotonic
        times = iter((0.0, 0.0, 10.0))
        real_verify(
            migration_connection,
            backup_path,
            expected_journal_mode=expected_journal_mode,
            deadline_seconds=deadline_seconds,
            monotonic=lambda: next(times),
        )

    monkeypatch.setattr(migrations, "_verify_backup", verify_with_expired_deadline)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_failed"
    connection = _connection(_database_path(tmp_path))
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'pending_table'"
            ).fetchone()
            is None
        )
    finally:
        connection.close()


def test_backup_verifier_sanitizes_artifact_recheck_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    path = _migrate(tmp_path)
    migration_connection = _connection(path)
    backup_path = migrations._backup_existing_database(migration_connection, path)
    expected_journal_mode = migration_connection.execute("PRAGMA journal_mode").fetchone()[0]
    sentinel = "ARTIFACT_RECHECK_SECRET_SENTINEL"

    def fail_artifact_recheck(candidate: Path) -> tuple[Path, ...]:
        del candidate
        raise migrations._BackupVerificationFailure(sentinel)

    monkeypatch.setattr(migrations, "_existing_artifact_paths", fail_artifact_recheck)
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._verify_backup(
                migration_connection,
                backup_path,
                expected_journal_mode=expected_journal_mode,
            )
    finally:
        migration_connection.close()

    assert raised.value.code == "backup_failed"
    _assert_sanitized(raised.value, sentinel)


def test_backup_rejects_different_basename_sidecar_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)

    real_copy = migrations._copy_database_with_deadline
    wrong_sidecar: Path | None = None

    def copy_with_wrong_sidecar(
        source: sqlite3.Connection,
        destination: sqlite3.Connection,
        *,
        deadline_seconds: float = migrations._BACKUP_DEADLINE_SECONDS,
        monotonic: Any = time.monotonic,
    ) -> None:
        nonlocal wrong_sidecar
        real_copy(
            source,
            destination,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        database_row = destination.execute("PRAGMA database_list").fetchone()
        assert database_row is not None
        partial_path = Path(database_row[2])
        wrong_sidecar = partial_path.with_name(
            partial_path.name.replace(migrations._BACKUP_PARTIAL_MARKER, "-other.sqlite3") + "-wal"
        )
        wrong_sidecar.write_bytes(b"unexpected sidecar")

    monkeypatch.setattr(migrations, "_copy_database_with_deadline", copy_with_wrong_sidecar)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "backup_failed"
    assert wrong_sidecar is not None
    wrong_sidecar.unlink()
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'pending_table'"
            ).fetchone()
            is None
        )
    finally:
        connection.close()


def test_verified_artifact_is_retained_after_commit_and_later_ddl_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = (
        b"CREATE TABLE pending_table (value TEXT);\nCREATE TABLE events (value TEXT);\n"
    )
    _migration_dir(monkeypatch, tmp_path, files)

    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "sql_error"
    root = _database_path(tmp_path).resolve().parent / ".neontof-migration-backups"
    assert list(root.glob(f"{_database_path(tmp_path).name}.migration-*.verified.sqlite3"))
    assert not list(root.glob(f"{_database_path(tmp_path).name}.migration-*.partial.sqlite3"))


def test_verified_backup_artifact_restores_schema_and_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    path = _database_path(tmp_path)
    connection = _connection(path)
    try:
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "campaign:alpha",
                1,
                "event:restore",
                "CampaignCreated",
                1,
                None,
                None,
                None,
                "2026-08-25T00:00:00Z",
                "in_world",
                "player_visible",
                sqlite3.Binary(
                    b'{"type":"CampaignCreated","event_id":"event:restore",'
                    b'"event_version":1,"campaign_id":"campaign:alpha",'
                    b'"session_id":null,"scene_id":null,"turn_id":null,'
                    b'"sequence":1,"occurred_at":"2026-08-25T00:00:00Z",'
                    b'"origin":"in_world","visibility":"player_visible",'
                    b'"payload":{"name":"NeontoF"}}'
                ),
            ),
        )
        connection.commit()
        before = migrations._database_snapshot(
            connection,
            start=time.monotonic(),
            deadline_seconds=migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
            monotonic=time.monotonic,
        )
    finally:
        connection.close()

    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    verified_paths: list[Path] = []
    real_backup = migrations._backup_existing_database

    def recording_backup(connection: sqlite3.Connection, database_path: Path) -> Path:
        verified_path = real_backup(connection, database_path)
        verified_paths.append(verified_path)
        return verified_path

    monkeypatch.setattr(migrations, "_backup_existing_database", recording_backup)
    database.migrate()

    assert len(verified_paths) == 1
    verified_path = verified_paths[0]
    restore_path = tmp_path / "restore" / "restored.sqlite3"
    restore_path.parent.mkdir()
    source = migrations._open_backup_connection(verified_path, query_only=True)
    destination = migrations._open_backup_connection(restore_path, query_only=False)
    try:
        migrations._copy_database_with_deadline(source, destination)
    finally:
        source.close()
        destination.close()

    restored = migrations._open_backup_connection(restore_path, query_only=True)
    try:
        after = migrations._database_snapshot(
            restored,
            start=time.monotonic(),
            deadline_seconds=migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
            monotonic=time.monotonic,
        )
    finally:
        restored.close()

    assert after == before


def test_test_only_restore_is_verified_with_bounded_verifier(tmp_path: Path) -> None:
    from neontof.persistence import migrations

    path = _migrate(tmp_path)
    migration_connection = _connection(path)
    verified_path = migrations._backup_existing_database(migration_connection, path)
    restore_path = tmp_path / "restore" / "bounded-restore.sqlite3"
    restore_path.parent.mkdir()
    source = migrations._open_backup_connection(verified_path, query_only=True)
    destination = migrations._open_backup_connection(restore_path, query_only=False)
    try:
        migrations._copy_database_with_deadline(source, destination)
    finally:
        source.close()
        destination.close()

    try:
        expected_journal_mode = migration_connection.execute("PRAGMA journal_mode").fetchone()[0]
        migrations._verify_backup(
            migration_connection,
            restore_path,
            expected_journal_mode=expected_journal_mode,
            deadline_seconds=migrations._BACKUP_VERIFY_DEADLINE_SECONDS,
            monotonic=time.monotonic,
        )
    finally:
        migration_connection.close()


def test_backup_identity_uses_os_samefile_and_rejects_different_file(tmp_path: Path) -> None:
    from neontof.persistence import migrations

    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    first_connection = sqlite3.connect(first)
    second_connection = sqlite3.connect(second)
    try:
        assert migrations._is_same_file_database(first_connection, first_connection, first)
        assert not migrations._is_same_file_database(first_connection, second_connection, first)
    finally:
        first_connection.close()
        second_connection.close()


def test_unverified_backup_cleanup_has_an_exact_artifact_set(tmp_path: Path) -> None:
    from neontof.persistence import migrations

    backup_path = tmp_path / "state.sqlite3"
    backup_path.write_bytes(b"partial")
    sidecar_wal = Path(f"{backup_path}-wal")
    sidecar_shm = Path(f"{backup_path}-shm")
    sidecar_wal.write_bytes(b"wal")
    sidecar_shm.write_bytes(b"shm")
    unrelated = tmp_path / "other.sqlite3"
    unrelated.write_bytes(b"keep")

    migrations._remove_unverified_backup(backup_path)

    assert not backup_path.exists()
    assert not sidecar_wal.exists()
    assert not sidecar_shm.exists()
    assert unrelated.is_file()


def test_promote_backup_artifacts_preserves_partial_marker_in_main_and_sidecars(
    tmp_path: Path,
) -> None:
    from neontof.persistence import migrations

    partial_path = tmp_path / "state.partial.sqlite3.migration-deadbeef.partial.sqlite3"
    partial_names = {
        partial_path.name,
        f"{partial_path.name}-wal",
        f"{partial_path.name}-shm",
    }
    verified_path = tmp_path / "state.partial.sqlite3.migration-deadbeef.verified.sqlite3"
    verified_names = {
        verified_path.name,
        f"{verified_path.name}-wal",
        f"{verified_path.name}-shm",
    }
    for path in (
        partial_path,
        Path(f"{partial_path}-wal"),
        Path(f"{partial_path}-shm"),
    ):
        path.write_bytes(b"partial artifact")

    promoted = migrations._promote_backup_artifacts(partial_path)

    assert promoted == verified_path
    assert {path.name for path in tmp_path.iterdir()} == verified_names
    assert all((tmp_path / name).is_file() for name in verified_names)
    assert not any((tmp_path / name).exists() for name in partial_names)


def test_unverified_backup_cleanup_preserves_partial_marker_in_all_artifacts(
    tmp_path: Path,
) -> None:
    from neontof.persistence import migrations

    partial_path = tmp_path / "state.partial.sqlite3.migration-deadbeef.partial.sqlite3"
    verified_path = tmp_path / "state.partial.sqlite3.migration-deadbeef.verified.sqlite3"
    artifact_paths = (
        partial_path,
        Path(f"{partial_path}-wal"),
        Path(f"{partial_path}-shm"),
        verified_path,
        Path(f"{verified_path}-wal"),
        Path(f"{verified_path}-shm"),
    )
    for path in artifact_paths:
        path.write_bytes(b"backup artifact")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_bytes(b"keep")

    migrations._remove_unverified_backup(partial_path)

    assert all(not path.exists() for path in artifact_paths)
    assert list(tmp_path.iterdir()) == [unrelated]


def test_migration_preserves_partial_marker_in_database_basename_during_backup_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence.sqlite_database import SqliteDatabase

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database_path = tmp_path / "runtime" / "state.partial.sqlite3"
    assert not database_path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    database = SqliteDatabase(database_path)
    database.migrate()

    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    database.migrate()

    connection = _connection(database_path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'pending_table'"
            ).fetchone()
            is not None
        )
        rows = connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (1, "0001_event_store.sql", hashlib.sha256(files["0001_event_store.sql"]).hexdigest()),
        (2, "0002_pending.sql", hashlib.sha256(files["0002_pending.sql"]).hexdigest()),
    ]
    backup_root = database_path.parent / ".neontof-migration-backups"
    verified_paths = sorted(backup_root.glob(f"{database_path.name}.migration-*.verified.sqlite3"))
    assert len(verified_paths) == 1
    verified_path = verified_paths[0]
    assert verified_path.name.startswith(f"{database_path.name}.migration-")
    assert verified_path.name.endswith(".verified.sqlite3")
    artifact_names = {path.name for path in backup_root.iterdir()}
    assert artifact_names <= {
        verified_path.name,
        f"{verified_path.name}-wal",
        f"{verified_path.name}-shm",
    }
    assert verified_path.name in artifact_names
    assert not list(backup_root.glob(f"{database_path.name}.migration-*.partial.sqlite3"))


def test_filesystem_database_requires_regular_file_before_backup(tmp_path: Path) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    directory = tmp_path / "database-directory"
    directory.mkdir()
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(MigrationError) as raised:
            migrations._backup_existing_database(connection, directory)
    finally:
        connection.close()

    assert raised.value.code == "unsupported_database"


def test_migrate_rejects_directory_database_before_opening_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import sqlite_database
    from neontof.persistence.migrations import MigrationError

    directory = tmp_path / "database-directory"
    directory.mkdir()

    def fail_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        del args, kwargs
        raise AssertionError("unsupported database must be rejected before connect")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    with pytest.raises(MigrationError) as raised:
        sqlite_database.SqliteDatabase(directory).migrate()

    assert raised.value.code == "unsupported_database"


def test_migrate_rejects_regular_file_parent_without_modifying_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import sqlite_database
    from neontof.persistence.migrations import MigrationError

    parent_file = tmp_path / "parent-file"
    original = b"parent file must remain unchanged"
    parent_file.write_bytes(original)
    target = parent_file / "state.sqlite3"

    def fail_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        del args, kwargs
        raise AssertionError("invalid parent must be rejected before connect")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    with pytest.raises(MigrationError) as raised:
        sqlite_database.SqliteDatabase(target).migrate()

    assert raised.value.code == "unsupported_database"
    assert parent_file.read_bytes() == original
    assert not target.exists()


def test_migrate_accepts_relative_database_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence.sqlite_database import SqliteDatabase

    monkeypatch.chdir(tmp_path)
    relative = Path("relative") / "state.sqlite3"

    SqliteDatabase(relative).migrate()

    assert (tmp_path / relative).is_file()


def test_migrate_accepts_hard_link_alias(tmp_path: Path) -> None:
    from neontof.persistence.sqlite_database import SqliteDatabase

    canonical = tmp_path / "state.sqlite3"
    SqliteDatabase(canonical).migrate()
    alias = tmp_path / "state-alias.sqlite3"
    try:
        os.link(canonical, alias)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"hard links unavailable: {error}")

    SqliteDatabase(alias).migrate()

    assert alias.is_file()
    assert os.path.samefile(canonical, alias)


@pytest.mark.parametrize(
    "raw_path",
    [":memory:", "file:memory?mode=memory&cache=shared", "file::memory:?cache=shared"],
)
def test_migrate_rejects_uri_and_in_memory_paths_before_open(
    tmp_path: Path, raw_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import sqlite_database
    from neontof.persistence.migrations import MigrationError

    def fail_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        del args, kwargs
        raise AssertionError("URI and in-memory paths must be rejected before connect")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    with pytest.raises(MigrationError) as raised:
        sqlite_database.SqliteDatabase(Path(raw_path)).migrate()

    assert raised.value.code == "unsupported_database"


def test_migrate_rejects_special_file_before_open(tmp_path: Path) -> None:
    mkfifo = getattr(os, "mkfifo", None)
    if not callable(mkfifo):
        pytest.skip("special file creation is unavailable")
    special = tmp_path / "state.sqlite3"
    try:
        mkfifo(str(special))
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"special file creation unavailable: {error}")

    from neontof.persistence import sqlite_database
    from neontof.persistence.migrations import MigrationError

    with pytest.raises(MigrationError) as raised:
        sqlite_database.SqliteDatabase(special).migrate()

    assert raised.value.code == "unsupported_database"


def test_backup_rejects_real_three_way_identity_mismatch_before_ddl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neontof.persistence import migrations
    from neontof.persistence.migrations import MigrationError

    files = _base_migration_files()
    _migration_dir(monkeypatch, tmp_path, files)
    database = _database(tmp_path)
    database.migrate()
    files["0002_pending.sql"] = b"CREATE TABLE pending_table (value TEXT);\n"
    _migration_dir(monkeypatch, tmp_path, files)
    path = _database_path(tmp_path)
    other_path = tmp_path / "other.sqlite3"
    other = _connection(other_path)
    other.close()

    real_open = migrations._open_backup_connection
    opened = 0

    def open_wrong_source(path: Path, *, query_only: bool) -> sqlite3.Connection:
        nonlocal opened
        opened += 1
        source_path = other_path if opened == 1 else path
        return real_open(source_path, query_only=query_only)

    monkeypatch.setattr(migrations, "_open_backup_connection", open_wrong_source)
    with pytest.raises(MigrationError) as raised:
        database.migrate()

    assert raised.value.code == "database_identity_mismatch"
    connection = _connection(path)
    try:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'pending_table'"
            ).fetchone()
            is None
        )
    finally:
        connection.close()
