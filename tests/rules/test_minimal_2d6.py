"""P1-04の再現可能な2d6判定契約テスト。"""

from __future__ import annotations

import random
from typing import Any

import pytest

CAMPAIGN_SEED = "a" * 64


def test_same_inputs_produce_same_seed_and_dice() -> None:
    from neontof.rules.minimal_2d6 import resolve_2d6

    first = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )
    second = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )

    assert second == first
    assert first.derived_seed == second.derived_seed
    assert first.result == second.result
    assert first.formula == "2d6"


def test_different_roll_index_changes_seed() -> None:
    from neontof.rules.minimal_2d6 import resolve_2d6

    first = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )
    second = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=1,
    )

    assert first.derived_seed != second.derived_seed


def test_global_random_state_does_not_affect_result() -> None:
    from neontof.rules.minimal_2d6 import resolve_2d6

    random.seed(101)
    state_before = random.getstate()
    first = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )
    state_after = random.getstate()

    random.seed(202)
    second = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )

    assert state_after == state_before
    assert second == first


def test_result_is_between_two_and_twelve() -> None:
    from neontof.rules.minimal_2d6 import resolve_2d6

    result = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )

    assert type(result.result) is int
    assert 2 <= result.result <= 12


def test_target_number_is_strict_and_bounded() -> None:
    from neontof.rules.minimal_2d6 import validate_target_number

    assert validate_target_number(2) == 2
    assert validate_target_number(12) == 12

    invalid_values: tuple[Any, ...] = (1, 13, True, "2")
    for invalid_value in invalid_values:
        with pytest.raises(ValueError):
            validate_target_number(invalid_value)


def test_check_success_is_derived_from_dice_and_target() -> None:
    from neontof.rules.minimal_2d6 import resolve_2d6, resolve_2d6_check

    check = resolve_2d6_check(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
        target=7,
    )
    dice = resolve_2d6(
        campaign_seed=CAMPAIGN_SEED,
        turn_id="turn:first",
        action_id="action:open-door",
        roll_index=0,
    )

    assert check.dice == dice
    assert check.success is (check.dice.result >= check.target)
