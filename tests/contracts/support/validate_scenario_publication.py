"""Scenario の公開境界を検証する test-only oracle。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from neontof.contracts.base import ContractModel
from neontof.contracts.ids import NpcId, Visibility

if TYPE_CHECKING:
    from neontof.contracts.scenario import ScenarioV1

type ScenarioVisibilityIssueCode = Literal[
    "missing_visibility",
    "invisible_scenario_content",
    "unknown_npc_visibility",
]


class ScenarioVisibilityIssue(ContractModel):
    """公開判定の失敗を、入力値を含めずに表す。"""

    path: str
    code: ScenarioVisibilityIssueCode
    message: str


class PublishedScenarioText(ContractModel):
    """公開先へ渡してよい、text fieldだけのtest-only projection。"""

    path: str
    text: str
    visibility: Visibility


_ISSUE_MESSAGES: dict[ScenarioVisibilityIssueCode, str] = {
    "missing_visibility": "required visibility is missing",
    "invisible_scenario_content": "candidate content is not visible to this publication",
    "unknown_npc_visibility": "visibility names an unknown NPC",
}


def _issue(path: str, code: ScenarioVisibilityIssueCode) -> ScenarioVisibilityIssue:
    """Issueにはraw valueを含めず、固定messageだけを格納する。"""

    return ScenarioVisibilityIssue(path=path, code=code, message=_ISSUE_MESSAGES[code])


def _check_required_visibility(
    value: object,
    path: str,
    issues: list[ScenarioVisibilityIssue],
) -> None:
    mapping = _as_mapping(value)
    if mapping is None or "visibility" not in mapping:
        issues.append(_issue(path, "missing_visibility"))


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return value


def _as_sequence(value: object) -> Sequence[object] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    return value


def normalize_missing_visibility_for_test(
    input_value: object,
) -> tuple[ScenarioVisibilityIssue, ...]:
    """Raw YAML mappingのrequired Visibility欠落だけを安全なIssueへ正規化する。"""

    input_mapping = _as_mapping(input_value)
    if input_mapping is None:
        return (_issue("scenario", "missing_visibility"),)

    issues: list[ScenarioVisibilityIssue] = []

    initial_scene = _as_mapping(input_mapping.get("initial_scene"))
    objective = initial_scene.get("objective") if initial_scene is not None else None
    _check_required_visibility(objective, "initial_scene.objective.visibility", issues)

    locations = _as_sequence(input_mapping.get("locations", ()))
    if locations is not None:
        for index, location in enumerate(locations):
            _check_required_visibility(location, f"locations[{index}].visibility", issues)

    npcs = _as_sequence(input_mapping.get("npcs", ()))
    if npcs is not None:
        for index, npc in enumerate(npcs):
            npc_mapping = _as_mapping(npc)
            goal = npc_mapping.get("goal") if npc_mapping is not None else None
            _check_required_visibility(goal, f"npcs[{index}].goal.visibility", issues)
            knowledge = (
                _as_sequence(npc_mapping.get("knowledge", ())) if npc_mapping is not None else None
            )
            if knowledge is not None:
                for knowledge_index, item in enumerate(knowledge):
                    _check_required_visibility(
                        item,
                        f"npcs[{index}].knowledge[{knowledge_index}].visibility",
                        issues,
                    )

    world_invariants = _as_sequence(input_mapping.get("world_invariants", ()))
    if world_invariants is not None:
        for index, invariant in enumerate(world_invariants):
            _check_required_visibility(
                invariant,
                f"world_invariants[{index}].visibility",
                issues,
            )

    _check_required_visibility(input_mapping.get("secret"), "secret.visibility", issues)

    clues = _as_sequence(input_mapping.get("clues", ()))
    if clues is not None:
        for index, clue in enumerate(clues):
            _check_required_visibility(clue, f"clues[{index}].visibility", issues)

    _check_required_visibility(input_mapping.get("clock"), "clock.visibility", issues)

    end_conditions = _as_sequence(input_mapping.get("end_conditions", ()))
    if end_conditions is not None:
        for index, condition in enumerate(end_conditions):
            _check_required_visibility(
                condition,
                f"end_conditions[{index}].visibility",
                issues,
            )

    return tuple(issues)


def _iter_visibility_fields(source: ScenarioV1) -> tuple[tuple[str, Visibility], ...]:
    """Typed Scenarioから、宣言されたVisibility fieldだけを列挙する。"""

    fields: list[tuple[str, Visibility]] = [
        ("initial_scene.objective.visibility", source.initial_scene.objective.visibility),
    ]
    fields.extend(
        (f"locations[{index}].visibility", location.visibility)
        for index, location in enumerate(source.locations)
    )
    for index, npc in enumerate(source.npcs):
        fields.append((f"npcs[{index}].goal.visibility", npc.goal.visibility))
        fields.extend(
            (
                f"npcs[{index}].knowledge[{knowledge_index}].visibility",
                knowledge.visibility,
            )
            for knowledge_index, knowledge in enumerate(npc.knowledge)
        )
    fields.extend(
        (f"world_invariants[{index}].visibility", invariant.visibility)
        for index, invariant in enumerate(source.world_invariants)
    )
    fields.append(("secret.visibility", source.secret.visibility))
    fields.extend(
        (f"clues[{index}].visibility", clue.visibility) for index, clue in enumerate(source.clues)
    )
    fields.append(("clock.visibility", source.clock.visibility))
    fields.extend(
        (f"end_conditions[{index}].visibility", condition.visibility)
        for index, condition in enumerate(source.end_conditions)
    )
    return tuple(fields)


def _iter_text_fields(source: ScenarioV1) -> tuple[tuple[str, str, Visibility], ...]:
    """Metadataを除き、公開可能なtext fieldだけを列挙する。"""

    fields: list[tuple[str, str, Visibility]] = [
        (
            "initial_scene.objective.text",
            source.initial_scene.objective.text,
            source.initial_scene.objective.visibility,
        )
    ]
    fields.extend(
        (f"locations[{index}].description", location.description, location.visibility)
        for index, location in enumerate(source.locations)
    )
    for index, npc in enumerate(source.npcs):
        fields.append((f"npcs[{index}].goal.text", npc.goal.text, npc.goal.visibility))
        fields.extend(
            (
                f"npcs[{index}].knowledge[{knowledge_index}].text",
                knowledge.text,
                knowledge.visibility,
            )
            for knowledge_index, knowledge in enumerate(npc.knowledge)
        )
    fields.extend(
        (
            f"world_invariants[{index}].statement",
            invariant.statement,
            invariant.visibility,
        )
        for index, invariant in enumerate(source.world_invariants)
    )
    fields.append(("secret.text", source.secret.text, source.secret.visibility))
    fields.extend(
        (f"clues[{index}].text", clue.text, clue.visibility)
        for index, clue in enumerate(source.clues)
    )
    fields.append(("clock.label", source.clock.label, source.clock.visibility))
    return tuple(fields)


def validate_scenario_publication_for_test(
    source: ScenarioV1,
    publication_visibility: Literal["player_visible"] | NpcId,
    candidate: Sequence[PublishedScenarioText] | None = None,
) -> tuple[ScenarioVisibilityIssue, ...]:
    """Typed sourceとcandidateの公開可能なtext集合を比較して検証する。"""

    known_npcs = {npc.id for npc in source.npcs}
    issues: list[ScenarioVisibilityIssue] = []
    for path, visibility in _iter_visibility_fields(source):
        if visibility in {"gm_only", "player_visible"}:
            continue
        if visibility not in known_npcs:
            issues.append(_issue(path, "unknown_npc_visibility"))

    if candidate is not None:
        expected = frozenset(
            (path, text, visibility)
            for path, text, visibility in _iter_text_fields(source)
            if visibility == publication_visibility
        )
        actual = frozenset((item.path, item.text, item.visibility) for item in candidate)
        if actual != expected:
            issues.append(_issue("candidate", "invisible_scenario_content"))

    return tuple(issues)


def project_scenario_public_text_for_test(
    scenario: ScenarioV1,
    publication_visibility: Literal["player_visible"] | NpcId,
) -> tuple[PublishedScenarioText, ...]:
    """指定公開先に完全一致するtextだけを、metadataなしでprojectionする。"""

    return tuple(
        PublishedScenarioText(path=path, text=text, visibility=visibility)
        for path, text, visibility in _iter_text_fields(scenario)
        if visibility == publication_visibility
    )
