"""Validate Character Sheet authoring documents at the typed contract boundary."""

from __future__ import annotations

from pathlib import Path

from neontof.authoring.yaml_loader import load_yaml_document
from neontof.contracts.character_sheet import CHARACTER_SHEET_ADAPTER, CharacterSheetV1


def load_character_sheet(path: Path) -> CharacterSheetV1:
    """Load and strictly validate one CharacterSheetV1 document."""

    character = CHARACTER_SHEET_ADAPTER.validate_python(load_yaml_document(path), strict=True)
    item_ids = tuple(item.id for item in character.initial_items)
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("initial item IDs must be unique")
    if character.resource.id == "resource:hp":
        raise ValueError("resource:hp is reserved for the character hit points")
    return character
