"""Test-only builders for Semantic Result inputs and validation contexts."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import neontof.contracts.semantic_result as semantic_result_contract
from neontof.contracts.semantic_result import (
    SemanticValidationContext,
    SemanticValidationOutcome,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "semantic-results"


def base_result() -> dict[str, Any]:
    """Return a fresh, schema-shaped Semantic Result with no state proposals."""

    return {
        "schema_version": 1,
        "rulings": [],
        "proposed_events": [],
        "proposed_facts": [],
        "knowledge_changes": [],
        "visibility_changes": [],
        "clarification_request": None,
        "rejection": None,
        "narrative_plan": [],
        "narrative": "",
        "mentioned_details": [],
        "evidence": [],
        "suggested_actions": [],
    }


def load_fixture(name: str) -> dict[str, Any]:
    """Load one JSON fixture for test inputs."""

    decoded = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def make_context(
    *,
    current_turn_status: Literal["running", "awaiting_player"] = "running",
    publication_visibility: str = "player_visible",
    known_entity_ids: frozenset[str] | None = None,
    known_npc_ids: frozenset[str] | None = None,
    known_fact_subject_ids: frozenset[str] | None = None,
    known_resource_ids: frozenset[str] | None = None,
    known_character_ids: frozenset[str] | None = None,
    known_location_ids: frozenset[str] | None = None,
    known_clock_ids: frozenset[str] | None = None,
    facts_by_id: tuple[tuple[str, Any], ...] = (),
) -> SemanticValidationContext:
    """Build a typed validation context only when a test actually evaluates it."""

    return SemanticValidationContext(
        known_entity_ids=known_entity_ids
        if known_entity_ids is not None
        else frozenset({"entity:hero", "entity:door"}),
        known_npc_ids=known_npc_ids if known_npc_ids is not None else frozenset({"npc:guard"}),
        known_fact_subject_ids=known_fact_subject_ids
        if known_fact_subject_ids is not None
        else frozenset({"entity:door"}),
        known_resource_ids=known_resource_ids
        if known_resource_ids is not None
        else frozenset({"resource:gold"}),
        known_character_ids=known_character_ids
        if known_character_ids is not None
        else frozenset({"character:hero"}),
        known_location_ids=known_location_ids
        if known_location_ids is not None
        else frozenset({"location:gate", "location:hall"}),
        known_clock_ids=known_clock_ids
        if known_clock_ids is not None
        else frozenset({"clock:session"}),
        facts_by_id=facts_by_id,
        current_turn_status=current_turn_status,
        publication_visibility=publication_visibility,
    )


def evaluate_semantic_result(
    raw: object, context: SemanticValidationContext
) -> SemanticValidationOutcome:
    """Call the production validator after the test has assembled its inputs."""

    validator: Callable[[object, SemanticValidationContext], SemanticValidationOutcome] = (
        semantic_result_contract.__dict__["validate_semantic_result"]
    )
    return validator(raw, context)
