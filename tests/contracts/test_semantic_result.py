"""P0-04 Semantic Result schema, validation, authority, and materializer contracts."""

from __future__ import annotations

import copy
import importlib
import inspect
import json
import re
from collections.abc import Callable, Mapping
from itertools import product
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from .support import materialize_semantic_result_for_test
from .support.evaluate_semantic_contract import (
    base_result,
    evaluate_semantic_result,
    load_fixture,
    make_context,
)
from .support.materialize_proposed_events import FixtureEventContext

EVENT_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "events"
SEMANTIC_FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "semantic-results"
DOOR_FACT_ID = "fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d0:0"

ROOT_SEQUENCE_FIELDS = (
    "rulings",
    "proposed_events",
    "proposed_facts",
    "knowledge_changes",
    "visibility_changes",
    "narrative_plan",
    "mentioned_details",
    "evidence",
    "suggested_actions",
)
RULING_SEQUENCE_FIELDS = ("rule_refs", "facts_used", "proposed_effects")
type TurnStatus = Literal["running", "awaiting_player"]


def _invoke_with_runtime_arguments(
    function: Callable[..., object],
    *arguments: object,
) -> object:
    # 本番境界の型注釈を変えず、実行時の不正値だけを検証する。
    return function(*arguments)


def _event_proposal(
    *,
    resource_id: str = "resource:gold",
    entity_id: str = "entity:hero",
    delta: object = 2,
) -> dict[str, object]:
    return {
        "type": "ResourceChanged",
        "payload": {
            "resource_id": resource_id,
            "entity_id": entity_id,
            "delta": delta,
        },
    }


def _character_proposal(
    *,
    character_id: str = "character:hero",
    from_location_id: str | None = None,
    to_location_id: str = "location:gate",
) -> dict[str, object]:
    return {
        "type": "CharacterMoved",
        "payload": {
            "character_id": character_id,
            "from_location_id": from_location_id,
            "to_location_id": to_location_id,
        },
    }


def _clock_proposal(*, clock_id: str = "clock:session", delta: object = 1) -> dict[str, object]:
    return {
        "type": "ClockAdvanced",
        "payload": {"clock_id": clock_id, "delta": delta},
    }


def _fact_proposal(
    *,
    holder: str = "world",
    subject_id: str | None = "entity:door",
    predicate: str = "is_open",
    value: object = True,
    visibility: str = "player_visible",
) -> dict[str, object]:
    return {
        "kind": "fact",
        "holder": holder,
        "subject_id": subject_id,
        "predicate": predicate,
        "value": value,
        "visibility": visibility,
    }


def _evidence_claim(
    *,
    fact_id: str = DOOR_FACT_ID,
    predicate: str = "is_open",
    value: object = True,
) -> dict[str, object]:
    return {"claim": {"fact_id": fact_id, "predicate": predicate, "value": value}}


def _ruling(
    *,
    rule_refs: object = (),
    facts_used: object = (),
    proposed_effects: object = (),
) -> dict[str, object]:
    return {
        "rule_refs": rule_refs,
        "facts_used": facts_used,
        "interpretation": "The ruling is only an annotation.",
        "roll_spec": None,
        "proposed_effects": proposed_effects,
        "is_house_ruling": False,
    }


def _door_fact() -> Any:
    """Obtain the Evidence Fact through the existing P0-03 parser and Projection."""

    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import rebuild_projection

    raw = (EVENT_FIXTURE_ROOT / "minimal-session.v1.json").read_bytes()
    projection = rebuild_projection(parse_domain_event_sequence(raw))
    assert len(projection.facts) == 1
    assert projection.facts[0].fact_id == DOOR_FACT_ID
    return projection.facts[0]


def _custom_fact(
    *,
    event_id: str = "event:fixture-fact",
    holder: str = "world",
    subject_id: str | None = "entity:door",
    predicate: str = "is_open",
    value: object = True,
    visibility: str = "player_visible",
) -> Any:
    from neontof.contracts.projection import FactRecord, derive_fact_id

    return FactRecord(
        fact_id=derive_fact_id(event_id, 0),
        event_id=event_id,
        kind="fact",
        holder=holder,
        subject_id=subject_id,
        predicate=predicate,
        value=value,
        visibility=visibility,
        status="active",
    )


def _context(
    *,
    current_turn_status: TurnStatus = "running",
    publication_visibility: str = "player_visible",
    fact: Any | None = None,
    facts_by_id: tuple[tuple[str, Any], ...] | None = None,
    known_npc_ids: frozenset[str] | None = None,
) -> Any:
    if facts_by_id is None:
        selected_fact = _door_fact() if fact is None else fact
        facts_by_id = ((selected_fact.fact_id, selected_fact),)
    return make_context(
        current_turn_status=current_turn_status,
        publication_visibility=publication_visibility,
        facts_by_id=facts_by_id,
        known_npc_ids=known_npc_ids,
    )


def _evaluate(
    raw: object,
    *,
    current_turn_status: TurnStatus = "running",
    publication_visibility: str = "player_visible",
    fact: Any | None = None,
    facts_by_id: tuple[tuple[str, Any], ...] | None = None,
    known_npc_ids: frozenset[str] | None = None,
) -> Any:
    return evaluate_semantic_result(
        raw,
        _context(
            current_turn_status=current_turn_status,
            publication_visibility=publication_visibility,
            fact=fact,
            facts_by_id=facts_by_id,
            known_npc_ids=known_npc_ids,
        ),
    )


def _codes(outcome: Any) -> set[str]:
    return {issue.code for issue in outcome.issues}


def _alias_contains(alias: object, target: object, seen: set[int] | None = None) -> bool:
    if alias is target or get_origin(alias) is target:
        return True
    visited = set() if seen is None else seen
    marker = id(alias)
    if marker in visited:
        return False
    visited.add(marker)
    return any(_alias_contains(argument, target, visited) for argument in get_args(alias))


def _validation_failure_next_status(current_status: TurnStatus) -> str:
    assert current_status in {"running", "awaiting_player"}
    return "aborted" if current_status == "running" else "awaiting_player"


def _assert_accepted(outcome: Any, next_status: str) -> Any:
    assert outcome.type == "accepted"
    assert outcome.next_status == next_status
    return outcome


def _assert_rejected(
    outcome: Any,
    expected_code: str,
    next_status: str | None = None,
) -> Any:
    assert outcome.type == "rejected"
    assert expected_code in _codes(outcome)
    if next_status is not None:
        assert outcome.next_status == next_status
    return outcome


def test_semantic_contract_models_are_strict_forbid_frozen_and_revalidate() -> None:
    from neontof.contracts.semantic_result import (
        AcceptedSemanticResult,
        ClarificationRequest,
        EventProposalRef,
        EvidenceClaim,
        EvidenceRef,
        FactProposalRef,
        KnowledgeChange,
        NarrativeBeat,
        ProposedCharacterMoved,
        ProposedClockAdvanced,
        ProposedFact,
        ProposedResourceChanged,
        ProvisionalDetail,
        RejectedSemanticResult,
        Rejection,
        RollSpec,
        Ruling,
        SemanticResultV1,
        SemanticValidationContext,
        SuggestedAction,
        ValidationIssue,
        VisibilityChange,
    )

    contract_models = (
        SemanticResultV1,
        Ruling,
        ProposedFact,
        KnowledgeChange,
        VisibilityChange,
        ClarificationRequest,
        Rejection,
        NarrativeBeat,
        SuggestedAction,
        EvidenceClaim,
        EvidenceRef,
        EventProposalRef,
        FactProposalRef,
        ProposedResourceChanged,
        ProposedCharacterMoved,
        ProposedClockAdvanced,
        ProvisionalDetail,
        RollSpec,
        ValidationIssue,
        SemanticValidationContext,
        AcceptedSemanticResult,
        RejectedSemanticResult,
    )
    for model in contract_models:
        assert model.model_config["strict"] is True
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["frozen"] is True
        assert model.model_config["revalidate_instances"] == "always"

    raw = base_result()
    result = SemanticResultV1.model_validate(raw)
    with pytest.raises(ValidationError):
        SemanticResultV1.model_validate({**raw, "unexpected": "field"})
    with pytest.raises(ValidationError):
        result.narrative = "changed"

    object.__setattr__(result, "narrative", 17)
    with pytest.raises(ValidationError):
        SemanticResultV1.model_validate(result)


def test_public_semantic_type_adapters_validate_each_proposal_and_reference_shape() -> None:
    semantic_result = importlib.import_module("neontof.contracts.semantic_result")
    from neontof.contracts.ids import NpcId
    from neontof.contracts.projection import FactRecord
    from neontof.contracts.semantic_result import (
        PROPOSAL_REF_ADAPTER,
        PROPOSED_EVENT_ADAPTER,
        SEMANTIC_OUTCOME_ADAPTER,
        SEMANTIC_RESULT_ADAPTER,
        AcceptedSemanticResult,
        EventProposalRef,
        EvidenceFact,
        FactProposalRef,
        NonNegativeStrictInt,
        PositiveStrictInt,
        ProposalRef,
        ProposedCharacterMoved,
        ProposedClockAdvanced,
        ProposedEvent,
        ProposedFact,
        ProposedResourceChanged,
        ProvisionalDetail,
        PublicationVisibility,
        RawSemanticResultInput,
        RejectedSemanticResult,
        SemanticResultV1,
        SemanticValidationIssueCode,
        SemanticValidationOutcome,
        ValidationIssue,
    )

    assert PROPOSED_EVENT_ADAPTER is semantic_result.PROPOSED_EVENT_ADAPTER
    assert PROPOSAL_REF_ADAPTER is semantic_result.PROPOSAL_REF_ADAPTER
    assert SEMANTIC_RESULT_ADAPTER is semantic_result.SEMANTIC_RESULT_ADAPTER
    assert SEMANTIC_OUTCOME_ADAPTER is semantic_result.SEMANTIC_OUTCOME_ADAPTER
    assert all(
        isinstance(adapter, TypeAdapter)
        for adapter in (
            PROPOSED_EVENT_ADAPTER,
            PROPOSAL_REF_ADAPTER,
            SEMANTIC_RESULT_ADAPTER,
            SEMANTIC_OUTCOME_ADAPTER,
        )
    )

    assert _alias_contains(NonNegativeStrictInt, int)
    assert _alias_contains(PositiveStrictInt, int)
    assert _alias_contains(PublicationVisibility, Literal)
    assert _alias_contains(PublicationVisibility, NpcId)
    assert _alias_contains(ProposedEvent, ProposedResourceChanged)
    assert _alias_contains(ProposedEvent, ProposedCharacterMoved)
    assert _alias_contains(ProposedEvent, ProposedClockAdvanced)
    assert _alias_contains(ProposalRef, EventProposalRef)
    assert _alias_contains(ProposalRef, FactProposalRef)
    assert _alias_contains(SemanticValidationOutcome, AcceptedSemanticResult)
    assert _alias_contains(SemanticValidationOutcome, RejectedSemanticResult)
    assert _alias_contains(RawSemanticResultInput, Mapping)
    assert _alias_contains(RawSemanticResultInput, SemanticResultV1)
    assert EvidenceFact is FactRecord
    assert set(get_args(SemanticValidationIssueCode)) == {
        "schema",
        "unknown_field",
        "unknown_version",
        "invalid_result",
        "invalid_event_proposal",
        "invalid_fact_proposal",
        "invalid_proposal_ref",
        "unknown_entity",
        "unknown_resource",
        "unknown_character",
        "unknown_location",
        "unknown_clock",
        "unknown_fact",
        "invisible_fact",
        "unrelated_visible_fact",
        "claim_mismatch",
        "duplicate_proposal",
        "conflicting_control_fields",
        "invalid_transition",
    }

    event_values: tuple[tuple[object, type[object]], ...] = (
        (_event_proposal(), ProposedResourceChanged),
        (_character_proposal(), ProposedCharacterMoved),
        (_clock_proposal(), ProposedClockAdvanced),
    )
    for raw, expected_type in event_values:
        parsed = PROPOSED_EVENT_ADAPTER.validate_python(raw, strict=True)
        assert isinstance(parsed, expected_type)

    for raw, expected_type in (
        ({"type": "event", "index": 0}, EventProposalRef),
        ({"type": "fact", "index": 0}, FactProposalRef),
    ):
        parsed = PROPOSAL_REF_ADAPTER.validate_python(raw, strict=True)
        assert isinstance(parsed, expected_type)

    parsed_result = SEMANTIC_RESULT_ADAPTER.validate_python(base_result(), strict=True)
    assert isinstance(parsed_result, SemanticResultV1)
    accepted = AcceptedSemanticResult(type="accepted", value=parsed_result, next_status="running")
    rejected = RejectedSemanticResult(
        type="rejected",
        issues=(ValidationIssue(path="schema", code="schema", message="schema validation failed"),),
        next_status="aborted",
    )
    assert isinstance(
        SEMANTIC_OUTCOME_ADAPTER.validate_python(accepted, strict=True),
        AcceptedSemanticResult,
    )
    assert isinstance(
        SEMANTIC_OUTCOME_ADAPTER.validate_python(rejected, strict=True),
        RejectedSemanticResult,
    )

    provisional = TypeAdapter(ProvisionalDetail).validate_python(
        {
            "id": "entity:door",
            "kind": "object",
            "label": "wooden door",
            "scene_id": "scene:hall",
            "visibility": "player_visible",
        },
        strict=True,
    )
    assert isinstance(provisional, ProvisionalDetail)
    fact = TypeAdapter(ProposedFact).validate_python(_fact_proposal(), strict=True)
    assert isinstance(fact, ProposedFact)


def test_public_type_adapters_cover_nested_annotation_and_context_models() -> None:
    from neontof.contracts.semantic_result import (
        EvidenceClaim,
        EvidenceRef,
        Ruling,
        SemanticResultV1,
        SemanticValidationContext,
    )

    context = _context()
    values: tuple[tuple[type[object], object], ...] = (
        (EvidenceClaim, _evidence_claim()["claim"]),
        (EvidenceRef, _evidence_claim()),
        (Ruling, _ruling(facts_used=[DOOR_FACT_ID])),
        (SemanticResultV1, base_result()),
        (SemanticValidationContext, context),
    )
    for model, raw in values:
        parsed = TypeAdapter(model).validate_python(raw, strict=True)
        assert isinstance(parsed, model)


def test_roll_spec_type_adapter_revalidates_a_constructed_instance() -> None:
    from neontof.contracts.semantic_result import RollSpec

    adapter = TypeAdapter(RollSpec)
    constructed = RollSpec(formula="1d20")
    field_name = next(iter(RollSpec.model_fields))
    object.__setattr__(constructed, field_name, object())
    with pytest.raises(ValidationError):
        adapter.validate_python(constructed, strict=True)


def test_validate_semantic_result_has_the_public_typed_signature() -> None:
    from neontof.contracts.semantic_result import (
        RawSemanticResultInput,
        SemanticValidationContext,
        SemanticValidationOutcome,
        validate_semantic_result,
    )

    signature = inspect.signature(validate_semantic_result)
    assert tuple(signature.parameters) == ("input_value", "context")
    annotations = inspect.get_annotations(validate_semantic_result, eval_str=True)
    assert annotations["input_value"] is RawSemanticResultInput
    assert annotations["context"] is SemanticValidationContext
    assert annotations["return"] is SemanticValidationOutcome
    context_annotations = get_type_hints(SemanticValidationContext.__init__)
    assert context_annotations["current_turn_status"] == Literal["running", "awaiting_player"]


def test_valid_control_and_proposal_keep_semantic_result_separate_from_narrative() -> None:
    control = _assert_accepted(
        _evaluate(load_fixture("valid-control.v1.json")),
        "running",
    )
    assert control.value.proposed_events == ()
    assert control.value.proposed_facts == ()
    assert control.value.narrative == "The lantern remains unlit beside the gate."

    proposal = _assert_accepted(
        _evaluate(load_fixture("valid-proposals.v1.json")),
        "running",
    )
    assert len(proposal.value.proposed_events) == 1
    assert len(proposal.value.proposed_facts) == 1
    assert proposal.value.narrative.startswith("The door opens")


def test_valid_rejection_is_an_accepted_semantic_result_control() -> None:
    result = _assert_accepted(_evaluate(load_fixture("valid-rejection.v1.json")), "awaiting_player")
    assert result.value.rejection is not None
    assert result.value.rejection.next_status == "awaiting_player"
    assert result.value.clarification_request is None

    aborted = base_result()
    aborted["rejection"] = {"reason": "The scene has ended.", "next_status": "aborted"}
    aborted_result = _assert_accepted(_evaluate(aborted), "aborted")
    assert aborted_result.value.rejection is not None


@pytest.mark.parametrize(
    ("current_status", "clarification", "rejection", "proposals"),
    [
        (status, clarification, rejection, proposals)
        for status in ("running", "awaiting_player")
        for clarification, rejection, proposals in product((False, True), repeat=3)
    ],
    ids=lambda value: str(value),
)
def test_control_decision_table_is_fixed_for_both_turn_statuses(
    current_status: TurnStatus,
    clarification: bool,
    rejection: bool,
    proposals: bool,
) -> None:
    raw = base_result()
    if clarification:
        raw["clarification_request"] = {"question": "Which gate?"}
    if rejection:
        raw["rejection"] = {"reason": "Choose another action.", "next_status": "aborted"}
    if proposals:
        raw["proposed_events"] = [_event_proposal()]

    outcome = _evaluate(raw, current_turn_status=current_status)
    has_conflict = (clarification or rejection) and proposals or clarification and rejection
    if has_conflict:
        _assert_rejected(
            outcome,
            "conflicting_control_fields",
            _validation_failure_next_status(current_status),
        )
        return

    if clarification:
        _assert_accepted(outcome, "awaiting_player")
    elif rejection:
        _assert_accepted(outcome, "aborted")
    else:
        _assert_accepted(outcome, "running")


def test_clarification_fixture_is_accepted_without_a_state_proposal() -> None:
    outcome = _assert_accepted(
        _evaluate(load_fixture("valid-clarification.v1.json")),
        "awaiting_player",
    )
    assert outcome.value.clarification_request is not None
    assert outcome.value.proposed_events == ()
    assert outcome.value.proposed_facts == ()


@pytest.mark.parametrize("current_status", ("running", "awaiting_player"))
@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("invalid-unknown-field.v1.json", "unknown_field"),
        ("invalid-unknown-version.v1.json", "unknown_version"),
        ("invalid-proposal.v1.json", "invalid_event_proposal"),
        ("invalid-proposal-ref.v1.json", "invalid_proposal_ref"),
        ("duplicate-proposal.v1.json", "duplicate_proposal"),
    ],
)
def test_invalid_and_duplicate_fixtures_are_rejected_with_limited_codes(
    current_status: TurnStatus,
    fixture_name: str,
    expected_code: str,
) -> None:
    outcome = _assert_rejected(
        _evaluate(load_fixture(fixture_name), current_turn_status=current_status),
        expected_code,
        _validation_failure_next_status(current_status),
    )
    assert _codes(outcome) <= {
        "schema",
        "unknown_field",
        "unknown_version",
        "invalid_result",
        "invalid_event_proposal",
        "invalid_fact_proposal",
        "invalid_proposal_ref",
        "duplicate_proposal",
        "conflicting_control_fields",
    }


@pytest.mark.parametrize(
    ("failure_kind", "expected_codes"),
    (
        ("schema", {"schema", "invalid_event_proposal"}),
        ("context", {"unknown_resource"}),
    ),
)
@pytest.mark.parametrize("current_status", ("running", "awaiting_player"))
def test_schema_and_context_validation_failures_set_status_by_current_turn(
    failure_kind: str,
    expected_codes: set[str],
    current_status: TurnStatus,
) -> None:
    raw = base_result()
    if failure_kind == "schema":
        raw["proposed_events"] = [_event_proposal(delta="2")]
    else:
        raw["proposed_events"] = [_event_proposal(resource_id="resource:silver")]

    outcome = _evaluate(raw, current_turn_status=current_status)
    assert outcome.type == "rejected"
    assert _codes(outcome) & expected_codes
    assert outcome.next_status == _validation_failure_next_status(current_status)


@pytest.mark.parametrize(
    ("mutated", "expected_code"),
    [
        (_event_proposal(resource_id="resource:silver"), "unknown_resource"),
        (_event_proposal(entity_id="entity:outsider"), "unknown_entity"),
        (_character_proposal(character_id="character:outsider"), "unknown_character"),
        (_character_proposal(to_location_id="location:outsider"), "unknown_location"),
        (_clock_proposal(clock_id="clock:outsider"), "unknown_clock"),
    ],
    ids=["resource", "entity", "character", "location", "clock"],
)
def test_proposal_reference_whitelists_reject_unknown_ids(
    mutated: dict[str, object],
    expected_code: str,
) -> None:
    raw = base_result()
    raw["proposed_events"] = [mutated]
    _assert_rejected(_evaluate(raw), expected_code)


def test_proposed_event_whitelist_is_exactly_the_three_state_proposals() -> None:
    proposals = (
        _event_proposal(),
        _character_proposal(),
        _clock_proposal(),
    )
    observed: set[str] = set()
    for proposal in proposals:
        raw = base_result()
        raw["proposed_events"] = [proposal]
        accepted = _assert_accepted(_evaluate(raw), "running")
        observed.add(accepted.value.proposed_events[0].type)

    assert observed == {"ResourceChanged", "CharacterMoved", "ClockAdvanced"}


@pytest.mark.parametrize(
    "forbidden_type",
    (
        "CampaignCreated",
        "SessionStarted",
        "SessionEnded",
        "SceneStarted",
        "SceneEnded",
        "PlayerInputAccepted",
        "DiceRolled",
        "FactAsserted",
        "FactSuperseded",
        "TurnCommitted",
        "TurnAwaitingPlayer",
        "TurnAborted",
        "TurnResumed",
        "TurnReverted",
    ),
)
def test_proposed_event_whitelist_rejects_lifecycle_and_non_proposal_events(
    forbidden_type: str,
) -> None:
    raw = base_result()
    raw["proposed_events"] = [{"type": forbidden_type, "payload": {}}]
    _assert_rejected(_evaluate(raw), "invalid_event_proposal")


def test_fact_subject_and_npc_reference_whitelists_are_fail_closed() -> None:
    unknown_subject = base_result()
    unknown_subject["proposed_facts"] = [_fact_proposal(subject_id="entity:outsider")]
    _assert_rejected(_evaluate(unknown_subject), "unknown_entity")

    unknown_holder = base_result()
    unknown_holder["proposed_facts"] = [_fact_proposal(holder="npc:outsider")]
    _assert_rejected(_evaluate(unknown_holder), "unknown_entity")

    unknown_visibility = base_result()
    unknown_visibility["proposed_facts"] = [_fact_proposal(visibility="npc:outsider")]
    _assert_rejected(_evaluate(unknown_visibility), "unknown_entity")


def test_strict_bool_and_integer_proposal_values_are_not_coerced() -> None:
    raw = base_result()
    raw["proposed_events"] = [_event_proposal(delta=True)]
    outcome = _evaluate(raw)
    assert outcome.type == "rejected"
    assert _codes(outcome) & {"schema", "invalid_event_proposal"}

    clock = base_result()
    clock["proposed_events"] = [_clock_proposal(delta="1")]
    clock_outcome = _evaluate(clock)
    assert clock_outcome.type == "rejected"
    assert _codes(clock_outcome) & {"schema", "invalid_event_proposal"}


def test_duplicate_proposed_events_are_not_silently_dropped() -> None:
    duplicate_event = base_result()
    duplicate_event["proposed_events"] = [_event_proposal(), _event_proposal()]
    _assert_rejected(_evaluate(duplicate_event), "duplicate_proposal")


def test_duplicate_proposed_facts_are_not_silently_dropped() -> None:
    duplicate_fact = base_result()
    duplicate_fact["proposed_facts"] = [_fact_proposal(), _fact_proposal()]
    _assert_rejected(_evaluate(duplicate_fact), "duplicate_proposal")


def test_duplicate_proposal_refs_are_not_silently_dropped() -> None:
    duplicate_ref = base_result()
    duplicate_ref["proposed_events"] = [_event_proposal()]
    duplicate_ref["rulings"] = [
        _ruling(
            proposed_effects=(
                {"type": "event", "index": 0},
                {"type": "event", "index": 0},
            )
        )
    ]
    _assert_rejected(_evaluate(duplicate_ref), "duplicate_proposal")


@pytest.mark.parametrize("ref_type", ("event", "fact"))
@pytest.mark.parametrize(
    ("index", "expected_codes"),
    ((-1, {"schema", "invalid_proposal_ref"}), (1, {"invalid_proposal_ref"})),
)
def test_proposal_refs_reject_out_of_range_indexes(
    ref_type: str,
    index: int,
    expected_codes: set[str],
) -> None:
    raw = base_result()
    if ref_type == "event":
        raw["proposed_events"] = [_event_proposal()]
    else:
        raw["proposed_facts"] = [_fact_proposal()]
    raw["rulings"] = [_ruling(proposed_effects=[{"type": ref_type, "index": index}])]
    outcome = _evaluate(raw)
    assert outcome.type == "rejected"
    assert _codes(outcome) & expected_codes


@pytest.mark.parametrize("ref_type", ("event", "fact"))
def test_duplicate_event_and_fact_proposal_refs_are_rejected(ref_type: str) -> None:
    raw = base_result()
    if ref_type == "event":
        raw["proposed_events"] = [_event_proposal()]
    else:
        raw["proposed_facts"] = [_fact_proposal()]
    duplicate_ref = {"type": ref_type, "index": 0}
    raw["rulings"] = [_ruling(proposed_effects=[duplicate_ref, copy.deepcopy(duplicate_ref)])]
    _assert_rejected(_evaluate(raw), "duplicate_proposal")


def test_evidence_fixture_accepts_existing_visible_fact() -> None:
    outcome = _assert_accepted(
        _evaluate(load_fixture("valid-evidence.v1.json")),
        "running",
    )
    assert len(outcome.value.evidence) == 1
    assert outcome.value.evidence[0].claim.fact_id == DOOR_FACT_ID


@pytest.mark.parametrize(
    ("claim", "expected_code"),
    [
        (_evidence_claim(fact_id="fact:" + "0" * 64 + ":0"), "unknown_fact"),
        (_evidence_claim(predicate="is_closed"), "claim_mismatch"),
        (_evidence_claim(value=False), "claim_mismatch"),
    ],
    ids=["unknown", "predicate", "value"],
)
def test_evidence_claim_lookup_rejects_unknown_or_mismatched_claims(
    claim: dict[str, object],
    expected_code: str,
) -> None:
    raw = base_result()
    raw["evidence"] = [claim]
    _assert_rejected(_evaluate(raw), expected_code)


def test_evidence_visibility_rejects_invisible_and_unrelated_npc_facts() -> None:
    gm_fact = _custom_fact(event_id="event:gm-fact", visibility="gm_only")
    gm_raw = base_result()
    gm_raw["evidence"] = [_evidence_claim(fact_id=gm_fact.fact_id)]
    _assert_rejected(
        _evaluate(gm_raw, fact=gm_fact, publication_visibility="player_visible"),
        "invisible_fact",
    )

    npc_fact = _custom_fact(
        event_id="event:guard-fact",
        holder="npc:guard",
        visibility="npc:guard",
    )
    npc_raw = base_result()
    npc_raw["evidence"] = [_evidence_claim(fact_id=npc_fact.fact_id)]
    _assert_accepted(
        _evaluate(
            npc_raw,
            fact=npc_fact,
            publication_visibility="npc:guard",
            known_npc_ids=frozenset({"npc:guard", "npc:other"}),
        ),
        "running",
    )
    _assert_rejected(
        _evaluate(
            npc_raw,
            fact=npc_fact,
            publication_visibility="npc:other",
            known_npc_ids=frozenset({"npc:guard", "npc:other"}),
        ),
        "unrelated_visible_fact",
    )

    unknown_npc_raw = base_result()
    unknown_npc_raw["evidence"] = [_evidence_claim(fact_id=npc_fact.fact_id)]
    _assert_rejected(
        _evaluate(
            unknown_npc_raw,
            fact=npc_fact,
            publication_visibility="npc:unknown",
            known_npc_ids=frozenset({"npc:guard"}),
        ),
        "unknown_entity",
    )


@pytest.mark.parametrize(
    ("publication_visibility", "fact_visibility", "holder", "expected_code"),
    (
        ("player_visible", "player_visible", "world", None),
        ("npc:guard", "npc:guard", "npc:guard", None),
        ("npc:guard", "gm_only", "world", "invisible_fact"),
        ("npc:guard", "player_visible", "world", "invisible_fact"),
        ("player_visible", "npc:guard", "npc:guard", "invisible_fact"),
    ),
)
def test_evidence_visibility_matrix_covers_player_and_npc_publication(
    publication_visibility: str,
    fact_visibility: str,
    holder: str,
    expected_code: str | None,
) -> None:
    fact = _custom_fact(
        event_id="event:visibility-matrix",
        holder=holder,
        visibility=fact_visibility,
    )
    raw = base_result()
    raw["evidence"] = [_evidence_claim(fact_id=fact.fact_id)]
    outcome = _evaluate(
        raw,
        fact=fact,
        publication_visibility=publication_visibility,
        known_npc_ids=frozenset({"npc:guard"}),
    )
    if expected_code is None:
        _assert_accepted(outcome, "running")
    else:
        _assert_rejected(outcome, expected_code)


def test_unknown_npc_is_rejected_in_fact_record_holder_and_provisional_detail() -> None:
    unknown_holder_fact = _custom_fact(
        event_id="event:unknown-holder",
        holder="npc:outsider",
        visibility="npc:outsider",
    )
    evidence = base_result()
    evidence["evidence"] = [_evidence_claim(fact_id=unknown_holder_fact.fact_id)]
    holder_outcome = _evaluate(
        evidence,
        fact=unknown_holder_fact,
        publication_visibility="npc:guard",
        known_npc_ids=frozenset({"npc:guard"}),
    )
    assert holder_outcome.type == "rejected"
    assert _codes(holder_outcome) & {"unknown_entity", "invalid_result"}

    detail = base_result()
    detail["mentioned_details"] = [
        {
            "id": "entity:door",
            "kind": "object",
            "label": "wooden door",
            "scene_id": "scene:hall",
            "visibility": "npc:outsider",
        }
    ]
    detail_outcome = _evaluate(
        detail,
        publication_visibility="player_visible",
        known_npc_ids=frozenset({"npc:guard"}),
    )
    _assert_rejected(detail_outcome, "unknown_entity")


@pytest.mark.parametrize(
    (
        "publication_visibility",
        "detail_id",
        "detail_kind",
        "detail_visibility",
        "known_npc_ids",
        "expected_codes",
    ),
    (
        (
            "player_visible",
            "entity:door",
            "object",
            "player_visible",
            frozenset({"npc:guard"}),
            None,
        ),
        (
            "npc:guard",
            "npc:guard",
            "npc",
            "npc:guard",
            frozenset({"npc:guard"}),
            None,
        ),
        (
            "npc:guard",
            "entity:door",
            "npc",
            "player_visible",
            frozenset({"npc:guard"}),
            {"invalid_result", "unknown_entity", "schema"},
        ),
        (
            "npc:guard",
            "npc:outsider",
            "npc",
            "npc:outsider",
            frozenset({"npc:guard"}),
            {"unknown_entity", "invalid_result"},
        ),
        (
            "npc:guard",
            "npc:other",
            "npc",
            "npc:other",
            frozenset({"npc:guard", "npc:other"}),
            {"unrelated_visible_fact", "invalid_result", "unknown_entity"},
        ),
    ),
    ids=("player", "same-npc", "npc-id-grammar", "unknown-npc", "unrelated-npc"),
)
def test_provisional_detail_visibility_and_npc_grammar_are_fail_closed(
    publication_visibility: str,
    detail_id: str,
    detail_kind: str,
    detail_visibility: str,
    known_npc_ids: frozenset[str],
    expected_codes: set[str] | None,
) -> None:
    raw = base_result()
    raw["mentioned_details"] = [
        {
            "id": detail_id,
            "kind": detail_kind,
            "label": "detail",
            "scene_id": "scene:hall",
            "visibility": detail_visibility,
        }
    ]
    outcome = _evaluate(
        raw,
        publication_visibility=publication_visibility,
        known_npc_ids=known_npc_ids,
    )
    if expected_codes is None:
        _assert_accepted(outcome, "running")
    else:
        assert outcome.type == "rejected"
        assert _codes(outcome) & expected_codes


def test_evidence_value_uses_deep_equality_with_bool_int_distinction() -> None:
    value = {"nested": [{"rank": 1, "label": "door"}], "enabled": True}
    fact = _custom_fact(event_id="event:nested-fact", predicate="state", value=value)

    matching = base_result()
    matching["evidence"] = [_evidence_claim(fact_id=fact.fact_id, predicate="state", value=value)]
    _assert_accepted(_evaluate(matching, fact=fact), "running")

    changed_leaf = base_result()
    changed_leaf["evidence"] = [
        _evidence_claim(
            fact_id=fact.fact_id,
            predicate="state",
            value={"nested": [{"rank": 2, "label": "door"}], "enabled": True},
        )
    ]
    _assert_rejected(_evaluate(changed_leaf, fact=fact), "claim_mismatch")

    bool_int = base_result()
    bool_int["evidence"] = [
        _evidence_claim(
            fact_id=fact.fact_id,
            predicate="state",
            value={"nested": [{"rank": 1, "label": "door"}], "enabled": 1},
        )
    ]
    _assert_rejected(_evaluate(bool_int, fact=fact), "claim_mismatch")


def test_facts_by_id_key_and_fact_id_must_match_and_keys_must_be_unique() -> None:
    fact = _door_fact()
    duplicate = base_result()
    duplicate["evidence"] = [_evidence_claim()]
    duplicate_outcome = _evaluate(
        duplicate,
        facts_by_id=((fact.fact_id, fact), (fact.fact_id, fact)),
    )
    _assert_rejected(duplicate_outcome, "invalid_result")

    mismatched_key = base_result()
    mismatched_key["evidence"] = [_evidence_claim()]
    other_key = "fact:" + "1" * 64 + ":0"
    mismatch_outcome = _evaluate(
        mismatched_key,
        facts_by_id=((other_key, fact),),
    )
    _assert_rejected(mismatch_outcome, "invalid_result")


def _sequence_sample(field: str, fact: Any) -> list[object]:
    if field == "rulings":
        return [_ruling(facts_used=[fact.fact_id])]
    if field == "proposed_events":
        return [_event_proposal()]
    if field == "proposed_facts":
        return [_fact_proposal()]
    if field == "knowledge_changes":
        return [{"note": "The player now knows the gate is nearby."}]
    if field == "visibility_changes":
        return [{"note": "The gate is visible to the player."}]
    if field == "narrative_plan":
        return [{"text": "Describe the stillness."}]
    if field == "mentioned_details":
        return [
            {
                "id": "entity:door",
                "kind": "object",
                "label": "wooden door",
                "scene_id": "scene:hall",
                "visibility": "player_visible",
            }
        ]
    if field == "evidence":
        return [_evidence_claim()]
    if field == "suggested_actions":
        return [{"label": "Wait."}]
    raise AssertionError(field)


def _set_sequence_field(raw: dict[str, Any], field: str, value: object, fact: Any) -> None:
    if field in ROOT_SEQUENCE_FIELDS:
        raw[field] = value
        return
    ruling = _ruling(facts_used=[fact.fact_id])
    ruling[field] = value
    raw["rulings"] = [ruling]


@pytest.mark.parametrize("field", ROOT_SEQUENCE_FIELDS)
@pytest.mark.parametrize("container_kind", ("list", "tuple"))
def test_exact_sequence_fields_copy_plain_list_and_tuple_inputs(
    field: str,
    container_kind: str,
) -> None:
    fact = _door_fact()
    sample = _sequence_sample(field, fact)
    source: object = list(copy.deepcopy(sample))
    if container_kind == "tuple":
        source = tuple(copy.deepcopy(sample))
    raw = base_result()
    _set_sequence_field(raw, field, source, fact)

    outcome = _assert_accepted(_evaluate(raw), "running")
    if field in ROOT_SEQUENCE_FIELDS:
        stored = getattr(outcome.value, field)
    else:
        stored = getattr(outcome.value.rulings[0], field)
    assert type(stored) is tuple
    assert stored is not source

    if isinstance(source, list):
        source.append(copy.deepcopy(sample[0]))
        assert len(stored) == 1


@pytest.mark.parametrize("field", RULING_SEQUENCE_FIELDS)
@pytest.mark.parametrize("container_kind", ("list", "tuple"))
def test_ruling_nested_sequence_fields_copy_and_block_mutation_propagation(
    field: str,
    container_kind: str,
) -> None:
    fact = _door_fact()
    values: dict[str, list[object]] = {
        "rule_refs": ["rule:gate"],
        "facts_used": [fact.fact_id],
        "proposed_effects": [{"type": "event", "index": 0}],
    }
    source_list = copy.deepcopy(values[field])
    source: object = source_list
    if container_kind == "tuple":
        source = tuple(copy.deepcopy(source_list))

    raw = base_result()
    if field == "proposed_effects":
        raw["proposed_events"] = [_event_proposal()]
    ruling = _ruling()
    ruling[field] = source
    raw["rulings"] = [ruling]

    outcome = _assert_accepted(_evaluate(raw), "running")
    stored = getattr(outcome.value.rulings[0], field)
    assert type(stored) is tuple
    assert stored is not source
    stored_before_source_mutation = copy.deepcopy(stored)

    assert isinstance(source, (list, tuple))
    if isinstance(source, list):
        source.append(copy.deepcopy(source[0]))
    if field == "proposed_effects":
        first_effect = source[0]
        assert isinstance(first_effect, dict)
        first_effect["index"] = 99
    assert stored == stored_before_source_mutation


class _ListSubclass(list[object]):
    pass


class _TupleSubclass(tuple[object, ...]):
    pass


@pytest.mark.parametrize("field", ROOT_SEQUENCE_FIELDS + RULING_SEQUENCE_FIELDS)
@pytest.mark.parametrize("container_kind", ("list_subclass", "tuple_subclass", "generator", "set"))
def test_exact_sequence_fields_reject_non_exact_sequence_inputs(
    field: str,
    container_kind: str,
) -> None:
    fact = _door_fact()
    sample = _sequence_sample("rulings" if field in RULING_SEQUENCE_FIELDS else field, fact)
    if field in RULING_SEQUENCE_FIELDS:
        sample = {
            "rule_refs": ["rule:gate"],
            "facts_used": [fact.fact_id],
            "proposed_effects": [],
        }[field]

    if container_kind == "list_subclass":
        value: object = _ListSubclass(sample)
    elif container_kind == "tuple_subclass":
        value = _TupleSubclass(sample)
    elif container_kind == "generator":
        value = (item for item in sample)
    else:
        value = set()

    raw = base_result()
    _set_sequence_field(raw, field, value, fact)
    outcome = _evaluate(raw)
    assert outcome.type == "rejected"
    assert _codes(outcome) & {
        "schema",
        "invalid_result",
        "invalid_event_proposal",
        "invalid_fact_proposal",
        "invalid_proposal_ref",
    }


def test_semantic_context_facts_by_id_has_the_same_exact_tuple_boundary() -> None:
    from neontof.contracts.semantic_result import SemanticValidationContext

    fact = _door_fact()
    context_data: dict[str, object] = {
        "known_entity_ids": frozenset({"entity:hero", "entity:door"}),
        "known_npc_ids": frozenset({"npc:guard"}),
        "known_fact_subject_ids": frozenset({"entity:door"}),
        "known_resource_ids": frozenset({"resource:gold"}),
        "known_character_ids": frozenset({"character:hero"}),
        "known_location_ids": frozenset({"location:gate"}),
        "known_clock_ids": frozenset({"clock:session"}),
        "facts_by_id": [(fact.fact_id, fact)],
        "current_turn_status": "running",
        "publication_visibility": "player_visible",
    }
    context = SemanticValidationContext.model_validate(context_data)
    assert type(context.facts_by_id) is tuple
    context_data["facts_by_id"] = [(fact.fact_id, fact)]
    assert context.facts_by_id is not context_data["facts_by_id"]

    invalid: object
    for invalid in (
        _ListSubclass([(fact.fact_id, fact)]),
        _TupleSubclass([(fact.fact_id, fact)]),
        (item for item in [(fact.fact_id, fact)]),
        set(),
    ):
        invalid_data = dict(context_data)
        invalid_data["facts_by_id"] = invalid
        with pytest.raises(ValidationError):
            SemanticValidationContext.model_validate(invalid_data)


def test_semantic_root_accepts_raw_mapping_but_rejects_frozen_json_representation() -> None:
    from neontof.contracts.base import FrozenJsonValue
    from neontof.contracts.semantic_result import SemanticResultV1

    raw = load_fixture("valid-control.v1.json")
    typed = SemanticResultV1.model_validate(raw)
    _assert_accepted(_evaluate(typed), "running")

    frozen_root = TypeAdapter(FrozenJsonValue).validate_python(raw, strict=True)
    rejected = _evaluate(frozen_root)
    assert rejected.type == "rejected"
    assert _codes(rejected) & {"schema", "invalid_result"}


def _assert_sanitized(outcome: Any, sentinels: tuple[str, ...]) -> None:
    assert outcome.type == "rejected"
    surfaces = (
        str(outcome),
        repr(outcome),
        repr(outcome.__dict__),
        str(outcome.issues),
        repr(outcome.issues),
    )
    for sentinel in sentinels:
        assert all(sentinel not in surface for surface in surfaces)
        assert all(sentinel not in str(issue) for issue in outcome.issues)
        assert all(sentinel not in repr(issue) for issue in outcome.issues)


def test_schema_and_nested_validation_errors_are_sanitized() -> None:
    field_sentinel = "RAW_FIELD_SECRET_SENTINEL"
    value_sentinel = "RAW_VALUE_SECRET_SENTINEL"
    url_sentinel = "https://redaction.invalid/private"

    raw = base_result()
    raw[field_sentinel] = {"value": value_sentinel, "url": url_sentinel}
    outcome = _evaluate(raw)
    _assert_sanitized(outcome, (field_sentinel, value_sentinel, url_sentinel))

    nested = base_result()
    nested["evidence"] = [
        {
            "claim": {
                "fact_id": value_sentinel,
                "predicate": "is_open",
                "value": url_sentinel,
            }
        }
    ]
    nested_outcome = _evaluate(nested)
    _assert_sanitized(nested_outcome, (field_sentinel, value_sentinel, url_sentinel))


def test_evidence_claim_normalizer_is_private_and_validation_error_does_not_escape() -> None:
    semantic_result = importlib.import_module("neontof.contracts.semantic_result")

    assert "_normalize_evidence_claim" not in getattr(semantic_result, "__all__", ())
    raw = base_result()
    raw["evidence"] = [{"claim": {"unexpected": "not a claim"}}]
    outcome = _evaluate(raw)
    assert outcome.type == "rejected"
    assert all(issue.code in {"schema", "invalid_result"} for issue in outcome.issues)


def test_narrative_and_annotation_only_result_materializes_zero_events() -> None:
    raw = base_result()
    raw.update(
        {
            "rulings": [_ruling()],
            "knowledge_changes": [{"note": "A note only."}],
            "visibility_changes": [{"note": "A visibility note only."}],
            "narrative_plan": [{"text": "A beat only."}],
            "narrative": "The narrator adds a new detail.",
            "mentioned_details": [
                {
                    "id": "entity:door",
                    "kind": "object",
                    "label": "door",
                    "scene_id": "scene:hall",
                    "visibility": "player_visible",
                }
            ],
            "suggested_actions": [{"label": "Wait."}],
        }
    )
    accepted = _assert_accepted(_evaluate(raw), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    assert materialize_semantic_result_for_test(accepted, context) == ()


def test_narrative_changes_do_not_change_materialized_state_proposals() -> None:
    first = base_result()
    first["proposed_events"] = [_event_proposal()]
    first["narrative"] = "The first prose says one thing."
    second = copy.deepcopy(first)
    second["narrative"] = "The second prose says something else."

    accepted_first = _assert_accepted(_evaluate(first), "running")
    accepted_second = _assert_accepted(_evaluate(second), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    assert materialize_semantic_result_for_test(
        accepted_first, context
    ) == materialize_semantic_result_for_test(accepted_second, context)


def test_materializer_accepts_only_accepted_result_and_emits_one_event_per_proposal() -> None:
    accepted = _assert_accepted(_evaluate(load_fixture("valid-proposals.v1.json")), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    events = materialize_semantic_result_for_test(accepted, context)
    assert len(events) == 2
    assert tuple(event.event_id for event in events) == (
        "event:fixture-1",
        "event:fixture-2",
    )
    assert len({event.event_id for event in events}) == len(events)

    with pytest.raises(TypeError):
        _invoke_with_runtime_arguments(
            materialize_semantic_result_for_test,
            {"type": "rejected"},
            context,
        )


def test_materializer_matches_handwritten_domain_events_and_projection_fact_ids() -> None:
    from neontof.contracts.domain import (
        FactAssertedEvent,
        FactAssertedPayload,
        ResourceChangedEvent,
        ResourceChangedPayload,
    )
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import derive_fact_id, rebuild_projection

    accepted = _assert_accepted(_evaluate(load_fixture("valid-proposals.v1.json")), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    events = materialize_semantic_result_for_test(accepted, context)
    expected = (
        ResourceChangedEvent(
            type="ResourceChanged",
            event_id="event:fixture-1",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=1,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=ResourceChangedPayload(
                resource_id="resource:gold",
                entity_id="entity:hero",
                delta=2,
            ),
        ),
        FactAssertedEvent(
            type="FactAsserted",
            event_id="event:fixture-2",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=2,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=FactAssertedPayload(
                kind="fact",
                holder="world",
                subject_id="entity:door",
                predicate="is_open",
                value=True,
            ),
        ),
    )
    assert events == expected

    wire = json.dumps([event.model_dump(mode="json") for event in events])
    parsed = parse_domain_event_sequence(wire)
    projection = rebuild_projection(parsed)
    assert projection.resources[0].value == 2
    assert len(projection.facts) == 1
    assert projection.facts[0].fact_id == derive_fact_id("event:fixture-2", 0)
    assert projection.facts[0].fact_id == derive_fact_id(parsed[1].event_id, 0)


def test_materializer_oracle_maps_all_four_allowed_proposals() -> None:
    from neontof.contracts.domain import (
        CharacterMovedEvent,
        CharacterMovedPayload,
        ClockAdvancedEvent,
        ClockAdvancedPayload,
        FactAssertedEvent,
        FactAssertedPayload,
        ResourceChangedEvent,
        ResourceChangedPayload,
    )

    raw = base_result()
    raw["proposed_events"] = [
        _event_proposal(),
        _character_proposal(from_location_id="location:hall"),
        _clock_proposal(),
    ]
    raw["proposed_facts"] = [_fact_proposal()]
    accepted = _assert_accepted(_evaluate(raw), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=7,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    events = materialize_semantic_result_for_test(accepted, context)
    expected = (
        ResourceChangedEvent(
            type="ResourceChanged",
            event_id="event:fixture-7",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=7,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=ResourceChangedPayload(
                resource_id="resource:gold",
                entity_id="entity:hero",
                delta=2,
            ),
        ),
        CharacterMovedEvent(
            type="CharacterMoved",
            event_id="event:fixture-8",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=8,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=CharacterMovedPayload(
                character_id="character:hero",
                from_location_id="location:hall",
                to_location_id="location:gate",
            ),
        ),
        ClockAdvancedEvent(
            type="ClockAdvanced",
            event_id="event:fixture-9",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=9,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=ClockAdvancedPayload(clock_id="clock:session", delta=1),
        ),
        FactAssertedEvent(
            type="FactAsserted",
            event_id="event:fixture-10",
            event_version=1,
            campaign_id="campaign:alpha",
            session_id="session:one",
            scene_id="scene:hall",
            turn_id="turn:one",
            sequence=10,
            occurred_at="2026-08-19T14:00:01Z",
            origin="in_world",
            visibility="player_visible",
            payload=FactAssertedPayload(
                kind="fact",
                holder="world",
                subject_id="entity:door",
                predicate="is_open",
                value=True,
            ),
        ),
    )
    assert events == expected
    assert tuple(event.type for event in events) == (
        "ResourceChanged",
        "CharacterMoved",
        "ClockAdvanced",
        "FactAsserted",
    )
    assert all(event.event_id.startswith("event:fixture-") for event in events)
    assert tuple(event.sequence for event in events) == (7, 8, 9, 10)

    repeated = materialize_semantic_result_for_test(accepted, context)
    assert events == repeated
    assert tuple(event.model_dump(mode="json") for event in events) == tuple(
        event.model_dump(mode="json") for event in repeated
    )


def test_materializer_fragments_preserve_sequence_event_and_fact_prefixes() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import derive_fact_id, rebuild_projection

    first_raw = base_result()
    first_raw["proposed_events"] = [_event_proposal()]
    first_raw["proposed_facts"] = [_fact_proposal(predicate="fragment_one", value=True)]
    second_raw = base_result()
    second_raw["proposed_events"] = [_clock_proposal()]
    second_raw["proposed_facts"] = [_fact_proposal(predicate="fragment_two", value=2)]

    first = _assert_accepted(_evaluate(first_raw), "running")
    second = _assert_accepted(_evaluate(second_raw), "running")
    first_context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    second_context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=3,
        occurred_at="2026-08-19T14:00:02Z",
        origin="in_world",
        visibility="player_visible",
    )
    first_events = materialize_semantic_result_for_test(first, first_context)
    second_events = materialize_semantic_result_for_test(second, second_context)
    combined = first_events + second_events

    assert tuple(event.sequence for event in combined) == (1, 2, 3, 4)
    assert tuple(event.event_id for event in combined) == (
        "event:fixture-1",
        "event:fixture-2",
        "event:fixture-3",
        "event:fixture-4",
    )

    parsed = parse_domain_event_sequence(
        json.dumps([event.model_dump(mode="json") for event in combined])
    )
    projection = rebuild_projection(parsed)
    fact_events = tuple(event for event in parsed if event.type == "FactAsserted")
    assert {(fact.event_id, fact.fact_id) for fact in projection.facts} == {
        (event.event_id, derive_fact_id(event.event_id, 0)) for event in fact_events
    }
    assert len({fact.fact_id for fact in projection.facts}) == 2

    facts_by_id = tuple((fact.fact_id, fact) for fact in projection.facts)
    evidence = base_result()
    evidence["evidence"] = [
        _evidence_claim(
            fact_id=fact.fact_id,
            predicate=fact.predicate,
            value=fact.value,
        )
        for fact in projection.facts
    ]
    _assert_accepted(_evaluate(evidence, facts_by_id=facts_by_id), "running")


def test_materializer_generated_fact_records_can_return_to_facts_by_id() -> None:
    from neontof.contracts.event_parser import parse_domain_event_sequence
    from neontof.contracts.projection import rebuild_projection

    raw = base_result()
    raw["proposed_facts"] = [_fact_proposal(predicate="is_open", value=True)]
    accepted = _assert_accepted(_evaluate(raw), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    events = materialize_semantic_result_for_test(accepted, context)
    projection = rebuild_projection(
        parse_domain_event_sequence(json.dumps([event.model_dump(mode="json") for event in events]))
    )
    assert len(projection.facts) == 1
    generated_fact = projection.facts[0]
    facts_by_id = ((generated_fact.fact_id, generated_fact),)

    evidence = base_result()
    evidence["evidence"] = [_evidence_claim(fact_id=generated_fact.fact_id)]
    _assert_accepted(_evaluate(evidence, facts_by_id=facts_by_id), "running")


def test_multiple_fact_materialization_uses_each_event_id_with_ordinal_zero() -> None:
    raw = base_result()
    raw["proposed_facts"] = [
        _fact_proposal(predicate="first_fact", value=True),
        _fact_proposal(predicate="second_fact", value=2),
    ]
    accepted = _assert_accepted(_evaluate(raw), "running")
    context = FixtureEventContext(
        campaign="campaign:alpha",
        session="session:one",
        scene="scene:hall",
        turn="turn:one",
        sequence_start=1,
        occurred_at="2026-08-19T14:00:01Z",
        origin="in_world",
        visibility="player_visible",
    )
    events = materialize_semantic_result_for_test(accepted, context)
    assert tuple(event.event_id for event in events) == (
        "event:fixture-1",
        "event:fixture-2",
    )

    from neontof.contracts.projection import derive_fact_id

    fact_ids = tuple(derive_fact_id(event.event_id, 0) for event in events)
    assert len(set(fact_ids)) == 2


def test_semantic_result_fixture_json_is_utf8_and_contains_no_secret_material() -> None:
    credential_patterns = (
        re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]"),
        re.compile(r"(?i)\bsecret\b\s*[:=]"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}\b"),
        re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
        re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    )
    for path in sorted(SEMANTIC_FIXTURE_ROOT.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        json.loads(text)
        lower = text.lower()
        assert "api_key" not in lower
        assert "api-key" not in lower
        assert "secret" not in lower
        assert "raw_input" not in lower
        assert all(pattern.search(text) is None for pattern in credential_patterns)
