"""P1-05 Character Sheet loader behavior tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from neontof.authoring.character_loader import load_character_sheet
from neontof.authoring.yaml_loader import load_yaml_document
from neontof.contracts.character_sheet import CharacterSheetV1, InitialItem

CHARACTER_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "characters" / "minimal-character.v1.yaml"
)


def test_character_loader_returns_character_sheet_v1() -> None:
    character = load_character_sheet(CHARACTER_FIXTURE)

    assert isinstance(character, CharacterSheetV1)
    assert character.id == "character:hana"
    assert character.canonical_name == "星野 花"
    assert character.hp.current == 7
    assert character.hp.max == 10
    assert character.resource.id == "resource:stamina"
    assert character.resource.current == 3
    assert character.initial_location_id == "location:forest-edge"


def test_character_loader_uses_initial_items_and_schema_version(tmp_path: Path) -> None:
    character = load_character_sheet(CHARACTER_FIXTURE)

    assert character.schema_version == 1
    assert type(character.schema_version) is int
    assert character.initial_items == (
        InitialItem(
            id="item:lantern",
            canonical_name="古いランタン",
        ),
    )
    assert not hasattr(character, "version")

    hp_collision = tmp_path / "hp-resource-collision.yaml"
    hp_collision.write_text(
        CHARACTER_FIXTURE.read_text(encoding="utf-8").replace(
            "id: resource:stamina", "id: resource:hp", 1
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError):
        load_character_sheet(hp_collision)

    duplicate_item_ids = tmp_path / "duplicate-initial-item-id.yaml"
    duplicate_item_ids.write_text(
        CHARACTER_FIXTURE.read_text(encoding="utf-8").replace(
            '  - id: item:lantern\n    canonical_name: "古いランタン"',
            "  - id: item:lantern\n"
            '    canonical_name: "古いランタン"\n'
            "  - id: item:lantern\n"
            '    canonical_name: "予備のランタン"',
            1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError):
        load_character_sheet(duplicate_item_ids)


def test_mutating_yaml_result_cannot_mutate_contract() -> None:
    raw = load_yaml_document(CHARACTER_FIXTURE)
    character = CharacterSheetV1.model_validate(raw, strict=True)

    aliases = raw["aliases"]
    initial_items = raw["initial_items"]
    assert isinstance(aliases, list)
    assert isinstance(initial_items, list)
    assert isinstance(initial_items[0], dict)
    aliases.append("入力後の別名")
    initial_items[0]["canonical_name"] = "入力後の書換え"

    assert character.aliases == ("花", "ハナ")
    assert character.initial_items[0].canonical_name == "古いランタン"
