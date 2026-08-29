"""Derived Projection snapshot storage rebuilt from the authoritative Event Log."""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import ValidationError

from neontof.contracts.base import ContractModel
from neontof.contracts.event_parser import DomainEventValidationError, DomainEventValidationIssue
from neontof.contracts.ids import CampaignId
from neontof.contracts.projection import Projection, rebuild_projection
from neontof.persistence.event_store import EventStore
from neontof.persistence.sqlite_database import SqliteDatabase


class ProjectionSnapshot(ContractModel):
    """One immutable projection snapshot and the Event sequence it covers."""

    campaign_id: CampaignId
    through_sequence: int
    projection: Projection


def _snapshot_validation_error() -> DomainEventValidationError:
    return DomainEventValidationError(
        (
            DomainEventValidationIssue(
                path="projection_snapshot",
                code="schema",
                message="projection snapshot validation failed",
            ),
        )
    )


def _snapshot_from_row(row: tuple[Any, ...] | None) -> ProjectionSnapshot | None:
    if row is None:
        return None
    if len(row) != 3:
        raise _snapshot_validation_error() from None
    campaign_id, through_sequence, projection_json = row
    if (
        type(campaign_id) is not str
        or type(through_sequence) is not int
        or through_sequence < 0
        or type(projection_json) is not bytes
    ):
        raise _snapshot_validation_error() from None

    parse_failed = False
    projection: Projection | None = None
    try:
        projection = Projection.model_validate_json(projection_json)
    except ValidationError, UnicodeDecodeError, TypeError, ValueError:
        parse_failed = True
    if parse_failed or projection is None:
        raise _snapshot_validation_error() from None
    if (
        (through_sequence > 0 and projection.campaign_id is None)
        or (projection.campaign_id is not None and projection.campaign_id != campaign_id)
        or projection.applied_through_sequence != through_sequence
    ):
        raise _snapshot_validation_error() from None

    construction_failed = False
    snapshot: ProjectionSnapshot | None = None
    try:
        snapshot = ProjectionSnapshot(
            campaign_id=campaign_id,
            through_sequence=through_sequence,
            projection=projection,
        )
    except ValidationError, TypeError, ValueError:
        construction_failed = True
    if construction_failed or snapshot is None:
        raise _snapshot_validation_error() from None
    return snapshot


class ProjectionStore:
    """Own immutable derived snapshots without replacing the Event Log authority."""

    def __init__(self, database: SqliteDatabase, event_store: EventStore) -> None:
        self._database = database
        self._event_store = event_store

    def rebuild(self, campaign_id: CampaignId) -> ProjectionSnapshot:
        def operation(connection: sqlite3.Connection) -> ProjectionSnapshot:
            # Keep read, pure reduction, and upsert in one transaction to prevent
            # append from interleaving a newer Event Log state with this snapshot.
            events = self._event_store._read_campaign_on_connection(connection, campaign_id)
            projection = rebuild_projection(events)
            projection_json = projection.model_dump_json().encode("utf-8")
            connection.execute(
                "INSERT INTO projection_snapshots "
                "(campaign_id, through_sequence, projection_json) VALUES (?, ?, ?) "
                "ON CONFLICT(campaign_id) DO UPDATE SET "
                "through_sequence = excluded.through_sequence, "
                "projection_json = excluded.projection_json "
                "WHERE excluded.through_sequence > projection_snapshots.through_sequence",
                (
                    campaign_id,
                    projection.applied_through_sequence,
                    sqlite3.Binary(projection_json),
                ),
            )
            row = connection.execute(
                "SELECT campaign_id, through_sequence, projection_json "
                "FROM projection_snapshots WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            snapshot = _snapshot_from_row(tuple(row) if row is not None else None)
            if snapshot is None:
                raise ValueError("projection snapshot upsert returned no row")
            return snapshot

        return self._database._write(operation)

    def read(self, campaign_id: CampaignId) -> ProjectionSnapshot | None:
        def operation(connection: sqlite3.Connection) -> ProjectionSnapshot | None:
            row = connection.execute(
                "SELECT campaign_id, through_sequence, projection_json "
                "FROM projection_snapshots WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            return _snapshot_from_row(tuple(row) if row is not None else None)

        return self._database._read(operation)

    def delete(self, campaign_id: CampaignId) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM projection_snapshots WHERE campaign_id = ?",
                (campaign_id,),
            )

        self._database._write(operation)
