"""P1-00の未採番Event draftとcoordination metadataの契約テスト。"""

import ast
from pathlib import Path
from typing import Any

import pytest
from pydantic import StrictBytes, ValidationError


def _event_body_values() -> dict[str, Any]:
    return {
        "type": "CampaignCreated",
        "event_id": "event:created",
        "event_version": 1,
        "campaign_id": "campaign:alpha",
        "session_id": None,
        "scene_id": None,
        "turn_id": None,
        "occurred_at": "2026-08-25T00:00:00Z",
        "origin": "in_world",
        "visibility": "player_visible",
        "payload_json": b'{"name":"NeontoF"}',
    }


def _metadata_values() -> dict[str, Any]:
    return {
        "campaign_id": "campaign:alpha",
        "session_id": "session:main",
        "scene_id": "scene:hall",
        "turn_id": "turn:first",
        "turn_request_id": "turn-request:first",
        "occurred_at": "2026-08-25T00:00:00Z",
        "root_turn_request_id": "turn-request:first",
        "event_ids": ("event:accepted", "event:committed"),
    }


def _forbidden_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, ...]] = set()
    package_parts = ("neontof",)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(tuple(alias.name.split(".")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_parts = tuple(node.module.split(".")) if node.module else ()
            if node.level:
                base_parts = package_parts[: -(node.level - 1)] if node.level > 1 else package_parts
                module_parts = base_parts + module_parts
            imports.add(module_parts)
            imports.update(
                module_parts + tuple(alias.name.split("."))
                for alias in node.names
                if alias.name != "*"
            )

    forbidden_roots = {
        ("neontof", "application"),
        ("neontof", "rules"),
        ("neontof", "model"),
        ("neontof", "web"),
        ("neontof", "persistence"),
    }
    return {
        ".".join(module_parts)
        for module_parts in imports
        if any(module_parts[: len(root)] == root for root in forbidden_roots)
    }


def test_event_batch_has_no_caller_assigned_sequence() -> None:
    from neontof.event_metadata import EventBatch, EventDraft, EventDraftBody

    draft = EventDraft(body=EventDraftBody(**_event_body_values()))
    batch = EventBatch(campaign_id="campaign:alpha", drafts=(draft,))

    assert batch.campaign_id == "campaign:alpha"
    assert batch.drafts == (draft,)
    assert "sequence" not in EventBatch.model_fields
    assert "sequence" not in EventDraft.model_fields
    assert "sequence" not in EventDraftBody.model_fields

    with pytest.raises(ValidationError):
        EventBatch.model_validate(
            {"campaign_id": "campaign:alpha", "drafts": (draft,), "sequence": 1}
        )


def test_event_draft_body_matches_unsequenced_domain_event_envelope() -> None:
    from neontof.contracts.domain import DomainEventBase
    from neontof.event_metadata import EventDraftBody

    expected_fields = tuple(
        field for field in DomainEventBase.model_fields if field not in {"sequence", "payload"}
    ) + ("payload_json",)
    assert tuple(EventDraftBody.model_fields) == expected_fields
    assert tuple(EventDraftBody.model_fields) == (
        "type",
        "event_id",
        "event_version",
        "campaign_id",
        "session_id",
        "scene_id",
        "turn_id",
        "occurred_at",
        "origin",
        "visibility",
        "payload_json",
    )


def test_event_draft_wraps_neutral_body_without_domain_event() -> None:
    from neontof.contracts.domain import DomainEventBase
    from neontof.event_metadata import EventDraft, EventDraftBody

    body = EventDraftBody(**_event_body_values())
    draft = EventDraft(body=body)

    assert draft.body == body
    assert draft.body is not body
    assert not issubclass(EventDraftBody, DomainEventBase)
    assert tuple(EventDraft.model_fields) == ("body",)


def test_event_payload_json_requires_exact_bytes() -> None:
    from neontof.event_metadata import EventDraftBody, RawEventPayloadJson

    assert RawEventPayloadJson is StrictBytes
    body = EventDraftBody(**_event_body_values())
    assert type(body.payload_json) is bytes
    assert body.payload_json == b'{"name":"NeontoF"}'

    for invalid in ('{"name":"NeontoF"}', bytearray(b'{"name":"NeontoF"}')):
        values = _event_body_values()
        values["payload_json"] = invalid
        with pytest.raises(ValidationError):
            EventDraftBody.model_validate(values)


def test_neutral_module_does_not_import_application_rules_model_web_or_persistence() -> None:
    module_path = Path(__file__).parents[1] / "src" / "neontof" / "event_metadata.py"
    from neontof.event_metadata import EventAppendMetadata

    assert module_path.is_file()
    assert _forbidden_imports(module_path) == set()
    assert EventAppendMetadata.__module__ == "neontof.event_metadata"


def test_turn_request_id_is_coordination_metadata_not_event_envelope_field() -> None:
    from neontof.contracts.domain import DomainEventBase
    from neontof.event_metadata import (
        EventAppendMetadata,
        EventDraftBody,
        RevertEventMetadata,
        TurnEventMetadata,
    )

    assert "turn_request_id" in EventAppendMetadata.model_fields
    assert "turn_request_id" in TurnEventMetadata.model_fields
    assert "turn_request_id" in RevertEventMetadata.model_fields
    assert "turn_request_id" not in EventDraftBody.model_fields
    assert "turn_request_id" not in DomainEventBase.model_fields


def test_turn_event_metadata_is_neutral_and_reusable() -> None:
    from neontof.event_metadata import (
        EventAppendMetadata,
        EventMaterializationInput,
        TurnEventMetadata,
    )

    metadata = TurnEventMetadata(**_metadata_values())

    assert issubclass(TurnEventMetadata, EventAppendMetadata)
    assert EventMaterializationInput is TurnEventMetadata
    assert metadata.session_id == "session:main"
    assert metadata.scene_id == "scene:hall"
    assert metadata.turn_id == "turn:first"
    assert metadata.turn_request_id == "turn-request:first"
    assert metadata.root_turn_request_id == "turn-request:first"
    assert metadata.event_ids == ("event:accepted", "event:committed")
    assert type(metadata.event_ids) is tuple
    assert all(field.is_required() for field in TurnEventMetadata.model_fields.values())


def test_revert_event_metadata_is_defined_before_use() -> None:
    from neontof.event_metadata import EventAppendMetadata, RevertEventMetadata

    values = _metadata_values()
    values.pop("root_turn_request_id")
    assert issubclass(RevertEventMetadata, EventAppendMetadata)
    assert tuple(RevertEventMetadata.model_fields) == (
        "campaign_id",
        "session_id",
        "scene_id",
        "turn_id",
        "turn_request_id",
        "occurred_at",
        "event_ids",
    )
    assert "root_turn_request_id" not in RevertEventMetadata.model_fields
    assert type(RevertEventMetadata(**values).event_ids) is tuple
    assert all(field.is_required() for field in RevertEventMetadata.model_fields.values())


def test_event_materialization_input_has_no_application_dependency() -> None:
    from neontof.event_metadata import EventMaterializationInput, TurnEventMetadata

    assert EventMaterializationInput is TurnEventMetadata
    assert (
        _forbidden_imports(Path(__file__).parents[1] / "src" / "neontof" / "event_metadata.py")
        == set()
    )
