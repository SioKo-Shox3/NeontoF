"""Delegate server-owned bootstrap input to the lifecycle Event boundary."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from neontof.application.turn_lifecycle import BootstrapPreparation, TurnLifecycleCoordinator
from neontof.authoring.bootstrap import BootstrapInput
from neontof.contracts.ids import EventId, OccurredAt
from neontof.event_metadata import EventBatch, StoredEvent

BootstrapEventBuilder = Callable[[BootstrapInput, OccurredAt, Sequence[EventId]], EventBatch]


class BootstrapApplicationService:
    """Own only bootstrap builder composition and coordinator delegation."""

    def __init__(
        self,
        coordinator: TurnLifecycleCoordinator,
        build_bootstrap_events: BootstrapEventBuilder,
    ) -> None:
        self._coordinator = coordinator
        self._build_bootstrap_events = build_bootstrap_events

    def create_campaign(
        self,
        *,
        input_value: BootstrapInput,
        occurred_at: OccurredAt,
        event_ids: Sequence[EventId],
    ) -> tuple[StoredEvent, ...]:
        def build() -> EventBatch:
            return self._build_bootstrap_events(input_value, occurred_at, event_ids)

        prepare: BootstrapPreparation = build
        return self._coordinator.append_bootstrap(
            campaign_id=input_value.campaign_id,
            prepare=prepare,
        )
