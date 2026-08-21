"""Strict Semantic Result contracts and their pure validation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter, ValidationError

from neontof.contracts.base import ContractModel, FrozenJsonValue
from neontof.contracts.domain import (
    CharacterMovedPayload,
    ClockAdvancedPayload,
    ResourceChangedPayload,
)
from neontof.contracts.ids import (
    CharacterId,
    ClockId,
    EntityId,
    FactHolder,
    FactId,
    FactKind,
    LocationId,
    NpcId,
    ResourceId,
    SceneId,
    Visibility,
)
from neontof.contracts.projection import FactRecord

NonNegativeStrictInt: TypeAlias = Annotated[int, Field(strict=True, ge=0)]  # noqa: UP040
PositiveStrictInt: TypeAlias = Annotated[int, Field(strict=True, gt=0)]  # noqa: UP040

PublicationVisibility: TypeAlias = Literal["player_visible"] | NpcId  # noqa: UP040
_TurnStatus: TypeAlias = Literal["running", "awaiting_player"]  # noqa: UP040


class _ExactSequenceTypeError(TypeError, ValueError):
    """Reject non-exact sequence inputs as both a boundary and Pydantic failure."""


def _copy_exact_sequence(value: object) -> object:
    """Copy only builtin list/tuple inputs into a fresh tuple."""

    if type(value) is list:
        return tuple(item for item in value)
    if type(value) is tuple:
        return tuple(item for item in value)
    raise _ExactSequenceTypeError("sequence must be a builtin list or tuple")


class ProposedResourceChanged(ContractModel):
    type: Literal["ResourceChanged"]
    payload: ResourceChangedPayload


class ProposedCharacterMoved(ContractModel):
    type: Literal["CharacterMoved"]
    payload: CharacterMovedPayload


class ProposedClockAdvanced(ContractModel):
    type: Literal["ClockAdvanced"]
    payload: ClockAdvancedPayload


ProposedEvent: TypeAlias = Annotated[  # noqa: UP040
    ProposedResourceChanged | ProposedCharacterMoved | ProposedClockAdvanced,
    Field(discriminator="type"),
]
PROPOSED_EVENT_ADAPTER: TypeAdapter[ProposedEvent] = TypeAdapter(ProposedEvent)


class ProposedFact(ContractModel):
    kind: FactKind
    holder: FactHolder
    subject_id: EntityId | None
    predicate: str
    value: FrozenJsonValue
    visibility: Visibility


class EventProposalRef(ContractModel):
    type: Literal["event"]
    index: NonNegativeStrictInt


class FactProposalRef(ContractModel):
    type: Literal["fact"]
    index: NonNegativeStrictInt


ProposalRef: TypeAlias = Annotated[  # noqa: UP040
    EventProposalRef | FactProposalRef,
    Field(discriminator="type"),
]
PROPOSAL_REF_ADAPTER: TypeAdapter[ProposalRef] = TypeAdapter(ProposalRef)


class RollSpec(ContractModel):
    formula: str


class Ruling(ContractModel):
    rule_refs: Annotated[tuple[str, ...], BeforeValidator(_copy_exact_sequence)]
    facts_used: Annotated[tuple[FactId, ...], BeforeValidator(_copy_exact_sequence)]
    interpretation: str
    roll_spec: RollSpec | None
    proposed_effects: Annotated[tuple[ProposalRef, ...], BeforeValidator(_copy_exact_sequence)]
    is_house_ruling: bool


class KnowledgeChange(ContractModel):
    note: str


class VisibilityChange(ContractModel):
    note: str


class ClarificationRequest(ContractModel):
    question: str


class Rejection(ContractModel):
    reason: str
    next_status: Literal["awaiting_player", "aborted"]


class NarrativeBeat(ContractModel):
    text: str


class ProvisionalDetail(ContractModel):
    id: EntityId | NpcId
    kind: str
    label: str
    scene_id: SceneId | None
    visibility: Visibility


class SuggestedAction(ContractModel):
    label: str


class EvidenceClaim(ContractModel):
    fact_id: FactId
    predicate: str
    value: FrozenJsonValue


class EvidenceRef(ContractModel):
    claim: EvidenceClaim


EvidenceFact: TypeAlias = FactRecord  # noqa: UP040

SemanticValidationIssueCode: TypeAlias = Literal[  # noqa: UP040
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
]


class ValidationIssue(ContractModel):
    path: str
    code: SemanticValidationIssueCode
    message: str


class SemanticResultV1(ContractModel):
    schema_version: Literal[1]
    rulings: Annotated[tuple[Ruling, ...], BeforeValidator(_copy_exact_sequence)]
    proposed_events: Annotated[tuple[ProposedEvent, ...], BeforeValidator(_copy_exact_sequence)]
    proposed_facts: Annotated[tuple[ProposedFact, ...], BeforeValidator(_copy_exact_sequence)]
    knowledge_changes: Annotated[tuple[KnowledgeChange, ...], BeforeValidator(_copy_exact_sequence)]
    visibility_changes: Annotated[
        tuple[VisibilityChange, ...], BeforeValidator(_copy_exact_sequence)
    ]
    clarification_request: ClarificationRequest | None
    rejection: Rejection | None
    narrative_plan: Annotated[tuple[NarrativeBeat, ...], BeforeValidator(_copy_exact_sequence)]
    narrative: str
    mentioned_details: Annotated[
        tuple[ProvisionalDetail, ...], BeforeValidator(_copy_exact_sequence)
    ]
    evidence: Annotated[tuple[EvidenceRef, ...], BeforeValidator(_copy_exact_sequence)]
    suggested_actions: Annotated[tuple[SuggestedAction, ...], BeforeValidator(_copy_exact_sequence)]


SEMANTIC_RESULT_ADAPTER: TypeAdapter[SemanticResultV1] = TypeAdapter(SemanticResultV1)


class SemanticValidationContext(ContractModel):
    known_entity_ids: frozenset[EntityId]
    known_npc_ids: frozenset[NpcId]
    known_fact_subject_ids: frozenset[EntityId]
    known_resource_ids: frozenset[ResourceId]
    known_character_ids: frozenset[CharacterId]
    known_location_ids: frozenset[LocationId]
    known_clock_ids: frozenset[ClockId]
    facts_by_id: Annotated[
        tuple[tuple[FactId, EvidenceFact], ...], BeforeValidator(_copy_exact_sequence)
    ]
    current_turn_status: _TurnStatus
    publication_visibility: PublicationVisibility

    def __init__(
        self,
        *,
        known_entity_ids: frozenset[EntityId],
        known_npc_ids: frozenset[NpcId],
        known_fact_subject_ids: frozenset[EntityId],
        known_resource_ids: frozenset[ResourceId],
        known_character_ids: frozenset[CharacterId],
        known_location_ids: frozenset[LocationId],
        known_clock_ids: frozenset[ClockId],
        facts_by_id: tuple[tuple[FactId, EvidenceFact], ...],
        current_turn_status: str,
        publication_visibility: PublicationVisibility,
    ) -> None:
        BaseModel.__init__(
            self,
            known_entity_ids=known_entity_ids,
            known_npc_ids=known_npc_ids,
            known_fact_subject_ids=known_fact_subject_ids,
            known_resource_ids=known_resource_ids,
            known_character_ids=known_character_ids,
            known_location_ids=known_location_ids,
            known_clock_ids=known_clock_ids,
            facts_by_id=facts_by_id,
            current_turn_status=current_turn_status,
            publication_visibility=publication_visibility,
        )


class AcceptedSemanticResult(ContractModel):
    type: Literal["accepted"]
    value: SemanticResultV1
    next_status: Literal["running", "awaiting_player", "aborted"]


class RejectedSemanticResult(ContractModel):
    type: Literal["rejected"]
    issues: Annotated[tuple[ValidationIssue, ...], BeforeValidator(_copy_exact_sequence)]
    next_status: Literal["awaiting_player", "aborted"]


SemanticValidationOutcome: TypeAlias = Annotated[  # noqa: UP040
    AcceptedSemanticResult | RejectedSemanticResult,
    Field(discriminator="type"),
]
SEMANTIC_OUTCOME_ADAPTER: TypeAdapter[SemanticValidationOutcome] = TypeAdapter(
    SemanticValidationOutcome
)

RawSemanticResultInput: TypeAlias = Mapping[str, object] | SemanticResultV1  # noqa: UP040

_SEMANTIC_FIELDS = frozenset(
    {
        "schema_version",
        "rulings",
        "proposed_events",
        "proposed_facts",
        "knowledge_changes",
        "visibility_changes",
        "clarification_request",
        "rejection",
        "narrative_plan",
        "narrative",
        "mentioned_details",
        "evidence",
        "suggested_actions",
    }
)

_ISSUE_PATHS: dict[SemanticValidationIssueCode, str] = {
    "schema": "result",
    "unknown_field": "result",
    "unknown_version": "schema_version",
    "invalid_result": "result",
    "invalid_event_proposal": "proposed_events",
    "invalid_fact_proposal": "proposed_facts",
    "invalid_proposal_ref": "rulings.proposed_effects",
    "unknown_entity": "context",
    "unknown_resource": "proposed_events",
    "unknown_character": "proposed_events",
    "unknown_location": "proposed_events",
    "unknown_clock": "proposed_events",
    "unknown_fact": "evidence",
    "invisible_fact": "evidence",
    "unrelated_visible_fact": "evidence",
    "claim_mismatch": "evidence",
    "duplicate_proposal": "result",
    "conflicting_control_fields": "result",
    "invalid_transition": "context",
}

_ISSUE_MESSAGES: dict[SemanticValidationIssueCode, str] = {
    "schema": "semantic result schema validation failed",
    "unknown_field": "semantic result contains an unknown field",
    "unknown_version": "semantic result version is unsupported",
    "invalid_result": "semantic result is invalid for the current context",
    "invalid_event_proposal": "semantic result contains an invalid event proposal",
    "invalid_fact_proposal": "semantic result contains an invalid fact proposal",
    "invalid_proposal_ref": "semantic result contains an invalid proposal reference",
    "unknown_entity": "semantic result references an unknown entity",
    "unknown_resource": "semantic result references an unknown resource",
    "unknown_character": "semantic result references an unknown character",
    "unknown_location": "semantic result references an unknown location",
    "unknown_clock": "semantic result references an unknown clock",
    "unknown_fact": "semantic result references an unknown fact",
    "invisible_fact": "semantic result references a fact outside publication visibility",
    "unrelated_visible_fact": "semantic result references another NPC's visible fact",
    "claim_mismatch": "semantic result evidence does not match the recorded fact",
    "duplicate_proposal": "semantic result contains a duplicate proposal or reference",
    "conflicting_control_fields": "semantic result control fields conflict with proposals",
    "invalid_transition": "semantic result context has an invalid turn transition",
}


def _append_issue(
    issues: list[ValidationIssue],
    code: SemanticValidationIssueCode,
) -> None:
    path = _ISSUE_PATHS[code]
    if any(issue.code == code and issue.path == path for issue in issues):
        return
    issues.append(
        ValidationIssue(
            path=path,
            code=code,
            message=_ISSUE_MESSAGES[code],
        )
    )


def _failure_status(context: object) -> Literal["awaiting_player", "aborted"]:
    status = getattr(context, "current_turn_status", None)
    if type(status) is str and status == "awaiting_player":
        return "awaiting_player"
    return "aborted"


def _rejected(
    context: object,
    issues: list[ValidationIssue] | tuple[ValidationIssue, ...],
) -> RejectedSemanticResult:
    return RejectedSemanticResult(
        type="rejected",
        issues=tuple(issues),
        next_status=_failure_status(context),
    )


def _schema_failure_codes(
    input_value: object, error: Exception
) -> tuple[SemanticValidationIssueCode, ...]:
    if isinstance(input_value, Mapping):
        try:
            keys = tuple(input_value.keys())
            version = input_value["schema_version"] if "schema_version" in keys else None
            if type(version) is int and version != 1:
                return ("unknown_version",)
            if any(type(key) is not str or key not in _SEMANTIC_FIELDS for key in keys):
                return ("unknown_field",)
        except AttributeError, KeyError, RuntimeError, TypeError, ValueError:
            return ("schema",)

    if isinstance(error, ValidationError):
        try:
            locations = tuple(detail.get("loc", ()) for detail in error.errors())
        except AttributeError, TypeError, ValueError:
            locations = ()
        first_fields = tuple(location[0] for location in locations if location)
        if "proposed_events" in first_fields:
            return ("invalid_event_proposal",)
        if "proposed_facts" in first_fields:
            return ("invalid_fact_proposal",)
        if "rulings" in first_fields:
            return ("invalid_proposal_ref",)
    return ("schema",)


def _validate_context(
    context: object,
) -> tuple[SemanticValidationContext | None, dict[str, FactRecord], tuple[ValidationIssue, ...]]:
    try:
        canonical_context = SemanticValidationContext.model_validate(context, strict=True)
    except AttributeError, TypeError, ValueError, ValidationError:
        issues: list[ValidationIssue] = []
        status = getattr(context, "current_turn_status", None)
        if type(status) is str and status not in {"running", "awaiting_player"}:
            _append_issue(issues, "invalid_transition")
        else:
            _append_issue(issues, "invalid_result")
        return None, {}, tuple(issues)

    issues = []
    if canonical_context.publication_visibility.startswith("npc:") and (
        canonical_context.publication_visibility not in canonical_context.known_npc_ids
    ):
        _append_issue(issues, "unknown_entity")

    facts: dict[str, FactRecord] = {}
    for fact_id, fact in canonical_context.facts_by_id:
        if fact_id in facts or fact_id != fact.fact_id:
            _append_issue(issues, "invalid_result")
            continue
        facts[fact_id] = fact

        if fact.subject_id is not None and (
            fact.subject_id not in canonical_context.known_entity_ids
            or fact.subject_id not in canonical_context.known_fact_subject_ids
        ):
            _append_issue(issues, "unknown_entity")
        if fact.holder.startswith("npc:") and fact.holder not in canonical_context.known_npc_ids:
            _append_issue(issues, "unknown_entity")
        if fact.visibility.startswith("npc:") and (
            fact.visibility not in canonical_context.known_npc_ids
        ):
            _append_issue(issues, "unknown_entity")

    return canonical_context, facts, tuple(issues)


def _validate_publication_visibility(
    visibility: str,
    publication_visibility: str,
    known_npc_ids: frozenset[NpcId],
    issues: list[ValidationIssue],
) -> None:
    if visibility.startswith("npc:") and visibility not in known_npc_ids:
        _append_issue(issues, "unknown_entity")
        return
    if visibility == publication_visibility:
        return
    if visibility.startswith("npc:") and publication_visibility.startswith("npc:"):
        _append_issue(issues, "unrelated_visible_fact")
    else:
        _append_issue(issues, "invisible_fact")


def _validate_entity(
    entity_id: str,
    context: SemanticValidationContext,
    issues: list[ValidationIssue],
) -> None:
    if entity_id not in context.known_entity_ids:
        _append_issue(issues, "unknown_entity")


def _validate_proposals(
    result: SemanticResultV1,
    context: SemanticValidationContext,
    facts: dict[str, FactRecord],
    issues: list[ValidationIssue],
) -> None:
    for proposal in result.proposed_events:
        if isinstance(proposal, ProposedResourceChanged):
            if proposal.payload.resource_id not in context.known_resource_ids:
                _append_issue(issues, "unknown_resource")
            _validate_entity(proposal.payload.entity_id, context, issues)
        elif isinstance(proposal, ProposedCharacterMoved):
            if proposal.payload.character_id not in context.known_character_ids:
                _append_issue(issues, "unknown_character")
            if proposal.payload.from_location_id is not None and (
                proposal.payload.from_location_id not in context.known_location_ids
            ):
                _append_issue(issues, "unknown_location")
            if proposal.payload.to_location_id not in context.known_location_ids:
                _append_issue(issues, "unknown_location")
        elif isinstance(proposal, ProposedClockAdvanced):
            if proposal.payload.clock_id not in context.known_clock_ids:
                _append_issue(issues, "unknown_clock")
        else:
            _append_issue(issues, "invalid_event_proposal")

    for fact_proposal in result.proposed_facts:
        if fact_proposal.subject_id is not None and (
            fact_proposal.subject_id not in context.known_entity_ids
            or fact_proposal.subject_id not in context.known_fact_subject_ids
        ):
            _append_issue(issues, "unknown_entity")
        if fact_proposal.holder.startswith("npc:") and (
            fact_proposal.holder not in context.known_npc_ids
        ):
            _append_issue(issues, "unknown_entity")
        _validate_publication_visibility(
            fact_proposal.visibility,
            context.publication_visibility,
            context.known_npc_ids,
            issues,
        )

    for index, proposal in enumerate(result.proposed_events):
        if any(proposal == previous for previous in result.proposed_events[:index]):
            _append_issue(issues, "duplicate_proposal")
    for index, fact_proposal in enumerate(result.proposed_facts):
        if any(fact_proposal == previous for previous in result.proposed_facts[:index]):
            _append_issue(issues, "duplicate_proposal")

    references: set[tuple[str, int]] = set()
    for ruling in result.rulings:
        for fact_id in ruling.facts_used:
            fact = facts.get(fact_id)
            if fact is None:
                _append_issue(issues, "unknown_fact")
            else:
                _validate_publication_visibility(
                    fact.visibility,
                    context.publication_visibility,
                    context.known_npc_ids,
                    issues,
                )
        for reference in ruling.proposed_effects:
            if isinstance(reference, EventProposalRef):
                reference_key = ("event", reference.index)
                if reference.index >= len(result.proposed_events):
                    _append_issue(issues, "invalid_proposal_ref")
            elif isinstance(reference, FactProposalRef):
                reference_key = ("fact", reference.index)
                if reference.index >= len(result.proposed_facts):
                    _append_issue(issues, "invalid_proposal_ref")
            else:
                _append_issue(issues, "invalid_proposal_ref")
                continue
            if reference_key in references:
                _append_issue(issues, "duplicate_proposal")
            references.add(reference_key)


def _validate_details(
    result: SemanticResultV1,
    context: SemanticValidationContext,
    issues: list[ValidationIssue],
) -> None:
    for detail in result.mentioned_details:
        if detail.kind == "npc" and not detail.id.startswith("npc:"):
            _append_issue(issues, "invalid_result")
        if detail.id.startswith("npc:"):
            if detail.id not in context.known_npc_ids:
                _append_issue(issues, "unknown_entity")
        elif detail.id not in context.known_entity_ids:
            _append_issue(issues, "unknown_entity")
        _validate_publication_visibility(
            detail.visibility,
            context.publication_visibility,
            context.known_npc_ids,
            issues,
        )


def _normalize_evidence_claim(input_value: object) -> EvidenceClaim:
    """Strictly revalidate one claim without exposing validation details."""

    if isinstance(input_value, EvidenceRef):
        input_value = input_value.claim
    return TypeAdapter(EvidenceClaim).validate_python(input_value, strict=True)


def _deep_equal_json(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, tuple) and isinstance(right, tuple):
        left_tuple: tuple[object, ...] = left
        right_tuple: tuple[object, ...] = right
        if len(left_tuple) != len(right_tuple):
            return False
        return all(_deep_equal_json(a, b) for a, b in zip(left_tuple, right_tuple, strict=True))
    return left == right


def _validate_evidence(
    result: SemanticResultV1,
    context: SemanticValidationContext,
    facts: dict[str, FactRecord],
    issues: list[ValidationIssue],
) -> None:
    for reference in result.evidence:
        try:
            claim = _normalize_evidence_claim(reference.claim)
        except AttributeError, TypeError, ValueError, ValidationError:
            _append_issue(issues, "schema")
            continue
        fact = facts.get(claim.fact_id)
        if fact is None:
            _append_issue(issues, "unknown_fact")
            continue
        _validate_publication_visibility(
            fact.visibility,
            context.publication_visibility,
            context.known_npc_ids,
            issues,
        )
        if fact.predicate != claim.predicate or not _deep_equal_json(fact.value, claim.value):
            _append_issue(issues, "claim_mismatch")


def _result_schema_issues(
    input_value: object,
    error: Exception,
) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    for code in _schema_failure_codes(input_value, error):
        _append_issue(issues, code)
    return tuple(issues)


def validate_semantic_result(
    input_value: RawSemanticResultInput,
    context: SemanticValidationContext,
) -> SemanticValidationOutcome:
    """Validate a raw Semantic Result and return only a sanitized outcome."""

    try:
        result = SEMANTIC_RESULT_ADAPTER.validate_python(input_value, strict=True)
    except (AttributeError, TypeError, ValueError, ValidationError, RecursionError) as error:
        return _rejected(context, _result_schema_issues(input_value, error))

    canonical_context, facts, context_issues = _validate_context(context)
    if canonical_context is None or context_issues:
        return _rejected(context, context_issues)

    issues: list[ValidationIssue] = []
    _validate_proposals(result, canonical_context, facts, issues)
    _validate_details(result, canonical_context, issues)
    _validate_evidence(result, canonical_context, facts, issues)

    has_clarification = result.clarification_request is not None
    has_rejection = result.rejection is not None
    has_proposals = bool(result.proposed_events or result.proposed_facts)
    if (has_clarification and has_rejection) or (
        has_proposals and (has_clarification or has_rejection)
    ):
        _append_issue(issues, "conflicting_control_fields")

    if issues:
        return _rejected(context, issues)

    if has_clarification:
        next_status: Literal["running", "awaiting_player", "aborted"] = "awaiting_player"
    elif has_rejection:
        assert result.rejection is not None
        next_status = result.rejection.next_status
    else:
        next_status = "running"

    try:
        return AcceptedSemanticResult(
            type="accepted",
            value=result,
            next_status=next_status,
        )
    except AttributeError, TypeError, ValueError, ValidationError, RecursionError:
        fallback_issues: list[ValidationIssue] = []
        _append_issue(fallback_issues, "invalid_result")
        return _rejected(context, fallback_issues)


validate_semantic_result.__annotations__ = {
    "input_value": RawSemanticResultInput,
    "context": SemanticValidationContext,
    "return": SemanticValidationOutcome,
}


__all__ = (
    "PROPOSAL_REF_ADAPTER",
    "PROPOSED_EVENT_ADAPTER",
    "SEMANTIC_OUTCOME_ADAPTER",
    "SEMANTIC_RESULT_ADAPTER",
    "AcceptedSemanticResult",
    "ClarificationRequest",
    "EventProposalRef",
    "EvidenceClaim",
    "EvidenceFact",
    "EvidenceRef",
    "FactProposalRef",
    "KnowledgeChange",
    "NarrativeBeat",
    "NonNegativeStrictInt",
    "PositiveStrictInt",
    "ProposalRef",
    "ProposedCharacterMoved",
    "ProposedClockAdvanced",
    "ProposedEvent",
    "ProposedFact",
    "ProposedResourceChanged",
    "ProvisionalDetail",
    "PublicationVisibility",
    "RawSemanticResultInput",
    "RejectedSemanticResult",
    "Rejection",
    "RollSpec",
    "Ruling",
    "SemanticResultV1",
    "SemanticValidationContext",
    "SemanticValidationIssueCode",
    "SemanticValidationOutcome",
    "SuggestedAction",
    "ValidationIssue",
    "VisibilityChange",
    "validate_semantic_result",
)
