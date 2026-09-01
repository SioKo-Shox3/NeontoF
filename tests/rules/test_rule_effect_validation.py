"""P1-04の資源・状態異常・Clock境界契約テスト。"""

from __future__ import annotations

from typing import Any


def test_resource_change_cannot_cross_zero_or_maximum() -> None:
    from neontof.contracts.domain import ResourceChangedPayload
    from neontof.contracts.projection import Projection, ResourceState
    from neontof.contracts.semantic_result import ProposedResourceChanged
    from neontof.rules.minimal_2d6 import ResourceLimit, validate_resource_changes

    projection = Projection(
        campaign_id="campaign:alpha",
        campaign_name=None,
        session_id=None,
        scenario_id=None,
        session_title=None,
        scene_id=None,
        scene_label=None,
        scene_end_reason=None,
        session_end_reason=None,
        resources=(ResourceState(resource_id="resource:hp", entity_id="entity:hero", value=5),),
        locations=(),
        clocks=(),
        facts=(),
        reverted_turn_ids=frozenset(),
        applied_through_sequence=0,
        audit_event_ids=(),
    )
    proposals = (
        ProposedResourceChanged(
            type="ResourceChanged",
            payload=ResourceChangedPayload(
                resource_id="resource:hp",
                entity_id="entity:hero",
                delta=-6,
            ),
        ),
        ProposedResourceChanged(
            type="ResourceChanged",
            payload=ResourceChangedPayload(
                resource_id="resource:hp",
                entity_id="entity:hero",
                delta=6,
            ),
        ),
    )
    limits = (
        ResourceLimit(
            resource_id="resource:hp",
            entity_id="entity:hero",
            minimum=0,
            maximum=10,
        ),
    )

    issues = validate_resource_changes(
        projection=projection,
        proposals=proposals,
        limits=limits,
    )

    assert tuple(issue.code for issue in issues) == ("out_of_bounds", "out_of_bounds")
    assert projection.resources[0].value == 5


def test_hp_and_one_resource_use_existing_resource_ids() -> None:
    from neontof.contracts.domain import ResourceChangedPayload
    from neontof.contracts.projection import Projection, ResourceState
    from neontof.contracts.semantic_result import ProposedResourceChanged
    from neontof.rules.minimal_2d6 import ResourceLimit, validate_resource_changes

    projection = Projection(
        campaign_id="campaign:alpha",
        campaign_name=None,
        session_id=None,
        scenario_id=None,
        session_title=None,
        scene_id=None,
        scene_label=None,
        scene_end_reason=None,
        session_end_reason=None,
        resources=(
            ResourceState(resource_id="resource:hp", entity_id="entity:hero", value=5),
            ResourceState(resource_id="resource:gold", entity_id="entity:hero", value=2),
        ),
        locations=(),
        clocks=(),
        facts=(),
        reverted_turn_ids=frozenset(),
        applied_through_sequence=0,
        audit_event_ids=(),
    )
    proposals = (
        ProposedResourceChanged(
            type="ResourceChanged",
            payload=ResourceChangedPayload(
                resource_id="resource:hp",
                entity_id="entity:hero",
                delta=-1,
            ),
        ),
        ProposedResourceChanged(
            type="ResourceChanged",
            payload=ResourceChangedPayload(
                resource_id="resource:gold",
                entity_id="entity:hero",
                delta=1,
            ),
        ),
    )
    limits = (
        ResourceLimit(
            resource_id="resource:hp",
            entity_id="entity:hero",
            minimum=0,
            maximum=10,
        ),
        ResourceLimit(
            resource_id="resource:gold",
            entity_id="entity:hero",
            minimum=0,
            maximum=3,
        ),
    )

    assert (
        validate_resource_changes(
            projection=projection,
            proposals=proposals,
            limits=limits,
        )
        == ()
    )


def test_status_condition_uses_closed_two_value_convention() -> None:
    import pytest

    from neontof.rules.minimal_2d6 import validate_status_condition

    assert validate_status_condition("injured") == "injured"
    assert validate_status_condition("shaken") == "shaken"

    invalid_value: Any = "stunned"
    with pytest.raises(ValueError):
        validate_status_condition(invalid_value)


def test_clock_advance_respects_single_clock_bounds() -> None:
    from neontof.rules.minimal_2d6 import validate_clock_advance

    assert validate_clock_advance(current=2, delta=3, maximum=5) == ()

    overflow = validate_clock_advance(current=3, delta=3, maximum=5)
    assert tuple(issue.code for issue in overflow) == ("out_of_bounds",)

    invalid_delta = validate_clock_advance(current=2, delta=0, maximum=5)
    assert tuple(issue.code for issue in invalid_delta) == ("out_of_bounds",)
