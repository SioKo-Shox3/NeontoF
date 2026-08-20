"""Fail-closed projection of a Turn's lifecycle from the complete Event column."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from neontof.contracts.domain import (
    DomainEvent,
    PlayerInputAcceptedEvent,
    TurnAbortedEvent,
    TurnAwaitingPlayerEvent,
    TurnCommittedEvent,
    TurnResumedEvent,
    TurnRevertedEvent,
)
from neontof.contracts.event_parser import DomainEventValidationError, DomainEventValidationIssue
from neontof.contracts.ids import TurnId
from neontof.contracts.projection import _validate_canonical_events

type TurnStatus = Literal["pending", "running", "awaiting_player", "committed", "aborted"]


def _reject(path: str, message: str) -> None:
    issue = DomainEventValidationIssue(path=path, code="invalid_payload", message=message)
    raise DomainEventValidationError((issue,)) from None


def _is_target(event: DomainEvent, turn_id: TurnId) -> bool:
    if isinstance(event, TurnRevertedEvent):
        return event.payload.target_turn_id == turn_id
    return event.turn_id == turn_id


def _request_id(event: DomainEvent) -> str | None:
    if isinstance(
        event,
        (
            PlayerInputAcceptedEvent,
            TurnAwaitingPlayerEvent,
            TurnResumedEvent,
            TurnAbortedEvent,
            TurnCommittedEvent,
        ),
    ):
        return event.payload.turn_request_id
    return None


def project_turn_status(turn_id: TurnId, events: Sequence[DomainEvent]) -> TurnStatus:
    """Project one Turn after validating every Event in the canonical column."""

    if (
        type(turn_id) is not str
        or re.fullmatch(r"^turn:[a-z0-9]+(?:-[a-z0-9]+)*$", turn_id) is None
    ):
        issue = DomainEventValidationIssue(
            path="turn_id", code="invalid_id", message="invalid Turn ID"
        )
        raise DomainEventValidationError((issue,)) from None

    canonical_events = _validate_canonical_events(events)
    status: TurnStatus = "pending"
    accepted = False
    request_id: str | None = None
    target_found = False

    for event in canonical_events:
        if not _is_target(event, turn_id):
            continue
        target_found = True
        path = f"events[{event.sequence - 1}]"

        if isinstance(event, TurnRevertedEvent):
            if status != "committed":
                _reject(path, "only a committed turn may be reverted")
            continue

        event_request_id = _request_id(event)
        if event_request_id is not None:
            if request_id is None:
                if not isinstance(event, PlayerInputAcceptedEvent):
                    _reject(path, "turn request must be accepted before lifecycle events")
                request_id = event_request_id
            elif event_request_id != request_id:
                _reject(path, "turn request ID does not match the accepted request")

        if isinstance(event, PlayerInputAcceptedEvent):
            if accepted:
                _reject(path, "a turn request may be accepted only once")
            if status != "pending":
                _reject(path, "turn request cannot be accepted in the current status")
            accepted = True
            status = "pending"
        elif isinstance(event, TurnResumedEvent):
            if not accepted or status not in {"pending", "awaiting_player"}:
                _reject(path, "TurnResumed is not allowed in the current status")
            status = "running"
        elif isinstance(event, TurnAwaitingPlayerEvent):
            if not accepted or status != "running":
                _reject(path, "TurnAwaitingPlayer is not allowed in the current status")
            status = "awaiting_player"
        elif isinstance(event, TurnCommittedEvent):
            if not accepted or status not in {"running", "awaiting_player"}:
                _reject(path, "TurnCommitted is not allowed in the current status")
            status = "committed"
        elif isinstance(event, TurnAbortedEvent):
            if not accepted or status not in {"pending", "running", "awaiting_player"}:
                _reject(path, "TurnAborted is not allowed in the current status")
            status = "aborted"
        elif status not in {"running", "awaiting_player"}:
            _reject(path, "turn effect is not allowed in the current status")

    return status if target_found else "pending"
