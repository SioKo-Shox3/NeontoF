"""手書きfixtureを使ったDomain Event、payload、Projectionの契約テスト。"""

import json
import re
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from pydantic import ValidationError

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "events"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def test_minimal_fixture_has_the_fixed_17_event_sequence() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))

    assert len(events) == 27
    assert tuple(event.sequence for event in events) == tuple(range(1, 28))
    assert tuple(event.event_id for event in events) == tuple(
        f"event:e{index:02d}" for index in range(1, 28)
    )
    assert tuple(event.type for event in events) == (
        "CampaignCreated",
        "SessionStarted",
        "SceneStarted",
        "PlayerInputAccepted",
        "TurnResumed",
        "DiceRolled",
        "ResourceChanged",
        "CharacterMoved",
        "ClockAdvanced",
        "FactAsserted",
        "TurnAwaitingPlayer",
        "TurnResumed",
        "TurnCommitted",
        "PlayerInputAccepted",
        "TurnResumed",
        "ResourceChanged",
        "CharacterMoved",
        "ClockAdvanced",
        "FactAsserted",
        "TurnCommitted",
        "FactSuperseded",
        "SceneEnded",
        "SceneStarted",
        "PlayerInputAccepted",
        "TurnAborted",
        "TurnReverted",
        "SessionEnded",
    )
    assert {event.type for event in events} == {
        "CampaignCreated",
        "SessionStarted",
        "SceneStarted",
        "PlayerInputAccepted",
        "TurnResumed",
        "DiceRolled",
        "ResourceChanged",
        "CharacterMoved",
        "ClockAdvanced",
        "FactAsserted",
        "FactSuperseded",
        "SceneEnded",
        "TurnAwaitingPlayer",
        "TurnAborted",
        "TurnCommitted",
        "TurnReverted",
        "SessionEnded",
    }
    assert "TurnStarted" not in {event.type for event in events}
    assert "EmptyPayload" not in {event.type for event in events}


def test_event_wire_envelope_has_explicit_nulls_and_strict_metadata() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence

    raw = _fixture_bytes("minimal-session.v1.json")
    decoded = json.loads(raw)
    events = parse_domain_event_sequence(raw)
    expected_keys = {
        "type",
        "event_id",
        "event_version",
        "campaign_id",
        "session_id",
        "scene_id",
        "turn_id",
        "sequence",
        "occurred_at",
        "origin",
        "visibility",
        "payload",
    }

    for raw_event, event in zip(decoded, events, strict=True):
        assert set(raw_event) == expected_keys
        assert raw_event["event_version"] == 1
        assert type(raw_event["event_version"]) is int
        assert type(raw_event["sequence"]) is int
        assert raw_event["event_id"] == event.event_id
        assert re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            raw_event["occurred_at"],
        )
        assert re.fullmatch(r"[0-9a-f]{64}", raw_event["payload"].get("input_digest", "")) or (
            raw_event["type"] != "PlayerInputAccepted"
        )

    null_context_types = {"CampaignCreated", "SessionEnded"}
    for raw_event in decoded:
        event_type = raw_event["type"]
        if event_type == "CampaignCreated":
            assert raw_event["session_id"] is None
            assert raw_event["scene_id"] is None
            assert raw_event["turn_id"] is None
        elif event_type == "SessionStarted":
            assert raw_event["session_id"] == "session:one"
            assert raw_event["scene_id"] is None
            assert raw_event["turn_id"] is None
        elif event_type in {"SceneStarted", "SceneEnded"}:
            assert raw_event["session_id"] == "session:one"
            assert raw_event["scene_id"] == "scene:hall"
            assert raw_event["turn_id"] is None
        elif event_type in {
            "PlayerInputAccepted",
            "DiceRolled",
            "ResourceChanged",
            "CharacterMoved",
            "ClockAdvanced",
            "TurnAwaitingPlayer",
            "TurnResumed",
            "TurnAborted",
            "TurnCommitted",
        }:
            assert raw_event["session_id"] == "session:one"
            assert raw_event["scene_id"] == "scene:hall"
            assert isinstance(raw_event["turn_id"], str)
        elif event_type in {"FactAsserted", "FactSuperseded", "TurnReverted"}:
            assert raw_event["session_id"] == "session:one"
        elif event_type == "SessionEnded":
            assert raw_event["session_id"] == "session:one"
            assert raw_event["scene_id"] is None
            assert raw_event["turn_id"] is None
        else:
            pytest.fail(f"unexpected event type: {event_type}")

    assert null_context_types == {"CampaignCreated", "SessionEnded"}
    assert decoded[20]["occurred_at"] < decoded[19]["occurred_at"]


def test_each_event_payload_has_the_fixed_fields_and_effect_materials() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    payload_keys = {event.type: set(event.payload.model_dump(mode="python")) for event in events}

    assert payload_keys["CampaignCreated"] == {"name"}
    assert payload_keys["SessionStarted"] == {"scenario_id", "title"}
    assert payload_keys["SceneStarted"] == {"label"}
    assert payload_keys["SceneEnded"] == {"reason"}
    assert payload_keys["PlayerInputAccepted"] == {"turn_request_id", "input_digest"}
    assert payload_keys["DiceRolled"] == {
        "campaign_seed",
        "action_id",
        "roll_index",
        "derived_seed",
        "formula",
        "result",
    }
    assert payload_keys["ResourceChanged"] == {"resource_id", "entity_id", "delta"}
    assert payload_keys["CharacterMoved"] == {
        "character_id",
        "from_location_id",
        "to_location_id",
    }
    assert payload_keys["ClockAdvanced"] == {"clock_id", "delta"}
    assert payload_keys["FactAsserted"] == {
        "kind",
        "holder",
        "subject_id",
        "predicate",
        "value",
    }
    assert payload_keys["FactSuperseded"] == {"target_fact_id"}
    assert payload_keys["TurnAwaitingPlayer"] == {"turn_request_id"}
    assert payload_keys["TurnResumed"] == {"turn_request_id"}
    assert payload_keys["TurnAborted"] == {"turn_request_id", "reason"}
    assert payload_keys["TurnCommitted"] == {"turn_request_id"}
    assert payload_keys["TurnReverted"] == {"target_turn_id"}
    assert payload_keys["SessionEnded"] == {"reason"}

    payload_values = {event.type: event.payload.model_dump(mode="python") for event in events}
    assert payload_values["CampaignCreated"]["name"] == "NeontoF"
    assert payload_values["SessionStarted"]["scenario_id"] == "scenario:minimal"
    assert payload_values["SceneStarted"]["label"] == "Hall"
    assert payload_values["SceneEnded"]["reason"] == "table_correction"
    assert payload_values["PlayerInputAccepted"]["turn_request_id"] == "turn-request:three"
    assert payload_values["ResourceChanged"]["delta"] == 3
    assert payload_values["CharacterMoved"]["from_location_id"] == "location:gate"
    assert payload_values["ClockAdvanced"]["delta"] == 4
    assert payload_values["FactAsserted"]["predicate"] == "is_open"
    assert payload_values["FactSuperseded"]["target_fact_id"].endswith(":0")
    assert payload_values["TurnAwaitingPlayer"]["turn_request_id"] == "turn-request:one"
    assert payload_values["TurnAborted"]["reason"] == "table_correction"
    assert payload_values["TurnReverted"]["target_turn_id"] == "turn:two"
    assert payload_values["SessionEnded"]["reason"] == "completed"


def test_dice_seed_fields_are_auditable_and_derived_from_all_inputs() -> None:
    from neontof.contracts.domain import derive_dice_seed
    from neontof.contracts.event_parser import parse_domain_event_sequence

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    dice_event = events[5]
    assert dice_event.type == "DiceRolled"
    dice_payload = dice_event.payload
    assert dice_event.turn_id == "turn:one"
    assert dice_payload.campaign_seed == (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert dice_payload.action_id == "action:open-door"
    assert dice_payload.roll_index == 0
    assert dice_payload.derived_seed == (
        "b80e804f6f362eb3c4735e474929ef29d1baca3965e6a67e52b90a4ae58e86b8"
    )
    assert dice_payload.formula == "1d20+2"
    assert dice_payload.result == 7
    assert (
        derive_dice_seed(
            dice_payload.campaign_seed,
            dice_event.turn_id,
            dice_payload.action_id,
            dice_payload.roll_index,
        )
        == dice_payload.derived_seed
    )

    base = ("a" * 64, "turn:one", "action:open-door", 0)
    base_seed = derive_dice_seed(*base)
    assert base_seed == ("b80e804f6f362eb3c4735e474929ef29d1baca3965e6a67e52b90a4ae58e86b8")

    changed_campaign_seed = derive_dice_seed("c" * 64, base[1], base[2], base[3])
    changed_turn_id = derive_dice_seed(base[0], "turn:two", base[2], base[3])
    changed_action_id = derive_dice_seed(base[0], base[1], "action:close-door", base[3])
    changed_roll_index = derive_dice_seed(base[0], base[1], base[2], 1)

    assert changed_campaign_seed == (
        "75cc328734cacc6d128f863d0c180934ad58285df03aca81196fb85c7e885c15"
    )
    assert changed_turn_id == ("2b3e845c438aa526f7132567cbcc0b52ed58bc7822c28a9273b694d84dbc8169")
    assert changed_action_id == ("a1e89a1876de69ed63e099c0ec43063f8cece9ecdc9f5f45a7087e3a34d6ea2e")
    assert changed_roll_index == (
        "95aba69461649e4d1e8a182bce634d7ac21775f8002cb1dcfea1a2c379551f65"
    )
    assert base_seed not in {
        changed_campaign_seed,
        changed_turn_id,
        changed_action_id,
        changed_roll_index,
    }


def test_fact_id_vectors_are_fixed_and_payload_ids_are_stable() -> None:
    from neontof.contracts.projection import derive_fact_id

    assert derive_fact_id("event:e10", 0) == (
        "fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d0:0"
    )
    assert derive_fact_id("event:alpha", 0) == (
        "fact:bd64e06f407fa7ae48f0dd712f0817622f6fab8b9ea11905979745c1426b2ef4:0"
    )
    assert derive_fact_id("event:alpha", 1) == (
        "fact:977fdf29ed9b0faeaf966c4ac373e2e209c939d32b4329674b922d21680de4e2:1"
    )
    assert derive_fact_id("event:z9", 42) == (
        "fact:7d9055cf0f3053fabcf237138adc2ec54a67353e2e9b953be2239c3caf050b95:42"
    )

    with pytest.raises((TypeError, ValueError)):
        derive_fact_id("event:alpha", True)


def test_rebuild_projection_matches_handwritten_expected_and_is_repeatable() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import (
        CharacterLocation,
        ClockState,
        FactRecord,
        Projection,
        ResourceState,
        rebuild_projection,
    )

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    expected = Projection(
        campaign_id="campaign:alpha",
        campaign_name="NeontoF",
        session_id="session:one",
        scenario_id="scenario:minimal",
        session_title="Minimal Session",
        scene_id="scene:hall",
        scene_label="Hall",
        scene_end_reason=None,
        session_end_reason="completed",
        resources=(ResourceState(resource_id="resource:gold", entity_id="entity:hero", value=5),),
        locations=(CharacterLocation(character_id="character:hero", location_id="location:gate"),),
        clocks=(ClockState(clock_id="clock:session", value=2),),
        facts=(
            FactRecord(
                fact_id="fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d0:0",
                event_id="event:e10",
                kind="fact",
                holder="world",
                subject_id="entity:door",
                predicate="is_open",
                value=True,
                visibility="player_visible",
                status="superseded",
            ),
        ),
        reverted_turn_ids=frozenset({"turn:two"}),
        applied_through_sequence=27,
        audit_event_ids=(
            "event:e01",
            "event:e02",
            "event:e03",
            "event:e04",
            "event:e05",
            "event:e06",
            "event:e07",
            "event:e08",
            "event:e09",
            "event:e10",
            "event:e11",
            "event:e12",
            "event:e13",
            "event:e14",
            "event:e15",
            "event:e16",
            "event:e17",
            "event:e18",
            "event:e19",
            "event:e20",
            "event:e21",
            "event:e22",
            "event:e23",
            "event:e24",
            "event:e25",
            "event:e26",
            "event:e27",
        ),
    )

    projection = rebuild_projection(events)
    assert projection == expected
    assert rebuild_projection(events) == projection
    assert projection.scene_end_reason is None
    assert projection.session_end_reason == "completed"
    assert projection.audit_event_ids == expected.audit_event_ids


def test_projection_and_fact_record_have_exact_fields_and_immutable_shapes() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import FactRecord, Projection, rebuild_projection

    projection = rebuild_projection(
        parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    )
    assert tuple(FactRecord.model_fields) == (
        "fact_id",
        "event_id",
        "kind",
        "holder",
        "subject_id",
        "predicate",
        "value",
        "visibility",
        "status",
    )
    assert tuple(Projection.model_fields) == (
        "campaign_id",
        "campaign_name",
        "session_id",
        "scenario_id",
        "session_title",
        "scene_id",
        "scene_label",
        "scene_end_reason",
        "session_end_reason",
        "resources",
        "locations",
        "clocks",
        "facts",
        "reverted_turn_ids",
        "applied_through_sequence",
        "audit_event_ids",
    )
    assert FactRecord.__module__ == "neontof.contracts.projection"
    assert Projection.__module__ == "neontof.contracts.projection"
    assert type(projection.resources) is tuple
    assert type(projection.locations) is tuple
    assert type(projection.clocks) is tuple
    assert type(projection.facts) is tuple
    assert type(projection.reverted_turn_ids) is frozenset
    assert type(projection.audit_event_ids) is tuple

    with pytest.raises(ValidationError):
        projection.facts[0].predicate = "tampered"
    with pytest.raises(ValidationError):
        projection.resources[0].value = 999
    with pytest.raises((TypeError, ValidationError)):
        projection.resources += ()


@pytest.mark.parametrize(
    "update",
    [
        pytest.param({"sequence": 99}, id="sequence-gap"),
        pytest.param({"event_id": "event:e13"}, id="duplicate-event-id"),
        pytest.param({"campaign_id": "campaign:other"}, id="campaign-mismatch"),
        pytest.param({"session_id": None}, id="wire-context-mismatch"),
    ],
)
def test_rebuild_projection_revalidates_every_canonical_event_before_reducing(
    update: dict[str, object],
) -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.projection import rebuild_projection

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    sabotaged_event = events[13].model_copy(update=update)
    sabotaged_events = events[:13] + (sabotaged_event,) + events[14:]

    with pytest.raises(DomainEventValidationError):
        rebuild_projection(sabotaged_events)


def test_rebuild_projection_rejects_duplicate_turn_commit_before_revert() -> None:
    from neontof.contracts.domain import TurnCommittedEvent, TurnRevertedEvent
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.projection import rebuild_projection

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    committed_event = events[19]
    assert isinstance(committed_event, TurnCommittedEvent)
    duplicate_commit = committed_event.model_copy(
        update={"event_id": "event:e20-duplicate", "sequence": 21}
    )
    events_with_duplicate = (
        events[:20]
        + (duplicate_commit,)
        + tuple(event.model_copy(update={"sequence": event.sequence + 1}) for event in events[20:])
    )

    assert tuple(event.sequence for event in events_with_duplicate) == tuple(
        range(1, len(events_with_duplicate) + 1)
    )
    reverted_event = events_with_duplicate[-2]
    assert isinstance(reverted_event, TurnRevertedEvent)
    assert duplicate_commit.turn_id == "turn:two"
    assert reverted_event.payload.target_turn_id == "turn:two"
    with pytest.raises(DomainEventValidationError):
        rebuild_projection(events_with_duplicate)


def test_domain_event_and_payload_values_are_immutable() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    fact_event = events[9]
    assert fact_event.type == "FactAsserted"
    with pytest.raises(ValidationError):
        fact_event.sequence = 99
    with pytest.raises(ValidationError):
        fact_event.payload.predicate = "changed"


def test_rebuild_projection_fails_closed_for_invalid_or_repeated_reverts() -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.projection import rebuild_projection

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    invalid_target_payload = events[25].payload.model_copy(update={"target_turn_id": "turn:three"})
    invalid_target = events[25].model_copy(update={"payload": invalid_target_payload})
    with pytest.raises(DomainEventValidationError):
        rebuild_projection(events[:25] + (invalid_target,) + events[26:])

    repeated_revert = events[25].model_copy(update={"event_id": "event:e28", "sequence": 28})
    with pytest.raises(DomainEventValidationError):
        rebuild_projection(events + (repeated_revert,))


@pytest.mark.parametrize("container_type", ("list", "dict"))
def test_rebuild_projection_rejects_cyclic_fact_value_as_domain_validation_error(
    container_type: str,
) -> None:
    from neontof.contracts.event_parser import (
        DomainEventValidationError,
        parse_domain_event_sequence,
    )
    from neontof.contracts.projection import rebuild_projection

    events = parse_domain_event_sequence(_fixture_bytes("minimal-session.v1.json"))
    cyclic_list: list[object] = []
    cyclic_dict: dict[str, object] = {}
    if container_type == "list":
        cyclic_list.append(cyclic_list)
        cyclic_value: object = cyclic_list
    else:
        cyclic_dict["self"] = cyclic_dict
        cyclic_value = cyclic_dict
    cyclic_payload = events[9].payload.model_copy(update={"value": cyclic_value})
    cyclic_fact = events[9].model_copy(update={"payload": cyclic_payload})
    sabotaged_events = events[:9] + (cyclic_fact,) + events[10:]

    with pytest.raises(DomainEventValidationError):
        rebuild_projection(sabotaged_events)


def test_domain_event_excludes_transcript_and_telemetry_inputs() -> None:
    from neontof.contracts.domain import DomainEvent, TelemetryEntry, TranscriptEntry
    from neontof.contracts.projection import rebuild_projection

    assert TranscriptEntry.__name__ not in str(DomainEvent)
    assert TelemetryEntry.__name__ not in str(DomainEvent)
    assert TranscriptEntry not in get_args(DomainEvent)
    assert TelemetryEntry not in get_args(DomainEvent)

    hints = get_type_hints(rebuild_projection)
    assert "TranscriptEntry" not in str(hints["events"])
    assert "TelemetryEntry" not in str(hints["events"])


def test_fixture_has_no_narrative_transcript_telemetry_or_secret_material() -> None:
    raw_text = _fixture_bytes("minimal-session.v1.json").decode("utf-8")
    lower_text = raw_text.lower()
    for forbidden in ("api_key", "narrative", "transcript", "telemetry", "raw_input"):
        assert forbidden not in lower_text
