# Semantic Result Specification

## 1. 位置づけ

本書は、Phase 0 / P0-04 で固定する Semantic Result 契約を記録する。正本となる実装は
src/neontof/contracts/semantic_result.py と src/neontof/contracts/transport.py、検証用の
契約テストは tests/contracts/test_semantic_result.py と tests/contracts/test_transport.py にある。
本書は承認済み docs/plans/phase-00-foundation.md §10 と、P0-03仕様
docs/specs/core-domain-and-events.md に従う。

本文は日本語で記述する。コード片、識別子、型名、field名、path、signature、commandは、契約上の表記を
変えずに英語で記載する。

## 2. 目的とNon-goal

### 2.1 目的

Semantic Result は、LLM の自由文をゲーム状態の入力にしないための、検証済み Structured Result の境界で
ある。raw mapping または既に検証された SemanticResultV1 を strict な Schemaへ通し、現在の Turn と公開先の
contextに照合したうえで、AcceptedSemanticResult または RejectedSemanticResult を返す。

この境界が固定するものは次の通りである。

- SemanticResultV1 の version、型、field、collection、discriminator。
- Accepted / Rejected の意味と next_status。
- Proposal、Evidence、stable ID、Visibility、NPC、duplicate の fail-closed な検証。
- Narrative と状態変更 Proposal の責務分離。
- validated AcceptedSemanticResult から Transport frame へ渡す順序と型。
- P0-03の DomainEvent、FactRecord、Projection、Transcript / Telemetry との境界。
- validation error、通常ログ、fixture、公開向け呼び出しへ秘密を渡さない境界。

Semantic Result 自体は Event でも State でもない。状態の権威は常に Event Log にあり、State と Canon は
Event から再構築される Projection である。

### 2.2 Non-goal

P0-04では次を実装・公開しない。

- Prompt、実Model call、実Provider、production Semantic Result pipeline。
- 自由文のparse、Narrativeからの状態推測、自然言語の矛盾検出。
- production Context Builder、production Visibility Filter。
- Event append、Event Store、Turn Engine、DB、SQLite、production materializer。
- 本番HTTP endpoint、本番SSE endpoint、HTTP resend、Browser UI。
- Provider / Hook / Plugin / Profile / Registry、二つ目の実装を前提にした将来用Interface。
- Semantic ResultからDiceを直接実行する経路。DiceはP0-03のseed導出と検証済みEventの責務である。
- Transcript / Telemetry をゲーム状態の入力やrollback対象へ混ぜる経路。

P0-04のproduction sourceは src/neontof/contracts/semantic_result.py と
src/neontof/contracts/transport.py に限る。Proposalから DomainEvent を組み立てる helper は、
テストの一対一検証に必要な test-only support としてだけ存在する。

## 3. 責務とデータの流れ

~~~text
RawSemanticResultInput
        |
        v
SEMANTIC_RESULT_ADAPTER.validate_python(..., strict=True)
        |
        v
validate_semantic_result(...)
        |
        +--> RejectedSemanticResult  -- Eventへ渡さない
        |
        +--> AcceptedSemanticResult
                  |
                  +--> validated proposed_events / proposed_facts
                  |       -- 将来のTurn EngineがEvent append前に扱う候補
                  |
                  +--> narrative / annotations -- Narrativeとしてだけ扱う
~~~

ここでいう「候補」は、Acceptedになったことだけで状態が変わるという意味ではない。P0-04には Event append
も Stateを直接更新する公開APIもない。後続の認可された経路が、検証済み Proposal を既存のDomain契約へ
変換し、Event Logへappendする責務を持つ。

## 4. Raw input と Schema

### 4.1 root input

実装pathは src/neontof/contracts/semantic_result.py である。rootの公開型は次の通りである。

~~~python
RawSemanticResultInput: TypeAlias = Mapping[str, object] | SemanticResultV1

SEMANTIC_RESULT_ADAPTER: TypeAdapter[SemanticResultV1] = TypeAdapter(SemanticResultV1)
~~~

validate_semantic_result は raw JSON text を受け取る関数ではない。JSONをdecodeしたmapping/object、または
SemanticResultV1 をroot入口とし、最初に次のstrict adapterへ渡す。

~~~python
SEMANTIC_RESULT_ADAPTER.validate_python(input_value, strict=True)
~~~

rootを FrozenJsonValue（tuple-of-pairs）へ先に変換してからadapterへ渡してはならない。JSON objectのkey、
arrayの順序、scalarの型をlosslessに保ったmapping/objectを渡す。rootのfrozen JSON表現は拒否され、
FrozenJsonValue は ProposedFact.value、EvidenceClaim.value、またはTransport内部のimmutable表現に限る。

### 4.2 共通型とpublic TypeAdapter

次の型とadapterは src/neontof/contracts/semantic_result.py のpublic contractである。

~~~python
NonNegativeStrictInt: TypeAlias = Annotated[int, Field(strict=True, ge=0)]
PositiveStrictInt: TypeAlias = Annotated[int, Field(strict=True, gt=0)]
PublicationVisibility: TypeAlias = Literal["player_visible"] | NpcId

ProposedEvent: TypeAlias = Annotated[
    ProposedResourceChanged | ProposedCharacterMoved | ProposedClockAdvanced,
    Field(discriminator="type"),
]
PROPOSED_EVENT_ADAPTER: TypeAdapter[ProposedEvent] = TypeAdapter(ProposedEvent)

ProposalRef: TypeAlias = Annotated[
    EventProposalRef | FactProposalRef,
    Field(discriminator="type"),
]
PROPOSAL_REF_ADAPTER: TypeAdapter[ProposalRef] = TypeAdapter(ProposalRef)

EvidenceFact: TypeAlias = FactRecord

SemanticValidationIssueCode: TypeAlias = Literal[
    "schema", "unknown_field", "unknown_version", "invalid_result",
    "invalid_event_proposal", "invalid_fact_proposal", "invalid_proposal_ref",
    "unknown_entity", "unknown_resource", "unknown_character", "unknown_location",
    "unknown_clock", "unknown_fact", "invisible_fact", "unrelated_visible_fact",
    "claim_mismatch", "duplicate_proposal", "conflicting_control_fields",
    "invalid_transition",
]

SemanticValidationOutcome: TypeAlias = Annotated[
    AcceptedSemanticResult | RejectedSemanticResult,
    Field(discriminator="type"),
]
SEMANTIC_OUTCOME_ADAPTER: TypeAdapter[SemanticValidationOutcome] = TypeAdapter(
    SemanticValidationOutcome
)
~~~

EvidenceFact は新しいFact modelではなく、P0-03の FactRecord そのものである。全てのContractModelは
strict=True、extra="forbid"、frozen=True、revalidate_instances="always" を継承する。公開collectionは
mutableな list / dict ではなくtupleまたはfrozensetである。

SemanticResultV1 と Ruling のsequence fieldにはprivateな _copy_exact_sequence が適用される。
組み込み list / tuple だけをfresh tupleへcopyし、tuple subclass、generator、set、任意Iterableは拒否する。
検証後に入力側collectionを変更しても、検証済みmodelやoutcomeへ伝播しない。

### 4.3 Proposed event とfact

~~~python
class ProposedResourceChanged(ContractModel):
    type: Literal["ResourceChanged"]
    payload: ResourceChangedPayload

class ProposedCharacterMoved(ContractModel):
    type: Literal["CharacterMoved"]
    payload: CharacterMovedPayload

class ProposedClockAdvanced(ContractModel):
    type: Literal["ClockAdvanced"]
    payload: ClockAdvancedPayload

class ProposedFact(ContractModel):
    kind: FactKind
    holder: FactHolder
    subject_id: EntityId | None
    predicate: str
    value: FrozenJsonValue
    visibility: Visibility
~~~

ProposedEvent の許可集合は ResourceChanged、CharacterMoved、ClockAdvanced の3種類だけである。
Lifecycle Event、DiceRolled、FactAsserted、FactSuperseded、TurnReverted などを
proposed_eventsへ入れることはできない。ProposedFact は後続のtest-only materializerで
FactAssertedPayloadへ写像できるが、P0-04自身はEventをappendしない。

### 4.4 nested model

src/neontof/contracts/semantic_result.py のnested modelとfieldは次の通りである。

| 型 | field / 型 |
|---|---|
| EventProposalRef | type: Literal["event"]、index: NonNegativeStrictInt |
| FactProposalRef | type: Literal["fact"]、index: NonNegativeStrictInt |
| RollSpec | formula: str |
| Ruling | rule_refs: tuple[str, ...]、facts_used: tuple[FactId, ...]、interpretation: str、roll_spec: RollSpec | None、proposed_effects: tuple[ProposalRef, ...]、is_house_ruling: bool |
| KnowledgeChange | note: str |
| VisibilityChange | note: str |
| ClarificationRequest | question: str |
| Rejection | reason: str、next_status: Literal["awaiting_player", "aborted"] |
| NarrativeBeat | text: str |
| ProvisionalDetail | id: EntityId | NpcId、kind: str、label: str、scene_id: SceneId | None、visibility: Visibility |
| SuggestedAction | label: str |
| EvidenceClaim | fact_id: FactId、predicate: str、value: FrozenJsonValue |
| EvidenceRef | claim: EvidenceClaim |
| ValidationIssue | path: str、code: SemanticValidationIssueCode、message: str |

note、question、reason、text、label、interpretation、narrative は状態変更の権威ではない。
自由文を後からparseしてEventやStateへ反映する経路は存在しない。

### 4.5 SemanticResultV1 fields

~~~python
class SemanticResultV1(ContractModel):
    schema_version: Literal[1]
    rulings: tuple[Ruling, ...]
    proposed_events: tuple[ProposedEvent, ...]
    proposed_facts: tuple[ProposedFact, ...]
    knowledge_changes: tuple[KnowledgeChange, ...]
    visibility_changes: tuple[VisibilityChange, ...]
    clarification_request: ClarificationRequest | None
    rejection: Rejection | None
    narrative_plan: tuple[NarrativeBeat, ...]
    narrative: str
    mentioned_details: tuple[ProvisionalDetail, ...]
    evidence: tuple[EvidenceRef, ...]
    suggested_actions: tuple[SuggestedAction, ...]
~~~

schema_version は 1 だけを受理する。未知field、未知version、nested modelの型違反、string number、
booleanをintegerとして扱う暗黙変換は拒否する。

### 4.6 root field authority

SemanticResultV1 のroot fieldは、状態変更の権威を同列に持たない。root fieldのauthorityと許可された
用途を次の表で固定する。

| field group | fields | authority / 許可された用途 |
|---|---|---|
| version metadata | `schema_version` | Semantic Resultの契約形式を示すversion metadataだけである。状態変更の権威でも、control fieldでも、narrativeの権威でもなく、Event / Stateへ直接入力しない。未知versionはSchema validationで拒否する。 |
| proposed events / facts | `proposed_events`、`proposed_facts` | 状態変更Proposalの唯一の宣言源。Schemaとcontextを通ったAccepted値だけを、後続の認可された経路がDomainEvent候補として扱える。AcceptedだけではStateは変わらず、Event Logへのappendが唯一の状態変更である。 |
| control fields | `clarification_request`、`rejection` | Turnの制御と`next_status`の決定だけに使う。validな`rejection`はAccepted outcomeに保持し、clarificationまたはProposalとの衝突は`conflicting_control_fields`でRejectedにする。EventやStateの直接入力ではない。 |
| evidence | `evidence`、`rulings.facts_used` | `facts_by_id`に既存するFactRecordを、公開先のVisibility、predicate、valueと照合する参照だけである。自由文からFactを作らず、新しいFactやStateの権威を持たない。 |
| narrative / annotation | `narrative`、`narrative_plan`、`mentioned_details`、`suggested_actions`、`knowledge_changes`、`visibility_changes`、`rulings` | 説明、注釈、公開文、候補表示だけに使う。Proposalを追加せず、NarrativeやannotationからEventを生成しない。`rulings.facts_used`のEvidence照合と`rulings.proposed_effects`のProposal参照は、上の境界に従う。 |
| Transcript / Telemetry external | SemanticResult rootのfieldではない`TranscriptEntry`、`TelemetryEntry` | Game State / Canon / DomainEventの入力に含めず、ゲーム状態transactionの外へappendする。Turn失敗時も記録を消さず、費用をrollbackしない。 |

この表の「authority」は、値を受理することではなく、後続処理で何を決定できるかを意味する。Event Logが
ゲーム状態の唯一の権威であり、Semantic Result、Narrative、Transcript、TelemetryはいずれもStateを直接
更新しない。

### 4.7 validation order と context invalid short-circuit

`validate_semantic_result` の検証順は次で固定する。

1. `SEMANTIC_RESULT_ADAPTER.validate_python(input_value, strict=True)`でroot Schemaを検証する。失敗したら
   sanitizedなIssueだけを持つ`RejectedSemanticResult`を直ちに返し、context以下の検証を行わない。
2. Schema-validなrootに対して`SemanticValidationContext.model_validate(context, strict=True)`を実行し、
   `facts_by_id`のkey / `FactRecord.fact_id`一致、ID対応集合、公開先NPCなどcontext自体を検証する。
3. contextの再検証が失敗した、またはcontext固有のIssueが1件でもある場合は、Proposal、Detail、Evidence、
   control衝突の検証へ進まず、`RejectedSemanticResult`を直ちに返す。Issueは固定code / path / messageへ
   sanitizedされ、`next_status`は元contextのstatusが正確に`"awaiting_player"`なら`"awaiting_player"`、
   それ以外なら`"aborted"`とする。
4. canonical contextとcanonicalized `facts_by_id`を使い、Proposalの対応集合、Visibility、duplicate、
   ProposalRef、`rulings.facts_used`を検証する。
5. `mentioned_details`のEntity / NPC / Visibilityを検証し、続けて`evidence`を既存FactRecordへ照合する。
6. `clarification_request`、`rejection`、Proposalの同居を検証する。IssueがあればRejected、Issueがなければ
   controlに従う`next_status`を計算してAcceptedにする。

contextが不正なときに後段のProposalやEvidenceを部分的に検証・filterしてはならない。この短絡は、壊れた
contextを前提にしたAccepted outcomeを作らず、失敗時にもsanitizedなRejected outcomeだけを返すための契約である。

## 5. Validation outcome とdecision table

### 5.1 public signature

~~~python
# src/neontof/contracts/semantic_result.py
def validate_semantic_result(
    input_value: RawSemanticResultInput,
    context: SemanticValidationContext,
) -> SemanticValidationOutcome: ...

# private helper。public exportしない。
def _normalize_evidence_claim(input_value: object) -> EvidenceClaim: ...
~~~

このsignatureは実装でruntime annotationにも設定され、input_value、context、returnの3型を正確に公開
する。private _normalize_evidence_claim はpublic exportではない。

### 5.2 SemanticValidationContext

~~~python
class SemanticValidationContext(ContractModel):
    known_entity_ids: frozenset[EntityId]
    known_npc_ids: frozenset[NpcId]
    known_fact_subject_ids: frozenset[EntityId]
    known_resource_ids: frozenset[ResourceId]
    known_character_ids: frozenset[CharacterId]
    known_location_ids: frozenset[LocationId]
    known_clock_ids: frozenset[ClockId]
    facts_by_id: tuple[tuple[FactId, EvidenceFact], ...]
    current_turn_status: _TurnStatus
    publication_visibility: PublicationVisibility

    # 明示的なpublic __init__ 引数の注釈
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
        current_turn_status: Literal["running", "awaiting_player"],
        publication_visibility: PublicationVisibility,
    ) -> None: ...
~~~

facts_by_id は同じkeyを二度持てず、各keyと FactRecord.fact_id が完全一致しなければcontextを拒否する。
各ID集合はProposalの対応集合として使い、Proposalのgrammarだけで受理しない。

実装のclass field annotationはprivate alias `_TurnStatus`だが、`SemanticValidationContext.__init__` の
`current_turn_status`引数は上記の`Literal["running", "awaiting_player"]`である。test-onlyの
`FixtureEventContext.sequence_start`は`PositiveStrictInt`（strict intかつ`gt=0`）であり、0、負数、bool、
文字列数値を受理しない。

### 5.3 outcome model とstatus

~~~python
class AcceptedSemanticResult(ContractModel):
    type: Literal["accepted"]
    value: SemanticResultV1
    next_status: Literal["running", "awaiting_player", "aborted"]

class RejectedSemanticResult(ContractModel):
    type: Literal["rejected"]
    issues: tuple[ValidationIssue, ...]
    next_status: Literal["awaiting_player", "aborted"]
~~~

AcceptedSemanticResult はSchema-validでcontextにも整合する結果である。validな
SemanticResultV1.rejection は入力契約違反ではなく、Acceptedの value に保持するcontrolであり、
next_status は Rejection.next_status になる。

RejectedSemanticResult はSchema、context、Proposal、Evidence、Visibility、duplicate、control衝突などの
入力契約違反だけを表す。issues はsanitizedな ValidationIssue のtupleだけを持ち、raw resultやraw入力を
保持しない。入力契約違反時の next_status は、current_turn_status="running" なら "aborted"、
current_turn_status="awaiting_player" なら "awaiting_player" である。

### 5.4 16行decision table

proposals は proposed_events または proposed_facts が1件以上であることを表す。

| current_turn_status | clarification_request | rejection | proposals | 結果 |
|---|---:|---:|---:|---|
| running | なし | なし | なし | AcceptedSemanticResult, next_status="running" |
| running | なし | なし | あり | AcceptedSemanticResult, next_status="running"（Proposalを保持） |
| running | あり | なし | なし | AcceptedSemanticResult, next_status="awaiting_player" |
| running | なし | あり | なし | AcceptedSemanticResult, next_status=rejection.next_status |
| running | あり | なし | あり | RejectedSemanticResult, conflicting_control_fields, next_status="aborted" |
| running | なし | あり | あり | RejectedSemanticResult, conflicting_control_fields, next_status="aborted" |
| running | あり | あり | なし | RejectedSemanticResult, conflicting_control_fields, next_status="aborted" |
| running | あり | あり | あり | RejectedSemanticResult, conflicting_control_fields, next_status="aborted" |
| awaiting_player | なし | なし | なし | AcceptedSemanticResult, next_status="running" |
| awaiting_player | なし | なし | あり | AcceptedSemanticResult, next_status="running"（Proposalを保持） |
| awaiting_player | あり | なし | なし | AcceptedSemanticResult, next_status="awaiting_player" |
| awaiting_player | なし | あり | なし | AcceptedSemanticResult, next_status=rejection.next_status |
| awaiting_player | あり | なし | あり | RejectedSemanticResult, conflicting_control_fields, next_status="awaiting_player" |
| awaiting_player | なし | あり | あり | RejectedSemanticResult, conflicting_control_fields, next_status="awaiting_player" |
| awaiting_player | あり | あり | なし | RejectedSemanticResult, conflicting_control_fields, next_status="awaiting_player" |
| awaiting_player | あり | あり | あり | RejectedSemanticResult, conflicting_control_fields, next_status="awaiting_player" |

clarificationとvalid rejectionの同時指定、またはcontrolとProposalの同居は、Proposalを黙って捨てずに
conflicting_control_fields で拒否する。

### 5.5 validation failure の扱い

validation failure はcontrolの有無にかかわらず RejectedSemanticResult になる。schema、Proposal grammar、
対応集合、Evidence、duplicate、contextの失敗を valid rejection と混同しない。root/nested adapter、
_normalize_evidence_claim、context再検証で発生したPydantic ValidationError は境界内で捕捉し、固定された
ValidationIssueだけへ変換する。

## 6. Visibility、NPC、facts_by_id、Evidence、duplicate

### 6.1 公開先とVisibility

P0-03の Visibility は "gm_only" | "player_visible" | NpcId である。
PublicationVisibility は "player_visible" または既知の NpcId である。可視性は推測やfilterではなく
完全一致で判定する。

| publication_visibility | 受理する Visibility | 拒否する例 |
|---|---|---|
| player_visible | player_visible のみ | gm_only、任意の npc:X は invisible_fact |
| npc:X | npc:X のみ | gm_only / player_visible は invisible_fact、npc:Y（Y != X）は unrelated_visible_fact |

gm_only はどの公開先にも公開しない。npc:X のXが known_npc_ids に無ければ、公開先自体を含めて
unknown_entity として拒否する。対象外NPCの情報を別NPCへ黙ってfilterしてはならない。

### 6.2 NPCとIDの対応集合

known_npc_ids は次の全てに適用する。

- PublicationVisibility と Visibility の NpcId。
- ProposedFact.holder のNPC。
- FactRecord.holder / FactRecord.visibility のNPC。
- ProvisionalDetail のNPC対象。

ProvisionalDetail.kind == "npc" なら id は npc: grammarでなければならない。NPC grammarを満たすIDは
known lookupを通し、未登録のNPCは受理しない。NPCではない EntityId は known_entity_ids へ照合する。

### 6.3 facts_by_id とEvidence

facts_by_id の各tupleは (FactId, FactRecord) である。keyの一意性、key == FactRecord.fact_id、
FactRecordのsubject / holder / visibilityの対応集合を確認する。Evidenceのlookupは、次を全て満たす場合だけ
成功する。

1. EvidenceClaim.fact_id が facts_by_id のkeyとして存在する。
2. keyと FactRecord.fact_id が一致している。
3. FactRecord.visibility が publication_visibility と完全一致する。
4. EvidenceClaim.predicate と FactRecord.predicate が一致する。
5. EvidenceClaim.value と FactRecord.value がdeep equalである。

deep equalityはleafの型も比較するため、True と 1 は同じ値ではない。Evidenceは過去の事実を自由文から
推測せず、実在する可視Fact IDと記録値だけを参照する。ruling.facts_used も同じFact lookupとVisibility
検証を受ける。

### 6.4 duplicateとProposalRef

同一の ProposedEvent、ProposedFact、または同じ (type, index) の ProposalRef は
duplicate_proposal で拒否する。範囲外の EventProposalRef / FactProposalRef は
invalid_proposal_ref で拒否する。duplicateを取り除いて処理を続けたり、重複Eventを黙って一つにしたり
しない。

## 7. Issue、redaction、秘密の境界

### 7.1 Issue codeと公開path

ValidationIssue のcodeは有限集合であり、pathも次の固定値だけを使う。raw field名、raw value、URL、
Pydanticのraw error reprをpath/messageへ流さない。

| code | 固定path |
|---|---|
| schema | result |
| unknown_field | result |
| unknown_version | schema_version |
| invalid_result | result |
| invalid_event_proposal | proposed_events |
| invalid_fact_proposal | proposed_facts |
| invalid_proposal_ref | rulings.proposed_effects |
| unknown_entity | context |
| unknown_resource | proposed_events |
| unknown_character | proposed_events |
| unknown_location | proposed_events |
| unknown_clock | proposed_events |
| unknown_fact | evidence |
| invisible_fact | evidence |
| unrelated_visible_fact | evidence |
| claim_mismatch | evidence |
| duplicate_proposal | result |
| conflicting_control_fields | result |
| invalid_transition | context |

### 7.2 redactionとAPI key

validation boundaryは raw inputやexceptionを保存しない。Outcome、Issue、通常ログ、fixture、Transportへの
未検証raw値に、P0-04が管理する次の情報を含めない。

- raw input、未検証のfield/value、raw path、URL、Pydantic errorのrepr。
- secret、API key、credential、bearer token、private key。
- TurnPostRequest.input_text のraw値（request boundaryの外側）。

_normalize_evidence_claim は validate_semantic_result のEvidence loopからだけ呼ぶprivate helperで、
その ValidationError を外へ漏らさない。P0-04は公開向けmodel callを実行せず、API keyを受け取るfieldや
引数を持たない。Transportは検証済みAccepted値だけを送るが、任意のaccepted narrative文字列を自動redact
する契約ではないため、上流は公開先に不可視な情報やAPI keyをSemantic Resultへ入れてはならない。テストfixture
や通常ログへ秘密を記録しない。

## 8. NarrativeとEvent権威の分離

narrative、narrative_plan、mentioned_details、suggested_actions、knowledge_changes、
visibility_changes、Ruling は、Semantic Result内の説明・注釈・公開文のための値であり、Eventの代わりに
ならない。

状態変更候補として宣言できるのは proposed_events と proposed_facts だけである。ただしそれらもEvent
Logへappendされるまでは状態変更ではない。Narrativeを変更してもProposalが同じなら、test-only materializer
の出力は変わらない。Narrative-only / annotation-only result は生成Event 0件である。

P0-03が定める通り、Event Logはゲーム状態の唯一の権威であり、State / CanonはEvent列から再構築できる
Projectionである。Semantic ResultやNarrativeをStateへ直接書き込む公開API、Narrativeをparseする経路、
未検証のProposalをEventへ渡す経路を作らない。

## 9. test-only materializerの境界

### 9.1 所有pathとsignature

materializerはproduction codeではない。実装pathは次のtest-only supportに限定する。

~~~text
tests/contracts/support/materialize_proposed_events.py
~~~

~~~python
class FixtureEventContext(ContractModel):
    campaign: CampaignId
    session: SessionId
    scene: SceneId
    turn: TurnId
    sequence_start: PositiveStrictInt
    occurred_at: OccurredAt
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility

def materialize_semantic_result_for_test(
    result: AcceptedSemanticResult,
    context: FixtureEventContext,
) -> tuple[DomainEvent, ...]: ...
~~~

production src/neontof/contracts/semantic_result.py から FixtureEventContext や
materialize_semantic_result_for_test をexportしない。materializerはRejected outcome、raw mapping、
Narrative、注釈を受けて状態を変更する責務を持たない。AcceptedSemanticResult 以外を渡すと拒否する。

### 9.2 test oracleの決定性

materializerは、source orderで proposed_events を先に、proposed_facts を後に連結する。0-based
ordinal を使い、各Eventの sequence は context.sequence_start + ordinal、event_id は
event:fixture-{sequence} とする。外部時刻、random、UUIDは使わず、同じ入力から同じtupleを返す。

| Semantic proposal | DomainEvent | visibility |
|---|---|---|
| ProposedResourceChanged | ResourceChanged（payloadをfield-for-fieldで渡す） | context.visibility |
| ProposedCharacterMoved | CharacterMoved（payloadをfield-for-fieldで渡す） | context.visibility |
| ProposedClockAdvanced | ClockAdvanced（payloadをfield-for-fieldで渡す） | context.visibility |
| ProposedFact | FactAsserted（FactAssertedPayloadへ1件ずつ写像） | ProposedFact.visibility |

全Eventの event_version=1 とenvelope contextは FixtureEventContext から供給する。Fact IDは独自生成せず、
P0-03の rebuild_projection が既存の derive_fact_id(event_id, 0) を使う経路へ通す。連結配列のordinalを
Fact ID導出へ渡さない。複数Factは異なる event_id を持つため、ordinal 0でもFact IDは一意になる。

テストでは生成EventをP0-03の parser / rebuild_projection へ通し、FactRecord.fact_id と
derive_fact_id(event_id, 0) の一致、facts_by_idへの再投入、対応するEvidenceのAcceptedを確認する。
これはEvent Storeやproduction State更新の代替ではない。

## 10. Transport契約

### 10.1 型とpublic TypeAdapter

実装pathは src/neontof/contracts/transport.py である。

~~~python
class TurnPostRequest(ContractModel):
    type: Literal["turn_post"]
    turn_request_id: TurnRequestId
    input_text: str

JsonValue: TypeAlias = FrozenJsonValue

class SemanticResultFrame(ContractModel):
    type: Literal["semantic_result"]
    data: JsonValue

class NarrativeFrame(ContractModel):
    type: Literal["narrative"]
    data: str

class DoneFrame(ContractModel):
    type: Literal["done"]
    data: Literal["running", "awaiting_player", "aborted"]

TransportFrame: TypeAlias = Annotated[
    SemanticResultFrame | NarrativeFrame | DoneFrame,
    Field(discriminator="type"),
]
TRANSPORT_FRAME_ADAPTER: TypeAdapter[TransportFrame] = TypeAdapter(TransportFrame)
~~~

TurnPostRequest、各Frame modelはstrict / forbid / frozen / revalidateである。input_text はPOST request
境界で一時的に存在する値で、Semantic Result、Issue、Event、Frame、通常ログへrawのまま渡さない。

### 10.2 builderのsignatureと順序

~~~python
def build_buffered_response(
    result: AcceptedSemanticResult,
) -> tuple[TransportFrame, ...]: ...

def build_sse_frames(
    result: AcceptedSemanticResult,
) -> tuple[TransportFrame, ...]: ...
~~~

両builderは AcceptedSemanticResult だけを受ける。raw SemanticResultV1、
RejectedSemanticResult、検証前のNarrativeは受け付けず、runtimeでもaccepted modelをstrict再検証する。

両builderの出力は同じpureな3 frame sequenceである。

| 順序 | frame | data |
|---:|---|---|
| 1 | SemanticResultFrame(type="semantic_result") | AcceptedSemanticResult.value.model_dump(mode="python") を FrozenJsonValue として検証した値 |
| 2 | NarrativeFrame(type="narrative") | AcceptedSemanticResult.value.narrative |
| 3 | DoneFrame(type="done") | AcceptedSemanticResult.next_status |

SemanticResultFrame.data の JsonValue = FrozenJsonValue はtransport内部のimmutable表現であり、本番SSEや
HTTP endpointの実装・wire endpointを意味しない。build_sse_frames と build_buffered_response のframe列は
順序、data、nested frozen valueまで一致する。検証前のNarrativeや input_text は送信されない。

## 11. Transcript / Telemetryとの境界

P0-03の TranscriptEntry と TelemetryEntry は DomainEvent unionとProjection入力の外側にある別型で
ある。Semantic Result、Event、ProjectionへTranscript / Telemetryを埋め込まない。

Transcript / Telemetry はゲーム状態のtransaction外へappendし、Turn失敗時も記録を消さない。費用もTurn
rollbackで戻さない。P0-04はそのStoreや実記録を作らない。失敗したvalidationのIssueを返すことと、失敗Turnの
Transcript / Telemetryを保持することは別の責務であり、一方を他方へ変換しない。

## 12. 不変条件

P0-04の実装・テスト・後続実装は、少なくとも次を同時に満たす。

1. Event Logがゲーム状態の唯一の権威であり、Semantic Result / NarrativeからStateを直接更新しない。
2. State / CanonはEventから再構築され、Semantic ResultはEventではない。
3. 自由文をparseして状態やEventへ入れない。Structured ResultをSchemaとcontext検証した後だけProposalを扱う。
4. AcceptedSemanticResult だけがTransport builderとtest-only materializerの入力になれる。
5. RejectedSemanticResult は入力契約違反を表し、raw input、raw value、Pydantic error、secretを保持しない。
6. proposed_events の許可集合は3種類、proposed_facts はFact proposalだけであり、lifecycle EventやDiceを宣言しない。
7. Visibilityは完全一致で、不可視Fact、別NPCのFact、未知NPCをfilterして通さない。
8. facts_by_id のkeyは一意で、key == FactRecord.fact_id。Evidenceは存在・可視性・predicate・valueを照合する。
9. duplicate Proposal / ProposalRefを黙って削除せず、duplicate_proposal で拒否する。
10. NarrativeとannotationだけからEventを生成しない。Narrative変更はProposalのmaterialized outputを変えない。
11. test-only materializerは一対一・決定論的で、Fact IDは derive_fact_id(event_id, 0) に委譲する。
12. Transportは semantic_result → narrative → done の順序を守り、done.data == next_status とする。
13. Transcript / TelemetryはDomainEvent・Projection・Event transactionの外側に置く。
14. P0-04は公開向け呼び出しへAPI keyや不可視情報を渡す引数を持たず、fixture / 通常ログへ秘密を記録しない。
    Transportへ渡すAccepted値も、上流で公開可能性を満たすものだけにする。
15. Diceの判定はglobal randomや自由なseedではなく、P0-03のseed導出経由で扱う。

## 13. 検証

P0-04のcanonical commandは`docs/plans/phase-00-foundation.md` §10.5を参照する。P0-03 regressionの
canonical commandは同計画 §9.5を参照する。以下では、P0-04の既存レビュー時REDと、source着地後の現行
Green / quality evidenceを混同しないように分けて記録する。Python executableは計画の手順でrepository
rootから`.venv/Scripts/python.exe`へ解決し、実行環境固有の絶対pathは仕様書へ埋め込まない。

### 13.1 Test First RED（c51ab55をGitから再現した履歴証拠）

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$pythonExe = Join-Path $repositoryRoot '.venv/Scripts/python.exe'
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempRoot = [System.IO.Path]::GetFullPath((Join-Path $tempBase ('neontof-p0-04-red-' + [guid]::NewGuid().ToString('N'))))
if (-not $tempRoot.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'temporary path escaped the temp directory.' }
$archivePath = Join-Path $tempRoot 'c51ab55.tar'
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    & git archive --format=tar --output=$archivePath c51ab55
    $archiveExit = $LASTEXITCODE
    if ($archiveExit -eq 0) {
        & tar -xf $archivePath -C $tempRoot
        $extractExit = $LASTEXITCODE
    }
    if ($archiveExit -ne 0 -or $extractExit -ne 0) { throw 'Git archive extraction failed.' }
    Push-Location $tempRoot
    try {
        & $pythonExe -m pytest tests/contracts/test_semantic_result.py tests/contracts/test_transport.py -q
        $focusedExit = $LASTEXITCODE
        & $pythonExe -m pytest tests/contracts/test_semantic_result.py tests/contracts/test_transport.py --collect-only -q
        $collectExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    if ([System.IO.Directory]::Exists($tempRoot)) { [System.IO.Directory]::Delete($tempRoot, $true) }
    $tempExistsAfterCleanup = [System.IO.Directory]::Exists($tempRoot)
}
'archive_exit=' + $archiveExit
'extract_exit=' + $extractExit
'focused_exit=' + $focusedExit
'collect_exit=' + $collectExit
'temp_exists_after_cleanup=' + $tempExistsAfterCleanup
~~~

これはproduction sourceのSemantic Result / Transport実装が未着地のtest-first commit `c51ab55`を
Gitからarchiveして一時展開し、repositoryの現行sourceを混ぜずに正規venvから実行した履歴証拠である。
`c51ab55`はこのtest-first差分の親として固定し、`collect-only`は同じtest pathに対して別途実行した。

~~~text
archive_exit=0
extract_exit=0
focused_exit=1
178 failed, 1 passed in 4.97s
collect_exit=0
179 tests collected in 0.13s
exception_types=ModuleNotFoundError
syntax_error_lines=0
collection_error_lines=0
temp_exists_after_cleanup=False
~~~

このREDはproduction source着地前のcontracts module/export不在による期待されたREDであり、Greenの証拠
ではない。例外は`ModuleNotFoundError`だけで、`SyntaxError`とcollection errorはない。archiveとextractが
成功し、一時展開先はcleanup後に存在しない。source着地後のfocused `179 passed`は13.2節に分けて記録し、
REDをGreenへ読み替えない。

### 13.2 現行Greenとcanonical quality evidence

~~~powershell
python -m pytest tests/contracts/test_semantic_result.py tests/contracts/test_transport.py -q
python -m mypy --strict src tests --exclude tests/typecheck_fixtures
~~~

現行の安定した実測結果は次の通りである。P0-03 regressionは§9.5のcanonical commandを別に実行する。

~~~text
focused: 179 passed
mypy --strict src tests --exclude tests/typecheck_fixtures:
Success: no issues found in 38 source files
P0-03 regression: 86 passed, 1 warning
~~~

本節は現行の安定結果だけを記録し、過去の失敗一覧や実行環境固有のpathを含めない。
format、lint、compileallを含む全体Gateのcommandと証拠は計画書のcanonical blockを正本とする。

### 13.3 必須語・禁止語とtest-only export

P0-04計画 §10.5 の required term検索とforbidden pattern検索を実行する。required termは
AcceptedSemanticResult、RejectedSemanticResult、SemanticValidationContext、known_npc_ids、
facts_by_id、conflicting_control_fields、_normalize_evidence_claim、proposed_events、
proposed_facts、materialize_semantic_result_for_test、sequence_start、event:fixture-、
FactAsserted、derive_fact_id(event_id, 0)、rebuild_projection、FactRecord.fact_id、
player_visible、gm_only、npc:、clarification_request、rejection である。禁止patternは
private helperのpublic normalizer名、Semantic Result rootへのFrozenJsonValue直接指定、
non-strict validation flag、publication visibility専用module名に相当する4種類である。

~~~powershell
$requiredTerms = @(
    'AcceptedSemanticResult', 'RejectedSemanticResult', 'SemanticValidationContext',
    'known_npc_ids', 'facts_by_id', 'conflicting_control_fields', '_normalize_evidence_claim',
    'proposed_events', 'proposed_facts', 'materialize_semantic_result_for_test',
    'sequence_start', 'event:fixture-', 'FactAsserted', 'derive_fact_id(event_id, 0)',
    'rebuild_projection', 'FactRecord.fact_id', 'player_visible', 'gm_only', 'npc:',
    'clarification_request', 'rejection'
)
$scanPaths = @(
    'docs/specs/semantic-result.md',
    'src/neontof/contracts',
    'tests/contracts/support'
)
$missing = @()
$requiredToolFailures = @()
foreach ($term in $requiredTerms) {
    $termHits = @(rg -n --fixed-strings -- $term $scanPaths)
    $termExit = $LASTEXITCODE
    if ($termExit -eq 0) { continue }
    if ($termExit -eq 1) { $missing += $term; continue }
    $requiredToolFailures += $term
}
if ($missing.Count -ne 0) {
    throw "required term missing (rg exit 1): $($missing -join ', ')"
}
if ($requiredToolFailures.Count -ne 0) {
    throw "required rg tool failure (exit >=2): $($requiredToolFailures -join ', ')"
}
$forbiddenPatterns = @(
    ('def ' + 'normalize_evidence_claim('),
    ('payload: ' + 'FrozenJsonValue'),
    ('strict' + '=False'),
    ('publication_' + 'visibility.py')
)
$forbiddenHits = 0
$forbiddenToolFailures = @()
foreach ($pattern in $forbiddenPatterns) {
    $patternMatches = @(rg -n --fixed-strings -- $pattern src/neontof tests docs/specs/semantic-result.md)
    $patternExit = $LASTEXITCODE
    if ($patternExit -eq 1) { continue }
    if ($patternExit -eq 0) { $patternMatches; $forbiddenHits++; continue }
    $forbiddenToolFailures += $pattern
}
if ($forbiddenHits -ne 0) {
    throw "forbidden rg hit (exit 0): $forbiddenHits pattern(s)."
}
if ($forbiddenToolFailures.Count -ne 0) {
    throw "forbidden rg tool failure (exit >=2): $($forbiddenToolFailures -join ', ')"
}
$productionMaterializerMatches = @(rg -n --fixed-strings -- 'materialize_semantic_result_for_test' src/neontof/contracts/semantic_result.py)
$productionMaterializerExit = $LASTEXITCODE
if ($productionMaterializerExit -eq 0) { $productionMaterializerMatches; throw 'production materializer export hit.' }
if ($productionMaterializerExit -ne 1) { throw "production materializer scan tool failure: exit $productionMaterializerExit" }
$productionContextMatches = @(rg -n --fixed-strings -- 'FixtureEventContext' src/neontof/contracts/semantic_result.py)
$productionContextExit = $LASTEXITCODE
if ($productionContextExit -eq 0) { $productionContextMatches; throw 'production fixture context export hit.' }
if ($productionContextExit -ne 1) { throw "production fixture context scan tool failure: exit $productionContextExit" }
"required_term_count=$($requiredTerms.Count)"
"required_term_missing=$($missing.Count)"
"required_scan_tool_failures=$($requiredToolFailures.Count)"
"forbidden_pattern_count=$($forbiddenPatterns.Count)"
"forbidden_hit_count=$forbiddenHits"
"forbidden_scan_tool_failures=$($forbiddenToolFailures.Count)"
"production_materializer_hits=0"
"production_fixture_context_hits=0"
~~~

実測結果:

~~~text
required_term_count=21
required_term_missing=0
required_scan_tool_failures=0
forbidden_pattern_count=4
forbidden_hit_count=0
forbidden_scan_tool_failures=0
production_materializer_hits=0
production_fixture_context_hits=0
~~~

判定はfail-closedである。required termでは`rg` exit 0をfound、exit 1をmissing、exit 2以上をtool
failureとして扱う。forbidden patternではexit 1をzero hit、exit 0をhitによるFAIL、exit 2以上をtool
failureとして扱う。したがって、`$LASTEXITCODE`の未確認やtool errorをzero hitへ読み替えない。

### 13.4 文書形式とdiff

~~~powershell
$path = 'docs/specs/semantic-result.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
$text = [System.IO.File]::ReadAllText($path)
$crlfCount = ([regex]::Matches($text, [string]([char]13) + [string]([char]10))).Count
$fenceCount = ([regex]::Matches($text, '(?m)^~~~')).Count
$lineNumber = 0
$trailingWhitespaceLines = @(
    Get-Content -LiteralPath $path | ForEach-Object {
        $lineNumber++
        if ($_ -match '[ \t]+$') { $lineNumber }
    }
)
"utf8_bom=$hasBom"
"crlf_count=$crlfCount"
"markdown_fence_count=$fenceCount"
"trailing_whitespace_lines=$($trailingWhitespaceLines.Count)"
if ($hasBom -or $crlfCount -ne 0 -or $fenceCount % 2 -ne 0 -or $trailingWhitespaceLines.Count -ne 0) { exit 1 }

git diff --check
git diff --numstat
git diff --ignore-cr-at-eol --numstat
~~~

実測結果:

~~~text
utf8_bom=False
crlf_count=0
markdown_fence_count=42
trailing_whitespace_lines=0
git diff --check: exit=0（出力なし）
git diff --numstat と git diff --ignore-cr-at-eol --numstat: tracked diffの出力一致
~~~

git diff --check はwarning/errorなしで終了した。新規未追跡の本書は通常のgit diff numstatには含まれないため、
本書自身は上のbyte/fence/trailing-whitespace検査で確認し、numstatの2種類はtracked diffについて突き合わせる。

## 14. Phase 1へ先送りする事項

P0-04で契約だけを固定し、次をPhase 1以降へ送る。

- Context Builderとproduction Visibility Filterによる公開contextの組み立て。
- Model Gateway、実Provider、retry、budget、production Semantic Result pipeline。
- Turn EngineによるAccepted ProposalのDomainEvent化、Event append、atomic transaction。
- HTTP POST endpoint、SSE配信、buffered fallbackの実transport、resendとidempotency。
- Transcript / Telemetry Store、Secret Store、SQLite、Browser Client。
- production materializer、二つ目のProvider / Ruleset / Scenario、Plugin / Hook / Profile。
- Dice実行、seed記録、ルール判定と、Semantic Result以外のDomain Event変換。

これらを進める際も、本書のaccepted/rejected境界、Narrative非権威、Visibility完全一致、Event Log単一権威、
Transcript / Telemetry外部、API keyなしの不変条件を変更してはならない。変更が必要なら、実装より先に上位
Planと必要なADRを更新する。

## 15. ADR・Plan・P0-03との関係

- docs/plans/phase-00-foundation.md §10 は、P0-04のGoal、Non-goal、許可path、型とsignature、decision table、
  test-only materializer、Transport、focused gate、commit boundaryを承認済みの実行計画として定める。本書はその
  契約を読み手向けに記録する。計画にないproduction endpointやprovider抽象化を追加しない。
- docs/specs/core-domain-and-events.md はP0-03の下位契約であり、DomainEvent、FactRecord、Visibility、
  derive_fact_id(event_id, 0)、rebuild_projection、Event Log権威、Transcript / Telemetryの型分離を所有する。
  P0-04はそれらを再定義せず、Evidenceとtest-only materializerから参照する。
- P0-02bで承認された技術スタックADR（docs/adr/0001-technology-stack.md）との関係は、Pydanticの
  ContractModel、strict validation、immutable contractを利用することに限る。P0-04は技術選定を変更せず、
  新しいProvider、Hook、Plugin、Registryの判断を行わない。
- 上位仕様、Phase順序、現Phaseの詳細計画、個別仕様の優先順位に従う。契約変更が必要な場合は、コードや本書を
  先に変更せず、承認済みPlanと必要なADRを先に改訂する。

本書の作成は docs/specs/semantic-result.md の新規追加だけを対象とし、コミットは行わない。
