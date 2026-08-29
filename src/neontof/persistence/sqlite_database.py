"""SQLite connection lifecycle, migration boundary, and safe database errors."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from neontof.persistence.migrations import (
    MigrationError,
    MigrationIssueCode,
    _canonical_database_path,
    _run_migrations,
)

T = TypeVar("T")
type DatabaseIssueCode = Literal["locked", "io", "corrupt", "other"]

_WRITE_LOCK = threading.Lock()


class SqliteOperationError(Exception):
    """Sanitized failure for a non-migration SQLite operation."""

    __slots__ = ("code",)
    code: DatabaseIssueCode

    def __init__(self, code: DatabaseIssueCode) -> None:
        self.code = code
        Exception.__init__(self, "sqlite operation failed")


def _sqlite_issue_code(error: sqlite3.DatabaseError) -> DatabaseIssueCode:
    detail = str(error).lower()
    if "locked" in detail or "busy" in detail:
        return "locked"
    if "disk i/o" in detail or "readonly" in detail or "unable to open" in detail:
        return "io"
    if "malformed" in detail or "corrupt" in detail:
        return "corrupt"
    return "other"


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.DatabaseError:
        pass


class SqliteDatabase:
    """Own one database path while keeping connection use operation-scoped."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._write_lock = _WRITE_LOCK

    def migrate(self) -> None:
        """Apply additive migrations under the process-wide writer lock."""

        path_failure_code: MigrationIssueCode | None = None
        canonical: Path | None = None
        try:
            existing = self._path.exists() or self._path.is_symlink()
            canonical = _canonical_database_path(self._path, existing=existing)
        except MigrationError as error:
            path_failure_code = error.code
        except OSError, RuntimeError, ValueError:
            path_failure_code = "unsupported_database"
        if path_failure_code is not None or canonical is None:
            raise MigrationError(path_failure_code or "unsupported_database") from None
        self._path = canonical
        mkdir_failed = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            mkdir_failed = True
        if mkdir_failed:
            raise MigrationError("sql_error") from None

        failure_code: MigrationIssueCode | None = None
        with self._write_lock:
            connection: sqlite3.Connection | None = None
            try:
                connection = self._open_connection()
                _run_migrations(connection, self._path)
            except MigrationError as error:
                failure_code = error.code
            except OSError, RuntimeError, TypeError, ValueError, sqlite3.Error:
                failure_code = "sql_error"
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except OSError, RuntimeError, TypeError, ValueError, sqlite3.Error:
                        if failure_code is None:
                            failure_code = "sql_error"
        if failure_code is not None:
            raise MigrationError(failure_code) from None

    def _read(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        """Run one typed read on a fresh query-only connection."""

        connection: sqlite3.Connection | None = None
        mapped: SqliteOperationError | None = None
        result: list[T] = []
        try:
            try:
                connection = self._open_connection()
                connection.execute("PRAGMA query_only=ON")
                query_only = connection.execute("PRAGMA query_only").fetchone()
                if query_only is None or query_only[0] != 1:
                    raise sqlite3.DatabaseError
                result.append(operation(connection))
            except sqlite3.DatabaseError as error:
                mapped = SqliteOperationError(_sqlite_issue_code(error))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.DatabaseError as error:
                    if mapped is None:
                        mapped = SqliteOperationError(_sqlite_issue_code(error))
        if mapped is not None:
            raise mapped from None
        if not result:
            raise RuntimeError("sqlite operation produced no result")
        return result[0]

    def _write(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        """Run one write callback in a serialized immediate transaction."""

        with self._write_lock:
            connection: sqlite3.Connection | None = None
            mapped: SqliteOperationError | None = None
            result: list[T] = []
            try:
                try:
                    connection = self._open_connection()
                    connection.execute("BEGIN IMMEDIATE")
                    result.append(operation(connection))
                    connection.execute("COMMIT")
                except sqlite3.DatabaseError as error:
                    if connection is not None:
                        _rollback(connection)
                    mapped = SqliteOperationError(_sqlite_issue_code(error))
                except BaseException:
                    if connection is not None:
                        _rollback(connection)
                    raise
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except sqlite3.DatabaseError as error:
                        if mapped is None:
                            mapped = SqliteOperationError(_sqlite_issue_code(error))
        if mapped is not None:
            raise mapped from None
        if not result:
            raise RuntimeError("sqlite operation produced no result")
        return result[0]

    def _open_connection(self) -> sqlite3.Connection:
        """Open a connection with the fixed Phase 1 SQLite settings."""

        connection = sqlite3.connect(
            self._path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=True,
            uri=False,
        )
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA query_only=0")
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
            synchronous = connection.execute("PRAGMA synchronous").fetchone()
            query_only = connection.execute("PRAGMA query_only").fetchone()
            if (
                busy_timeout is None
                or busy_timeout[0] != 5000
                or synchronous is None
                or synchronous[0] != 2
                or query_only is None
                or query_only[0] != 0
            ):
                raise sqlite3.DatabaseError
        except sqlite3.DatabaseError:
            connection.close()
            raise
        return connection
