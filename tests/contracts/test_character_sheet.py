"""P0-05 Character Sheetのtest-first契約。"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from operator import setitem
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "characters" / "minimal-character.v1.yaml"
TUPLE_FIELD_PATHS: tuple[tuple[str, ...], ...] = (
    ("aliases",),
    ("initial_items",),
    ("speech_style", "endings"),
    ("speech_style", "forbidden_patterns"),
)

type PathPart = str | int


class _TupleSubclass(tuple[object, ...]):
    pass


class _ListSubclass(list[object]):
    pass


class _ArbitraryIterable:
    def __iter__(self) -> Iterator[object]:
        return iter(())


def _fixture_text() -> str:
    return FIXTURE_PATH.read_bytes().decode("utf-8")


def _fixture_raw() -> dict[str, object]:
    loaded = yaml.safe_load(_fixture_text())
    assert isinstance(loaded, dict)
    return cast(dict[str, object], loaded)


def _character_sheet_module() -> Any:
    return importlib.import_module("neontof.contracts.character_sheet")


def _validate(raw: object) -> Any:
    return _character_sheet_module().CHARACTER_SHEET_ADAPTER.validate_python(raw, strict=True)


def _get_path(root: object, path: tuple[PathPart, ...]) -> object:
    current = root
    for part in path:
        if isinstance(part, str):
            assert isinstance(current, dict)
            current = current[part]
        else:
            assert isinstance(current, list)
            current = current[part]
    return current


def _set_path(root: dict[str, object], path: tuple[PathPart, ...], value: object) -> None:
    assert path
    current: object = root
    for part in path[:-1]:
        if isinstance(part, str):
            assert isinstance(current, dict)
            current = current[part]
        else:
            assert isinstance(current, list)
            current = current[part]

    last = path[-1]
    if isinstance(last, str):
        assert isinstance(current, dict)
        current[last] = value
    else:
        assert isinstance(current, list)
        current[last] = value


def _get_model_path(model: object, path: tuple[PathPart, ...]) -> Any:
    current = model
    for part in path:
        if isinstance(part, str):
            current = getattr(current, part)
        else:
            assert isinstance(current, tuple)
            current = current[part]
    return current


def test_fixture_is_bom_free_utf8_and_japanese_values_round_trip() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()

    assert not raw_bytes.startswith(b"\xef\xbb\xbf")
    text = raw_bytes.decode("utf-8")
    assert "星野 花" in text
    assert "ハナ" in text
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    assert loaded["canonical_name"] == "星野 花"
    assert loaded["aliases"] == ["花", "ハナ"]


def test_valid_japanese_fixture_is_safe_loaded_and_validated() -> None:
    sheet = _validate(_fixture_raw())

    assert sheet.schema_version == 1
    assert sheet.id == "character:hana"
    assert sheet.canonical_name == "星野 花"
    assert sheet.aliases == ("花", "ハナ")
    assert sheet.description == "森の境界を守る旅人。"
    assert sheet.hp.current == 7
    assert sheet.hp.max == 10
    assert sheet.resource.id == "resource:stamina"
    assert sheet.resource.current == 3
    assert sheet.resource.max == 5
    assert sheet.initial_items[0].id == "item:lantern"
    assert sheet.initial_items[0].canonical_name == "古いランタン"
    assert sheet.initial_location_id == "location:forest-edge"
    assert sheet.visibility == "player_visible"
    assert sheet.speech_style is not None
    assert sheet.speech_style.first_person == "私"
    assert sheet.speech_style.second_person == "あなた"
    assert sheet.speech_style.endings == ("です", "ます")
    assert sheet.speech_style.forbidden_patterns == ("ひどい",)
    assert sheet.ruleset.id == "ruleset:neontof-minimal-2d6-v1"
    assert sheet.ruleset.action_modifier == 1


def test_visibility_is_required() -> None:
    raw = _fixture_raw()
    del raw["visibility"]

    with pytest.raises(ValidationError):
        _validate(raw)


def test_visibility_null_is_rejected() -> None:
    raw = _fixture_raw()
    raw["visibility"] = None

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize("visibility", ("gm_only", "player_visible", "npc:watcher"))
def test_visibility_accepts_only_the_declared_kinds(visibility: str) -> None:
    raw = _fixture_raw()
    raw["visibility"] = visibility

    sheet = _validate(raw)

    assert sheet.visibility == visibility


@pytest.mark.parametrize(
    "visibility", ("character:hana", "npc:", "npc:Watcher", "npc:bad--slug", True)
)
def test_visibility_rejects_wrong_kind_or_non_string(visibility: object) -> None:
    raw = _fixture_raw()
    raw["visibility"] = visibility

    with pytest.raises(ValidationError):
        _validate(raw)


def test_speech_style_may_be_omitted() -> None:
    raw = _fixture_raw()
    del raw["speech_style"]

    sheet = _validate(raw)

    assert sheet.speech_style is None


def test_speech_style_may_be_explicitly_null() -> None:
    raw = _fixture_raw()
    raw["speech_style"] = None

    sheet = _validate(raw)

    assert sheet.speech_style is None


def test_character_resource_state_identity_and_root_exports_are_preserved() -> None:
    module = _character_sheet_module()
    root = importlib.import_module("neontof.contracts")
    from neontof.contracts import projection

    assert module.ResourceState.__module__ == "neontof.contracts.character_sheet"
    assert projection.ResourceState.__module__ == "neontof.contracts.projection"
    assert module.ResourceState is not projection.ResourceState
    assert root.ResourceState is projection.ResourceState
    for name in ("CharacterSheetV1", "CHARACTER_SHEET_ADAPTER", "HitPoints"):
        assert name not in root.__all__
        assert not hasattr(root, name)


def test_exact_yaml_sequences_are_copied_to_tuples_and_input_mutation_does_not_propagate() -> None:
    raw = _fixture_raw()
    expected = {path: tuple(cast(list[object], _get_path(raw, path))) for path in TUPLE_FIELD_PATHS}

    sheet = _validate(raw)

    for path, expected_value in expected.items():
        model_value = _get_model_path(sheet, path)
        assert type(model_value) is tuple
        if path == ("initial_items",):
            assert tuple(item.model_dump(mode="python") for item in model_value) == expected_value
        else:
            assert model_value == expected_value

    for path in TUPLE_FIELD_PATHS:
        source_value = _get_path(raw, path)
        assert isinstance(source_value, list)
        source_value.append("入力側の変更")

    assert sheet.aliases == expected[("aliases",)]
    assert sheet.initial_items == tuple(
        _character_sheet_module().InitialItem.model_validate(item, strict=True)
        for item in expected[("initial_items",)]
    )
    assert sheet.speech_style is not None
    assert sheet.speech_style.endings == expected[("speech_style", "endings")]
    assert sheet.speech_style.forbidden_patterns == expected[("speech_style", "forbidden_patterns")]


def test_exact_tuple_inputs_are_copied_and_nested_input_mutation_does_not_propagate() -> None:
    raw = _fixture_raw()
    tuple_inputs: dict[tuple[str, ...], tuple[object, ...]] = {}
    for path in TUPLE_FIELD_PATHS:
        source_value = _get_path(raw, path)
        assert isinstance(source_value, list)
        tuple_value = tuple(source_value)
        tuple_inputs[path] = tuple_value
        _set_path(raw, path, tuple_value)

    initial_item = cast(
        dict[str, object],
        cast(list[object], _get_path(raw, ("initial_items",)))[0],
    )
    sheet = _validate(raw)
    initial_item["canonical_name"] = "入力側の変更"

    for path, input_value in tuple_inputs.items():
        model_value = _get_model_path(sheet, path)
        assert type(model_value) is tuple
        assert len(model_value) == len(input_value)
        assert model_value is not input_value
    assert sheet.initial_items[0].canonical_name == "古いランタン"


@pytest.mark.parametrize("path", TUPLE_FIELD_PATHS)
@pytest.mark.parametrize(
    "invalid_kind", ("list_subclass", "tuple_subclass", "generator", "set", "iterable")
)
def test_sequence_fields_accept_only_exact_list_or_tuple(
    path: tuple[str, ...], invalid_kind: str
) -> None:
    raw = _fixture_raw()
    valid_value = _get_path(raw, path)
    assert isinstance(valid_value, list)

    invalid_value: object
    if invalid_kind == "list_subclass":
        invalid_value = _ListSubclass(valid_value)
    elif invalid_kind == "tuple_subclass":
        invalid_value = _TupleSubclass(tuple(valid_value))
    elif invalid_kind == "generator":
        invalid_value = (item for item in valid_value)
    elif invalid_kind == "set":
        invalid_value = set()
    else:
        invalid_value = _ArbitraryIterable()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("field_name", "current", "maximum"),
    (
        ("hp", 0, 0),
        ("hp", 10, 10),
        ("hp", 4, 10),
        ("resource", 0, 0),
        ("resource", 5, 5),
        ("resource", 2, 5),
    ),
)
def test_hp_and_resource_accept_zero_max_and_current_at_or_below_max(
    field_name: str, current: int, maximum: int
) -> None:
    raw = _fixture_raw()
    _set_path(raw, (field_name, "current"), current)
    _set_path(raw, (field_name, "max"), maximum)

    sheet = _validate(raw)
    state = getattr(sheet, field_name)

    assert state.current == current
    assert state.max == maximum


@pytest.mark.parametrize(
    ("field_name", "current", "maximum"),
    (
        ("hp", -1, 10),
        ("hp", 11, 10),
        ("hp", 0, -1),
        ("resource", -1, 5),
        ("resource", 6, 5),
        ("resource", 0, -1),
    ),
)
def test_hp_and_resource_reject_negative_or_over_max_bounds(
    field_name: str, current: int, maximum: int
) -> None:
    raw = _fixture_raw()
    _set_path(raw, (field_name, "current"), current)
    _set_path(raw, (field_name, "max"), maximum)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    (
        (("id",), "npc:hana"),
        (("resource", "id"), "item:stamina"),
        (("initial_items", 0, "id"), "resource:lantern"),
        (("initial_location_id",), "scene:forest"),
    ),
)
def test_ids_reject_a_value_of_the_wrong_kind(
    path: tuple[PathPart, ...], invalid_value: object
) -> None:
    raw = _fixture_raw()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    (
        (("id",), "character:Bad"),
        (("resource", "id"), "resource:"),
        (("initial_items", 0, "id"), "item:bad--slug"),
        (("initial_location_id",), "location:bad-"),
        (("ruleset", "id"), "ruleset:bad--slug"),
    ),
)
def test_ids_reject_same_kind_values_with_invalid_slug_grammar(
    path: tuple[PathPart, ...], invalid_value: object
) -> None:
    raw = _fixture_raw()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    (
        (("hp", "current"), "7"),
        (("hp", "max"), True),
        (("resource", "current"), "3"),
        (("resource", "max"), False),
        (("ruleset", "action_modifier"), "1"),
        (("ruleset", "action_modifier"), True),
    ),
)
def test_numeric_fields_reject_string_and_bool_numbers(
    path: tuple[PathPart, ...], invalid_value: object
) -> None:
    raw = _fixture_raw()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize("aliases", (("", "ハナ"), ("花", "花")))
def test_aliases_reject_empty_and_duplicate_values(aliases: tuple[str, ...]) -> None:
    raw = _fixture_raw()
    raw["aliases"] = list(aliases)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    (
        (("extra",), "reject"),
        (("hp", "extra"), "reject"),
        (("resource", "extra"), "reject"),
        (("initial_items", 0, "extra"), "reject"),
        (("speech_style", "extra"), "reject"),
        (("ruleset", "extra"), "reject"),
    ),
)
def test_unknown_fields_are_rejected_at_every_nested_contract_boundary(
    path: tuple[PathPart, ...], invalid_value: object
) -> None:
    raw = _fixture_raw()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    (
        (("schema_version",), 2),
        (("schema_version",), "1"),
        (("schema_version",), True),
        (("ruleset", "id"), "ruleset:other-v1"),
        (("ruleset", "id"), 1),
    ),
)
def test_schema_version_and_ruleset_are_fixed_and_strict(
    path: tuple[PathPart, ...], invalid_value: object
) -> None:
    raw = _fixture_raw()
    _set_path(raw, path, invalid_value)

    with pytest.raises(ValidationError):
        _validate(raw)


def test_character_sheet_and_nested_models_are_frozen() -> None:
    sheet = _validate(_fixture_raw())

    with pytest.raises(ValidationError):
        sheet.canonical_name = "変更"
    with pytest.raises(ValidationError):
        sheet.hp.current = 1
    with pytest.raises(ValidationError):
        sheet.resource.max = 99
    with pytest.raises(ValidationError):
        sheet.initial_items[0].canonical_name = "変更"
    assert sheet.speech_style is not None
    with pytest.raises(ValidationError):
        sheet.speech_style.first_person = "変更"
    with pytest.raises(ValidationError):
        sheet.ruleset.action_modifier = 2


def test_all_public_sequence_fields_are_tuples_and_tuple_mutation_fails() -> None:
    sheet = _validate(_fixture_raw())

    for path in TUPLE_FIELD_PATHS:
        value = _get_model_path(sheet, path)
        assert type(value) is tuple
        with pytest.raises(TypeError):
            setitem(cast(list[object], value), 0, value[0])


@pytest.mark.parametrize(
    ("nested_path", "field_name", "invalid_value"),
    (
        (("hp",), "current", 11),
        (("resource",), "current", 6),
        (("initial_items", 0), "id", "item:"),
        (("speech_style",), "first_person", 1),
        (("ruleset",), "action_modifier", True),
    ),
)
def test_revalidation_rejects_sabotaged_nested_instances(
    nested_path: tuple[PathPart, ...], field_name: str, invalid_value: object
) -> None:
    module = _character_sheet_module()
    sheet = _validate(_fixture_raw())
    nested = _get_model_path(sheet, nested_path)
    object.__setattr__(nested, field_name, invalid_value)

    with pytest.raises(ValidationError):
        module.CHARACTER_SHEET_ADAPTER.validate_python(sheet, strict=True)
