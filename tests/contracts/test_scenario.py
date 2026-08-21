"""P0-06 Scenario FormatのTest First契約。"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from neontof.contracts.ids import NpcId, Visibility
from tests.contracts.support.validate_scenario_publication import (
    PublishedScenarioText,
    normalize_missing_visibility_for_test,
    project_scenario_public_text_for_test,
    validate_scenario_publication_for_test,
)

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "scenarios"
SECRET_SENTINEL = "SCENARIO_SECRET_SENTINEL"
GM_ONLY_SENTINEL = "SCENARIO_GM_ONLY_SENTINEL"
NPC_TARGET_SENTINEL = "SCENARIO_NPC_WARDEN_SENTINEL"
METADATA_SENTINEL = "SCENARIO_METADATA_SENTINEL"

type RawPath = tuple[str | int, ...]
type PublicationVisibility = Literal["player_visible"] | NpcId


SEQUENCE_CASES: tuple[tuple[str, RawPath], ...] = (
    ("scene_npc_ids", ("initial_scene", "npc_ids")),
    ("locations", ("locations",)),
    ("npcs", ("npcs",)),
    ("world_invariants", ("world_invariants",)),
    ("clues", ("clues",)),
    ("end_conditions", ("end_conditions",)),
    ("end_condition_clue_ids", ("end_conditions", 0, "clue_ids")),
    ("npc_aliases", ("npcs", 0, "aliases")),
    ("npc_knowledge", ("npcs", 0, "knowledge")),
    ("clue_location_ids", ("clues", 0, "location_ids")),
)


def _load_fixture(filename: str) -> dict[str, Any]:
    """YAMLはtest-onlyでUTF-8として読み、productionへI/Oを持ち込まない。"""

    raw = yaml.safe_load((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _minimal_raw() -> dict[str, Any]:
    return _load_fixture("minimal-scenario.v1.yaml")


def _scenario_contract_module() -> ModuleType:
    return importlib.import_module("neontof.contracts.scenario")


def _get_raw_value(root: object, path: RawPath) -> Any:
    value: Any = root
    for part in path:
        if isinstance(part, str):
            assert isinstance(value, dict)
            value = value[part]
        else:
            assert isinstance(value, (list, tuple))
            value = value[part]
    return value


def _get_model_value(root: object, path: RawPath) -> Any:
    value: Any = root
    for part in path:
        if isinstance(part, str):
            value = getattr(value, part)
        else:
            value = value[part]
    return value


def _canonical_for_assertion(value: object) -> object:
    """Raw YAMLのlist/dictとimmutable nested modelを同じ形で比較する。"""

    if isinstance(value, BaseModel):
        return _canonical_for_assertion(value.model_dump())
    if isinstance(value, dict):
        return tuple((key, _canonical_for_assertion(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_canonical_for_assertion(item) for item in value)
    return value


def _set_raw_value(root: dict[str, Any], path: RawPath, value: object) -> None:
    parent = _get_raw_value(root, path[:-1])
    last = path[-1]
    if isinstance(last, str):
        assert isinstance(parent, dict)
        parent[last] = value
    else:
        assert isinstance(parent, list)
        parent[last] = value


def _remove_raw_value(root: dict[str, Any], path: RawPath) -> None:
    parent = _get_raw_value(root, path[:-1])
    last = path[-1]
    if isinstance(last, str):
        assert isinstance(parent, dict)
        del parent[last]
    else:
        assert isinstance(parent, list)
        del parent[last]


def _required_visibility_paths(raw: dict[str, Any]) -> tuple[RawPath, ...]:
    paths: list[RawPath] = [
        ("initial_scene", "objective", "visibility"),
        ("secret", "visibility"),
        ("clock", "visibility"),
    ]
    paths.extend(("locations", index, "visibility") for index in range(len(raw["locations"])))
    for index, npc in enumerate(raw["npcs"]):
        paths.append(("npcs", index, "goal", "visibility"))
        paths.extend(
            ("npcs", index, "knowledge", knowledge_index, "visibility")
            for knowledge_index in range(len(npc["knowledge"]))
        )
    paths.extend(
        ("world_invariants", index, "visibility") for index in range(len(raw["world_invariants"]))
    )
    paths.extend(("clues", index, "visibility") for index in range(len(raw["clues"])))
    paths.extend(
        ("end_conditions", index, "visibility") for index in range(len(raw["end_conditions"]))
    )
    return tuple(paths)


def _path_text(path: RawPath) -> str:
    result = ""
    for part in path:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = part
    return result


def _raw_with_count(section: str, count: int) -> dict[str, Any]:
    raw = _minimal_raw()
    values = deepcopy(raw[section])
    while len(values) < count:
        extra = deepcopy(values[-1])
        index = len(values)
        if section == "locations":
            extra["id"] = f"location:extra-{index}"
            extra["canonical_name"] = f"Extra Location {index}"
        elif section == "npcs":
            extra["id"] = f"npc:extra-{index}"
            extra["canonical_name"] = f"Extra NPC {index}"
            extra["aliases"] = [f"extra-{index}"]
        elif section == "clues":
            extra["id"] = f"clue:extra-{index}"
        elif section == "end_conditions":
            extra["id"] = f"end-condition:extra-{index}"
            extra["outcome"] = "failure"
        values.append(extra)
    raw[section] = values[:count]
    if section == "clues" and count == 2:
        raw["end_conditions"][0] = {
            "type": "clock_reached",
            "id": "end-condition:seal-opened",
            "outcome": "success",
            "clock_id": "clock:pressure",
            "value": 3,
            "visibility": "player_visible",
        }
    return raw


def _duplicate_id_raw(section: str) -> dict[str, Any]:
    raw = _minimal_raw()
    values = raw[section]
    values[1]["id"] = values[0]["id"]
    return raw


class _TupleSubclass(tuple[object, ...]):
    pass


class _ListSubclass(list[object]):
    pass


class _HashableMapping(dict[str, Any]):
    def __init__(self, value: dict[str, Any]) -> None:
        super().__init__(deepcopy(value))

    def __hash__(self) -> int:  # type: ignore[override]
        return id(self)


class _ArbitraryIterable:
    def __iter__(self) -> Iterator[object]:
        return iter(())


def _as_valid_set_element(value: Any) -> Any:
    if isinstance(value, dict):
        return _HashableMapping({key: _as_valid_set_element(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_as_valid_set_element(item) for item in deepcopy(value))
    if isinstance(value, tuple):
        return tuple(_as_valid_set_element(item) for item in value)
    return value


def _invalid_sequence(kind: str, source: list[Any]) -> object:
    if kind == "tuple_subclass":
        return _TupleSubclass(tuple(source))
    if kind == "list_subclass":
        return _ListSubclass(source)
    if kind == "generator":
        return (item for item in source)
    if kind == "set":
        return {_as_valid_set_element(item) for item in source}
    if kind == "arbitrary_iterable":
        return _ArbitraryIterable()
    raise AssertionError(f"unknown invalid sequence kind: {kind}")


def _mutate_nested_mapping(value: dict[str, Any]) -> None:
    for key, item in value.items():
        if isinstance(item, str):
            value[key] = f"{item}-tampered-after-validation"
            return
    raise AssertionError("expected a string field for nested alias mutation")


def test_minimal_scenario_fixture_is_valid_with_fixed_counts_and_outcomes() -> None:
    scenario_contract = _scenario_contract_module()
    scenario_adapter = scenario_contract.SCENARIO_ADAPTER
    scenario_v1 = scenario_contract.ScenarioV1

    raw = _minimal_raw()
    scenario = scenario_adapter.validate_python(raw)

    assert isinstance(scenario, scenario_v1)
    assert tuple(scenario_v1.model_fields) == (
        "schema_version",
        "id",
        "version",
        "initial_scene",
        "locations",
        "npcs",
        "world_invariants",
        "secret",
        "clues",
        "clock",
        "end_conditions",
    )
    assert scenario.schema_version == 1
    assert scenario.id == "scenario:minimal"
    assert len(scenario.locations) == 4
    assert len(scenario.npcs) == 3
    assert len(scenario.secret.model_dump()) == 3
    assert scenario.secret.visibility == "gm_only"
    assert len(scenario.clues) == 3
    assert len(scenario.end_conditions) == 2
    assert {condition.outcome for condition in scenario.end_conditions} == {"success", "failure"}
    assert raw["end_conditions"][0]["clue_ids"] == [
        "clue:broken-seal",
        "clue:astral-mark",
        "clue:silver-key",
    ]
    assert type(scenario.locations) is tuple
    assert type(scenario.npcs) is tuple
    assert type(scenario.clues) is tuple
    assert type(scenario.end_conditions) is tuple


@pytest.mark.parametrize(
    ("section", "count"),
    [
        pytest.param("locations", 4, id="locations-minimum"),
        pytest.param("locations", 6, id="locations-maximum"),
        pytest.param("npcs", 3, id="npcs-minimum"),
        pytest.param("npcs", 4, id="npcs-maximum"),
    ],
)
def test_location_and_npc_count_boundaries_are_accepted(section: str, count: int) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    scenario = scenario_adapter.validate_python(_raw_with_count(section, count))
    assert len(getattr(scenario, section)) == count


@pytest.mark.parametrize(
    ("section", "count"),
    [
        pytest.param("locations", 3, id="locations-below-minimum"),
        pytest.param("locations", 7, id="locations-above-maximum"),
        pytest.param("npcs", 2, id="npcs-below-minimum"),
        pytest.param("npcs", 5, id="npcs-above-maximum"),
        pytest.param("clues", 1, id="clues-below-minimum"),
        pytest.param("clues", 2, id="clues-below-exact-count"),
        pytest.param("clues", 4, id="clues-above-maximum"),
        pytest.param("end_conditions", 1, id="end-conditions-not-two-low"),
        pytest.param("end_conditions", 3, id="end-conditions-not-two-high"),
    ],
)
def test_scenario_rejects_invalid_collection_cardinality(section: str, count: int) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    raw = _raw_with_count(section, count)
    if section == "clues" and count == 2:
        assert all("clue_ids" not in condition for condition in raw["end_conditions"])
        assert [
            (condition["type"], condition["outcome"]) for condition in raw["end_conditions"]
        ] == [
            ("clock_reached", "success"),
            ("clock_reached", "failure"),
        ]

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize("field", ["secret", "clock"])
def test_secret_and_clock_are_single_definition_fields(field: str) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    raw[field] = [raw[field]]
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    "section", ["locations", "npcs", "world_invariants", "clues", "end_conditions"]
)
def test_each_definition_namespace_rejects_duplicate_ids(section: str) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(_duplicate_id_raw(section))


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(("initial_scene", "npc_ids"), id="scene-npc-reference"),
        pytest.param(("clues", 0, "location_ids"), id="clue-location-reference"),
        pytest.param(
            ("end_conditions", 0, "clue_ids"),
            id="end-clue-reference",
        ),
    ],
)
def test_reference_lists_reject_duplicate_references(path: RawPath) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    references = _get_raw_value(raw, path)
    assert isinstance(references, list)
    references[1] = references[0]
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    ("path", "unknown_id"),
    [
        pytest.param(("initial_scene", "location_id"), "location:missing", id="scene-location"),
        pytest.param(("initial_scene", "npc_ids"), "npc:missing", id="scene-npc"),
        pytest.param(("clues", 0, "location_ids"), "location:missing", id="clue-location"),
        pytest.param(
            ("end_conditions", 0, "clue_ids"),
            "clue:missing",
            id="end-clue",
        ),
        pytest.param(
            ("end_conditions", 1, "clock_id"),
            "clock:missing",
            id="end-clock",
        ),
    ],
)
def test_all_reference_targets_must_exist(path: RawPath, unknown_id: str) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    target = _get_raw_value(raw, path)
    if isinstance(target, list):
        target[0] = unknown_id
    else:
        _set_raw_value(raw, path, unknown_id)
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


def test_gm_only_is_valid_source_visibility_and_missing_visibility_is_separate() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _load_fixture("gm-only-player-publication.v1.yaml")
    source = scenario_adapter.validate_python(raw)

    assert source.secret.visibility == "gm_only"
    assert validate_scenario_publication_for_test(source, "player_visible") == ()
    assert normalize_missing_visibility_for_test(raw) == ()


def test_unknown_npc_visibility_is_reported_by_typed_publication_oracle() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    raw["locations"][0]["visibility"] = "npc:unknown"
    source = scenario_adapter.validate_python(raw)

    issues = validate_scenario_publication_for_test(source, "player_visible")
    assert tuple(issue.code for issue in issues) == ("unknown_npc_visibility",)
    assert issues[0].path == "locations[0].visibility"
    assert "npc:unknown" not in repr(issues)


@pytest.mark.parametrize(
    ("filename", "expected_path"),
    [
        pytest.param(
            "missing-objective-visibility.v1.yaml",
            "initial_scene.objective.visibility",
            id="objective",
        ),
        pytest.param(
            "missing-npc-goal-visibility.v1.yaml",
            "npcs[0].goal.visibility",
            id="npc-goal",
        ),
        pytest.param(
            "missing-end-condition-visibility.v1.yaml",
            "end_conditions[0].visibility",
            id="end-condition",
        ),
    ],
)
def test_missing_visibility_fixtures_use_sanitized_oracle(
    filename: str,
    expected_path: str,
) -> None:
    issues = normalize_missing_visibility_for_test(_load_fixture(filename))

    assert len(issues) == 1
    assert issues[0].code == "missing_visibility"
    assert issues[0].path == expected_path
    assert SECRET_SENTINEL not in repr(issues)


def test_every_text_and_fact_visibility_field_has_missing_visibility_coverage() -> None:
    raw = _minimal_raw()

    for path in _required_visibility_paths(raw):
        case = deepcopy(raw)
        _remove_raw_value(case, path)
        issues = normalize_missing_visibility_for_test(case)
        assert tuple(issue.code for issue in issues) == ("missing_visibility",), _path_text(path)
        assert issues[0].path == _path_text(path)


def test_metadata_does_not_require_visibility() -> None:
    raw = _minimal_raw()
    raw["locations"][0]["canonical_name"] = METADATA_SENTINEL
    raw["npcs"][0]["aliases"] = [METADATA_SENTINEL]

    assert normalize_missing_visibility_for_test(raw) == ()


def test_public_projection_excludes_secret_sentinel_and_metadata() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    raw = deepcopy(_minimal_raw())
    raw["secret"]["text"] = SECRET_SENTINEL
    raw["locations"][1]["description"] = GM_ONLY_SENTINEL
    raw["npcs"][0]["goal"]["text"] = NPC_TARGET_SENTINEL
    raw["locations"][0]["canonical_name"] = METADATA_SENTINEL
    raw["npcs"][0]["aliases"] = [METADATA_SENTINEL]
    scenario = scenario_adapter.validate_python(raw)

    projection = project_scenario_public_text_for_test(scenario, "player_visible")
    projection_text = repr(projection)
    assert isinstance(projection, tuple)
    assert projection
    assert all(item.visibility == "player_visible" for item in projection)
    assert SECRET_SENTINEL not in projection_text
    assert GM_ONLY_SENTINEL not in projection_text
    for metadata in (
        METADATA_SENTINEL,
        "location:gate",
        "npc:warden",
        "location:archive",
        "npc:scholar",
    ):
        assert metadata not in projection_text


def test_public_projection_for_npc_uses_exact_visibility_match() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    scenario = scenario_adapter.validate_python(_minimal_raw())
    projection = project_scenario_public_text_for_test(scenario, "npc:warden")

    assert projection
    assert all(item.visibility == "npc:warden" for item in projection)
    assert any(item.text == "The warden protects the hidden chamber." for item in projection)
    assert all(item.visibility != "player_visible" for item in projection)
    assert SECRET_SENTINEL not in repr(projection)


def test_candidate_is_optional_and_valid_projection_candidate_is_accepted() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    source = scenario_adapter.validate_python(_minimal_raw())
    candidate = project_scenario_public_text_for_test(source, "player_visible")

    assert validate_scenario_publication_for_test(source, "player_visible") == ()
    assert validate_scenario_publication_for_test(source, "player_visible", candidate) == ()


@pytest.mark.parametrize(
    ("publication_visibility", "path", "text", "visibility"),
    [
        pytest.param(
            "player_visible",
            "secret.text",
            "The inner chamber is sealed from visitors.",
            "player_visible",
            id="secret-relabelled-player-visible",
        ),
        pytest.param(
            "player_visible",
            "npcs[0].goal.text",
            "The warden protects the hidden chamber.",
            "player_visible",
            id="npc-content-relabelled-player-visible",
        ),
        pytest.param(
            "npc:warden",
            "initial_scene.objective.text",
            "Reach the sealed observatory.",
            "npc:warden",
            id="player-content-relabelled-npc-visible",
        ),
    ],
)
def test_candidate_relabel_sabotage_is_rejected_by_exact_source_match(
    publication_visibility: PublicationVisibility,
    path: str,
    text: str,
    visibility: Visibility,
) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    source = scenario_adapter.validate_python(_minimal_raw())
    candidate_items = list(project_scenario_public_text_for_test(source, publication_visibility))
    assert candidate_items
    candidate_items[0] = PublishedScenarioText(path=path, text=text, visibility=visibility)
    candidate = tuple(candidate_items)

    issues = validate_scenario_publication_for_test(source, publication_visibility, candidate)
    assert tuple(issue.code for issue in issues) == ("invisible_scenario_content",)
    assert all(value not in repr(issues) for value in (text, SECRET_SENTINEL, visibility))


@pytest.mark.parametrize(
    ("container_type", "path"),
    [
        pytest.param(container_type, path, id=f"{container_type}-{name}")
        for name, path in SEQUENCE_CASES
        for container_type in ("list", "tuple")
    ],
)
def test_exact_list_and_tuple_fields_copy_to_new_tuples_without_input_mutation(
    container_type: str,
    path: RawPath,
) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    source_sequence = _get_raw_value(raw, path)
    assert isinstance(source_sequence, list)
    original_items = deepcopy(source_sequence)
    if container_type == "tuple":
        input_sequence: list[Any] | tuple[Any, ...] = tuple(source_sequence)
    else:
        input_sequence = source_sequence
    _set_raw_value(raw, path, input_sequence)

    scenario = scenario_adapter.validate_python(raw)
    model_sequence = _get_model_value(scenario, path)
    assert type(model_sequence) is tuple
    assert _canonical_for_assertion(model_sequence) == _canonical_for_assertion(original_items)
    assert model_sequence is not input_sequence

    before_mutation = deepcopy(_canonical_for_assertion(model_sequence))
    if isinstance(input_sequence, list):
        input_sequence.append(deepcopy(input_sequence[-1]))
    if input_sequence and isinstance(input_sequence[0], dict):
        _mutate_nested_mapping(input_sequence[0])
    elif not isinstance(input_sequence, list):
        source_sequence.append(deepcopy(source_sequence[-1]))
    assert _canonical_for_assertion(model_sequence) == before_mutation


@pytest.mark.parametrize(
    "path",
    [pytest.param(path, id=f"{name}-hashable-list") for name, path in SEQUENCE_CASES],
)
def test_hashable_mapping_elements_are_valid_inside_a_list(path: RawPath) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    source_sequence = _get_raw_value(raw, path)
    assert isinstance(source_sequence, list)
    input_sequence = [_as_valid_set_element(item) for item in source_sequence]
    if isinstance(source_sequence[0], dict):
        assert isinstance(input_sequence[0], _HashableMapping)
    _set_raw_value(raw, path, input_sequence)

    scenario = scenario_adapter.validate_python(raw)
    assert type(_get_model_value(scenario, path)) is tuple


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        pytest.param(kind, path, id=f"{kind}-{name}")
        for name, path in SEQUENCE_CASES
        for kind in ("tuple_subclass", "list_subclass", "generator", "set", "arbitrary_iterable")
    ],
)
def test_sequence_fields_accept_only_exact_list_or_tuple(
    kind: str,
    path: RawPath,
) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    source_sequence = _get_raw_value(raw, path)
    assert isinstance(source_sequence, list)
    if kind == "set":
        _set_raw_value(raw, path, deepcopy(source_sequence))
        scenario_adapter.validate_python(raw)
        raw = _minimal_raw()
    _set_raw_value(raw, path, _invalid_sequence(kind, source_sequence))

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        pytest.param(("schema_version",), "1", id="schema-version-string"),
        pytest.param(("clock", "segments"), "6", id="clock-segments-string"),
        pytest.param(("clock", "initial"), True, id="clock-initial-bool"),
        pytest.param(("end_conditions", 1, "value"), "6", id="end-value-string"),
        pytest.param(("end_conditions", 1, "value"), False, id="end-value-bool"),
    ],
)
def test_scenario_contract_is_strict_for_numbers_and_booleans(path: RawPath, value: object) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    _set_raw_value(raw, path, value)
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("top-level", id="top-level"),
        pytest.param("location", id="nested-location"),
        pytest.param("npc-goal", id="nested-npc-goal"),
    ],
)
def test_unknown_fields_are_forbidden_at_every_contract_depth(mutation: str) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    if mutation == "top-level":
        raw["unexpected"] = "reject"
    elif mutation == "location":
        raw["locations"][0]["unexpected"] = "reject"
    else:
        raw["npcs"][0]["goal"]["unexpected"] = "reject"

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("unknown", id="unknown-discriminator"),
        pytest.param("missing", id="missing-discriminator"),
        pytest.param("wrong-shape", id="section-name-is-not-discriminator"),
    ],
)
def test_end_condition_union_requires_explicit_type_discriminator(mutation: str) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    if mutation == "unknown":
        raw["end_conditions"][0]["type"] = "unsupported"
    elif mutation == "missing":
        del raw["end_conditions"][0]["type"]
    else:
        raw["end_conditions"][0]["type"] = "clock_reached"

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


@pytest.mark.parametrize(
    "outcomes",
    [
        pytest.param(("success", "success"), id="success-twice"),
        pytest.param(("failure", "failure"), id="failure-twice"),
        pytest.param(("failure", "failure"), id="success-missing"),
        pytest.param(("success", "success"), id="failure-missing"),
    ],
)
def test_end_conditions_require_one_success_and_one_failure(outcomes: tuple[str, str]) -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    for condition, outcome in zip(raw["end_conditions"], outcomes, strict=True):
        condition["outcome"] = outcome

    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


def test_end_condition_outcome_is_required() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER

    raw = _minimal_raw()
    del raw["end_conditions"][0]["outcome"]
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(raw)


def test_contract_models_are_frozen_and_nested_instances_are_revalidated() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    scenario = scenario_adapter.validate_python(_minimal_raw())
    with pytest.raises(ValidationError):
        scenario.clock.initial = 99
    with pytest.raises(ValidationError):
        scenario.initial_scene.objective.text = "tampered"

    object.__setattr__(scenario.clock, "initial", "tampered")
    with pytest.raises(ValidationError):
        scenario_adapter.validate_python(scenario)


def test_publication_issue_and_projection_never_retain_raw_secret_content() -> None:
    scenario_adapter = _scenario_contract_module().SCENARIO_ADAPTER
    raw = deepcopy(_minimal_raw())
    raw["secret"]["text"] = SECRET_SENTINEL
    source = scenario_adapter.validate_python(raw)
    candidate = (
        PublishedScenarioText(
            path="secret.text",
            text=SECRET_SENTINEL,
            visibility="player_visible",
        ),
    )
    issues = validate_scenario_publication_for_test(source, "player_visible", candidate)
    projection = project_scenario_public_text_for_test(source, "player_visible")
    publication_output = (issues, projection)

    assert SECRET_SENTINEL not in repr(issues)
    assert SECRET_SENTINEL not in repr(projection)
    assert SECRET_SENTINEL not in repr(publication_output)
