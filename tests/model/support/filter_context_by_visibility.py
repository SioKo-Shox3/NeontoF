"""Test-only visibility filter for provider context facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neontof.contracts.projection import FactRecord
    from neontof.contracts.semantic_result import PublicationVisibility


def filter_context_by_visibility(
    facts: tuple[FactRecord, ...],
    publication_visibility: PublicationVisibility,
) -> tuple[FactRecord, ...]:
    """Return only facts whose visibility exactly matches the publication target."""

    if publication_visibility == "player_visible":
        return tuple(fact for fact in facts if fact.visibility == "player_visible")
    if publication_visibility.startswith("npc:"):
        return tuple(fact for fact in facts if fact.visibility == publication_visibility)
    return ()
