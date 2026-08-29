"""Phase 0 manifestとPhase 1 repository guard境界を検証する契約テスト。"""

import ast
import re
import tomllib
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
PHASE_1_ALLOWED_EXACT_PATHS = frozenset(
    {
        ".node-version",
        "client",
        "client/package-lock.json",
        "client/package.json",
        "client/tsconfig.json",
        "src/neontof/persistence",
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
    def __init__(self) -> None:
        self.sqlite_module_names: set[str] = {"sqlite3"}
        self.sqlite_symbol_names: set[str] = set()
        self.sqlite_star_imported = False
        self.uses_sqlite = False

    @staticmethod
    def _is_sqlite_module(module_name: str) -> bool:
        return module_name == "sqlite3" or module_name.startswith("sqlite3.")

    @staticmethod
    def _attribute_root_name(node: ast.AST) -> str | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            if self._is_sqlite_module(imported.name):
                self.sqlite_module_names.add(imported.asname or imported.name.split(".", 1)[0])
                self.uses_sqlite = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = node.module or ""
        if node.level == 0 and self._is_sqlite_module(module_name):
            self.uses_sqlite = True
            for imported in node.names:
                if imported.name in {"connect", "Connection"}:
                    self.sqlite_symbol_names.add(imported.asname or imported.name)
                elif imported.name == "*":
                    self.sqlite_star_imported = True
        elif {"persistence", "sqlite"}.intersection(module_name.split(".")) and any(
            imported.name in {"connect", "Connection", "*"} for imported in node.names
        ):
            self.uses_sqlite = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr in {"connect", "Connection"}
            and self._attribute_root_name(node.value) in self.sqlite_module_names
        ):
            self.uses_sqlite = True
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and (
            node.id in self.sqlite_symbol_names or self.sqlite_star_imported
        ):
            self.uses_sqlite = True
        self.generic_visit(node)


def _sqlite_usage_violations(production_root: Path) -> list[Path]:
    violations: list[Path] = []
    for path in production_root.rglob("*.py"):
        source_text = path.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(path))
        visitor = _SqliteUsageVisitor()
        visitor.visit(tree)
        relative_parts = path.relative_to(production_root).parts
        if visitor.uses_sqlite and (not relative_parts or relative_parts[0] != "persistence"):
            violations.append(path)
    return sorted(violations)


def _repository_guard_violations(repository_root: Path) -> list[Path]:
    violations: list[Path] = []
    for path in repository_root.rglob("*"):
        relative_path = path.relative_to(repository_root)
        relative_parts = relative_path.parts
        if any(part in GENERATED_DIRECTORY_NAMES for part in relative_parts):
            continue
        is_phase_1_scoped_path = (
            "client" in relative_parts
            or "migrations" in relative_parts
            or relative_parts[:3]
            in {
                ("src", "neontof", "persistence"),
                ("src", "neontof", "persistence_like"),
            }
        )
        if is_phase_1_scoped_path and not _is_phase_1_allowed_path(relative_path):
            violations.append(path)
            continue
        if _is_forbidden_database_artifact(relative_path):
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
        ]
    )

    assert "event_metadata.py" in production_files


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


def test_sqlite_connections_are_allowed_only_in_persistence(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "neontof"
    (synthetic_root / "persistence").mkdir(parents=True)
    (synthetic_root / "persistence" / "database.py").write_text(
        "import sqlite3\nconnection = sqlite3.connect(':memory:')\n"
        "connection_type: type[sqlite3.Connection]\n",
        encoding="utf-8",
    )
    (synthetic_root / "persistence_like").mkdir()
    rejected_path = synthetic_root / "persistence_like" / "database.py"
    rejected_path.write_text(
        "import sqlite3\nconnection = sqlite3.connect(':memory:')\n", encoding="utf-8"
    )
    application_path = synthetic_root / "application" / "persistence.py"
    application_path.parent.mkdir()
    application_path.write_text(
        "import sqlite3\nconnection = sqlite3.connect(':memory:')\n", encoding="utf-8"
    )
    comment_only_path = synthetic_root / "application" / "comment_only.py"
    comment_only_path.write_text(
        "# sqlite3.connect(':memory:')\nvalue = 'sqlite3.Connection'\n", encoding="utf-8"
    )

    violations = _sqlite_usage_violations(synthetic_root)
    assert rejected_path in violations
    assert application_path in violations
    assert comment_only_path not in violations
    assert not any(path.parent.name == "persistence" for path in violations)
    assert _sqlite_usage_violations(PRODUCTION_ROOT) == []


def test_sqlite_source_scan_rejects_alias_and_import_variants_outside_persistence(
    tmp_path: Path,
) -> None:
    synthetic_root = tmp_path / "neontof"
    outside_root = synthetic_root / "application"
    outside_root.mkdir(parents=True)
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
        "deep_wildcard.py": ("from sqlite3.dbapi2 import *\nconnection = connect(':memory:')\n"),
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
    rejected_paths: list[Path] = []
    for filename, source in variants.items():
        path = outside_root / filename
        path.write_text(source, encoding="utf-8")
        rejected_paths.append(path)

    helper_path = outside_root / "relative_helper.py"
    helper_path.write_text("from ..persistence import helper\nvalue = helper()\n", encoding="utf-8")
    absolute_application_helper_path = outside_root / "absolute_application_helper.py"
    absolute_application_helper_path.write_text(
        "from neontof.application import helper\nvalue = helper()\n", encoding="utf-8"
    )
    absolute_persistence_helper_path = outside_root / "absolute_persistence_helper.py"
    absolute_persistence_helper_path.write_text(
        "from neontof.persistence import helper\nvalue = helper()\n", encoding="utf-8"
    )

    persistence_root = synthetic_root / "persistence"
    persistence_root.mkdir()
    (persistence_root / "aliases.py").write_text(
        "import sqlite3 as db\nconnection = db.connect(':memory:')\n", encoding="utf-8"
    )
    (persistence_root / "deep_aliases.py").write_text(
        "import sqlite3.dbapi2 as db\nconnection = db.connect(':memory:')\n", encoding="utf-8"
    )

    violations = _sqlite_usage_violations(synthetic_root)
    assert set(rejected_paths) <= set(violations)
    assert helper_path not in violations
    assert absolute_application_helper_path not in violations
    assert absolute_persistence_helper_path not in violations


def test_repository_guard_rejects_database_files_in_repository_tree(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repository"
    synthetic_root.mkdir()
    (synthetic_root / "state.sqlite").write_bytes(b"not a database")
    nested_path = synthetic_root / "client" / "node_modules" / "cache.db"
    nested_path.parent.mkdir(parents=True)
    nested_path.write_bytes(b"not a database")

    violations = _repository_guard_violations(synthetic_root)
    assert synthetic_root / "state.sqlite" in violations
    assert nested_path not in violations
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
