"""P1-05 YAML authoring input boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from neontof.authoring.character_loader import load_character_sheet
from neontof.authoring.yaml_loader import load_yaml_document
from pydantic import ValidationError

CHARACTER_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "characters" / "minimal-character.v1.yaml"
)


def test_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_bytes(b"root:\n  id: first\n  id: second\n")

    with pytest.raises(ValueError):
        load_yaml_document(duplicate)


def test_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown-character.yaml"
    unknown.write_bytes(CHARACTER_FIXTURE.read_bytes() + b"unexpected: true\n")

    with pytest.raises(ValidationError):
        load_character_sheet(unknown)

    unsafe = tmp_path / "unsafe-constructor.yaml"
    unsafe.write_bytes(b'value: !!python/object/apply:builtins.str ["unsafe"]\n')
    with pytest.raises((ValueError, yaml.YAMLError)):
        load_yaml_document(unsafe)


def test_loader_rejects_non_utf8(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid-utf8.yaml"
    invalid_utf8.write_bytes(b"value: \xff\n")
    bom_prefixed = tmp_path / "bom-prefixed.yaml"
    bom_prefixed.write_bytes(b"\xef\xbb\xbfvalue: valid\n")

    with pytest.raises(ValueError):
        load_yaml_document(invalid_utf8)
    with pytest.raises(ValueError):
        load_yaml_document(bom_prefixed)


def test_loader_rejects_document_over_size_limit(tmp_path: Path) -> None:
    exact_limit = tmp_path / "exact-limit.yaml"
    exact_limit.write_bytes(b"a: 1\n")
    over_limit = tmp_path / "over-limit.yaml"
    over_limit.write_bytes(b"a: 12\n")

    assert load_yaml_document(exact_limit, max_bytes=5) == {"a": 1}
    with pytest.raises(ValueError):
        load_yaml_document(over_limit, max_bytes=5)
