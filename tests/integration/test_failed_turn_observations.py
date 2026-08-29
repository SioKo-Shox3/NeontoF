"""P1-02 failed-turn retention and observation transaction-boundary tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Self

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SHA256 = "a" * 64
OCCURRED_AT = "2026-08-25T00:00:00Z"


def _observation_components() -> tuple[type[Any], type[Any], type[Any]]:
    try:
        from neontof.observability.records import TelemetryRecord, TranscriptRecord
        from neontof.persistence.observation_store import ObservationStore
    except ImportError:
        pytest.fail("P1-02 observation production modules are not available")
    return TranscriptRecord, TelemetryRecord, ObservationStore


def _stores(tmp_path: Path) -> tuple[Any, Any, Any, Path]:
    from neontof.persistence.event_store import EventStore
    from neontof.persistence.sqlite_database import SqliteDatabase

    path = tmp_path / "runtime" / "failed-turn.sqlite3"
    assert not path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(path)
    database.migrate()
    _, _, observation_store_type = _observation_components()
    return database, observation_store_type(database), EventStore(database), path


def _transcript(
    kind: str,
    entry_id: str,
    *,
    data: dict[str, object],
    campaign_id: str = "campaign:alpha",
    session_id: str | None = "session:main",
    turn_id: str | None = "turn:first",
    model_call_id: str | None = "model-call:first",
) -> Any:
    transcript_type, _, _ = _observation_components()
    return transcript_type(
        entry_id=entry_id,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        model_call_id=model_call_id,
        kind=kind,
        occurred_at=OCCURRED_AT,
        data=data,
    )


def _telemetry(
    entry_id: str,
    *,
    campaign_id: str = "campaign:alpha",
    session_id: str = "session:main",
    turn_id: str = "turn:first",
    model_call_id: str = "model-call:first",
    status: str = "succeeded",
    error_code: str | None = None,
    cost_microusd: int = 0,
) -> Any:
    _, telemetry_type, _ = _observation_components()
    return telemetry_type(
        entry_id=entry_id,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        model_call_id=model_call_id,
        provider="fake_provider",
        model="test.model",
        roles=("referee",),
        attempt=1,
        status=status,
        input_tokens=2,
        output_tokens=3,
        cached_tokens=0,
        latency_ms=4,
        cost_microusd=cost_microusd,
        error_code=error_code,
        occurred_at=OCCURRED_AT,
    )


def _duplicate_event_batch() -> Any:
    from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody

    body = EventDraftBody(
        type="CampaignCreated",
        event_id="event:failed-turn",
        event_version=1,
        campaign_id="campaign:alpha",
        session_id=None,
        scene_id=None,
        turn_id=None,
        occurred_at=OCCURRED_AT,
        origin="in_world",
        visibility="player_visible",
        payload_json=json.dumps({"name": "NeontoF"}, separators=(",", ":")).encode("utf-8"),
    )
    draft = EventDraft(body=body)
    return EventBatch(campaign_id="campaign:alpha", drafts=(draft, draft))


def _turn_revert_batch() -> Any:
    from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody

    body = EventDraftBody(
        type="TurnReverted",
        event_id="event:turn-reverted",
        event_version=1,
        campaign_id="campaign:alpha",
        session_id="session:main",
        scene_id=None,
        turn_id=None,
        occurred_at=OCCURRED_AT,
        origin="table_correction",
        visibility="player_visible",
        payload_json=b'{"target_turn_id":"turn:first"}',
    )
    return EventBatch(
        campaign_id="campaign:alpha",
        drafts=(EventDraft(body=body),),
    )


def _fail_event(event_store: Any) -> None:
    with pytest.raises((AttributeError, TypeError, ValueError, RuntimeError)):
        event_store.append(_duplicate_event_batch())


def _assert_no_events(event_store: Any) -> None:
    assert event_store.read_campaign("campaign:alpha") == ()


class _NonReentrantLockProbe:
    def __init__(self) -> None:
        self.depth = 0
        self.acquire_count = 0

    def __enter__(self) -> Self:
        if self.depth != 0:
            raise AssertionError("single writer lock was acquired recursively")
        self.depth = 1
        self.acquire_count += 1
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        del args
        self.depth = 0
        return False


def test_player_input_is_retained_when_turn_fails(tmp_path: Path) -> None:
    _, observation_store, event_store, _ = _stores(tmp_path)
    observation_store.append_transcript(
        _transcript("player_input", "transcript:player-input", data={"text": "look"})
    )
    observation_store.append_transcript(
        _transcript(
            "error",
            "transcript:failure",
            data={"error_code": "model_error", "digest": SHA256, "byte_length": 0},
        )
    )

    _fail_event(event_store)

    assert [record.kind for record in observation_store.read_transcript("campaign:alpha")] == [
        "player_input",
        "error",
    ]
    _assert_no_events(event_store)


def test_timeout_records_transcript_and_telemetry_with_zero_events(tmp_path: Path) -> None:
    _, observation_store, event_store, _ = _stores(tmp_path)
    observation_store.append_transcript(
        _transcript("player_input", "transcript:timeout-input", data={"text": "wait"})
    )
    observation_store.append_transcript(
        _transcript(
            "error",
            "transcript:timeout-error",
            data={"error_code": "timeout", "digest": SHA256, "byte_length": 0},
        )
    )
    observation_store.append_telemetry(
        _telemetry(
            "telemetry:timeout",
            status="timed_out",
            error_code="timeout",
        )
    )

    _fail_event(event_store)

    assert observation_store.read_transcript("campaign:alpha", "turn:first")
    timeout = observation_store.read_telemetry("campaign:alpha", "turn:first")
    assert len(timeout) == 1
    assert timeout[0].status == "timed_out"
    assert timeout[0].error_code == "timeout"
    _assert_no_events(event_store)


def test_turn_revert_does_not_reduce_session_cost(tmp_path: Path) -> None:
    _, observation_store, event_store, _ = _stores(tmp_path)
    observation_store.append_telemetry(_telemetry("telemetry:revert", cost_microusd=37))
    before = observation_store.session_cost_microusd("campaign:alpha", "session:main")

    event_store.append(_turn_revert_batch())

    after = observation_store.session_cost_microusd("campaign:alpha", "session:main")
    assert before == 37
    assert after == before


def test_session_cost_is_campaign_scoped(tmp_path: Path) -> None:
    _, observation_store, _, _ = _stores(tmp_path)
    observation_store.append_telemetry(_telemetry("telemetry:alpha", cost_microusd=13))
    observation_store.append_telemetry(
        _telemetry(
            "telemetry:beta",
            campaign_id="campaign:beta",
            cost_microusd=29,
        )
    )

    assert observation_store.session_cost_microusd("campaign:alpha", "session:main") == 13
    assert observation_store.session_cost_microusd("campaign:beta", "session:main") == 29


def test_failed_turn_persists_observation_with_zero_events(tmp_path: Path) -> None:
    _, observation_store, event_store, _ = _stores(tmp_path)
    observation_store.append_transcript(
        _transcript("player_input", "transcript:failed-input", data={"text": "open door"})
    )
    observation_store.append_telemetry(
        _telemetry(
            "telemetry:failed",
            status="failed",
            error_code="model_error",
            cost_microusd=5,
        )
    )

    _fail_event(event_store)

    assert len(observation_store.read_transcript("campaign:alpha")) == 1
    assert observation_store.session_cost_microusd("campaign:alpha", "session:main") == 5
    _assert_no_events(event_store)


def test_observation_append_is_outside_event_append_critical_section(
    tmp_path: Path,
) -> None:
    database, observation_store, event_store, _ = _stores(tmp_path)
    lock_probe = _NonReentrantLockProbe()
    database._write_lock = lock_probe

    observation_store.append_transcript(
        _transcript("player_input", "transcript:outside", data={"text": "listen"})
    )
    observation_store.append_telemetry(_telemetry("telemetry:outside"))
    _fail_event(event_store)

    assert lock_probe.acquire_count == 3
    assert lock_probe.depth == 0


@pytest.mark.skip(
    reason=(
        "実Turn pipelineがP1-03まで未実装のため、production pipelineの順序検証はP1-03の実装と同時に実施する。"
        "P1-02の別transaction・failed-turn retention・lock非再入テストは引き続き実体を検証する。"
    )
)
def test_observation_pipeline_orders_player_input_model_observations_then_event_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, observation_store, event_store, _ = _stores(tmp_path)
    order: list[str] = []
    real_append_transcript: Callable[[Any], None] = observation_store.append_transcript
    real_append_telemetry: Callable[[Any], None] = observation_store.append_telemetry
    real_event_append: Callable[[Any], Any] = event_store.append

    def append_transcript(record: Any) -> None:
        order.append(f"transcript:{record.kind}")
        real_append_transcript(record)

    def append_telemetry(record: Any) -> None:
        order.append("telemetry")
        real_append_telemetry(record)

    def append_event(batch: Any) -> Any:
        order.append("event_append")
        return real_event_append(batch)

    monkeypatch.setattr(observation_store, "append_transcript", append_transcript)
    monkeypatch.setattr(observation_store, "append_telemetry", append_telemetry)
    monkeypatch.setattr(event_store, "append", append_event)

    observation_store.append_transcript(
        _transcript("player_input", "transcript:ordered-input", data={"text": "search"})
    )
    observation_store.append_transcript(
        _transcript(
            "model_request",
            "transcript:ordered-request",
            data={
                "context_digest": SHA256,
                "context_item_count": 0,
                "output_schema": "semantic-result-v1",
            },
        )
    )
    observation_store.append_transcript(
        _transcript(
            "model_response",
            "transcript:ordered-response",
            data={
                "response_digest": SHA256,
                "narrative_byte_length": 5,
                "proposed_event_count": 0,
                "proposed_fact_count": 0,
            },
        )
    )
    observation_store.append_telemetry(_telemetry("telemetry:ordered"))
    _fail_event(event_store)

    assert order == [
        "transcript:player_input",
        "transcript:model_request",
        "transcript:model_response",
        "telemetry",
        "event_append",
    ]
