# Phase 1: First Playable Local Web Slice Implementation Plan

**Goal:** localhost で Server を起動し、Browser だけで一人用 Scenario を開始から成功または失敗 End まで遊べる Vertical Slice を作る。

**Architecture:** Event Log をゲーム状態の唯一の権威とする。Turn Engine だけが検証済み Event を atomic appendし、State / Canon / provisional detail は Event から再構築する。Transcript / Telemetry と idempotency coordination はゲーム状態 transaction の外に置く。

**Tech Stack:** Python 3.14.3、FastAPI 0.141.1、Pydantic 2.13.4、Uvicorn 0.52.3、stdlib `sqlite3`、pytest 9.1.1、ruff 0.16.3、mypy 2.3.1、HTTP POST + SSE + buffered fallback。Vite、vanilla TypeScript、Playwright、Node、npmのversionはこの計画の時点で確認済みのRepository事実ではない。P1-10aのpackage manifest・lockfile・install/version outputで根拠が得られた値だけを採用し、既存ADRにないclient toolchainの固定はplan-level proposalとして扱う。

**Spec:** `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/0001-technology-stack.md`、Phase 0 の `docs/specs/**`、既存の `src/neontof/contracts/**` と `src/neontof/model/**` を再利用する。Phase 0 契約を暗黙に変更しない。

## Verification status at plan start

- Phase 0 local Gate: PASS相当。local `pytest`は`587 passed`相当、local `ruff`はPASS。
- Phase 0 remote CI: **failure**。`gh run 32474533578`は`completed failure`で、2026-08-21のremote `ruff check`が`tests/model/support/run_invocation_scenario.py`などのI001 5件でexit `1`となった。
- したがってremote状態はfailureとして記録する。Phase 1のlocal作業はlocal Entryを根拠に継続できるが、Phase 1のFinal Gateはremote failureを未解決のままPASSにしない。
- remote repair、status reportの書換え、pushはこの計画の作業に含めない。remote側の修復と結果の記録は別の承認済み作業とする。

## Global Constraints

- Event Log以外をゲーム状態の権威にしない。
- Stateを直接変更する public APIを作らない。
- LLMの自由文または Narrativeを parseしてEventへ変換しない。
- Semantic Resultのschema、reference、visibility、evidenceを検証してからEventへ変換する。
- Event batchは1回のSQLite transactionでappendし、失敗時に全件rollbackする。
- Transcript / TelemetryはEvent transactionの外へappendし、失敗Turnの記録と費用を消さない。
- 公開向けContextには`player_visible` Factだけを渡す。`gm_only`または他NPC専用Factを渡さない。
- API keyをBrowser、通常ログ、prompt、fixture、response、Transcriptへ渡さない。
- Diceは既存の次の関数だけからseedを導出する。

```python
def derive_dice_seed(
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: StrictInt,
) -> LowercaseSha256
```

- 通常Turnはprovider invocationを1回だけ行う。`max_attempts=1`、同じ`ModelCallId`のretryは0回とし、timeout/errorは記録してabortする。retryを無限にしないというRoadmapの上限を、Phase 1では「0 retry」と選択する。
- Fake / Scripted / Recorded Fixture経路を先に完成させる。
- 実Provider、API key、課金、外部networkは必須テストおよびCIの前提にしない。
- Phase 0の`Role`を変更しない。通常Fast Pathでは既存値だけを使う。

```python
Role = Literal["referee", "world_simulator", "npc_actor", "narrator"]
```

- Validatorは`validate_semantic_result()`などのコードとして扱う。
- DirectorはScene境界のorchestration conceptとして扱い、Phase 1ではdeterministicな`ScenarioRuntime`が担当する。`director`または`validator`を`Role`へ追加しない。
- 二つ目のProvider / Ruleset / Scenario形式、Provider registry、generic repository、Plugin、Hook、Profile、Manifestを作らない。
- 認証、Docker、公開Server、multiplayer、Search、Recall、Vector DB、Turn Planner、Character Creation UI、Scenario Editor、本格戦闘を実装しない。
- remote CIは**failure**であり、local PASSとは別に記録する。failureをgreenへ読み替えない。
- `git push`を実行しない。

---

## 1. Goal and Expected Behavior Change

Phase 0のread-onlyな契約とFake Provider基盤に対し、次のproduction behaviorを追加する。

1. `python -m neontof.main`でsingle-worker localhost Serverを起動する。
2. Browserから固定されたCharacter SheetとScenarioを読み込み、Campaign / Session / initial Sceneを開始する。
3. Player Inputを冪等に受理する。
4. deterministic 2d6判定、公開可能なFact Context、Fake Providerを用いてSemantic Resultを得る。
5. Semantic Resultを検証し、Eventへ変換してatomic appendする。
6. EventからState / Fact / Turn Status / provisional detailを再構築する。
7. Narrative、Suggested Actions、Location、HP、Resource、Inventory、Objective、Clock、Dice、Cost、Processing StatusをBrowserへ表示する。
8. validation済みresponseだけをSSEまたはbuffered JSONで公開する。
9. reload後に最後のEvent列から画面を復元する。
10. 成功または失敗Endまで通しプレイし、`docs/playtests/phase-01-first-complete-run.md`へ結果を記録する。

## 2. Explicit Non-goal

次は作成しない。

- 完全なRecall Gate、Summary、Search Index、Embedding、Vector DB
- 二つ目のProviderまたはProvider capability abstraction
- 二つ目のRuleset、Ruleset registry
- Turn Planner、Strict Path、複数quality mode
- Plugin、Hook、Profile、Manifest、Capability Graph
- 認証、Room、Participant、multiplayer
- Dockerfile、Compose、公開deployment
- Character Creation UI、Character編集UI
- Scenario Editor、汎用Scenario parser、Graph DSL
- WebSocket
- 本格戦闘、複雑な対抗判定
- 任意時点Undo、分岐save
- Sceneをまたぐprovisional detail保持
- API key入力画面
- 実ProviderをCI必須条件にすること

## 3. Entry Conditions

実装開始時に次を確認する。

```powershell
git branch --show-current
git rev-parse --short HEAD
git status --short
.\.venv\Scripts\python.exe -m pytest -q
```

期待証拠:

```text
feature/phase-01-local-web-slice
e2b72a9
```

計画ファイルがuntrackedの状態では、`git status --short`に`?? docs/plans/phase-01-first-playable-local-web-slice.md`が現れる。これはplan成果物の状態であり、Phase 0実装差分の証拠とは分ける。Phase 1実装へ移るEntryでは、planのcommit boundaryを確定した後、実装path以外の差分がないことを確認する。pytestはPhase 0 baselineの`587 passed`相当でexit `0`であること。件数はPhase 1 test追加後に増えるため、以後はexit `0`とfailure数`0`を判定基準にする。

Entry判定:

- Phase 0 Gate: local PASS
- Phase 0 remote CI: **failure** (`gh run 32474533578`, completed failure、remote ruff I001 5件、exit `1`)
- local Phase 1作業: 継続可。ただしremote failureをgreenとは扱わず、Final Gateで解消済みの証拠が得られるまでPhase 1 PASSを記録しない。
- Phase 1開始: ユーザー承認済み
- worktree: clean
- branch: `feature/phase-01-local-web-slice`
- push: 未承認

remote failureはPhase 1のlocal実装を止める理由にはしないが、Phase 0のremote GateをPASSへ読み替える理由にもならない。この計画はremote repair、remote status reportの変更、pushを行わない。

## 4. User-requested Phase Gate

### Correctness

- EventだけからStateとFactを再構築できる。
- Projection tableを削除して再構築しても同じJSONになる。
- Model failureでeffect Eventを残さない。
- Event batch途中のSQLite failureで全Eventをrollbackする。
- Transcript / Telemetryは失敗Turnにも残る。
- rollbackまたは`TurnReverted`でTelemetry費用が減らない。
- 記録にない過去を「未決定」として扱う。
- `gm_only` secretを公開Context、Browser response、Transcript、通常ログへ渡さない。
- Diceがseedを含めて再現できる。
- 同一`TurnRequestId`の再送でDice、model logical call、Eventを二重発生させない。
- NarrativeだけではStateが変化しない。
- API keyなし、外部networkなしでPython test、client build、browser integration testが通る。

### Experience

- BrowserだけでScenarioの成功または失敗Endへ到達できる。
- Location、HP、Resource、Inventory、Objective、Clock、Dice、Costを常時確認できる。
- Suggested Actionsを2〜4件表示する。
- submit直後にProcessing Statusを表示する。
- reload後に最後の状態または進行中Turnを表示する。
- ClockによりNPCまたは世界が能動的に変化する。
- 実装者が翌日もう一度遊びたいかを記録する。
- 再プレイしたくない場合、理由をfrequencyとseverityで分類する。

### Scope

- P1-06はFake / Recorded Fixtureに加えて、明示承認済みの具体的な実Provider adapterを1つだけ成果物にする。Fake-onlyはPhase 1完了ではない。
- Rulesetは`neontof-minimal-2d6-v1`だけ。
- Plugin、Profile、Search、Vector DB、認証、Docker、multiplayerが存在しない。
- Phase 2機能を先取りしていない。

## 5. Stop Conditions

次の場合はその場で停止し、修正またはユーザー判断を求める。

- Event append以外の経路からHP、Resource、Clock、Location、Factを変更する必要が生じた。
- current PhaseのEvent unionで必要なauthoritative stateを表せず、新Event typeが必要になった。
- `docs/specs/**`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/PRODUCT_PLAN.md`の変更が必要になった。
- `gm_only` sentinelが公開ContextまたはBrowser payloadへ1回でも現れた。
- Eventと再構築Projectionが一致しない。
- 同じRequest IDでDice、model call、Eventのいずれかが重複した。
- 通常Turnのprovider invocationまたは同じ`ModelCallId`のattemptが1回を超えた。
- budget checkより前にProviderを呼んだ。
- API keyまたは外部networkが必須testに必要になった。
- Provider名、SDK、key source、cost、destination、call上限の明示承認なしに実Provider adapterまたはexternal callを追加しようとした。
- C-03のProvider request boundaryが未承認のままP1-06 Fake/Recorded GatewayをGREENまたはcommit扱いにしようとした。また、provider approvalまたはC-03 plan amendment/re-reviewが未完了のまま、P1-06 concrete real Provider adapterまたはP1-07以降のprovider-dependent integrationをGREENまたはcommit扱いにしようとした。
- C-01、C-02、C-03、またはprovider approvalが未承認のまま、それぞれに依存するWPをGREENまたはcommit扱いにしようとした。
- Narrative自由文のparseがstate更新に必要になった。
- Scenarioが未実装機能へ依存した。
- C-01またはC-02 decision gateの承認なしに該当WPを開始しようとした。
- 同一手法の失敗が2回続いた。
- human playtestでScenarioを完走できない。
- Narrativeの大半を読み飛ばす、入力迷いが頻発する、NPCが待つだけになる。
- Phase Gate後にユーザー承認なしでPhase 2へ進もうとした。

### C-01 decision gate: Turn clarificationとmodel call上限

既存core/semantic contractの次の条件を同時に尊重する必要がある。

- Turn lifecycle Eventは、同一Turn内で`request_id`が一致する。
- `TurnAwaitingPlayer`から`TurnResumed`へは同じTurnで遷移できる。
- Semantic Resultの`clarification_request`は`Proposal`と同居できない。
- Phase 1通常TurnのModel call上限は1回である。
- Roadmap P1-08の成果物には`clarification_request`が含まれる。

この計画だけでは、model由来の`clarification_request`を同じTurnの意味ある完了結果へ進めながら、同じrequest ID、既存validator、1回のModel callを全て満たす実装方式を決められない。従って、pre-model ambiguityだけに限定したり、model由来clarificationをtestだけに追いやったりしてC-01を解消した扱いにしない。

P1-03およびP1-08の実装開始前に、次のいずれかをユーザーが明示承認するまで、C-01に関係する実装とその依存integrationを停止する。

1. **1回のModel callを維持する:** model由来`clarification_request`を同じTurnで完了させる仕様をPhase 1の受け入れ対象から外す。Roadmap P1-08との関係を上位文書で判断し、承認された対象だけを実装する。
2. **同じTurnでclarificationを完了する:** 2回目のModel callを許可し、通常Turnの1回制限・call count Gate・必要な上位契約を改訂する。既存文書の改訂なしには実装しない。
3. **clarificationをTurn境界で扱う:** `TurnAwaitingPlayer`後の入力を新しいTurnまたは別の明示的な契約として扱う。既存の同一Turn/request ID条件と両立するかを上位契約で判断し、承認されるまで実装しない。

各選択肢は、validator、request ID、Turn状態、Model call count、Roadmap成果物のいずれかへ影響する。承認前に既存Phase 0契約、Product Plan、Roadmapをこの計画から変更しない。C-01承認後だけ、P1-03/P1-08のtype、event sequence、test fixture、call-count testを承認内容に合わせて確定する。

---

## 6. Write Scope

### Allowed write paths

- `src/neontof/app.py`
- `src/neontof/config.py`
- `src/neontof/main.py`
- `src/neontof/application/**`
- `src/neontof/authoring/**`
- `src/neontof/model/gateway.py`
- `src/neontof/model/gateway_models.py`
- `src/neontof/observability/**`
- `src/neontof/persistence/**`
- `src/neontof/rules/**`
- `src/neontof/scenario_runtime.py`
- `src/neontof/web/**`
- `tests/application/**`
- `tests/authoring/**`
- `tests/integration/**`
- `tests/observability/**`
- `tests/model_gateway/**`
- `tests/persistence/**`
- `tests/rules/**`
- `tests/web/**`
- `tests/test_app.py`
- `tests/test_main.py`
- `tests/acceptance/phase_01_gate.py`
- `tests/acceptance/phase_01_fake_complete_run.py`
- `tests/fixtures/phase_01/**`
- `content/characters/phase-01-investigator.v1.yaml`
- `content/scenarios/phase-01-clocktower.v1.yaml`
- `client/**`
- `.node-version`
- `.gitignore`
- `.github/workflows/ci.yml`
- `requirements.in`
- `requirements-dev.in`
- `requirements.lock.txt`
- `docs/plans/phase-01-first-playable-local-web-slice.md`
- `docs/playtests/phase-01-first-complete-run.md`
- `docs/status/phase-01-first-playable-local-web-slice.md`

### Forbidden write paths

- `AGENTS.md`
- `CLAUDE.md`
- `.claude/**`
- `.codex/**`
- `.harness/**`
- `docs/agent-guide/**`
- `docs/PRODUCT_PLAN.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/adr/**`
- `docs/specs/**`
- `docs/status/phase-00-foundation.md`
- `src/neontof/contracts/**`
- 既存の`src/neontof/model/fake_provider.py`
- 既存の`src/neontof/model/model_invoker.py`
- 既存の`src/neontof/model/recorded_fixture.py`
- 既存の`src/neontof/model/scripted_provider.py`
- `tests/contracts/**`
- 既存の`tests/model/**`
- `.env`
- `*.sqlite`
- `*.db`
- `client/node_modules/**`
- `client/dist/**`

禁止pathの変更が必要になった場合は実装せずStop Conditionとして報告する。

---

## 7. Ownership, Lifetime, Threading, Dependency Direction

### Ownership and lifetime

- `SqliteDatabase`はdatabase pathとwrite serialization lockだけを所有する。
- `sqlite3.Connection`は各operation内で生成・使用・closeし、object fieldへ保存しない。
- `EventStore`だけがDomain Event tableをappendする。
- `ProjectionStore`はEventを読み、削除可能なprojection snapshotだけを置換する。
- `ObservationStore`はTranscript / Telemetryだけをappendする。
- `TurnRequestStore`はHTTP requestの重複実行を防ぐoperational recordを所有する。ゲーム状態のProjection入力にはしない。
- `TurnEngine`がEvent appendを呼べる唯一のapplication serviceである。
- FastAPI routeはHTTP validation、application call、frame serializationだけを担当する。
- Browserはserverが返したpublic viewだけを保持し、秘密、DB、API keyを持たない。

### Threading

- Uvicornは`workers=1`を維持する。
- FastAPI route、SSE generator、threadpool間でConnectionを共有しない。
- SQLite writeは`threading.Lock`と`BEGIN IMMEDIATE`で直列化する。
- readはoperationごとに別Connectionを開く。
- model invocationは同期boundaryとして扱い、SSEのasync generatorから`asyncio.to_thread()`で呼ぶ。
- Diceはlocal `random.Random` instanceだけを使い、global random stateを変更しない。
- Event sequenceはwrite transaction内で現在の最大sequenceを確認して採番競合を拒否する。

### Dependency direction

```text
client
  → HTTP/SSE contracts

src/neontof/web
  → src/neontof/application
  → existing src/neontof/contracts

src/neontof/application
  → persistence
  → rules
  → authoring
  → model/gateway
  → existing contracts/model contracts

persistence / rules / authoring / gateway
  → existing contracts

existing contracts
  → no Phase 1 modules

production code
  → never imports tests
```

`ProjectionStore`から`EventStore.append()`を呼ばない。`ModelGateway`から`EventStore`を呼ばない。`ScenarioRuntime`は未採番`EventDraft`または`EventBatch`を返し、Stateを直接更新しない。

---

## 8. Dependency and Parallel Execution Plan

### Batch 0 — neutral Event metadata prerequisite

P1-00を最初に着地させる。これはPhase 1 plan内のneutral contract landing unitであり、Roadmapの新しい成果物や上位文書の変更ではない。Event draft、batch metadata、Turn lifecycle metadataの型を`src/neontof/persistence/event_metadata.py`に置き、P1-03/P1-04/P1-08がApplication固有の未定義型へ依存しないようにする。

### Batch A — Batch 0後に互いに独立

次はwrite pathが互いに素で、結果依存がないため1バッチで並列実行できる。

- P1-01a: SQLite owner、migration、Event Store
- P1-04a: deterministic 2d6 rules（P1-00のneutral metadataだけを参照し、Application metadataには依存しない）
- P1-05a: Character / Scenario YAML loader
- P1-10a: Vite client scaffold
- P1-12a: First Scenario / Character content

### Batch B — Batch A後、互いに独立

- P1-01b: Projection Store
- P1-02: Transcript / Telemetry Store
- P1-04b: HP / Resource / Clock rule validation
- P1-05b: bootstrap Event normalization
- P1-10b: static UI components

### Sequential integration chain

```text
P1-00
  → P1-01 + P1-04 + P1-05 + P1-10a
P1-01 + P1-02 + C-01 approval
  → P1-03
P1-03 + P1-05 + C-03 approval
  → P1-06 Fake/Recorded Gateway（normal invocation 1、zero retry、C-03 contract approved）
P1-06 Fake/Recorded GREEN + Provider approval + C-03 plan amendment/re-review
  → P1-06 concrete real Provider adapter 1つ
P1-06 concrete real Provider adapter path確定 + P1-05
  → P1-07
P1-07 + C-01 approval
  → P1-08
P1-08 + C-02 approval
  → P1-09
P1-09 + P1-12 runtime
  → P1-11
P1-11 + P1-10a
  → P1-10b
P1-10b + P1-12
  → P1-13
```

Fake / Recordedのlocal validationはprovider approval前も続けてよいが、concrete real Provider adapterなしでFinal GateをPASSにしない。

P1-12 content validationはP1-05a完了後に実行する。P1-12 runtime behaviorはP1-09完了後に統合する。

P1-10aはP1-11のFastAPI、health、readiness、static routeに依存しない。P1-10aはViteのdev/preview serverだけでclient scaffoldを検証し、P1-11のserver lifecycle GateはP1-11以降で初めて要求する。P1-10bのBrowser integrationはP1-11のserver contractとP1-10aのclient scaffoldが揃ってから開始する。

レビューを通過したcommitは、依存する次WP開始前に着地させる。異なるBatchの未コミットdiffを混ぜない。

### WP landing contract

各WPは、`Test First`のREDを実際に記録し、同じWPの最小実装だけでfocused commandをGREENにし、そのWPに列挙したpathだけを明示的に`git add -- <path...>`して着地させる。依存WPの開始条件は、そのcommitのfocused command、関係するquality gate、`git diff --check`、scope確認が全てGREENであることとする。Batch Aを並列に進める場合も、各workerは自分のWPのpathだけをstageし、他WPのdiffを同じcommitへ混ぜない。

`git add -A`、`git add .`、`git push`は禁止する。各WPの明示的なstaging pathとfocused commandは本計画末尾のCommit Boundary Summaryに固定する。未確認の依存、契約判断、provider選択が見つかったWPはGREENやcommitを偽装せず、該当Stop Conditionで停止する。

---

# 9. Work Packages

## P1-00: Neutral Event Draft and Metadata Contracts

**Create**

- `src/neontof/persistence/event_metadata.py`
- `tests/persistence/test_event_metadata.py`

P1-00はP1-01、P1-03、P1-04、P1-08、P1-09、P1-12が共有するneutral locationであり、Application固有のmetadataをEvent StoreやRulesへ逆向きに導入しない。Eventのsequenceはここでも呼び出し側でも割り当てない。`EventDraftBody`は未採番候補のneutral bodyであり、既存parserによるstrictな`DomainEvent`再構築・再検証はEvent Store内だけで行う。`DomainEvent`をproducerの返却型にしない。

**Public types and signatures**

```python
class EventAppendMetadata(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    occurred_at: OccurredAt

class EventDraftBody(ContractModel):
    event_id: EventId
    event_version: Literal[1]
    type: StrictStr
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    occurred_at: OccurredAt
    origin: StrictStr
    visibility: Visibility
    payload: FrozenJsonValue

class EventDraft(ContractModel):
    body: EventDraftBody

class EventBatch(ContractModel):
    campaign_id: CampaignId
    drafts: tuple[EventDraft, ...]

class StoredEvent(ContractModel):
    campaign_id: CampaignId
    sequence: int
    event: DomainEvent

class TurnEventMetadata(EventAppendMetadata):
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    root_turn_request_id: TurnRequestId
    event_ids: tuple[EventId, ...]

class RevertEventMetadata(EventAppendMetadata):
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    event_ids: tuple[EventId, ...]

class EventMaterializationInput(TurnEventMetadata):
    pass
```

`EventDraftBody.payload`は既存Event parserが受け付ける未採番候補の`FrozenJsonValue`に限る。producerはpayloadを`DomainEvent`へ先にcast/constructせず、EventStoreがbody全体をstrict再検証してから採番済み`DomainEvent`を生成する。

`TurnEventMetadata.turn_request_id`は、同じTurnに属する`PlayerInputAccepted`、`TurnAwaitingPlayer`、`TurnResumed`、`TurnCommitted`、`TurnAborted`の全てへ渡すcanonical request IDである。`TurnAwaitingPlayer`から`TurnResumed`へ進む場合も`turn_id`と`turn_request_id`は同じであり、別のTurnや別のlifecycle request IDを作らない。HTTPの重複排除keyは`TurnRequestStore`の外部coordination recordにだけ保存する。

`EventStore.append(batch: EventBatch) -> tuple[StoredEvent, ...]`はP1-00で定義した未採番`EventDraft`だけを受け付ける。transaction内で現在の最大sequenceの次から連番を割り当て、各draft bodyを既存のDomainEvent parser/validationへ通して再構築・再検証し、`StoredEvent`（採番済み`DomainEvent`を含む）としてinsertして返す。sequenceの取得・連続性検証・全draftの再検証・insertは同一write transaction内で行い、別のpublic `next_sequence()`を持たない。`SqliteDatabase`はpath、write serialization lock、connection lifecycle、migrationだけを所有し、generic public `write(Callable[[Connection], T])`を公開しない。Observation / Request storeはそれぞれのtableだけを対象に自分のtransactionを持ち、Event Log appendを呼ばない。

**Test First**

- `test_event_batch_has_no_caller_assigned_sequence`
- `test_event_draft_body_has_only_unassigned_domain_event_fields`
- `test_event_draft_wraps_neutral_body_without_domain_event`
- `test_turn_event_metadata_is_neutral_and_reusable`
- `test_revert_event_metadata_is_defined_before_use`
- `test_event_materialization_input_has_no_application_dependency`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_event_metadata.py -q
```

期待REDはmissing moduleまたは未定義metadata型である。0 testやcollection errorだけをRED証拠にしない。

**GREEN**

focused commandがexit `0`となり、metadata moduleが`application`、`rules`、`model`、`web`をimportせず、sequenceをcallerから受け取らないことをassertする。

**Commit boundary**

```powershell
git add -- src/neontof/persistence/event_metadata.py tests/persistence/test_event_metadata.py
```

Test FirstのREDは未コミット証拠として残し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめ、`feat: Event draftとmetadataのneutral契約を固定する`として着地させる。

## P1-01: Event Store and Projections

### P1-01 preflight — sqlite source-scan policy stop

Phase 1のpersistenceは既存のsqlite source scanと衝突する可能性がある。`docs/agent-guide/**`は直接編集禁止であり、scanを通すために現行ガイドへ例外を追記してはならない。

P1-01aの最初のfile edit前に、orchestratorはMyWorkflow正本のallowlist/deploy手順、または現行ガイドが定める許可方式を確認し、sqlite usageをallowlistへ反映する正しい経路と証拠を確定する。この確認ができない、またはガイド直接編集が必要ならP1-01aを停止し、ユーザー判断を求める。remote repairやpushで代替しない。

policy確認とPhase 1 local scanを混同しない。許可方式が確定した後のlocal scanは、次の対象だけを検査する。

```powershell
rg -n "sqlite3|SqliteDatabase|\.sqlite|\.db" src/neontof/persistence tests/persistence
```

このcommandはPhase 1 persistenceの実使用箇所を表示するlocal evidenceであり、MyWorkflowのallowlist/deploy確認の代替ではない。source scanのpolicy resultが未確認のままP1-01aをGREENにしない。

### P1-01a — SQLite schema and atomic Event Store

**Create**

- `src/neontof/persistence/__init__.py`
- `src/neontof/persistence/sqlite_database.py`
- `src/neontof/persistence/migrations.py`
- `src/neontof/persistence/migrations/0001_phase_1.sql`
- `src/neontof/persistence/event_store.py`
- `tests/persistence/test_migrations.py`
- `tests/persistence/test_event_store.py`

**Public types and signatures**

```python
T = TypeVar("T")

class SqliteDatabase:
    def __init__(self, path: Path) -> None: ...
    def migrate(self) -> None: ...
    def read(self, operation: Callable[[sqlite3.Connection], T]) -> T: ...
    def _open_connection(self) -> sqlite3.Connection: ...

class EventStore:
    def __init__(self, database: SqliteDatabase) -> None: ...
    def append(self, batch: EventBatch) -> tuple[StoredEvent, ...]: ...
    def read_campaign(self, campaign_id: CampaignId) -> tuple[DomainEvent, ...]: ...
    def read_session(
        self,
        campaign_id: CampaignId,
        session_id: SessionId,
    ) -> tuple[DomainEvent, ...]: ...
    def read_turn(
        self,
        campaign_id: CampaignId,
        turn_id: TurnId,
    ) -> tuple[DomainEvent, ...]: ...
    def find_turn_by_request(
        self,
        campaign_id: CampaignId,
        turn_request_id: TurnRequestId,
    ) -> tuple[DomainEvent, ...]: ...
```

`EventStore`だけが`DomainEvent`をEvent Logへappendする。`append(batch)`は未採番`EventDraftBody`を全draftについて既存parser/`revalidate_domain_event()`へ通してstrictに再構築・再検証し、同一Campaign、context整合性、unique Event IDを確認する。sequenceは同じ`BEGIN IMMEDIATE` transaction内で次値から連番割当し、採番済み`DomainEvent`を`StoredEvent`へ包んでinsert・返却する。callerへsequence取得APIを公開しない。`SqliteDatabase`のconnection lifecycleを使う各storeは、自分が所有するtableのwrite transactionだけを実行する。
`read_campaign()`、`read_session()`、`read_turn()`、`find_turn_by_request()`のread-sideは既存どおり`DomainEvent`列を返す。neutral draft化の対象はproducer/append境界だけで、Projection/Event read側の入力契約は変更しない。

`0001_phase_1.sql`は次のtableを作る。

- `schema_migrations`
- `events`
- `projection_snapshots`
- `turn_requests`
- `transcript_entries`
- `telemetry_entries`

`events`のprimary keyは`(campaign_id, sequence)`、`event_id`はunique、`event_json`はcanonical JSONとする。`PlayerInputAccepted`行の`turn_request_id`へpartial unique indexを付ける。

**Test First**

先に次を追加する。

- `test_append_persists_events_in_sequence`
- `test_append_rolls_back_every_event_when_second_insert_fails`
- `test_sequence_is_allocated_inside_append_transaction`
- `test_read_filters_campaign_session_and_turn`
- `test_duplicate_event_id_leaves_database_unchanged`
- `test_connection_is_not_reused_across_operations`
- `test_event_store_has_no_public_next_sequence`
- `test_sqlite_database_has_no_generic_public_write`
- `test_migration_is_idempotent`
- `test_schema_version_is_one`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_event_store.py -q
```

期待RED:

```text
ERROR ... ModuleNotFoundError: No module named 'neontof.persistence'
```

または、module skeleton着地後はatomicity testが`2 != 0`で失敗すること。collection errorや0 testはRED証拠にしない。

**GREEN**

同じcommandがexit `0`となり、全testが`passed`、failure `0`。rollback testのrow countが`0`、成功batchのrow countが期待件数と一致し、caller側にsequence割当やgeneric public writeが存在しないこと。

**Commit boundary**

```powershell
git add -- src/neontof/persistence/__init__.py src/neontof/persistence/sqlite_database.py src/neontof/persistence/migrations.py src/neontof/persistence/migrations/0001_phase_1.sql src/neontof/persistence/event_store.py tests/persistence/test_migrations.py tests/persistence/test_event_store.py
```

Test FirstのREDは未コミット証拠として残し、focused testとsqlite policy確認がGREENになった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: append-onlyなSQLite Event Storeと原子性を実装する
```

Acceptance evidence:

- 故意に2件目を失敗させたbatch後のEvent件数`0`
- 同じEvent列のread結果が入力順と一致
- public State update methodが存在しない

### P1-01b — Projection snapshot and rebuild

**Create**

- `src/neontof/persistence/projection_store.py`
- `tests/persistence/test_projection_store.py`

**Public types and signatures**

```python
class ProjectionSnapshot(ContractModel):
    campaign_id: CampaignId
    through_sequence: int
    projection: Projection

class ProjectionStore:
    def __init__(
        self,
        database: SqliteDatabase,
        event_store: EventStore,
    ) -> None: ...
    def rebuild(self, campaign_id: CampaignId) -> ProjectionSnapshot: ...
    def read(self, campaign_id: CampaignId) -> ProjectionSnapshot | None: ...
    def delete(self, campaign_id: CampaignId) -> None: ...
```

`rebuild()`は既存の次をそのまま呼ぶ。

```python
def rebuild_projection(events: Sequence[DomainEvent]) -> Projection
```

Projection tableはderived cacheであり、`delete()`はEventを削除しない。

**Test First**

- `test_delete_projection_does_not_delete_events`
- `test_rebuild_after_delete_returns_identical_projection`
- `test_snapshot_through_sequence_matches_event_log`
- `test_projection_store_has_no_state_mutation_method`
- `test_reverted_turn_is_removed_after_rebuild`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_projection_store.py -q
```

期待REDは`ModuleNotFoundError: No module named 'neontof.persistence.projection_store'`。実装途中は`AttributeError`で`rebuild`が無いこと。

**GREEN**

全testがpassし、delete前後の`projection.model_dump_json()`がbyte-for-byte一致すること。

**Commit boundary**

```powershell
git add -- src/neontof/persistence/projection_store.py tests/persistence/test_projection_store.py
```

Test FirstのREDは未コミット証拠として残し、P1-01aのcommitとsqlite policy/local scanがGREENで、delete/rebuild/reverted-turn focused commandがfailure `0`になった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Eventから再生成できるProjection Storeを追加する
```

---

## P1-02: Transcript and Telemetry Stores

**Create**

- `src/neontof/observability/__init__.py`
- `src/neontof/observability/records.py`
- `src/neontof/observability/sanitization.py`
- `src/neontof/persistence/observation_store.py`
- `tests/observability/test_sanitization.py`
- `tests/persistence/test_observation_store.py`
- `tests/integration/test_failed_turn_observations.py`

**Public types and signatures**

```python
TranscriptKind = Literal[
    "player_input",
    "model_request",
    "model_response",
    "narrative",
    "error",
    "retry",
    "correction",
]

class TranscriptRecord(ContractModel):
    entry_id: TranscriptId
    campaign_id: CampaignId
    session_id: SessionId | None
    turn_id: TurnId | None
    model_call_id: ModelCallId | None
    kind: TranscriptKind
    occurred_at: OccurredAt
    data: FrozenJsonValue

class TelemetryRecord(ContractModel):
    entry_id: TelemetryId
    campaign_id: CampaignId
    session_id: SessionId
    turn_id: TurnId
    model_call_id: ModelCallId
    provider: str
    model: str
    roles: tuple[Role, ...]
    attempt: int
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    latency_ms: int
    cost_microusd: int
    error_code: str | None
    occurred_at: OccurredAt

def sanitize_observation(value: FrozenJsonValue) -> FrozenJsonValue: ...

class ObservationStore:
    def __init__(self, database: SqliteDatabase) -> None: ...
    def append_transcript(self, record: TranscriptRecord) -> None: ...
    def append_telemetry(self, record: TelemetryRecord) -> None: ...
    def read_transcript(
        self,
        campaign_id: CampaignId,
        turn_id: TurnId | None = None,
    ) -> tuple[TranscriptRecord, ...]: ...
    def read_telemetry(
        self,
        campaign_id: CampaignId,
        turn_id: TurnId | None = None,
    ) -> tuple[TelemetryRecord, ...]: ...
    def session_cost_microusd(self, session_id: SessionId) -> int: ...
```

`sanitize_observation()`はkey名が`api_key`、`authorization`、`token`、`secret`に一致する値を`"[REDACTED]"`へ置換する。invalid raw model bodyは保存せず、digest、byte length、sanitized error codeだけを保存する。

`ObservationStore.append_transcript()`と`append_telemetry()`はEvent Log appendとは別のwrite transactionで、自分のobservation tableだけを書き込む。失敗Turnの観測記録とcostはEvent rollbackや`TurnReverted`で消さず、`EventStore.append()`、`TurnRequestStore`、Observation Storeのownershipを混ぜない。

**Test First**

- `test_player_input_is_retained_when_turn_fails`
- `test_timeout_records_transcript_and_telemetry_with_zero_events`
- `test_turn_revert_does_not_reduce_session_cost`
- `test_api_key_named_fields_are_redacted_recursively`
- `test_raw_invalid_model_body_is_not_persisted`
- `test_observation_types_cannot_be_appended_to_event_store`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/observability tests/persistence/test_observation_store.py tests/integration/test_failed_turn_observations.py -q
```

期待REDはmissing moduleまたはtimeout integrationのTranscript件数`0`に対する`1`期待失敗。

**GREEN**

- timeout後のEvent count `0`
- Transcriptに`player_input`と`error`
- Telemetryに`timed_out`
- session costはrevert前後で同値
- secret sentinel hit `0`

**Commit boundary**

```powershell
git add -- src/neontof/observability/__init__.py src/neontof/observability/records.py src/neontof/observability/sanitization.py src/neontof/persistence/observation_store.py tests/observability/test_sanitization.py tests/persistence/test_observation_store.py tests/integration/test_failed_turn_observations.py
```

Test FirstのREDは未コミット証拠として残し、P1-00/P1-01のEvent ownershipと独立したobservation focused commandがfailure `0`になった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: TranscriptとTelemetryをEvent transaction外へ保存する
```

---

## P1-03: Turn State Machine

**Create**

- `src/neontof/application/__init__.py`
- `src/neontof/application/turn_models.py`
- `src/neontof/application/turn_lifecycle.py`
- `src/neontof/persistence/turn_request_store.py`
- `tests/application/test_turn_lifecycle.py`
- `tests/persistence/test_turn_request_store.py`
- `tests/integration/test_turn_idempotency.py`

**Public types and signatures**

```python
RequestExecutionStatus = Literal[
    "processing",
    "awaiting_player",
    "committed",
    "aborted",
]

class CachedTurnResponse(ContractModel):
    status_code: int
    media_type: Literal["application/json", "text/event-stream"]
    body: str

class TurnRequestRecord(ContractModel):
    request_key: str
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    status: RequestExecutionStatus
    response: CachedTurnResponse | None

class RequestClaim(ContractModel):
    type: Literal["new", "existing"]
    record: TurnRequestRecord

class TurnRequestStore:
    def __init__(self, database: SqliteDatabase) -> None: ...
    def claim(
        self,
        *,
        request_key: str,
        turn_request_id: TurnRequestId,
        campaign_id: CampaignId,
        session_id: SessionId,
        scene_id: SceneId,
        turn_id: TurnId,
        root_turn_request_id: TurnRequestId,
        input_digest: LowercaseSha256,
    ) -> RequestClaim: ...
    def complete(
        self,
        request_key: str,
        status: RequestExecutionStatus,
        response: CachedTurnResponse,
    ) -> TurnRequestRecord: ...
    def read(self, request_key: str) -> TurnRequestRecord | None: ...

def build_started_events(
    *,
    metadata: TurnEventMetadata,
    input_digest: LowercaseSha256,
) -> EventBatch: ...

def build_awaiting_event(
    *,
    metadata: TurnEventMetadata,
) -> EventBatch: ...

def build_committed_event(
    *,
    metadata: TurnEventMetadata,
) -> EventBatch: ...

def build_aborted_event(
    *,
    metadata: TurnEventMetadata,
    reason: Literal["failed", "cancelled", "table_correction"],
) -> EventBatch: ...

def build_revert_event(
    *,
    metadata: RevertEventMetadata,
    target_turn_id: TurnId,
) -> EventBatch: ...

def build_crash_recovery_batch(
    *,
    record: TurnRequestRecord,
    turn_events: Sequence[DomainEvent],
) -> EventBatch: ...
```

`project_turn_status()`を変更せずreuseする。Event-derived `TurnStatus`がゲーム状態の権威であり、`TurnRequestStore`はHTTPの重複排除、processing claim、cached responseだけを持つ外部coordination recordで、Event Projectionへの入力にしない。

`PlayerInputAcceptedEvent`、`TurnAwaitingPlayerEvent`、`TurnResumedEvent`、`TurnCommittedEvent`、`TurnAbortedEvent`は、同じTurnなら全て`TurnEventMetadata.turn_request_id`をそのまま使う。`TurnAwaitingPlayer → TurnResumed`は同じ`turn_id`、同じcanonical `turn_request_id`であり、resume HTTPの新しい`request_key`はcoordination recordにだけ保存する。

同一`request_key`の`claim()`は既存recordを返し、cached responseがあれば`status_code`、`media_type`、UTF-8 canonical JSON/SSE `body`をbyte-for-byteで返す。Dice、Provider、Event appendは再実行しない。`scene_id`と`input_digest`はclaim時に保存し、同じcanonical `turn_request_id`のrecoveryへ渡す。`processing` recordの再送は、既存のTurn status parserのEvent順序で再構築したstatusを使い、次のrecovery ruleに従う。

- Event-derived statusに`TurnCommitted`または`TurnAborted`が既にあれば、Event / Projectionからresponseを再構築して一度だけcacheし、Providerを再呼出ししない。
- claim後の最初のEventがまだ無く、Event Logに同Turnの`PlayerInputAccepted`が無ければ、`TurnRequestRecord`の`campaign_id`、`session_id`、`scene_id`、`turn_id`、canonical `turn_request_id`、`input_digest`から`PlayerInputAccepted` draftを作り、その直後に`TurnAborted(reason="failed")` draftを置いた同一`EventBatch`をappendする。部分的な再実行やprovider retryは行わない。
- terminal Eventが無く、Event Logに同Turnの`PlayerInputAccepted`が既にあれば、recordのcanonical `turn_request_id`に一致する許可済みの`TurnAborted(reason="failed")` draftだけを同一batchへ置いてappendする。`PlayerInputAccepted`を二重作成しない。
- `TurnResumed`後のrunning crash windowはEvent-derived statusがrunningであることを確認して`TurnAborted`だけをappendする。`TurnAwaitingPlayer`後はawaiting responseを再構築してcacheし、入力を勝手にabortまたは再送しない。terminal後は既存terminal responseを再構築してcacheし、Eventを追加しない。
- `TurnAwaitingPlayer`のcached responseはそのまま返す。ユーザー入力を続けるresumeは同じTurnのcanonical request IDをLifecycle Eventへ渡し、外部dedupe用に新しい`request_key`を使う。

`build_started_events()`は、`PlayerInputAccepted` draftと`TurnResumed` draftを同じ`EventBatch`へ順序どおりに置き、両方のcanonical `turn_request_id`と`input_digest`を検証する。`build_awaiting_event()`とterminal builder、`build_crash_recovery_batch()`も同じmetadataと既存status parserの許可された遷移だけを使う。Request storeのwriteはEvent Storeのappend transactionとは別であり、Turn statusのauthorityではない。

**Test First**

- `test_new_request_is_claimed_once`
- `test_duplicate_processing_request_returns_existing_record`
- `test_duplicate_committed_request_returns_cached_response`
- `test_cached_response_replays_status_media_type_and_body_exactly`
- `test_ambiguous_input_enters_awaiting_player_without_effect_events`
- `test_resume_uses_same_turn_id`
- `test_resume_uses_same_canonical_turn_request_id`
- `test_processing_crash_recovers_without_provider_reinvocation`
- `test_claim_before_first_event_recovers_with_accepted_then_aborted_batch`
- `test_crash_after_player_input_accepted_appends_only_authorized_abort`
- `test_crash_after_turn_started_uses_event_derived_running_status`
- `test_crash_after_terminal_replays_terminal_without_append`
- `test_crash_after_awaiting_player_rebuilds_awaiting_response`
- `test_recovery_uses_existing_turn_status_parser_order`
- `test_processing_replay_with_committed_event_caches_rebuilt_response`
- `test_latest_committed_turn_can_be_reverted`
- `test_non_latest_turn_cannot_be_reverted`
- `test_duplicate_request_rolls_dice_once`
- `test_duplicate_request_invokes_model_once`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_turn_lifecycle.py tests/persistence/test_turn_request_store.py tests/integration/test_turn_idempotency.py -q
```

期待REDはmissing module、またはduplicate requestでcall count `2`に対し`1`期待の失敗。

**GREEN**

同じRequestを2回送ったfixtureで次が成立する。

```text
model_logical_calls=1
dice_rolls=1
player_input_accepted_events=1
turn_committed_events=1
```

recovery testでは、claim-before-first-eventが`PlayerInputAccepted`→`TurnAborted`の2 draftを1 batchでappendし、after-accepted/after-startedは`TurnAborted`だけ、after-`TurnAwaitingPlayer`はawaiting responseのcache、after-terminalはEvent追加なしとなる。各分岐は`TurnRequestStore.status`ではなく既存のEvent-derived status parserの順序とcanonical `turn_request_id`で決める。

**Contract checkpoint**

C-01 decision gateがユーザー承認済みでない場合、P1-03の実装を開始しない。follow-up requestを新しい`PlayerInputAcceptedEvent`として暗黙に追加したり、model由来clarificationをpre-model ambiguityへ置き換えたりしない。承認後も、選択された契約に一致するEvent sequence、request ID、call count testだけを実装し、Phase 0 contractをこの計画から変更しない。

**Commit boundary**

```powershell
git add -- src/neontof/application/__init__.py src/neontof/application/turn_models.py src/neontof/application/turn_lifecycle.py src/neontof/persistence/turn_request_store.py tests/application/test_turn_lifecycle.py tests/persistence/test_turn_request_store.py tests/integration/test_turn_idempotency.py
```

Test FirstのREDは未コミット証拠として残し、C-01 decision gate承認後に上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Request IDで直列化するTurn状態機械を追加する
```

---

## P1-04: Minimal Rules and Dice

**Create**

- `src/neontof/rules/__init__.py`
- `src/neontof/rules/minimal_2d6.py`
- `tests/rules/test_minimal_2d6.py`
- `tests/rules/test_rule_effect_validation.py`

**Public types and signatures**

```python
class DiceResult(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: int
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: int

class PublicDiceView(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: int
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: int

class ResourceLimit(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    minimum: int
    maximum: int

class RuleValidationIssue(ContractModel):
    path: str
    code: Literal["out_of_bounds", "unsupported_formula", "unknown_resource"]
    message: str

def resolve_2d6(
    *,
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: int,
) -> DiceResult: ...

def validate_resource_changes(
    *,
    projection: Projection,
    proposals: Sequence[ProposedResourceChanged],
    limits: Sequence[ResourceLimit],
) -> tuple[RuleValidationIssue, ...]: ...

```

`resolve_2d6()`は`derive_dice_seed()`を呼び、そのdigestから生成したlocal `random.Random`だけを使う。LLMが返したdice値、Eventに存在しないmodifier、target、dice tuple、success flagはauthoritative stateにしない。`DiceResult`は既存`DiceRolledPayload`のauthoritative fieldsだけを表し、Event materializationとreplay projectionはP1-08で行う。P1-04はrulesとdeterminismだけを担当し、`TurnEventMetadata`、`EventMaterializationInput`、Application runtimeへ依存しない。

HPは`resource:hp`、Character Sheetの1資源はその既存`ResourceId`として扱う。状態異常やNPC noticeのFact predicateはPhase 1では許可せず、Inventoryだけを`inventory_item`、Clockは既存`ClockAdvanced`として扱う。新しいRuleset interfaceを作らない。

**Test First**

- `test_same_inputs_produce_same_seed_and_dice`
- `test_different_roll_index_changes_seed`
- `test_global_random_state_does_not_affect_result`
- `test_result_is_between_two_and_twelve`
- `test_resource_change_cannot_cross_zero_or_maximum`
- `test_rules_module_does_not_import_application_metadata`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/rules -q
```

期待REDはmissing module。skeleton後は再現性testで異なるdiceとなる失敗。

**GREEN**

全test pass。固定fixtureを2回実行した`derived_seed`、`formula`、`result`が一致し、resultはEventのauthoritative fieldsだけから再計算可能である。

**Commit boundary**

```powershell
git add -- src/neontof/rules/__init__.py src/neontof/rules/minimal_2d6.py tests/rules/test_minimal_2d6.py tests/rules/test_rule_effect_validation.py
```

Test FirstのREDは未コミット証拠として残し、P1-00のneutral metadataを除くApplication依存がないことを確認した後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: 再現可能な最小Rulesetと資源境界を実装する
```

---

## P1-05: Character and Scenario Loading

### Dependency update

`PyYAML==6.0.3`を`requirements-dev.in`から`requirements.in`へ移す。production Character / Scenario loaderがYAMLを読むためである。`types-PyYAML`は`requirements-dev.in`に残す。`requirements.lock.txt`をhash付きで再生成する。他のPython dependencyを追加しない。

**Create**

- `src/neontof/authoring/__init__.py`
- `src/neontof/authoring/yaml_loader.py`
- `src/neontof/authoring/character_loader.py`
- `src/neontof/authoring/scenario_loader.py`
- `src/neontof/authoring/bootstrap.py`
- `tests/authoring/test_yaml_loader.py`
- `tests/authoring/test_character_loader.py`
- `tests/authoring/test_scenario_loader.py`
- `tests/authoring/test_bootstrap_events.py`

**Modify**

- `requirements.in`
- `requirements-dev.in`
- `requirements.lock.txt`

**Public types and signatures**

```python
def load_yaml_document(path: Path, *, max_bytes: int = 1_048_576) -> dict[str, object]: ...

def load_character_sheet(path: Path) -> CharacterSheetV1: ...

def load_scenario(path: Path) -> ScenarioV1: ...

class BootstrapInput(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    campaign_seed: LowercaseSha256
    campaign_name: str
    session_title: str
    character: CharacterSheetV1
    scenario: ScenarioV1

def build_bootstrap_events(
    input_value: BootstrapInput,
    *,
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
) -> EventBatch: ...
```

### Phase 1 input, ID, Fact, and authority contract

P1-05は既存の`ScenarioV1`と`CharacterSheetV1`をloaderの入力型として使う。versionはそれぞれ既存contractの`version` fieldと、Phase 1 contentの`v1` filename/IDで固定し、bootstrapで別のad hoc JSON schemaを作らない。

Bootstrapで使用するstable IDは次のnamespaceと対応規則を持つ。

- `campaign_id`、`session_id`、`scene_id`、`turn_id`、`turn_request_id`: `BootstrapInput`から受け取り、display nameから生成しない。
- Scenario: `scenario:phase-01-clocktower`、Scene: ScenarioV1が定義するversioned scene ID。
- Character: CharacterSheetV1が定義するcharacter IDを`entity:character-<slug>`へ対応させる。
- NPC: ScenarioV1が定義する全4件のNPC IDを`entity:npc-<slug>`へ対応させる。
- Location: ScenarioV1が定義する全5件のLocation IDを`entity:location-<slug>`へ対応させる。
- Clue: ScenarioV1が定義する全3件のClue IDを`entity:clue-<slug>`へ対応させる。
- Clock: ScenarioV1が定義する唯一のClock IDをそのまま登録する。初期currentが`0`でもknown clock registryへ必ず入れる。

`<slug>`はV1 documentに明示されたstable IDであり、loaderがdisplay nameから暗黙生成しない。missing、duplicate、version不一致のIDはbootstrap前にrejectする。

Phase 1のFactは既存`FactRecord`のsubject/predicate/value/visibility/source Event schemaを使い、次のpredicateだけを許可する。`kind`、`holder`、`subject_id`のnullable/required、value shape、visibility、sourceを表のとおり固定し、任意のdict、display name、未定義のidentifier namespaceをvalueにしたad hoc JSONは拒否する。`subject_id`が`None`のpublic FactもPublicContextへ保持する。

| predicate | kind | holder | subject_id | exact value shape | visibility | source |
|---|---|---|---|---|---|---|
| `inventory_item` | `fact` | `player_character` | required: character `EntityId` | stable `ItemId` | `player_visible` | `CharacterSheetV1.inventory`からbootstrapした`FactAsserted` |
| `objective` | `fact` | `world` | nullable (`None`) | `SceneId` strict value object | `player_visible` | `ScenarioV1.initial_scene.id`からbootstrapした`FactAsserted` |
| `location` | `fact` | `player_character` | required: character `EntityId` | stable `LocationId` | `player_visible` | `CharacterMoved` Event |
| `clue` | `fact` | `world` | nullable (`None`) | stable clue `EntityId` | `player_visible` | `ScenarioV1.clues`とvalidated `FactAsserted` |
| `scenario_version` | `fact` | `world` | nullable (`None`) | `ScenarioV1.version`のstrict string | `player_visible` | `ScenarioV1.version`からbootstrapした`FactAsserted` |
| `character_version` | `fact` | `player_character` | required: character `EntityId` | `CharacterSheetV1.version`のstrict string | `player_visible` | `CharacterSheetV1.version`からbootstrapした`FactAsserted` |

`condition`と`npc_notice`はPhase 1許可predicateから外す。必要になった場合は上位契約の判断が完了するまで停止し、別のidentifier namespaceやpredicateをこの計画から発明しない。ObjectiveのFact valueは`ScenarioV1.initial_scene.id`の`SceneId`とし、表示textはFact valueへ入れず、`ScenarioV1.initial_scene.objective.text`をP1-07のtyped `PublicStaticData`から読む。

authoritative sourceは次のとおりである。

- HP maxと初期HP、resource maxと初期resourceはCharacterSheetV1のresource定義からbootstrapする。currentの以後の値はEvent-derived Projectionだけをauthorityとする。
- Objectiveのauthoritative valueは`ScenarioV1.initial_scene.id`の`SceneId`であり、表示textは同じScenarioV1の`initial_scene.objective.text`をtyped `PublicStaticData`から読む。clock maxとend conditionはScenarioV1のversioned definitionから読む。clock currentはEvent-derived Projectionで、初期値`0`をbootstrap規約とする。
- success/failure EndはScenarioV1の既存end condition定義だけを`ScenarioRuntime`が評価する。Model、Narrative、Factの自由文をauthoritative sourceにしない。
- CharacterSheetV1/ScenarioV1のversionとstable IDはloaderが検証し、bootstrap Eventのmetadataへversionを埋め込む場合も既存Event schemaのfieldだけを使う。

YAML loaderはUTF-8 BOMなし、duplicate mapping key拒否、`yaml.safe_load`相当のsafe constructor、size limitを強制する。任意Python object constructorを許可しない。

Bootstrapは既存Eventだけを使う。

- `CampaignCreated`
- `SessionStarted`
- `SceneStarted`
- bootstrap用`PlayerInputAccepted`
- bootstrap用`TurnResumed`
- HP currentとResource currentの`ResourceChanged`
- initial locationの`CharacterMoved`
- clock initialが正数の場合の`ClockAdvanced`
- Character / Scenario metadataの`FactAsserted`
- `TurnCommitted`

Character、NPC、Location、Clueはdeterministicな対応Entity IDへ正規化する。

```text
character:<slug> → entity:character-<slug>
npc:<slug>       → entity:npc-<slug>
location:<slug>  → entity:location-<slug>
clue:<slug>      → entity:clue-<slug>
```

Secretは`FactAsserted.visibility="gm_only"`、公開情報は`player_visible`とする。speech styleの不可視部分をpublic Contextへ渡さない。

**Test First**

- `test_loader_rejects_duplicate_yaml_keys`
- `test_loader_rejects_unknown_fields`
- `test_loader_rejects_non_utf8`
- `test_loader_rejects_document_over_size_limit`
- `test_character_loader_returns_character_sheet_v1`
- `test_scenario_loader_returns_scenario_v1`
- `test_bootstrap_uses_only_existing_domain_event_types`
- `test_bootstrap_returns_unassigned_event_batch`
- `test_bootstrap_events_rebuild_initial_hp_resource_location_and_clock`
- `test_bootstrap_secret_fact_is_gm_only`
- `test_mutating_yaml_result_cannot_mutate_contract`
- `test_bootstrap_batch_is_atomic`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring -q
```

期待REDはmissing module。bootstrap skeleton後はProjectionのHP / location / secret Fact不足でassertion failure。

**GREEN**

全test pass。bootstrap Event列を`rebuild_projection()`へ渡し、Character current HP、Resource、Location、Clock、Scenario ID、Scene ID、Factが期待値と一致する。

**Lock command**

`docs/agent-guide/build-and-verify.md`のcanonical fresh TEMP venv手順を使い、次の入力からlockを再生成する。

```powershell
$env:CUSTOM_COMPILE_COMMAND = "py -3.14 -m piptools compile --generate-hashes requirements-dev.in"
& $lockPython -m piptools compile `
  --generate-hashes `
  --output-file requirements.lock.txt `
  requirements-dev.in
```

生成後:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
```

期待GREEN:

```text
No broken requirements found.
```

**Commit boundary**

```powershell
git add -- src/neontof/authoring/__init__.py src/neontof/authoring/yaml_loader.py src/neontof/authoring/character_loader.py src/neontof/authoring/scenario_loader.py src/neontof/authoring/bootstrap.py tests/authoring/test_yaml_loader.py tests/authoring/test_character_loader.py tests/authoring/test_scenario_loader.py tests/authoring/test_bootstrap_events.py requirements.in requirements-dev.in requirements.lock.txt
```

Test FirstのREDは未コミット証拠として残し、上記pathのtestsとimplementation、依存更新を1つのlogical GREEN commitへまとめ、ScenarioV1/CharacterSheetV1 input、stable ID、Fact schema、bootstrap clock/authority、fresh lock install、focused authoring commandを確認して着地させる。

```text
feat: CharacterとScenarioをEventへ正規化する
```

---

## P1-06: Model Gateway

**Create**

- `src/neontof/model/gateway_models.py`
- `src/neontof/model/gateway.py`
- `tests/model_gateway/test_gateway_budget.py`
- `tests/model_gateway/test_gateway_retry.py`
- `tests/model_gateway/test_gateway_security.py`
- `tests/model_gateway/test_gateway_fake_provider.py`

**Public types and signatures**

```python
class SessionBudget(ContractModel):
    session_id: SessionId
    limit_microusd: int
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int
    cached_microusd_per_million_tokens: int
    max_attempts: Literal[1] = 1

class GatewayRequest(ContractModel):
    public_context: PublicContext
    player_input: str
    dice_result: DiceResult
    max_narrative_chars: int

class GatewaySuccess(ContractModel):
    type: Literal["success"]
    response: ModelResponse
    attempts: int
    cost_microusd: int

class GatewayFailure(ContractModel):
    type: Literal["failure"]
    code: Literal[
        "budget_exceeded",
        "timeout",
        "model_error",
        "invalid_json",
    ]
    attempts: Literal[1]

GatewayOutcome = GatewaySuccess | GatewayFailure

class ModelGateway:
    def __init__(
        self,
        *,
        provider: TestProvider,
        observations: ObservationStore,
        budget: SessionBudget,
        timeout_seconds: float,
    ) -> None: ...

    def invoke(self, request: GatewayRequest) -> GatewayOutcome: ...
```

`ModelGateway`のcallerは完成済みのmodel requestを渡さず、`GatewayRequest`の`public_context`、`player_input`、Event-derived `dice_result`、`max_narrative_chars`だけを渡す。秘密を含まない最終provider requestへのenvelope/mappingは、C-03で承認された境界だけが担当する。C-03承認前に既存P0 provider invocation shapeへ暗黙にmappingしたり、P0型やForbidden pathをこの計画から変更したりしない。

通常Turnの`ModelRequest.roles`は次に固定する。

```python
("referee", "world_simulator", "npc_actor", "narrator")
```

1 Turnに1つの`ModelCallId`だけを発行し、provider invocationを1回だけ行う。`max_attempts=1`でretryは0回とする。budgetはその1回の前に確認し、timeout/errorはTelemetryとTranscriptへ記録してabortする。費用は整数`cost_microusd`で計算し、失敗後にrollbackしない。Roadmapの「無限retryしない」上限を、Phase 1では「0 retry」とする。

**Test First**

- `test_budget_is_checked_before_first_attempt`
- `test_timeout_aborts_without_retry`
- `test_model_error_aborts_without_retry`
- `test_one_turn_uses_one_model_call_id`
- `test_normal_turn_provider_invocation_count_is_one`
- `test_success_records_usage_and_cost`
- `test_failed_attempt_cost_is_not_rolled_back`
- `test_api_key_sentinel_never_reaches_request_response_or_log`
- `test_fake_provider_requires_no_api_key`
- `test_recorded_fixture_can_replace_fake_provider`
- `test_provider_spy_receives_public_only_request_with_player_input_and_dice`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/model_gateway -q
```

期待REDはmissing module。gateway skeleton後はprovider call count `2`に対する`1`期待失敗、またはC-03 conditional provider-boundary assertion未実装の失敗となる。C-03未承認中のconditional test/signatureをGREEN扱いにしない。

**GREEN**

```text
max_attempts_observed=1
logical_model_calls_per_turn=1
provider_invocations_per_turn=1
budget_checked_before_call=True
secret_hits=0
```

に相当するassertionが全てpassし、provider直前の実際のrequestがpublic-onlyで`gm_only`を含まず、callerの`player_input`と`dice_result`が到達する。C-03 contract approval後はFake / Recorded GatewayをGREENまたはcommit扱いにできるが、provider approval、C-03 plan amendment、再レビューが完了するまでconcrete real Provider adapterを実装、GREEN、commit扱いにしない。

### C-03 decision gate — Provider request boundary

既存P0の`ModelRequest`は`context: tuple[FactRecord, ...]`だけを持ち、`player_input`と`dice_result`を表せない。`src/neontof/model/model_invoker.py`、`fake_provider.py`、`recorded_fixture.py`、既存`tests/model/**`はP1-06のForbidden pathであり、現契約だけでは、`ModelGateway`から既存providerの最終invoke境界へ秘密を渡さずにplayer inputとdiceを到達させるenvelope/mappingを確定できない。

C-03では次のいずれかをユーザーが明示承認する。承認前はP1-06 Fake/Recorded Gatewayの実装、GREEN、commitを開始しない。concrete real Provider adapterはprovider approvalとC-03 plan amendment/re-reviewが揃うまで開始しない。

1. **既存P0 ModelRequest契約を上位改訂する:** `ModelRequest`へplayer input/diceを表す既存契約準拠のfieldまたはcontext mappingを追加し、`model_invoker.py`、provider境界、既存model test、schema/validator、依存する上位文書の変更範囲を列挙して承認する。Phase 1 planからForbidden pathを直接編集せず、上位改訂を先に完了する。
2. **Phase 1の明示承認済みProviderRequest adapterとFake adapterを追加する:** `GatewayRequest`からpublic-onlyの最終envelopeを作るadapterを新設し、既存TestProvider境界へplayer input/diceを安全にmappingする。adapterのpath、signature、dependency、Fake adapter、provider spy test、secret boundary、staging pathを承認済みplan amendmentへ固定する。二つ目のProvider abstractionやregistryは作らない。

各選択肢の影響は、P0 `ModelRequest`のschema、既存invoke境界、provider spyの入力shape、Fake/Recorded fixtureのmapping、Forbidden pathの扱い、依存とtest pathに及ぶ。承認だけで曖昧な実Provider実装を開始しない。固定responseで`player_input`または`dice_result`を無視する方式は、Phase 1 completionとしない。

Provider approval後、C-03の選択に対応するconcrete real Provider adapterのexact path、signature、dependency、test path、git add pathをplan amendmentへ追記し、そのamendmentの再レビューが終わるまで停止する。Fake/Recorded Gatewayのlocal implementationとvalidationはC-03 contract approval後に先行できるが、amendment承認前にconcrete real Provider adapterを実装、GREEN、commitしない。

### Provider selection and approval stop point（必須）

Roadmap P1-06の成果物は、Fake / Recorded Fixtureと交換可能な**一つの具体的な実Provider adapter**である。Fake-onlyではP1-06またはPhase 1を完了扱いにしない。

先にC-03でprovider request boundaryの方式を承認する。その後、Fake / Recorded Gateway、gateway budget、security、`max_attempts=1`、runtime testをAPI keyなし・external networkなしで実装し、normal invocation `1`、zero retry、C-03 contract approvedの条件でFake/Recorded GREENを確認する。Fake / Recordedのlocal validationはprovider approval前も続けてよい。Fake/Recorded GREENを確認した後、実Provider adapterと実行へ進む直前で再び停止し、ユーザーへ次を提示してprovider approvalを得る。provider approval後にexact adapter path等をC-03 plan amendmentへ追記し、再レビュー完了後にconcrete real Provider adapter 1つを実装する。

1. concrete Provider名
2. SDK名とversion、またはHTTP clientを使う場合の根拠
3. API key source（Browser、通常ログ、prompt、fixture、responseへ渡さないことを含む）
4. 想定costとsession budget
5. network destinationとdata visibility
6. 通常Turnの最大provider invocation数（`1`）とtimeout/error時のretry数（`0`）

provider approval前はSDK dependency、key reader、external HTTP call、concrete real Provider adapter、実Provider testを追加しない。provider approval後も、C-03で承認されたexact path/signature/dependency/test path/git add pathがplan amendmentへ反映され、再レビューを終えるまで実装しない。承認内容が既存契約またはこのplanの署名を変える場合は、実装せず上位文書の判断を求める。Fake / Recordedのlocal testはAPI key/networkなしでC-03 contract approval後に実行でき、provider approval前も継続してよいが、C-03、provider approval、amendment、再レビュー前はconcrete real Provider adapterのGREEN/commitやPhase 1 completionとしない。

**Commit boundary**

```powershell
git add -- src/neontof/model/gateway_models.py src/neontof/model/gateway.py tests/model_gateway/test_gateway_budget.py tests/model_gateway/test_gateway_retry.py tests/model_gateway/test_gateway_security.py tests/model_gateway/test_gateway_fake_provider.py
```

Test FirstのREDは未コミット証拠として残す。C-03承認後、上記pathのFake/Recorded testsとimplementationを1つのlogical GREEN commitへまとめる。Fake/Recorded GREEN、provider approval、C-03 plan amendmentの再レビュー、exact pathの確定後に、amendmentで追加されたreal adapter/test pathを明示して別のlogical GREEN commitへまとめる。未承認中は該当する`git add` pathを確定せず、concrete real Provider adapterのGREEN/commit扱いにしない。

```text
feat: Model Gatewayの予算と安全なProvider境界を実装する
```

---

## P1-07: Context Builder and Evidence Validation

**Create**

- `src/neontof/application/context_builder.py`
- `src/neontof/application/entity_resolver.py`
- `tests/application/test_context_builder.py`
- `tests/application/test_entity_resolver.py`
- `tests/integration/test_evidence_validation.py`

**Public types and signatures**

```python
class PublicInventoryItem(ContractModel):
    item_id: ItemId
    label: StrictStr

class PublicStaticData(ContractModel):
    character_id: EntityId
    hp_max: StrictInt
    resource_id: ResourceId
    resource_label: StrictStr
    resource_max: StrictInt
    inventory: tuple[PublicInventoryItem, ...]
    objective_scene_id: SceneId
    objective_text: StrictStr
    clock_id: ClockId
    clock_label: StrictStr
    clock_max: StrictInt

class ApplicationRegistry(ContractModel):
    scenario: ScenarioV1
    public_static_data: PublicStaticData
    known_location_ids: tuple[LocationId, ...]
    known_npc_ids: tuple[NpcId, ...]
    known_clock_ids: tuple[ClockId, ...]

class PublicResourceCurrent(ContractModel):
    resource_id: ResourceId
    current: StrictInt

class PublicResourceProjection(ContractModel):
    hp_current: StrictInt
    resources: tuple[PublicResourceCurrent, ...]

class PublicLocationProjection(ContractModel):
    location_id: LocationId

class PublicClockProjection(ContractModel):
    clock_id: ClockId
    current: StrictInt

FactValue = EntityId | ItemId | LocationId | SceneId | StrictStr

class PublicFact(ContractModel):
    fact_id: FactId
    kind: Literal["fact"]
    holder: Literal["world", "player_character"]
    subject_id: EntityId | None
    predicate: Literal[
        "inventory_item",
        "objective",
        "location",
        "clue",
        "scenario_version",
        "character_version",
    ]
    value: FactValue
    source_event_id: EventId

class PublicProjection(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    location_id: LocationId | None
    resources: PublicResourceProjection
    locations: tuple[PublicLocationProjection, ...]
    clocks: tuple[PublicClockProjection, ...]
    facts: tuple[PublicFact, ...]
    known_entity_ids: tuple[EntityId, ...]

class PublicContext(ContractModel):
    publication_visibility: PublicationVisibility
    projection: PublicProjection
    known_location_ids: tuple[LocationId, ...]
    known_npc_ids: tuple[NpcId, ...]
    known_clock_ids: tuple[ClockId, ...]
    context_digest: LowercaseSha256

def build_public_static_data(
    *,
    character: CharacterSheetV1,
    scenario: ScenarioV1,
) -> PublicStaticData: ...

class EntityCandidate(ContractModel):
    entity_id: EntityId
    canonical_name: str
    aliases: tuple[str, ...]

class EntityResolution(ContractModel):
    type: Literal["resolved", "ambiguous", "unknown"]
    entity_ids: tuple[EntityId, ...]

def build_context(
    *,
    projection: Projection,
    registry: ApplicationRegistry,
    publication_visibility: PublicationVisibility,
) -> PublicContext: ...

def build_semantic_validation_context(
    *,
    projection: Projection,
    registry: ApplicationRegistry,
    current_turn_status: Literal["running", "awaiting_player"],
    publication_visibility: PublicationVisibility,
) -> SemanticValidationContext: ...

def resolve_entity(
    *,
    text: str,
    candidates: Sequence[EntityCandidate],
) -> EntityResolution: ...
```

`PublicFact.subject_id`は`EntityId | None`であり、`None`のpublic Factも`build_context()`、`PublicProjection`、`PublicContext`の全経路で保持する。

`ApplicationRegistry`はP1-05でloadした`ScenarioV1`と`CharacterSheetV1`から作る。`build_public_static_data()`はHP max、resource ID/label/max、`CharacterSheetV1.inventory`の各InitialItemを`PublicInventoryItem(item_id: ItemId, label: StrictStr)`へ写し、objective_scene_idへ`ScenarioV1.initial_scene.id`の`SceneId`、objective_textへ`ScenarioV1.initial_scene.objective.text`、clock ID/label/maxだけをtyped `PublicStaticData`へ写す。secret本文、NPCの`gm_only`本文、任意のraw Scenario/Characterを含めない。location/NPC/clockのregistryは引数として明示し、bootstrap clockがcurrent `0`でもScenarioV1のclock IDを`known_clock_ids`へ登録する。`build_semantic_validation_context()`は`projection`だけからlocation、clock、NPC registryを推測せず、必ずregistryを受け取る。

`build_public_session_view()`は`public_static_data.inventory`の各`label`を順序どおり`PublicSessionView.inventory: tuple[str, ...]`へ写す。Factの`ItemId`と`PublicInventoryItem.item_id`はそのまま保持し、`EntityId`へ変換しない。

`build_context(..., publication_visibility="player_visible")`はactiveかつ`player_visible`のFactだけをtyped `PublicProjection`へ投影し、`subject_id=None`のpublic Factも落とさずに`PublicContext`を先に作る。secretを一度入れてから削除する方式ではなく、最初から選択しない。resources、locations、clocks、facts、campaign/session/scene/turn/request identifiersはEvent replay由来のtyped projectionとして明示する。full `Projection`はsemantic validationの内部入力に限り、Model Gateway、public HTTP view、Narrative auditへ渡さない。これらのsignatureは`PublicContext`または`PublicProjection`だけを受け取る。

Entity resolutionはUnicode NFKC、casefold、前後空白除去後のcanonical name / exact alias一致だけを使う。曖昧な場合は複数候補を返し、推測しない。自由文からstate effectを生成しない。

Evidenceは既存`validate_semantic_result()`によりfact existence、visibility、predicate/value一致を検証する。

**Test First**

- `test_player_context_contains_only_player_visible_facts`
- `test_subjectless_public_fact_is_retained`
- `test_gm_only_fact_never_enters_intermediate_context_bundle`
- `test_context_digest_is_deterministic`
- `test_unknown_past_returns_undetermined_fixture`
- `test_unknown_past_provider_spy_cannot_read_or_mutate_context`
- `test_public_context_does_not_expose_full_projection`
- `test_public_projection_contains_event_derived_resources_locations_clocks_and_turn_ids`
- `test_public_static_data_contains_only_allowed_character_and_scenario_values`
- `test_zero_clock_is_registered_as_known_clock`
- `test_invisible_evidence_is_rejected`
- `test_claim_mismatch_is_rejected`
- `test_alias_resolves_to_stable_entity_id`
- `test_ambiguous_alias_returns_all_candidates`
- `test_unknown_alias_does_not_guess`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_context_builder.py tests/application/test_entity_resolver.py tests/integration/test_evidence_validation.py -q
```

期待REDはmissing module。visibility filter skeleton後はsecret sentinelがContextに存在するassertion failure。

**GREEN**

- secret sentinel hit `0`
- unknown history fixtureのNarrativeまたはrejectionが「未決定」
- invisible Evidence outcomeが`RejectedSemanticResult`
- Alias resolutionが同じstable ID

**Commit boundary**

```powershell
git add -- src/neontof/application/context_builder.py src/neontof/application/entity_resolver.py tests/application/test_context_builder.py tests/application/test_entity_resolver.py tests/integration/test_evidence_validation.py
```

Test FirstのREDは未コミット証拠として残し、`ApplicationRegistry`、known clock ID `0`、PublicContext/PublicProjection、provider spy/sabotage、Evidence validationのfocused commandがfailure `0`になった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Visibility Filter、PublicProjection、Evidence validation、Alias解決を追加する
```

---

## P1-08: Semantic Result Pipeline

**Create**

- `src/neontof/application/event_materializer.py`
- `src/neontof/application/semantic_pipeline.py`
- `src/neontof/application/turn_engine.py`
- `tests/application/test_event_materializer.py`
- `tests/application/test_semantic_pipeline.py`
- `tests/integration/test_complete_fake_turn.py`
- `tests/integration/test_model_failure_atomicity.py`

**Public types and signatures**

```python
def materialize_accepted_result(
    *,
    outcome: AcceptedSemanticResult,
    metadata: EventMaterializationInput,
    dice_result: DiceResult | None,
) -> EventBatch: ...

def materialize_dice_event(
    *,
    result: DiceResult,
    metadata: EventMaterializationInput,
) -> EventDraft: ...

class DiceProjection(ContractModel):
    rolls: tuple[DiceResult, ...]

def rebuild_dice_projection(
    events: Sequence[DomainEvent],
) -> DiceProjection: ...

class TurnCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    request_key: str
    turn_request_id: TurnRequestId
    input_text: str

class ResumeTurnCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    request_key: str
    root_turn_request_id: TurnRequestId
    turn_request_id: TurnRequestId
    input_text: str

class TurnExecutionResult(ContractModel):
    turn_id: TurnId
    turn_request_id: TurnRequestId
    request_key: str
    status: Literal["running", "awaiting_player", "committed", "aborted"]
    semantic_result: AcceptedSemanticResult | None
    public_projection: PublicProjection
    dice_result: DiceResult | None
    cost_microusd: int
    corrections: tuple[str, ...]

class TurnEngine:
    def __init__(
        self,
        *,
        event_store: EventStore,
        projection_store: ProjectionStore,
        request_store: TurnRequestStore,
        observation_store: ObservationStore,
        gateway: ModelGateway,
        registry: ApplicationRegistry,
    ) -> None: ...

    def submit(self, command: TurnCommand) -> TurnExecutionResult: ...
    def resume(self, command: ResumeTurnCommand) -> TurnExecutionResult: ...
    def undo_latest(
        self,
        *,
        campaign_id: CampaignId,
        session_id: SessionId,
    ) -> TurnExecutionResult: ...
```

`EventMaterializationInput`はP1-00のneutral typeをimportして使い、P1-08で再定義しない。`materialize_accepted_result()`はcaller-assigned sequenceを持たない`EventBatch`を返し、`materialize_dice_event()`は未採番`EventDraft`を返す。`EventStore.append()`がsequence割当、既存DomainEvent parserによる再構築・再検証、全batch appendを同じtransactionで行う。P1-08のproducerは`DomainEvent`または`tuple[DomainEvent, ...]`を返さない。DiceのmaterializationとEvent replay projectionはP1-08の責務である。`DiceProjection.rolls`と`DiceResult`は`DiceRolledPayload`の`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけをauthoritative fieldsとして保持する。

Pipeline順序を固定する。

1. Player InputをTranscriptへappendする。
2. 外部`request_key`をclaimし、Event-derived `TurnStatus`を確認する。
3. Alias / targetをdeterministicに解決する。
4. ambiguousならmodel call前に`awaiting_player` Event batchをappendする。
5. public Contextを構築する。
6. deterministic diceを解決する。
7. budgetを確認する。
8. Gatewayを1 logical call、provider invocation 1回だけ実行する。
9. request / response / timeout / error / usageをTranscript / Telemetryへ記録する。retry recordはPhase 1通常Turnでは作らない。
10. `validate_semantic_result()`を実行する。
11. Rule、reference、Evidence、Visibilityを検証する。
12. accepted proposal、Dice、Fact、lifecycle Eventを1 `EventBatch`へmaterializeする。
13. `EventStore.append(batch)`を1回だけ呼ぶ。sequence割当を別APIで呼ばない。
14. Projectionをrebuildする。
15. validated Narrativeを公開候補にする。
16. post-public audit結果をcorrectionとして記録する。

`ProposedResourceChanged`、`ProposedCharacterMoved`、`ProposedClockAdvanced`、`ProposedFact`だけをmaterializeする。不明Event typeを追加しない。

**Test First**

- `test_invalid_event_type_is_rejected_before_append`
- `test_unknown_entity_is_rejected_before_append`
- `test_dice_projection_rebuilds_from_authoritative_event_fields`
- `test_materializers_return_unassigned_event_drafts_and_batches`
- `test_narrative_only_result_appends_no_state_effect_event`
- `test_proposed_events_are_appended_only_after_validation`
- `test_all_effect_events_and_turn_commit_are_atomic`
- `test_provider_failure_leaves_no_effect_events`
- `test_clarification_enters_awaiting_player`
- `test_model_clarification_contract_is_not_silently_rewritten`
- `test_rejection_aborts_without_effect_events`
- `test_suggested_actions_are_preserved`
- `test_mentioned_details_are_not_parsed_from_narrative`
- `test_duplicate_request_returns_cached_turn_result`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py -q
```

期待REDはmissing module。atomicity実装途中では1件以上のeffect Eventが残り、期待`0`とのassertion failureになる。

**GREEN**

- valid Fake turnが`committed`
- invalid Eventが`rejected`または`aborted`
- failure時effect Event count `0`
- Narrative-only時Resource / Location / Clock / Fact projectionが不変
- Suggested Actionsが2〜4件

**Contract checkpoint**

C-01 decision gateが未承認なら、P1-08の`clarification_request`実装、同じTurnのresume sequence、該当fixtureを開始しない。pre-model ambiguityだけに変換したり、model由来clarificationをtest-onlyへ限定したりしない。C-01承認後に限り、選択された影響範囲をこのWPのtype/signature/testへ反映する。Phase 0 contractの変更はこの計画から行わない。

**Commit boundary**

```powershell
git add -- src/neontof/application/event_materializer.py src/neontof/application/semantic_pipeline.py src/neontof/application/turn_engine.py tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py
```

Test FirstのREDは未コミット証拠として残し、C-01 decision gateが承認済みで、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。focused commandのfailure `0`、Event batch atomicity、dice replay、normal provider invocation count `1`を確認して着地させる。

```text
feat: 検証済みproposalだけをatomic appendするTurn Engineを実装する
```

---

## P1-09: provisional_detail

**Create**

- `src/neontof/application/provisional_details.py`
- `tests/application/test_provisional_details.py`
- `tests/integration/test_provisional_detail_lifecycle.py`

### C-02 decision gate — provisional_detail ID and Fact contract

既存semantic resultの`ProvisionalDetail.id`は`EntityId | NpcId`である。一方、Product Planの例は`pd:scene:...`で、既存validatorはknown Entity/NPCを要求する。この差を、`FactId`への置換や既知Entityの偽装で上位文書変更なしに黙って回避しない。

P1-09開始前にユーザーが次の選択肢のいずれかを明示承認するまで、type、ID、Fact schema、first-mentioned testを実装しない。

1. **既存ID contractを維持する:** `ProvisionalDetail.id`をknown `EntityId | NpcId`として扱う。`pd:scene:...`のProduct Plan例をどう解釈するか、またはPhase 1対象から外すかを上位文書で判断する。
2. **専用provisional IDを導入する:** `ProvisionalDetailId`と`pd:scene:...`形式を正式化し、semantic contract、validatorのknown-ID規則、Fact predicate/value schema、Product Plan例を改訂する。改訂なしには実装しない。
3. **P1-09を延期する:** provisional detailをPhase 1 Gateから外し、first-mentioned acceptanceを後続Phaseへ移す。

C-02承認後だけ、承認内容に対応する`ProvisionalDetail` type、stable ID mapping、`provisional_detail` Fact predicate/value schema、`test_first_mentioned_detail_uses_approved_id_schema`をこのWPへ追加する。承認前のP1-09は停止し、他のWPがこの未決定型へ依存しないようにする。

**Public types and signatures**

以下はC-02承認後に承認内容を反映して確定するconditional signatureであり、承認前に実装・fixture化しない。

```python
class ProjectedProvisionalDetail(ContractModel):
    fact_id: FactId
    entity_id: EntityId
    kind: str
    label: str
    scene_id: SceneId
    visibility: Visibility
    source_event_id: EventId

class ProvisionalProjection(ContractModel):
    scene_id: SceneId | None
    details: tuple[ProjectedProvisionalDetail, ...]

class PromotionOutcome(ContractModel):
    type: Literal["promoted", "conflict", "not_found"]
    events: EventBatch
    message: str | None

def project_provisional_details(
    *,
    projection: Projection,
    current_scene_id: SceneId | None,
) -> ProvisionalProjection: ...

def materialize_provisional_details(
    *,
    details: Sequence[ProvisionalDetail],
    metadata: EventMaterializationInput,
) -> EventBatch: ...

def promote_provisional_detail(
    *,
    reference_text: str,
    provisional: ProvisionalProjection,
    projection: Projection,
    metadata: EventMaterializationInput,
) -> PromotionOutcome: ...
```

`mentioned_details`はNarrative parseではなくSemantic Result fieldからのみ受け取る。未採番`EventDraft`を`EventBatch`へ入れてEvent Logへ`FactAsserted`として記録し、reserved predicate `provisional_detail`とscene IDをvalueへ含める。Event Store以外でsequenceを割り当てない。

`project_provisional_details()`は現在Sceneと一致するactive Factだけを返す。Scene終了後もEventとTranscriptは残るがContextへ入れない。

昇格時は既存Canonとsubject/predicate/valueを比較する。矛盾時は上書きせず`conflict`を返す。成功時はprovisional Factの`FactSuperseded`とcanonical `FactAsserted`を同一batchへ入れる。

**Test First**

- `test_mentioned_bookshelf_is_available_next_turn`
- `test_materialize_provisional_details_returns_unassigned_event_batch`
- `test_first_mentioned_detail_uses_approved_id_schema`
- `test_narrative_without_mentioned_detail_creates_nothing`
- `test_exact_label_reference_promotes_detail`
- `test_conflicting_canon_is_not_overwritten`
- `test_unreferenced_detail_disappears_after_scene_end`
- `test_transcript_retains_detail_after_scene_end`
- `test_gm_only_provisional_detail_never_enters_player_context`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py -q
```

期待REDはmissing module。scene filter未実装時は終了Sceneのdetail件数`1`に対し`0`期待の失敗。

**GREEN**

本棚fixtureで、次Turnに1件、昇格後canonical 1件、Scene終了後provisional 0件、Transcript narrative 1件が成立する。

**Contract checkpoint**

C-02が未承認なら、P1-09のfocused testをGREENにせず、`ProvisionalDetail.id`、reserved Fact value、first-mentioned fixtureを決めない。C-02承認後にだけ承認済みschemaでtest-firstを再開する。

**Commit boundary**

```powershell
git add -- src/neontof/application/provisional_details.py tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py
```

Test FirstのREDは未コミット証拠として残し、C-02 decision gate承認後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめ、first-mentioned test、Fact schema、scene lifetime、conflict handlingのfocused commandを確認して着地させる。

```text
feat: Event由来のprovisional detail Projectionを追加する
```

---

## P1-10: Minimal Browser Client

### P1-10a — Client scaffold

**Create**

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

**Modify**

- `.gitignore`
- `.github/workflows/ci.yml`

Client toolchain version policy:

`Vite`、`TypeScript`、`Playwright`、Node、npmのversionは未確認であり、次の値を採用済み事実として書かない。P1-10aではpackage manifestをplan-level proposalとして作り、実際に採用するversionは`client/package.json`、`client/package-lock.json`、`.node-version`と、`node --version`、`npm --version`、`npm ci`、`npx playwright install chromium`の実出力で確定する。既存ADRにないversion固定は、manifest/install outputが根拠を示した場合だけ行う。

提案するdevDependenciesは次のpackage名だけであり、versionはmanifestで検証後にpinする。

```json
{
  "@playwright/test": "<verified-version>",
  "typescript": "<verified-version>",
  "vite": "<verified-version>"
}
```

Exact scripts:

```json
{
  "dev": "vite --host 127.0.0.1",
  "typecheck": "tsc --noEmit",
  "build": "tsc --noEmit && vite build",
  "test": "playwright test"
}
```

`.node-version`と`packageManager`は、P1-10aのmanifest/install outputで確認したNode/npm versionだけを固定する。確認前に具体値を記録しない。

**Public TypeScript types**

```typescript
export type ProcessingStatus =
  | "accepted"
  | "building_context"
  | "invoking_model"
  | "validating"
  | "committing"
  | "done"
  | "failed";

export interface PublicSessionView {
  campaign_id: string;
  session_id: string;
  scene_id: string | null;
  turn_status: "pending" | "running" | "awaiting_player" | "committed" | "aborted";
  narrative: readonly string[];
  suggested_actions: readonly string[];
  location: string | null;
  hp_current: number;
  hp_max: number;
  resource_label: string;
  resource_current: number;
  resource_max: number;
  inventory: readonly string[];
  objective: string;
  clock_label: string;
  clock_current: number;
  clock_max: number;
  dice: {
    readonly campaign_seed: string;
    readonly action_id: string;
    readonly roll_index: number;
    readonly derived_seed: string;
    readonly formula: "2d6";
    readonly result: number;
  } | null;
  cost_microusd: number;
  processing_status: ProcessingStatus;
  corrections: readonly string[];
}

export interface ProcessingFrame {
  readonly type: "processing";
  readonly data: "accepted" | "building_context" | "invoking_model" | "validating" | "committing";
}

export interface SemanticResultFrame {
  readonly type: "semantic_result";
  readonly data: "accepted";
}

export interface NarrativeFrame {
  readonly type: "narrative";
  readonly data: string;
}

export interface StateFrame {
  readonly type: "state";
  readonly data: PublicSessionView;
}

export interface CorrectionFrame {
  readonly type: "correction";
  readonly data: string;
}

export interface ErrorFrame {
  readonly type: "error";
  readonly code: "budget_exceeded" | "timeout" | "model_error" | "invalid_result" | "conflict";
  readonly message: string;
}

export interface DoneFrame {
  readonly type: "done";
  readonly data: PublicSessionView;
}

export type TurnStreamFrame =
  | ProcessingFrame
  | SemanticResultFrame
  | NarrativeFrame
  | StateFrame
  | CorrectionFrame
  | ErrorFrame
  | DoneFrame;

export async function loadSession(sessionId: string): Promise<PublicSessionView>;
export async function startCampaign(): Promise<PublicSessionView>;
export async function submitTurn(
  sessionId: string,
  requestKey: string,
  turnRequestId: string,
  inputText: string,
  onFrame: (frame: TurnStreamFrame) => void,
): Promise<void>;
```

**Test First**

- `scaffold.spec.ts`でVite dev/preview serverのroot page、input、submit button、status regionのDOM scaffold存在を先に要求する。FastAPI、`/health`、readiness、static routeはこのWPの入力にしない。
- TypeScriptでunknown frame typeをexhaustive switchによりcompile errorへする。

**RED**

```powershell
npm --prefix client ci
npm --prefix client run typecheck
npm --prefix client run build
npm --prefix client run test -- scaffold.spec.ts
```

package未作成時の最初のREDは`ENOENT: no such file or directory, open 'client/package.json'`。scaffold後はmissing DOM element testがfailする。Vite dev/preview serverの起動・readiness・cleanupはPlaywright `webServer`設定で扱い、FastAPI health endpoint未実装をRED理由にしない。

**GREEN**

```powershell
npm --prefix client ci
npx --prefix client playwright install chromium
npm --prefix client run typecheck
npm --prefix client run build
npm --prefix client run test -- scaffold.spec.ts
```

期待:

```text
vite ... building for production...
✓ built
```

exit `0`、`client/dist`は生成されるがcommitしない。

### Browser Gate: Vite dev/preview scaffold

`scaffold.spec.ts`はP1-10aのBrowser Gateとして、Vite dev serverとVite preview serverのそれぞれで実行する。package installとChromium provisioningは依存準備であり、P1-11以降のFastAPI runtime testや「API keyなし・external networkなし」と別工程である。Playwright `webServer`設定がViteのfixed local port、root URL readiness、process cleanupを担う。P1-10aではFastAPI、`/health`、FastAPI static route、port `8765`を要求しない。

```powershell
npm --prefix client ci
npx --prefix client playwright install chromium
npm --prefix client run test -- scaffold.spec.ts
```

まずPlaywright configのdev profileで`npm --prefix client run dev -- --host 127.0.0.1 --port 5173`を起動し、root HTMLのreadiness後にspecを実行する。次に`npm --prefix client run build`を通し、preview profileで`npm --prefix client run preview -- --host 127.0.0.1 --port 4173`を起動して同じspecを実行する。各profileの終了後はPlaywrightがserverを停止し、次のprofileがportを再利用できることを確認する。

```powershell
npm --prefix client run test -- scaffold.spec.ts
```

P1-10aのGREENはVite dev/previewでDOM scaffoldが表示され、typecheck、build、Playwright provisioning、scaffold specがexit `0`になることだけである。CIでも同じVite profile、root readiness、fixed port、test、cleanupを実行する。FastAPI server起動、`/health`、readiness、static route、port `8765`のGateはP1-11以降へ移す。

**Commit boundary**

```powershell
git add -- .node-version client/package.json client/package-lock.json client/tsconfig.json client/vite.config.ts client/index.html client/src/main.ts client/src/api.ts client/src/models.ts client/src/styles.css client/tests/scaffold.spec.ts client/playwright.config.ts .gitignore .github/workflows/ci.yml
```

Test FirstのREDは未コミット証拠として残し、package manifest/install output、Vite dev/preview scaffold spec、typecheck、buildがGREENになった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。FastAPI health/readiness/static routeはこのcommitの条件に含めない。

```text
feat: Viteとvanilla TypeScriptのClient scaffoldを追加する
```

### P1-10b — Playable UI

**Create**

- `client/src/render.ts`
- `client/src/stream.ts`
- `client/tests/session-view.spec.ts`
- `client/tests/reload.spec.ts`
- `client/tests/complete-run.spec.ts`

必要領域に固定IDを付ける。

```text
#narrative
#player-input
#submit-turn
#suggested-actions
#current-location
#hp
#resource
#inventory
#objective
#clock
#dice
#cost
#processing-status
#corrections
```

**Test First**

- `test_processing_status_changes_immediately_after_submit`
- `test_session_view_displays_all_required_state`
- `test_suggested_action_populates_input`
- `test_reload_restores_last_session`
- `test_secret_sentinel_is_absent_from_dom`
- `test_complete_run_reaches_success_or_failure_end`

**RED**

```powershell
npm --prefix client run test
```

期待REDはrequired locator timeoutまたはmissing endpoint response。

**GREEN**

P1-11でGREENにしたFastAPI server start/readiness/cleanup helperで、FastAPIをlocalhost `127.0.0.1:8765`へ起動した状態で:

```powershell
npm --prefix client run test
```

全Playwright test pass。serverがreadiness 200になってからtestを開始し、test終了後にserverを停止する。DOM text全体にsecret sentinelが存在しない。

**Commit boundary**

```powershell
git add -- client/src/render.ts client/src/stream.ts client/tests/session-view.spec.ts client/tests/reload.spec.ts client/tests/complete-run.spec.ts
```

Test FirstのREDは未コミット証拠として残し、P1-10aのclient qualityとP1-11のserver readinessを通過したうえで、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Phase 1のplayable session UIとreload復元を実装する
```

---

## P1-11: Streaming or Safe Fallback

**Create**

- `src/neontof/web/__init__.py`
- `src/neontof/web/contracts.py`
- `src/neontof/web/routes.py`
- `src/neontof/web/streaming.py`
- `src/neontof/application/runtime.py`
- `src/neontof/application/public_view.py`
- `src/neontof/application/narrative_audit.py`
- `tests/web/test_turn_routes.py`
- `tests/web/test_streaming.py`
- `tests/application/test_narrative_audit.py`

**Modify**

- `src/neontof/app.py`
- `src/neontof/config.py`
- `src/neontof/main.py`
- `tests/test_app.py`
- `tests/test_main.py`

**Public types and signatures**

```python
from __future__ import annotations

@dataclass(frozen=True)
class ApplicationRuntime:
    database: SqliteDatabase
    event_store: EventStore
    projection_store: ProjectionStore
    request_store: TurnRequestStore
    observation_store: ObservationStore
    gateway: ModelGateway
    registry: ApplicationRegistry
    public_static_data: PublicStaticData
    scenario_runtime: ScenarioRuntime
    turn_engine: TurnEngine

class ProcessingFrame(ContractModel):
    type: Literal["processing"]
    data: Literal[
        "accepted",
        "building_context",
        "invoking_model",
        "validating",
        "committing",
    ]

class StateFrame(ContractModel):
    type: Literal["state"]
    data: PublicSessionView

class SemanticResultFrame(ContractModel):
    type: Literal["semantic_result"]
    data: Literal["accepted"]

class NarrativeFrame(ContractModel):
    type: Literal["narrative"]
    data: str

class CorrectionFrame(ContractModel):
    type: Literal["correction"]
    data: str

class ErrorFrame(ContractModel):
    type: Literal["error"]
    code: Literal[
        "budget_exceeded",
        "timeout",
        "model_error",
        "invalid_result",
        "conflict",
    ]
    message: str

class DoneFrame(ContractModel):
    type: Literal["done"]
    data: PublicSessionView

TurnStreamFrame = (
    ProcessingFrame
    | SemanticResultFrame
    | NarrativeFrame
    | StateFrame
    | CorrectionFrame
    | ErrorFrame
    | DoneFrame
)

class BufferedTurnResponse(ContractModel):
    frames: tuple[TurnStreamFrame, ...]

class PublicSessionView(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId | None
    turn_status: TurnStatus
    narrative: tuple[str, ...]
    suggested_actions: tuple[str, ...]
    location: str | None
    hp_current: int
    hp_max: int
    resource_label: str
    resource_current: int
    resource_max: int
    inventory: tuple[str, ...]
    objective: str
    clock_label: str
    clock_current: int
    clock_max: int
    dice: PublicDiceView | None
    cost_microusd: int
    processing_status: Literal[
        "accepted",
        "building_context",
        "invoking_model",
        "validating",
        "committing",
        "done",
        "failed",
    ]
    corrections: tuple[str, ...]

def build_public_session_view(
    *,
    public_projection: PublicProjection,
    public_static_data: PublicStaticData,
    resource_projection: PublicResourceProjection,
    dice_projection: DiceProjection,
    turn_status: TurnStatus,
) -> PublicSessionView: ...

def encode_sse(frame: TurnStreamFrame) -> bytes: ...

def build_buffered_turn_response(
    frames: Sequence[TurnStreamFrame],
) -> BufferedTurnResponse: ...

class NarrativeAuditResult(ContractModel):
    corrections: tuple[str, ...]

def audit_narrative(
    *,
    narrative: str,
    semantic_result: AcceptedSemanticResult,
    projection: PublicProjection,
    context: PublicContext,
) -> NarrativeAuditResult: ...

class HealthResponse(ContractModel):
    status: Literal["ok"]

class SubmitTurnBody(ContractModel):
    turn_request_id: TurnRequestId
    input_text: str

class HttpErrorBody(ContractModel):
    code: str
    message: str

def create_app(runtime: ApplicationRuntime | None = None) -> FastAPI: ...
```

`ApplicationRuntime`は`src/neontof/application/runtime.py`で上記shapeを先に定義し、`create_app`はその既存instanceを受け取る。`PublicSessionView`、`PublicProjection`、`PublicContext`、`PublicStaticData`、`PublicDiceView`だけをpublic view、Gateway request、Narrative auditへ渡し、full `Projection`、raw `ScenarioV1`、raw `CharacterSheetV1`をwireまたはpublic serviceへ渡さない。

`build_public_session_view()`の入力は上記のexact signatureに固定する。`public_projection`はEvent replay由来のcampaign/session/scene/turn/request identifiers、resources、locations、clocks、factsを含み、`resource_projection`は同じEvent replayから得たcurrent values、`dice_projection`は`rebuild_dice_projection(EventStore.read_...)`から得る。staticなmax/label/inventory/objective textは`PublicStaticData`だけから読み、inventoryは`public_static_data.inventory`のlabelを表示する。secret/NPC `gm_only`本文を参照しない。full `Projection`、raw authoring model、Transcript、Telemetryをこのbuilderへ渡さない。

reloadではEvent Logを同じ順序でreplayして`PublicProjection`、`PublicResourceProjection`、`DiceProjection`、`PublicSessionView`を再構築する。`test_reload_rebuilds_identical_dice_and_public_session_view_from_event_log`はprojection snapshotとcacheを削除した後でも、Eventだけから同じDiceとpublic view JSONになることをfocusedに確認する。

### Canonical JSON and HTTP contract

PythonとTypeScriptのcanonical JSONは一つだけとし、flatなsnake_caseを使う。Pydanticのalias、camelCase、nested `hp`/`resource`/`clock` shapeを併用しない。`PublicSessionView`のJSON fieldsは`campaign_id`、`session_id`、`scene_id`、`turn_status`、`narrative`、`suggested_actions`、`location`、`hp_current`、`hp_max`、`resource_label`、`resource_current`、`resource_max`、`inventory`、`objective`、`clock_label`、`clock_current`、`clock_max`、`dice`、`cost_microusd`、`processing_status`、`corrections`である。`dice`はnullまたは`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけを持つ。

すべてのframeは次のshapeである。

```json
{"type":"processing","data":"accepted"}
{"type":"semantic_result","data":"accepted"}
{"type":"narrative","data":"validated narrative"}
{"type":"state","data":{ "campaign_id":"...", "session_id":"...", "...":"PublicSessionView fields" }}
{"type":"correction","data":"display-only correction"}
{"type":"error","code":"timeout","message":"..."}
{"type":"done","data":{ "campaign_id":"...", "session_id":"...", "...":"PublicSessionView fields" }}
```

SSEは各frameをcanonical compact JSONで`data: <json>\n\n`へencodeし、buffered responseは`{"frames":[<TurnStreamFrame>, ...]}`とする。`Accept: text/event-stream`は`200`と`Content-Type: text/event-stream`、`Accept: application/json`は`200`と`Content-Type: application/json`を返す。両方のvalidated semantic/narrative/done dataは同値である。

HTTP status/bodyは次に固定する。

- `GET /health`: `200`, `{"status":"ok"}`。database、provider、API keyに依存しない。
- `POST /api/campaigns`: `201`, bodyはcanonical `PublicSessionView`。
- `GET /api/sessions/{session_id}`: foundなら`200`と`PublicSessionView`、未発見なら`404`と`{"code":"session_not_found","message":"..."}`。
- `POST /api/sessions/{session_id}/turns`、`POST /api/sessions/{session_id}/turns/{turn_id}/resume`: bodyは`{"turn_request_id":"...","input_text":"..."}`、`Idempotency-Key` headerは外部`request_key`として必須。成功は上記SSEまたはbuffered `200`。同じ`Idempotency-Key`のreplayはcached `status_code`、`media_type`、bodyをbyte-for-byteで返し、provider/dice/Eventを再実行しない。
- malformed bodyまたはmissing headerは`422`と`HttpErrorBody`、既存Turnと矛盾するresume/undoは`409`と`HttpErrorBody`、server failureは対応する`ErrorFrame`を含む`200` responseとする。
- `POST /api/sessions/{session_id}/undo`: 成功は`200`とbuffered `TurnStreamFrame` response、対象外Turnは`409`。`GET /`と`GET /assets/*`はBrowser静的配信だけを返し、secretを含めない。

`SubmitTurnBody.turn_request_id`はLifecycle Eventのcanonical IDであり、`Idempotency-Key`とは別である。resumeは同じ`turn_id`と同じ`turn_request_id`を使い、headerだけを新しい外部request keyにできる。

`src/neontof/main.py`のentrypointも次のsignatureとCLIを固定し、Browser Gateが同じserver lifecycleを使えるようにする。

```python
def main(argv: Sequence[str] | None = None) -> int: ...
```

`--host`のdefaultは`127.0.0.1`、`--port`のdefaultはplanで検証したlocal port、Browser Gateでは`8765`を明示する。single workerで起動し、SIGINT/terminationでexit `0`、port release、health再bind testを満たす。未確認のframework/versionやCLI仕様を既存ADRの決定として扱わず、実装前にこのplan-level contractとinstall outputを確認する。

HTTP endpoints:

```text
GET  /health
POST /api/campaigns
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/turns
POST /api/sessions/{session_id}/turns/{turn_id}/resume
POST /api/sessions/{session_id}/undo
GET  /
GET  /assets/*
```

`POST /api/sessions/{session_id}/turns`と`POST /api/sessions/{session_id}/turns/{turn_id}/resume`は、`Accept: text/event-stream`でSSE、`Accept: application/json`でbuffered responseを返す。両経路のvalidated semantic / narrative / done payloadは同値でなければならない。

Frame順序:

```text
processing:accepted
processing:building_context
processing:invoking_model
processing:validating
processing:committing
semantic_result
narrative
correction*
state
done
```

NarrativeはSemantic Result validationとEvent commitの完了前に送らない。Streaming非対応Providerでもserverがvalidated Narrativeを1 frameとして送る。

Narrative auditは表示訂正だけを生成し、EventをrollbackまたはState変更しない。訂正はTranscriptへappendする。

**Test First**

- `test_sse_and_buffered_frames_are_semantically_equal`
- `test_narrative_frame_never_precedes_semantic_result_frame`
- `test_narrative_is_not_sent_when_validation_fails`
- `test_state_frame_is_sent_after_event_commit`
- `test_correction_is_displayed_and_logged`
- `test_reload_returns_running_or_last_committed_state`
- `test_http_response_never_contains_api_key_sentinel`
- `test_health_remains_database_independent`
- `test_duplicate_idempotency_replays_exact_cached_http_response`
- `test_public_view_and_narrative_audit_receive_no_full_projection`
- `test_public_view_builder_accepts_only_typed_public_inputs`
- `test_reload_rebuilds_identical_dice_and_public_session_view_from_event_log`
- `test_http_status_and_body_shapes_are_canonical`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/web tests/application/test_narrative_audit.py tests/test_app.py tests/test_main.py -q
```

期待REDは404、missing module、またはNarrative frame indexがSemantic frameより小さいassertion failure。

**GREEN**

全test pass。SSEとbufferedのframeをJSON正規化したtupleが一致する。validation failure responseにNarrative frameが存在しない。

**Commit boundary**

```powershell
git add -- src/neontof/web/__init__.py src/neontof/web/contracts.py src/neontof/web/routes.py src/neontof/web/streaming.py src/neontof/application/runtime.py src/neontof/application/public_view.py src/neontof/application/narrative_audit.py src/neontof/app.py src/neontof/config.py src/neontof/main.py tests/web/test_turn_routes.py tests/web/test_streaming.py tests/application/test_narrative_audit.py tests/test_app.py tests/test_main.py
```

Test FirstのREDは未コミット証拠として残し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。canonical JSON、HTTP status/body、SSE/buffered同値、cached replay、full Projection非公開、health lifecycle、Event-only reloadのfocused commandがGREENであることを確認して着地させる。

```text
feat: 検証後だけNarrativeを公開するHTTP経路と訂正表示を追加する
```

---

## P1-12: First Scenario Content

**Create**

- `content/characters/phase-01-investigator.v1.yaml`
- `content/scenarios/phase-01-clocktower.v1.yaml`
- `tests/fixtures/phase_01/complete-run-requests.v1.json`
- `tests/fixtures/phase_01/complete-run-provider.v1.json`
- `tests/authoring/test_phase_01_content.py`
- `src/neontof/scenario_runtime.py`
- `tests/application/test_scenario_runtime.py`

**Content contract**

Scenarioは「黄昏時計塔」とし、次を固定する。

- Locations: 5
- NPCs: 4
- Secret: 1
- Clues: 3
- Clock: 1
- success End: 1
- failure End: 1
- Character Sheet: 1
- 2件以上のClueに2つ以上の取得Locationを設定する。
- 1 NPCがClock 2および4で能動的な公開Factを発生させる。
- 未実装の戦闘、Search、Recall、Character UIへ依存しない。
- End Conditionは既存`CluesDiscoveredEndCondition`と`ClockReachedEndCondition`だけを使う。
- secret本文は`gm_only`で、normal Model Contextへ入れない。

**Public types and signatures**

```python
class ScenarioAdvance(ContractModel):
    events: EventBatch
    reached_end: Literal["success", "failure"] | None
    public_notice: str | None

class ScenarioRuntime:
    def __init__(self, scenario: ScenarioV1) -> None: ...
    def evaluate_after_turn(
        self,
        *,
        projection: Projection,
        metadata: EventMaterializationInput,
    ) -> ScenarioAdvance: ...
    def evaluate_scene_transition(
        self,
        *,
        projection: Projection,
        requested_location_id: LocationId,
        confirmed: bool,
        metadata: EventMaterializationInput,
    ) -> ScenarioAdvance: ...
```

Director conceptはこのconcrete runtimeが担う。secret-aware判断とplayer-facing Narrativeを同じmodel callで生成しない。`ScenarioRuntime`は未採番`EventDraft`だけを`EventBatch`へ入れて返し、sequenceの割当やDomainEventの再構築はEvent Storeへ委譲する。公開すべき結果だけをEventへ変換し、次Turnのpublic Contextへ入れる。

**Test First**

- `test_content_loads_with_production_loader`
- `test_scenario_has_five_locations`
- `test_scenario_has_four_npcs`
- `test_scenario_has_one_gm_only_secret`
- `test_scenario_has_three_clues`
- `test_two_clues_have_multiple_acquisition_locations`
- `test_clock_drives_active_npc_event`
- `test_scenario_advance_returns_unassigned_event_batch`
- `test_scenario_has_one_success_and_one_failure_end`
- `test_scenario_uses_only_phase_1_runtime_features`
- `test_secret_sentinel_is_absent_from_public_context`
- `test_complete_run_fixture_reaches_an_end_condition`

**RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring/test_phase_01_content.py tests/application/test_scenario_runtime.py -q
```

期待REDはmissing content fileまたはcardinality assertion failure。

**GREEN**

全test pass。complete-run fixtureの最終`SessionEnded.reason`は`completed`で、successまたはfailure Endの公開Factが存在する。

**Commit boundary**

```powershell
git add -- content/characters/phase-01-investigator.v1.yaml content/scenarios/phase-01-clocktower.v1.yaml tests/fixtures/phase_01/complete-run-requests.v1.json tests/fixtures/phase_01/complete-run-provider.v1.json tests/authoring/test_phase_01_content.py src/neontof/scenario_runtime.py tests/application/test_scenario_runtime.py
```

Test FirstのREDは未コミット証拠として残し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。ScenarioV1/CharacterSheetV1のcardinality、authoritative clock/end condition、secret visibility、clock-driven NPC、complete-run fixtureのfocused commandがfailure `0`であることを確認して着地させる。

```text
feat: 黄昏時計塔ScenarioとClock Runtimeを追加する
```

---

## P1-13: First Complete Playtest and Phase Gate

**Create**

- `tests/acceptance/phase_01_fake_complete_run.py`
- `tests/acceptance/phase_01_gate.py`
- `docs/playtests/phase-01-first-complete-run.md`
- `docs/status/phase-01-first-playable-local-web-slice.md`

### Automated complete run

`phase_01_fake_complete_run.py`はtemporary directoryへSQLite DBを作り、production loader、Event Store、Fake / Recorded Fixture Gateway、Turn Engine、Projection、HTTP adapterを通してScenarioを完走する。

期待最終出力:

```text
phase_01_complete_run=end_reached
projection_rebuild=identical
partial_events_after_failure=0
failed_turn_transcript=retained
failed_turn_telemetry=retained
secret_hits=0
dice_replay=identical
duplicate_request_effects=1
browser_state=complete
```

**RED**

```powershell
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
```

期待REDは最初に未実装endpoint、未到達End、またはmissing fixtureでnon-zero exit。単なるprintだけでexit `0`にしない。

**GREEN**

上記9行を出力してexit `0`。

### Human playtest report

`docs/playtests/phase-01-first-complete-run.md`には次を日本語で記録する。

- date
- branch / commit
- Fake / Recorded Fixtureまたは明示承認済み実Providerの別
- start / end timestamp
- total duration
- reached End
- Turn count
- Turnごとのlatency
- Turnごとのcost
- 読み飛ばしたNarrative
- 入力に迷った箇所
- 意図を誤解された箇所
- NPCが受け身だった箇所
- Canon contradiction
- secret exposure
- correction表示
- replay desire: yes / no
- noの場合のreason、frequency、severity
- Stop Condition判定

生Transcript、API key、DB file、実Provider raw responseは文書またはGitへ入れない。

### Phase Gate script

`phase_01_gate.py`は次を検査する。

- Event / Projection rebuild
- failure atomicity
- Transcript / Telemetry retention
- Evidence visibility
- unknown past（固定応答だけでなく、provider spy/sabotageがunknown historyを読めず、PublicContextをmutationできないこと）
- secret scan
- Dice replay
- idempotency
- Non-goal source / dependency scan
- content cardinality
- playtest report required fields

unknown-past testはproviderへ固定の「未決定」文字列だけを返させて終わりにしない。spy providerで受信した`PublicContext`がtyped player-only viewであることを記録し、sabotage providerが過去の未記録Factを参照・注入・mutationしようとした場合にGatewayまたはvalidationが拒否し、Projection/Event Log/context digestが変わらないことをassertする。

**Commands**

```powershell
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
.\.venv\Scripts\python.exe tests/acceptance/phase_01_gate.py
npm --prefix client ci
npx --prefix client playwright install chromium
```

上の`npm ci`とChromium provisioningはdependency準備であり、runtime no-network Gateとは別に記録する。準備後、P1-11のfixed port `8765` server start/readiness/cleanup helperでserverを起動してから次を実行する。

```powershell
npm --prefix client run test
```

期待GREEN:

```text
phase_01_gate=pass
```

human playtest reportが存在しない、End未到達、replay desire未記入、unknown-past sabotageがcontext mutationを検出できない場合はexit non-zeroとする。Fake / Recorded Fixtureのcomplete runはAPI keyなしlocal acceptance evidenceであり、P1-06の一つの実Provider adapter成果物を置き換えない。

**Commit boundary**

```powershell
git add -- tests/acceptance/phase_01_fake_complete_run.py tests/acceptance/phase_01_gate.py docs/playtests/phase-01-first-complete-run.md docs/status/phase-01-first-playable-local-web-slice.md
```

Test FirstのREDは未コミット証拠として残し、Fake / Recorded complete run、phase gate、Browser Gate、unknown-past sabotage、playtest report required fields、local/remote statusが全て実測で確認できた後、上記pathのtestsとdeliverablesを1つのlogical GREEN commitへまとめて着地させる。remote failureをstatus reportから消してcommitしない。

```text
test: Phase 1の完全実行Gateと実測記録を追加する
```

Phase 2はこのcommit後も自動開始しない。ユーザーの明示指示を待つ。

---

# 10. Global Verification Commands

Repository rootで次を順番どおり実行する。

## Runtime and dependency

```powershell
py -3.14 --version
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
node --version
npm --version
npm --prefix client ci
```

versionは採用済み事実として先に期待値を固定しない。`node --version`、`npm --version`、`npm ci`、package manifest/lockfileの実出力を証拠として保存し、既存ADRにないversionを採用する場合はplan-level proposalとして扱う。

期待:

```text
Python 3.14.3
No broken requirements found.
```

## Remote CI status

Remote stateは**failure**でありgreenではない。確認済みrunは`gh run 32474533578`、`completed failure`、2026-08-21のremote `ruff check`は`tests/model/support/run_invocation_scenario.py`などのI001 5件でexit `1`である。local Phase 0 PASSとこのremote failureを別々に記録し、remote failureをlocal greenへ読み替えない。

このplanのGlobal Gateはremote修復、remote status reportの変更、pushを実行しない。remote結果を確認する必要がある場合もread-only確認だけとし、Phase 1 PASSの判定にはremote failureが解消された証拠を要求する。

## Python quality

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
.\.venv\Scripts\python.exe -m pytest -q
```

Success evidence:

- 全command exit `0`
- ruff: `All checks passed!`
- mypy: `Success: no issues found`
- pytest: failure `0`

既存warningは件数と内容を記録し、新規warningを黙認しない。

## Client quality

```powershell
npm --prefix client ci
npx --prefix client playwright install chromium
npm --prefix client run typecheck
npm --prefix client run build
npm --prefix client run test
```

Success evidence:

- TypeScript error `0`
- Vite build exit `0`
- Playwright failure `0`

`npm ci`と`npx ... playwright install chromium`はpackage/browser provisioningとして別に記録する。runtime test自体はAPI keyなし、external networkなしで実行し、serverのfixed port `8765` start/readiness/cleanupはP1-11 integration Gateの手順に従う。P1-10a単独ではFastAPI serverやhealthを起動しない。

## Network and secret boundary

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_no_external_network.py -q
.\.venv\Scripts\python.exe -m pytest tests/model_gateway/test_gateway_security.py tests/application/test_context_builder.py tests/web/test_turn_routes.py -q
```

Success evidence:

- external network attempt `0`
- API key / secret sentinel hit `0`

## Acceptance

```powershell
.\.venv\Scripts\python.exe tests/acceptance/entrypoint_lifecycle.py
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
.\.venv\Scripts\python.exe tests/acceptance/phase_01_gate.py
```

期待:

```text
entrypoint_lifecycle=graceful_exit_0_rebind_health_200
phase_01_complete_run=end_reached
phase_01_gate=pass
```

## Diff and scope

```powershell
git diff --numstat
git diff --ignore-cr-at-eol --numstat
git diff --check
git status --short
```

2つの`numstat`が一致すること。`git diff --check`が空でexit `0`。生成物、`.env`、DB、raw log、`node_modules`、`dist`がstatusへ現れないこと。

Stagingはcommitごとに許可pathを明示列挙する。`git add .`と`git add -A`を使わない。

---

# 11. Risk Level and Rollback Strategy

## Risk level

**Heavy**

理由:

- SQLite transactionとsingle-writer ownershipを新設する。
- Event append、Projection rebuild、Turn idempotencyを実装する。
- Visibility Filter、Semantic Result materialization、Gateway budgetを実装する。
- BrowserとServerを結ぶ新しいpublic HTTP/SSE APIを作る。
- Phase 1 Gateにhuman playtestを含む。
- C-01のcontract tensionが残っている。
- C-03のProvider request boundaryとprovider approvalが未確定である。

## Risk controls

- WPごとにfailing testを先に着地させる。
- Event Store、Projection、Visibility、Dice、Gateway、Turn Engineを別commitにする。
- dependency commitを通過するまで後続integrationを開始しない。
- SQLite migrationはadditiveなversion 1だけとする。
- migration前に既存DBがある場合は同じdirectoryへtimestamp付きcopyを作る。ただしDB backupをGitへ追加しない。
- Event rowをmigrationで書き換えない。
- Projectionは削除・再構築可能とする。
- 実Providerは明示承認まで追加しない。

## Rollback

- 未commitの局所変更は対象ファイルだけを修正し、ユーザーの無関係な差分へ触れない。
- commit済み変更は依存逆順に`git revert`する。
- `git reset --hard`、`git checkout --`を使わない。
- P1-01 rollback時はServerを停止し、Phase 1で生成した開発用DBだけを退避または削除する。対象absolute pathを確認せずに削除しない。
- Projection不具合はEventを残したままprojection tableだけを削除し、修正版でrebuildする。
- Gateway不具合はFake ProviderのままP1-06 commitをrevertし、API keyや外部通信へfallbackしない。
- Client不具合はclient commitだけをrevertし、Server contractを変更して帳尻を合わせない。
- C-01が未承認またはblockingの場合はP1-03以降を開始せず、P1-01 / P1-02 / P1-04 / P1-05の依存commitを保持してユーザー判断を待つ。
- C-02が未承認またはblockingの場合はP1-09とその依存integrationを開始せず、provisional detailのschemaを作らない。
- C-03が未承認またはblockingの場合はP1-06 Fake/Recorded Gatewayとその依存integrationを開始せず、GatewayのGREEN/commitを保留する。provider approvalが未承認またはblockingの場合はP1-06 concrete real Provider adapterとP1-07以降のprovider-dependent integrationを開始せず、real adapterのGREEN/commitを保留する。承認だけで固定responseや曖昧なadapterへfallbackしない。Fake / Recordedのlocal validationはprovider approval前も継続できる。

---

# 12. Commit Boundary Summary

各WP sectionの`Commit boundary`が、test-first RED→minimal GREENのfocused command、full-green条件、明示的な`git add -- <path...>`を定義する唯一の着地表である。下記の推奨順はcommit message順の要約であり、Batch Aを並列に実行しても各WP sectionのpath集合を越えてstageしない。P1-00を最初に着地させ、P1-04aはP1-00後に開始する。

推奨commit順:

0. `feat: Event draftとmetadataのneutral契約を固定する`（P1-00）
1. `feat: append-onlyなSQLite Event Storeと原子性を実装する`（P1-01a）
2. `feat: Eventから再生成できるProjection Storeを追加する`（P1-01b）
3. `feat: TranscriptとTelemetryをEvent transaction外へ保存する`（P1-02）
4. `feat: Request IDで直列化するTurn状態機械を追加する`（P1-03、C-01承認後）
5. `feat: 再現可能な最小Rulesetと資源境界を実装する`（P1-04）
6. `feat: CharacterとScenarioをEventへ正規化する`（P1-05）
7. `feat: Model Gatewayの予算と安全なProvider境界を実装する`（P1-06、C-03・provider approval・plan amendment後）
8. `feat: Visibility Filter、PublicProjection、Evidence validation、Alias解決を追加する`（P1-07）
9. `feat: 検証済みproposalだけをatomic appendするTurn Engineを実装する`（P1-08、C-01承認後）
10. `feat: Event由来のprovisional detail Projectionを追加する`（P1-09、C-02承認後）
11. `feat: Viteとvanilla TypeScriptのClient scaffoldを追加する`（P1-10a）
12. `feat: 検証後だけNarrativeを公開するHTTP経路と訂正表示を追加する`（P1-11）
13. `feat: Phase 1のplayable session UIとreload復元を実装する`（P1-10b）
14. `feat: 黄昏時計塔ScenarioとClock Runtimeを追加する`（P1-12）
15. `test: Phase 1の完全実行Gateと実測記録を追加する`（P1-13）

各commit前にfocused test、関連quality gate、diff scopeを確認する。レビュー済みcommitを着地させる前に依存する次WPを開始しない。commit後も`git push`しない。

---

# 13. Final Gate Decision

Phase 1をPASSと記録できるのは、次の全条件を満たした場合だけである。

- Python、TypeScript、Playwright、acceptance commandが全てexit `0`
- Event / Projection rebuildが一致
- model failureで部分effect Eventが0
- failed TurnのTranscript / Telemetryが保持される
- secret sentinel hitが0
- deterministic diceが再現
- duplicate Requestのeffect countが1
- Browserからsuccessまたはfailure Endへ到達
- human playtest reportが完成
- replay desireが明記
- Non-goalの混入が0
- C-01 decision gateが承認済みで、選択内容に一致するTurn lifecycle/call count testがある
- C-02 decision gateが承認済みで、選択内容に一致するprovisional detail ID/Fact/first-mentioned testがある（P1-09を含める場合）
- C-03 decision gateが承認済みで、選択内容に一致するProvider request boundary、player input/dice到達、public-only provider spy testがある
- C-03のplan amendmentと再レビューが完了し、承認済みexact adapter path、signature、dependency、test path、git add pathが固定されている
- provider approvalが承認済みで、承認された一つの具体的な実Provider adapterのpath、key source、cost、destination、call上限が実装とtestへ一致している
- P1-06のFake / Recorded Fixtureと交換可能な明示承認済みの具体的な実Provider adapterが1つ存在する。Fake-onlyはPASS条件を満たさない
- C-01、C-02、C-03、またはprovider approvalが未承認なら、該当WPをGREENまたはcommit扱いにしない。player input/diceを無視する固定response方式はPASS条件を満たさない
- 通常Turnの`max_attempts=1`、provider invocation `1`、timeout/error時retry `0`が実測される
- remote CIの状態を確認し、`completed failure`のままならPhase 1 Final GateはBLOCKEDとする。failureをgreenへ読み替えない

PASS後もPhase 2は開始しない。`docs/status/phase-01-first-playable-local-web-slice.md`へlocal Gate、remote **failure**（`gh run 32474533578`のcompleted failureとI001 5件）、Known Issues、playtest結果、C-01/C-02/C-03/provider approvalの状態を記録し、ユーザーの次の明示指示を待つ。remote repair、status reportの変更、pushはこの計画に含めない。
