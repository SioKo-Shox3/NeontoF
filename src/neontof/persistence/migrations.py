"""Additive SQLite migration discovery, validation, backup, and application."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

type MigrationIssueCode = Literal[
    "version_name_drift",
    "checksum_drift",
    "gap",
    "duplicate",
    "unknown_applied_version",
    "unsupported_database",
    "database_identity_mismatch",
    "backup_cleanup_failed",
    "backup_failed",
    "sql_error",
]

MIGRATIONS_DIRECTORY = Path(__file__).with_name("migrations")
_MIGRATION_NAME_PATTERN = re.compile(r"^(?P<version>[0-9]{4})_[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")

_BACKUP_DEADLINE_SECONDS: Final[float] = 10.0
_BACKUP_VERIFY_DEADLINE_SECONDS: Final[float] = _BACKUP_DEADLINE_SECONDS
_BACKUP_PAGES_PER_STEP: Final[int] = 256
_BACKUP_RETRY_SLEEP_SECONDS: Final[float] = 0.05
_BACKUP_MAX_BUSY_OR_LOCKED_RETRIES: Final[int] = 200
_BACKUP_BUSY_TIMEOUT_MILLISECONDS: Final[int] = 5000
_BACKUP_ROOT_NAME: Final[str] = ".neontof-migration-backups"
_BACKUP_PARTIAL_MARKER: Final[str] = ".partial.sqlite3"
_BACKUP_VERIFIED_MARKER: Final[str] = ".verified.sqlite3"
_BACKUP_VERIFY_BATCH_SIZE: Final[int] = 256


class MigrationError(Exception):
    """Sanitized migration failure with a fixed issue code."""

    __slots__ = ("code",)
    code: MigrationIssueCode

    def __init__(self, code: MigrationIssueCode) -> None:
        self.code = code
        Exception.__init__(self, "migration failed")


@dataclass(frozen=True)
class _MigrationSpec:
    version: int
    name: str
    raw_sql: bytes
    checksum: str
    sql: str


@dataclass(frozen=True)
class _TableSnapshot:
    name: str
    table_info: tuple[tuple[object, ...], ...]
    index_list: tuple[tuple[object, ...], ...]
    index_xinfo: tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]
    rows: tuple[tuple[object, ...], ...]
    event_json_types: tuple[object, ...]


@dataclass(frozen=True)
class _DatabaseSnapshot:
    schema_objects: tuple[tuple[object, ...], ...]
    tables: tuple[_TableSnapshot, ...]


class _BackupProgressFailure(Exception):
    pass


class _BackupVerificationFailure(Exception):
    pass


class _BackupSource(Protocol):
    def backup(
        self,
        target: sqlite3.Connection,
        *,
        pages: int,
        sleep: float,
        name: str,
        progress: Callable[[int, int, int], None],
    ) -> None: ...


def _new_error(code: MigrationIssueCode) -> MigrationError:
    return MigrationError(code)


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except OSError, RuntimeError, TypeError, ValueError, sqlite3.Error:
        return


def _discover_migrations() -> tuple[_MigrationSpec, ...]:
    specs: list[_MigrationSpec] = []
    failure_code: MigrationIssueCode | None = None
    try:
        paths = sorted(MIGRATIONS_DIRECTORY.glob("*.sql"), key=lambda item: item.name)
        for path in paths:
            match = _MIGRATION_NAME_PATTERN.fullmatch(path.name)
            if match is None:
                raise _new_error("sql_error")
            raw_sql = path.read_bytes()
            sql = raw_sql.decode("utf-8", errors="strict")
            specs.append(
                _MigrationSpec(
                    version=int(match.group("version")),
                    name=path.name,
                    raw_sql=raw_sql,
                    checksum=hashlib.sha256(raw_sql).hexdigest(),
                    sql=sql,
                )
            )
    except MigrationError as error:
        failure_code = error.code
    except OSError, UnicodeError, ValueError:
        failure_code = "sql_error"

    if failure_code is not None:
        raise _new_error(failure_code) from None

    if not specs:
        raise _new_error("sql_error")
    versions = [spec.version for spec in specs]
    if len(versions) != len(set(versions)):
        raise _new_error("duplicate")
    if versions != list(range(1, len(versions) + 1)):
        raise _new_error("gap")
    return tuple(specs)


def _read_applied_migrations(connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rows = connection.execute(
        "SELECT version, name, checksum_sha256 FROM schema_migrations"
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def _normalized_sql(sql: str) -> str:
    return re.sub(r"\s+", "", sql.upper())


def _validate_schema_migrations_shape(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
    expected_columns = (
        ("version", "INTEGER", 0, None, 1),
        ("name", "TEXT", 1, None, 0),
        ("checksum_sha256", "TEXT", 1, None, 0),
    )
    actual_columns = tuple((row[1], row[2], row[3], row[4], row[5]) for row in columns)
    if actual_columns != expected_columns:
        raise _new_error("sql_error")

    indexes = connection.execute("PRAGMA index_list(schema_migrations)").fetchall()
    if len(indexes) != 1:
        raise _new_error("sql_error")
    index = indexes[0]
    if index[2] != 1 or index[3] != "u" or index[4] != 0:
        raise _new_error("sql_error")
    index_name = index[1]
    if type(index_name) is not str:
        raise _new_error("sql_error")
    index_columns = connection.execute(
        f"PRAGMA index_xinfo({_quote_identifier(index_name)})"
    ).fetchall()
    key_columns = [row[2] for row in index_columns if row[5] == 1]
    if key_columns != ["name"]:
        raise _new_error("sql_error")

    sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if sql_row is None or type(sql_row[0]) is not str:
        raise _new_error("sql_error")
    expected_sql = _normalized_sql(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL UNIQUE,
            checksum_sha256 TEXT NOT NULL CHECK (
                length(checksum_sha256) = 64
                AND checksum_sha256 = lower(checksum_sha256)
                AND checksum_sha256 NOT GLOB '*[^0-9a-f]*'
            )
        )
        """
    )
    if _normalized_sql(sql_row[0]) != expected_sql:
        raise _new_error("sql_error")


def _validate_applied_migrations(
    specs: tuple[_MigrationSpec, ...], applied: list[tuple[int, str, str]]
) -> tuple[_MigrationSpec, ...]:
    by_version = {spec.version: spec for spec in specs}
    applied_versions: list[int] = []
    for row in applied:
        if len(row) != 3:
            raise _new_error("sql_error")
        version, name, checksum = row
        if type(version) is not int or type(name) is not str or type(checksum) is not str:
            raise _new_error("sql_error")
        if version not in by_version:
            raise _new_error("unknown_applied_version")
        applied_versions.append(version)
        expected = by_version[version]
        if name != expected.name:
            raise _new_error("version_name_drift")
        if checksum != expected.checksum:
            raise _new_error("checksum_drift")

    applied_set = set(applied_versions)
    if applied_set != set(range(1, len(applied_set) + 1)):
        raise _new_error("gap")
    return tuple(
        sorted(
            (spec for spec in specs if spec.version not in applied_set),
            key=lambda spec: spec.version,
        )
    )


def _schema_migrations_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def _has_existing_schema_or_data(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type IN ('table', 'index', 'view', 'trigger') "
        "AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone()
    return row is not None


def _split_sql_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise _new_error("sql_error")
    return tuple(statements)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _is_regular_file(path: Path) -> bool:
    try:
        return path.exists() and stat.S_ISREG(path.stat().st_mode)
    except OSError, ValueError:
        return False


def _is_unsupported_requested_path(database_path: Path) -> bool:
    raw_path = str(database_path)
    lowered = raw_path.lower()
    return (
        lowered == ":memory:"
        or lowered.startswith("file:")
        or "mode=memory" in lowered
        or "cache=shared" in lowered
    )


def _canonical_database_path(database_path: Path, *, existing: bool) -> Path:
    if _is_unsupported_requested_path(database_path):
        raise _new_error("unsupported_database")
    resolve_failed = False
    canonical: Path | None = None
    try:
        canonical = database_path.resolve(strict=existing)
    except OSError, RuntimeError, ValueError:
        resolve_failed = True
    if resolve_failed or canonical is None:
        raise _new_error("unsupported_database") from None
    if existing:
        if not _is_regular_file(canonical):
            raise _new_error("unsupported_database")
    else:
        if not canonical.parent.is_dir():
            parent = canonical.parent
            while True:
                if parent.exists() or parent.is_symlink():
                    if not parent.is_dir():
                        raise _new_error("unsupported_database")
                    break
                next_parent = parent.parent
                if next_parent == parent:
                    raise _new_error("unsupported_database")
                parent = next_parent
        if canonical.exists() and not _is_regular_file(canonical):
            raise _new_error("unsupported_database")
    return canonical


def _connection_main_file(connection: sqlite3.Connection) -> Path:
    rows = connection.execute("PRAGMA database_list").fetchall()
    main_file: object | None = None
    for row in rows:
        if len(row) >= 3 and row[1] == "main":
            main_file = row[2]
            break
    if type(main_file) is not str or not main_file:
        raise _new_error("unsupported_database")
    resolve_failed = False
    canonical: Path | None = None
    try:
        canonical = Path(main_file).resolve(strict=True)
    except OSError, RuntimeError, ValueError:
        resolve_failed = True
    if resolve_failed or canonical is None:
        raise _new_error("unsupported_database") from None
    if not _is_regular_file(canonical):
        raise _new_error("unsupported_database")
    return canonical


def _validate_migration_database_identity(
    connection: sqlite3.Connection, database_path: Path
) -> Path:
    canonical = _canonical_database_path(database_path, existing=True)
    main_file = _connection_main_file(connection)
    same_file = False
    try:
        same_file = os.path.samefile(canonical, main_file)
    except OSError, ValueError:
        same_file = False
    if not same_file:
        raise _new_error("database_identity_mismatch")
    return canonical


def _is_same_file_database(
    migration_connection: sqlite3.Connection,
    backup_source: sqlite3.Connection,
    database_path: Path,
) -> bool:
    try:
        canonical = _canonical_database_path(database_path, existing=True)
        migration_file = _connection_main_file(migration_connection)
        source_file = _connection_main_file(backup_source)
        return (
            os.path.samefile(canonical, migration_file)
            and os.path.samefile(canonical, source_file)
            and os.path.samefile(migration_file, source_file)
        )
    except MigrationError, OSError, ValueError, sqlite3.DatabaseError:
        return False


def _read_journal_mode(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA journal_mode").fetchone()
    if row is None or type(row[0]) is not str or not row[0]:
        raise _BackupVerificationFailure
    return row[0].lower()


def _open_backup_connection(path: Path, *, query_only: bool) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    failure_code: MigrationIssueCode | None = None
    try:
        connection = sqlite3.connect(
            path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=True,
            uri=False,
        )
        connection.execute(f"PRAGMA busy_timeout={_BACKUP_BUSY_TIMEOUT_MILLISECONDS}")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA query_only=ON" if query_only else "PRAGMA query_only=0")
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        actual_query_only = connection.execute("PRAGMA query_only").fetchone()
        if (
            busy_timeout is None
            or busy_timeout[0] != _BACKUP_BUSY_TIMEOUT_MILLISECONDS
            or synchronous is None
            or synchronous[0] != 2
            or actual_query_only is None
            or actual_query_only[0] != (1 if query_only else 0)
        ):
            raise _BackupVerificationFailure
    except MigrationError as error:
        failure_code = error.code
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        failure_code = "backup_failed"
    if failure_code is not None:
        if connection is not None:
            try:
                connection.close()
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                sqlite3.Error,
                _BackupVerificationFailure,
                _BackupProgressFailure,
            ):
                connection = None
        raise _new_error(failure_code) from None
    if connection is None:
        raise _new_error("backup_failed") from None
    return connection


def _check_deadline(start: float, deadline_seconds: float, monotonic: Callable[[], float]) -> None:
    if monotonic() - start >= deadline_seconds:
        raise _BackupProgressFailure


def _copy_database_with_deadline(
    source: _BackupSource,
    destination: sqlite3.Connection,
    *,
    deadline_seconds: float = _BACKUP_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    start = 0.0
    progress_seen = False
    completed = False
    done_seen = False
    busy_or_locked_retries = 0

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal busy_or_locked_retries, completed, done_seen, progress_seen
        _check_deadline(start, deadline_seconds, monotonic)
        if done_seen:
            raise _BackupProgressFailure
        if type(status) is not int:
            raise _BackupProgressFailure
        if type(remaining) is not int or type(total) is not int:
            raise _BackupProgressFailure
        if remaining < 0 or total < 0 or remaining > total:
            raise _BackupProgressFailure
        progress_seen = True
        if status == sqlite3.SQLITE_DONE:
            if remaining != 0:
                raise _BackupProgressFailure
            done_seen = True
            completed = True
        elif status == sqlite3.SQLITE_OK:
            if total == 0 or remaining >= total:
                raise _BackupProgressFailure
        elif status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            busy_or_locked_retries += 1
            if busy_or_locked_retries > _BACKUP_MAX_BUSY_OR_LOCKED_RETRIES:
                raise _BackupProgressFailure
        elif status != sqlite3.SQLITE_OK:
            raise _BackupProgressFailure

    failure_code: MigrationIssueCode | None = None
    try:
        start = monotonic()
        source.backup(
            destination,
            pages=_BACKUP_PAGES_PER_STEP,
            sleep=_BACKUP_RETRY_SLEEP_SECONDS,
            name="main",
            progress=progress,
        )
        _check_deadline(start, deadline_seconds, monotonic)
    except MigrationError:
        failure_code = "backup_failed"
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        failure_code = "backup_failed"
    if failure_code is None and (not progress_seen or not completed):
        failure_code = "backup_failed"
    if failure_code is not None:
        raise _new_error(failure_code) from None


def _partial_or_verified_path(path: Path, marker: str) -> Path:
    for source_marker in (_BACKUP_PARTIAL_MARKER, _BACKUP_VERIFIED_MARKER):
        for sidecar_suffix in ("", "-wal", "-shm"):
            source_suffix = source_marker + sidecar_suffix
            if path.name.endswith(source_suffix):
                stem = path.name[: -len(source_suffix)]
                return path.with_name(stem + marker + sidecar_suffix)
    raise _BackupVerificationFailure


def _artifact_paths(main_path: Path) -> tuple[Path, Path, Path]:
    return (
        main_path,
        Path(f"{main_path}-wal"),
        Path(f"{main_path}-shm"),
    )


def _has_unexpected_artifact_sidecar(main_path: Path) -> bool:
    if main_path.name.endswith(_BACKUP_PARTIAL_MARKER):
        stem = main_path.name[: -len(_BACKUP_PARTIAL_MARKER)]
    elif main_path.name.endswith(_BACKUP_VERIFIED_MARKER):
        stem = main_path.name[: -len(_BACKUP_VERIFIED_MARKER)]
    else:
        return False
    expected_names = {
        path.name
        for marker in (_BACKUP_PARTIAL_MARKER, _BACKUP_VERIFIED_MARKER)
        for path in _artifact_paths(main_path.with_name(stem + marker))
    }
    unexpected = False
    try:
        entries = main_path.parent.iterdir()
        for entry in entries:
            if entry.name.startswith(stem) and entry.name not in expected_names:
                unexpected = True
    except OSError, ValueError:
        raise _BackupVerificationFailure
    return unexpected


def _existing_artifact_paths(main_path: Path) -> tuple[Path, ...]:
    if not _is_regular_file(main_path):
        raise _BackupVerificationFailure
    if _has_unexpected_artifact_sidecar(main_path):
        raise _BackupVerificationFailure
    paths: list[Path] = [main_path]
    for path in _artifact_paths(main_path)[1:]:
        if path.exists():
            if not _is_regular_file(path):
                raise _BackupVerificationFailure
            paths.append(path)
    return tuple(paths)


def _remove_unverified_backup(backup_path: Path) -> None:
    mains = [backup_path]
    if backup_path.name.endswith(_BACKUP_PARTIAL_MARKER):
        mains.append(_partial_or_verified_path(backup_path, _BACKUP_VERIFIED_MARKER))
    elif backup_path.name.endswith(_BACKUP_VERIFIED_MARKER):
        mains.append(_partial_or_verified_path(backup_path, _BACKUP_PARTIAL_MARKER))
    targets: list[Path] = []
    seen: set[Path] = set()
    for main in mains:
        for path in _artifact_paths(main):
            if path not in seen:
                seen.add(path)
                targets.append(path)
    cleanup_failed = False
    for path in targets:
        try:
            exists = path.exists()
        except OSError, ValueError:
            cleanup_failed = True
            continue
        if not exists:
            continue
        try:
            path.unlink()
        except OSError:
            cleanup_failed = True
    if cleanup_failed:
        raise _new_error("backup_cleanup_failed")


def _new_partial_backup_path(database_path: Path) -> Path:
    root = database_path.parent / _BACKUP_ROOT_NAME
    mkdir_failed = False
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        mkdir_failed = True
    if mkdir_failed:
        raise _new_error("backup_failed") from None
    for _ in range(16):
        token = secrets.token_hex(16).lower()
        candidate = root / f"{database_path.name}.migration-{token}{_BACKUP_PARTIAL_MARKER}"
        try:
            candidate_exists = any(path.exists() for path in _artifact_paths(candidate))
        except OSError, RuntimeError, ValueError:
            candidate_exists = True
        if not candidate_exists:
            return candidate
    raise _new_error("backup_failed")


def _promote_backup_artifacts(partial_path: Path) -> Path:
    failure_code: MigrationIssueCode | None = None
    verified_path: Path | None = None
    try:
        partial_paths = _existing_artifact_paths(partial_path)
        verified_path = _partial_or_verified_path(partial_path, _BACKUP_VERIFIED_MARKER)
        verified_candidates = _artifact_paths(verified_path)
        if any(path.exists() for path in verified_candidates):
            raise _BackupVerificationFailure
        for partial in partial_paths:
            partial.replace(_partial_or_verified_path(partial, _BACKUP_VERIFIED_MARKER))
        if not _is_regular_file(verified_path):
            raise _BackupVerificationFailure
    except MigrationError:
        failure_code = "backup_failed"
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        failure_code = "backup_failed"
    if failure_code is not None or verified_path is None:
        raise _new_error(failure_code or "backup_failed") from None
    return verified_path


def _fetch_bounded(
    cursor: sqlite3.Cursor,
    *,
    start: float,
    deadline_seconds: float,
    monotonic: Callable[[], float],
) -> tuple[tuple[object, ...], ...]:
    rows: list[tuple[object, ...]] = []
    while True:
        _check_deadline(start, deadline_seconds, monotonic)
        batch = cursor.fetchmany(_BACKUP_VERIFY_BATCH_SIZE)
        _check_deadline(start, deadline_seconds, monotonic)
        if not batch:
            return tuple(rows)
        rows.extend(tuple(row) for row in batch)


def _query_bounded(
    connection: sqlite3.Connection,
    sql: str,
    *,
    start: float,
    deadline_seconds: float,
    monotonic: Callable[[], float],
) -> tuple[tuple[object, ...], ...]:
    _check_deadline(start, deadline_seconds, monotonic)
    cursor = connection.execute(sql)
    try:
        return _fetch_bounded(
            cursor,
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
    finally:
        cursor.close()


def _database_snapshot(
    connection: sqlite3.Connection,
    *,
    start: float,
    deadline_seconds: float,
    monotonic: Callable[[], float],
) -> _DatabaseSnapshot:
    schema_objects = _query_bounded(
        connection,
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name",
        start=start,
        deadline_seconds=deadline_seconds,
        monotonic=monotonic,
    )
    tables: list[_TableSnapshot] = []
    for schema_object in schema_objects:
        _check_deadline(start, deadline_seconds, monotonic)
        if len(schema_object) < 2 or schema_object[0] != "table":
            continue
        table_name = schema_object[1]
        if type(table_name) is not str:
            raise _BackupVerificationFailure
        quoted_table = _quote_identifier(table_name)
        table_info = _query_bounded(
            connection,
            f"PRAGMA table_info({quoted_table})",
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        index_list = _query_bounded(
            connection,
            f"PRAGMA index_list({quoted_table})",
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        index_xinfo: list[tuple[str, tuple[tuple[object, ...], ...]]] = []
        for index_row in index_list:
            if len(index_row) < 2 or type(index_row[1]) is not str:
                raise _BackupVerificationFailure
            index_name = index_row[1]
            index_xinfo.append(
                (
                    index_name,
                    _query_bounded(
                        connection,
                        f"PRAGMA index_xinfo({_quote_identifier(index_name)})",
                        start=start,
                        deadline_seconds=deadline_seconds,
                        monotonic=monotonic,
                    ),
                )
            )
        rows = _query_bounded(
            connection,
            f"SELECT * FROM {quoted_table}",
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        event_json_types: tuple[object, ...] = ()
        if table_name == "events":
            event_json_types = tuple(
                row[0]
                for row in _query_bounded(
                    connection,
                    "SELECT typeof(event_json) FROM events ORDER BY campaign_id, sequence",
                    start=start,
                    deadline_seconds=deadline_seconds,
                    monotonic=monotonic,
                )
            )
            if any(value != "blob" for value in event_json_types):
                raise _BackupVerificationFailure
        tables.append(
            _TableSnapshot(
                name=table_name,
                table_info=table_info,
                index_list=index_list,
                index_xinfo=tuple(index_xinfo),
                rows=rows,
                event_json_types=event_json_types,
            )
        )
    return _DatabaseSnapshot(schema_objects=schema_objects, tables=tuple(tables))


def _verify_backup(
    migration_connection: sqlite3.Connection,
    backup_path: Path,
    *,
    expected_journal_mode: str,
    deadline_seconds: float = _BACKUP_VERIFY_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    start = 0.0
    reopen: sqlite3.Connection | None = None
    failure_code: MigrationIssueCode | None = None
    try:
        start = monotonic()
        if not _is_regular_file(backup_path):
            raise _BackupVerificationFailure
        migration_mode = _read_journal_mode(migration_connection)
        if migration_mode != expected_journal_mode.lower():
            raise _BackupVerificationFailure
        reopen = _open_backup_connection(backup_path, query_only=True)
        backup_file = _connection_main_file(reopen)
        if not os.path.samefile(backup_path, backup_file):
            raise _BackupVerificationFailure
        if _read_journal_mode(reopen) != expected_journal_mode.lower():
            raise _BackupVerificationFailure
        live_snapshot = _database_snapshot(
            migration_connection,
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        backup_snapshot = _database_snapshot(
            reopen,
            start=start,
            deadline_seconds=deadline_seconds,
            monotonic=monotonic,
        )
        if live_snapshot != backup_snapshot:
            raise _BackupVerificationFailure
        _check_deadline(start, deadline_seconds, monotonic)
    except MigrationError as error:
        failure_code = error.code
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        failure_code = "backup_failed"
    finally:
        if reopen is not None:
            try:
                reopen.close()
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                sqlite3.Error,
                _BackupVerificationFailure,
                _BackupProgressFailure,
            ):
                if failure_code is None:
                    failure_code = "backup_failed"
    if failure_code is None:
        try:
            _existing_artifact_paths(backup_path)
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
            _BackupVerificationFailure,
            _BackupProgressFailure,
        ):
            failure_code = "backup_failed"
    if failure_code is not None:
        raise _new_error(failure_code) from None


def _backup_existing_database(
    migration_connection: sqlite3.Connection,
    database_path: Path,
) -> Path:
    canonical: Path | None = None
    identity_failure_code: MigrationIssueCode | None = None
    try:
        canonical = _canonical_database_path(database_path, existing=True)
        migration_file = _connection_main_file(migration_connection)
        if not os.path.samefile(canonical, migration_file):
            identity_failure_code = "database_identity_mismatch"
    except MigrationError as error:
        identity_failure_code = error.code
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        identity_failure_code = "database_identity_mismatch"
    if identity_failure_code is not None or canonical is None:
        raise _new_error(identity_failure_code or "database_identity_mismatch") from None

    backup_source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    partial_path: Path | None = None
    failure_code: MigrationIssueCode | None = None
    result: Path | None = None
    try:
        expected_journal_mode = _read_journal_mode(migration_connection)
        backup_source = _open_backup_connection(canonical, query_only=True)
        if not _is_same_file_database(migration_connection, backup_source, canonical):
            raise _new_error("database_identity_mismatch")
        if _read_journal_mode(backup_source) != expected_journal_mode:
            raise _new_error("backup_failed")
        partial_path = _new_partial_backup_path(canonical)
        destination = _open_backup_connection(partial_path, query_only=False)
        destination_file = _connection_main_file(destination)
        if not os.path.samefile(partial_path, destination_file):
            raise _new_error("backup_failed")
        if os.path.samefile(canonical, destination_file):
            raise _new_error("backup_failed")
        _copy_database_with_deadline(backup_source, destination)
        if _read_journal_mode(destination) != expected_journal_mode:
            raise _new_error("backup_failed")
        destination.close()
        destination = None
        backup_source.close()
        backup_source = None
        _existing_artifact_paths(partial_path)
        _verify_backup(
            migration_connection,
            partial_path,
            expected_journal_mode=expected_journal_mode,
        )
        _existing_artifact_paths(partial_path)
        result = _promote_backup_artifacts(partial_path)
    except MigrationError as error:
        failure_code = error.code
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
        _BackupVerificationFailure,
        _BackupProgressFailure,
    ):
        failure_code = "backup_failed"
    finally:
        for connection in (destination, backup_source):
            if connection is not None:
                try:
                    connection.close()
                except (
                    OSError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                    sqlite3.Error,
                    _BackupVerificationFailure,
                    _BackupProgressFailure,
                ):
                    if failure_code is None:
                        failure_code = "backup_failed"
    if failure_code is not None:
        cleanup_code: MigrationIssueCode | None = None
        if partial_path is not None:
            try:
                _remove_unverified_backup(partial_path)
            except MigrationError as cleanup_error:
                cleanup_code = cleanup_error.code
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                sqlite3.Error,
                _BackupVerificationFailure,
                _BackupProgressFailure,
            ):
                cleanup_code = "backup_cleanup_failed"
        if cleanup_code is not None:
            raise _new_error(cleanup_code) from None
        raise _new_error(failure_code) from None
    if result is None:
        raise _new_error("backup_failed")
    return result


def _run_migrations(
    connection: sqlite3.Connection,
    database_path: Path,
) -> None:
    transaction_started = False
    failure_code: MigrationIssueCode | None = None
    try:
        _validate_migration_database_identity(connection, database_path)
        current_journal_mode = _read_journal_mode(connection)
        if current_journal_mode != "wal":
            connection.execute("PRAGMA journal_mode=WAL")
        if _read_journal_mode(connection) != "wal":
            raise _BackupVerificationFailure

        connection.execute("BEGIN IMMEDIATE")
        transaction_started = True
        specs = _discover_migrations()
        if _schema_migrations_exists(connection):
            _validate_schema_migrations_shape(connection)
            applied = _read_applied_migrations(connection)
        else:
            applied = []
        pending = _validate_applied_migrations(specs, applied)
        if pending and _has_existing_schema_or_data(connection):
            _backup_existing_database(connection, database_path)
        for spec in pending:
            for statement in _split_sql_statements(spec.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum_sha256) VALUES (?, ?, ?)",
                (spec.version, spec.name, spec.checksum),
            )
        connection.execute("COMMIT")
        transaction_started = False
    except MigrationError as error:
        failure_code = error.code
    except _BackupVerificationFailure, _BackupProgressFailure:
        failure_code = "backup_failed"
    except OSError, RuntimeError, TypeError, ValueError, sqlite3.Error:
        failure_code = "sql_error"
    finally:
        if transaction_started:
            _rollback(connection)
    if failure_code is not None:
        raise _new_error(failure_code) from None
