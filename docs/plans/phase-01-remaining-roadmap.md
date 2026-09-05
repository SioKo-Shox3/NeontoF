# Phase 1 残作業の再分割とLocal Gateway実装計画

[Phase 1 First Playable Local Web Slice 詳細実装計画](./phase-01-first-playable-local-web-slice.md)

この文書は、Phase 1の未着手部分を一つの大きな実装単位で扱わず、依存関係が明確な一回のサイクルへ分けるための実行計画である。各フェーズは「計画 → 実装 → 検証 → コミット」を一回で完了させる。フェーズ内に別サイクルや途中のRED commitを入れない。詳細実装計画に残る各WPの契約、テスト名、完了履歴は参照情報として保持し、残作業の実行単位と依存順はこの文書で定める。

P1-11、P1-12、P1-13はこの文書の実装範囲に含めない。これらは後続の外部依存として、ここで定める契約を受け取る。Local Gatewayを完了しても、実Provider、HTTP経路、Scenario、Browser、complete runが完了したことにはならない。

## 共通制約

各フェーズでは、その節に列挙したpathだけを書き換える。列挙外のpathが必要になった場合は、変更せずに停止して判断を返す。特に次のpathは全フェーズで書き込み禁止である。

- `src/neontof/contracts/**`
- 既存の`src/neontof/model/model_invoker.py`
- 既存の`src/neontof/model/fake_provider.py`
- 既存の`src/neontof/model/recorded_fixture.py`
- 既存の`src/neontof/model/scripted_provider.py`
- 既存の`src/neontof/model/__init__.py`
- `tests/contracts/**`
- 既存の`tests/model/**`
- `docs/PRODUCT_PLAN.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/adr/**`
- `docs/specs/**`
- `.claude/**`、`.codex/**`、その他のハーネス
- `.env`

Event Logをゲーム状態の唯一の権威とし、Stateを直接更新する公開APIを作らない。State、Projection、public viewは検証済みEventから再構築する。TranscriptとTelemetryはEvent appendのtransaction外へ独立にappendし、失敗したTurnの観測記録と発生済み費用を消さない。Semantic Resultを検証してからpre-IDの候補を作り、Event ID、`OccurredAt`、`EventBatch`の構成とappendは既存のCoordinator経路に委譲する。自由文Narrativeをstate effectへ変換しない。

Local GatewayへAPI key、外部通信、SDK、具体的な実Provider、Provider registry、Plugin、第二のRuleset、二つ目の抽象化を追加しない。実Providerは別の承認済みフェーズでのみ扱う。`build_context`のcampaign Event列入力不足はこの計画で解消する。それ以外の実矛盾、禁止pathの必要性、同じ手法の失敗二回、2時間超過、台帳警告が発生した場合は、その場で停止する。

ロールバックは依存の逆順に`git revert`で行う。`git reset --hard`や`git checkout --`は使わず、EventやObservationを削除して整合を取らない。commit時は許可pathを明示してstageし、`git push`は行わない。

## 依存順と並列条件

サーバー側の残作業は次の順で進める。

```text
Local Gateway → Real Provider → Public Context → Semantic Effects
  → Response Recovery → Turn Pipeline
  → Provisional Detail（C-02承認時のみ）
  → 外部P1-12 → 外部P1-11 → Playable Client
```

C-02を延期する承認があった場合は、Turn Pipelineから外部P1-12へ直接進む。Client Foundation（旧P1-10a）は着地済みP1-00bに依存するだけで、サーバー側のpathや結果には依存しないため、Local Gateway以降のサーバー作業と並列に進められる。Playable Client（旧P1-10b）はClient Foundationと外部P1-11の両方が完了してから開始する。全体の受入れは外部P1-13が担当する。

`tests/test_repository_contracts.py`を変更するサーバー側フェーズは一つずつ実行する。前フェーズのfocused Gate、共通Gate、`git diff --check`、明示的なcommit、clean worktreeを確認してから次へ進む。Client Foundationはこの共有laneを変更せず、P1-00bのguardを利用する。

共通のPython Gateは、各フェーズのfocused commandに続けて次の順で実行する。利用できないコマンドや未確定のtoolchainを実行済みと記録しない。

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git diff --numstat
git diff --ignore-cr-at-eol --numstat
```

成功条件は、compileがexit `0`、formatが`files already formatted`、lintが`All checks passed!`、mypyが`Success: no issues found`、pytestのfailure/errorが`0`、行末差分がないことである。Client FoundationとPlayable Clientは、各節に記載するNode/Playwright Gateを使い、Python Gateを不要に追加しない。

## 1. Local Gateway（旧P1-06のFake / Recorded部分）

### 目的と依存

公開Context、player input、DiceをAPI keyなしで受け取るLocal Gatewayを作る。依存は着地済みのP1-03、P1-04、P1-05、承認済みQ1/Q2/Q3、およびC-03で確定した追加envelope方式である。ここで着地するのはFake / Recorded Fixtureを使うLocal Gatewayだけであり、P1-06全体とPhase 1全体の完了条件に含まれる実Providerは別フェーズで扱う。

### 許可path

作成するpathは次の6つである。

- `src/neontof/model/gateway_models.py`
- `src/neontof/model/gateway.py`
- `tests/model_gateway/test_gateway_budget.py`
- `tests/model_gateway/test_gateway_retry.py`
- `tests/model_gateway/test_gateway_security.py`
- `tests/model_gateway/test_gateway_fake_provider.py`

変更するpathは`tests/test_repository_contracts.py`だけであり、上記production 2 pathをexact manifestへ追加する。P0のProvider、loader、steps、既存model testは変更しない。

### 所有権と契約

`gateway_models.py`は、次の純粋な公開契約を所有する。各field shapeはP1-06の公開契約定義を正本とし、`application`や`web`をimportしない。

- `PublicInventoryItem`、`PublicStaticData`
- `PublicResourceCurrent`、`PublicResourceProjection`
- `PublicLocationProjection`、`PublicClockProjection`
- `PublicFactValue`、`PublicFact`とpredicate/value/holder/subject validator
- `ScenarioOutcome`、`ScenarioOutcomeFact`
- `PublicProjection`、`PublicContext`

`ContractModel`、ID型、Semantic Result、`ModelResponse`、`ProviderStep`、`RecordedFixtureV1`は既存の所有moduleからimportする。`TargetNumber`、`StatusCondition`、完全な`DiceResult`は`rules/minimal_2d6.py`から使う。`gateway.py`がGateway、envelope mapping、具体的なFixture adapterを所有し、P0のProvider型を再定義しない。

`SessionBudget`は`campaign_id`、`session_id`、`limit_microusd`、`input_microusd_per_million_tokens`、`output_microusd_per_million_tokens`、`cached_microusd_per_million_tokens`、`max_attempts: Literal[1] = 1`を持ち、金額と単価はstrictな非負整数にする。公開契約の中心は次のとおりである。

```python
class ProviderDiceResult(ContractModel):
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    formula: Literal["2d6"]
    result: Annotated[StrictInt, Field(ge=2, le=12)]

class GatewayRequest(ContractModel):
    turn_id: TurnId
    public_context: PublicContext
    player_input: StrictStr
    dice_result: DiceResult
    max_narrative_chars: PositiveStrictInt

class ProviderRequest(ContractModel):
    model_call_id: ModelCallId
    turn_id: TurnId
    roles: tuple[Role, ...]
    public_context: PublicContext
    player_input: StrictStr
    dice_result: ProviderDiceResult
    max_narrative_chars: PositiveStrictInt
    output_schema: Literal["semantic-result-v1"]

class GatewayFixtureCase(ContractModel):
    expected_request: ProviderRequest
    step: ProviderStep
```

`GatewaySuccess`は既存のsuccess/response shapeを保ち、`attempts: Literal[1]`とstrict非負の`cost_microusd`を返す。`GatewayFailure`は`budget_exceeded`、`timeout`、`model_error`、`invalid_json`の4 codeを保ち、`attempts: Literal[0, 1]`とする。validatorによりbudget超過は`0`、それ以外は`1`に固定する。

GatewayとFixture adapterのsignatureは次に固定する。

```python
def build_provider_request(
    *,
    request: GatewayRequest,
    model_call_id: ModelCallId,
) -> ProviderRequest: ...

class GatewayFixtureProvider:
    def __init__(self, *, cases: tuple[GatewayFixtureCase, ...]) -> None: ...

    def invoke(
        self,
        request: ProviderRequest,
        *,
        timeout_seconds: float,
    ) -> ModelResponse: ...

    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]: ...

def create_gateway_fake_provider(
    *,
    expected_request: ProviderRequest,
    step: ProviderStep,
) -> GatewayFixtureProvider: ...

def create_gateway_recorded_provider(
    *,
    expected_requests: tuple[ProviderRequest, ...],
    fixture: RecordedFixtureV1,
) -> GatewayFixtureProvider: ...

class ModelGateway:
    def __init__(
        self,
        *,
        provider: GatewayFixtureProvider,
        observations: ObservationStore,
        budget: SessionBudget,
        timeout_seconds: float,
    ) -> None: ...

    def invoke(self, request: GatewayRequest) -> GatewayOutcome: ...
```

`ProviderRequest`はPhase 1 adapterの最終受取り境界であり、P0 invocationへ情報を落とすmappingを作らない。`build_provider_request()`が、検証済みのpublic Context、player input、Dice、narrative上限に、server側の`model_call_id`、`turn_id`、固定roles、`output_schema`を加える。`ProviderDiceResult`へ写すのは`action_id`、`roll_index`、`formula`、`result`だけであり、`campaign_seed`、`derived_seed`、API keyなどを渡さない。player inputまたはDiceを無視した固定response、架空Factへ詰めるmapping、P0 `TestProvider.invoke()`への情報脱落は許可しない。

挙動は次の順で固定する。

1. `GatewayRequest`をstrictに再検証し、budgetとpublic Contextのcampaign/sessionを一致させる。
2. `ObservationStore.session_cost_microusd(campaign_id, session_id)`の累計がlimit以上ならproviderを呼ばない。call `0`、`attempts=0`、`model_call_id=None`、error Transcriptあり、attempt Telemetryなしとする。
3. provider call時だけ`ModelCallId`を`"model-call:" + sha256(request.turn_id.encode("utf-8")).hexdigest()`で作る。rolesは`("referee", "world_simulator", "npc_actor", "narrator")`、output schemaは`"semantic-result-v1"`に固定する。
4. Fixture adapterは次の完全な`expected_request`と実requestを照合してから`ProviderStep`を実行する。不一致またはcase枯渇は固定errorにする。Fakeは一件、Recordedは`expected_requests`とfixture stepsの同数case列を使い、両者を同じ具体adapterで交換できるようにする。
5. Success stepは既存`ModelResponse`を再検証し、timeout/model error/invalid JSONは既存の意味に対応する固定例外から、それぞれのGateway failureへ写す。raw error、cause、provider bodyは返さない。
6. `timeout_seconds`はfiniteかつ正であることを検証してadapterへ渡す。このフェーズでは`TimeoutStep`で確認し、実通信のdeadline/cancellationは実Providerフェーズで別途承認する。threadやworkerは作らない。
7. 通常Turnはlogical model call、provider invocationとも一回だけ、retryは0回とする。`max_attempts=1`を変更しない。
8. usageのinput/output/cached三値を保存し、costを`(input_tokens * input_rate + output_tokens * output_rate + cached_tokens * cached_rate + 999999) // 1000000`で計算する。Fixture境界のinput_tokensは非cached分と定義する。実Providerのusage正規化はReal Providerフェーズで確定する。fixture failureでusage不明ならusage/costは`0`とし、既存消費を減らさない。
9. request Transcriptはcontext digest、context item count、output schemaだけ、response Transcriptはdigest、長さ、提案件数だけ、error Transcriptはallowlistのerror code、digest、byte lengthだけを保存する。通常logへrequest全文、API key、secret、raw exceptionを出さない。
10. 同期invokeとObservationStoreだけを使う。EventStore、SQLite接続、application owner、独自lock、Gateway独自cacheは持たない。再実行抑止は既存Coordinatorに委譲する。
11. Gateway直前のrequestはpublic-onlyで、`gm_only`やその他の秘密を含まない。公開Diceは4 fieldだけを持ち、seedを含めない。

### テストと完了条件

テストは次の9名だけを既存pathへ追加し、新しいtest名やhelper fileを作らない。

- `tests/model_gateway/test_gateway_budget.py`
  - `test_budget_is_checked_before_first_attempt`
  - `test_success_records_usage_and_cost`
  - `test_failed_attempt_cost_is_not_rolled_back`
- `tests/model_gateway/test_gateway_retry.py`
  - `test_timeout_aborts_without_retry`
  - `test_model_error_aborts_without_retry`
  - `test_one_turn_uses_one_model_call_id`
- `tests/model_gateway/test_gateway_security.py`
  - `test_api_key_sentinel_never_reaches_request_response_or_log`
  - `test_provider_spy_receives_public_only_request_with_player_input_and_dice`
- `tests/model_gateway/test_gateway_fake_provider.py`
  - `test_recorded_fixture_can_replace_fake_provider`

`model_error`と`invalid_json`は`test_model_error_aborts_without_retry`のparameterizeで扱う。budget testではprovider call `0`、`attempts=0`、attempt Telemetry `0`を、呼出し系ではModelCallId `1`、provider call `1`、player input、Diceの4公開field、seed不在、異なるinput/Diceの不一致拒否を確認する。交換testではFakeとRecordedをAPI keyなし・network遮断下で同じadapterへ差し替える。P0のRecordedFixture loaderとstepsを再利用する。

実装前と完了時のfocused commandは次である。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/model_gateway tests/test_repository_contracts.py -q
```

実装前はmissing gateway moduleによるRED理由を確認し、Green後に上記commandと共通Python Gateを実行する。完了条件は次の証拠が全て成立することである。

```text
max_attempts_observed=1
logical_model_calls_per_turn=1
provider_invocations_per_turn=1
budget_checked_before_call=True
secret_hits=0
```

### 着地点

上記7 pathだけを明示してstageし、Fake/Recorded Local Gatewayのtestsとimplementationを一つのlogical GREEN commitへまとめる。

```powershell
git add -- src/neontof/model/gateway_models.py src/neontof/model/gateway.py tests/model_gateway/test_gateway_budget.py tests/model_gateway/test_gateway_retry.py tests/model_gateway/test_gateway_security.py tests/model_gateway/test_gateway_fake_provider.py tests/test_repository_contracts.py
```

```text
feat: 公開入力とDiceを受け取るLocal Gatewayを追加する
```

## 2. Real Provider（旧P1-06の残部）

### 目的と固定候補

Local Gatewayが受け取る完全な`ProviderRequest`を、Fake / Recordedと交換可能な一つの具体的なReal Providerへ渡す。接続方式はAPIだけに限定せずCLIを許容し、最初のadapter候補はCodex CLI `0.153.3`と`gpt-5.3-codex-spark`とする。Claude CLI/API（中国モデルを含む）は将来候補として残すが、今回第二Provider、registry、Plugin、汎用化は作らない。

P0の`ModelResponse`と公開`ProviderRequest`は変更しない。Providerへ渡すのは完全envelope内の公開Context、player input、公開Dice、call metadataだけであり、`campaign_seed`、`derived_seed`、API keyその他の秘密は渡さない。Provider共通型は次の最小契約だけを候補とし、既存の`GatewayFixtureProvider`とReal Provider adapterで共有する。

```python
class GatewayProvider(Protocol):
    def invoke(
        self,
        request: ProviderRequest,
        *,
        timeout_seconds: float,
    ) -> ModelResponse: ...
```

`ModelGateway`のproviderは`GatewayProvider`、budgetは`SessionBudget | SubscriptionBudget`へ限定して拡張する。`SubscriptionBudget`は`campaign_id`、`session_id`、`limit_calls=10`、`max_attempts=1`だけを持ち、金額単価0による無制限扱いを許さない。`cost_microusd`は追加従量課金であり、月額料金や契約枠消費とは別に扱う。追加課金0を確認できたsubscriptionだけ既存の整数`0`を使い、既存の成功Telemetry、SQL、金額sum型は変えない。追加課金、credit消費、自動fallbackが生じる場合は停止する。アプリの通常defaultは10 callsであり、実装前CLI調査に使うユーザー承認済みsubscription調査回数とは別である。調査ごとの再承認は要求しない。

### 呼出し境界、予約、CLI実証

provider呼出し前に、既存の`ObservationStore`へ一回分のsubscription callを原子的に予約する。候補APIのsignatureは次のとおりである。

```python
def try_reserve_subscription_call(
    self,
    campaign_id: CampaignId,
    session_id: SessionId,
    model_call_id: ModelCallId,
    limit_calls: int,
) -> bool: ...

def session_subscription_call_count(
    self,
    campaign_id: CampaignId,
    session_id: SessionId,
) -> int: ...
```

`try_reserve_subscription_call()`は既存の`session_cost_microusd(campaign_id, session_id)`と同じcampaign/session scopeで使用済み件数を確認し、上限未満なら現在の`model_call_id`を含む一枠を永続化して`True`、上限到達なら変更せず`False`を返す。`False`のときはproviderを呼ばない。同じ`ModelCallId`の実再呼出しも新しい一枠として数え、idempotent予約にしない。`session_subscription_call_count()`はcampaign/session単位の常に0以上の`int`を返す。check+insertはEvent transaction外の短い一つのSQLite transactionで行い、既存single-writer / `ObservationStore`の所有境界を守る。別connection/別DBは導入せず、失敗、timeout、session再起動でも予約を戻さない。予約tableは新規`0005_subscription_call_budget.sql`でCREATEだけを行い、既存migrationは変更しない。Transcript / Telemetryと同じ観測境界で失敗Turnの予約・費用を保持する。

Codex CLI候補はアプリケーションがshellを介さず公開promptをstdinへ渡し、CLI管理の認証だけを使う。アプリケーションは`auth.json`を読まず、API keyをBrowser、通常log、prompt、fixture、responseへ渡さない。次は実証対象の起動条件候補であり、未確認のoptionや設定を確定契約として扱わない。

```text
codex exec --ignore-user-config --ephemeral --json --output-schema ... --sandbox read-only --skip-git-repo-check
model: gpt-5.3-codex-spark
reasoning: low
application timeout: 60 seconds
retry: 0
destination: https://chatgpt.com/backend-api/codex/responses
```

送信先にはChatGPTのデータ設定を適用する。`--sandbox read-only`で読取toolを消せるか、`--ignore-user-config`でAGENTS、skills、MCP、hookを全て消せるか、built-in OpenAI providerのretry設定をoverrideできるかは未確認である。CLI process一回をmodel invocation一回と数えない。wrapper mock、JSONL turn event数、subprocess起動回数だけでは合格にしない。

実装前CLI実証は、ユーザーが承認済みのsubscription利用範囲で、秘密を含まない人工公開TRPG入力をCLIへ直接渡して行う。未実装の`SubscriptionBudget`、`0005_subscription_call_budget.sql`、ObservationStore予約APIは使わない。入口は、同じCLI version・起動条件について、CLI自身が受理した有効prompt/tool定義、実際に適用されたretry設定と起動コード、実通信のmodel request数とtimeout/model error時の失敗挙動を示す証跡である。少なくとも`全tool排除`、`非公開混入なし`、`モデル生成request=1`、`timeout/errorでもretry=0`を同じ条件で示せなければ、実装待機のままとする。未確認の設定や技術を確定条件として追記しない。

実装後アプリsmokeはCLI実証と分離する。初回smokeだけは`SubscriptionBudget(limit_calls=1)`を使い、最初の予約成功、失敗/timeout後の予約保持、DB/session再起動後の上限保持、上限到達時の変更なし・provider呼出しなしを確認する。Fake / Recorded / CIはAPI keyや外部networkを必須にしない。

### 一サイクルのpath、test、Gate

実装後のDoneに置くtestは次の5名だけとする。最初の3件はCLI実証とadapter境界、4件目と5件目はアプリsmoke/migrationを検証する。既存Local Gatewayのtest契約は変更しない。

- `test_codex_envelope_excludes_secrets_and_seeds`
- `test_codex_prompt_and_tools_are_isolated`
- `test_codex_single_invocation_and_no_retry`
- `test_subscription_limit_survives_failure_and_restart`
- `test_subscription_migration_preserves_existing_observations`

候補pathは次の12個である。この一覧は実装候補であり、アプリ実装・test・dependencyの着手許可ではない。Python依存は追加しない。

- `docs/plans/phase-01-first-playable-local-web-slice.md`
- `docs/plans/phase-01-remaining-roadmap.md`
- `src/neontof/model/gateway_models.py`
- `src/neontof/model/gateway.py`
- `src/neontof/model/codex_cli_provider.py`
- `src/neontof/persistence/observation_store.py`
- `src/neontof/persistence/migrations/0005_subscription_call_budget.sql`
- `tests/model_gateway/test_codex_cli_provider.py`
- `tests/model_gateway/test_gateway_budget.py`
- `tests/persistence/test_observation_store.py`
- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

候補pathは承認済みの実adapter code pathではない。exact adapter code path、依存、test path、staging範囲のapprovalは未取得であり、実装cycle開始時に確定する。実装前CLI実証で一回invocation・retryなしを証明できない、または既知未確認点が残る場合はadapter、test、migrationを作らない。Real Providerはこの一サイクルで完了させ、入れ子phaseを作らない。実装cycleのGateは次のfocused pytestと既存のcompileall、ruff、mypy、full pytestである。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/model_gateway tests/persistence/test_observation_store.py tests/persistence/test_migrations.py tests/test_repository_contracts.py
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
.\.venv\Scripts\python.exe -m pytest -q
```

この計画段階では新しいtestを作成・実行しない。Real Provider commit後に初めて旧P1-06全体を完了扱いにする。Local Gatewayの完了契約と次のPublic Context変更は維持する。

## 3. Public Context（旧P1-07）

### 目的と許可path

Real Providerのenvelope契約、P1-05のauthoring、`build_context`のEvent列入力修正を前提に、全campaign Event列から公開ProjectionとPublic Contextを作る。非公開Factを排除し、Evidence検証とstable IDのAlias解決を行う。

許可pathは次の6つである。

- `src/neontof/application/context_builder.py`
- `src/neontof/application/entity_resolver.py`
- `tests/application/test_context_builder.py`
- `tests/application/test_entity_resolver.py`
- `tests/integration/test_evidence_validation.py`
- `tests/test_repository_contracts.py`

純粋な公開契約はLocal Gatewayの`gateway_models.py`からimportし、`ApplicationRegistry`、`build_public_static_data()`、`build_context()`、`build_semantic_validation_context()`、public selector、Entity解決だけをこのフェーズのownerに残す。

### 完了条件

`build_context(*, projection, campaign_events, registry, publication_visibility)`は、同じcampaignの全validated Event tupleを受け、`rebuild_projection(campaign_events) == projection`を検証してから公開Contextを作る。不一致、Eventなしでprojectionだけが存在する入力、対象外の破損Eventを見落とす入力はfail-closedにする。公開Turn IDは最後の公開`PlayerInputAcceptedEvent`の`event.turn_id`と`event.payload.turn_request_id`を対で使い、該当Eventがなければ両方`None`とする。coordination record、request row、未appendの現在Turn IDは公開IDの根拠にしない。

`PublicFact`、`ScenarioOutcomeFact`、resource/location/clock projection、`PublicProjection`、`PublicContext`は公開可能な値だけをstrictに検証する。subjectなしの公開Factを落とさず、`gm_only`、不正predicate/value/holder/subject、複数active outcome、壊れたsourceを拒否する。AliasはUnicode NFKC、casefold、前後空白除去後のexact一致だけを使い、曖昧・未知を推測しない。

正本P1-07のfocused testと`tests/test_repository_contracts.py`を同じcommandで実行し、public-only、全Event列、projection一致、Event由来ID、invisible Evidence拒否、Aliasのstable ID、対象外Event破損のfail-closedを確認する。riskは高い。共通Python Gateを通過した後、次のcommitで着地させる。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_context_builder.py tests/application/test_entity_resolver.py tests/integration/test_evidence_validation.py tests/test_repository_contracts.py -q
```

```text
feat: Event由来の公開ContextとEvidence検証を追加する
```

## 4. Semantic Effects（旧P1-08の候補生成部分）

### 目的と許可path

Public Contextと、P0 payload boundaryの確認後に、schema/rule/evidence検証済みのSemantic ResultとDiceからpre-ID `PreparedEffect`候補を作る。DiceのEvent replayもこのフェーズで所有する。

許可pathは次の5つである。

- `src/neontof/application/event_materializer.py`
- `src/neontof/application/semantic_pipeline.py`
- `tests/application/test_event_materializer.py`
- `tests/application/test_semantic_pipeline.py`
- `tests/test_repository_contracts.py`

`DiceProjection`と`rebuild_dice_projection()`は`event_materializer.py`に置く。materializerとsemantic pipelineはEvent ID、`OccurredAt`、`EventDraft`、`EventBatch`、EventStore、append callerを持たず、current `TurnRequestIdentity`からpre-ID candidateのenvelopeだけを作る。target/conditionのFact candidateは既存のvalidatorを通し、target変更時は`FactSuperseded`を先に、`FactAsserted`を後に並べる。full Event replay以外のDice入力、filtered slice、snapshot、coordination record、observationは使わない。

正本P1-08のevent materializer/semantic pipeline focused setと共通Python Gateを通し、candidateのidentity一致、Dice replay、Narrative-only時のstate不変、invalid Event/Entityのappend前拒否、Event ID未採番境界を確認する。scenario endとscenario outcomeはこのcore candidate cycleへ持ち込まず、外部P1-12がTurn Pipelineへserialに追加する。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/test_repository_contracts.py -q
```

```text
feat: 検証済みSemantic Resultを未採番候補へ変換する
```

## 5. Response Recovery（旧P1-08の応答契約部分）

### 目的と許可path

Semantic Effectsに続き、initial/staged recovery payloadのstrict codec、`TurnResponseDocument`、normal/undo `ResponseRebuilder`を実装する。TurnCommand、TurnEngine、HTTP routeはこのフェーズに含めない。既存Coordinatorのcallback型へ適合させ、保存payloadをopaque bytesとして扱う層とdecodeする層を分ける。

許可pathは次の3つである。

- `src/neontof/application/turn_responses.py`
- `tests/application/test_turn_responses.py`
- `tests/test_repository_contracts.py`

`InitialRecoveryPayload`、`StagedResponseSeed`、`StagedRecoveryPayload`、`RecoveryPayload`、canonical UTF-8 codec、initial/staged builder、`TurnResponseDocument`、`ResponseDocumentBuilder`をここで所有する。strict/frozenなidentity・media・digestを検証し、duplicate key、trailing token、unknown field、改ざん、secret、raw provider body、Event-derived Projectionの重複保存を拒否する。normal committed/abortedはv2 staged payload、awaitingはv2優先またはv1 default、recovery-abortedは保存済みv1 initialを使う契約を保つ。

正本P1-08の`test_turn_responses.py` focused commandと共通Python Gateを通し、codecのcanonical bytes、改ざん拒否、staged presentation再利用、typed `TurnResponseDocument`、builder/serializer一回の境界を確認する。P1-08のresponse builderはfull Event tuple、rebuild済みProjection組、`DiceProjection`/`DiceResult`、validated presentation inputを受ける形へ合わせるが、`PublicSessionView`は作らない。riskは高い。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_turn_responses.py tests/test_repository_contracts.py -q
```

```text
feat: Turn応答の再構築と保存payloadのcodecを追加する
```

## 6. Turn Pipeline（旧P1-08の接続部分）

### 目的と許可path

Response RecoveryとSemantic Effectsのcommit後に、commandからclaim、bound preparation、Gateway、candidate validation、Coordinator、response rebuildまでを接続する。

許可pathは次の4つである。

- `src/neontof/application/turn_engine.py`
- `tests/integration/test_complete_fake_turn.py`
- `tests/integration/test_model_failure_atomicity.py`
- `tests/test_repository_contracts.py`

`TurnEngine.submit()`/`resume()`だけがcommandからserver-ownedなTurn ID、digest、immutable `TurnPreparationContext`、initial recovery payload、pre-claim intentを一度構成する。NewClaim後に一度だけ取得した全validated Event tupleをbound preparationへ渡し、`build_context`のprojection一致検証、Dice replay、pre-ID candidate確定、Gatewayへの`identity.turn_id`供給を行う。Gateway requestのTurn IDは`PublicProjection.turn_id`から取得せず、現在の呼出しメタデータとして別に渡す。現在IDのための先行appendを作らない。

append後response rebuildとreloadが使うEvent入力は、同じcampaign全体のvalidated tupleとrebuild済み`Projection`、`PublicProjection`、`PublicResourceProjection`、`DiceProjection`の組である。coordination recordやrequest rowを公開Projection IDの根拠にしない。Turn Pipelineのcore pathでは`scenario_end=None`、`scenario_outcome=None`とし、Scenario候補とsuccess/failure outcomeは外部P1-12へ渡す。

正本P1-08のfocused setと共通Python Gateを通し、failure時effect Event `0`、normal provider invocation `1`、retry `0`、interleaved input isolation、target/conditionの連続replay、v2 payloadの保存とrestart再利用、byte-for-byte response、Coordinatorだけのappend/complete caller境界を確認する。riskは高い。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py tests/test_repository_contracts.py -q
```

```text
feat: Turn PipelineをLifecycle Coordinatorへ接続する
```

## 7. Provisional Detail（旧P1-09、C-02承認時のみ）

C-02の明示承認がない間はwrite pathを空にし、`ProvisionalDetail`のID、Fact predicate/value schema、first-mentioned fixtureを決めない。承認内容が既存schemaや上位文書の変更を必要とする場合は停止し、承認なしに推測実装しない。C-02を延期する承認が確定した場合はこのフェーズを実行せず、Turn Pipelineから外部P1-12へ進む。

承認後にだけ許可する6 pathは次である。

- `src/neontof/application/provisional_details.py`
- `src/neontof/application/turn_engine.py`
- `tests/application/test_provisional_details.py`
- `tests/integration/test_provisional_detail_lifecycle.py`
- `tests/integration/test_complete_fake_turn.py`
- `tests/test_repository_contracts.py`

mentioned detailはNarrative parseではなくSemantic Resultから受け、current Sceneのactive Factだけをprojectionする。materialize/promotionはcurrent identityを使うpre-ID candidateだけを返し、P1-08のbound preparationへ合流してから一回だけEvent ID allocation、Factory、Coordinator appendへ進む。Scene終了後はContextから消えるがEventとTranscriptは保持する。P1-03のappend callerを増やさない。

正本P1-09 focused commandと共通Python Gateで、次Turn保持、明示参照による昇格、Scene終了後の非表示、Transcript保持、current identity不一致拒否、pre-ID合流を確認する。riskは高い。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py tests/integration/test_complete_fake_turn.py tests/test_repository_contracts.py -q
```

```text
feat: Event由来のprovisional detailをTurnへ接続する
```

## 8. Client Foundation（旧P1-10a）

P1-00bのrepository guardに依存する。サーバー側のpathや結果には依存せず、必要ならLocal Gateway以降と並列に一サイクルで着地させる。FastAPI readiness、`/health`、port `8765`はこのフェーズの条件にしない。

### 許可path

正本P1-10aの作成・変更pathである次の14 pathだけを許可する。

- `.node-version`
- `client/package.json`
- `client/package-lock.json`
- `client/tsconfig.json`
- `client/vite.config.ts`
- `client/index.html`
- `client/src/main.ts`
- `client/src/api.ts`
- `client/src/models.ts`
- `client/src/styles.css`
- `client/tests/scaffold.spec.ts`
- `client/playwright.config.ts`
- `.gitignore`
- `.github/workflows/ci.yml`

production Python、repository guard、server manifest、DB pathは変更しない。Vite、TypeScript、Playwright、Node、npmのversionはmanifestとinstall outputで確認できた値だけをpinする。

### 完了条件

Vite dev/previewのroot pageにinput、submit button、status regionのscaffoldを表示し、flatなsnake_case frame unionとexhaustive switchを用意する。次のGateを実行する。

```powershell
npm --prefix client ci
npx --prefix client playwright install chromium
npm --prefix client run typecheck
npm --prefix client run build
npm --prefix client run test -- scaffold.spec.ts
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

dev profileは`127.0.0.1:5173`、preview profileは`127.0.0.1:4173`を使い、PlaywrightのwebServerがreadinessとcleanupを行う。exit `0`、scaffold spec pass、guard pass、生成物をstatusへ残さないことを完了条件とする。riskは中程度である。

```text
feat: Viteとvanilla TypeScriptのClient scaffoldを追加する
```

## 9. Playable Client（旧P1-10b）

Client Foundationと外部P1-11の完了後に開始する。外部P1-11は外部P1-12後に着地するため、server manifestをこのフェーズで変更しない。

### 許可path

正本P1-10bの7 pathだけを許可する。

- `client/src/render.ts`
- `client/src/stream.ts`
- `client/src/retry.ts`
- `client/src/styles.css`
- `client/tests/session-view.spec.ts`
- `client/tests/reload.spec.ts`
- `client/tests/complete-run.spec.ts`

操作、processing status、SSE/buffered frame、StateFrameの表示、suggested action、target/condition/outcome、reload、同じrequest keyと`turn_request_id`による再送を実server契約で成立させる。Event由来のreload subsetを表示し、Event Logにないpresentation fieldsはtyped defaultまたは同じHTTP responseから渡されたpresentationを使う。API key、secret、raw provider response、full Projection、Transcript/TelemetryをlocalStorageへ保存しない。

次のGateを実行する。

```powershell
npm --prefix client run test
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

P1-11のFastAPI serverがreadiness `200`になってからPlaywrightを開始し、required DOM、Event由来reload/replay、SSE/buffered同値、secret sentinel不在、success/failure End表示を確認する。riskは中程度である。

```text
feat: Playable Clientとreload復元を実装する
```

## 外部依存とPhase 1受入れ

外部P1-12は、Scenario candidate、Clock、success/failure end、`ScenarioOutcomeFact`をTurn Pipelineのbound preparationへserialに統合する。外部P1-11は、composition root、HTTP route、SSEまたはbuffered serializer、P1-12後の`ScenarioRuntime`注入、Event-only reloadを実装する。外部P1-13はFake/Recordedまたは承認済み実Providerを通したcomplete run、人手playtest、status記録、Phase 1 Gateを担当する。この文書はこれらのpath、追加分割、commitを定義しない。

Fake-only、C-02未判断、complete run未実施、human playtest未実施、remote CI未確認の状態でPhase 1全体をPASSにしない。P1-06全体の完了には、Local Gatewayに加えてprovider approval済みの一つの具体的な実Provider adapterが必要である。remote CIの`pending / 未確認`はgreenやfailureへ読み替えず、Phase 1 Final Gateの判定を保留する。

最終受入れでは、EventとProjectionの再構築一致、failed TurnのTranscript/Telemetry保持、secret sentinel `0`、deterministic Dice、重複Requestのeffect count `1`、Browserからのsuccessまたはfailure End、playtest report、replay desire、Non-goal混入なしを外部P1-13で確認する。Phase 1上位Gateの条件は、正本に記載されたものから変更しない。
