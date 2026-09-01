"""Validate Scenario authoring documents at the typed contract boundary."""

from __future__ import annotations

from pathlib import Path

from neontof.authoring.yaml_loader import load_yaml_document
from neontof.contracts.scenario import SCENARIO_ADAPTER, ScenarioV1


def load_scenario(path: Path) -> ScenarioV1:
    """Load and strictly validate one ScenarioV1 document."""

    return SCENARIO_ADAPTER.validate_python(load_yaml_document(path), strict=True)
