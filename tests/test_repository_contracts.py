"""Phase 0のmanifestと境界を検証するrepository-level契約テスト。"""

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
}


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


def _tracked_candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in REPOSITORY_ROOT.rglob("*"):
        relative_parts = path.relative_to(REPOSITORY_ROOT).parts
        if path.is_file() and not any(part in GENERATED_DIRECTORY_NAMES for part in relative_parts):
            files.append(path)
    return files


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


def test_repository_contracts_fix_ci_order_and_windows_runner() -> None:
    ci_text = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "runs-on: windows-latest" in ci_text
    assert "node" not in ci_text.lower()
    assert "npm" not in ci_text.lower()

    commands = [
        'py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"',
        "py -3.14 -m venv .venv",
        ".venv/Scripts/python -m pip install --require-hashes -r requirements.lock.txt",
        ".venv/Scripts/python -m pip check",
        ".venv/Scripts/python -m compileall -q src",
        ".venv/Scripts/python -m ruff format --check src tests",
        ".venv/Scripts/python -m ruff check src tests",
        '.venv/Scripts/python -m mypy --strict src tests --exclude "tests/typecheck_fixtures"',
        ".venv/Scripts/python -m pytest -q",
    ]
    positions = [ci_text.index(command) for command in commands]
    assert positions == sorted(positions)


def test_repository_contracts_fix_production_manifest_and_forbidden_paths() -> None:
    production_files = sorted(
        path.relative_to(PRODUCTION_ROOT).as_posix() for path in PRODUCTION_ROOT.rglob("*.py")
    )
    assert production_files == [
        "__init__.py",
        "app.py",
        "config.py",
        "contracts/__init__.py",
        "contracts/base.py",
        "contracts/domain.py",
        "contracts/event_parser.py",
        "contracts/ids.py",
        "contracts/projection.py",
        "contracts/turn_status.py",
        "main.py",
    ]

    forbidden_names = {
        "package.json",
        "package-lock.json",
        ".node-version",
        "Dockerfile",
        "tsconfig.json",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "vitest.config.ts",
    }
    all_files = _tracked_candidate_files()
    assert not [path for path in all_files if path.name in forbidden_names]
    assert not [
        path
        for path in REPOSITORY_ROOT.rglob("*")
        if path.is_dir() and path.name in {"client", "migrations"}
    ]
    forbidden_sdk_name = "open" + "ai"
    forbidden_registry_name = "provider" + "_registry.py"
    assert not list(PRODUCTION_ROOT.rglob(f"{forbidden_sdk_name}*.py"))
    assert not list(PRODUCTION_ROOT.rglob(forbidden_registry_name))
    assert not [path for path in all_files if path.name.endswith((".sqlite", ".db"))]

    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in PRODUCTION_ROOT.rglob("*.py")
    )
    assert forbidden_sdk_name not in source_text.lower()
    assert "sqlite3.connect" not in source_text
    assert "sqlite3.Connection" not in source_text
    forbidden_provider_names = ("ProviderRegistry", "provider_registry")
    for forbidden_provider_name in forbidden_provider_names:
        assert forbidden_provider_name not in source_text
    assert "background worker" not in source_text.lower()


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
