"""Phase 0 manifestとPhase 1 repository guard境界を検証する契約テスト。"""

from __future__ import annotations

import ast
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = REPOSITORY_ROOT / "src" / "neontof"
GENERATED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
ARTIFACT_SCAN_GENERATED_DIRECTORY_NAMES = frozenset({"dist", "node_modules"})
PHASE_1_ALLOWED_EXACT_PATHS = frozenset(
    {
        ".node-version",
        "client",
        "client/package-lock.json",
        "client/package.json",
        "client/tsconfig.json",
        "src/neontof/observability",
        "src/neontof/observability/__init__.py",
        "src/neontof/observability/records.py",
        "src/neontof/observability/sanitization.py",
        "src/neontof/application/turn_models.py",
        "src/neontof/persistence",
        "src/neontof/persistence/observation_store.py",
        "src/neontof/persistence/turn_request_store.py",
        "src/neontof/persistence/migrations",
    }
)
FORBIDDEN_REPOSITORY_FILENAMES = frozenset(
    {
        "Dockerfile",
        ".node-version",
        "eslint.config.mjs",
        "package-lock.json",
        "package.json",
        "prettier.config.mjs",
        "tsconfig.json",
        "vitest.config.ts",
    }
)
FORBIDDEN_DATABASE_SUFFIXES = frozenset(
    {
        ".sqlite",
        ".sqlite3",
        ".db",
        ".sqlite-wal",
        ".sqlite-shm",
        ".sqlite3-wal",
        ".sqlite3-shm",
        ".db-wal",
        ".db-shm",
    }
)
FORBIDDEN_DATABASE_GLOB_PATTERNS = (
    "*.db-*",
    "*.sqlite-*",
    "*.sqlite3-*",
    "*.sqlite-journal",
    "*.sqlite3-journal",
    "*.db-journal",
    "*.migration-*.partial.sqlite3",
    "*.migration-*.partial.sqlite3-wal",
    "*.migration-*.partial.sqlite3-shm",
    "*.migration-*.verified.sqlite3",
    "*.migration-*.verified.sqlite3-wal",
    "*.migration-*.verified.sqlite3-shm",
)
FORBIDDEN_DATABASE_DIRECTORY_NAMES = frozenset({".neontof-migration-backups"})
CI_GATE_COMMANDS = (
    'py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"',
    "py -3.14 -m venv .venv",
    ".venv/Scripts/python -m pip install --require-hashes -r requirements.lock.txt",
    ".venv/Scripts/python -m pip check",
    ".venv/Scripts/python -m compileall -q src",
    ".venv/Scripts/python -m ruff format --check src tests",
    ".venv/Scripts/python -m ruff check src tests",
    '.venv/Scripts/python -m mypy --strict src tests --exclude "tests/typecheck_fixtures"',
    ".venv/Scripts/python -m pytest -q",
)

SQLITE_MODULE_REFERENCE_NAMES = frozenset(
    {
        "Binary",
        "complete_statement",
        "Connection",
        "Cursor",
        "Blob",
        "Error",
        "DatabaseError",
        "IntegrityError",
        "SQLITE_BUSY",
        "SQLITE_DONE",
        "SQLITE_LOCKED",
        "SQLITE_OK",
    }
)
SQLITE_SINK_METHOD_NAMES = frozenset(
    {
        "execute",
        "executemany",
        "executescript",
        "cursor",
        "backup",
        "blobopen",
        "deserialize",
        "serialize",
        "iterdump",
        "setconfig",
        "enable_load_extension",
        "load_extension",
        "set_authorizer",
        "set_progress_handler",
        "set_trace_callback",
        "create_function",
        "create_aggregate",
        "create_collation",
        "create_window_function",
        "interrupt",
        "commit",
        "rollback",
    }
)
SQLITE_CURSOR_METHOD_NAMES = frozenset({"fetchone", "fetchall", "fetchmany", "close"})
SQLITE_BLOB_READ_METHOD_NAMES = frozenset({"close", "read", "seek", "tell"})
SQLITE_HIGHER_ORDER_NAME_NAMES = frozenset(
    {"AsyncExitStack", "ExitStack", "methodcaller", "partial"}
)
SQLITE_HIGHER_ORDER_METHOD_NAMES = frozenset(
    {"callback", "enter_context", "push", "push_async", "push_async_callback"}
)
NON_SQL_SUBSCRIPT_STORE_NAMES = frozenset(
    {
        "result",
        "pieces",
        "object_items",
        "role_values",
        "records",
        "tables",
        "index_xinfo",
        "validated",
        "steps",
    }
)
ALLOWED_SQLITE_CALLBACK_CALLS = {
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._validate_migration_database_identity",
    ): frozenset({"_connection_main_file"}),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._is_same_file_database",
    ): frozenset({"_connection_main_file"}),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._query_bounded",
    ): frozenset({"_fetch_bounded"}),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._database_snapshot",
    ): frozenset({"_query_bounded"}),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._verify_backup",
    ): frozenset({"_read_journal_mode", "_connection_main_file", "_database_snapshot"}),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._backup_existing_database",
    ): frozenset(
        {
            "_connection_main_file",
            "_read_journal_mode",
            "_is_same_file_database",
            "_copy_database_with_deadline",
            "_verify_backup",
        }
    ),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._run_migrations",
    ): frozenset(
        {
            "_validate_migration_database_identity",
            "_read_journal_mode",
            "_schema_migrations_exists",
            "_validate_schema_migrations_shape",
            "_read_applied_migrations",
            "_has_existing_schema_or_data",
            "_backup_existing_database",
            "_rollback",
        }
    ),
    (
        "src/neontof/persistence/observation_store.py",
        "neontof.persistence.observation_store.ObservationStore.append_transcript.<locals>.operation",
    ): frozenset({"_next_sequence"}),
    (
        "src/neontof/persistence/observation_store.py",
        "neontof.persistence.observation_store.ObservationStore.append_telemetry.<locals>.operation",
    ): frozenset({"_next_sequence"}),
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database.SqliteDatabase.migrate",
    ): frozenset({"_run_migrations"}),
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database.SqliteDatabase._read",
    ): frozenset({"operation"}),
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database.SqliteDatabase._write",
    ): frozenset({"operation", "_rollback"}),
}
ALLOWED_SQLITE_CALLBACK_CALL_COUNTS = {
    (relative_path, qualified_name, callback_name): 1
    for (relative_path, qualified_name), callback_names in ALLOWED_SQLITE_CALLBACK_CALLS.items()
    for callback_name in callback_names
}
ALLOWED_SQLITE_CALLBACK_CALL_COUNTS.update(
    {
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._is_same_file_database",
            "_connection_main_file",
        ): 2,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._database_snapshot",
            "_query_bounded",
        ): 6,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._verify_backup",
            "_read_journal_mode",
        ): 2,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._verify_backup",
            "_database_snapshot",
        ): 2,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._backup_existing_database",
            "_connection_main_file",
        ): 2,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._backup_existing_database",
            "_read_journal_mode",
        ): 3,
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._run_migrations",
            "_read_journal_mode",
        ): 2,
        (
            "src/neontof/persistence/sqlite_database.py",
            "neontof.persistence.sqlite_database.SqliteDatabase._write",
            "_rollback",
        ): 2,
    }
)
CROSS_MODULE_METHOD_NAMES = frozenset(
    {"_read_campaign_on_connection", "read_campaign", "claim", "_write"}
)
DATABASE_OPERATION_ALLOWLIST = frozenset(
    {
        (
            "src/neontof/persistence/event_store.py",
            "neontof.persistence.event_store.EventStore.append",
            "_write",
        ),
        (
            "src/neontof/persistence/event_store.py",
            "neontof.persistence.event_store.EventStore.read_campaign",
            "_read",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.append_transcript",
            "_write",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.append_telemetry",
            "_write",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.read_transcript",
            "_read",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.read_telemetry",
            "_read",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.session_cost_microusd",
            "_read",
        ),
        (
            "src/neontof/persistence/projection_store.py",
            "neontof.persistence.projection_store.ProjectionStore.rebuild",
            "_write",
        ),
        (
            "src/neontof/persistence/projection_store.py",
            "neontof.persistence.projection_store.ProjectionStore.read",
            "_read",
        ),
        (
            "src/neontof/persistence/projection_store.py",
            "neontof.persistence.projection_store.ProjectionStore.delete",
            "_write",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.claim",
            "_write",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.stage_recovery_metadata",
            "_write",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.stage",
            "_write",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.read",
            "_read",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.read_processing",
            "_read",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.complete",
            "_write",
        ),
    }
)
DATABASE_OPERATION_ALLOWLIST_COUNTS = {key: 1 for key in DATABASE_OPERATION_ALLOWLIST}
DATABASE_OPERATION_ALLOWLIST_COUNTS.update(
    {
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.read_transcript",
            "_read",
        ): 2,
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.read_telemetry",
            "_read",
        ): 2,
    }
)
CURRENT_EVENTSTORE_CALLER_COUNT = 2
P1_03_EVENTSTORE_CALLER_COUNT = 2

RUNTIME_CONNECT_PATH = "src/neontof/persistence/sqlite_database.py"
RUNTIME_CONNECT_QUALIFIED_NAME = (
    "neontof.persistence.sqlite_database.SqliteDatabase._open_connection"
)
MIGRATION_CONNECT_PATH = "src/neontof/persistence/migrations.py"
MIGRATION_CONNECT_QUALIFIED_NAME = "neontof.persistence.migrations._open_backup_connection"
CONNECT_ALLOWLIST = {
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME),
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME),
}
EVENTSTORE_CALLER_ALLOWLIST = {
    (
        "src/neontof/application/turn_lifecycle.py",
        "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.execute",
    ),
    (
        "src/neontof/application/turn_lifecycle.py",
        "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.revert_latest",
    ),
}
EVENT_DML_PATH = "src/neontof/persistence/event_store.py"
EVENT_DML_QUALIFIED_NAME = "neontof.persistence.event_store.EventStore.append.<locals>.operation"
SAME_CONNECTION_READER_PATH = "src/neontof/persistence/projection_store.py"
SAME_CONNECTION_READER_QUALIFIED_NAME = (
    "neontof.persistence.projection_store.ProjectionStore.rebuild.<locals>.operation"
)
TURN_REQUEST_READER_PATH = "src/neontof/persistence/turn_request_store.py"
TURN_REQUEST_READER_QUALIFIED_NAME = (
    "neontof.persistence.turn_request_store.TurnRequestStore.claim.<locals>.operation"
)
SAME_CONNECTION_READER_ALLOWLIST = {
    (SAME_CONNECTION_READER_PATH, SAME_CONNECTION_READER_QUALIFIED_NAME),
    (TURN_REQUEST_READER_PATH, TURN_REQUEST_READER_QUALIFIED_NAME),
}
GETATTR_ALLOWLIST = {
    (
        "src/neontof/persistence/event_store.py",
        "neontof.persistence.event_store._assert_event_scalar_fields",
    ): 2,
    (
        "src/neontof/persistence/event_store.py",
        "neontof.persistence.event_store._readback_event",
    ): 2,
    (
        "src/neontof/persistence/event_store.py",
        "neontof.persistence.event_store.EventStore.read_turn",
    ): 1,
    (
        "src/neontof/persistence/event_store.py",
        "neontof.persistence.event_store.EventStore.find_turn_by_request",
    ): 1,
    (
        "src/neontof/contracts/semantic_result.py",
        "neontof.contracts.semantic_result._failure_status",
    ): 1,
    (
        "src/neontof/contracts/semantic_result.py",
        "neontof.contracts.semantic_result._validate_context",
    ): 1,
    ("src/neontof/main.py", "neontof.main._install_ctrl_break_handler"): 1,
}
OBJECT_SETATTR_ALLOWLIST = {
    (
        "src/neontof/contracts/event_parser.py",
        "neontof.contracts.event_parser.DomainEventValidationError.__init__",
    )
}
TRANSACTION_ALLOWLIST = {
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database._rollback",
        "ROLLBACK",
    ),
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database.SqliteDatabase._write",
        "BEGIN IMMEDIATE",
    ),
    (
        "src/neontof/persistence/sqlite_database.py",
        "neontof.persistence.sqlite_database.SqliteDatabase._write",
        "COMMIT",
    ),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._rollback",
        "ROLLBACK",
    ),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._run_migrations",
        "BEGIN IMMEDIATE",
    ),
    (
        "src/neontof/persistence/migrations.py",
        "neontof.persistence.migrations._run_migrations",
        "COMMIT",
    ),
}
PRAGMA_ALLOWLIST_COUNTS = {
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "busy_timeout=5000"): 1,
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "busy_timeout"): 1,
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "synchronous=full"): 1,
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "synchronous"): 1,
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "query_only=0"): 1,
    (RUNTIME_CONNECT_PATH, RUNTIME_CONNECT_QUALIFIED_NAME, "query_only"): 1,
    (
        RUNTIME_CONNECT_PATH,
        "neontof.persistence.sqlite_database.SqliteDatabase._read",
        "query_only=on",
    ): 1,
    (
        RUNTIME_CONNECT_PATH,
        "neontof.persistence.sqlite_database.SqliteDatabase._read",
        "query_only",
    ): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "busy_timeout=<dynamic>"): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "busy_timeout"): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "synchronous=full"): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "synchronous"): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "query_only=<dynamic>"): 1,
    (MIGRATION_CONNECT_PATH, MIGRATION_CONNECT_QUALIFIED_NAME, "query_only"): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._connection_main_file",
        "database_list",
    ): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._read_journal_mode",
        "journal_mode",
    ): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._validate_schema_migrations_shape",
        "table_info=schema_migrations",
    ): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._validate_schema_migrations_shape",
        "index_list=schema_migrations",
    ): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._validate_schema_migrations_shape",
        "index_xinfo=<dynamic>",
    ): 1,
    (
        MIGRATION_CONNECT_PATH,
        "neontof.persistence.migrations._run_migrations",
        "journal_mode=wal",
    ): 1,
}


@dataclass(frozen=True)
class _SourceRecord:
    path: Path
    relative_path: str
    source: str
    tree: ast.Module
    visitor: _SqliteUsageVisitor


def _direct_requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-r"):
            continue
        match = re.match(
            r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)\s*(?:==|~=|!=|<=|>=|<|>|;|$)", line
        )
        assert match is not None, line
        names.add(match.group("name").lower())
    return names


def _tracked_candidate_files(root: Path = REPOSITORY_ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if path.is_file() and not any(part in GENERATED_DIRECTORY_NAMES for part in relative_parts):
            files.append(path)
    return files


def _is_phase_1_allowed_path(relative_path: Path) -> bool:
    if relative_path.as_posix() in PHASE_1_ALLOWED_EXACT_PATHS:
        return True

    if relative_path.name in FORBIDDEN_REPOSITORY_FILENAMES:
        return False
    if _is_forbidden_database_artifact(relative_path):
        return False

    relative_parts = relative_path.parts
    if relative_parts and relative_parts[0] == "client":
        if len(relative_parts) > 1 and relative_parts[1] in {"node_modules", "dist"}:
            return False
        return len(relative_parts) > 1

    migrations_root = Path("src/neontof/persistence/migrations")
    persistence_root = Path("src/neontof/persistence")
    return migrations_root in relative_path.parents or persistence_root in relative_path.parents


def _is_forbidden_database_artifact(relative_path: Path) -> bool:
    name = relative_path.name.lower()
    if name in FORBIDDEN_DATABASE_DIRECTORY_NAMES:
        return True
    if name.endswith(tuple(FORBIDDEN_DATABASE_SUFFIXES)):
        return True
    return any(Path(name).match(pattern) for pattern in FORBIDDEN_DATABASE_GLOB_PATTERNS)


def _ci_guard_violations(ci_text: str) -> list[str]:
    violations: list[str] = []
    if "runs-on: windows-latest" not in ci_text:
        violations.append("windows_runner")

    positions: list[int] = []
    for command in CI_GATE_COMMANDS:
        if command not in ci_text:
            violations.append(f"missing:{command}")
        else:
            positions.append(ci_text.index(command))
    if len(positions) == len(CI_GATE_COMMANDS) and positions != sorted(positions):
        violations.append("python_gate_order")
    return violations


class _SqliteUsageVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str = "neontof.unknown") -> None:
        self.sqlite_module_names: set[str] = {"sqlite3"}
        self.sqlite_symbol_names: set[str] = set()
        self.dynamic_import_module_names: set[str] = set()
        self.dynamic_import_function_names: set[str] = {"__import__"}
        self.dynamic_sqlite_import_calls: list[tuple[ast.Call, str]] = []
        self.dynamic_import_rebound = False
        self.sqlite_star_imported = False
        self.uses_sqlite = False
        self.has_potential_sink = False
        self.invalid_sqlite_import = False
        self.sqlite_rebound = False
        self.unsafe_database_rebind = False
        self.unsafe_database_escape = False
        self.indirect_database_alias = False
        self.calls: list[tuple[ast.Call, str]] = []
        self.sqlite_module_attributes: list[tuple[ast.Attribute, str]] = []
        self.sqlite_module_calls: list[tuple[ast.Call, str, str]] = []
        self.getattr_calls: list[tuple[ast.Call, str]] = []
        self.attribute_stores: list[tuple[ast.Attribute, str]] = []
        self.subscript_stores: list[tuple[ast.Subscript, str]] = []
        self.lambda_nodes: list[tuple[ast.Lambda, str]] = []
        self.context_expressions: list[tuple[ast.AST, str]] = []
        self.higher_order_names: set[str] = set()
        self.higher_order_module_names: set[str] = set()
        self.higher_order_calls: list[tuple[ast.Call, str]] = []
        self.known_connection_names: set[str] = set()
        self.known_cursor_names: set[str] = set()
        self.opened_cursor_names: set[str] = set()
        self.cursor_close_counts: dict[str, int] = {}
        self.open_handle_bindings: dict[tuple[str, str], str] = {}
        self.open_handle_assignments: list[tuple[str, str, str, ast.Assign | ast.AnnAssign]] = []
        self.handle_alias_bindings: set[tuple[str, str]] = set()
        self.borrowed_cursor_bindings: set[tuple[str, str]] = set()
        self.known_blob_names: set[str] = set()
        self.opened_blob_names: set[str] = set()
        self.blob_close_counts: dict[str, int] = {}
        self.borrowed_blob_bindings: set[tuple[str, str]] = set()
        self.known_backup_source_names: set[str] = set()
        self.readonly_blob_names: set[str] = set()
        self.event_store_names: set[str] = set()
        self.cross_module_method_aliases: dict[str, str] = {}
        self.cross_module_method_alias_rebound = False
        self.unsafe_event_store_rebind = False
        self.return_nodes: list[tuple[ast.Return, str]] = []
        self.yield_nodes: list[tuple[ast.Yield | ast.YieldFrom, str]] = []
        self.function_names: set[str] = set()
        self.function_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.module_name = module_name
        self._scope: list[str] = [module_name]
        self._function_depth = 0

    @staticmethod
    def _is_sqlite_module(module_name: str) -> bool:
        return module_name == "sqlite3" or module_name.startswith("sqlite3.")

    @staticmethod
    def _attribute_root_name(node: ast.AST) -> str | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    @staticmethod
    def _target_names(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.Tuple, ast.List)):
            names: list[str] = []
            for element in node.elts:
                names.extend(_SqliteUsageVisitor._target_names(element))
            return tuple(names)
        return ()

    def _qualified_name(self) -> str:
        return self._scope[-1]

    def _enter_function(self, name: str) -> None:
        parent = self._scope[-1]
        if self._function_depth:
            qualified = f"{parent}.<locals>.{name}"
        else:
            qualified = f"{parent}.{name}"
        self._scope.append(qualified)
        self._function_depth += 1

    def _leave_function(self) -> None:
        self._scope.pop()
        self._function_depth -= 1

    def _bind_annotation(self, name: str, annotation: ast.AST | None) -> None:
        if annotation is None:
            return
        parts = _attribute_parts(annotation)
        if parts is not None and parts[:1] == ("sqlite3",):
            if parts[-1] == "Connection":
                self.known_connection_names.add(name)
            elif parts[-1] == "Cursor":
                self.known_cursor_names.add(name)
            elif parts[-1] == "Blob":
                self.known_blob_names.add(name)
        if isinstance(annotation, ast.Name) and annotation.id == "EventStore":
            self.event_store_names.add(name)
        if isinstance(annotation, ast.Name) and annotation.id == "_BackupSource":
            self.known_backup_source_names.add(name)

    @staticmethod
    def _is_event_store_reference(value: ast.AST) -> bool:
        parts = _attribute_parts(value)
        return parts is not None and parts[-1] == "_event_store"

    def _is_safe_event_store_value(self, value: ast.AST) -> bool:
        return (
            self._is_event_store_reference(value)
            or (
                isinstance(value, ast.Name)
                and (value.id == "event_store" or value.id in self.event_store_names)
            )
            or (isinstance(value, ast.Call) and _receiver_terminal_name(value.func) == "EventStore")
        )

    @staticmethod
    def _cross_module_method_reference(value: ast.AST) -> str | None:
        if not isinstance(value, ast.Attribute):
            return None
        return value.attr if value.attr in CROSS_MODULE_METHOD_NAMES else None

    def _is_dynamic_import_reference(self, value: ast.AST) -> bool:
        if isinstance(value, ast.Name):
            return value.id in self.dynamic_import_function_names
        parts = _attribute_parts(value)
        return (
            parts is not None
            and parts[0] in self.dynamic_import_module_names
            and parts[-1] == "import_module"
        )

    def _bind_from_value(
        self,
        target: ast.AST,
        value: ast.AST,
        assignment: ast.Assign | ast.AnnAssign | None = None,
    ) -> None:
        names = self._target_names(target)
        if not names:
            return
        qualified_name = self._qualified_name()
        if self._is_dynamic_import_reference(value):
            self.dynamic_import_function_names.update(names)
            return
        method_name = self._cross_module_method_reference(value)
        if method_name is not None:
            for name in names:
                self.cross_module_method_aliases[name] = method_name
            return
        if self._is_safe_event_store_value(value):
            self.event_store_names.update(names)
            return
        if _is_sqlite_module_call(value, "connect", self):
            self.known_connection_names.update(names)
            return
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "blobopen"
            and _receiver_is_known_connection(value.func.value, self)
        ):
            self.known_blob_names.update(names)
            self.opened_blob_names.update(names)
            for name in names:
                self.open_handle_bindings[(qualified_name, name)] = "blob"
                if assignment is not None:
                    self.open_handle_assignments.append((qualified_name, name, "blob", assignment))
            if _keyword_bool(value, "readonly") is True:
                self.readonly_blob_names.update(names)
            return
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "execute"
            and _receiver_is_known_connection(value.func.value, self)
        ):
            self.known_cursor_names.update(names)
            self.opened_cursor_names.update(names)
            for name in names:
                self.open_handle_bindings[(qualified_name, name)] = "cursor"
                if assignment is not None:
                    self.open_handle_assignments.append(
                        (qualified_name, name, "cursor", assignment)
                    )
            return
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "cursor"
            and _receiver_is_known_connection(value.func.value, self)
        ):
            self.known_cursor_names.update(names)
            self.opened_cursor_names.update(names)
            for name in names:
                self.open_handle_bindings[(qualified_name, name)] = "cursor"
                if assignment is not None:
                    self.open_handle_assignments.append(
                        (qualified_name, name, "cursor", assignment)
                    )
            return
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "_open_backup_connection"
        ):
            self.known_connection_names.update(names)
        if isinstance(value, ast.Name):
            if value.id in self.known_cursor_names or value.id in self.known_blob_names:
                self.handle_alias_bindings.update((qualified_name, name) for name in names)
            if value.id in self.known_connection_names:
                self.known_connection_names.update(names)
            if value.id in self.known_cursor_names:
                self.known_cursor_names.update(names)
            if value.id in self.known_blob_names:
                self.known_blob_names.update(names)
            if value.id in self.known_backup_source_names:
                self.known_backup_source_names.update(names)
            if value.id in self.readonly_blob_names:
                self.readonly_blob_names.update(names)
            if value.id in self.event_store_names:
                self.event_store_names.update(names)

    def _is_safe_database_rebind(self, value: ast.AST) -> bool:
        if isinstance(value, ast.Constant) and value.value is None:
            return True
        if _is_sqlite_module_call(value, "connect", self):
            return True
        if isinstance(value, ast.Name):
            return bool(
                value.id
                in self.known_connection_names | self.known_cursor_names | self.known_blob_names
            )
        if not isinstance(value, ast.Call):
            return False
        if isinstance(value.func, ast.Name) and value.func.id == "_open_backup_connection":
            return self.module_name == "neontof.persistence.migrations"
        if isinstance(value.func, ast.Attribute):
            parts = _attribute_parts(value.func)
            if (
                self.module_name == "neontof.persistence.sqlite_database"
                and parts == ("self", "_open_connection")
                and self._qualified_name()
                in {
                    "neontof.persistence.sqlite_database.SqliteDatabase.migrate",
                    "neontof.persistence.sqlite_database.SqliteDatabase._read",
                    "neontof.persistence.sqlite_database.SqliteDatabase._write",
                }
            ):
                return True
            if value.func.attr in {"blobopen", "execute", "cursor"}:
                return _receiver_is_known_connection(value.func.value, self)
        return False

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            if self._is_sqlite_module(imported.name):
                self.sqlite_module_names.add(imported.asname or imported.name.split(".", 1)[0])
                self.uses_sqlite = True
                self.has_potential_sink = True
                if imported.asname is not None or imported.name != "sqlite3":
                    self.invalid_sqlite_import = True
            elif imported.name == "importlib":
                self.dynamic_import_module_names.add(imported.asname or "importlib")
            elif imported.name in {"contextlib", "functools", "operator"}:
                self.higher_order_module_names.add(imported.asname or imported.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = node.module or ""
        if node.level == 0 and self._is_sqlite_module(module_name):
            self.uses_sqlite = True
            self.has_potential_sink = True
            self.invalid_sqlite_import = True
            for imported in node.names:
                if imported.name in SQLITE_MODULE_REFERENCE_NAMES or imported.name == "connect":
                    self.sqlite_symbol_names.add(imported.asname or imported.name)
                elif imported.name == "*":
                    self.sqlite_star_imported = True
        elif {"persistence", "sqlite"}.intersection(module_name.split(".")) and any(
            imported.name in {"connect", "Connection", "*"} for imported in node.names
        ):
            self.uses_sqlite = True
            self.has_potential_sink = True
            self.invalid_sqlite_import = True
        elif node.level == 0 and module_name in {
            "contextlib",
            "functools",
            "operator",
        }:
            for imported in node.names:
                if imported.name in SQLITE_HIGHER_ORDER_NAME_NAMES | {"setitem", "delitem"}:
                    self.higher_order_names.add(imported.asname or imported.name)
                    self.has_potential_sink = True
        elif node.level == 0 and module_name == "importlib":
            for imported in node.names:
                if imported.name == "import_module":
                    self.dynamic_import_function_names.add(imported.asname or imported.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self._scope[-1]
        self._scope.append(f"{parent}.{node.name}")
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_function(node.name)
        qualified_name = self._qualified_name()
        self.function_names.add(qualified_name)
        self.function_nodes[qualified_name] = node
        arguments = (
            tuple(node.args.posonlyargs)
            + tuple(node.args.args)
            + tuple(node.args.kwonlyargs)
            + ((node.args.vararg,) if node.args.vararg is not None else ())
            + ((node.args.kwarg,) if node.args.kwarg is not None else ())
        )
        for argument in arguments:
            self._bind_annotation(argument.arg, argument.annotation)
            annotation_parts = (
                _attribute_parts(argument.annotation) if argument.annotation else None
            )
            if annotation_parts is not None:
                if annotation_parts[-1] == "Cursor":
                    self.borrowed_cursor_bindings.add((qualified_name, argument.arg))
                elif annotation_parts[-1] == "Blob":
                    self.borrowed_blob_bindings.add((qualified_name, argument.arg))
        self.generic_visit(node)
        self._leave_function()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter_function(node.name)
        qualified_name = self._qualified_name()
        self.function_names.add(qualified_name)
        self.function_nodes[qualified_name] = node
        arguments = (
            tuple(node.args.posonlyargs)
            + tuple(node.args.args)
            + tuple(node.args.kwonlyargs)
            + ((node.args.vararg,) if node.args.vararg is not None else ())
            + ((node.args.kwarg,) if node.args.kwarg is not None else ())
        )
        for argument in arguments:
            self._bind_annotation(argument.arg, argument.annotation)
            annotation_parts = (
                _attribute_parts(argument.annotation) if argument.annotation else None
            )
            if annotation_parts is not None:
                if annotation_parts[-1] == "Cursor":
                    self.borrowed_cursor_bindings.add((qualified_name, argument.arg))
                elif annotation_parts[-1] == "Blob":
                    self.borrowed_blob_bindings.add((qualified_name, argument.arg))
        self.generic_visit(node)
        self._leave_function()

    def visit_Return(self, node: ast.Return) -> None:
        self.return_nodes.append((node, self._qualified_name()))
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        self.yield_nodes.append((node, self._qualified_name()))
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.yield_nodes.append((node, self._qualified_name()))
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.lambda_nodes.append((node, self._qualified_name()))
        arguments = (
            tuple(node.args.posonlyargs)
            + tuple(node.args.args)
            + tuple(node.args.kwonlyargs)
            + ((node.args.vararg,) if node.args.vararg is not None else ())
            + ((node.args.kwarg,) if node.args.kwarg is not None else ())
        )
        for argument in arguments:
            self._bind_annotation(argument.arg, argument.annotation)
            if argument.arg == "connection":
                self.known_connection_names.add(argument.arg)
            elif argument.arg == "cursor":
                self.known_cursor_names.add(argument.arg)
            elif argument.arg == "blob":
                self.known_blob_names.add(argument.arg)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.context_expressions.extend(
            (item.context_expr, self._qualified_name()) for item in node.items
        )
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.context_expressions.extend(
            (item.context_expr, self._qualified_name()) for item in node.items
        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        for name in self._target_names(node.target):
            self._bind_annotation(name, node.annotation)
            if node.value is None:
                annotation_parts = _attribute_parts(node.annotation)
                if annotation_parts is not None:
                    if annotation_parts[-1] == "Cursor":
                        self.borrowed_cursor_bindings.add((self._qualified_name(), name))
                    elif annotation_parts[-1] == "Blob":
                        self.borrowed_blob_bindings.add((self._qualified_name(), name))
        if node.value is not None:
            names = self._target_names(node.target)
            if _assignment_escapes_database_handle(node.target, node.value, self):
                self.unsafe_database_escape = True
                self.has_potential_sink = True
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in self.cross_module_method_aliases
                and self._cross_module_method_reference(node.value) is None
            ):
                self.cross_module_method_alias_rebound = True
                self.has_potential_sink = True
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in self.dynamic_import_function_names
                and not self._is_dynamic_import_reference(node.value)
            ):
                self.dynamic_import_rebound = True
                self.has_potential_sink = True
            if set(names) & self.event_store_names and not self._is_safe_event_store_value(
                node.value
            ):
                self.unsafe_event_store_rebind = True
                self.has_potential_sink = True
            if (
                isinstance(node.target, ast.Attribute)
                and node.target.attr == "_event_store"
                and not self._is_safe_event_store_value(node.value)
            ):
                self.unsafe_event_store_rebind = True
                self.has_potential_sink = True
            known_database_names = (
                self.known_connection_names | self.known_cursor_names | self.known_blob_names
            )
            if set(names) & known_database_names and not self._is_safe_database_rebind(node.value):
                self.unsafe_database_rebind = True
                self.has_potential_sink = True
            self._bind_from_value(node.target, node.value, node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            names = self._target_names(target)
            if _assignment_escapes_database_handle(target, node.value, self):
                self.unsafe_database_escape = True
                self.has_potential_sink = True
            if (
                isinstance(target, ast.Name)
                and target.id in self.cross_module_method_aliases
                and self._cross_module_method_reference(node.value) is None
            ):
                self.cross_module_method_alias_rebound = True
                self.has_potential_sink = True
            if (
                isinstance(target, ast.Name)
                and target.id in self.dynamic_import_function_names
                and not self._is_dynamic_import_reference(node.value)
            ):
                self.dynamic_import_rebound = True
                self.has_potential_sink = True
            if set(names) & self.event_store_names and not self._is_safe_event_store_value(
                node.value
            ):
                self.unsafe_event_store_rebind = True
                self.has_potential_sink = True
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "_event_store"
                and not self._is_safe_event_store_value(node.value)
            ):
                self.unsafe_event_store_rebind = True
                self.has_potential_sink = True
            known_database_names = (
                self.known_connection_names | self.known_cursor_names | self.known_blob_names
            )
            if set(names) & known_database_names and not self._is_safe_database_rebind(node.value):
                self.unsafe_database_rebind = True
                self.has_potential_sink = True
            if isinstance(target, ast.Name) and (
                target.id in self.sqlite_module_names or target.id in self.sqlite_symbol_names
            ):
                self.sqlite_rebound = True
                self.has_potential_sink = True
            if isinstance(node.value, ast.Name) and node.value.id in self.sqlite_module_names:
                self.sqlite_rebound = True
                self.has_potential_sink = True
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr in SQLITE_SINK_METHOD_NAMES
            ):
                self.indirect_database_alias = True
                self.has_potential_sink = True
            value_parts = _attribute_parts(node.value)
            if value_parts is not None and value_parts[:1] == ("sqlite3",):
                self.indirect_database_alias = True
                self.has_potential_sink = True
            if isinstance(node.value, ast.Name) and node.value.id in self.higher_order_names:
                self.higher_order_names.update(names)
            if (
                value_parts is not None
                and value_parts[0] in self.higher_order_module_names
                and value_parts[-1] in SQLITE_HIGHER_ORDER_NAME_NAMES
            ):
                self.higher_order_names.update(names)
            self._bind_from_value(target, node.value, node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        parts = _attribute_parts(node)
        if parts is not None and parts[:1] == ("sqlite3",):
            self.uses_sqlite = True
            self.has_potential_sink = True
            self.sqlite_module_attributes.append((node, self._qualified_name()))
        if isinstance(node.ctx, ast.Store):
            self.attribute_stores.append((node, self._qualified_name()))
            if node.attr in {"autocommit", "isolation_level", "row_factory", "text_factory"}:
                self.has_potential_sink = True
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Store):
            self.subscript_stores.append((node, self._qualified_name()))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        qualified_name = self._qualified_name()
        self.calls.append((node, qualified_name))
        if isinstance(node.func, ast.Name):
            if node.func.id == "getattr":
                self.getattr_calls.append((node, qualified_name))
                self.has_potential_sink = True
            elif node.func.id in self.dynamic_import_function_names:
                self.dynamic_sqlite_import_calls.append((node, qualified_name))
                if node.args and _static_string(node.args[0]) == "sqlite3":
                    self.uses_sqlite = True
                self.has_potential_sink = True
            elif node.func.id in {"setattr", "delattr"}:
                self.has_potential_sink = True
            elif node.func.id in self.higher_order_names | SQLITE_HIGHER_ORDER_NAME_NAMES:
                self.higher_order_calls.append((node, qualified_name))
                self.has_potential_sink = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in SQLITE_SINK_METHOD_NAMES:
                self.has_potential_sink = True
            module_parts = _attribute_parts(node.func)
            if (
                module_parts is not None
                and module_parts[0] in self.dynamic_import_module_names
                and module_parts[-1] == "import_module"
            ):
                self.dynamic_sqlite_import_calls.append((node, qualified_name))
                if node.args and _static_string(node.args[0]) == "sqlite3":
                    self.uses_sqlite = True
                self.has_potential_sink = True
            if module_parts is not None and module_parts[:1] == ("sqlite3",):
                self.uses_sqlite = True
                self.has_potential_sink = True
                self.sqlite_module_calls.append((node, module_parts[-1], qualified_name))
            if (
                module_parts is not None
                and module_parts[0] in self.higher_order_module_names
                and module_parts[-1] in SQLITE_HIGHER_ORDER_NAME_NAMES
            ):
                self.higher_order_calls.append((node, qualified_name))
                self.has_potential_sink = True
            if node.func.attr in SQLITE_HIGHER_ORDER_METHOD_NAMES:
                self.higher_order_calls.append((node, qualified_name))
                self.has_potential_sink = True
            if (
                node.func.attr in {"setitem", "delitem"}
                and module_parts is not None
                and module_parts[:1] == ("operator",)
            ):
                self.has_potential_sink = True
            receiver_name = _receiver_terminal_name(node.func.value)
            if node.func.attr == "close" and receiver_name is not None:
                if receiver_name in self.known_blob_names:
                    self.blob_close_counts[receiver_name] = (
                        self.blob_close_counts.get(receiver_name, 0) + 1
                    )
                if receiver_name in self.known_cursor_names:
                    self.cursor_close_counts[receiver_name] = (
                        self.cursor_close_counts.get(receiver_name, 0) + 1
                    )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and (
            node.id in self.sqlite_symbol_names or self.sqlite_star_imported
        ):
            self.uses_sqlite = True
            self.has_potential_sink = True
        self.generic_visit(node)


def _attribute_parts(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return tuple(parts)


def _root_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _root_name(node.value)
    if isinstance(node, ast.Subscript):
        return _root_name(node.value)
    return None


def _is_method_call(node: ast.AST, method_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method_name
    )


def _is_sqlite_module_call(
    node: ast.AST,
    attribute_name: str,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    parts = _attribute_parts(node.func)
    return (
        node.func.attr == attribute_name
        and parts is not None
        and parts[:1] == ("sqlite3",)
        and not visitor.sqlite_rebound
    )


def _receiver_is_known_connection(node: ast.AST, visitor: _SqliteUsageVisitor) -> bool:
    root = _root_name(node)
    return root is not None and root in visitor.known_connection_names


def _receiver_is_known_cursor(node: ast.AST, visitor: _SqliteUsageVisitor) -> bool:
    root = _root_name(node)
    return root is not None and root in visitor.known_cursor_names


def _receiver_is_known_blob(node: ast.AST, visitor: _SqliteUsageVisitor) -> bool:
    root = _root_name(node)
    return root is not None and root in visitor.known_blob_names


def _keyword_bool(call: ast.Call, name: str) -> bool | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value if type(keyword.value.value) is bool else None
    return None


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr) and not any(
        isinstance(value, ast.FormattedValue) for value in node.values
    ):
        parts = [value.value for value in node.values if isinstance(value, ast.Constant)]
        return "".join(part for part in parts if type(part) is str)
    return None


type _SqlToken = tuple[str, str, bool]
type _ParsedSources = tuple[list[_SourceRecord], set[Path]]


def _source_relative_path(path: Path, production_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(REPOSITORY_ROOT.resolve())
        return relative.as_posix()
    except ValueError:
        relative = path.relative_to(production_root)
        root_parts = production_root.parts
        if root_parts and root_parts[-1] == "neontof":
            return Path("src", "neontof", relative).as_posix()
        if root_parts and root_parts[-1] == "src":
            return Path("src", relative).as_posix()
        return relative.as_posix()


def _module_name_for_source(relative_path: str) -> str:
    prefix = "src/neontof/"
    relative_path = relative_path.removeprefix(prefix).removesuffix(".py")
    parts = relative_path.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(("neontof", *parts))


def _source_records(production_root: Path) -> _ParsedSources:
    records: list[_SourceRecord] = []
    parse_failures: set[Path] = set()
    for path in sorted(production_root.rglob("*.py")):
        try:
            source = path.read_bytes().decode("utf-8", errors="strict")
            relative_path = _source_relative_path(path, production_root)
            tree = ast.parse(source, filename=str(path))
        except OSError, UnicodeError, SyntaxError:
            parse_failures.add(path)
            continue
        visitor = _SqliteUsageVisitor(_module_name_for_source(relative_path))
        visitor.visit(tree)
        records.append(
            _SourceRecord(
                path=path,
                relative_path=relative_path,
                source=source,
                tree=tree,
                visitor=visitor,
            )
        )
    return records, parse_failures


def _lex_sql(sql: str) -> list[_SqlToken] | None:
    tokens: list[_SqlToken] = []
    index = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
            continue
        if character in "'\"`[":
            closing = "]" if character == "[" else character
            value: list[str] = []
            cursor = index + 1
            closed = False
            while cursor < length:
                if sql[cursor] == closing:
                    if closing != "]" and cursor + 1 < length and sql[cursor + 1] == closing:
                        value.append(closing)
                        cursor += 2
                        continue
                    closed = True
                    cursor += 1
                    break
                value.append(sql[cursor])
                cursor += 1
            if not closed:
                return None
            kind = "string" if character == "'" else "identifier"
            tokens.append((kind, "".join(value), True))
            index = cursor
            continue
        if character.isalpha() or character == "_":
            cursor = index + 1
            while cursor < length and (sql[cursor].isalnum() or sql[cursor] in "_$"):
                cursor += 1
            tokens.append(("word", sql[index:cursor], False))
            index = cursor
            continue
        if character.isdigit():
            cursor = index + 1
            while cursor < length and (sql[cursor].isdigit() or sql[cursor] in ".eE+-"):
                cursor += 1
            tokens.append(("word", sql[index:cursor], False))
            index = cursor
            continue
        tokens.append(("symbol", character, False))
        index += 1
    return tokens


def _split_sql_statements_strict(sql: str) -> list[list[_SqlToken]] | None:
    tokens = _lex_sql(sql)
    if tokens is None:
        return None
    statements: list[list[_SqlToken]] = []
    current: list[_SqlToken] = []
    depth = 0
    for token in tokens:
        value = token[1]
        if value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
            if depth < 0:
                return None
        if value == ";" and depth == 0:
            if not current:
                return None
            statements.append(current)
            current = []
        else:
            current.append(token)
    if depth != 0 or current:
        return None
    return statements


def _source_sql_tokens(sql: str) -> list[_SqlToken] | None:
    tokens = _lex_sql(sql)
    if tokens is None or any(token[1] == ";" for token in tokens):
        return None
    depth = 0
    for token in tokens:
        if token[1] == "(":
            depth += 1
        elif token[1] == ")":
            depth -= 1
            if depth < 0:
                return None
    return tokens if depth == 0 else None


def _token_word(token: _SqlToken | None) -> str | None:
    if token is None or token[0] not in {"word", "identifier"}:
        return None
    return token[1]


def _has_processing_partial_predicate(statement: list[_SqlToken]) -> bool:
    for index in range(len(statement) - 3):
        where = _token_word(statement[index])
        status = _token_word(statement[index + 1])
        if (
            where is not None
            and where.upper() == "WHERE"
            and status is not None
            and status.lower() == "status"
            and statement[index + 2][1] == "="
            and statement[index + 3][0] == "string"
            and statement[index + 3][1].lower() == "processing"
        ):
            return True
    return False


def _has_request_key_exact_check(statement: list[_SqlToken]) -> bool:
    expected = (
        ("word", "request_key"),
        ("word", "blob"),
        ("word", "not"),
        ("word", "null"),
        ("word", "primary"),
        ("word", "key"),
        ("word", "check"),
        ("symbol", "("),
        ("word", "typeof"),
        ("symbol", "("),
        ("word", "request_key"),
        ("symbol", ")"),
        ("symbol", "="),
        ("string", "blob"),
        ("word", "and"),
        ("word", "length"),
        ("symbol", "("),
        ("word", "request_key"),
        ("symbol", ")"),
        ("word", "between"),
        ("word", "1"),
        ("word", "and"),
        ("word", "256"),
        ("symbol", ")"),
    )
    width = len(expected)
    for index in range(len(statement) - width + 1):
        candidate = statement[index : index + width]
        if all(
            token[0] == kind and token[1].lower() == value and token[2] is (kind == "string")
            for token, (kind, value) in zip(candidate, expected)
        ):
            return True
    return False


def _target_from_tokens(tokens: list[_SqlToken], index: int) -> tuple[str, bool, bool, int] | None:
    if index >= len(tokens) or tokens[index][0] not in {"word", "identifier"}:
        return None
    target = tokens[index][1].lower()
    quoted = tokens[index][2]
    index += 1
    qualified = False
    if index + 1 < len(tokens) and tokens[index][1] == ".":
        if tokens[index + 1][0] not in {"word", "identifier"}:
            return None
        target = tokens[index + 1][1].lower()
        qualified = True
        index += 2
    return target, quoted, qualified, index


def _sql_write_target(
    tokens: list[_SqlToken],
) -> tuple[str, str, bool, bool, bool] | None:
    if not tokens:
        return None
    first = _token_word(tokens[0])
    if first is None:
        return None
    first_upper = first.upper()
    has_cte = first_upper == "WITH"
    depth = 0
    operation_index: int | None = None
    for index, token in enumerate(tokens):
        if token[1] == "(":
            depth += 1
        elif token[1] == ")":
            depth -= 1
        word = _token_word(token)
        if (
            depth == 0
            and word is not None
            and word.upper()
            in {
                "INSERT",
                "REPLACE",
                "UPDATE",
                "DELETE",
                "CREATE",
                "DROP",
                "ALTER",
            }
        ):
            operation_index = index
            break
    if operation_index is None:
        return None
    operation = _token_word(tokens[operation_index])
    if operation is None:
        return None
    operation = operation.upper()
    target_index = operation_index + 1
    if operation == "INSERT":
        if target_index < len(tokens) and (_token_word(tokens[target_index]) or "").upper() == "OR":
            target_index += 2
        if (
            target_index >= len(tokens)
            or (_token_word(tokens[target_index]) or "").upper() != "INTO"
        ):
            return None
        target_index += 1
    elif operation == "REPLACE":
        if (
            target_index >= len(tokens)
            or (_token_word(tokens[target_index]) or "").upper() != "INTO"
        ):
            return None
        target_index += 1
    elif operation == "UPDATE":
        pass
    elif operation == "DELETE":
        if (
            target_index >= len(tokens)
            or (_token_word(tokens[target_index]) or "").upper() != "FROM"
        ):
            return None
        target_index += 1
    elif operation in {"DROP", "ALTER"}:
        if target_index < len(tokens) and (_token_word(tokens[target_index]) or "").upper() in {
            "TABLE",
            "INDEX",
            "TRIGGER",
            "VIEW",
        }:
            target_index += 1
    elif operation == "CREATE":
        if target_index < len(tokens) and (_token_word(tokens[target_index]) or "").upper() in {
            "TEMP",
            "TEMPORARY",
            "UNIQUE",
        }:
            target_index += 1
        if target_index >= len(tokens) or (_token_word(tokens[target_index]) or "").upper() not in {
            "TABLE",
            "INDEX",
            "TRIGGER",
            "VIEW",
        }:
            return None
        target_index += 1
        if (
            target_index + 2 < len(tokens)
            and (_token_word(tokens[target_index]) or "").upper() == "IF"
            and (_token_word(tokens[target_index + 1]) or "").upper() == "NOT"
            and (_token_word(tokens[target_index + 2]) or "").upper() == "EXISTS"
        ):
            target_index += 3
    target = _target_from_tokens(tokens, target_index)
    if target is None:
        return None
    target_name, quoted, qualified, _ = target
    return operation, target_name, quoted, qualified, has_cte


def _sql_first_word(tokens: list[_SqlToken]) -> str | None:
    if not tokens:
        return None
    word = _token_word(tokens[0])
    return word.upper() if word is not None else None


def _is_exact_events_insert(sql: str) -> bool:
    tokens = _source_sql_tokens(sql)
    if tokens is None:
        return False
    into = _token_word(tokens[1]) if len(tokens) >= 2 else None
    return (
        len(tokens) >= 4
        and _sql_first_word(tokens) == "INSERT"
        and into is not None
        and into.upper() == "INTO"
        and tokens[2][0] == "word"
        and tokens[2][1].lower() == "events"
        and tokens[3][1] == "("
    )


def _is_actual_production_root(production_root: Path) -> bool:
    try:
        return production_root.resolve() == PRODUCTION_ROOT.resolve()
    except OSError, RuntimeError, ValueError:
        return False


def _literal_value(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _connect_call_is_exact(call: ast.Call, relative_path: str, qualified_name: str) -> bool:
    if (relative_path, qualified_name) not in CONNECT_ALLOWLIST:
        return False
    if (
        not isinstance(call.func, ast.Attribute)
        or call.func.attr != "connect"
        or _attribute_parts(call.func) != ("sqlite3", "connect")
        or len(call.args) != 1
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return False
    path_argument = call.args[0]
    if relative_path == RUNTIME_CONNECT_PATH:
        if _attribute_parts(path_argument) != ("self", "_path"):
            return False
    elif relative_path == MIGRATION_CONNECT_PATH:
        if not isinstance(path_argument, ast.Name) or path_argument.id != "path":
            return False
    else:
        return False
    values = {keyword.arg: _literal_value(keyword.value) for keyword in call.keywords}
    expected = {
        "timeout": 5.0,
        "isolation_level": None,
        "check_same_thread": True,
        "uri": False,
    }
    return values == expected and len(call.keywords) == len(expected)


def _strict_splitter_is_proven(tree: ast.Module) -> bool:
    # P1-01c proves this one production-shaped AST form; it does not build a
    # general control-flow graph for alternative splitters.
    splitter_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_split_sql_statements"
    ]
    all_splitter_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_split_sql_statements"
    ]
    if len(splitter_functions) != 1 or len(all_splitter_functions) != 1:
        return False
    splitter = splitter_functions[0]
    if (
        len(splitter.args.posonlyargs) != 0
        or len(splitter.args.args) != 1
        or splitter.args.args[0].arg != "sql"
        or splitter.args.vararg is not None
        or splitter.args.kwonlyargs
        or splitter.args.kwarg is not None
        or splitter.args.defaults
        or splitter.args.kw_defaults
        or len([node for node in ast.walk(splitter) if isinstance(node, ast.Return)]) != 1
        or len(splitter.body) != 5
    ):
        return False

    statements_init, buffer_init, loop, incomplete_guard, final_return = splitter.body
    if not (
        isinstance(statements_init, ast.AnnAssign)
        and isinstance(statements_init.target, ast.Name)
        and statements_init.target.id == "statements"
        and isinstance(statements_init.value, ast.List)
        and not statements_init.value.elts
    ):
        return False
    if not (
        isinstance(buffer_init, ast.Assign)
        and len(buffer_init.targets) == 1
        and isinstance(buffer_init.targets[0], ast.Name)
        and buffer_init.targets[0].id == "buffer"
        and isinstance(buffer_init.value, ast.Constant)
        and buffer_init.value.value == ""
    ):
        return False
    if not isinstance(loop, ast.For) or loop.orelse or len(loop.body) != 2:
        return False
    if not isinstance(loop.target, ast.Name) or loop.target.id != "line":
        return False
    line_split = loop.iter
    if not (
        isinstance(line_split, ast.Call)
        and isinstance(line_split.func, ast.Attribute)
        and line_split.func.attr == "splitlines"
        and isinstance(line_split.func.value, ast.Name)
        and line_split.func.value.id == "sql"
        and not line_split.args
        and len(line_split.keywords) == 1
        and line_split.keywords[0].arg == "keepends"
        and isinstance(line_split.keywords[0].value, ast.Constant)
        and line_split.keywords[0].value.value is True
    ):
        return False
    add_line, complete_guard = loop.body
    if not (
        isinstance(add_line, ast.AugAssign)
        and isinstance(add_line.target, ast.Name)
        and add_line.target.id == "buffer"
        and isinstance(add_line.op, ast.Add)
        and isinstance(add_line.value, ast.Name)
        and add_line.value.id == "line"
    ):
        return False
    if (
        not isinstance(complete_guard, ast.If)
        or complete_guard.orelse
        or len(complete_guard.body) != 3
    ):
        return False
    complete_test = complete_guard.test
    if not (
        isinstance(complete_test, ast.Call)
        and isinstance(complete_test.func, ast.Attribute)
        and _attribute_parts(complete_test.func) == ("sqlite3", "complete_statement")
        and len(complete_test.args) == 1
        and isinstance(complete_test.args[0], ast.Name)
        and complete_test.args[0].id == "buffer"
        and not complete_test.keywords
    ):
        return False
    statement_assign, append_statement, reset_buffer = complete_guard.body
    if not (
        isinstance(statement_assign, ast.Assign)
        and len(statement_assign.targets) == 1
        and isinstance(statement_assign.targets[0], ast.Name)
        and statement_assign.targets[0].id == "statement"
        and isinstance(statement_assign.value, ast.Call)
        and isinstance(statement_assign.value.func, ast.Attribute)
        and statement_assign.value.func.attr == "strip"
        and isinstance(statement_assign.value.func.value, ast.Name)
        and statement_assign.value.func.value.id == "buffer"
        and not statement_assign.value.args
        and not statement_assign.value.keywords
    ):
        return False
    if not (
        isinstance(append_statement, ast.If)
        and isinstance(append_statement.test, ast.Name)
        and append_statement.test.id == "statement"
        and not append_statement.orelse
        and len(append_statement.body) == 1
        and isinstance(append_statement.body[0], ast.Expr)
        and isinstance(append_statement.body[0].value, ast.Call)
        and isinstance(append_statement.body[0].value.func, ast.Attribute)
        and append_statement.body[0].value.func.attr == "append"
        and isinstance(append_statement.body[0].value.func.value, ast.Name)
        and append_statement.body[0].value.func.value.id == "statements"
        and len(append_statement.body[0].value.args) == 1
        and isinstance(append_statement.body[0].value.args[0], ast.Name)
        and append_statement.body[0].value.args[0].id == "statement"
        and not append_statement.body[0].value.keywords
    ):
        return False
    if not (
        isinstance(reset_buffer, ast.Assign)
        and len(reset_buffer.targets) == 1
        and isinstance(reset_buffer.targets[0], ast.Name)
        and reset_buffer.targets[0].id == "buffer"
        and isinstance(reset_buffer.value, ast.Constant)
        and reset_buffer.value.value == ""
    ):
        return False
    if not (
        isinstance(incomplete_guard, ast.If)
        and not incomplete_guard.orelse
        and len(incomplete_guard.body) == 1
        and isinstance(incomplete_guard.test, ast.Call)
        and isinstance(incomplete_guard.test.func, ast.Attribute)
        and incomplete_guard.test.func.attr == "strip"
        and isinstance(incomplete_guard.test.func.value, ast.Name)
        and incomplete_guard.test.func.value.id == "buffer"
        and not incomplete_guard.test.args
        and not incomplete_guard.test.keywords
        and isinstance(incomplete_guard.body[0], ast.Raise)
    ):
        return False
    return (
        isinstance(final_return, ast.Return)
        and isinstance(final_return.value, ast.Call)
        and isinstance(final_return.value.func, ast.Name)
        and final_return.value.func.id == "tuple"
        and len(final_return.value.args) == 1
        and isinstance(final_return.value.args[0], ast.Name)
        and final_return.value.args[0].id == "statements"
        and not final_return.value.keywords
    )


def _contains_without_nested_scope(parent: ast.AST, target: ast.AST) -> bool:
    for child in ast.iter_child_nodes(parent):
        if child is target:
            return True
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if _contains_without_nested_scope(child, target):
            return True
    return False


def _migration_loop_has_strict_statement_source(
    tree: ast.Module,
    execute_call: ast.Call | None = None,
) -> bool:
    if not _strict_splitter_is_proven(tree):
        return False
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function.name != "_run_migrations":
            continue
        for node in _walk_without_nested_scope(function):
            if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
                continue
            if node.target.id != "statement" or not isinstance(node.iter, ast.Call):
                continue
            if (
                not isinstance(node.iter.func, ast.Name)
                or node.iter.func.id != "_split_sql_statements"
                or len(node.iter.args) != 1
                or not isinstance(node.iter.args[0], ast.Attribute)
                or node.iter.args[0].attr != "sql"
                or not isinstance(node.iter.args[0].value, ast.Name)
                or node.iter.args[0].value.id != "spec"
            ):
                continue
            if execute_call is None:
                return True
            if _contains_without_nested_scope(node, execute_call):
                return True
    return False


def _joined_string_is_exact(
    node: ast.AST,
    prefix: str,
    formatted_name: str,
    suffix: str,
) -> bool:
    if not isinstance(node, ast.JoinedStr):
        return False
    expected_values = 2 if suffix == "" else 3
    if len(node.values) != expected_values:
        return False
    first, formatted = node.values[:2]
    return (
        isinstance(first, ast.Constant)
        and first.value == prefix
        and isinstance(formatted, ast.FormattedValue)
        and isinstance(formatted.value, ast.Name)
        and formatted.value.id == formatted_name
        and (
            suffix == ""
            or (isinstance(node.values[2], ast.Constant) and node.values[2].value == suffix)
        )
    )


def _dynamic_pragma_is_exact(node: ast.AST, qualified_name: str) -> bool:
    if qualified_name == "neontof.persistence.migrations._open_backup_connection":
        if _joined_string_is_exact(
            node,
            "PRAGMA busy_timeout=",
            "_BACKUP_BUSY_TIMEOUT_MILLISECONDS",
            "",
        ):
            return True
        return (
            isinstance(node, ast.IfExp)
            and isinstance(node.test, ast.Name)
            and node.test.id == "query_only"
            and _static_string(node.body) in {"PRAGMA query_only=ON"}
            and _static_string(node.orelse) in {"PRAGMA query_only=0"}
        )
    if qualified_name == "neontof.persistence.migrations._validate_schema_migrations_shape":
        if not isinstance(node, ast.JoinedStr) or len(node.values) != 3:
            return False
        first, formatted, last = node.values
        return (
            isinstance(first, ast.Constant)
            and first.value == "PRAGMA index_xinfo("
            and isinstance(formatted, ast.FormattedValue)
            and isinstance(formatted.value, ast.Call)
            and isinstance(formatted.value.func, ast.Name)
            and formatted.value.func.id == "_quote_identifier"
            and len(formatted.value.args) == 1
            and isinstance(formatted.value.args[0], ast.Name)
            and formatted.value.args[0].id == "index_name"
            and isinstance(last, ast.Constant)
            and last.value == ")"
        )
    return False


def _pragma_signature(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
) -> str | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "execute" or not call.args:
        return None
    argument = call.args[0]
    sql = _static_string(argument)
    if sql is not None:
        parts = _pragma_parts(sql)
        if parts is not None:
            name, value = parts
            return name if value is None else f"{name}={value}"
        if (
            record.relative_path == MIGRATION_CONNECT_PATH
            and qualified_name == "neontof.persistence.migrations._validate_schema_migrations_shape"
            and sql
            in {
                "PRAGMA table_info(schema_migrations)",
                "PRAGMA index_list(schema_migrations)",
            }
        ):
            return sql.removeprefix("PRAGMA ").replace("(", "=").removesuffix(")")
        return None
    if not _dynamic_pragma_is_exact(argument, qualified_name):
        return None
    if qualified_name == MIGRATION_CONNECT_QUALIFIED_NAME:
        if _joined_string_is_exact(
            argument,
            "PRAGMA busy_timeout=",
            "_BACKUP_BUSY_TIMEOUT_MILLISECONDS",
            "",
        ):
            return "busy_timeout=<dynamic>"
        return "query_only=<dynamic>"
    return "index_xinfo=<dynamic>"


def _sql_contains_load_extension(tokens: list[_SqlToken]) -> bool:
    return any(
        token[0] in {"word", "identifier"} and token[1].upper() == "LOAD_EXTENSION"
        for token in tokens
    )


def _query_bounded_sql_argument_is_safe(argument: ast.AST) -> bool:
    sql = _static_string(argument)
    if sql is not None:
        tokens = _source_sql_tokens(sql)
        if (
            tokens is None
            or _sql_first_word(tokens) not in {"SELECT", "EXPLAIN", "VALUES"}
            or _sql_contains_load_extension(tokens)
            or _sql_write_target(tokens) is not None
        ):
            return False
        if any(
            token[0] in {"word", "identifier"}
            and token[1].lower() in {"sqlite_master", "sqlite_schema"}
            for token in tokens
        ):
            return sql == (
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )
        return True
    if not isinstance(argument, ast.JoinedStr):
        return False
    if any(
        _joined_string_is_exact(argument, prefix, "quoted_table", suffix)
        for prefix, suffix in (
            ("PRAGMA table_info(", ")"),
            ("PRAGMA index_list(", ")"),
            ("SELECT * FROM ", ""),
        )
    ):
        return True
    if len(argument.values) != 3:
        return False
    first, formatted, last = argument.values
    return (
        isinstance(first, ast.Constant)
        and first.value == "PRAGMA index_xinfo("
        and isinstance(formatted, ast.FormattedValue)
        and isinstance(formatted.value, ast.Call)
        and isinstance(formatted.value.func, ast.Name)
        and formatted.value.func.id == "_quote_identifier"
        and len(formatted.value.args) == 1
        and isinstance(formatted.value.args[0], ast.Name)
        and formatted.value.args[0].id == "index_name"
        and isinstance(last, ast.Constant)
        and last.value == ")"
    )


def _query_bounded_call_is_exact(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
) -> bool:
    if (
        record.relative_path != MIGRATION_CONNECT_PATH
        or qualified_name != "neontof.persistence.migrations._database_snapshot"
        or not isinstance(call.func, ast.Name)
        or call.func.id != "_query_bounded"
        or len(call.args) != 2
        or not isinstance(call.args[0], ast.Name)
        or call.args[0].id != "connection"
        or len(call.keywords) != 3
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return False
    keyword_names = {keyword.arg for keyword in call.keywords}
    if keyword_names != {"start", "deadline_seconds", "monotonic"}:
        return False
    return all(
        isinstance(keyword.value, ast.Name) and keyword.value.id == keyword.arg
        for keyword in call.keywords
    ) and _query_bounded_sql_argument_is_safe(call.args[1])


def _query_bounded_callers_are_exact(record: _SourceRecord) -> bool:
    query_calls = [
        (call, qualified_name)
        for call, qualified_name in record.visitor.calls
        if isinstance(call.func, ast.Name) and call.func.id == "_query_bounded"
    ]
    expected_count = ALLOWED_SQLITE_CALLBACK_CALL_COUNTS.get(
        (
            MIGRATION_CONNECT_PATH,
            "neontof.persistence.migrations._database_snapshot",
            "_query_bounded",
        ),
        0,
    )
    return len(query_calls) == expected_count and all(
        _query_bounded_call_is_exact(record, call, qualified_name)
        for call, qualified_name in query_calls
    )


def _query_bounded_dynamic_execute_is_exact(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
) -> bool:
    if (
        record.relative_path != MIGRATION_CONNECT_PATH
        or qualified_name != "neontof.persistence.migrations._query_bounded"
    ):
        return False
    execute_calls = [
        candidate
        for candidate, candidate_qualified_name in record.visitor.calls
        if (
            candidate_qualified_name == qualified_name
            and isinstance(candidate.func, ast.Attribute)
            and candidate.func.attr == "execute"
        )
    ]
    return len(execute_calls) == 1 and execute_calls[0] is call


def _dynamic_sql_is_allowed(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
) -> bool:
    if not call.args:
        return False
    argument = call.args[0]
    if (
        record.relative_path == MIGRATION_CONNECT_PATH
        and qualified_name == "neontof.persistence.migrations._query_bounded"
        and isinstance(argument, ast.Name)
        and argument.id == "sql"
        and len(call.args) == 1
        and not call.keywords
        and _query_bounded_dynamic_execute_is_exact(record, call, qualified_name)
        and _query_bounded_callers_are_exact(record)
    ):
        return True
    if (
        record.relative_path == MIGRATION_CONNECT_PATH
        and qualified_name == "neontof.persistence.migrations._run_migrations"
        and isinstance(argument, ast.Name)
        and argument.id == "statement"
        and _migration_loop_has_strict_statement_source(record.tree, call)
    ):
        return True
    if (
        record.relative_path == "src/neontof/persistence/observation_store.py"
        and qualified_name
        == "neontof.persistence.observation_store.ObservationStore.read_telemetry"
        and isinstance(argument, ast.BinOp)
    ):
        return (
            isinstance(argument.op, ast.Add)
            and isinstance(argument.left, ast.Name)
            and argument.left.id == "select"
            and _static_string(argument.right)
            in {
                "WHERE campaign_id = ? ORDER BY append_sequence",
                "WHERE campaign_id = ? AND turn_id = ? ORDER BY append_sequence",
            }
        )
    if (
        record.relative_path == "src/neontof/persistence/observation_store.py"
        and qualified_name == "neontof.persistence.observation_store._next_sequence"
        and isinstance(argument, ast.JoinedStr)
    ):
        return _joined_string_is_exact(
            argument,
            "SELECT COALESCE(MAX(append_sequence), 0) FROM ",
            "table",
            " WHERE campaign_id = ?",
        )
    if record.relative_path == MIGRATION_CONNECT_PATH and qualified_name in {
        "neontof.persistence.migrations._open_backup_connection",
        "neontof.persistence.migrations._validate_schema_migrations_shape",
    }:
        return _dynamic_pragma_is_exact(argument, qualified_name)
    return False


def _strict_transaction_token(sql: str) -> str | None:
    if sql != sql.strip():
        sql = sql.strip()
    if sql in {"ROLLBACK", "COMMIT", "BEGIN IMMEDIATE"}:
        return sql
    return None


def _pragma_parts(sql: str) -> tuple[str, str | None] | None:
    tokens = _source_sql_tokens(sql)
    if tokens is None:
        return None
    if _sql_first_word(tokens) != "PRAGMA" or len(tokens) < 2:
        return None
    if tokens[1][2]:
        return None
    name = _token_word(tokens[1])
    if name is None:
        return None
    if len(tokens) == 2:
        return name.lower(), None
    if len(tokens) < 4 or tokens[2][1] != "=":
        return None
    if any(token[2] for token in tokens[3:]):
        return None
    value = "".join(token[1] for token in tokens[3:]).lower()
    return name.lower(), value


def _pragma_is_allowed(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
    sql: str | None,
) -> bool:
    if sql is None:
        return _dynamic_sql_is_allowed(record, call, qualified_name)
    if (
        record.relative_path == MIGRATION_CONNECT_PATH
        and qualified_name == "neontof.persistence.migrations._validate_schema_migrations_shape"
        and sql
        in {
            "PRAGMA table_info(schema_migrations)",
            "PRAGMA index_list(schema_migrations)",
        }
    ):
        return True
    parts = _pragma_parts(sql)
    if parts is None:
        return False
    name, value = parts
    if record.relative_path == RUNTIME_CONNECT_PATH:
        if qualified_name == RUNTIME_CONNECT_QUALIFIED_NAME:
            return (name, value) in {
                ("busy_timeout", "5000"),
                ("busy_timeout", None),
                ("synchronous", "full"),
                ("synchronous", None),
                ("query_only", "0"),
                ("query_only", None),
            }
        if qualified_name == "neontof.persistence.sqlite_database.SqliteDatabase._read":
            return (name, value) in {("query_only", "on"), ("query_only", None)}
    if record.relative_path == MIGRATION_CONNECT_PATH:
        if qualified_name == MIGRATION_CONNECT_QUALIFIED_NAME:
            return (name, value) in {
                ("busy_timeout", None),
                ("query_only", None),
                ("synchronous", "full"),
                ("synchronous", None),
            }
        if qualified_name == "neontof.persistence.migrations._connection_main_file":
            return (name, value) == ("database_list", None)
        if qualified_name == "neontof.persistence.migrations._read_journal_mode":
            return (name, value) == ("journal_mode", None)
        if qualified_name == "neontof.persistence.migrations._run_migrations":
            return (name, value) == ("journal_mode", "wal")
    return False


def _known_callback_call(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if isinstance(call.func, ast.Name):
        callback_name = call.func.id
        allowed_names = ALLOWED_SQLITE_CALLBACK_CALLS.get(
            (record.relative_path, qualified_name), frozenset()
        )
        if callback_name not in allowed_names:
            return False
        if any(keyword.arg is None for keyword in call.keywords):
            return False
        keyword_names = {keyword.arg for keyword in call.keywords}

        def known_connection_argument(index: int) -> bool:
            if len(call.args) <= index:
                return False
            argument = call.args[index]
            return isinstance(argument, ast.Name) and argument.id in visitor.known_connection_names

        if callback_name in {
            "_connection_main_file",
            "_read_journal_mode",
            "_rollback",
            "operation",
        }:
            return len(call.args) == 1 and not keyword_names and known_connection_argument(0)
        if callback_name == "_validate_migration_database_identity":
            return len(call.args) == 2 and not keyword_names and known_connection_argument(0)
        if callback_name == "_fetch_bounded":
            return (
                len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id in visitor.known_cursor_names
                and keyword_names == {"start", "deadline_seconds", "monotonic"}
            )
        if callback_name in {"_query_bounded", "_database_snapshot"}:
            if callback_name == "_query_bounded":
                return (
                    len(call.args) == 2
                    and known_connection_argument(0)
                    and keyword_names == {"start", "deadline_seconds", "monotonic"}
                    and _query_bounded_call_is_exact(record, call, qualified_name)
                )
            return (
                len(call.args) == 1
                and known_connection_argument(0)
                and keyword_names == {"start", "deadline_seconds", "monotonic"}
            )
        if callback_name == "_verify_backup":
            return (
                len(call.args) == 2
                and known_connection_argument(0)
                and keyword_names == {"expected_journal_mode"}
            )
        if callback_name == "_is_same_file_database":
            return (
                len(call.args) == 3
                and not keyword_names
                and all(
                    isinstance(argument, ast.Name) and argument.id in visitor.known_connection_names
                    for argument in call.args[:2]
                )
            )
        if callback_name == "_copy_database_with_deadline":
            return (
                len(call.args) == 2
                and not keyword_names
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "backup_source"
                and isinstance(call.args[1], ast.Name)
                and call.args[1].id == "destination"
            )
        if callback_name == "_run_migrations":
            return len(call.args) == 2 and not keyword_names and known_connection_argument(0)
        if callback_name in {"_schema_migrations_exists", "_validate_schema_migrations_shape"}:
            return len(call.args) == 1 and not keyword_names and known_connection_argument(0)
        if callback_name in {"_read_applied_migrations", "_has_existing_schema_or_data"}:
            return len(call.args) == 1 and not keyword_names and known_connection_argument(0)
        if callback_name == "_backup_existing_database":
            return len(call.args) == 2 and not keyword_names and known_connection_argument(0)
        if callback_name == "_next_sequence":
            return len(call.args) == 3 and not keyword_names and known_connection_argument(0)
        return False
    if isinstance(call.func, ast.Attribute) and call.func.attr == "_read_campaign_on_connection":
        return (
            (
                (
                    (record.relative_path, qualified_name) in SAME_CONNECTION_READER_ALLOWLIST
                    and _receiver_terminal_name(call.func.value) == "_event_store"
                )
                or (
                    record.relative_path == EVENT_DML_PATH
                    and qualified_name == "neontof.persistence.event_store.EventStore.read_campaign"
                    and _receiver_terminal_name(call.func.value) == "self"
                )
            )
            and len(call.args) == 2
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in visitor.known_connection_names
            and isinstance(call.args[1], ast.Name)
            and call.args[1].id == "campaign_id"
        )
    return False


def _lambda_contains_database_operation(node: ast.Lambda) -> bool:
    for child in ast.walk(node.body):
        if isinstance(child, ast.Attribute) and child.attr in SQLITE_SINK_METHOD_NAMES:
            return True
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id in {"getattr", "setattr", "delattr"}
        ):
            return True
    return False


def _call_contains_known_database_object(
    node: ast.AST,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if isinstance(node, ast.Name):
        return (
            node.id in visitor.known_connection_names
            or node.id in visitor.known_cursor_names
            or node.id in visitor.known_blob_names
        )
    if isinstance(node, ast.Lambda):
        return _lambda_contains_database_operation(node)
    return any(
        _call_contains_known_database_object(child, visitor) for child in ast.iter_child_nodes(node)
    )


def _value_is_database_handle(node: ast.AST, visitor: _SqliteUsageVisitor) -> bool:
    if isinstance(node, ast.Name):
        return (
            node.id in visitor.known_connection_names
            or node.id in visitor.known_cursor_names
            or node.id in visitor.known_blob_names
        )
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    return node.func.attr in {"execute", "cursor", "blobopen"} and _receiver_is_known_connection(
        node.func.value, visitor
    )


def _contains_direct_database_handle(node: ast.AST, visitor: _SqliteUsageVisitor) -> bool:
    if _value_is_database_handle(node, visitor):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_contains_direct_database_handle(element, visitor) for element in node.elts)
    if isinstance(node, ast.Dict):
        return any(
            _contains_direct_database_handle(element, visitor)
            for element in (*node.keys, *node.values)
            if element is not None
        )
    return False


def _call_passes_database_handle(call: ast.Call, visitor: _SqliteUsageVisitor) -> bool:
    return any(
        _value_is_database_handle(argument, visitor)
        or (isinstance(argument, ast.Lambda) and _lambda_contains_database_operation(argument))
        for argument in call.args
    )


def _assignment_escapes_database_handle(
    target: ast.AST,
    value: ast.AST,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if not _contains_direct_database_handle(value, visitor):
        return False
    return not (isinstance(target, ast.Name) and _value_is_database_handle(value, visitor))


def _ast_parent_map(node: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(node):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _handle_close_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef, name: str
) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "close"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        )
    ]


def _handle_name_load_is_allowed(
    record: _SourceRecord,
    node: ast.Name,
    parent: ast.AST | None,
    kind: str,
    qualified_name: str,
    final_node_ids: set[int],
    parents: dict[int, ast.AST],
    visitor: _SqliteUsageVisitor,
) -> bool:
    if isinstance(parent, ast.Attribute) and parent.value is node:
        call = parents.get(id(parent))
        if not isinstance(call, ast.Call) or call.func is not parent:
            return False
        if parent.attr == "close":
            return id(call) in final_node_ids and not call.args and not call.keywords
        if kind == "cursor":
            return _cursor_call_is_bounded(call, parent.attr)
        return parent.attr in SQLITE_BLOB_READ_METHOD_NAMES and parent.attr != "close"
    if isinstance(parent, ast.Subscript) and parent.value is node:
        return kind == "blob" and isinstance(parent.ctx, ast.Load)
    if isinstance(parent, ast.Call) and node in parent.args:
        return isinstance(parent.func, ast.Name) and _known_callback_call(
            record, parent, qualified_name, visitor
        )
    return False


def _opening_has_exact_lifetime(
    record: _SourceRecord,
    qualified_name: str,
    name: str,
    kind: str,
    assignment: ast.Assign | ast.AnnAssign,
) -> bool:
    # The accepted lifetime is intentionally syntactic: open, immediate try,
    # and one final close.  Context-manager, conditional-open, and exception-
    # path inference are outside the P1-01c scanner boundary.
    function = record.visitor.function_nodes.get(qualified_name)
    if function is None or assignment not in function.body:
        return False
    assignment_index = function.body.index(assignment)
    if assignment_index + 1 >= len(function.body):
        return False
    try_node = function.body[assignment_index + 1]
    if not isinstance(try_node, ast.Try) or try_node.handlers or try_node.orelse:
        return False
    if len(try_node.finalbody) != 1:
        return False
    final_statement = try_node.finalbody[0]
    if not isinstance(final_statement, ast.Expr):
        return False
    final_close = final_statement.value
    if not (
        isinstance(final_close, ast.Call)
        and isinstance(final_close.func, ast.Attribute)
        and final_close.func.attr == "close"
        and isinstance(final_close.func.value, ast.Name)
        and final_close.func.value.id == name
        and not final_close.args
        and not final_close.keywords
    ):
        return False
    close_calls = _handle_close_calls(function, name)
    if len(close_calls) != 1 or close_calls[0] is not final_close:
        return False
    final_node_ids = {id(final_close)}
    nested_scope_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )
    for child in ast.walk(try_node):
        if isinstance(child, nested_scope_types) and any(
            isinstance(descendant, ast.Name)
            and isinstance(descendant.ctx, ast.Load)
            and descendant.id == name
            for descendant in ast.walk(child)
        ):
            return False
    allowed_node_ids = {
        id(child)
        for statement in (*try_node.body, *try_node.finalbody)
        for child in ast.walk(statement)
    }
    parents = _ast_parent_map(function)
    for child in ast.walk(function):
        if not (
            isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name
        ):
            continue
        if id(child) not in allowed_node_ids:
            return False
        if not _handle_name_load_is_allowed(
            record,
            child,
            parents.get(id(child)),
            kind,
            qualified_name,
            final_node_ids,
            parents,
            record.visitor,
        ):
            return False
    return True


def _database_handle_lifetime_is_exact(record: _SourceRecord) -> bool:
    visitor = record.visitor
    if visitor.handle_alias_bindings:
        return False
    for qualified_name, _ in visitor.borrowed_cursor_bindings:
        # _fetch_bounded is the existing production callback whose caller owns
        # the cursor; its direct call position is checked by the caller shape.
        if not (
            record.relative_path == MIGRATION_CONNECT_PATH
            and qualified_name == "neontof.persistence.migrations._fetch_bounded"
        ):
            return False
    if visitor.borrowed_blob_bindings:
        return False
    opening_keys: set[tuple[str, str]] = set()
    for qualified_name, name, kind, assignment in visitor.open_handle_assignments:
        key = (qualified_name, name)
        if key in opening_keys or visitor.open_handle_bindings.get(key) != kind:
            return False
        opening_keys.add(key)
        if not _opening_has_exact_lifetime(record, qualified_name, name, kind, assignment):
            return False
    return True


def _database_operation_call_is_exact(
    record: _SourceRecord,
    call: ast.Call,
    qualified_name: str,
) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"_read", "_write"}:
        return False
    if (
        _receiver_terminal_name(call.func.value) != "_database"
        or (record.relative_path, qualified_name, call.func.attr)
        not in DATABASE_OPERATION_ALLOWLIST
        or len(call.args) != 1
        or call.keywords
    ):
        return False
    argument = call.args[0]
    return (isinstance(argument, ast.Name) and argument.id in {"operation"}) or isinstance(
        argument, ast.Lambda
    )


def _function_definition(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _walk_without_nested_scope(node: ast.AST) -> Iterable[ast.AST]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield child
        yield from _walk_without_nested_scope(child)


def _backup_helper_is_exact(record: _SourceRecord) -> bool:
    if (
        record.relative_path != MIGRATION_CONNECT_PATH
        or "neontof.persistence.migrations._copy_database_with_deadline"
        not in record.visitor.function_names
    ):
        return False
    function = _function_definition(record.tree, "_copy_database_with_deadline")
    if function is None:
        return False
    argument_names = {
        argument.arg
        for argument in (
            tuple(function.args.posonlyargs)
            + tuple(function.args.args)
            + tuple(function.args.kwonlyargs)
        )
    }
    if not {"deadline_seconds", "monotonic"} <= argument_names:
        return False
    progress_functions = [
        node
        for node in function.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "progress"
    ]
    if len(progress_functions) != 1:
        return False
    progress = progress_functions[0]
    progress_arguments = tuple(argument.arg for argument in progress.args.posonlyargs) + tuple(
        argument.arg for argument in progress.args.args
    )
    if progress_arguments != ("status", "remaining", "total") or (
        progress.args.kwonlyargs
        or progress.args.vararg is not None
        or progress.args.kwarg is not None
    ):
        return False

    def is_deadline_check(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_check_deadline"
            and len(node.args) == 3
            and not node.keywords
            and all(
                isinstance(argument, ast.Name) and argument.id == expected
                for argument, expected in zip(
                    node.args, ("start", "deadline_seconds", "monotonic"), strict=True
                )
            )
        )

    progress_checks = sum(is_deadline_check(node) for node in ast.walk(progress))
    outer_checks = sum(is_deadline_check(node) for node in _walk_without_nested_scope(function))
    has_monotonic_call = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "monotonic"
        and not node.args
        and not node.keywords
        for node in _walk_without_nested_scope(function)
    )
    return progress_checks == 1 and outer_checks >= 1 and has_monotonic_call


def _backup_existing_database_flow_is_exact(record: _SourceRecord) -> bool:
    if (
        record.relative_path != MIGRATION_CONNECT_PATH
        or "neontof.persistence.migrations._backup_existing_database"
        not in record.visitor.function_names
    ):
        return True
    function = _function_definition(record.tree, "_backup_existing_database")
    if function is None:
        return False
    calls_by_name: dict[str, list[int]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls_by_name.setdefault(node.func.id, []).append(node.lineno)
    if (
        len(calls_by_name.get("_copy_database_with_deadline", [])) != 1
        or len(calls_by_name.get("_verify_backup", [])) != 1
        or len(calls_by_name.get("_promote_backup_artifacts", [])) != 1
        or len(calls_by_name.get("_existing_artifact_paths", [])) != 2
    ):
        return False
    copy_line = calls_by_name["_copy_database_with_deadline"][0]
    verify_line = calls_by_name["_verify_backup"][0]
    promote_line = calls_by_name["_promote_backup_artifacts"][0]
    return copy_line < verify_line < promote_line


def _call_uses_higher_order_factory(
    call: ast.Call,
    visitor: _SqliteUsageVisitor,
) -> bool:
    names = visitor.higher_order_names | SQLITE_HIGHER_ORDER_NAME_NAMES
    for node in ast.walk(call.func):
        if isinstance(node, ast.Name) and node.id in names:
            return True
        if isinstance(node, ast.Attribute):
            parts = _attribute_parts(node)
            if (
                parts is not None
                and parts[0] in visitor.higher_order_module_names
                and parts[-1] in SQLITE_HIGHER_ORDER_NAME_NAMES
            ):
                return True
    return False


def _context_uses_database_object(
    record: _SourceRecord,
    context: ast.AST,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if (
        _receiver_is_known_connection(context, visitor)
        or _receiver_is_known_cursor(context, visitor)
        or _receiver_is_known_blob(context, visitor)
    ):
        return True
    if (
        isinstance(context, ast.Call)
        and isinstance(context.func, ast.Attribute)
        and _is_sqlite_module_call(context, "connect", visitor)
    ):
        return True
    if (
        isinstance(context, ast.Call)
        and isinstance(context.func, ast.Attribute)
        and (
            (
                record.relative_path == RUNTIME_CONNECT_PATH
                and context.func.attr == "_open_connection"
            )
            or (
                record.relative_path == MIGRATION_CONNECT_PATH
                and context.func.attr == "_open_backup_connection"
            )
        )
    ):
        return True
    return _call_contains_known_database_object(context, visitor)


def _receiver_terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _append_receiver_is_direct_event_store_constructor(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "append"
        and isinstance(call.func.value, ast.Call)
        and _receiver_terminal_name(call.func.value.func) == "EventStore"
    )


def _call_keyword(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _cursor_call_is_bounded(call: ast.Call, method: str) -> bool:
    if call.keywords:
        return False
    if method in {"close", "fetchall", "fetchone"}:
        return not call.args
    if method == "fetchmany":
        if len(call.args) != 1:
            return False
        size = call.args[0]
        return _literal_value(size) == 256 or (
            isinstance(size, ast.Name) and size.id == "_BACKUP_VERIFY_BATCH_SIZE"
        )
    return False


def _backup_call_is_exact(
    record: _SourceRecord,
    call: ast.Call,
    visitor: _SqliteUsageVisitor,
) -> bool:
    if (
        not _backup_helper_is_exact(record)
        or not isinstance(call.func, ast.Attribute)
        or call.func.attr != "backup"
        or _receiver_terminal_name(call.func.value) != "source"
        or _root_name(call.func.value) not in visitor.known_backup_source_names
        or len(call.args) != 1
        or not isinstance(call.args[0], ast.Name)
        or call.args[0].id != "destination"
        or call.args[0].id not in visitor.known_connection_names
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return False
    values = {keyword.arg: keyword.value for keyword in call.keywords}
    if set(values) != {"pages", "sleep", "name", "progress"} or len(call.keywords) != 4:
        return False
    pages = values["pages"]
    sleep = values["sleep"]
    name = values["name"]
    progress = values["progress"]
    return (
        (
            _literal_value(pages) == 256
            or (isinstance(pages, ast.Name) and pages.id == "_BACKUP_PAGES_PER_STEP")
        )
        and (
            _literal_value(sleep) == 0.05
            or (isinstance(sleep, ast.Name) and sleep.id == "_BACKUP_RETRY_SLEEP_SECONDS")
        )
        and _literal_value(name) == "main"
        and isinstance(progress, ast.Name)
        and progress.id == "progress"
    )


def _storage_dml_is_allowed(record: _SourceRecord, qualified_name: str, sql: str) -> bool:
    tokens = _source_sql_tokens(sql)
    if tokens is None:
        return False
    if _sql_contains_load_extension(tokens):
        return False
    parsed = _sql_write_target(tokens)
    if parsed is None:
        first = _sql_first_word(tokens)
        return first in {"SELECT", "EXPLAIN", "VALUES"}
    operation, target, quoted, qualified, has_cte = parsed
    if operation not in {"INSERT", "REPLACE", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
        return False
    if has_cte or target in {"sqlite_master", "sqlite_schema"}:
        return False
    if target == "events":
        return (
            record.relative_path == EVENT_DML_PATH
            and qualified_name == EVENT_DML_QUALIFIED_NAME
            and operation == "INSERT"
            and not quoted
            and not qualified
            and _is_exact_events_insert(sql)
        )
    allowed_locations = {
        (
            "src/neontof/persistence/projection_store.py",
            "neontof.persistence.projection_store.ProjectionStore.rebuild.<locals>.operation",
            "projection_snapshots",
        ),
        (
            "src/neontof/persistence/projection_store.py",
            "neontof.persistence.projection_store.ProjectionStore.delete.<locals>.operation",
            "projection_snapshots",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.append_transcript.<locals>.operation",
            "transcript_entries",
        ),
        (
            "src/neontof/persistence/observation_store.py",
            "neontof.persistence.observation_store.ObservationStore.append_telemetry.<locals>.operation",
            "telemetry_entries",
        ),
        (
            "src/neontof/persistence/migrations.py",
            "neontof.persistence.migrations._run_migrations",
            "schema_migrations",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.claim.<locals>.operation",
            "turn_requests",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.stage_recovery_metadata.<locals>.operation",
            "turn_requests",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.stage.<locals>.operation",
            "turn_requests",
        ),
        (
            "src/neontof/persistence/turn_request_store.py",
            "neontof.persistence.turn_request_store.TurnRequestStore.complete.<locals>.operation",
            "turn_requests",
        ),
    }
    return (
        (
            record.relative_path,
            qualified_name,
            target,
        )
        in allowed_locations
        and not quoted
        and not qualified
        and operation
        in {
            "INSERT",
            "UPDATE",
            "DELETE",
        }
    )


def _is_allowed_projection_snapshot_write(
    record: _SourceRecord,
    qualified_name: str,
    sql: str,
) -> bool:
    if not _storage_dml_is_allowed(record, qualified_name, sql):
        return False
    tokens = _source_sql_tokens(sql)
    parsed = _sql_write_target(tokens) if tokens is not None else None
    return parsed is not None and parsed[1] == "projection_snapshots"


def _source_has_exact_non_sql_getattr(record: _SourceRecord) -> bool:
    counts: dict[tuple[str, str], int] = {}
    for _, qualified_name in record.visitor.getattr_calls:
        key = (record.relative_path, qualified_name)
        counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        if GETATTR_ALLOWLIST.get(key) != count:
            return False
    return True


def _source_has_only_non_sql_allowlist(record: _SourceRecord) -> bool:
    visitor = record.visitor
    if (
        visitor.uses_sqlite
        or visitor.invalid_sqlite_import
        or visitor.sqlite_rebound
        or visitor.sqlite_module_attributes
        or visitor.indirect_database_alias
        or any(
            _context_uses_database_object(record, context, visitor)
            for context, _ in visitor.context_expressions
        )
    ):
        return False
    if any(
        _call_contains_known_database_object(call, visitor)
        for call, _ in visitor.higher_order_calls
    ):
        return False
    for call, qualified_name in visitor.calls:
        if isinstance(call.func, ast.Name) and call.func.id == "getattr":
            if GETATTR_ALLOWLIST.get((record.relative_path, qualified_name)) is None:
                return False
        elif isinstance(call.func, ast.Name) and (
            call.func.id in {"setattr", "delattr"}
            or call.func.id in visitor.higher_order_names
            or call.func.id in SQLITE_HIGHER_ORDER_NAME_NAMES
        ):
            return False
        elif (
            isinstance(call.func, ast.Attribute)
            and _attribute_parts(call.func) == ("object", "__setattr__")
            and (record.relative_path, qualified_name) in OBJECT_SETATTR_ALLOWLIST
        ):
            continue
        elif (
            isinstance(call.func, ast.Attribute)
            and (
                call.func.attr in SQLITE_SINK_METHOD_NAMES
                or call.func.attr in {"setitem", "delitem"}
                or call.func.attr in SQLITE_HIGHER_ORDER_METHOD_NAMES
                or call.func.attr in {"execute", "cursor", "blobopen", "backup"}
            )
        ) or (
            isinstance(call.func, ast.Call)
            and _call_uses_higher_order_factory(call, visitor)
            and _call_contains_known_database_object(call, visitor)
        ):
            return False
    return _source_has_exact_non_sql_getattr(record)


def _source_file_has_violation(record: _SourceRecord) -> bool:
    visitor = record.visitor
    path_parts = record.relative_path.split("/")
    is_persistence = (
        len(path_parts) > 2
        and path_parts[:2] == ["src", "neontof"]
        and path_parts[2] == "persistence"
    )
    if not is_persistence:
        if _source_has_only_non_sql_allowlist(record):
            return False
        return visitor.uses_sqlite or visitor.has_potential_sink or visitor.invalid_sqlite_import

    if (
        visitor.invalid_sqlite_import
        or visitor.dynamic_sqlite_import_calls
        or visitor.dynamic_import_rebound
        or visitor.sqlite_rebound
        or visitor.unsafe_database_rebind
        or visitor.unsafe_database_escape
        or visitor.indirect_database_alias
        or visitor.unsafe_event_store_rebind
        or visitor.cross_module_method_alias_rebound
    ):
        return True

    if visitor.cross_module_method_aliases:
        return True

    for node, qualified_name in (*visitor.return_nodes, *visitor.yield_nodes):
        if (
            node.value is not None
            and _value_is_database_handle(node.value, visitor)
            and not (
                isinstance(node.value, ast.Name)
                and node.value.id == "connection"
                and qualified_name
                in {RUNTIME_CONNECT_QUALIFIED_NAME, MIGRATION_CONNECT_QUALIFIED_NAME}
            )
        ):
            return True

    if not _database_handle_lifetime_is_exact(record):
        return True

    for name in visitor.opened_cursor_names:
        if visitor.cursor_close_counts.get(name, 0) != 1:
            return True
    for name in visitor.opened_blob_names:
        if visitor.blob_close_counts.get(name, 0) != 1:
            return True

    if (
        record.relative_path == MIGRATION_CONNECT_PATH
        and "neontof.persistence.migrations._backup_existing_database" in visitor.function_names
        and not _backup_existing_database_flow_is_exact(record)
    ):
        return True

    for context, _ in visitor.context_expressions:
        if _context_uses_database_object(record, context, visitor):
            return True
    if visitor.higher_order_calls:
        return True

    module_call_functions = {id(call.func) for call, _, _ in visitor.sqlite_module_calls}
    for attribute, _ in visitor.sqlite_module_attributes:
        parts = _attribute_parts(attribute)
        if (
            parts is None
            or parts[0] != "sqlite3"
            or parts[-1]
            not in {
                *SQLITE_MODULE_REFERENCE_NAMES,
                "connect",
            }
        ):
            return True
        if parts[-1] == "connect" and id(attribute) not in module_call_functions:
            return True

    for call, attribute_name, qualified_name in visitor.sqlite_module_calls:
        if attribute_name not in SQLITE_MODULE_REFERENCE_NAMES and attribute_name != "connect":
            return True
        if attribute_name == "connect" and not _connect_call_is_exact(
            call, record.relative_path, qualified_name
        ):
            return True
        if attribute_name in {"Connection", "Cursor", "Blob"}:
            return True
    connect_counts: dict[tuple[str, str], int] = {}
    for call, attribute_name, qualified_name in visitor.sqlite_module_calls:
        if attribute_name == "connect":
            key = (record.relative_path, qualified_name)
            connect_counts[key] = connect_counts.get(key, 0) + 1
    if any(count != 1 and key in CONNECT_ALLOWLIST for key, count in connect_counts.items()):
        return True

    if not _source_has_exact_non_sql_getattr(record):
        return True

    for attribute, qualified_name in visitor.attribute_stores:
        receiver = _receiver_terminal_name(attribute.value)
        if receiver in {
            "connection",
            "migration_connection",
            "backup_source",
            "destination",
            "reopen",
            "blob",
            "sqlite3",
        } or attribute.attr in {"autocommit", "isolation_level", "row_factory", "text_factory"}:
            return True

    for subscript, _ in visitor.subscript_stores:
        root = _root_name(subscript.value)
        if root not in NON_SQL_SUBSCRIPT_STORE_NAMES:
            return True

    for call, qualified_name in visitor.calls:
        if isinstance(call.func, ast.Name):
            if call.func.id in {"setattr", "delattr"}:
                return True
            if call.func.id in visitor.higher_order_names | SQLITE_HIGHER_ORDER_NAME_NAMES:
                return True
            if call.func.id == "getattr":
                continue
            if (
                _call_contains_known_database_object(call, visitor)
                and not _known_callback_call(record, call, qualified_name, visitor)
                and call.func.id
                not in {
                    "isinstance",
                    "issubclass",
                    "type",
                    "tuple",
                    "list",
                    "dict",
                    "bytes",
                    "str",
                    "len",
                    "any",
                    "all",
                    "sorted",
                    "set",
                    "enumerate",
                    "range",
                    "Path",
                    "Exception",
                    "ValueError",
                    "RuntimeError",
                    "MigrationError",
                    "DomainEventValidationIssue",
                    "DomainEventValidationError",
                    "ProjectionSnapshot",
                    "EventStoreConstraintError",
                    "_new_error",
                    "_validation_error",
                    "_issue",
                    "json",
                    "hashlib",
                    "re",
                    "os",
                    "stat",
                    "time",
                    "secrets",
                    "sqlite3",
                }
            ):
                return True
        elif isinstance(call.func, ast.Attribute):
            method = call.func.attr
            receiver_node = call.func.value
            call_parts = _attribute_parts(call.func)
            if call_parts == ("object", "__setattr__"):
                if (record.relative_path, qualified_name) not in OBJECT_SETATTR_ALLOWLIST:
                    return True
                continue
            if method in {"_read", "_write"}:
                if not _database_operation_call_is_exact(record, call, qualified_name):
                    return True
                continue
            if method in SQLITE_HIGHER_ORDER_METHOD_NAMES:
                return True
            if (
                method in {"setitem", "delitem"}
                and call_parts is not None
                and call_parts[:1] == ("operator",)
            ):
                return True
            if method in {"execute", "executemany", "executescript"}:
                if _receiver_is_known_cursor(receiver_node, visitor):
                    return True
                if not _receiver_is_known_connection(receiver_node, visitor) or method != "execute":
                    return True
                sql = _static_string(call.args[0]) if call.args else None
                if sql is None:
                    if not _dynamic_sql_is_allowed(record, call, qualified_name):
                        return True
                    continue
                source_tokens = _source_sql_tokens(sql)
                first_word = _sql_first_word(source_tokens) if source_tokens else None
                if first_word in {"ROLLBACK", "COMMIT", "BEGIN"}:
                    if len(call.args) != 1 or call.keywords:
                        return True
                    token = _strict_transaction_token(sql)
                    if (
                        token is None
                        or (record.relative_path, qualified_name, token)
                        not in TRANSACTION_ALLOWLIST
                    ):
                        return True
                    continue
                if first_word == "PRAGMA":
                    if len(call.args) != 1 or call.keywords:
                        return True
                    if not _pragma_is_allowed(record, call, qualified_name, sql):
                        return True
                    continue
                if not _storage_dml_is_allowed(record, qualified_name, sql):
                    parsed = _source_sql_tokens(sql)
                    parsed_first = _sql_first_word(parsed) if parsed else None
                    if parsed_first not in {"SELECT", "EXPLAIN", "VALUES"} or (
                        parsed is not None and _sql_contains_load_extension(parsed)
                    ):
                        return True
            elif method == "cursor":
                if not _receiver_is_known_connection(receiver_node, visitor):
                    return True
            elif method == "blobopen":
                if (
                    not _receiver_is_known_connection(receiver_node, visitor)
                    or _keyword_bool(call, "readonly") is not True
                ):
                    return True
            elif method == "backup":
                if (
                    record.relative_path != MIGRATION_CONNECT_PATH
                    or qualified_name
                    != "neontof.persistence.migrations._copy_database_with_deadline"
                    or not _backup_call_is_exact(record, call, visitor)
                ):
                    return True
            elif _receiver_is_known_blob(receiver_node, visitor):
                receiver_name = _receiver_terminal_name(receiver_node)
                if (
                    receiver_name is None
                    or receiver_name not in visitor.readonly_blob_names
                    or method not in SQLITE_BLOB_READ_METHOD_NAMES
                ):
                    return True
            elif (
                method in SQLITE_CURSOR_METHOD_NAMES
                and isinstance(receiver_node, ast.Call)
                and isinstance(receiver_node.func, ast.Attribute)
                and receiver_node.func.attr == "execute"
                and _receiver_is_known_connection(receiver_node.func.value, visitor)
                and _cursor_call_is_bounded(call, method)
            ):
                continue
            elif _receiver_is_known_cursor(receiver_node, visitor):
                if not _cursor_call_is_bounded(call, method):
                    return True
            elif _receiver_is_known_connection(receiver_node, visitor):
                if method != "close":
                    return True
            elif method in SQLITE_SINK_METHOD_NAMES or (
                _call_passes_database_handle(call, visitor)
                and not _known_callback_call(record, call, qualified_name, visitor)
            ):
                return True

    for lambda_node, qualified_name in visitor.lambda_nodes:
        if not _lambda_contains_database_operation(lambda_node):
            continue
        parent_call_allowed = False
        for call, call_qualified_name in visitor.calls:
            if call_qualified_name != qualified_name:
                continue
            if _database_operation_call_is_exact(record, call, call_qualified_name):
                parent_call_allowed = True
        if not parent_call_allowed:
            return True

    return False


EXPECTED_MIGRATION_TABLES = {
    "0001_event_store.sql": ("schema_migrations", "events"),
    "0002_projection_snapshots.sql": ("projection_snapshots",),
    "0003_observation_stores.sql": ("transcript_entries", "telemetry_entries"),
    "0004_turn_requests.sql": ("turn_requests",),
}
EXPECTED_MIGRATION_INDEXES = {
    "0004_turn_requests.sql": (
        "uq_turn_requests_campaign_processing",
        "idx_turn_requests_campaign_turn_request_id",
    ),
}


def _migration_directory(production_root: Path) -> Path:
    direct = production_root / "migrations"
    if direct.is_dir():
        return direct
    nested = production_root / "persistence" / "migrations"
    if nested.is_dir():
        return nested
    return direct


def _migration_sql_violations(production_root: Path) -> list[Path]:
    violations: set[Path] = set()
    migrations_root = _migration_directory(production_root)
    if not migrations_root.exists():
        return []
    try:
        paths = sorted(migrations_root.glob("*.sql"))
    except OSError, ValueError:
        return [migrations_root]
    for path in paths:
        try:
            raw_sql = path.read_bytes()
        except OSError:
            violations.add(path)
            continue
        if raw_sql.startswith(b"\xef\xbb\xbf") or b"\r" in raw_sql:
            violations.add(path)
            continue
        try:
            sql = raw_sql.decode("utf-8", errors="strict")
        except UnicodeError:
            violations.add(path)
            continue
        statements = _split_sql_statements_strict(sql)
        expected_tables = EXPECTED_MIGRATION_TABLES.get(path.name)
        expected_indexes = EXPECTED_MIGRATION_INDEXES.get(path.name, ())
        expected_statement_count = len(expected_tables or ()) + len(expected_indexes)
        if (
            statements is None
            or expected_tables is None
            or len(statements) != expected_statement_count
        ):
            violations.add(path)
            continue
        actual_tables: list[str] = []
        actual_indexes: list[str] = []
        statement_failed = False
        for index, statement in enumerate(statements):
            parsed = _sql_write_target(statement)
            if parsed is None:
                statement_failed = True
                break
            operation, target, quoted, qualified, has_cte = parsed
            if operation != "CREATE" or quoted or qualified or has_cte:
                statement_failed = True
                break
            first_words: list[str] = []
            for token in statement[:3]:
                word = _token_word(token)
                if word is not None:
                    first_words.append(word.upper())
            if index < len(expected_tables):
                if len(first_words) < 2 or first_words[:2] != ["CREATE", "TABLE"]:
                    statement_failed = True
                    break
                if (
                    path.name == "0004_turn_requests.sql"
                    and target == "turn_requests"
                    and not _has_request_key_exact_check(statement)
                ):
                    statement_failed = True
                    break
                actual_tables.append(target)
            else:
                if (
                    operation != "CREATE"
                    or len(first_words) < 3
                    or not (
                        first_words[:2] == ["CREATE", "INDEX"]
                        or first_words[:3] == ["CREATE", "UNIQUE", "INDEX"]
                    )
                ):
                    statement_failed = True
                    break
                if (
                    path.name == "0004_turn_requests.sql"
                    and target == "uq_turn_requests_campaign_processing"
                    and not _has_processing_partial_predicate(statement)
                ):
                    statement_failed = True
                    break
                actual_indexes.append(target)
        if (
            statement_failed
            or tuple(actual_tables) != expected_tables
            or tuple(actual_indexes) != expected_indexes
        ):
            violations.add(path)
    return sorted(violations)


def _sqlite_source_violations(production_root: Path) -> list[Path]:
    records, parse_failures = _source_records(production_root)
    violations = set(parse_failures)
    for record in records:
        if _source_file_has_violation(record):
            violations.add(record.path)

    connect_counts: dict[tuple[str, str], int] = {}
    transaction_counts: dict[tuple[str, str, str], int] = {}
    getattr_counts: dict[tuple[str, str], int] = {}
    pragma_counts: dict[tuple[str, str, str], int] = {}
    database_operation_counts: dict[tuple[str, str, str], int] = {}
    callback_counts: dict[tuple[str, str, str], int] = {}
    for record in records:
        for _, attribute_name, qualified_name in record.visitor.sqlite_module_calls:
            if attribute_name == "connect":
                connect_key = (record.relative_path, qualified_name)
                connect_counts[connect_key] = connect_counts.get(connect_key, 0) + 1
        for call, qualified_name in record.visitor.calls:
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr in {"_read", "_write"}
                and _receiver_terminal_name(call.func.value) == "_database"
            ):
                operation_key = (record.relative_path, qualified_name, call.func.attr)
                database_operation_counts[operation_key] = (
                    database_operation_counts.get(operation_key, 0) + 1
                )
            if isinstance(call.func, ast.Name):
                callback_key = (record.relative_path, qualified_name, call.func.id)
                if callback_key in ALLOWED_SQLITE_CALLBACK_CALL_COUNTS:
                    callback_counts[callback_key] = callback_counts.get(callback_key, 0) + 1
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "execute":
                continue
            if not call.args:
                continue
            sql = _static_string(call.args[0])
            if sql is None:
                continue
            transaction = _strict_transaction_token(sql)
            if transaction is not None:
                transaction_key = (record.relative_path, qualified_name, transaction)
                transaction_counts[transaction_key] = transaction_counts.get(transaction_key, 0) + 1
        for _, qualified_name in record.visitor.getattr_calls:
            getattr_key = (record.relative_path, qualified_name)
            getattr_counts[getattr_key] = getattr_counts.get(getattr_key, 0) + 1
        for call, qualified_name in record.visitor.calls:
            signature = _pragma_signature(record, call, qualified_name)
            if signature is None:
                continue
            pragma_key = (record.relative_path, qualified_name, signature)
            if pragma_key in PRAGMA_ALLOWLIST_COUNTS:
                pragma_counts[pragma_key] = pragma_counts.get(pragma_key, 0) + 1

    for (relative_path, qualified_name), count in connect_counts.items():
        if (relative_path, qualified_name) in CONNECT_ALLOWLIST and count != 1:
            violations.update(
                record.path for record in records if record.relative_path == relative_path
            )
    for transaction_key, count in transaction_counts.items():
        if transaction_key in TRANSACTION_ALLOWLIST and count != 1:
            relative_path = transaction_key[0]
            violations.update(
                record.path for record in records if record.relative_path == relative_path
            )
    for pragma_key, count in pragma_counts.items():
        if count != PRAGMA_ALLOWLIST_COUNTS[pragma_key]:
            relative_path = pragma_key[0]
            violations.update(
                record.path for record in records if record.relative_path == relative_path
            )
    for operation_key, count in database_operation_counts.items():
        if (
            operation_key in DATABASE_OPERATION_ALLOWLIST
            and count != DATABASE_OPERATION_ALLOWLIST_COUNTS[operation_key]
        ):
            relative_path = operation_key[0]
            violations.update(
                record.path for record in records if record.relative_path == relative_path
            )
    for callback_key, count in callback_counts.items():
        if count != ALLOWED_SQLITE_CALLBACK_CALL_COUNTS[callback_key]:
            relative_path = callback_key[0]
            violations.update(
                record.path for record in records if record.relative_path == relative_path
            )

    if _is_actual_production_root(production_root):
        for relative_path, qualified_name in CONNECT_ALLOWLIST:
            if connect_counts.get((relative_path, qualified_name), 0) != 1:
                violations.add(PRODUCTION_ROOT / Path(relative_path).relative_to("src/neontof"))
        for transaction_key in TRANSACTION_ALLOWLIST:
            if transaction_counts.get(transaction_key, 0) != 1:
                relative_path = transaction_key[0]
                violations.add(PRODUCTION_ROOT / Path(relative_path).relative_to("src/neontof"))
        for key, expected_count in GETATTR_ALLOWLIST.items():
            if getattr_counts.get(key, 0) != expected_count:
                relative_path = key[0]
                violations.add(PRODUCTION_ROOT / Path(relative_path).relative_to("src/neontof"))
        for pragma_key, expected_count in PRAGMA_ALLOWLIST_COUNTS.items():
            if pragma_counts.get(pragma_key, 0) != expected_count:
                relative_path = pragma_key[0]
                violations.add(PRODUCTION_ROOT / Path(relative_path).relative_to("src/neontof"))
    return sorted(violations)


def _append_receiver_is_event_store(call: ast.Call, visitor: _SqliteUsageVisitor) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "append":
        return False
    if _append_receiver_is_direct_event_store_constructor(call):
        return True
    receiver_name = _receiver_terminal_name(call.func.value)
    if receiver_name is None:
        return False
    if visitor.unsafe_event_store_rebind:
        return False
    return (
        receiver_name in {"_event_store", "event_store"}
        or receiver_name in visitor.event_store_names
    )


def _eventstore_append_caller_violations(production_root: Path) -> list[Path]:
    records, parse_failures = _source_records(production_root)
    violations = set(parse_failures)
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if record.visitor.unsafe_event_store_rebind:
            violations.add(record.path)
        for call, qualified_name in record.visitor.calls:
            if not _append_receiver_is_event_store(call, record.visitor):
                continue
            if _append_receiver_is_direct_event_store_constructor(call):
                violations.add(record.path)
            key = (record.relative_path, qualified_name)
            counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        if key not in EVENTSTORE_CALLER_ALLOWLIST or count != 1:
            for record in records:
                if record.relative_path == key[0]:
                    violations.add(record.path)
                    break
    for record in records:
        if record.relative_path != "src/neontof/application/turn_lifecycle.py":
            continue
        # The lifecycle path's presence is the implementation-stage boundary.  When
        # P1-03 exists, both expected methods must exist with one call each; the
        # P1-01c baseline has no lifecycle path and therefore still requires zero.
        for relative_path, qualified_name in EVENTSTORE_CALLER_ALLOWLIST:
            if (
                relative_path == record.relative_path
                and counts.get((relative_path, qualified_name), 0) != 1
            ):
                violations.add(record.path)
    return sorted(violations)


def _static_execute_records(record: _SourceRecord) -> Iterable[tuple[ast.Call, str, str]]:
    for call, qualified_name in record.visitor.calls:
        if isinstance(call.func, ast.Attribute) and call.func.attr == "execute" and call.args:
            sql = _static_string(call.args[0])
            if sql is not None:
                yield call, qualified_name, sql


def _events_dml_violations(production_root: Path) -> list[Path]:
    records, parse_failures = _source_records(production_root)
    violations = set(parse_failures)
    event_insert_counts: dict[tuple[str, str], int] = {}
    for record in records:
        for _, qualified_name, sql in _static_execute_records(record):
            tokens = _source_sql_tokens(sql)
            if tokens is None:
                continue
            parsed = _sql_write_target(tokens)
            if parsed is None or parsed[1] != "events":
                continue
            operation, _, quoted, qualified, has_cte = parsed
            if (
                record.relative_path == EVENT_DML_PATH
                and qualified_name == EVENT_DML_QUALIFIED_NAME
                and operation == "INSERT"
                and not quoted
                and not qualified
                and not has_cte
                and _is_exact_events_insert(sql)
            ):
                key = (record.relative_path, qualified_name)
                event_insert_counts[key] = event_insert_counts.get(key, 0) + 1
            else:
                violations.add(record.path)
    if _is_actual_production_root(production_root) and sum(event_insert_counts.values()) != 1:
        violations.add(PRODUCTION_ROOT / "persistence" / "event_store.py")
    elif not _is_actual_production_root(production_root):
        for (relative_path, _), count in event_insert_counts.items():
            if count != 1:
                violations.update(
                    record.path for record in records if record.relative_path == relative_path
                )
    return sorted(violations)


def _cross_module_violations(production_root: Path) -> list[Path]:
    records, parse_failures = _source_records(production_root)
    violations = set(parse_failures)
    reader_count = 0
    for record in records:
        if record.relative_path not in {
            SAME_CONNECTION_READER_PATH,
            TURN_REQUEST_READER_PATH,
        }:
            continue
        if record.visitor.cross_module_method_aliases:
            violations.add(record.path)
        if record.visitor.cross_module_method_alias_rebound:
            violations.add(record.path)
        reader_lines: list[int] = []
        for call, qualified_name in record.visitor.calls:
            if not isinstance(call.func, ast.Attribute):
                continue
            method = call.func.attr
            if method == "_read_campaign_on_connection":
                if (
                    not record.visitor.unsafe_event_store_rebind
                    and (record.relative_path, qualified_name) in SAME_CONNECTION_READER_ALLOWLIST
                    and not call.keywords
                    and len(call.args) == 2
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == "connection"
                    and isinstance(call.args[1], ast.Name)
                    and call.args[1].id == "campaign_id"
                    and _receiver_terminal_name(call.func.value) == "_event_store"
                ):
                    reader_count += 1
                    reader_lines.append(call.lineno)
                else:
                    violations.add(record.path)
            elif method in {"read_campaign", "claim"} or (
                method == "_write"
                and (
                    "<locals>.operation" in qualified_name
                    or _receiver_terminal_name(call.func.value) != "_database"
                )
            ):
                violations.add(record.path)
        if record.relative_path == SAME_CONNECTION_READER_PATH:
            projection_write_lines = [
                call.lineno
                for call, qualified_name, sql in _static_execute_records(record)
                if _is_allowed_projection_snapshot_write(record, qualified_name, sql)
            ]
            if (
                reader_lines
                and projection_write_lines
                and min(reader_lines) >= min(projection_write_lines)
            ):
                violations.add(record.path)
        if (
            "event_boundary_lock" in record.source
            and "_WRITE_LOCK" in record.source
            and (
                "_WRITE_LOCK = event_boundary_lock" in record.source
                or "event_boundary_lock = _WRITE_LOCK" in record.source
            )
        ):
            violations.add(record.path)
    if _is_actual_production_root(production_root) and reader_count != 2:
        violations.add(PRODUCTION_ROOT / "persistence" / "projection_store.py")
        violations.add(PRODUCTION_ROOT / "persistence" / "turn_request_store.py")
    elif not _is_actual_production_root(production_root) and reader_count > 2:
        for record in records:
            if record.relative_path in {
                SAME_CONNECTION_READER_PATH,
                TURN_REQUEST_READER_PATH,
            }:
                violations.add(record.path)
    return sorted(violations)


def _sqlite_usage_violations(production_root: Path) -> list[Path]:
    violations = set(_sqlite_source_violations(production_root))
    violations.update(_eventstore_append_caller_violations(production_root))
    violations.update(_events_dml_violations(production_root))
    violations.update(_migration_sql_violations(production_root))
    violations.update(_cross_module_violations(production_root))
    return sorted(violations)


def _repository_guard_violations(repository_root: Path) -> list[Path]:
    violations: list[Path] = []
    for path in repository_root.rglob("*"):
        relative_path = path.relative_to(repository_root)
        relative_parts = relative_path.parts
        if _is_forbidden_database_artifact(relative_path) and (
            not any(part in GENERATED_DIRECTORY_NAMES for part in relative_parts)
            or any(part in ARTIFACT_SCAN_GENERATED_DIRECTORY_NAMES for part in relative_parts)
        ):
            violations.append(path)
            continue
        if any(part in GENERATED_DIRECTORY_NAMES for part in relative_parts):
            continue
        is_phase_1_scoped_path = (
            "client" in relative_parts
            or "migrations" in relative_parts
            or relative_parts[:3]
            in {
                ("src", "neontof", "persistence"),
                ("src", "neontof", "persistence_like"),
                ("src", "neontof", "observability"),
            }
        )
        if is_phase_1_scoped_path and not _is_phase_1_allowed_path(relative_path):
            violations.append(path)
            continue
        if relative_path.as_posix() in PHASE_1_ALLOWED_EXACT_PATHS:
            continue
        if path.name in FORBIDDEN_REPOSITORY_FILENAMES:
            violations.append(path)
            continue
        is_production_path = relative_parts[:2] == ("src", "neontof")
        if is_production_path and (
            path.name.lower().startswith("openai") or path.name == "provider_registry.py"
        ):
            violations.append(path)
            continue
        if is_production_path and path.is_file() and path.suffix == ".py":
            source_text = path.read_text(encoding="utf-8")
            if "openai" in source_text.lower() or "providerregistry" in source_text.lower():
                violations.append(path)
                continue
        if _is_phase_1_allowed_path(relative_path):
            continue
    return sorted(violations)


def test_repository_contracts_fix_runtime_and_dev_root_sets() -> None:
    assert (REPOSITORY_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14.3"
    assert _direct_requirement_names(REPOSITORY_ROOT / "requirements.in") == {
        "fastapi",
        "pydantic",
        "uvicorn",
    }
    assert _direct_requirement_names(REPOSITORY_ROOT / "requirements-dev.in") == {
        "pyyaml",
        "httpx",
        "mypy",
        "pytest",
        "ruff",
        "types-pyyaml",
    }


def test_repository_contracts_fix_versions_and_lock_boundary() -> None:
    assert (REPOSITORY_ROOT / "requirements.in").read_text(encoding="utf-8") == (
        "fastapi==0.141.1\npydantic==2.13.4\nuvicorn==0.52.3\n"
    )
    dev_requirements = (REPOSITORY_ROOT / "requirements-dev.in").read_text(encoding="utf-8")
    assert "-r requirements.in\n" in dev_requirements
    assert "PyYAML==6.0.3\n" in dev_requirements
    assert "mypy==2.3.1\n" in dev_requirements
    assert "pytest==9.1.1\n" in dev_requirements
    assert "ruff==0.16.3\n" in dev_requirements

    lock_text = (REPOSITORY_ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock_text
    forbidden_sdk_name = "open" + "ai"
    assert forbidden_sdk_name not in lock_text.lower()
    assert "pip-tools" not in lock_text.lower()


def test_repository_contracts_fix_pyproject_and_environment_contract() -> None:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["pytest"]["ini_options"] == {
        "pythonpath": ["src"],
        "testpaths": ["tests"],
        "addopts": "-ra --strict-markers",
    }
    assert pyproject["tool"]["ruff"]["target-version"] == "py314"
    assert pyproject["tool"]["ruff"]["line-length"] == 100
    assert pyproject["tool"]["ruff"]["format"]["line-ending"] == "lf"
    assert pyproject["tool"]["mypy"]["strict"] is True
    assert pyproject["tool"]["mypy"]["warn_unused_ignores"] is True
    assert pyproject["tool"]["mypy"]["plugins"] == ["pydantic.mypy"]
    assert "tests/typecheck_fixtures" in pyproject["tool"]["mypy"]["exclude"]

    assert (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8") == (
        "NEONTOF_HOST=127.0.0.1\nNEONTOF_PORT=8765\nNEONTOF_WORKERS=1\n"
    )


def test_python_gate_order_is_preserved() -> None:
    ci_text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert _ci_guard_violations(ci_text) == []

    swapped = (
        ci_text.replace(CI_GATE_COMMANDS[1], "__SWAPPED_COMMAND__", 1)
        .replace(CI_GATE_COMMANDS[2], CI_GATE_COMMANDS[1], 1)
        .replace("__SWAPPED_COMMAND__", CI_GATE_COMMANDS[2], 1)
    )
    assert "python_gate_order" in _ci_guard_violations(swapped)


def test_windows_runner_assertion_is_preserved() -> None:
    ci_text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert _ci_guard_violations(ci_text) == []

    sabotaged = ci_text.replace("runs-on: windows-latest", "runs-on: ubuntu-latest", 1)
    assert "windows_runner" in _ci_guard_violations(sabotaged)


def test_exact_production_manifest_requires_explicit_entries() -> None:
    production_files = sorted(
        path.relative_to(PRODUCTION_ROOT).as_posix() for path in PRODUCTION_ROOT.rglob("*.py")
    )
    # production manifestはWP単位の明示entryを維持し、glob/prefixへ緩めない。
    assert production_files == sorted(
        [
            "__init__.py",
            "main.py",
            "config.py",
            "app.py",
            "application/__init__.py",
            "application/turn_lifecycle.py",
            "application/turn_models.py",
            "contracts/__init__.py",
            "contracts/base.py",
            "contracts/ids.py",
            "contracts/domain.py",
            "contracts/event_parser.py",
            "contracts/projection.py",
            "contracts/turn_status.py",
            "contracts/semantic_result.py",
            "contracts/transport.py",
            "contracts/character_sheet.py",
            "contracts/scenario.py",
            "event_metadata.py",
            "rules/__init__.py",
            "rules/minimal_2d6.py",
            "persistence/__init__.py",
            "persistence/sqlite_database.py",
            "persistence/migrations.py",
            "persistence/event_store.py",
            "persistence/projection_store.py",
            "model/__init__.py",
            "model/model_invoker.py",
            "model/fake_provider.py",
            "model/scripted_provider.py",
            "model/recorded_fixture.py",
            "observability/__init__.py",
            "observability/records.py",
            "observability/sanitization.py",
            "persistence/observation_store.py",
            "persistence/turn_request_store.py",
        ]
    )

    assert "event_metadata.py" in production_files


def test_rules_module_does_not_import_event_metadata() -> None:
    rules_root = PRODUCTION_ROOT / "rules"
    imported_modules: set[str] = set()
    for module_path in (rules_root / "__init__.py", rules_root / "minimal_2d6.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    imported_modules.add(node.module)
                    imported_modules.update(
                        f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
                    )
                if node.level and (
                    (node.module is not None and node.module.rsplit(".", 1)[-1] == "event_metadata")
                    or any(alias.name == "event_metadata" for alias in node.names)
                ):
                    imported_modules.add("neontof.event_metadata")

    assert not any(
        module == "neontof.event_metadata" or module.startswith("neontof.event_metadata.")
        for module in imported_modules
    )


def test_forbidden_dockerfile_sdk_registry_and_generated_paths_remain_forbidden(
    tmp_path: Path,
) -> None:
    assert _repository_guard_violations(REPOSITORY_ROOT) == []

    synthetic_root = tmp_path / "repository"
    (synthetic_root / "client" / "node_modules").mkdir(parents=True)
    (synthetic_root / "client" / "dist").mkdir(parents=True)
    (synthetic_root / "client" / "node_modules" / "package.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (synthetic_root / "client" / "dist" / "bundle.js").write_text(
        "console.log('generated');\n", encoding="utf-8"
    )
    (synthetic_root / "Dockerfile").write_text("FROM python:3.14\n", encoding="utf-8")
    (synthetic_root / "src" / "neontof").mkdir(parents=True)
    (synthetic_root / "src" / "neontof" / "openai_client.py").write_text(
        "raise RuntimeError\n", encoding="utf-8"
    )
    (synthetic_root / "src" / "neontof" / "provider_registry.py").write_text(
        "raise RuntimeError\n", encoding="utf-8"
    )
    (synthetic_root / ".node-version").write_text("22\n", encoding="utf-8")
    (synthetic_root / "client" / "src").mkdir(parents=True)
    (synthetic_root / "client" / "package.json").write_text("{}\n", encoding="utf-8")
    (synthetic_root / "client" / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (synthetic_root / "client" / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (synthetic_root / "client" / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (synthetic_root / "src" / "neontof" / "persistence" / "migrations").mkdir(parents=True)

    violations = _repository_guard_violations(synthetic_root)
    assert synthetic_root / "Dockerfile" in violations
    assert synthetic_root / "client" / "node_modules" not in violations
    assert synthetic_root / "client" / "node_modules" / "package.json" not in violations
    assert synthetic_root / "client" / "dist" not in violations
    assert synthetic_root / "client" / "dist" / "bundle.js" not in violations
    assert synthetic_root / "src" / "neontof" / "openai_client.py" in violations
    assert synthetic_root / "src" / "neontof" / "provider_registry.py" in violations
    assert synthetic_root / ".node-version" not in violations
    assert synthetic_root / "client" / "package.json" not in violations
    assert synthetic_root / "client" / "package-lock.json" not in violations
    assert synthetic_root / "client" / "tsconfig.json" not in violations
    assert synthetic_root / "client" / "src" / "main.ts" not in violations
    assert synthetic_root / "src" / "neontof" / "persistence" / "migrations" not in violations

    forbidden_names = FORBIDDEN_REPOSITORY_FILENAMES
    all_files = _tracked_candidate_files()
    assert not [
        path
        for path in all_files
        if path.name in forbidden_names
        and not _is_phase_1_allowed_path(path.relative_to(REPOSITORY_ROOT))
    ]
    forbidden_sdk_name = "open" + "ai"
    forbidden_registry_name = "provider" + "_registry.py"
    assert not list(PRODUCTION_ROOT.rglob(f"{forbidden_sdk_name}*.py"))
    assert not list(PRODUCTION_ROOT.rglob(forbidden_registry_name))
    assert not [
        path for path in all_files if path.name.lower().endswith(tuple(FORBIDDEN_DATABASE_SUFFIXES))
    ]

    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in PRODUCTION_ROOT.rglob("*.py")
    )
    assert forbidden_sdk_name not in source_text.lower()
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []
    forbidden_provider_names = ("ProviderRegistry", "provider_registry")
    for forbidden_provider_name in forbidden_provider_names:
        assert forbidden_provider_name not in source_text
    assert "background worker" not in source_text.lower()


def test_generated_directory_names_include_node_modules(tmp_path: Path) -> None:
    assert "node_modules" in GENERATED_DIRECTORY_NAMES

    synthetic_root = tmp_path / "repository"
    (synthetic_root / "node_modules").mkdir(parents=True)
    (synthetic_root / "node_modules" / "generated.py").write_text(
        "generated = True\n", encoding="utf-8"
    )
    kept_file = synthetic_root / "src" / "kept.py"
    kept_file.parent.mkdir(parents=True)
    kept_file.write_text("kept = True\n", encoding="utf-8")

    assert set(_tracked_candidate_files(synthetic_root)) == {kept_file}


def test_phase_1_client_and_migrations_paths_are_allowed() -> None:
    allowed_paths = {Path(path) for path in PHASE_1_ALLOWED_EXACT_PATHS}
    assert all(_is_phase_1_allowed_path(path) for path in allowed_paths)
    assert "client/src/main.ts" not in PHASE_1_ALLOWED_EXACT_PATHS

    assert not _is_phase_1_allowed_path(Path("package.json"))
    assert not _is_phase_1_allowed_path(Path("unrelated/package.json"))
    assert not _is_phase_1_allowed_path(Path("other/.node-version"))
    assert not _is_phase_1_allowed_path(Path("client/.node-version"))
    assert _is_phase_1_allowed_path(Path("client/other.json"))
    assert _is_phase_1_allowed_path(Path("client/src/main.ts"))
    assert _is_phase_1_allowed_path(Path("client/package.json"))
    assert _is_phase_1_allowed_path(Path("client/package-lock.json"))
    assert _is_phase_1_allowed_path(Path("client/tsconfig.json"))
    assert not _is_phase_1_allowed_path(Path("client/nested/package.json"))
    assert not _is_phase_1_allowed_path(Path("client/nested/package-lock.json"))
    assert not _is_phase_1_allowed_path(Path("client/nested/tsconfig.json"))
    for forbidden_name in (
        "Dockerfile",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "vitest.config.ts",
    ):
        assert not _is_phase_1_allowed_path(Path("client") / forbidden_name)
        assert not _is_phase_1_allowed_path(Path("client/nested") / forbidden_name)
    assert not _is_phase_1_allowed_path(Path("client/node_modules"))
    assert not _is_phase_1_allowed_path(Path("client/dist"))
    assert _is_phase_1_allowed_path(Path("src/neontof/persistence"))
    assert _is_phase_1_allowed_path(Path("src/neontof/persistence/event_store.py"))
    assert _is_phase_1_allowed_path(Path("src/neontof/persistence/migrations/0001.sql"))
    assert _is_phase_1_allowed_path(Path("src/neontof/observability"))
    assert _is_phase_1_allowed_path(Path("src/neontof/observability/records.py"))
    assert _is_phase_1_allowed_path(Path("src/neontof/observability/sanitization.py"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.sqlite"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.sqlite3"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.db"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.db-wal"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.db-shm"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.sqlite-wal"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/cache.sqlite-shm"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/Dockerfile"))
    assert not _is_phase_1_allowed_path(Path("migrations/0001.sql"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/application/migrations/0001.sql"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence/migrations/package.json"))
    assert not _is_phase_1_allowed_path(Path("unrelated/client/marker.txt"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/persistence_like/module.py"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/observability_like/module.py"))
    assert not _is_phase_1_allowed_path(Path("src/neontof/observability/cache.sqlite"))
    assert not _is_phase_1_allowed_path(Path("application/persistence.py"))


def test_repository_guard_enforces_phase_1_path_policy(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repository"
    invalid_paths = (
        synthetic_root / "migrations" / "0001.sql",
        synthetic_root / "src" / "neontof" / "application" / "migrations" / "0001.sql",
        synthetic_root / "unrelated" / "client" / "marker.txt",
        synthetic_root / "src" / "neontof" / "persistence_like" / "module.py",
        synthetic_root / "src" / "neontof" / "persistence" / "cache.sqlite",
        synthetic_root / "src" / "neontof" / "persistence" / "cache.db",
        synthetic_root / "src" / "neontof" / "persistence" / "Dockerfile",
        synthetic_root / "src" / "neontof" / "persistence" / "package.json",
        synthetic_root / "src" / "neontof" / "persistence" / "openai_client.py",
        synthetic_root / "src" / "neontof" / "persistence" / "provider_registry.py",
        synthetic_root / "src" / "neontof" / "observability" / "extra.py",
        synthetic_root / "client" / ".node-version",
        synthetic_root / "client" / "Dockerfile",
        synthetic_root / "client" / "nested" / "eslint.config.mjs",
        synthetic_root / "client" / "nested" / "prettier.config.mjs",
        synthetic_root / "client" / "nested" / "vitest.config.ts",
        synthetic_root / "client" / "nested" / "package.json",
        synthetic_root / "client" / "cache.sqlite",
        synthetic_root / "package.json",
        synthetic_root / "unrelated" / "package-lock.json",
    )
    for path in invalid_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")

    allowed_paths = (
        synthetic_root / ".node-version",
        synthetic_root / "client" / "package.json",
        synthetic_root / "client" / "package-lock.json",
        synthetic_root / "client" / "tsconfig.json",
        synthetic_root / "client" / "src" / "main.ts",
        synthetic_root / "src" / "neontof" / "persistence" / "event_store.py",
        synthetic_root / "src" / "neontof" / "persistence" / "migrations" / "0001.sql",
        synthetic_root / "src" / "neontof" / "observability" / "records.py",
    )
    for path in allowed_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")

    violations = _repository_guard_violations(synthetic_root)
    assert set(invalid_paths) <= set(violations)
    assert not set(allowed_paths) & set(violations)
    persistence_root = synthetic_root / "src" / "neontof" / "persistence"
    assert persistence_root not in violations
    assert persistence_root / "event_store.py" not in violations


def test_node_and_npm_are_not_rejected_by_ci_guard() -> None:
    ci_text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    synthetic_client_gate = (
        ci_text
        + """

      - name: Check Node runtime
        shell: pwsh
        run: node --version

      - name: Install client dependencies
        shell: pwsh
        run: npm ci

      - name: Check npm runtime
        shell: pwsh
        run: npm --version
    """
    )
    assert _ci_guard_violations(synthetic_client_gate) == []


def _synthetic_production_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository" / "src" / "neontof"
    root.mkdir(parents=True)
    return root


def _write_synthetic_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / Path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode("utf-8"))
    return path


def test_sqlite_type_references_and_exact_runtime_migration_connects_are_allowed(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/sqlite_database.py",
        """
import sqlite3

class SqliteDatabase:
    def _open_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self._path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=True,
            uri=False,
        )
""",
    )
    _write_synthetic_source(
        synthetic_root,
        "persistence/migrations.py",
        """
import sqlite3

def _open_backup_connection(path: object, *, query_only: bool) -> sqlite3.Connection:
    return sqlite3.connect(
        path,
        timeout=5.0,
        isolation_level=None,
        check_same_thread=True,
        uri=False,
    )

def is_connection(value: object) -> bool:
    return isinstance(value, sqlite3.Connection)
""",
    )

    assert _sqlite_usage_violations(synthetic_root) == []
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_scan_rejects_arbitrary_persistence_connect_and_constructor(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    cases = {
        "persistence/database_connect.py": """
import sqlite3

connection = sqlite3.connect(\":memory:\")
""",
        "persistence/connection_constructor.py": """
import sqlite3

connection_type = sqlite3.Connection()
""",
        "persistence/cursor_constructor.py": """
import sqlite3

cursor = sqlite3.Cursor()
""",
        "persistence/blob_constructor.py": """
import sqlite3

blob = sqlite3.Blob()
""",
        "persistence/dynamic_import_connect.py": """
connection = __import__(\"sqlite3\").connect(\":memory:\")
""",
        "persistence/dynamic_import_constructor.py": """
connection = __import__(\"sqlite3\").Connection(\":memory:\")
""",
    }
    rejected_paths = [
        _write_synthetic_source(synthetic_root, relative_path, source)
        for relative_path, source in cases.items()
    ]

    violations = _sqlite_usage_violations(synthetic_root)
    assert set(rejected_paths) <= set(violations)


def test_sqlite_source_scan_rejects_arbitrary_persistence_connect_alias_and_import_variants(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    variants = {
        "module_alias.py": "import sqlite3 as db\nconnection = db.connect(':memory:')\n",
        "deep_module_alias.py": (
            "import sqlite3.dbapi2 as db\nconnection = db.connect(':memory:')\n"
        ),
        "deep_module.py": (
            "import sqlite3.dbapi2\nconnection = sqlite3.dbapi2.connect(':memory:')\n"
        ),
        "connect_alias.py": "from sqlite3 import connect as open_db\nconnection = open_db(':memory:')\n",
        "deep_connect_alias.py": (
            "from sqlite3.dbapi2 import connect as open_db\nconnection = open_db(':memory:')\n"
        ),
        "connection_alias.py": (
            "from sqlite3 import Connection as DbConnection\nconnection_type: type[DbConnection]\n"
        ),
        "deep_connection_alias.py": (
            "from sqlite3.dbapi2 import Connection as DbConnection\n"
            "connection_type: type[DbConnection]\n"
        ),
        "wildcard.py": "from sqlite3 import *\nconnection = connect(':memory:')\n",
        "deep_wildcard.py": "from sqlite3.dbapi2 import *\nconnection = connect(':memory:')\n",
        "dynamic_import_connect.py": ("connection = __import__('sqlite3').connect(':memory:')\n"),
        "dynamic_import_constructor.py": (
            "connection = __import__('sqlite3').Connection(':memory:')\n"
        ),
        "importlib_connect.py": (
            "import importlib\n"
            "connection = importlib.import_module('sqlite3').connect(':memory:')\n"
        ),
        "importlib_constructor.py": (
            "import importlib\n"
            "connection = importlib.import_module('sqlite3').Connection(':memory:')\n"
        ),
    }
    rejected_paths = [
        _write_synthetic_source(synthetic_root, f"application/{name}", source)
        for name, source in variants.items()
    ]
    rejected_paths.append(
        _write_synthetic_source(
            synthetic_root,
            "persistence/arbitrary.py",
            "import sqlite3 as db\nconnection = db.connect(':memory:')\n",
        )
    )

    helper_path = _write_synthetic_source(
        synthetic_root,
        "application/helper.py",
        "from neontof.application import helper\nvalue = helper()\n",
    )

    violations = _sqlite_usage_violations(synthetic_root)
    assert set(rejected_paths) <= set(violations)
    assert helper_path not in violations

    import_variants = {
        "relative_persistence_connect.py": (
            "from ..persistence import connect\nconnection = connect(':memory:')\n"
        ),
        "relative_persistence_store_connect.py": (
            "from ..persistence.sqlite_store import connect\nconnection = connect(':memory:')\n"
        ),
        "relative_persistence_connection.py": (
            "from ..persistence import Connection\nconnection_type: type[Connection]\n"
        ),
        "relative_persistence_wildcard.py": (
            "from ..persistence.sqlite_store import *\nconnection = connect(':memory:')\n"
        ),
        "absolute_persistence_connect.py": (
            "from neontof.persistence import connect\nconnection = connect(':memory:')\n"
        ),
        "absolute_persistence_connection.py": (
            "from neontof.persistence import Connection\nconnection_type: type[Connection]\n"
        ),
        "absolute_persistence_wildcard.py": (
            "from neontof.persistence import *\nconnection = connect(':memory:')\n"
        ),
        "absolute_persistence_store_connect.py": (
            "from neontof.persistence.sqlite_store import connect\n"
            "connection = connect(':memory:')\n"
        ),
    }
    for case_name, source in import_variants.items():
        case_root = _synthetic_production_root(tmp_path / case_name.removesuffix(".py"))
        rejected_path = _write_synthetic_source(case_root, f"application/{case_name}", source)
        assert rejected_path in _sqlite_usage_violations(case_root), case_name


def test_sqlite_connect_exact_allowlist_rejects_duplicate_call_count(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/sqlite_database.py",
        """
import sqlite3

class SqliteDatabase:
    def _open_connection(self) -> sqlite3.Connection:
        sqlite3.connect(self._path, timeout=5.0, isolation_level=None, check_same_thread=True, uri=False)
        return sqlite3.connect(self._path, timeout=5.0, isolation_level=None, check_same_thread=True, uri=False)
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_repository_guard_rejects_database_files_in_repository_tree(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repository"
    synthetic_root.mkdir()
    (synthetic_root / "state.sqlite").write_bytes(b"not a database")
    nested_path = synthetic_root / "client" / "node_modules" / "cache.db"
    nested_path.parent.mkdir(parents=True)
    nested_path.write_bytes(b"not a database")

    violations = _repository_guard_violations(synthetic_root)
    assert synthetic_root / "state.sqlite" in violations
    assert nested_path in violations
    assert _repository_guard_violations(REPOSITORY_ROOT) == []


def test_repository_contracts_define_projection_models_only_in_projection_module() -> None:
    projection_path = PRODUCTION_ROOT / "contracts" / "projection.py"
    assert projection_path.is_file()

    def class_definition_count(path: Path, class_name: str) -> int:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return sum(
            isinstance(node, ast.ClassDef) and node.name == class_name for node in ast.walk(tree)
        )

    assert class_definition_count(projection_path, "FactRecord") == 1
    assert class_definition_count(projection_path, "Projection") == 1
    for path in PRODUCTION_ROOT.rglob("*.py"):
        if path == projection_path:
            continue
        assert class_definition_count(path, "FactRecord") == 0, path
        assert class_definition_count(path, "Projection") == 0, path


def test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repository"
    persistence_root = synthetic_root / "src" / "neontof" / "persistence"
    persistence_root.mkdir(parents=True)
    forbidden_paths = tuple(
        persistence_root / filename
        for filename in (
            "state.sqlite",
            "state.sqlite3",
            "state.db",
            "state.sqlite-wal",
            "state.sqlite-shm",
            "state.sqlite3-wal",
            "state.sqlite3-shm",
            "state.db-wal",
            "state.db-shm",
            "state.sqlite-2",
            "state.sqlite3-2",
            "state.sqlite3-journal",
            "state.sqlite-wal-extra",
            "state.sqlite3-shm-extra",
        )
    )
    for path in forbidden_paths:
        path.write_bytes(b"database artifact")

    violations = _repository_guard_violations(synthetic_root)

    assert set(forbidden_paths) <= set(violations)


def test_repository_guard_rejects_journals_variants_and_migration_artifact_sets(
    tmp_path: Path,
) -> None:
    synthetic_root = tmp_path / "repository"
    persistence_root = synthetic_root / "src" / "neontof" / "persistence"
    persistence_root.mkdir(parents=True)
    forbidden_names = (
        "state.db-journal",
        "state.sqlite-journal",
        "state.sqlite3-journal",
        "state.db-2",
        "state.migration-deadbeef.partial.sqlite3",
        "state.migration-deadbeef.partial.sqlite3-wal",
        "state.migration-deadbeef.partial.sqlite3-shm",
        "state.migration-deadbeef.verified.sqlite3",
        "state.migration-deadbeef.verified.sqlite3-wal",
        "state.migration-deadbeef.verified.sqlite3-shm",
    )
    forbidden_paths = tuple(persistence_root / name for name in forbidden_names)
    for path in forbidden_paths:
        path.write_bytes(b"database artifact")
    backup_root = persistence_root / ".neontof-migration-backups"
    backup_root.mkdir()
    (backup_root / "state.migration-deadbeef.partial.sqlite3").write_bytes(b"partial")

    violations = _repository_guard_violations(synthetic_root)

    assert set(forbidden_paths) <= set(violations)
    assert backup_root in violations
    for path in forbidden_paths:
        assert not _is_phase_1_allowed_path(path.relative_to(synthetic_root))
    assert not _is_phase_1_allowed_path(
        Path("src/neontof/persistence/state.migration-deadbeef.partial.sqlite3")
    )


def test_repository_guard_does_not_treat_normal_persistence_files_as_database_artifacts(
    tmp_path: Path,
) -> None:
    synthetic_root = tmp_path / "repository"
    persistence_root = synthetic_root / "src" / "neontof" / "persistence"
    persistence_root.mkdir(parents=True)
    normal_paths = (
        persistence_root / "README.txt",
        persistence_root / "migration_notes.md",
        persistence_root / "event_store.py",
    )
    for path in normal_paths:
        path.write_text("marker\n", encoding="utf-8")

    violations = _repository_guard_violations(synthetic_root)

    assert not set(normal_paths) & set(violations)


def test_event_store_append_has_one_nested_events_insert(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/event_store.py",
        """
import sqlite3

class EventStore:
    def append(self, batch: object) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(\"INSERT INTO events(event_id) VALUES (?)\", (batch,))

        operation(None)
""",
    )

    assert _sqlite_usage_violations(synthetic_root) == []


def test_repository_scan_rejects_second_events_insert_or_replace_update_delete(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/event_store.py",
        """
import sqlite3

class EventStore:
    def append(self, batch: object) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(\"INSERT INTO events(event_id) VALUES (?)\", (batch,))
            connection.execute(\"INSERT OR REPLACE INTO events(event_id) VALUES (?)\", (batch,))
            connection.execute(\"UPDATE events SET event_id = ?\", (batch,))
            connection.execute(\"DELETE FROM events\")

        operation(None)
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_migration_dynamic_statement_is_allowed_after_strict_token_scan(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/migrations.py",
        """
import sqlite3

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
        raise ValueError
    return tuple(statements)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
    )
    migrations_root = synthetic_root / "persistence" / "migrations"
    migrations_root.mkdir(parents=True)
    source_migration = PRODUCTION_ROOT / "persistence" / "migrations" / "0001_event_store.sql"
    (migrations_root / source_migration.name).write_bytes(source_migration.read_bytes())

    assert _sqlite_usage_violations(synthetic_root) == []


def test_repository_scan_rejects_dynamic_sql_comment_string_cte_and_quoted_bypass(
    tmp_path: Path,
) -> None:
    cases = {
        "direct_dynamic": (
            "persistence/migrations.py",
            """
import sqlite3

def _run_migrations(connection: sqlite3.Connection, sql: str) -> None:
    connection.execute(sql)
""",
        ),
        "decoy_loop": (
            "persistence/migrations.py",
            """
import sqlite3

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
        raise ValueError
    return tuple(statements)

def _decoy(connection: sqlite3.Connection, sql: str) -> None:
    for statement in _split_sql_statements(sql):
        connection.execute(statement)

def _run_migrations(connection: sqlite3.Connection, sql: str) -> None:
    connection.execute(sql)
""",
        ),
        "external_execute": (
            "persistence/migrations.py",
            """
import sqlite3

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
        raise ValueError
    return tuple(statements)

def _run_migrations(connection: sqlite3.Connection, sql: str) -> None:
    for statement in _split_sql_statements(sql):
        pass
    connection.execute(statement)
""",
        ),
        "fake_splitter": (
            "persistence/migrations.py",
            """
import sqlite3

def _split_sql_statements(sql: str) -> tuple[str, ...]:
    return (sql,)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
        ),
        "if_false_decoy": (
            "persistence/migrations.py",
            """
import sqlite3

def _split_sql_statements(sql: str) -> tuple[str, ...]:
    if False:
        statements: list[str] = []
        buffer = ""
        for line in sql.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if not statement:
                    raise ValueError
                statements.append(statement)
                buffer = ""
        if buffer.strip():
            raise ValueError
        return tuple(statements)
    return (sql,)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
        ),
        "other_function_decoy": (
            "persistence/migrations.py",
            """
import sqlite3

def _evidence_only(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if not statement:
                raise ValueError
            statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise ValueError
    return tuple(statements)

def _split_sql_statements(sql: str) -> tuple[str, ...]:
    return (sql,)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
        ),
        "other_loop_decoy": (
            "persistence/migrations.py",
            """
import sqlite3

def _split_sql_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for ignored in ():
        for line in sql.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if not statement:
                    raise ValueError
                statements.append(statement)
                buffer = ""
    if buffer.strip():
        raise ValueError
    return tuple(statements)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
        ),
        "raw_sql_first_return": (
            "persistence/migrations.py",
            """
import sqlite3

def _split_sql_statements(sql: str) -> tuple[str, ...]:
    return (sql,)
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if not statement:
                raise ValueError
            statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise ValueError
    return tuple(statements)

def _run_migrations(connection: sqlite3.Connection, specs: tuple[object, ...]) -> None:
    for spec in specs:
        for statement in _split_sql_statements(spec.sql):
            connection.execute(statement)
""",
        ),
    }
    for case_name, (relative_path, source) in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(synthetic_root, relative_path, source)
        assert rejected_path in _sqlite_usage_violations(synthetic_root)

    raw_root = _synthetic_production_root(tmp_path / "raw_migration")
    raw_source_path = _write_synthetic_source(
        raw_root,
        "persistence/migrations.py",
        """
import sqlite3

def _run_migrations(connection: sqlite3.Connection, sql: str) -> None:
    connection.execute(sql)
""",
    )
    migrations_root = raw_root / "persistence" / "migrations"
    migrations_root.mkdir(parents=True)
    rejected_migration_path = migrations_root / "0001_event_store.sql"
    rejected_migration_path.write_bytes(
        b"-- CREATE TABLE events;\n"
        b"WITH source AS (SELECT 'CREATE TABLE events') "
        b'CREATE TABLE "events" (event_id TEXT);\n'
    )

    violations = _sqlite_usage_violations(raw_root)
    assert raw_source_path in violations
    assert rejected_migration_path in violations

    query_root = _synthetic_production_root(tmp_path / "query_bounded_delete")
    production_source = (PRODUCTION_ROOT / "persistence" / "migrations.py").read_text(
        encoding="utf-8"
    )
    mutated_source = production_source.replace(
        '"SELECT typeof(event_json) FROM events ORDER BY campaign_id, sequence"',
        '"DELETE FROM events"',
        1,
    )
    assert mutated_source != production_source
    query_path = _write_synthetic_source(
        query_root,
        "persistence/migrations.py",
        mutated_source,
    )
    assert query_path in _sqlite_usage_violations(query_root)


def test_source_candidate_without_sqlite_import_is_skipped_only_without_sink(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    plain_path = _write_synthetic_source(
        synthetic_root,
        "application/plain.py",
        "# sqlite3.connect(':memory:')\nvalue = 'sqlite3.Connection'\n",
    )
    assert plain_path not in _sqlite_usage_violations(synthetic_root)

    sink_path = _write_synthetic_source(
        synthetic_root,
        "application/unknown_sink.py",
        'connection.execute("SELECT 1")\n',
    )
    assert sink_path in _sqlite_usage_violations(synthetic_root)


def test_source_scan_rejects_no_import_unknown_sqlite_wrapper(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "application/wrapper.py",
        """
def open_database() -> object:
    return object()

connection = open_database()
connection.execute(\"SELECT 1\")
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_sqlite_call_receiver_positive_paths_are_exact(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    production_source = (PRODUCTION_ROOT / "persistence" / "migrations.py").read_text(
        encoding="utf-8"
    )
    _write_synthetic_source(
        synthetic_root,
        "persistence/migrations.py",
        production_source,
    )

    assert _sqlite_usage_violations(synthetic_root) == []

    load_extension_root = _synthetic_production_root(tmp_path / "load_extension_sql")
    load_extension_path = _write_synthetic_source(
        load_extension_root,
        "persistence/migrations.py",
        """
import sqlite3

def _query_bounded(connection: sqlite3.Connection) -> None:
    connection.execute("SELECT load_extension('x')")
""",
    )
    assert load_extension_path in _sqlite_usage_violations(load_extension_root)


def test_sqlite_scan_rejects_unknown_receiver_alias_rebind_and_getattr(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/unknown.py",
        """
import sqlite3

def read(connection: sqlite3.Connection, factory: object) -> None:
    sqlite3 = factory
    sqlite3.connect(\":memory:\")
    getattr(connection, \"execute\")(\"SELECT 1\")
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_event_parser_exception_object_setattr_is_non_sql_positive() -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_scan_rejects_connection_blob_and_operator_store_mutation(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/mutate.py",
        """
import operator
import sqlite3

def mutate(connection: sqlite3.Connection, blob: sqlite3.Blob) -> None:
    connection.row_factory = object()
    blob[0] = 1
    operator.setitem(connection, \"row_factory\", object())
    setattr(connection, \"row_factory\", object())
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_read_only_blob_lifecycle_and_read_subscript_are_allowed(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/blob_reader.py",
        """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> bytes:
    blob = connection.blobopen(\"events\", \"event_json\", 1, readonly=True)
    try:
        return blob[0:1]
    finally:
        blob.close()
""",
    )

    assert _sqlite_usage_violations(synthetic_root) == []


def test_sqlite_scan_rejects_blob_write_unknown_blob_and_nested_subscript_store(
    tmp_path: Path,
) -> None:
    cases = {
        "write": """
import sqlite3

def mutate(connection: sqlite3.Connection, value: object) -> None:
    blob = connection.blobopen(\"events\", \"event_json\", 1, readonly=False)
    blob.write(b\"x\")
    blob[0][0] = 1
    value[0] = 1
    sqlite3.Blob()
""",
        "missing_close": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> bytes:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    return blob.read(1)
""",
        "unknown_blob": """
import sqlite3

def read_blob(blob: sqlite3.Blob) -> bytes:
    return blob.read(1)
""",
        "nested_conditional_finally": """
import sqlite3

def read_blob(connection: sqlite3.Connection, enabled: bool) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    try:
        blob.read(1)
    finally:
        if enabled:
            blob.close()
""",
        "nested_loop_finally": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    try:
        blob.read(1)
    finally:
        for _ in range(1):
            blob.close()
""",
        "nested_while_finally": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    try:
        blob.read(1)
    finally:
        while False:
            blob.close()
""",
        "nested_try_finally": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    try:
        blob.read(1)
    finally:
        try:
            blob.close()
        finally:
            pass
""",
        "conditional_close": """
import sqlite3

def read_blob(connection: sqlite3.Connection, enabled: bool) -> None:
    if enabled:
        blob = connection.blobopen("events", "event_json", 1, readonly=True)
        blob.read(1)
        blob.close()
""",
        "close_before_use": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    blob.close()
    blob.read(1)
""",
        "cross_function_close": """
import sqlite3

def open_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    blob.read(1)

def close_blob() -> None:
    blob.close()
""",
        "alias_close": """
import sqlite3

def read_blob(connection: sqlite3.Connection) -> None:
    blob = connection.blobopen("events", "event_json", 1, readonly=True)
    alias = blob
    try:
        alias.read(1)
    finally:
        blob.close()
        alias.close()
""",
    }

    for case_name, source in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(
            synthetic_root, f"persistence/blob_{case_name}.py", source
        )
        assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_only_six_transaction_sql_sites_are_allowed(tmp_path: Path) -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []

    migration_path = (
        tmp_path / "src" / "neontof" / "persistence" / "migrations" / "0004_turn_requests.sql"
    )
    migration_path.parent.mkdir(parents=True)
    migration_sql = (
        REPOSITORY_ROOT
        / "src"
        / "neontof"
        / "persistence"
        / "migrations"
        / "0004_turn_requests.sql"
    ).read_bytes()
    migration_path.write_bytes(migration_sql)
    assert _migration_sql_violations(tmp_path / "src" / "neontof") == []

    migration_path.write_bytes(migration_sql.replace(b" WHERE status = 'processing'", b""))
    assert migration_path in _migration_sql_violations(tmp_path / "src" / "neontof")

    request_key_mutations = (
        (b"length(request_key) BETWEEN 1 AND 256", b"length(request_key) BETWEEN 1 AND 257"),
        (b"length(request_key) BETWEEN 1 AND 256", b"length(request_key) BETWEEN 1 AND 255"),
        (b"AND length(request_key) BETWEEN 1 AND 256", b""),
        (b"typeof(request_key) = 'blob'", b"typeof(request_key) = 'text'"),
    )
    for original, replacement in request_key_mutations:
        mutated_sql = migration_sql.replace(original, replacement)
        assert mutated_sql != migration_sql
        migration_path.write_bytes(mutated_sql)
        assert migration_path in _migration_sql_violations(tmp_path / "src" / "neontof")


def test_sqlite_scan_rejects_transaction_sql_with_semicolon_comment_trailing_token_end_savepoint_and_release(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/sqlite_database.py",
        """
import sqlite3

def _rollback(connection: sqlite3.Connection) -> None:
    connection.execute(\"ROLLBACK;\")
    connection.execute(\"END\")
    connection.execute(\"SAVEPOINT nested\")
    connection.execute(\"RELEASE nested\")

class SqliteDatabase:
    def _write(self, connection: sqlite3.Connection) -> None:
        connection.execute(\"BEGIN IMMEDIATE -- trailing\")
        connection.execute(\"COMMIT extra\")
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_exact_pragma_positive_calls_are_allowed() -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_scan_rejects_unapproved_pragma_setter_or_value(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/sqlite_database.py",
        """
import sqlite3

class SqliteDatabase:
    def _open_connection(self, connection: sqlite3.Connection) -> None:
        connection.execute(\"PRAGMA journal_mode=DELETE\")
        connection.execute(\"PRAGMA busy_timeout=100\")
        connection.execute(\"PRAGMA foreign_keys=ON\")
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_bounded_cursor_flow_is_allowed(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/cursor_reader.py",
        """
import sqlite3

def read(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    cursor = connection.cursor()
    try:
        return tuple(cursor.fetchmany(256))
    finally:
        cursor.close()
""",
    )

    assert _sqlite_usage_violations(synthetic_root) == []


def test_sqlite_scan_rejects_cursor_flow_escape_and_unknown_callback(tmp_path: Path) -> None:
    cases = {
        "callback": """
import sqlite3

def read(connection: sqlite3.Connection, callback: object) -> object:
    cursor = object().cursor()
    cursor.execute(\"SELECT 1\")
    return callback(cursor)
""",
        "return_cursor": """
import sqlite3

def read(connection: sqlite3.Connection) -> sqlite3.Cursor:
    cursor = connection.cursor()
    return cursor
""",
        "yield_cursor": """
import sqlite3

def read(connection: sqlite3.Connection):
    cursor = connection.cursor()
    yield cursor
""",
        "duplicate_known_callback": """
import sqlite3

def _query_bounded(connection: sqlite3.Connection, sql: str) -> object:
    cursor: sqlite3.Cursor
    _fetch_bounded(cursor, start=0.0, deadline_seconds=1.0, monotonic=object())
    _fetch_bounded(cursor, start=0.0, deadline_seconds=1.0, monotonic=object())
    return None
""",
        "borrowed_cursor": """
import sqlite3

def read(cursor: sqlite3.Cursor) -> tuple[tuple[object, ...], ...]:
    return tuple(cursor.fetchmany(256))
""",
        "nested_conditional_finally": """
import sqlite3

def read(connection: sqlite3.Connection, enabled: bool) -> None:
    cursor = connection.cursor()
    try:
        cursor.fetchmany(256)
    finally:
        if enabled:
            cursor.close()
""",
        "nested_loop_finally": """
import sqlite3

def read(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.fetchmany(256)
    finally:
        for _ in range(1):
            cursor.close()
""",
        "conditional_close": """
import sqlite3

def read(connection: sqlite3.Connection, enabled: bool) -> None:
    if enabled:
        cursor = connection.cursor()
        cursor.fetchmany(256)
        cursor.close()
""",
        "close_before_use": """
import sqlite3

def read(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    cursor.close()
    cursor.fetchmany(256)
""",
        "alias_close": """
import sqlite3

def read(connection: sqlite3.Connection) -> None:
    cursor = connection.cursor()
    alias = cursor
    try:
        alias.fetchmany(256)
    finally:
        cursor.close()
        alias.close()
""",
        "comprehension_capture": """
import sqlite3

def read(connection: sqlite3.Connection) -> tuple[object, ...]:
    cursor = connection.cursor()
    try:
        return tuple(row for row in cursor.fetchmany(256))
    finally:
        cursor.close()
""",
        "nested_function_capture": """
import sqlite3

def read(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    cursor = connection.cursor()

    def consume() -> tuple[tuple[object, ...], ...]:
        return tuple(cursor.fetchmany(256))

    try:
        return consume()
    finally:
        cursor.close()
""",
    }

    for case_name, source in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(
            synthetic_root,
            "persistence/migrations.py"
            if case_name == "duplicate_known_callback"
            else f"persistence/cursor_{case_name}.py",
            source,
        )
        assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_existing_backup_chain_and_source_backup_direction_are_allowed() -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_scan_rejects_backup_receiver_argument_and_destination_bypass(
    tmp_path: Path,
) -> None:
    cases = {
        "wrong_receiver": """
import sqlite3

def _copy_database_with_deadline(source: object, destination: sqlite3.Connection) -> None:
    destination.backup(source, pages=1, sleep=0.0, name=\"temp\", progress=None)
""",
        "missing_deadline": """
import sqlite3

class _BackupSource:
    pass

def _copy_database_with_deadline(
    source: _BackupSource, destination: sqlite3.Connection
) -> None:
    def progress(status: int, remaining: int, total: int) -> None:
        return None

    source.backup(
        destination,
        pages=_BACKUP_PAGES_PER_STEP,
        sleep=_BACKUP_RETRY_SLEEP_SECONDS,
        name=\"main\",
        progress=progress,
    )
""",
        "missing_post_verification": """
import sqlite3

def _backup_existing_database(
    migration_connection: sqlite3.Connection, database_path: object
) -> object:
    backup_source: sqlite3.Connection
    destination: sqlite3.Connection
    _copy_database_with_deadline(backup_source, destination)
    return database_path
""",
    }

    for case_name, source in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(
            synthetic_root,
            "persistence/migrations.py"
            if case_name in {"missing_deadline", "missing_post_verification"}
            else f"persistence/{case_name}.py",
            source,
        )
        assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_pure_sqlite_constants_and_known_callback_are_allowed() -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_scan_rejects_deserialize_extension_exitstack_methodcaller_partial_and_lambda_capture(
    tmp_path: Path,
) -> None:
    cases = {
        "protocol": """
import sqlite3
from contextlib import ExitStack
from functools import partial
from operator import methodcaller

def unsafe(connection: sqlite3.Connection, callback: object) -> None:
    connection.deserialize(b\"db\")
    connection.enable_load_extension(True)
    with ExitStack() as stack:
        stack.callback(callback)
    methodcaller(\"execute\", \"SELECT 1\")(connection)
    partial(callback, connection)()
    callback(lambda: connection.execute(\"SELECT 1\"))
""",
        "saved_lambda": """
import sqlite3

def unsafe(connection: sqlite3.Connection) -> object:
    callback = lambda: connection.execute(\"SELECT 1\")
    return callback
""",
        "decoy_write": """
import sqlite3

class OtherDatabase:
    def _write(self, operation: object) -> None:
        return None

def unsafe(connection: sqlite3.Connection, database: OtherDatabase) -> None:
    database._write(lambda: connection.execute(\"SELECT 1\"))
""",
    }

    for case_name, source in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(
            synthetic_root, f"persistence/{case_name}.py", source
        )
        assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_projection_rebuild_and_claim_have_two_same_connection_readers() -> None:
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_cross_module_scan_rejects_claim_read_campaign_or_nested_write(tmp_path: Path) -> None:
    cases = {
        "direct": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            events = self._event_store.read_campaign(campaign_id)
            self._event_store.claim(campaign_id)
            self._database._write(lambda inner: inner.execute(\"DELETE FROM events\"))
            return events

        return self._database._write(operation)
""",
        "reader_alias": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            reader = self._event_store._read_campaign_on_connection
            return reader(connection, campaign_id)

        return self._database._write(operation)
""",
        "reader_rebind": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            reader = self._event_store._read_campaign_on_connection
            reader = object()
            return reader(connection, campaign_id)

        return self._database._write(operation)
""",
        "read_campaign_alias": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            store = self._event_store
            return store.read_campaign(campaign_id)

        return self._database._write(operation)
""",
        "claim_alias": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            claim = self._event_store.claim
            return claim(campaign_id)

        return self._database._write(operation)
""",
        "write_alias": """
import sqlite3

class ProjectionStore:
    def rebuild(self, campaign_id: str) -> object:
        def operation(connection: sqlite3.Connection) -> object:
            writer = self._database._write
            return writer(lambda inner: inner.execute("DELETE FROM events"))

        return self._database._write(operation)
""",
    }

    for case_name, source in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(
            synthetic_root, "persistence/projection_store.py", source
        )
        assert rejected_path in _cross_module_violations(synthetic_root)


def test_eventstore_append_caller_allowlist_requires_exact_qualified_path_and_count(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "application/turn_lifecycle.py",
        """
class TurnLifecycleCoordinator:
    def execute(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        store = self._event_store
        store.append(batch)

    def revert_latest(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        store = self._event_store
        store.append(batch)
""",
    )

    records, _ = _source_records(synthetic_root)
    synthetic_counts: dict[tuple[str, str], int] = {}
    for record in records:
        for call, qualified_name in record.visitor.calls:
            if _append_receiver_is_event_store(call, record.visitor):
                key = (record.relative_path, qualified_name)
                synthetic_counts[key] = synthetic_counts.get(key, 0) + 1
    assert synthetic_counts == {
        (
            "src/neontof/application/turn_lifecycle.py",
            "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.execute",
        ): 1,
        (
            "src/neontof/application/turn_lifecycle.py",
            "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.revert_latest",
        ): 1,
    }
    assert sum(synthetic_counts.values()) == P1_03_EVENTSTORE_CALLER_COUNT
    production_records, _ = _source_records(PRODUCTION_ROOT)
    production_counts: dict[tuple[str, str], int] = {}
    for record in production_records:
        for call, qualified_name in record.visitor.calls:
            if _append_receiver_is_event_store(call, record.visitor):
                key = (record.relative_path, qualified_name)
                production_counts[key] = production_counts.get(key, 0) + 1
    assert production_counts == {
        (
            "src/neontof/application/turn_lifecycle.py",
            "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.execute",
        ): 1,
        (
            "src/neontof/application/turn_lifecycle.py",
            "neontof.application.turn_lifecycle.TurnLifecycleCoordinator.revert_latest",
        ): 1,
    }
    assert sum(production_counts.values()) == CURRENT_EVENTSTORE_CALLER_COUNT
    assert _eventstore_append_caller_violations(PRODUCTION_ROOT) == []
    assert _sqlite_usage_violations(synthetic_root) == []


def test_eventstore_append_caller_allowlist_rejects_wrong_path_same_name_duplicate_and_other_owner(
    tmp_path: Path,
) -> None:
    cases = {
        "wrong_path": (
            "application/other.py",
            """
class TurnLifecycleCoordinator:
    def execute(self) -> None:
        self._event_store.append(batch)
""",
        ),
        "duplicate": (
            "application/turn_lifecycle.py",
            """
class TurnLifecycleCoordinator:
    def execute(self) -> None:
        self._event_store.append(first)
        self._event_store.append(second)

class OtherCoordinator:
    def revert_latest(self) -> None:
        self._event_store.append(batch)
""",
        ),
        "alias_rebind": (
            "application/turn_lifecycle.py",
            """
class TurnLifecycleCoordinator:
    def execute(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        store = self._event_store
        store = object()
        store.append(batch)

    def revert_latest(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        self._event_store.append(batch)
""",
        ),
        "missing_execute": (
            "application/turn_lifecycle.py",
            """
class TurnLifecycleCoordinator:
    def execute(self, event_store: object, batch: object) -> None:
        return None

    def revert_latest(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        self._event_store.append(batch)
""",
        ),
        "missing_revert_latest": (
            "application/turn_lifecycle.py",
            """
class TurnLifecycleCoordinator:
    def execute(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        self._event_store.append(batch)

    def revert_latest(self, event_store: object, batch: object) -> None:
        return None
        """,
        ),
        "missing_method_definition": (
            "application/turn_lifecycle.py",
            """
class TurnLifecycleCoordinator:
    def revert_latest(self, event_store: object, batch: object) -> None:
        self._event_store = event_store
        self._event_store.append(batch)
""",
        ),
        "direct_event_store_constructor": (
            "application/other.py",
            """
class EventStore:
    pass

def execute(database: object, batch: object) -> None:
    EventStore(database).append(batch)
""",
        ),
        "constructor_alias": (
            "application/other.py",
            """
class EventStore:
    pass

def execute(database: object, batch: object) -> None:
    store = EventStore(database)
    store.append(batch)
""",
        ),
    }

    for case_name, (relative_path, source) in cases.items():
        synthetic_root = _synthetic_production_root(tmp_path / case_name)
        rejected_path = _write_synthetic_source(synthetic_root, relative_path, source)
        assert rejected_path in _eventstore_append_caller_violations(synthetic_root)


def test_eventstore_append_caller_allowlist_rejects_third_callsite(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "application/turn_lifecycle.py",
        """
class TurnLifecycleCoordinator:
    def append_bootstrap(self) -> None:
        self._event_store.append(batch)
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)


def test_events_dml_allowlist_requires_exact_storage_path_and_nested_operation(
    tmp_path: Path,
) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    _write_synthetic_source(
        synthetic_root,
        "persistence/event_store.py",
        """
import sqlite3

class EventStore:
    def append(self, batch: object) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(\"INSERT INTO events(event_id) VALUES (?)\", (batch,))

        operation(None)
""",
    )

    assert _sqlite_usage_violations(synthetic_root) == []


def test_events_dml_allowlist_rejects_duplicate_insert_and_other_owner(tmp_path: Path) -> None:
    synthetic_root = _synthetic_production_root(tmp_path)
    rejected_path = _write_synthetic_source(
        synthetic_root,
        "persistence/other_store.py",
        """
import sqlite3

class OtherStore:
    def write(self, connection: sqlite3.Connection) -> None:
        def operation() -> None:
            connection.execute(\"INSERT INTO events(event_id) VALUES (?)\", (\"x\",))

        operation()
""",
    )

    assert rejected_path in _sqlite_usage_violations(synthetic_root)
