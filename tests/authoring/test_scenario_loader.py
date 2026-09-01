"""P1-05 Scenario loader behavior tests."""

from __future__ import annotations

from pathlib import Path

from neontof.authoring.scenario_loader import load_scenario

from neontof.contracts.scenario import ScenarioV1

SCENARIO_FIXTURE = Path(__file__).parents[1] / "fixtures" / "scenarios" / "minimal-scenario.v1.yaml"


def test_scenario_loader_returns_scenario_v1() -> None:
    scenario = load_scenario(SCENARIO_FIXTURE)

    assert isinstance(scenario, ScenarioV1)
    assert scenario.schema_version == 1
    assert scenario.id == "scenario:minimal"
    assert scenario.version == "v1"
    assert scenario.initial_scene.id == "scene:opening"
    assert scenario.initial_scene.objective.text == "Reach the sealed observatory."
    assert tuple(location.id for location in scenario.locations) == (
        "location:gate",
        "location:archive",
        "location:tower",
        "location:courtyard",
    )
    assert tuple(npc.id for npc in scenario.npcs) == (
        "npc:warden",
        "npc:scholar",
        "npc:merchant",
    )
    assert tuple(clue.id for clue in scenario.clues) == (
        "clue:broken-seal",
        "clue:astral-mark",
        "clue:silver-key",
    )
    assert scenario.clock.id == "clock:pressure"
    assert scenario.clock.initial == 0
