# Test Provider と Fixture 仕様

- **対象**: Phase 0 / P0-07 (Test Provider and Fixture Strategy)
- **目的**: API key、課金、外部 network、実モデルの出力揺れなしで、model invocation の成功・失敗・再試行相当・timeout・invalid JSON・決定性を検証する
- **根拠**: [AGENTS.md](../../AGENTS.md)、[docs/IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md)、[docs/plans/phase-00-foundation.md の §13](../plans/phase-00-foundation.md)、実装と focused test
- **文書の立場**: この文書は P0-07 が固定する最小の契約であり、Phase 1 の実 Provider 設計を先取りしない

## 1. 目的と適用範囲

P0-07 は、API key を持たず、課金せず、外部 network に接続せず、同じ入力から同じ typed response・sanitized call log・検証済み proposed Event sequence を得るための test harness を固定する。対象は provider-neutral な request / response 境界と、Fake / Scripted / Recorded Fixture の三つの test 用具である。

この仕様の「成功」は、provider が schema-valid な ModelResponse を返し、その後に P0-04 の validate_semantic_result が AcceptedSemanticResult を返すことを指す。provider の成功だけでは Event は生成されない。

### 1.1 P0-07 で固定するもの

- ModelRequest から ModelResponse へ至る一つの ModelInvoker (Callable) 境界
- SemanticResultV1 を ModelResponse.payload に保持する typed response
- discriminated ProviderStep と PROVIDER_STEP_ADAPTER
- 固定 step を返す Fake Provider、step 列を消費する Scripted Provider、JSON bytes を再生する Recorded Fixture Provider
- RecordedFixtureV1 の version 1 schema と、6つの provider fixture の期待値
- ProviderCallLogMeta から raw request を含まない SanitizedProviderCallLogEntry を作る規則
- context の canonical JSON、SHA-256 digest、visibility の test-only filter、固定された失敗 taxonomy
- API key なし、network call 0、外部 Provider なしの focused test / gate

### 1.2 Non-goal

P0-07 では次を作らない。これらが必要になった場合は計画と境界を改訂してから、別 Phase の作業として扱う。

- 実 Provider、OpenAI SDK、Provider Adapter、複数の実 Provider
- API key、Secret store、Secret Store integration、credential 管理
- retry runtime、backoff、retry policy、timeout policy、budget / rate limit runtime
- Provider registry、Plugin、Hook、Profile、capability negotiation、capability registry
- 二つ目の Provider を前提にした hierarchy、generic factory、interface の一般化
- production Context Builder、production visibility filter、Prompt 生成、Provider request mapping
- Event append、State / Canon の更新、Turn Engine、Event Store
- Transcript、Telemetry、費用の記録・課金計算・費用の rollback
- SQLite、sqlite3.Connection、migration、database file、永続 call log
- raw 実 Provider response、実ネットワーク、実 Provider の CI test

retry-then-success は Scripted / Recorded の step 消費を再現する test data であり、retry runtime の実装ではない。test-only driver が fixture の expected_call_count 回だけ呼び出すが、backoff や retry policy を持つ production API ではない。

## 2. Provider 境界とゲーム状態境界

### 2.1 データフロー

~~~text
ModelRequest
    │
    ▼
TestProvider.invoke(request)
    │
    ├─ success: ModelResponse(payload: SemanticResultV1, usage: ModelUsage)
    └─ failure: fixed exception + sanitized call log

success response (test-only driver)
    │
    ▼
validate_semantic_result(response.payload, validation_context)
    │
    ├─ AcceptedSemanticResult
    │       │
    │       ▼
    │   materialize_semantic_result_for_test(...)
    │       │
    │       ▼
    │   tuple[DomainEvent, ...]  # test observation only
    └─ non-accepted outcome → events == ()
~~~

Event Log がゲーム状態の唯一の権威であり、State / Canon は Event から再構築される。Provider が所有するのは、typed ModelResponse と instance-local な sanitized observation だけである。Provider は Event、State、Canon、Transcript、Telemetry、費用を所有せず、これらへ書き込む関数を公開しない。

materialize_semantic_result_for_test は P0-04 の test-only materializer であり、P0-07 の Provider の責務ではない。P0-07 の production source に materializer、Event append、State direct update API を追加しない。

### 2.2 Semantic Result と Narrative

ModelResponse.payload は typed SemanticResultV1 である。payload 内の narrative と narrative_plan は Narrative の出力情報であり、状態変更の権威ではない。tests/model/test_recorded_fixture.py::test_narrative_changes_never_change_materialized_events は、同じ proposed_events のまま Narrative だけを差し替えた場合に materialized Event が同一で、proposed_events の delta を変えた場合だけ Event が変わることを固定する。

自由文を parse して Event や State を作らない。success response は schema validation の後、さらに P0-04 の validate_semantic_result を通し、AcceptedSemanticResult の proposed_events / proposed_facts だけを test-only materializer へ渡す。

### 2.3 失敗 Turn と観測

Provider failure、timeout、invalid JSON、script exhaustion では ModelResponse と Event を作らない。一方、失敗した attempt の sanitized call log は残す。provider success 後に P0-04 の semantic validation が non-accepted outcome を返す場合は、typed ModelResponse は観測結果として残るが、Event と materialization は作らない。これはゲーム状態の transaction ではなく、test provider の観測値である。usage は ModelUsage の token counter であり、費用や課金額ではない。Transcript / Telemetry の保存規則をこの仕様で代替しない。

## 3. 正確なファイルパスと責務

| パス | P0-07 での責務 |
|---|---|
| docs/specs/test-provider-and-fixtures.md | 本契約。fixture version、typed validation、sanitization、error、call log、network / API key なしの方針を記録する。 |
| [src/neontof/model/__init__.py](../../src/neontof/model/__init__.py) | model contract の最小 package export。Context Builder / visibility filter は所有しない。 |
| [src/neontof/model/model_invoker.py](../../src/neontof/model/model_invoker.py) | ModelRequest、ModelUsage、ModelResponse、ModelInvoker、discriminated ProviderStep、ProviderCallLogMeta を定義する。 |
| [src/neontof/model/fake_provider.py](../../src/neontof/model/fake_provider.py) | 一つの validated ProviderStep を invocation ごとに再現する create_fake_provider を提供する。 |
| [src/neontof/model/scripted_provider.py](../../src/neontof/model/scripted_provider.py) | Sequence[ProviderStep] を順序どおり一つずつ消費し、instance-local な calls を記録する create_scripted_provider を提供する。 |
| [src/neontof/model/recorded_fixture.py](../../src/neontof/model/recorded_fixture.py) | JSON bytes の duplicate-key 検査、lossless decode、typed fixture load、Recorded Fixture Provider、sanitized call log を所有する。network I/O は持たない。 |
| [tests/model/__init__.py](../../tests/model/__init__.py) | test-only package marker。production export を持たない。 |
| [tests/model/support/__init__.py](../../tests/model/support/__init__.py) | test-only support namespace marker。production export を持たない。 |
| tests/model/support/filter_context_by_visibility.py | test-only の context / visibility filter。production API ではない。 |
| [tests/model/support/run_invocation_scenario.py](../../tests/model/support/run_invocation_scenario.py) | test-only driver。failure mapping、validate_semantic_result、materialize_semantic_result_for_test の接続を行う。Semantic Result の重複定義は持たない。 |
| [tests/model/test_fake_provider.py](../../tests/model/test_fake_provider.py) | Fake Provider の fixed success / failure、call log、strict contract、secret boundary を検証する。 |
| [tests/model/test_scripted_provider.py](../../tests/model/test_scripted_provider.py) | step 順、call count / order、failure 後の success、script exhaustion、固定 exception を検証する。 |
| [tests/model/test_recorded_fixture.py](../../tests/model/test_recorded_fixture.py) | JSON bytes から typed payload / expected Event へ至る fixture 境界、決定性、lossless scalar、duplicate key、strict scalar を検証する。 |
| [tests/model/test_provider_security.py](../../tests/model/test_provider_security.py) | sanitized call log、digest、固定 exception mapping、secret、visibility boundary、stdout / stderr / logging 非漏洩を検証する。 |
| tests/fixtures/providers/normal-turn.v1.json | success fixture。 |
| tests/fixtures/providers/retry-then-success.v1.json | model error の後に success を返す step sequence fixture。 |
| tests/fixtures/providers/model-error.v1.json | model error fixture。 |
| tests/fixtures/providers/timeout.v1.json | timeout fixture。 |
| tests/fixtures/providers/invalid-json.v1.json | invalid JSON fixture。 |
| tests/fixtures/providers/sanitized-call-log.v1.json | 空の Semantic Result と sanitized call log の success fixture。 |
| [tests/support/no_external_network.py](../../tests/support/no_external_network.py) | 全 pytest session の autouse fixture から呼ばれる test support。外部 network entrypoint を fail-fast にし、Windows TestClient / ASGI の内部 socketpair 通信だけを限定的に許可する。 |
| [tests/test_no_external_network.py](../../tests/test_no_external_network.py) | 全 pytest session に適用される _block_external_network の DNS / socket / HTTP / urllib / httpx 遮断を検証する。 |

src/neontof/model/__init__.py の root export は PROVIDER_STEP_ADAPTER、InvalidJsonStep、ModelErrorStep、ModelInvoker、ModelRequest、ModelResponse、ModelUsage、ProviderCallLogMeta、ProviderStep、PublicationVisibility、Role、SuccessStep、TimeoutStep である。factory と Recorded Fixture loader は各 module の関数として公開され、root package へ追加 export しない。

## 4. 公開契約

以下は実装に存在する型・alias・function の正確な形である。PublicationVisibility、FactRecord、SemanticResultV1、ProposedEvent、ModelCallId、TurnId、NonNegativeStrictInt、PositiveStrictInt、LowercaseSha256 は既存 contract を再利用し、P0-07 で再定義しない。

### 4.1 Request / response と invocation boundary

~~~python
Role: TypeAlias = Literal["referee", "world_simulator", "npc_actor", "narrator"]

class ModelRequest(ContractModel):
    model_call_id: ModelCallId
    turn_id: TurnId
    roles: tuple[Role, ...]
    publication_visibility: PublicationVisibility
    context: tuple[FactRecord, ...]
    output_schema: Literal["semantic-result-v1"]

class ModelUsage(ContractModel):
    input_tokens: NonNegativeStrictInt
    output_tokens: NonNegativeStrictInt
    cached_tokens: NonNegativeStrictInt

class ModelResponse(ContractModel):
    payload: SemanticResultV1
    usage: ModelUsage

ModelInvoker: TypeAlias = Callable[[ModelRequest], ModelResponse]
~~~

ModelRequest に API key、secret、credential、Secret Store の値を持たせない。context はすでに typed な tuple[FactRecord, ...] であり、raw JSON、Prompt、任意の dict を受ける境界ではない。

### 4.2 Discriminated provider step

~~~python
class SuccessStep(ContractModel):
    type: Literal["success"]
    response: ModelResponse

class ModelErrorStep(ContractModel):
    type: Literal["model_error"]
    code: str
    message: str

class TimeoutStep(ContractModel):
    type: Literal["timeout"]

class InvalidJsonStep(ContractModel):
    type: Literal["invalid_json"]
    body: str

ProviderStep: TypeAlias = Annotated[
    SuccessStep | ModelErrorStep | TimeoutStep | InvalidJsonStep,
    Field(discriminator="type"),
]
PROVIDER_STEP_ADAPTER: TypeAdapter[ProviderStep] = TypeAdapter(ProviderStep)
~~~

code、message、body は test step の入力としてのみ存在する。failure branch は ModelResponse を返さず、これらの raw 値を exception message や call log へ転送しない。

### 4.3 Call log の typed shape

~~~python
class ProviderCallLogMeta(ContractModel):
    attempt: PositiveStrictInt
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    usage: ModelUsage | None
    context_item_count: NonNegativeStrictInt
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None

class SanitizedProviderCallLogEntry(ContractModel):
    request_id: ModelCallId
    attempt: PositiveStrictInt
    publication_visibility: PublicationVisibility
    context_digest: LowercaseSha256
    context_item_count: NonNegativeStrictInt
    usage: ModelUsage | None
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None

ProviderCallLogEntry: TypeAlias = SanitizedProviderCallLogEntry
~~~

sanitized entry の JSON field 集合は次の8つに固定する。

~~~text
request_id
attempt
publication_visibility
context_digest
context_item_count
usage
status
error_code
~~~

roles、context、payload、任意 JSON、code、body、message、環境変数、API key、secret は保持しない。

### 4.4 Fixture、Provider、factory の Signature

~~~python
class RecordedFixtureV1(ContractModel):
    fixture_version: Literal[1]
    name: str
    steps: tuple[ProviderStep, ...]
    expected_call_count: NonNegativeStrictInt
    expected_final_outcome: Literal["success", "model_error", "timeout", "invalid_json"]
    expected_proposed_events: tuple[ProposedEvent, ...]

class TestProvider(Protocol):
    def invoke(self, request: ModelRequest) -> ModelResponse: ...

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]: ...

def create_fake_provider(step: ProviderStep) -> TestProvider: ...
def create_scripted_provider(steps: Sequence[ProviderStep]) -> TestProvider: ...
def load_recorded_fixture(source: bytes) -> RecordedFixtureV1: ...
def create_recorded_fixture_provider(source: bytes) -> TestProvider: ...
def sanitize_provider_call_log(
    input_request: ModelRequest,
    meta: ProviderCallLogMeta,
) -> SanitizedProviderCallLogEntry: ...
~~~

TestProvider は Protocol だが production Provider hierarchy ではない。ModelInvoker と同じく一つの Callable / Protocol boundary を検証するための最小形であり、registry、Plugin、Hook、Profile を導入する理由にはならない。

### 4.5 Test-only support の Signature

~~~python
def filter_context_by_visibility(
    facts: tuple[FactRecord, ...],
    publication_visibility: PublicationVisibility,
) -> tuple[FactRecord, ...]: ...

def run_invocation_scenario(
    source: bytes,
    request: ModelRequest,
    validation_context: SemanticValidationContext,
    event_context: FixtureEventContext,
) -> InvocationScenarioResult: ...
~~~

filter_context_by_visibility は [tests/model/support/filter_context_by_visibility.py](../../tests/model/support/filter_context_by_visibility.py) にだけ置く。run_invocation_scenario は [tests/model/support/run_invocation_scenario.py](../../tests/model/support/run_invocation_scenario.py) にだけ置き、production Context Builder や production visibility filter として再利用しない。

## 5. Recorded Fixture schema と6 fixture

### 5.1 schema

各 JSON file は次の root object を持つ。JSON から型化された後は mutable な raw mapping を契約値として保持しない。

~~~text
fixture_version: 1
name: string
steps: array of ProviderStep
expected_call_count: NonNegativeStrictInt
expected_final_outcome: "success" | "model_error" | "timeout" | "invalid_json"
expected_proposed_events: array of ProposedEvent
~~~

success step の形は次のとおりである。

~~~text
{
  "type": "success",
  "response": {
    "payload": SemanticResultV1,
    "usage": {
      "input_tokens": NonNegativeStrictInt,
      "output_tokens": NonNegativeStrictInt,
      "cached_tokens": NonNegativeStrictInt
    }
  }
}
~~~

non-success step は discriminated type に応じて次の JSON shape を使う。

~~~text
{"type": "model_error", "code": string, "message": string}
{"type": "timeout"}
{"type": "invalid_json", "body": string}
~~~

expected_proposed_events は raw dict の比較値ではなく、PROPOSED_EVENT_ADAPTER.validate_python(event_value, strict=True) を通した tuple[ProposedEvent, ...] である。expected_final_outcome は fixture の最終的な期待値であり、script_exhausted は fixture outcome の literal ではない。

### 5.2 実ファイル6件の対応

| 実ファイル | 実際の内容 | 期待値 |
|---|---|---|
| tests/fixtures/providers/normal-turn.v1.json | steps は success 1件。payload.proposed_events は ResourceChanged(resource:gold, entity:hero, delta: 2) 1件。usage は 12 / 8 / 0。 | expected_call_count: 1、expected_final_outcome: "success"、同じ ResourceChanged 1件。 |
| tests/fixtures/providers/retry-then-success.v1.json | model_error (code: "temporary_failure"、message: "upstream said: transient connection reset") の後に、normal-turn と同じ success。 | expected_call_count: 2、expected_final_outcome: "success"、proposed Event は1件。calls は failed → succeeded、Event materialization は成功時に一度だけ行う。 |
| tests/fixtures/providers/model-error.v1.json | model_error 1件。code: "upstream_unavailable"、message: "upstream said: connection reset by peer"。 | expected_call_count: 1、expected_final_outcome: "model_error"、proposed Event なし。 |
| tests/fixtures/providers/timeout.v1.json | timeout 1件。 | expected_call_count: 1、expected_final_outcome: "timeout"、proposed Event なし。 |
| tests/fixtures/providers/invalid-json.v1.json | invalid_json 1件。body: "not-json"。 | expected_call_count: 1、expected_final_outcome: "invalid_json"、proposed Event なし。成功 ModelResponse は作らない。 |
| tests/fixtures/providers/sanitized-call-log.v1.json | success 1件。Semantic Result は全配列が空、Narrative は空文字列。usage は 4 / 3 / 0。 | expected_call_count: 1、expected_final_outcome: "success"、proposed Event なし。sanitized log の固定値に使う。 |

上表は実際の tests/fixtures/providers/*.json の内容に基づく。fixture file と test-only の異常ケースを混同しない。

### 5.3 6 fixture 以外の test-only ケース

| ケース | 現在の表現 | 契約上の意味 |
|---|---|---|
| Narrative 差替え | tests/model/test_recorded_fixture.py の _normal_turn_variant が normal-turn の bytes を memory 上で変換し、narrative / narrative_plan だけを差し替える。別 JSON file はない。 | narrative_variant.events == base.events。Narrative は Event の入力にならない。proposed_event_delta の変更は Event を変える。 |
| Semantic schema 違反 | 現在の6 fixtureには専用の invalid-semantic JSON file はない。success payload は常に SEMANTIC_RESULT_ADAPTER.validate_json を通り、違反は success step として materialize しない。duplicate key と strict scalar の負例は test_recorded_fixture.py の in-memory bytes で検証する。 | raw mapping や invalid payload を ModelResponse.payload に保存しない。Semantic context の判定は validate_semantic_result に委譲し、AcceptedSemanticResult の場合だけ test-only materializer を呼ぶ。 |
| 未知 / 非公開 visibility | fixture ではなく test_provider_security.py::_visibility_facts と filter_context_by_visibility で検証する。player_visible は player fact のみ、gm_only は ()、npc:gareth は exact target のみ、npc:other は npc:gareth を含めない。 | publication target と Fact の visibility を完全一致させ、公開先に不可視 Fact を渡さない。production publication_visibility.py は作らない。 |
| 漏洩 sentinel | TOP_SECRET_SENTINEL は test memory 上の FactRecord.value にだけ注入する。JSON fixture、sanitized call log JSON、stdout、stderr、caplog には出さない。 | ModelRequest / sanitized log に secret field を設けない。テスト用 sentinel を Fixture に書き込まない。 |

この表の「専用 file はない」は欠落を隠すための表現ではない。P0-07 の6 fixture schema と test-only の異常注入を分離し、fixture corpus を raw secret や将来の全失敗 taxonomy で肥大化させないための明示的な境界である。

## 6. Typed validation と materialization の順序

Recorded Fixture は次の順序を変えない。

1. load_recorded_fixture(source: bytes) は type(source) is bytes を確認し、json.loads(source, object_pairs_hook=_reject_duplicate_object_keys) で duplicate object key を拒否する。
2. root は _require_object、steps と expected_proposed_events は _require_array で JSON object / array として確認する。array の順序と scalar type を変換しない。
3. 各 success step について response を object として取得し、payload JSON value だけを次で UTF-8 bytes 化する。

   ~~~python
   payload_bytes = json.dumps(
       response_document.get("payload"),
       ensure_ascii=False,
       separators=(",", ":"),
   ).encode("utf-8")
   semantic_payload = SEMANTIC_RESULT_ADAPTER.validate_json(payload_bytes)
   ~~~

   この呼び出しの戻り値は SemanticResultV1 であり、raw dict ではない。tuple-of-pairs root や raw mapping payload を ModelResponse.payload に保存しない。
4. typed semantic_payload を response document に戻し、PROVIDER_STEP_ADAPTER.validate_python(transformed_step, strict=True) で discriminated SuccessStep と ModelResponse を確定する。非-success step は raw step document を同じ adapter の strict=True で検証する。
5. expected_proposed_events の各要素を PROPOSED_EVENT_ADAPTER.validate_python(event_value, strict=True) で型化する。
6. 最後に RecordedFixtureV1.model_validate(transformed_document, strict=True) を通す。
7. provider success 後、test-only run_invocation_scenario は validate_semantic_result(response.payload, validation_context) を呼ぶ。AcceptedSemanticResult の場合だけ、その value を materialize_semantic_result_for_test(outcome, event_context) へ渡す。非 accepted outcome、failure、timeout、invalid JSON、script exhaustion では events == () とし、Provider が State を更新しない。

この順序により「JSON bytes → Schema-valid SemanticResultV1 → P0-04 Semantic validation → Accepted result → test-only Event materialization」が固定される。Narrative の自由文を状態へ直接流入させる段階はない。

## 7. Sanitization、digest、visibility、secrecy

### 7.1 固定された failure mapping

| step / 状態 | 公開 exception message | sanitized status | sanitized error_code |
|---|---|---|---|
| ModelErrorStep | RuntimeError("model invocation failed") | failed | model_error |
| TimeoutStep | TimeoutError("model invocation timed out") | timed_out | timeout |
| InvalidJsonStep | ValueError("model response JSON is invalid") | rejected | invalid_json |
| script exhaustion | RuntimeError("script exhausted") | rejected | script_exhausted |
| load_recorded_fixture の invalid source | ValueError("recorded fixture is invalid") | call log なし | provider invocation なし |

ModelErrorStep.code、ModelErrorStep.message、InvalidJsonStep.body、upstream の raw error は、exception message、sanitized call log、stdout、stderr、logging へ漏らさない。失敗時は ModelResponse と Event を返さない。

### 7.2 context digest

sanitize_provider_call_log(input_request, meta) は input_request.context の Fact だけを canonicalize し、次の順で digest を作る。

~~~python
context_json = [fact.model_dump(mode="json") for fact in input_request.context]
context_bytes = json.dumps(
    context_json,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
context_digest = hashlib.sha256(context_bytes).hexdigest()
~~~

期待値は production helper から生成せず、test の literal vector で固定する。

- 空 context の digest: 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
- event_id: "event:fact-source"、fact_id: "fact:" + 64 個の "a" + ":0"、visibility: "player_visible" 等を含む固定 preimage の digest: e88d0b92defd512874ef3955493bc82a3337ec983de178ac5f72c34c64d0ee55

上記の一件の Fact に対する test 側の canonical preimage は次の literal である。

~~~text
[{"event_id":"event:fact-source","fact_id":"fact:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:0","holder":"world","kind":"fact","predicate":"status","status":"active","subject_id":"entity:hero","value":"public","visibility":"player_visible"}]
~~~

model_call_id、turn_id、roles、publication_visibility は digest preimage に含めない。context の値を変えた場合だけ digest が変わり、request metadata だけを変えても digest は変わらない。context_digest は lowercase hex の LowercaseSha256 として検証する。

### 7.3 visibility filter は test-only

filter_context_by_visibility は次の完全一致だけを許す。

- publication_visibility == "player_visible": fact.visibility == "player_visible" の Fact だけ
- publication_visibility.startswith("npc:"): fact.visibility == publication_visibility の Fact だけ
- 上記以外（gm_only を含む）: ()

この関数は test の漏洩境界を検証するためだけに存在する。production Context Builder、visibility filter、Prompt builder の代わりに使わない。

### 7.4 secrets と raw observation

- ModelRequest.model_fields に api、key、secret、credential を含む field はない。
- sanitized log は request_id、attempt、publication visibility、digest、context item count、usage、status、error code のみを持つ。
- TOP_SECRET_SENTINEL は test memory に限定し、fixture bytes と call log JSON に保存しない。
- failure の raw code、body、message と raw error は公開境界へ渡さない。
- tests/test_no_external_network.py と全 session の _block_external_network は、外部 entrypoint（通常の
  `socket.connect` / `connect_ex` / `send` / `sendall` / `sendto`、`socket.getaddrinfo`、
  `socket.create_connection`、`http.client`、`urllib`、`httpx` の接続経路）を fail-fast にする。
  例外は、Windows の TestClient / ASGI が self-pipe / 内部 IPC に使う `socket.socketpair()` の生成と、
  その呼び出しで生成された endpoint 同士の `send` / `sendall` だけである。生成された endpoint は guard
  が識別したものに限り、通常の socket の `send` / `sendall`、`sendto`、外部接続、通常の
  `connect` / `connect_ex` は許可しない。これは外部 host への通信を許可する例外ではない。

## 8. Strict Pydantic 境界

P0-07 の contract model は ContractModel を基底にし、次の設定を全 nested model に適用する。

~~~text
strict=True
extra="forbid"
frozen=True
revalidate_instances="always"
~~~

具体的な固定事項は次のとおりである。

- NonNegativeStrictInt: input_tokens、output_tokens、cached_tokens、context_item_count、expected_call_count に使う。負数、bool、文字列数値を受理しない。0 は受理する。
- PositiveStrictInt: attempt に使う。0、負数、bool を受理しない。
- LowercaseSha256: context_digest に使う。uppercase hex、64文字未満、形式外の値を受理しない。
- extra="forbid": unexpected field を拒否する。
- frozen=True: 構築後の field assignment を拒否する。
- revalidate_instances="always": nested ModelUsage が model_copy(update={"input_tokens": -1}) のように壊されても、ModelResponse.model_validate(...) の境界で再検証して拒否する。
- PROVIDER_STEP_ADAPTER は Field(discriminator="type") で branch を決める。type のない任意 mapping を ProviderStep として受理しない。

model_construct、validation bypass の typing.cast、# type: ignore で production 境界を迂回しない。公開 contract の collection は tuple / frozenset 等の immutable collection を使い、raw mutable list / dict を外へ返さない。

根拠となる focused test は [tests/model/test_fake_provider.py](../../tests/model/test_fake_provider.py) の test_provider_contract_models_are_strict_immutable_and_revalidate_nested_models、test_model_invoker_public_contract_stays_narrow_and_discriminated、test_provider_call_log_meta_fields_are_typed、および [tests/model/test_provider_security.py](../../tests/model/test_provider_security.py) の strict counter / metadata tests である。

## 9. Test First、RED → GREEN、実行ゲート

### 9.1 Test First の実測手順と RED / Green

Test First の RED は、実装前 commit `a357d42` を `git archive` で一時ディレクトリへ展開し、
現行 repository の `.venv` Python をその一時 tree の working directory から呼び出す read-only 手順で
実測した。手順は `git archive a357d42` → `<temp>` へ展開 → current `.venv` の
`python -m pytest tests/model -q` である。

archive tree での実測結果は次のとおりである。

~~~text
pytest tests/model -q
（失敗一覧の各失敗は ModuleNotFoundError: No module named 'neontof.model'）
63 failed, 5 passed in 0.62s
exit 1
~~~

これは a357d42 archive での実測 RED であり、SyntaxError、collection error、0 tests はなかった。
5 passed は test-only / network / path 系である。production module 着地後の Green は別の現行 tree
で実行した結果として記録し、RED と混同しない。

現在 tree で RED を再実行していない。production module を削除・退避して archive 状態を再現することは
許可された scope 外であり、現行 tree の Green を RED evidence として扱えないためである。現行 tree の
Green は §9.3 の current-tree measurement として別に記録する。計画書 §13.6 の 39 tests / 6 fixtures
は設計時ラベルであり、a357d42 archive の RED 実測や現行 tree の Green 実測の代わりにはしない。

### 9.2 P0-07 focused / local gate

repository root で次を実行する。PowerShell の正式な local command は [docs/agent-guide/build-and-verify.md](../agent-guide/build-and-verify.md) に従う。

~~~powershell
.\\.venv\\Scripts\\python.exe -m pytest tests/model -q
.\\.venv\\Scripts\\python.exe -m pytest tests/test_no_external_network.py -q
.\\.venv\\Scripts\\python.exe -m pytest tests/test_no_external_network.py --setup-plan -q
.\\.venv\\Scripts\\python.exe -m compileall -q src
.\\.venv\\Scripts\\python.exe -m ruff format --check src tests
.\\.venv\\Scripts\\python.exe -m ruff check src tests
.\\.venv\\Scripts\\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
~~~

### 9.3 実測（2026-08-21）

次は、a357d42 archive での RED 実測と、現行 tree での Green / local gate 実測を分けた記録である。
計画書や過去の P0-01b 実測値を現在値として読み替えない。

| コマンド | 実際の出力 / 結果 |
|---|---|
| RED（a357d42 archive を一時展開し、current `.venv` Python で実行）: `pytest tests/model -q` | 失敗一覧の各失敗は `ModuleNotFoundError: No module named 'neontof.model'` / `63 failed, 5 passed in 0.62s` / exit 1。SyntaxError / collection error / 0 tests なし。5 passed は test-only / network / path 系。 |
| Green（現行 tree）: .\\.venv\\Scripts\\python.exe -m pytest tests/model -q | .................................................................... [100%] / 68 passed in 0.21s / exit 0 |
| .\\.venv\\Scripts\\python.exe -m pytest tests/test_no_external_network.py -q | ........ [100%] / 8 passed in 0.06s / exit 0 |
| .\\.venv\\Scripts\\python.exe -m pytest tests/test_no_external_network.py --setup-plan -q | SETUP S _block_external_network、8 test node、TEARDOWN S _block_external_network、no tests ran in 0.03s / exit 0（setup plan のため実行はしない） |
| .\\.venv\\Scripts\\python.exe -m compileall -q src | stdout なし / exit 0 |
| .\\.venv\\Scripts\\python.exe -m ruff format --check src tests | 52 files already formatted / exit 0 |
| .\\.venv\\Scripts\\python.exe -m ruff check src tests | All checks passed! / exit 0 |
| .\\.venv\\Scripts\\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures | Success: no issues found in 51 source files / exit 0 |
| 今回のレビュー時実測: .\\.venv\\Scripts\\python.exe -m pytest tests/contracts/test_semantic_result.py tests/model/test_recorded_fixture.py -q | 193 passed in 0.51s / exit 0 |
| 今回のレビュー時実測: .\\.venv\\Scripts\\python.exe -m pytest -q | 587 passed, 2 warnings in 3.00s / exit 0。warning は Starlette/httpx と Pydantic の既存 deprecation warning。 |
| 今回のレビュー時実測: required term `rg` scan（19 terms） | 全19 terms が exit 0。 |
| 今回のレビュー時実測: secret / sentinel、forbidden source pattern、bare `Hook` identifier、network source pattern の `rg` scan | secret / sentinel は exit 1（zero hits）、forbidden source pattern は全15 patterns が exit 1（zero hits）、bare `Hook` は exit 1（zero hits）、network source pattern は exit 1（zero hits）。 |

network guard の setup plan で確認した test node は test_external_connection_entrypoints_fail_fast、test_socket_methods_are_guarded_without_connecting、test_socket_getaddrinfo_is_guarded_without_resolving、test_socket_sendto_is_guarded_without_sending、test_socket_send_is_guarded_without_sending、test_socket_sendall_is_guarded_without_sending、test_http_client_connect_methods_are_guarded_without_connecting、test_socketpair_internal_send_methods_remain_allowed である。

この仕様書の実測では API key の値を表示していない。実 Provider、OpenAI SDK、外部 network は使用していない。remote CI の green はこの local output から推測しない。

## 10. 既知の境界と Phase 1 以降の判断

### 10.1 Phase 0 で固定したもの

- Fake / Scripted / Recorded Fixture の最小 test boundary
- ModelInvoker の一つの Callable と TestProvider Protocol
- ModelRequest、ModelResponse、ProviderStep、ProviderCallLogMeta、RecordedFixtureV1 の型と version 1 schema
- success payload の SEMANTIC_RESULT_ADAPTER.validate_json 境界、strict=True typed materialization の順序
- Semantic Result と Narrative の非対称性（Narrative は Event の権威でない）
- sanitized call log の field 集合、固定 exception message、error status / code
- canonical context digest と metadata 非依存性
- test-only visibility filter と「公開先へ不可視 Fact を渡さない」検証
- API key なし、network call 0、実 Provider なしの test / lint / type gate

### 10.2 Phase 1 以降に実装判断する予定物

- 実 Provider Adapter、OpenAI Responses API 等の mapping、SDK、model configuration、実費用の計測
- production Context Builder、visibility projection、Prompt / request composition
- retry runtime の policy、backoff、timeout、attempt budget、idempotency、failure Turn lifecycle
- Turn Engine、validated Event append、Event Store、State / Canon projection、永続 call log
- Transcript / Telemetry の transaction 外 append と cost accounting
- Secret Store、credential injection、runtime secret rotation
- SQLite schema / migration / connection ownership
- SemanticValidationOutcome の rejected case を専用 Recorded Fixture として増やすかどうか。現行6 fixtureには専用 file がなく、P0-04 の validation oracle が所有する。

### 10.3 Phase 1 の予定ではない禁止項目

Provider registry、Plugin、Hook、Profile、capability negotiation、capability registry は、Phase 1 の
予定へ自動的に持ち越さない。二つ目の具体実装と、それを必要とする実測が揃うまで、registry、Plugin
ABI、Hook、Profile、capability の一般化を作らない。必要性が確認された場合も、Phase 1 の予定へ黙って
追加せず、計画と境界を別途設計・承認する。

P0-07 完了後も、6 fixture の存在を実 Provider の互換契約、retry runtime の仕様、または production Event Store の代用とみなさない。Phase 1 の実装入口は、API key を公開向け request や通常 log に渡さないこと、typed validation を迂回しないこと、Event Log を唯一の状態権威とすることを再確認してから決める。§10.3 の禁止項目は、この実装入口へ自動的に含めない。

## 11. 参照と追跡表

| 判断 | 実装の根拠 | test の根拠 |
|---|---|---|
| 一つの narrow invocation boundary | src/neontof/model/model_invoker.py の ModelInvoker: TypeAlias = Callable[[ModelRequest], ModelResponse] | test_model_invoker_public_contract_stays_narrow_and_discriminated |
| typed Semantic Result | src/neontof/model/recorded_fixture.py の SEMANTIC_RESULT_ADAPTER.validate_json と PROVIDER_STEP_ADAPTER.validate_python(..., strict=True) | test_success_step_payload_is_semantic_result_model、test_json_bytes_preserve_array_order_and_scalar_types |
| Narrative 非権威 | run_invocation_scenario は accepted payload の materializer だけを呼ぶ | test_narrative_changes_never_change_materialized_events |
| failure redaction | fake_provider.py、scripted_provider.py、recorded_fixture.py の固定 exception / sanitized call | test_failure_mapping_is_fixed_and_redacted、test_failure_does_not_emit_raw_error_to_stdout_stderr_or_logs |
| call log の最小 field | sanitize_provider_call_log と SanitizedProviderCallLogEntry | test_sanitized_call_log_contains_only_safe_observation_fields、test_sanitize_provider_call_log_returns_only_safe_typed_fields |
| digest の決定性 | sanitize_provider_call_log の canonical JSON + SHA-256 | test_context_digest_matches_fixed_canonical_vector、metadata / context 差分 tests |
| visibility 非漏洩 | test-only filter_context_by_visibility.py | test_player_filter_returns_player_visible_facts_only、test_gm_only_is_never_selected_by_publication_filter、NPC exact-match tests |
| secret 非漏洩 | ModelRequest に secret field がなく、sanitized log に raw context がない | test_request_and_sanitized_log_never_carry_secret_fields_or_raw_secret、stdout / stderr / log tests |
| network call 0 | production model source に network client を持たず、session guard を有効にする | tests/test_no_external_network.py と _block_external_network の setup plan |

この文書の変更範囲は docs/specs/test-provider-and-fixtures.md だけである。実装、test、計画、ADR、docs/agent-guide は変更しない。
