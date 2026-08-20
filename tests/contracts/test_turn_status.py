"""完全なcanonical Event列に対するTurn status Projectionの契約テスト。"""

from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "events"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def test_full_campaign_turn_one_follows_pending_running_awaiting_running_committed() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))

    assert project_turn_status("turn:one", events[:3]) == "pending"
    assert project_turn_status("turn:one", events[:4]) == "pending"
    assert project_turn_status("turn:one", events[:5]) == "running"
    assert project_turn_status("turn:one", events[:11]) == "awaiting_player"
    assert project_turn_status("turn:one", events[:12]) == "running"
    assert project_turn_status("turn:one", events[:13]) == "committed"
    assert project_turn_status("turn:one", events) == "committed"


def test_turn_two_remains_committed_after_revert_and_turn_three_is_aborted() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))

    assert project_turn_status("turn:two", events[:20]) == "committed"
    assert project_turn_status("turn:two", events) == "committed"
    assert project_turn_status("turn:three", events[:25]) == "aborted"
    assert project_turn_status("turn:three", events) == "aborted"


def test_unrelated_revert_envelope_is_ignored_for_turn_three_status() -> None:
    from neontof.contracts.domain import TurnRevertedEvent
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    revert_event = events[25]
    assert isinstance(revert_event, TurnRevertedEvent)
    unrelated_revert = revert_event.model_copy(update={"turn_id": "turn:three"})
    events_with_unrelated_revert = events[:25] + (unrelated_revert,) + events[26:]

    assert unrelated_revert.payload.target_turn_id == "turn:two"
    assert tuple(event.sequence for event in events_with_unrelated_revert) == tuple(
        range(1, len(events_with_unrelated_revert) + 1)
    )
    event_ids = tuple(event.event_id for event in events_with_unrelated_revert)
    assert len(event_ids) == len(set(event_ids))
    assert {event.campaign_id for event in events_with_unrelated_revert} == {"campaign:alpha"}
    assert project_turn_status("turn:three", events_with_unrelated_revert) == "aborted"


def test_other_turns_and_null_context_events_are_ignored() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    assert project_turn_status("turn:other", events) == "pending"

    status_events = parse_domain_event_sequence(_fixture_bytes("turn-status-sequences.v1.json"))
    assert project_turn_status("turn:one", status_events) == "committed"
    assert project_turn_status("turn:two", status_events) == "committed"
    assert project_turn_status("turn:missing", status_events) == "pending"


def test_same_request_duplicate_mismatch_and_terminal_transitions_are_rejected() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.turn_status import project_turn_status

    raw = _fixture_bytes("same-request-resend.v1.json")
    duplicate_events = parse_domain_event_sequence(raw)
    assert tuple(event.event_id for event in duplicate_events[:5]) == (
        "event:r01",
        "event:r02",
        "event:r03",
        "event:r04",
        "event:r05",
    )

    with pytest.raises(DomainEventValidationError):
        project_turn_status("turn:one", duplicate_events[:5])

    events_without_duplicate = duplicate_events[:4] + duplicate_events[5:]
    committed_then_resumed = tuple(
        event.model_copy(update={"sequence": sequence})
        for sequence, event in enumerate(events_without_duplicate, start=1)
    )
    with pytest.raises(DomainEventValidationError):
        project_turn_status("turn:one", committed_then_resumed)

    mismatch_raw = raw.replace(
        b'"turn_request_id": "turn-request:one"',
        b'"turn_request_id": "turn-request:two"',
        1,
    )
    mismatch_events_with_duplicate = parse_domain_event_sequence(mismatch_raw)
    mismatch_events = mismatch_events_with_duplicate[:4] + mismatch_events_with_duplicate[5:]
    mismatch_events = tuple(
        event.model_copy(update={"sequence": sequence})
        for sequence, event in enumerate(mismatch_events, start=1)
    )
    with pytest.raises(DomainEventValidationError):
        project_turn_status("turn:one", mismatch_events)

    status_events = parse_domain_event_sequence(_fixture_bytes("turn-status-sequences.v1.json"))
    mismatched_payload = status_events[9].payload.model_copy(
        update={"turn_request_id": "turn-request:one"}
    )
    mismatched_resume = status_events[9].model_copy(update={"payload": mismatched_payload})
    with pytest.raises(DomainEventValidationError):
        project_turn_status(
            "turn:two",
            status_events[:9] + (mismatched_resume,) + status_events[10:],
        )

    terminal_events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))[:13]
    terminal_event = terminal_events[-1].model_copy(
        update={"event_id": "event:terminal", "sequence": 14}
    )
    with pytest.raises(DomainEventValidationError):
        project_turn_status("turn:one", terminal_events + (terminal_event,))


@pytest.mark.parametrize(
    "update",
    [
        pytest.param({"sequence": 99}, id="sequence-gap"),
        pytest.param({"event_id": "event:e13"}, id="duplicate-event-id"),
        pytest.param({"campaign_id": "campaign:other"}, id="campaign-mismatch"),
        pytest.param({"session_id": None}, id="wire-context-mismatch"),
    ],
)
def test_turn_status_validates_unselected_canonical_events_before_filtering(
    update: dict[str, object],
) -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    sabotaged_event = events[13].model_copy(update=update)
    sabotaged_events = events[:13] + (sabotaged_event,) + events[14:]

    with pytest.raises(DomainEventValidationError):
        project_turn_status("turn:one", sabotaged_events)


def test_revert_target_must_be_a_prior_committed_turn_and_origin_is_correction_only() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.turn_status import project_turn_status

    events = parse_domain_event_sequence(_fixture_bytes("turn-status-sequences.v1.json"))
    assert project_turn_status("turn:two", events) == "committed"

    invalid_origin = _fixture_bytes("invalid-payloads.v1.json")
    with pytest.raises(DomainEventValidationError):
        parse_domain_event_sequence(invalid_origin)
