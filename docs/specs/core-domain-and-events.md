# Core Domain and Event Model Specification

## 1. 位置づけと対象

本書は、Phase 0 / P0-03 で実装済みの contract model と、承認済み
Phase 0 計画 §9.1〜§9.6 が固定する Core Domain / Event 契約を記録する。
対象は Event v1 の wire 契約、stable ID、Visibility、DomainEvent の検証、
Projection の再構築、Turn status の投影、および Transcript / Telemetry の型境界で
ある。

本書のコード片に出てくる型名、field 名、signature、Event type は英語表記を
正本とする。P0-03 は実行基盤を作るPhaseではなく、後続実装が越えてはならない
契約境界を固定するPhaseである。

## 2. Goal と Non-goal

### 2.1 Goal

P0-03 の Goal は、次の不変条件を文書と実行可能な純粋 contract で固定し、
Event列から同じ Projection と Turn status を再構築できる状態にすることである。

- Event Log をゲーム状態に関する唯一の権威ある永続記録とする。
- State と Canon は Event から再構築できる Projection とする。
- 状態変更の入力は、raw JSON を検証して得た DomainEvent だけとする。
- Entity、Turn、Event、Fact などを stable ID で参照する。
- Event envelope に version、sequence、occurred_at、origin、Visibility を持たせる。
- TurnAwaitingPlayer、TurnResumed、TurnAborted を含む Turn status を投影する。
- Fact ID と Dice seed を決定論的に導出する。
- Event列を削除せずに TurnReverted で対象Turnの効果を Projection から除外する。
- Transcript / Telemetry を DomainEvent とゲーム状態のトランザクションから分離する。

### 2.2 Non-goal

次は本仕様 / P0-03では追加・公開しない。Phase 0の別WPで既存または別成果物として
扱うものは、このNon-goalの対象外とする。P0-01bで既に存在するthin FastAPI health
adapter、およびP0-07のFake / Scripted / Recorded Fixture Providerを禁止対象に
誤読しない。

- Event append、Event Store、Store interface、DB、database table、SQLite
  transaction、migration runner。
- Turn Engine、実際のTurn実行、Scenarioを遊ぶ処理、Web UI。
- P0-03で追加するproduction HTTP endpoint / adapter、real Provider呼び出し、
  Provider abstraction / registry。上記のP0-01b health adapterとP0-07のfixture
  Providerは、別WPの既存または別成果物であり、この禁止対象ではない。
- HTTP resend の実装、resend時の既存結果返却、任意時点・部分・recursive revert。
  P0-03 は canonical Event列の same-request 検証までであり、実HTTP再送は P1-03
  の対象である。
- TurnStarted Event と EmptyPayload。これらは省略するのではなく、parser で
  unknown_event として拒否する。
- decoded Mapping を受け取る public parser、version の暗黙変換、raw input、
  Narrative、Transcript、Telemetry、prompt、secret、API key を Event payload
  に入れる経路。
- test-only reference reducer、reference_projection、期待値自動生成helper。
- Plugin、Hook、Profile、Manifest、Capability Graph、および二つ目の
  Ruleset / Scenario。将来用の抽象化や空のInterfaceも作らない。
- 完全な Canon Ledger、Recall検索基盤、汎用 Scenario Editor、本格的な戦闘、
  認証、Docker、公開デプロイ、複数人対応。
- Semantic Result の生成・変換仕様、Narrative の生成、自由文 Narrative parsing。
  自由文を後からparseして状態へ反映する経路は作らない。

## 3. 中核不変条件

### 3.1 Event Log、State、Canon

Event Log がゲーム世界とゲーム状態の唯一の権威である。State や Canon を直接
更新する公開 API は存在しない。状態に関わる変更は、将来の Event append 経路で
検証済み DomainEvent として記録され、そのEvent列からProjectionを再構築する。
P0-03では append 自体は作らないが、この所有権を破る入力経路も作らない。

P0-03 の concrete Projection は、Stateに相当する campaign/session/scene、
resource/location/clock と、Canonに相当する facts を同じ immutable model に
保持する。別の CanonProjection や StateProjection class は定義しない。
どちらも Event から再生成可能な派生値であり、Event Logの代替ではない。

rebuild_projection と project_turn_status は、入力された Sequence[DomainEvent]
をそのまま信用しない。全Eventを strict に再検証し、canonical sequence、Event ID、
campaign、wire context、payload、origin を検証してから対象のreduce/filterを行う。
検証済みでない Event、raw JSON、decoded mapping、Transcript、Telemetry は状態投影の
入力にならない。

### 3.2 順序、秘密、文章

- canonical Event列の順序は入力の sequence が決める。occurred_at でsortしない。
- Semantic Result と Narrative は別の責務であり、NarrativeはEventの代わりにならない。
- 公開先に不可視な情報を公開向け呼び出しへ渡さない。P0-03のpayload、fixture、
  validation error、通常ログへ API key や secret を書かない。
- Turn が失敗しても Transcript / Telemetry の記録をゲーム状態のrevertに含めない。
  それらはそもそも DomainEvent union と Projection input の外側にある。

## 4. 依存方向、所有権、寿命

### 4.1 Contract module の依存方向

各moduleの定義元と依存方向は次で固定する。矢印は「右側を利用する」を表し、
下位のcontractから上位のApplicationや未実装のStoreへ依存しない。

| module | 所有するもの | 依存先 |
|---|---|---|
| base.py | 唯一の ContractModel、FrozenJsonValue | Pydanticのみ |
| contracts/__init__.py | stableな__all__によるcanonical public export policy。型の重複定義なし | 各contract module |
| ids.py | stable ID grammar、Visibility、metadata literal | Pydantic、標準の日時/正規表現 |
| domain.py | 17 Event payload、v1 envelope、DomainEvent、Dice seed、Transcript / Telemetry型 | base.py、ids.py |
| event_parser.py | raw JSON parser、sanitized validation issue/error | base.py、domain.py |
| projection.py | FactRecord、State/Canonを含む Projection、Fact ID、純粋 reducer | base.py、domain.py、ids.py、parserのsanitized error |
| turn_status.py | Turn status projection と遷移検証 | domain.py、projection.pyのcanonical validation、parserのsanitized error |

Application、HTTP、Event Store、DB、Turn Engine、Provider、Plugin、Hook、Profile は
このP0-03 contractの依存先ではない。P0-03はそれらのinterfaceを先回りして定義しない。

### 4.2 所有権と寿命

- parsed DomainEvent は immutable な値であり、canonical Event列の要素として扱う。
  parserは入力raw bytes/textを所有・保存せず、検証済みmodelだけを返す。
- Event Logは権威ある履歴を所有する概念上の境界だが、P0-03ではそのStoreやappend
  lifecycleを作らない。
- Projection は Event列から必要時に作り直せる派生値であり、破棄しても正史を
  失わない。rebuild_projection は既存Eventや既存Projectionを変更しない。
- TranscriptEntry と TelemetryEntry は DomainEvent と別の型で、別の保存寿命を
  持つ。ゲーム状態のEvent transactionに参加せず、失敗Turnの記録や費用を
  TurnReverted で戻す責務を持たない。P0-03ではそのStoreを作らない。
- Secret/API keyの所有者をcontractに置かない。validation errorにも秘密のcauseや
  contextを残さない。

## 5. Stable ID と Visibility

### 5.1 ID grammar

IDは表示名ではなく stable ID で参照する。次の型は全て strict な str であり、
英小文字、数字、単一ハイフン区切りのslugだけを許可する。

~~~text
^<prefix>:[a-z0-9]+(?:-[a-z0-9]+)*$
~~~

prefix と型の対応は次の通りである。

| 型 | prefix |
|---|---|
| CampaignId | campaign |
| SessionId | session |
| SceneId | scene |
| TurnId | turn |
| TurnRequestId | turn-request |
| EventId | event |
| NpcId | npc |
| EntityId | entity |
| FactSubjectId | fact-subject |
| CharacterId | character |
| LocationId | location |
| ItemId | item |
| ClockId | clock |
| ResourceId | resource |
| ActionId | action |
| ScenarioId | scenario |
| SecretId | secret |
| ClueId | clue |
| InvariantId | invariant |
| EndConditionId | end-condition |
| TranscriptId | transcript |
| TelemetryId | telemetry |
| ModelCallId | model-call |

したがって、例えば npc:gareth、turn-request:one は有効だが、大文字、
空slug、連続または末尾のハイフン、名前だけの値は無効である。

FactId だけは次の別grammarである。

~~~text
^fact:[0-9a-f]{64}:(0|[1-9][0-9]*)$
~~~

SHA-256 digestは常に lowercase hex とする。LowercaseSha256 は次のgrammarで
ある。

~~~text
^[0-9a-f]{64}$
~~~

### 5.2 Visibility と関連literal

Visibility は Event単位の可視範囲で、次のいずれかである。

~~~text
"gm_only" | "player_visible" | NpcId
~~~

最後の分岐は、上記の npc:<lowercase-slug> grammar を持つ値である。
VisibilityはFact payloadの中にはなく、FactAsserted EventのVisibilityが
FactRecord.visibilityへコピーされる。

Fact関連のliteralは次の通りである。

| 型 | 許可値 |
|---|---|
| FactKind | fact、ruling、agreement、plan、promise |
| FactHolder | world、player_character、rumor、または NpcId |
| SceneEndReason | completed、aborted、table_correction |
| SessionEndReason | completed、aborted、table_correction |

## 6. Fact ID と Dice seed の導出

### 6.1 Fact ID

public signatureは次である。

~~~python
def derive_fact_id(event_id: EventId, ordinal: int) -> FactId: ...
~~~

ordinal は type(ordinal) is int の strict int、0以上、0-basedである。
bool は int として受け付けない。preimageは次のbyte列で、ASCII encodeと
NUL delimiterを固定する。

~~~text
b"neontof:fact-id:v1\0" +
event_id.encode("ascii") + b"\0" +
decimal_ascii(ordinal)
~~~

SHA-256のlowercase hex digestを使い、次を返す。

~~~text
fact:{digest}:{ordinal}
~~~

固定vectorは次の通りである。

| event_id / ordinal | expected FactId |
|---|---|
| event:alpha / 0 | fact:bd64e06f407fa7ae48f0dd712f0817622f6fab8b9ea11905979745c1426b2ef4:0 |
| event:alpha / 1 | fact:977fdf29ed9b0faeaf966c4ac373e2e209c939d32b4329674b922d21680de4e2:1 |
| event:z9 / 42 | fact:7d9055cf0f3053fabcf237138adc2ec54a67353e2e9b953be2239c3caf050b95:42 |
| event:e10 / 0 | fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d0:0 |

P0-03の FactAsserted payloadにはordinal fieldを持たせない。現在の
rebuild_projection は FactAsserted 1件につき derive_fact_id(event.event_id, 0)
を使う。

### 6.2 Dice seed

public signatureは次である。

~~~python
def derive_dice_seed(
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: StrictInt,
) -> LowercaseSha256: ...
~~~

引数は、LowercaseSha256、TurnId、ActionIdのgrammarを満たすtyped /
prevalidated valueであることを事前条件とする。derive_dice_seed のruntime validation
が行うのは roll_index がnon-negativeなstrict intであることだけであり、raw ID
grammarを再検証する関数ではない。raw boundaryのID validationはparser /
ContractModelが担う。

roll_index は strict int の0以上で、JSON、Unicode、locale、時刻、global random
を使わない。導出式は次のbyte列をSHA-256へ渡すものに固定する。

~~~text
H(campaign_seed, turn_id, action_id, roll_index) =
  sha256(
    b"neontof:dice-seed:v1\0" +
    campaign_seed.encode("ascii") + b"\0" +
    turn_id.encode("ascii") + b"\0" +
    action_id.encode("ascii") + b"\0" +
    decimal_ascii(roll_index)
  ).hexdigest()
~~~

neontof:dice-seed:v1 は domain separator、各 b"\0" はfield delimiterである。
derived_seed は DiceRolled payloadに記録し、Eventの turn_id、campaign seed、
action、indexから再計算した値と一致しなければ rejectする。

基準vectorは次の通りである。

| 材料 | expected LowercaseSha256 |
|---|---|
| ("a"*64, "turn:one", "action:open-door", 0) | b80e804f6f362eb3c4735e474929ef29d1baca3965e6a67e52b90a4ae58e86b8 |
| campaign seedだけを "c"*64 に変更 | 75cc328734cacc6d128f863d0c180934ad58285df03aca81196fb85c7e885c15 |
| turnだけを "turn:two" に変更 | 2b3e845c438aa526f7132567cbcc0b52ed58bc7822c28a9273b694d84dbc8169 |
| actionだけを "action:close-door" に変更 | a1e89a1876de69ed63e099c0ec43063f8cece9ecdc9f5f45a7087e3a34d6ea2e |
| roll indexだけを 1 に変更 | 95aba69461649e4d1e8a182bce634d7ac21775f8002cb1dcfea1a2c379551f65 |

## 7. ContractModel と immutable JSON

### 7.1 共通model設定

src/neontof/contracts/base.py の ContractModel が唯一の定義元である。
全てのpayload、Event subtype、Projection、validation issue はこのmodelを継承し、
同じ設定を使う。

~~~python
class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
~~~

- strict=True: 数値文字列などの暗黙変換をしない。
- extra="forbid": wire top-level、payload、nested modelの未知fieldを拒否する。
- frozen=True: model fieldを代入で変更できない。
- revalidate_instances="always": typed modelを受け取る境界でも再検証し、
  model_copy等で改変された値を reducerへ通さない。

### 7.2 FrozenJsonValue

FrozenJsonValue は FactAssertedPayload.value の公開値で、入力のaliasを
切断しながら再帰的にimmutableな形へ変換する。許可される値は次である。

- None
- strictな str
- strictな bool
- strictな int（boolをintとして受理しない）
- finiteな float（NaN、+inf、-inf は拒否）
- 上記を要素とする list/tuple。凍結後はtupleになる。
- string keyを持つ dict。凍結後はuniqueなkeyをsortした
  tuple[tuple[str, FrozenJsonValue], ...] になる。

list、dict、tupleは再帰的に走査される。active containerのIDを追跡して
自己参照・相互参照のcycleを拒否する。dict keyはstrictなstrだけである。
入力側のnested object/arrayを後から変更しても、検証済み値は変わらない。
frozen modelとtuple化されたnested valueへのmutationは拒否される。

## 8. Event v1 wire envelope

### 8.1 Top-level field

全Eventは次のfieldを必ず持つ。nullableなfieldも省略せず、明示的な
nullを送る。subtypeの type がdiscriminatorであり、payloadはその
subtypeのstrict ContractModelである。

| field | type / invariant |
|---|---|
| type | 下記17種のliteral。v1 unionのdiscriminator |
| event_id | EventId。canonical Event列内でunique |
| event_version | strict int のliteral 1。未知versionはreject |
| campaign_id | CampaignId。全Eventでrequired |
| session_id | SessionId \| None。Event typeのcontext規則に従い値または明示的null |
| scene_id | SceneId \| None。Event typeのcontext規則に従い値または明示的null |
| turn_id | TurnId \| None。Event typeのcontext規則に従い値または明示的null |
| sequence | strict int。canonical campaign列では1開始・欠落なしの連番 |
| occurred_at | OccurredAt。ASCIIの YYYY-MM-DDTHH:MM:SSZ、秒精度、実在日時 |
| origin | 一般Eventは in_world \| table_correction。TurnReverted は table_correction のみ。systemは不可 |
| visibility | Visibility |
| payload | Event subtype固有のstrict ContractModel。extra fieldなし |

sequenceはcanonical列で 1, 2, ..., N でなければならない。Event IDの重複、
sequenceの欠落・重複・順序不一致、campaign IDの混在はcanonical validationの
失敗である。複数Eventは入力配列の順序を使い、occurred_atで並べ替えない。
日時は表示用metadataであり、ゲーム判断や順序付けには使わない。

occurred_at は次だけを受理する。

~~~text
^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$
~~~

local time、offset、fractional seconds、lowercase z、実在しない日付、
秒精度を外れる値は拒否する。

### 8.2 context規則

top-levelの3つのcontext fieldは、次の表に従ってrequiredまたはnullableとなる。
nullableの場合もfield自体は必須である。

| Event type | session_id | scene_id | turn_id |
|---|---|---|---|
| CampaignCreated | null | null | null |
| SessionStarted | required | null | null |
| SceneStarted、SceneEnded | required | required | null |
| PlayerInputAccepted、DiceRolled、ResourceChanged、CharacterMoved、ClockAdvanced | required | required | required |
| TurnAwaitingPlayer、TurnResumed、TurnAborted、TurnCommitted | required | required | required |
| FactAsserted、FactSuperseded | required | nullable | nullable |
| TurnReverted | required | nullable | nullable |
| SessionEnded | required | null | null |

TurnRevertedのtargetはenvelopeの turn_id ではなくpayloadの
target_turn_idで表す。そのため通常は scene_id と turn_id が nullでも、
対象Turnのrevertとして扱う。

## 9. 17 Event type と payload

全payloadは対応するstrict subtypeであり、fieldの追加・省略・型の暗黙変換を
受け付けない。NonEmptyString は strictな非空 str、NonNegativeStrictInt
は strict int かつ >= 0、PositiveStrictInt は strict int かつ > 0 である。

| Event type | payload fields / type | ProjectionまたはTurn statusへのeffect |
|---|---|---|
| CampaignCreated | name: NonEmptyString | campaign_nameを設定する。campaign_idはenvelopeの値を使う。 |
| SessionStarted | scenario_id: ScenarioId \| None、title: NonEmptyString | session_id、scenario_id、session_titleを設定する。 |
| SceneStarted | label: NonEmptyString | scene_idとscene_labelを設定し、scene_end_reason=Noneに戻す。 |
| SceneEnded | reason: SceneEndReason | 現在のsceneをclearせず、scene_end_reasonへreasonを記録する。 |
| PlayerInputAccepted | turn_request_id: TurnRequestId、input_digest: LowercaseSha256 | raw inputではなくdigestだけを記録し、対象Turnのrequestを一度だけ受理する。statusはpendingのまま。 |
| DiceRolled | campaign_seed: LowercaseSha256、action_id: ActionId、roll_index: NonNegativeStrictInt、derived_seed: LowercaseSha256、formula: NonEmptyString、result: StrictInt | 導出材料、seed、式、結果をaudit可能に記録する。実装はseed一致を検証するが、ここではglobal randomを実行しない。 |
| ResourceChanged | resource_id: ResourceId、entity_id: EntityId、delta: StrictInt | (resource_id, entity_id)ごとのresource値へdeltaを加算する。 |
| CharacterMoved | character_id: CharacterId、from_location_id: LocationId \| None、to_location_id: LocationId | 現在locationがfrom_location_idと一致することを検証し、to_location_idへ変更する。初回の現在値はNone。 |
| ClockAdvanced | clock_id: ClockId、delta: PositiveStrictInt | clock値へdeltaを加算する。 |
| FactAsserted | kind: FactKind、holder: FactHolder、subject_id: EntityId \| None、predicate: NonEmptyString、value: FrozenJsonValue | event_idとordinal 0からFactを作り、EventのVisibilityをFactへコピーする。statusはactive。 |
| FactSuperseded | target_fact_id: FactId | 既にProjectionに存在するtarget Factだけをsupersededへ変更する。 |
| TurnAwaitingPlayer | turn_request_id: TurnRequestId | 対象Turnをrunningからawaiting_playerへ進める。 |
| TurnResumed | turn_request_id: TurnRequestId | pendingまたはawaiting_playerからrunningへ進める。 |
| TurnAborted | turn_request_id: TurnRequestId、reason: Literal["failed", "cancelled", "table_correction"] | pending、running、awaiting_playerの対象Turnをabortedへ終端化する。 |
| TurnCommitted | turn_request_id: TurnRequestId | runningまたはawaiting_playerの対象Turnをcommittedへ終端化する。 |
| TurnReverted | target_turn_id: TurnId | target Turnのstate/fact effectをProjectionへ適用せず、reverted_turn_idsへtargetを追加する。status自体は変更しない。 |
| SessionEnded | reason: SessionEndReason | session_idをclearせず、session_end_reasonへreasonを設定する。 |

この17種がEvent typeの全体である。

~~~text
CampaignCreated
SessionStarted
SceneStarted
SceneEnded
PlayerInputAccepted
DiceRolled
ResourceChanged
CharacterMoved
ClockAdvanced
FactAsserted
FactSuperseded
TurnAwaitingPlayer
TurnResumed
TurnAborted
TurnCommitted
TurnReverted
SessionEnded
~~~

TurnStarted、EmptyPayload、Narrative、raw input、Transcript、Telemetry、
prompt、secret、API keyはEvent typeまたはpayloadとして存在しない。

## 10. Raw parser と sanitized validation error

### 10.1 public signature とraw JSON境界

public parserはraw str \| bytesだけを受ける。decoded Mapping、任意object、
decoded Sequence[object]をpublic入力に戻さない。

~~~python
def parse_domain_event(raw: str | bytes) -> DomainEvent: ...
def parse_domain_event_sequence(raw: str | bytes) -> tuple[DomainEvent, ...]: ...
~~~

parse_domain_event はUTF-8 JSON objectだけ、parse_domain_event_sequence は
UTF-8 JSON arrayだけを受理する。Python型が str または bytes でない場合は
入力値をreprへ入れず、次だけをraiseする。

~~~text
TypeError("raw must be str or bytes")
~~~

parser内部のraw境界は次のprivate adapter経路に固定する。

- _RAW_EVENT_ADAPTER.validate_json(raw, strict=True) でversion probe。
- _DOMAIN_EVENT_V1_ADAPTER.validate_json(raw, strict=True) で単体v1 Eventを検証。
- _SEQUENCE_JSON_ADAPTER.validate_json(raw, strict=True) でJSON arrayを検証。
- sequence要素はdecoded objectをvalidate_pythonへ渡さず、UTF-8 JSON bytesへ
  再シリアライズして parse_domain_event へ渡す。

3つのadapterはprivateであり、public parserは常にraw JSON boundaryを通る。
versionを黙って別versionへ変換しない。

### 10.2 Issue と Error

DomainEventValidationIssue は次の3 fieldだけを持つ frozen
ContractModelである。

~~~python
class DomainEventValidationIssue(ContractModel):
    path: str
    code: IssueCode
    message: str
~~~

IssueCode の許可値は次である。

~~~text
schema
unknown_field
unknown_event
unknown_version
invalid_id
invalid_sequence
invalid_payload
~~~

DomainEventValidationError は ValueError であり、publicにはread-onlyな
issues tupleだけを公開する。

~~~python
class DomainEventValidationError(ValueError):
    def __init__(self, issues: tuple[DomainEventValidationIssue, ...]) -> None: ...

    @property
    def issues(self) -> tuple[DomainEventValidationIssue, ...]: ...
~~~

Errorの通常文字列は固定の domain event validation failed である。raw input、
input_value、URL、Pydantic context、cause、secretを保存しない。custom instance
attributeを増やさず、issuesはtupleとfrozen modelで公開する。validation failureは
DomainEventValidationError(issues) from Noneでraiseし、元のPydantic errorを
cause / contextへ残さない。

### 10.3 failure分類とredaction

raw JSON、Pydantic、sequenceのfailureは、値を含めずに次のcodeへ分類する。

| failure | code / pathの規則 |
|---|---|
| malformed JSON、JSON object/arrayのschema不一致 | schema |
| top-levelまたはpayloadの未知field | unknown_field。top-levelはfield、payloadはpayload.field |
| 17種にない type、TurnStarted、EmptyPayload | unknown_event、pathはtype |
| event_version の欠落、非strict int、literal 1以外 | unknown_version、pathはevent_version |
| ID grammar不一致 | invalid_id。既知のID fieldだけをpathに出す |
| payload fieldの型、missing、literal、timestamp等の不正 | schema または invalid_payload |
| sequenceの1開始・連番、Event ID uniqueness、campaign一致の破綻 | invalid_sequence |

revert targetの先行commit、直近commitとの一致、commit数、revertの一回性は
raw parserの責務ではない。parse_domain_event / parse_domain_event_sequence は
wire、schema、ID、sequence、campaignのraw境界を検証し、revert semanticsは
rebuild_projectionがcanonical Event列に対して検証する。

Pydantic errorsは include_input=False、include_url=False、
include_context=False 相当で取り出す。issue pathは既知のtop-level/payload
fieldだけを許可し、未知のfield名や未知のpath segmentは固定の field へ
置き換える。したがって、悪意あるfield名、URL、raw JSON、API keyは
issue path/message、str(error)、repr(error)、args、__dict__、
__cause__、__context__、issues、通常log、fixtureのいずれにも現れない。
fixtureにも secret / Narrative / Transcript / Telemetry / raw input / API keyを
入れない。このP0-03が契約する公開Error / issue / 通常log / fixtureのredaction
surfaceは、ここで列挙した面に限定する。`__traceback__`やcaller frame localsの
scrubは保証しないため、caller側でraw inputを保持・ログしない運用責務を負う。
DomainEventValidationError自身のcustom dataはsanitizedとし、raw input、cause、
context、secretを保持しない。

## 11. Projection

### 11.1 公開modelとfield

projection.py が次のmodelを所有する。field順も契約の一部である。

~~~python
class ResourceState(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    value: StrictInt

class CharacterLocation(ContractModel):
    character_id: CharacterId
    location_id: LocationId | None

class ClockState(ContractModel):
    clock_id: ClockId
    value: StrictInt

class FactRecord(ContractModel):
    fact_id: FactId
    event_id: EventId
    kind: FactKind
    holder: FactHolder
    subject_id: EntityId | None
    predicate: str
    value: FrozenJsonValue
    visibility: Visibility
    status: Literal["active", "superseded"]

class Projection(ContractModel):
    campaign_id: CampaignId | None
    campaign_name: str | None
    session_id: SessionId | None
    scenario_id: ScenarioId | None
    session_title: str | None
    scene_id: SceneId | None
    scene_label: str | None
    scene_end_reason: SceneEndReason | None
    session_end_reason: SessionEndReason | None
    resources: tuple[ResourceState, ...]
    locations: tuple[CharacterLocation, ...]
    clocks: tuple[ClockState, ...]
    facts: tuple[FactRecord, ...]
    reverted_turn_ids: frozenset[TurnId]
    applied_through_sequence: StrictInt
    audit_event_ids: tuple[EventId, ...]
~~~

P0-03の FactRecord.status は active | superseded だけである。disputed
などのCanon ledger全体のstatusはこのcontractへ追加しない。

公開collectionにmutable list / dictを使わない。resources は
(resource_id, entity_id) のstable ID順、locations はcharacter ID順、
clocks はclock ID順、facts はFact ID順にcanonicalizeし、
audit_event_ids は入力sequence順を保持する。

### 11.2 rebuild_projection

public signatureは次である。

~~~python
def rebuild_projection(events: Sequence[DomainEvent]) -> Projection: ...
~~~

この events は単一campaignの全canonical Event列であり、事前filter済みの列や
raw JSONではない。処理順は次の通りである。

1. 入力sequenceをtuple化し、typed DomainEventを全て strict 再検証する。
2. 全Eventについて Event envelope、ID、context、payload、origin、
   campaign ID、sequence 1開始連番、Event ID uniquenessを検証する。
3. 各 TurnReverted の時点で、そのEventより前に存在する直近の TurnCommitted の
   turn_idがpayload targetであり、targetがその時点までにちょうど1回commit済みで、
   同一targetを既にrevertしていないことだけをfail-closedに検証する。これは
   Product Planの直前Turn semanticsを維持する条件である。prior commitがない場合、
   直近commitがtargetでない場合、targetのその時点までのcommitが0回または2回以上の場合、
   同一targetを既にrevertしている場合は拒否する。revert後の同じTurnの再commitなど
   全campaign lifecycleはrebuild_projectionの責務外とし、対象Turnのlifecycle terminal /
   後続遷移はproject_turn_status側の責務とする。
4. 検証に失敗した場合はProjectionを返さず、sanitized
   DomainEventValidationErrorをraiseする。
5. 検証済みEventを入力sequence順にreduceする。既存入力をsort、delete、mutateせず、
   occurred_at順にも並べ替えない。

TurnReverted のtarget Turnに属するEventは、そのEvent自身の turn_id がtargetと
一致する限りstate/fact effectを適用しない。TurnReverted自身はtargetの
turn_idをenvelopeに持たない場合でも、audit_event_idsに残る。したがって、
revert後も全監査Eventをsequence順に確認できる。

FactSuperseded はtarget Factがその時点までに存在するときだけ適用できる。
CharacterMoved は from_location_id と現在locationが一致するときだけ適用する。
これらに失敗した場合もProjectionを返さない。

空Event列では、全nullable scalarは None、collectionは空tupleまたは
空frozenset、applied_through_sequence は 0、audit_event_ids は空tupleとなる。
同じEvent列を2回rebuildした結果はdeep equalである。Projectionを破棄してから
同じEvent列で再構築しても同じ値になる。

## 12. Turn status projection

### 12.1 signatureと入力

public signatureは次である。

~~~python
def project_turn_status(
    turn_id: TurnId,
    events: Sequence[DomainEvent],
) -> TurnStatus: ...
~~~

TurnStatus の許可値は次である。

~~~text
pending | running | awaiting_player | committed | aborted
~~~

events は単一campaignの全canonical Event列であり、対象Turnだけに先に
filterしてはならない。まず全Eventについてcampaign、sequence、Event ID、
envelope、payload、origin、wire contextなどの構文・canonical検証を行い、その後に
対象を選ぶ。これは全Turnのlifecycle transition順序を実行することではない。
別Turnのwell-formed Eventは無視し、別Turnのlifecycle順序、request ID mismatch、
terminal後の遷移を理由にrejectしない。filter前にrejectするのは、全列のwire /
canonical invariant違反だけである。

対象判定は通常Eventでは event.turn_id == turn_id、TurnRevertedでは
event.payload.target_turn_id == turn_id である。Campaign/Session/Scene/Factの
turn_id=None Eventは対象外で無視する。対象Eventが1件もなければ pending を返す。

### 12.2 許可される遷移

| current / Event | next status | 条件 |
|---|---|---|
| 初期 / 対象Eventなし | pending | 対象Eventがない場合 |
| pending / PlayerInputAccepted | pending | requestを一度だけ受理 |
| pending / TurnResumed | running | 先に同じTurnのinputを受理済み |
| running / TurnAwaitingPlayer | awaiting_player | request IDが一致 |
| awaiting_player / TurnResumed | running | request IDが一致 |
| running または awaiting_player / TurnCommitted | committed | request IDが一致 |
| pending、running、または awaiting_player / TurnAborted | aborted | request IDが一致 |
| committed / payloadがtargetのTurnReverted | committed | statusは変更しない |

TurnResumed は pending または awaiting_player からだけ許可する。
TurnAwaitingPlayer は running からだけ、TurnCommitted は running または
awaiting_player からだけ許可する。TurnAborted は表の3状態からだけ許可する。
terminal後の対象Event、未許可遷移はrejectする。

### 12.3 same-request と TurnReverted

対象Turnの PlayerInputAccepted が設定した turn_request_id を基準に、
PlayerInputAccepted、TurnAwaitingPlayer、TurnResumed、TurnAborted、
TurnCommitted に存在するrequest IDは全て一致しなければならない。

- PlayerInputAccepted は対象Turnで一度だけ許可する。
- 最初のlifecycle Eventは PlayerInputAccepted でなければならない。
- request ID mismatch、重複受理、terminal後の再開をrejectする。
- lifecycle payloadを持たないstate effect Eventも、running または
  awaiting_player 以外ではrejectする。
- 別Turnの正当なEventにあるrequest ID mismatchは対象Turnの検証へ混ぜない。

TurnReverted は envelopeの turn_id ではなくpayloadの target_turn_idにより
対象化する。targetが committed でなければrejectし、許可された一回の
origin="table_correction" Eventとして扱う。ただし、statusを reverted などへ
変換せず、返り値は committed のままである。revertされた事実は
Projection.reverted_turn_ids で表す。

## 13. Transcript / Telemetry の型分離

DomainEvent unionとProjection入力には、次の型を含めない。

~~~python
class TranscriptEntry(ContractModel):
    entry_id: TranscriptId
    text: NonEmptyString

class TelemetryEntry(ContractModel):
    entry_id: TelemetryId
    name: NonEmptyString
~~~

TranscriptEntry はPlayer Input、Model Request/Response、Tool Call、エラー、
retry、公開Narrativeなどの記録を置くための別型であり、TelemetryEntry は
利用状況の記録を置くための別型である。P0-03では上記の最小field以外の
Transcript/Telemetry schemaやStoreを発明しない。

これらはゲーム状態のtransaction外へappendする。Turnが失敗してもTranscriptと
Telemetryの記録を消さず、費用をTurn revertで戻さない。逆に、これらの値を
DomainEvent payloadへ埋めたり、rebuild_projection / project_turn_statusへ
渡したりする経路は型上も実装上も持たない。秘密やAPI keyを通常ログ・fixture・
公開Narrativeへ書かない制約はこの分離より上位にある。

## 14. Versioned contract の変更規則

本書は event_version=1 のversioned contractである。Event type、wire field、
context、payload field/type、ID grammar、導出式、Projection field、Turn遷移を
変更する場合は、実装を先に変更せず、先に承認済み Plan と必要な ADR を更新する。
P0-03 parserは未知versionを暗黙変換せず rejectし、migration runnerはPhase 0の
対象外である。
