# Phase 1: First Playable Local Web Slice 詳細実装計画

**目標:** localhost で Server を起動し、Browser だけで一人用 Scenario を開始から成功または失敗 End まで遊べる Vertical Slice を作る。

**構成:** Event Log をゲーム状態の唯一の権威とする。Turn Engine だけが検証済み Event を atomic appendし、State / Canon / provisional detail は Event から再構築する。Transcript / Telemetry と idempotency coordination はゲーム状態 transaction の外に置く。

**技術構成:** Python 3.14.3、FastAPI 0.141.1、Pydantic 2.13.4、Uvicorn 0.52.3、stdlib `sqlite3`、pytest 9.1.1、ruff 0.16.3、mypy 2.3.1、HTTP POST + SSE + buffered fallback。Vite、vanilla TypeScript、Playwright、Node、npmのversionはこの計画の時点で確認済みのRepository事実ではない。P1-10aのpackage manifest・lockfile・install/version outputで根拠が得られた値だけを採用し、既存ADRにないclient toolchainの固定はplan-level proposalとして扱う。

**参照仕様:** `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/0001-technology-stack.md`、Phase 0 の `docs/specs/**`、既存の `src/neontof/contracts/**` と `src/neontof/model/**` を再利用する。Phase 0 契約を暗黙に変更しない。

## 既存の完了成果物と検証事実

- P1-00（Neutral Event DraftとMetadata契約）はcommit `b5c1bf3`で完了している。
- P1-00b（Phase 1 Repository Guard移行）はcommit `31fab05`で完了している。
- Phase 0 local baselineは`605 passed, 2 warnings`である。警告は件数・内容を実行時の証拠として記録し、新規警告を黙認しない。
- Remote CIは**pending / 未確認**であり、local baselineとは別の検証事実として扱う。local結果からgreen/failureへ読み替えない。

## 全体制約

- Event Log以外をゲーム状態の権威にしない。
- Stateを直接変更する public APIを作らない。
- LLMの自由文または Narrativeを parseしてEventへ変換しない。
- Semantic Resultのschema、reference、visibility、evidenceを検証してからEventへ変換する。
- Event batchは1回のSQLite transactionでappendし、失敗時に全件rollbackする。
- P1-01a の migration は `0001_event_store.sql` だけを適用し、`schema_migrations` と `events` だけを作る。P1-01b、P1-02、P1-03がそれぞれ `0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`を追加する。全migrationはadditiveで、down migrationを作らない。
- migration runnerは各SQLファイルのraw SQL bytesを`sha256`し、適用済み行の`version`、`name`、`checksum`のdrift、gap、duplicate、out-of-order、unknown applied versionをDDL前にfail-closedで検証する。pending migrationの判定もtransaction内で行う。
- migrationの順序は`BEGIN IMMEDIATE` → `sqlite_master`で`type='table'`の`schema_migrations`存在を確認 → 不存在ならapplied setを空にして同tableをSELECTせず、存在するならtable shapeを検証してからread → validation/pending判定 → 必要時だけrepository tree外のSQLite backup API copy → DDL → `schema_migrations` row insert → `COMMIT`とする。pendingかつ既存schema/dataがある場合だけbackupを作り、新規DBまたはbackup不要時は作らない。backup失敗時はDDLを実行しない。
- migrationでDDLと`schema_migrations` rowを同一transactionに置く。no-op再実行はbackupもschema row writeも行わず、backup file/sidecarをGitへ入れない。このcopyはProduct Plan §20のWeb backup機能ではなく、W-Dで必要な最小copyだけである。
- `SqliteDatabase`にpublic generic `read`/`write`/retry/worker APIを作らない。public型付きStore readだけを公開し、private `_read`/`_write`を境界にする。
- SQLiteは初回migrate時に`PRAGMA journal_mode=WAL`をtransaction外で一度だけ設定し、`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`、`isolation_level=None`、`check_same_thread=True`で固定する。process内shared `threading.Lock`でwriteとmigrateを1つに直列化し、readはlock外の別connectionで行う。以後のno-op再実行ではschema/write/backupを行わない。
- `_read`はconnectionごとに`PRAGMA query_only=ON`を設定するが、多層防御でありsecurity boundaryとは過大表現しない。主境界はpublic surfaceとrepository source guardである。
- 既存`DomainEventValidationError`と`DomainEventValidationIssue`/`IssueCode`は、`src/neontof/contracts/event_parser.py`とcore specの既存契約を変更せず、parser・sequence・projection validationだけに使う。Event StoreのDB constraint violationはP1-01aのローカルな`EventStoreConstraintError`へ分離し、その他の`DatabaseError`は`locked`/`io`/`corrupt`/`other`だけを持つ`SqliteOperationError`へ変換する。元exceptionのmessage/args/cause/context/custom attr/logを残さない。
- `read_campaign`はcampaign内の全sequence連番を読み、全rowの`event_json`、derived columns、readbackを検証してから返す。`read_session`、`read_turn`、`find_turn_by_request`はその完全列へのinspection-only filterであり、対象外rowの破損でもfail-closedにする。
- Projection rebuild/status/dice/public projectionはfiltered sliceを入力にせず、`read_campaign`の完全列だけを入力とする。Event Logだけがauthorityであり、coordination record・observation・snapshotを入力にしない。
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
- Remote CIは**pending / 未確認**であり、local baselineとは別の検証事実として記録する。green/failureへ読み替えない。

## Phase 1の固定契約

この計画の固定契約は次のとおりである。P1-01aは`0001_event_store.sql`の最小schemaとEvent Storeだけを扱い、後続WPの契約は各WPで実装・再検証する。

| 確認項目 | 対応する計画上の契約 |
|---|---|
| migrationの分割とschema ownership | P1-01a=`0001_event_store.sql`（`schema_migrations`/`events`のみ）、P1-01b=`0002_projection_snapshots.sql`、P1-02=`0003_observation_stores.sql`、P1-03=`0004_turn_requests.sql`。全てadditive、down migrationなし。 |
| migration runnerの検証・backup・transaction順序 | raw SQL bytes SHA-256、version/name/checksum drift、gap/duplicate/out-of-order/unknown versionのDDL前検証、必要時だけのrepository tree外SQLite backup API copy、DDLとrow insertの同一transaction。 |
| SQLiteの公開境界とconcurrency | typed Store readだけをpublicにし、private `_read`/`_write`、固定PRAGMA、shared write lock、別connection read、generic write/retry/workerなし。 |
| exceptionの安全な境界 | 既存`DomainEventValidationError`はparser・sequence・projection validationへ限定し、Event Storeのconstraint violationは`EventStoreConstraintError`、SQLite operation failureは`SqliteOperationError`、migration failureは`MigrationError`へ分離する。いずれも元exceptionの詳細・chain・logを保持しない。 |
| Event readの完全性 | `read_campaign`が全sequence・全row・derived columns・readbackを検証し、typed filterはその完全列に対するinspection-only処理とする。 |
| Event authorityの入力経路 | Projection、status、dice、public projection、recoveryはfiltered sliceやsnapshot等を入力にせず、campaign全体のvalidated Event列を使う。 |
| request dedupeとrecovery | DB-wide opaque `request_key`、campaign-scoped canonical `TurnRequestId`、全identity照合、transaction内resume context validation、processing/response型不変条件、campaign全体recovery。 |
| Observationの非transaction境界 | `tool_call`、purpose-specific allowlist、raw provider情報非保存、Event append外の別`_write`、failed TurnのEvent 0件保持、table-local sequence。 |
| Projection snapshotのmonotonicity | P1-01bでEvent read→pure rebuild→monotonic upsertを同じwrite lock critical sectionに置き、stale candidateを拒否する。 |
| Test Firstと着地 | REDで失敗理由を確認し、testsとimplementation（該当SQLを含む）を一つのlogical GREEN commitへまとめ、explicit `git add -- <path...>`で着地する。 |
| repository guardと証拠 | production manifestの4つのP1-01a `.py` entryを維持し、SQLはmanifest entry外、`tests/test_repository_contracts.py`をModify/stage/commitへ含め、WAL sidecarと`.db` variantsを拒否する。 |
| Phase 1の境界 | `event_metadata.py`、contracts、上位文書、後続WPの実装をP1-01aで変更せず、C-01/C-02/C-03/provider approvalのstop gateを維持する。 |

一般見出しは日本語で記述し、各migrationのschema-set evidence、RED/GREEN、commit boundaryは各WPの契約として定義する。Product Plan、Roadmap、ADR、specの改訂と、二つ目の具体実装がない抽象化はPhase 1の対象外とする。

---

## 1. 目標と期待する挙動変化

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

## 2. 明示的なNon-goal

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
- Product Plan、Roadmap、ADR、specを改訂すること。後続WPの契約はこの計画で定義するが、実装は各WPの範囲で行う。

## 3. 入口条件

実装開始時に次を確認する。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

期待証拠:

```text
605 passed, 2 warnings
```

P1-01aの実装開始条件は、P1-00（commit `b5c1bf3`）とP1-00b（commit `31fab05`）が完了していること、Phase 0 local baselineが`605 passed, 2 warnings`であること、P1-00bのrepository guard契約が利用できることである。pytestはexit `0`とfailure数`0`を判定基準にし、Phase 1のtest追加後は件数を固定値として扱わない。

Entry判定:

- Phase 0 Gate: local PASS
- Phase 0 remote CI: **pending / 未確認**。remote runのgreen/failureを判定しない。
- P1-01aの開始条件: P1-00とP1-00bの完了、local baselineのexit `0`、repository guard契約の利用可能性。

Remote未確認はlocal baselineの判定を変更せず、Phase 0のremote GateをPASSへ読み替える根拠にもならない。

## 4. ユーザー指定のPhase Gate

### 正しさ

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

### 体験

- BrowserだけでScenarioの成功または失敗Endへ到達できる。
- Location、HP、Resource、Inventory、Objective、Clock、Dice、Costを常時確認できる。
- Suggested Actionsを2〜4件表示する。
- submit直後にProcessing Statusを表示する。
- reload後に最後の状態または進行中Turnを表示する。
- ClockによりNPCまたは世界が能動的に変化する。
- 実装者が翌日もう一度遊びたいかを記録する。
- 再プレイしたくない場合、理由をfrequencyとseverityで分類する。

### 範囲

- P1-06はFake / Recorded Fixtureに加えて、明示承認済みの具体的な実Provider adapterを1つだけ成果物にする。Fake-onlyはPhase 1完了ではない。
- Rulesetは`neontof-minimal-2d6-v1`だけ。
- Plugin、Profile、Search、Vector DB、認証、Docker、multiplayerが存在しない。
- Phase 2機能を先取りしていない。

## 5. 停止条件

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
- C-03で承認されたProvider request boundaryをP1-06 Fake/Recorded Gateway、concrete real Provider adapter、P1-07以降のprovider-dependent integrationへ反映できない。
- C-01、C-02、C-03、またはprovider approvalが未承認のまま、それぞれに依存するWPをGREENまたはcommit扱いにしようとした。
- Narrative自由文のparseがstate更新に必要になった。
- Scenarioが未実装機能へ依存した。
- C-01またはC-02 decision gateの承認なしに該当WPを開始しようとした。
- P1-00のproduction manifest exact-match、unsequenced DomainEvent envelope、exact payload bytes、またはcoordination metadataの境界が成立しない。
- P1-00bでexact production manifestをglob/prefixへ緩める、forbidden判定を削る、source scanを迂回する、またはPython gate order/Windows runner assertionを弱める必要が生じた。
- 各WPがproduction `.py` pathを同じexact manifestへ明示追加せずにGREENまたはcommitしようとした。
- `tests/test_repository_contracts.py`をModify/stageする二つのWPを同時にactiveにする、または前WPのfocused/full Gate、`git diff --check`、明示commit、clean worktree確認前にmanifest laneの次WPを開始する必要が生じた。
- P1-01 preflightで既存manifestの形式変更、既存migration/policy/P0 contract file変更、repository test-side scanとguide-side scanのいずれかの更新経路を飛ばす必要が生じた。
- `sqlite3.connect`または`sqlite3.Connection`が`src/neontof/persistence/**`以外に現れる、alias/import変形でsource scanを逃れる、またはruntime/test DBをrepository treeへ置く必要が生じた。
- migrationのapplied `version`、`name`、raw SQL bytes SHA-256 checksumにdriftがある、gap、duplicate、out-of-order、unknown applied versionをDDL前に検出できない、またはpending判定をtransaction外へ移す必要が生じた。
- pending migrationで既存schema/dataがあるのにrepository tree外のSQLite backup API copyを作れない、backupが失敗したのにDDLを続行する、または新規DB/no-op再実行で不要なbackupやschema row writeを行う必要が生じた。
- `DomainEventValidationError`、`SqliteOperationError`、`MigrationError`へSQLiteの値・message・cause・context・custom attr・logを漏らす必要が生じた、または`DomainEventValidationError`を別exceptionへwrapする必要が生じた。
- `SqliteDatabase`にpublic generic `read`/`write`、retry、workerを置く、readがwrite lockを取る、または`_read`の`query_only=ON`を主security boundaryと表現する必要が生じた。
- `read_campaign`がcampaign全体の連番・全rowの`event_json`・derived columns・readbackを検証する前に返る、またはfiltered readが対象外の壊れたrowを無視する必要が生じた。
- Projection rebuild、Turn status、dice、public projectionが`read_campaign`の完全列ではなくfiltered slice、snapshot、coordination record、observationを入力にする必要が生じた。
- Event append critical sectionの内側からTranscript / Telemetry appendを呼ぶ、同じDBのnested `_write`を行う、または失敗TurnでEvent 0件のままobservationを保存できない必要が生じた。
- Projection snapshotが古い`through_sequence`で新しいsnapshotを上書きする、Event read・pure rebuild・monotonic upsertを同じwrite lock critical sectionに置けない必要が生じた。
- `request_key`をDB-wide opaqueにしない、canonical `TurnRequestId`をcampaign-scopedにしない、resumeのcontext validationをtransaction外にする、または`processing`とresponseありを型上許す必要が生じた。
- P1-08開始前に、既存`FrozenJsonValue`のcomposite value round-tripではないlossless raw boundaryが承認済みでなく、Phase 0 semantic contractの改訂も済んでいない。
- 同一手法の失敗が2回続いた。
- human playtestでScenarioを完走できない。
- Narrativeの大半を読み飛ばす、入力迷いが頻発する、NPCが待つだけになる。
- Phase Gate後にユーザー承認なしでPhase 2へ進もうとした。

### C-01判断Gate: Turn clarificationとmodel call上限

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

## 6. 変更範囲

### 許可される変更パス

- `src/neontof/app.py`
- `src/neontof/config.py`
- `src/neontof/event_metadata.py`
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
- `tests/test_repository_contracts.py`
- `tests/rules/**`
- `tests/web/**`
- `tests/test_app.py`
- `tests/test_main.py`
- `tests/test_event_metadata.py`
- `tests/acceptance/phase_01_gate.py`
- `tests/acceptance/phase_01_fake_complete_run.py`
- `tests/fixtures/phase_01/**`
- `content/characters/phase-01-investigator.v1.yaml`
- `content/scenarios/phase-01-clocktower.v1.yaml`
- `client/**`（ただし`client/node_modules`と`client/dist`は生成物としてGitへ追加しない）
- `.node-version`
- `.gitignore`
- `.github/workflows/ci.yml`
- `requirements.in`
- `requirements-dev.in`
- `requirements.lock.txt`
- `docs/plans/phase-01-first-playable-local-web-slice.md`
- `docs/playtests/phase-01-first-complete-run.md`
- `docs/status/phase-01-first-playable-local-web-slice.md`

### 禁止される変更パス

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
- `Dockerfile`
- `*.sqlite`
- `*.db`
- `*.sqlite3`
- `*.sqlite-wal`
- `*.sqlite-shm`
- `*.db-wal`
- `*.db-shm`
- `*.db-*` のSQLite variant
- `client/node_modules/**`
- `client/dist/**`

禁止pathの変更が必要になった場合は実装せずStop Conditionとして報告する。

---

## 7. 所有権・寿命・スレッド・依存方向

### 所有権と寿命

- `SqliteDatabase`はdatabase pathとprocess内shared write serialization `threading.Lock`だけを所有する。
- `sqlite3.Connection`は各operation内で生成・使用・closeし、object fieldへ保存しない。
- `_write`と`migrate`は同じshared lockを保持し、同時に1つだけ実行する。readはlock外の別connectionを使う。
- `_read`はconnectionごとに`PRAGMA query_only=ON`を設定する。これは多層防御であり、主security boundaryはpublic surfaceとrepository source guardである。
- `EventStore`だけがDomain Event tableをappendする。
- `ProjectionStore`はEventを読み、削除可能なprojection snapshotだけを置換する。
- `ObservationStore`はTranscript / Telemetryだけをappendする。
- `TurnRequestStore`はHTTP requestの重複実行を防ぐoperational recordを所有する。ゲーム状態のProjection入力にはしない。
- `TurnEngine`がEvent appendを呼べる唯一のapplication serviceである。
- FastAPI routeはHTTP validation、application call、frame serializationだけを担当する。
- Browserはserverが返したpublic viewだけを保持し、秘密、DB、API keyを持たない。

### スレッド

- Uvicornは`workers=1`を維持する。
- FastAPI route、SSE generator、threadpool間でConnectionを共有しない。
- SQLite writeとmigrationはprocess内shared `threading.Lock`と`BEGIN IMMEDIATE`で直列化する。generic retry、worker、public write bypassは作らない。
- `read`はoperationごとに別Connectionをlock外で開き、`isolation_level=None`、`busy_timeout=5000`、`synchronous=FULL`、`check_same_thread=True`を設定する。
- `PRAGMA journal_mode=WAL`は初回migrate時にtransaction外で一度だけ設定する。WALの`-wal`/`-shm` sidecarはrepositoryへ置かない。
- model invocationは同期boundaryとして扱い、SSEのasync generatorから`asyncio.to_thread()`で呼ぶ。
- Diceはlocal `random.Random` instanceだけを使い、global random stateを変更しない。
- Event sequenceはwrite transaction内で現在の最大sequenceを確認して採番競合を拒否する。

### 依存方向

```text
client
  → HTTP/SSE contracts

src/neontof/event_metadata
  → existing src/neontof/contracts

src/neontof/authoring/bootstrap.py
  → src/neontof/event_metadata
  → existing src/neontof/contracts

persistence
  → src/neontof/event_metadata
  → existing src/neontof/contracts

src/neontof/application / src/neontof/scenario_runtime
  → src/neontof/event_metadata
  → persistence / rules / authoring / model/gateway as needed
  → existing src/neontof/contracts

src/neontof/web
  → src/neontof/application
  → src/neontof/event_metadata
  → existing src/neontof/contracts

rules / gateway
  → existing src/neontof/contracts

authoring
  → existing src/neontof/contracts

existing contracts
  → no Phase 1 modules

production code
  → never imports tests
```

`src/neontof/event_metadata.py`はpersistence所有ではないneutral top-level moduleで、既存`src/neontof/contracts`にだけ依存する。`persistence`、`rules`、`authoring`、`application`、`model`、`web`をimportしない。

`ProjectionStore`から`EventStore.append()`を呼ばない。`ModelGateway`から`EventStore`を呼ばない。`ScenarioRuntime`は未採番`EventDraft`または`EventBatch`を返し、Stateを直接更新しない。

### Event readの利用契約

`EventStore.read_campaign(campaign_id)`が唯一の完全列readであり、Projection rebuild、Event-derived Turn status、dice replay、`PublicProjection`/`PublicSessionView`の全callerはこの戻り値だけを入力にする。`read_session()`、`read_turn()`、`find_turn_by_request()`のfiltered tuple、snapshot、`TurnRequestStore`、Transcript、Telemetryをprojection/replayの入力へ渡さない。対象外rowの破損も`read_campaign()`がfail-closedにするため、downstreamが壊れたrowを見落とさない。

`SqliteDatabase`のpublic surfaceは`migrate()`だけであり、generic public `read`/`write`/retry/workerを持たない。Storeが公開するのは型付きreadと責務ごとのappend/claimだけである。`DomainEventValidationError`はそのまま伝播させ、SQLite例外を含む内部例外は安全な列挙codeだけへ変換して外へ出す。

---

## 8. 依存関係と並列実行計画

### Batch 0 — neutral Event metadataの前提（完了済み）

P1-00（commit `b5c1bf3`）はPhase 1のneutral contract landing unitとして完了している。Event draft、batch metadata、Turn lifecycle metadataの型を`src/neontof/event_metadata.py`に置き、P1-03/P1-05/P1-08がApplication固有の未定義型へ依存しない境界を固定する。P1-04はrulesとdeterminismだけを担当し、`event_metadata`をimportしない。

### Batch 0b — Phase 1 repository guardへの移行（完了済み）

P1-00b（commit `31fab05`）はP1-01 preflightとBatch Aが依存するguard transitionとして完了している。Phase 0のexact production manifest、forbidden判定、repository test-side source scan、Python gate order、Windows runner assertionを維持したまま、Phase 1で作るclient/migrations pathとpersistence限定のSQLite usageを検証可能なguardへ遷移した。

### Manifest直列化lane — Batch 0b後

P1-01 preflightがP1-00bの後に完了したら、`tests/test_repository_contracts.py`をModify/stageするproduction WPは一つのmanifest serialization laneへ入れる。exact production manifestを共有するため、同一時刻にactiveにできるlane内WPは一つだけである。次のWPは、前WPのfocused test、full quality Gate、`git diff --check`、明示commit、clean worktreeを確認してから開始する。

laneの実行順は、技術的依存を満たす範囲で次のとおり固定する。

```text
P1-01a → P1-01b → P1-02 → P1-03 → P1-04 → P1-05
  → P1-06 → P1-07 → P1-08 → P1-09 → P1-12 → P1-11
```

上記の各WPは自分のproduction `.py` pathをexact manifestへ追加し、同じpathをModify、staging、commitへ含める。C-01、C-02、C-03、provider approval、payload boundaryなどのStop Conditionでlane内のWPが停止した場合、後続lane WPを開始しない。lane順は共有manifestの競合を解消するための直列化であり、各WPの技術的な入口条件も別途満たす。
P1-06でconcrete real Provider adapterのproduction pathが追加される場合も、C-03で承認されたexact contractをP1-06のmanifest、Modify、staging、commitへ反映し、次のP1-07へ渡す。

### Batch A — Batch 0b後に開始可能なlane外作業

一般則として、write pathが互いに素で結果依存がないWPは並列実行できる。ただし`tests/test_repository_contracts.py`を共有するproduction WPはこの一般則の例外であり、manifest serialization laneのtokenを同時に二つ取得してはならない。P1-10aはproduction manifestを変更しないclient/test-only WPなので、P1-00bのfocused commandとGateがGREENになった後、lane内のactive WPと並列に開始できる。P1-04a、P1-05a、P1-12aはlane内で順番を待ち、Batch Aの独立並列作業としては扱わない。

- P1-10a: Vite client scaffold（manifest lane外）

### Batch B — 依存成立後のlane外作業

P1-10bとP1-13もproduction manifestを変更しないclient/test-only WPだが、依存関係を越えて並列化しない。P1-10bはP1-10aとP1-11のserver contract後、P1-13はP1-10bとP1-12後に開始する。依存が成立した後に、互いのclient/test pathとDB/temp pathが重ならない別のtest-only作業が存在する場合だけ並列実行できる。

- P1-10b: static UI components
- P1-13: First Complete Playtest and Phase Gate

### 逐次統合chain

```text
P1-00（neutral metadata + production manifest）
  → P1-00b（Phase 1 Repository Guard Transition）
P1-00b
  → P1-01 preflight
P1-01 preflight
  → manifest serialization lane（P1-01a → P1-01b → P1-02 → P1-03 → P1-04 → P1-05 → P1-06 → P1-07 → P1-08 → P1-09 → P1-12 → P1-11）
P1-00b
  → P1-10a（manifest lane外。P1-00からの技術的依存はない）
P1-02 + C-01 approval
  → P1-03
P1-03 + P1-05 + C-03 approval
  → P1-06 Fake/Recorded Gateway（normal invocation 1、zero retry、C-03 contract approved）
P1-06 Fake/Recorded GREEN + Provider approval + C-03承認済みexact contract
  → P1-06 concrete real Provider adapter 1つ
P1-06 concrete real Provider adapter path確定 + P1-05
  → P1-07
P1-07 + C-01 approval + payload boundary confirmation
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

依存WPの検証済みcommitは、依存する次WP開始前に着地させる。異なるBatchの変更を混ぜない。

### WP着地契約

各WPは、`Test First`のREDを実際に記録し、同じWPの最小実装だけでfocused commandをGREENにし、そのWPに列挙したpathだけを明示的に`git add -- <path...>`して着地させる。依存WPの開始条件は、そのcommitのfocused command、関係するquality gate、`git diff --check`、scope確認が全てGREENであることとする。`tests/test_repository_contracts.py`をModifyするWPでは、このpathを同時に編集・stageできるactive WPを二つ以上にしない。manifest serialization laneでは前WPの明示commitとclean worktreeを確認するまで次WPを開始せず、lane外のclient/test-only WPも依存pathが重なる場合は並列実行しない。

`git add -A`、`git add .`は使わない。各WPの明示的なstaging pathとfocused commandは本計画末尾のCommit Boundary Summaryに固定する。未確認の依存、契約判断、provider選択が見つかったWPはGREENやcommitを偽装せず、該当Stop Conditionで停止する。

---

# 9. Work Package一覧

## P1-00: Neutral Event DraftとMetadata契約（完了済み: `b5c1bf3`）

**完了成果物**

- `src/neontof/event_metadata.py`
- `tests/test_event_metadata.py`

**完了時の変更**

- `tests/test_repository_contracts.py`

P1-00はP1-01、P1-03、P1-05、P1-08、P1-09、P1-12が共有するneutral locationであり、Application固有のmetadataをEvent StoreやRulesへ逆向きに導入しない。`tests/test_repository_contracts.py`のproduction manifestには`src/neontof/event_metadata.py`が明示されている。EventのsequenceはP1-00でも呼び出し側でも割り当てない。`EventDraftBody`は既存`DomainEventBase`と同じ未採番wire envelopeを表し、P1-00はI/O、parser、Event Store、materializationを実装しない。producerの返却型は`EventDraft`または`EventBatch`とし、`DomainEvent`を返却型にしない。`StoredEvent`はEventStoreのappend/read return typeであり、producerの`DomainEvent` return禁止とは別の契約である。P1-04はrulesとdeterminismだけを担当し、`EventMaterializationInput`と`TurnEventMetadata`をimportしない。

**公開型とシグネチャ**

```python
RawEventPayloadJson: TypeAlias = StrictBytes

class EventAppendMetadata(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    turn_request_id: TurnRequestId | None
    occurred_at: OccurredAt

class EventDraftBody(ContractModel):
    type: StrictStr
    event_id: EventId
    event_version: Literal[1]
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    occurred_at: OccurredAt
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility
    payload_json: RawEventPayloadJson

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

EventMaterializationInput: TypeAlias = TurnEventMetadata
```

`EventDraftBody`には`sequence`もtop-levelの`turn_request_id`も置かない。`turn_request_id`は`EventAppendMetadata`、`TurnEventMetadata`、`RevertEventMetadata`に残すproducer側coordination metadataであり、DomainEvent envelopeのfieldではない。`TurnEventMetadata.turn_request_id`は、同じTurnに属する`PlayerInputAccepted`、`TurnAwaitingPlayer`、`TurnResumed`、`TurnCommitted`、`TurnAborted`の全てへ渡すcanonical request IDである。最初のTurnでは`root_turn_request_id`と`turn_request_id`は同じoriginal request IDを持ち、`TurnAwaitingPlayer`から`TurnResumed`へ進む場合も同じrootと同じcanonical `turn_request_id`を保持する。HTTPの重複排除keyだけを外部coordination recordへ保存する。

`RawEventPayloadJson = StrictBytes`はP1-00がexact bytesを保持するだけのwire boundaryである。P1-00ではUTF-8 decode、JSON root、全入力消費、duplicate key、nested object/array shape、envelope assemblyを検証しない。これらのpayload boundary挙動はP1-01のEventStore materializerとそのfocused testsだけが担当する。

後続P1-01の`EventStore`だけが`_materialize_event_json(*, body: EventDraftBody, sequence: int) -> tuple[bytes, DomainEvent]`を実装する。P1-00は`RawEventPayloadJson`を保持して`EventDraft`または`EventBatch`へ渡すだけであり、このmaterializer、I/O、parser呼出し、Store処理を実装しない。

**検証済みテスト**

- `test_event_batch_has_no_caller_assigned_sequence`
- `test_event_draft_body_matches_unsequenced_domain_event_envelope`
- `test_event_draft_wraps_neutral_body_without_domain_event`
- `test_event_payload_json_requires_exact_bytes`
- `test_neutral_module_does_not_import_application_rules_model_web_or_persistence`
- `test_turn_request_id_is_coordination_metadata_not_event_envelope_field`
- `test_turn_event_metadata_is_neutral_and_reusable`
- `test_revert_event_metadata_is_defined_before_use`
- `test_event_materialization_input_has_no_application_dependency`

`test_revert_event_metadata_is_defined_before_use`は、`RevertEventMetadata`型を単独でimportでき、`EventAppendMetadata`を継承し、required fieldsを持ち、`root_turn_request_id`を持たないことを検証する。

上記のP1-00各testではproduction importをfunction body内に置き、collection errorを発生させない。AST/import testはneutral moduleが`application`、`rules`、`model`、`web`、`persistence`をimportしないことを検査する。focused commandはP1-00 testとproduction manifestを検査する`tests/test_repository_contracts.py`の両方を明示的に対象にする。P1-00 focused testsでP1-01のpayload parsing、assembly、duplicate key、trailing token、rollback挙動を先取り実装しない。

**検証コマンド**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_event_metadata.py tests/test_repository_contracts.py -q
```

このfocused commandは、missing module/type、契約assertion、またはproduction manifestのexact-match failureを検出する。collection errorや0 testだけを失敗根拠にせず、テスト件数を固定値として扱わない。

**完了時の契約**

上記focused commandがexit `0`となり、production manifestが`src/neontof/event_metadata.py`を含むこと、neutral moduleが`application`、`rules`、`model`、`web`、`persistence`をimportしないこと、sequenceをcallerから受け取らないこと、unsequenced envelopeとcoordination metadataの境界、exact bytes typeの契約をassertする。P1-01のpayload parsingやassemblyの結果はこのGateに含めない。

P1-00の完了commitは`b5c1bf3`である。

## P1-00b: Phase 1 Repository Guard移行（完了済み: `31fab05`）

**完了時の変更**

- `tests/test_repository_contracts.py`

P1-00bはP1-01 preflightとBatch Aが依存するguard transitionとして完了している。Phase 0のexact production manifestは完全一致のまま維持し、globやprefixへの変更、forbidden判定の削除、source scanの迂回を行わない。P1-00b自身はproduction manifestへ新しい`.py`を追加せず、以後の各WPが自分のproduction pathを同じmanifestへ明示追加し、同じWPのModify、staging、commitへ含める契約を固定する。

**Guard契約**

- `GENERATED_DIRECTORY_NAMES`へ`node_modules`を追加済みである。Phase 1で実際に作る`.node-version`、`client/package.json`、`client/package-lock.json`、`client/tsconfig.json`、`client` directory、`src/neontof/persistence/migrations` directoryは許可される。
- `Dockerfile`、forbidden SDK/registry、`client/node_modules`、`client/dist`、DB fileは引き続き禁止または生成物扱いとし、manifestのexact-matchやforbidden判定を緩めて許可しない。
- CIからnode/npmを禁止するassertは撤回済みである。`node --version`、`npm --version`、`npm ci`、Playwright provisioningはPhase 1のclient Gateで実行できる。Python gate orderとWindows runnerのassertは維持される。
- `sqlite3.connect`と`sqlite3.Connection`は`src/neontof/persistence/**`だけで許可し、その他のproduction moduleでは禁止する。import alias、`from sqlite3 import ...`、別名参照などの変形でrepository source scanを逃れる実装を許可しない。
- repository test-side source scanはAST/import-awareに実行し、単純な文字列一致だけを回避する別名・import変形を検出する。repository guardはrepository tree直下・再帰下の`*.db`、`*.db-wal`、`*.db-shm`、`*.db-*`、`*.sqlite`、`*.sqlite-wal`、`*.sqlite-shm`、`*.sqlite3`を拒否し、WAL sidecarとvariantをGitへ入れない。

**検証済みテスト**

- `test_generated_directory_names_include_node_modules`
- `test_phase_1_client_and_migrations_paths_are_allowed`
- `test_forbidden_dockerfile_sdk_registry_and_generated_paths_remain_forbidden`
- `test_exact_production_manifest_requires_explicit_entries`
- `test_node_and_npm_are_not_rejected_by_ci_guard`
- `test_python_gate_order_is_preserved`
- `test_windows_runner_assertion_is_preserved`
- `test_sqlite_connections_are_allowed_only_in_persistence`
- `test_sqlite_source_scan_rejects_alias_and_import_variants_outside_persistence`
- `test_repository_guard_rejects_database_files_in_repository_tree`
- `test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants`

上記testは`tests/test_repository_contracts.py`だけに置き、exact production manifestの既存entry、forbidden SDK/registry、Dockerfile、client/node_modules、client/dist、DB file、Python gate order、Windows runner assertionを回帰させない。

**検証コマンド**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

このfocused commandは、guardの許可path、generated directory、node/npm、SQLite scope、alias/import variant、または既存exact manifest/forbidden assertionの失敗を検出する。collection errorや0 testだけを失敗根拠にしない。

**完了時の契約**

同じcommandがexit `0`となり、production manifestが完全一致のまま明示entryだけを受け付け、forbidden判定を維持し、Phase 1のclient/migrations pathを許可し、node/npmをCIから排除せず、Python gate orderとWindows runner assertionを維持し、`sqlite3.connect`/`sqlite3.Connection`をpersistence配下だけで許可する。alias/import変形によるsource scan bypass、repository tree内のDB file、`client/node_modules`、`client/dist`は検出される。


## P1-01: Event StoreとProjection

### P1-01 事前確認 — repository guard / manifest / migration / SQLite source-scan の停止条件

P1-00bのfocused commandとGuard GateがGREENであることを、P1-01事前確認の入口条件とする。P1-01事前確認自身では`tests/test_repository_contracts.py`を変更しない。P1-01a着手後は、P1-01aが作るproduction `.py` pathをexact production manifestへ明示追加するため、同ファイルをP1-01aのModify、staging、commitへ含める。

既存production manifestの完全一致、forbidden判定、manifestの形式は変更しない。P1-01aの`src/neontof/persistence/migrations/0001_event_store.sql`と`src/neontof/persistence/migrations` directoryはP1-00bで許可されたpathであり、新規作成してよい。Phase 1のmigration file setは、P1-01aの`0001_event_store.sql`、P1-01bの`0002_projection_snapshots.sql`、P1-02の`0003_observation_stores.sql`、P1-03の`0004_turn_requests.sql`で構成する。既存のPhase 0 migration、migration policy、contract manifestの形式、P0 contract fileは変更しない。既存entryの削除、glob/prefix化、forbidden SDK/registryの解除、またはP1-00bで明示されたclient/migrations pathとnode/npm usageの範囲を超える変更が必要になった場合は、P1-01aの最初のfile edit前に停止する。

SQLiteの更新経路は二つに分ける。repository test-sideは`tests/test_repository_contracts.py`が所有し、exact manifest、generated path、forbidden path、Python gate order、Windows runner、production sourceのAST/import-aware SQLite scopeを検査する。guide-sideは`docs/agent-guide/build-and-verify.md`が定義するSQLite scanを使い、同文書は直接編集しない。

repository test-sideのfocused evidenceは次で取得する。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

このtest-side scanは`sqlite3.connect`、`sqlite3.Connection`、`import sqlite3 as ...`、`from sqlite3 import ...`などのalias/import変形をAST/import-awareに検出し、単純な文字列一致だけを通す回避を許さない。許可範囲は`src/neontof/persistence/**`だけである。

guide-sideのSQLite scanは`docs/agent-guide/build-and-verify.md`の`production forbidden source scan`全体をそのまま実行する。SQLite判定部は同文書の`Get-RgHitCount`経由の次のpatternと`sqlite_connection_hits`出力を含む。

```powershell
$sqliteConnectionHits = Get-RgHitCount -Pattern '(?i)(?:sqlite3\.connect|sqlite(?:\+|:))' -Path @('src')
"sqlite_connection_hits=$sqliteConnectionHits"
```

P1-00b後のguide-side policyは`src/neontof/persistence/**`だけをSQLite ownerとして扱い、それ以外のproduction sourceをhitとする。`sqlite3.Connection`のimport aliasを含むscope判定はrepository test-sideのAST/import-aware scanが担当し、guide-sideの単純な文字列scanだけで完了扱いにしない。

P1-01aでpersistenceのSQLite usageを導入する前に、guide-side scan policyを`src/neontof/persistence/**`だけをownerとして扱う内容へMyWorkflow正本で更新し、deployしてから、展開後に同じscanを再検証する。`docs/agent-guide/**`は直接編集しない。repository test-sideのguard変更とguide-sideの更新経路を混同せず、両方のevidenceが確認されるまでP1-01aをGREENにしない。文字列一致だけでalias/import変形を見逃す実装や、remote repair/pushによる迂回は認めない。

P1-01、P1-11、P1-13のruntime/test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置き、repository内の`*.sqlite`、`*.sqlite3`、`*.db`、`*.db-wal`、`*.db-shm`、`*.sqlite-wal`、`*.sqlite-shm`、raw DB backupを生成しない。P1-01aのmigration/atomicity、P1-11のserver start/readiness/rollback、P1-13のcomplete run/playtest/rollbackは、このDB locationとguard statusを同時に検証する。

### P1-01a — SQLite schemaとatomic Event Store

**作成**

- `src/neontof/persistence/__init__.py`
- `src/neontof/persistence/sqlite_database.py`
- `src/neontof/persistence/migrations.py`
- `src/neontof/persistence/migrations/0001_event_store.sql`
- `src/neontof/persistence/event_store.py`
- `tests/persistence/test_event_store.py`

**変更**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

P1-01aのproduction manifest追加は`src/neontof/persistence/__init__.py`、`src/neontof/persistence/sqlite_database.py`、`src/neontof/persistence/migrations.py`、`src/neontof/persistence/event_store.py`の4つだけを明示する。`src/neontof/persistence/migrations/0001_event_store.sql`はmanifestの`.py` entryではなく、P1-00bで許可されたmigration pathとして扱う。P1-01aのwrite scopeは上記のCreate/Modify pathだけであり、`src/neontof/event_metadata.py`、`src/neontof/contracts/**`、`docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/**`、`docs/specs/**`、その他の上位文書を変更しない。P1-01b/P1-02/P1-03のtable・migration・Store実装を先取りしない。

**公開型とシグネチャ**

```python
T = TypeVar("T")

DatabaseIssueCode = Literal["locked", "io", "corrupt", "other"]
EventStoreIssueCode = Literal["duplicate_event_id", "event_constraint_violation"]
MigrationIssueCode = Literal[
    "version_name_drift",
    "checksum_drift",
    "gap",
    "duplicate",
    "out_of_order",
    "unknown_applied_version",
    "backup_failed",
    "sql_error",
]

class SqliteOperationError(Exception):
    code: DatabaseIssueCode

class EventStoreConstraintError(ValueError):
    code: EventStoreIssueCode

    def __init__(self, code: EventStoreIssueCode) -> None: ...

class MigrationError(Exception):
    code: MigrationIssueCode

class SqliteDatabase:
    def __init__(self, path: Path) -> None: ...
    def migrate(self) -> None: ...
    def _read(self, operation: Callable[[sqlite3.Connection], T]) -> T: ...
    def _write(self, operation: Callable[[sqlite3.Connection], T]) -> T: ...
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

    def _read_campaign_on_connection(
        self,
        connection: sqlite3.Connection,
        campaign_id: CampaignId,
    ) -> tuple[DomainEvent, ...]: ...

def _materialize_event_json(
    *,
    body: EventDraftBody,
    sequence: int,
) -> tuple[bytes, DomainEvent]: ...
```

`SqliteDatabase`のpublic surfaceは`migrate()`だけである。`path`以外のconnectionを保持せず、`_read(self, operation: Callable[[sqlite3.Connection], T]) -> T`、`_write(self, operation: Callable[[sqlite3.Connection], T]) -> T`、`_open_connection(self) -> sqlite3.Connection`はprivate exact signatureとして固定する。`_open_connection()`は`isolation_level=None`、`check_same_thread=True`、`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`を設定する。`migrate()`はshared `threading.Lock`を保持したまま、初回だけmigration connection上でtransaction外に`PRAGMA journal_mode=WAL`を一度設定し、その後にmigration transactionを実行する。以後のno-op再実行ではschema/write/backupを行わない。`_read()`はlockを取らず、operationごとの別connectionに`PRAGMA query_only=ON`を設定してcallbackを実行し、connectionをcloseする。query-onlyはdefense-in-depthであり、主な境界はpublic surfaceとrepository guardである。`_write()`はshared `threading.Lock`を保持して`BEGIN IMMEDIATE`、callback、`COMMIT`を実行し、例外時は`ROLLBACK`してconnectionをcloseする。retryやworkerを暗黙に追加しない。

`EventStore`は`from neontof.event_metadata import EventBatch, EventDraftBody, StoredEvent`でneutral typeをimportし、`DomainEvent`をEvent Logへappendする唯一のownerである。`append(batch)`は未採番`EventDraftBody`を受け取り、同じ`BEGIN IMMEDIATE` transaction内でsequenceを割り当て、各draftについて`_materialize_event_json(*, body: EventDraftBody, sequence: int) -> tuple[bytes, DomainEvent]`を呼ぶ。public generic `SqliteDatabase.read()`は存在せず、typed Storeのreadだけを公開する。

`_materialize_event_json()`の`body.payload_json`は、UTF-8 strictでdecodeできる単一の完全なJSON objectであり、DomainEventの`payload`全体を表す。materializerはenvelope組み立て前にpayload bytesを全入力消費し、末尾tokenを許さず、全階層のduplicate object keyを拒否し、root object以外を拒否する。duplicate object key拒否は既存`parse_domain_event`の機能ではなくEventStore materializerの先行guardであり、parser受理だけではduplicate key guardの証拠にならない。nested object/arrayのshapeは保持し、元のpayload bytesを再encodeしない。

EventStoreは固定順・compact JSONでenvelopeを構成し、bodyのscalar（`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`occurred_at`、`origin`、`visibility`）とtransactionでassignedした`sequence`をそれぞれ一度だけ出力し、検証済み`payload_json` bytesをouter `payload` valueとして一度だけ挿入する。payload bytesをenvelope fragmentとして連結しない。

完成したassembled bytesを既存`parse_domain_event`へ渡す。照合は二つに分ける。第一に、parsed `DomainEvent`の`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`sequence`（transaction assigned）、`occurred_at`、`origin`、`visibility`というscalar/envelope全fieldがbodyとassigned sequenceにstrict一致することを検証する。第二に、既存parserによるtyped payload validationの成功とは別に、persisted exact assembled `event_json`から特定したouter `payload` valueのbyte spanが検証済み`payload_json`の元bytesと一致すること、nested object/array shapeが保たれていることを検証する。この二つを合わせてenvelope全体の一致とする。既存`FrozenJsonValue`のlossy representationを比較根拠にしない。
`_materialize_event_json`とenvelope assemblerでは`EventDraftBody.model_dump_json()`、`EventDraftBody.model_dump()`、`DomainEvent.model_dump_json()`、`DomainEvent.model_dump()`、typed modelの汎用再encodeを一切使わない。outer scalarは固定fieldを標準JSON encoderで出し、`payload_json`の元bytesをouter `payload`のnested valueへ一度だけ挿入する。永続化対象の`event_json`はparser受理、scalar/envelope全fieldのstrict一致、typed payload validation、payload byte span一致を通過したexact assembled bytesだけとし、payload boundary failureを含むbatchは同一transaction全体をrollbackする。callerへsequence取得APIを公開しない。`SqliteDatabase`のconnection lifecycleを使う各storeは、自分が所有するtableのwrite transactionだけを実行する。

`read_campaign(campaign_id)`は`events`の全rowを`campaign_id`単位で`sequence ASC`に読み、sequenceが`1..N`の連番であることを確認する。全rowについてraw `event_json`のUTF-8、既存parserの受理、derived columnsとparsed `DomainEvent`のstrict一致、readbackした全fieldの一致を検証し、1件でも不正なら何も返さずsanitized errorでfail-closedにする。全件検証が完了してからだけ`tuple[DomainEvent, ...]`を返す。`_read_campaign_on_connection(connection, campaign_id)`はこの完全列検証の共通private実装である。

`read_session()`、`read_turn()`、`find_turn_by_request()`はそれぞれ先に`read_campaign()`と同じ完全列を取得し、read_campaign完了後のvalidated memory filterだけを行う。filtered SQLを直接実行して対象外rowを見落とさない。`read_session()`は指定`campaign_id`と`session_id`、`read_turn()`は指定`turn_id`に一致するEvent、またはvalidated `TurnReverted.payload.target_turn_id`が一致するEventを返す。`find_turn_by_request()`はvalidated `PlayerInputAccepted.payload.turn_request_id`だけを候補として走査し、top-level envelopeや`TurnRequestStore`のcoordination rowを参照しない。`0001_event_store.sql`にはrequest lookup indexを作らない。該当しなければ全て`()`を返し、全ID lookupは`campaign_id`のscope内に限定する。対象外の壊れたrowがあってもfilter結果を返さず、完全列検証のfailureをそのままfail-closedにする。Projection rebuild、Turn status、dice、public projectionはこの`read_campaign()`の完全列だけを入力にする。

### migration runnerの固定契約

`migrations.py`はmigration directoryの`*.sql`をfilename bytesとして`Path.read_bytes()`し、raw bytesそのものに`hashlib.sha256(raw_bytes).hexdigest()`を適用する。checksum計算で改行・encoding・whitespaceを正規化しない。実行時だけUTF-8 strictでdecodeし、各statementを同じconnectionの明示transaction内で実行する。implicit commitを起こす実行経路を使わない。`schema_migrations`の各rowは`version`、`name`、`checksum_sha256`を持ち、現行fileのversion/name/checksumと完全照合する。

`migrate()`の順序と失敗境界は次のとおり固定する。

```text
BEGIN IMMEDIATE
  → sqlite_masterでtype='table'のschema_migrations存在を確認
  → 存在しない場合はapplied setを空にし、schema_migrationsをSELECTしない
  → 存在する場合はtable shapeを検証してからschema_migrations read
  → migration file setとapplied version/name/checksumのvalidationおよびpending判定
  → pendingかつ既存schema/dataがある場合だけ、migration source connectionからrepository tree外の新しいdestination connectionへSQLite Connection.backup()
  → destinationをclose/reopenしてschema/dataを検証
  → pending migrationのDDL
  → schema_migrations row insert
COMMIT
```

`schema_migrations`の存在確認は`sqlite_master`への`type='table'`を含む明示的な照会で行う。存在しない場合だけapplied setを空にし、同tableへのSELECTを行わない。存在する場合は`PRAGMA table_info(schema_migrations)`等でtable shapeを検証してから読む。任意の`no such table`をbootstrap扱いにして握り潰さない。schema_migrationsのtable shape不一致、予期しないSQLite error、またはread failureはその場で安全な`MigrationError`として扱い、空setへ置換しない。available file setのversion重複、applied versionのduplicate、gap、out-of-order、unknown applied version、version/name/checksum driftのvalidationとpending判定は同じtransaction内でDDL前に行う。pendingがなければDDL、row insert、backupを行わず、no-op再実行とする。

pending migrationがあり、DBに既存のnon-system schemaまたはdataがある場合だけ、write lockを保持したmigration source connectionから、repository tree外の新しいdestination connectionへ`sqlite3.Connection.backup()`を行う。destination connectionはcloseしてreopenし、`sqlite_master`、table shape、schema/dataを検証してからDDLへ進む。新規DB、zero-byte DB、または既存schema/dataがなくbackup不要な場合はcopyしない。backup失敗はDDLまたは`schema_migrations` row insertより前に安全な`MigrationError(code="backup_failed")`へ変換し、rollbackしてDDLへ進まない。copyはProduct Plan §20のWeb backup機能を先取りするものではなく、W-Dで必要な最小copyである。backup fileと`-wal`/`-shm` sidecarはGitへ入れない。

SQLite例外の境界は二段に固定する。既存`DomainEventValidationError`と`DomainEventValidationIssue`/`IssueCode`は`src/neontof/contracts/event_parser.py`およびcore specの既存契約を変更せず、parser、sequence、projection validationだけに使う。Event Storeは、同じwrite transaction内の事前照合でduplicate `event_id`を検出し、`EventStoreConstraintError(code="duplicate_event_id")`へ写像する。事前照合で検出されないその他の`sqlite3.IntegrityError`は`EventStoreConstraintError(code="event_constraint_violation")`へ写像する。payload/envelope/sequence/readback validationから生じた既存`DomainEventValidationError`はsanitizedな既存issue codeのまま送出し、`EventStoreConstraintError`へwrapしない。

元のSQLite exceptionのmessage、value、args、cause、context、custom attr、logは保持しない。except block内ではcodeに応じた固定文面のmapped errorだけを作り、元exceptionをmapped errorへ連結せず、except blockの外で`raise mapped_error from None`相当として送出する。その他の`sqlite3.DatabaseError`は`SqliteOperationError`の`locked`、`io`、`corrupt`、`other`のいずれかへ分類し、migration固有のdrift、validation、backup、DDL失敗は`MigrationError`の固定codeだけを返す。

`0001_event_store.sql`は次のexact schemaだけを作る。後続table、down migration、request lookup index、後続WPのschemaをここへ入れない。

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL CHECK (
        length(checksum_sha256) = 64
        AND checksum_sha256 = lower(checksum_sha256)
        AND checksum_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);

CREATE TABLE events (
    campaign_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    event_version INTEGER NOT NULL CHECK (event_version = 1),
    session_id TEXT NULL,
    scene_id TEXT NULL,
    turn_id TEXT NULL,
    occurred_at TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('in_world', 'table_correction')),
    visibility TEXT NOT NULL,
    event_json BLOB NOT NULL CHECK (typeof(event_json) = 'blob'),
    PRIMARY KEY (campaign_id, sequence),
    UNIQUE (event_id)
);
```

`schema_migrations.name`はmigrationのbasename全体を保存する。migration filenameは`NNNN_lower_snake_case.sql`であり、`0001_event_store.sql`のようにbasename全体をnameとして照合する。raw SQL bytes checksumは現行計画のSHA-256と同じ`hashlib.sha256(raw_bytes).hexdigest()`で計算し、改行・encoding・whitespaceを正規化しない。`events`のprimary keyは`(campaign_id, sequence)`、`event_id`はunique、`event_json`はparser受理とenvelope一致確認を通過したexact assembled JSON bytesとして保存する。derived columnsはparsed Eventのreadback検証用であり、Event Logの代替authorityにしない。

既存parser/readbackは`type`、`event_id`、`event_version`、context（`campaign_id`、`session_id`、`scene_id`、`turn_id`）、`visibility`の意味を検証する。DB列`type`はJSON envelopeの`type`と同値でなければならず、`event_json`は再encodeした値ではなくexact assembled bytesでなければならない。`find_turn_by_request()`のmatching keyはvalidated `PlayerInputAccepted.payload.turn_request_id`だけとし、read_campaign完了後のvalidated memory filterだけを使う。`0001_event_store.sql`ではrequest lookup indexを作らず、P1-03のrequest dedupe contractをEvent Log authorityの代替にしない。

**テストファースト**

先に次を追加する。

- `test_append_persists_events_in_sequence`
- `test_append_rolls_back_every_event_when_second_insert_fails`
- `test_sequence_is_allocated_inside_append_transaction`
- `test_read_campaign_validates_every_row_before_returning`
- `test_read_campaign_requires_contiguous_sequence`
- `test_read_session_filters_only_after_complete_campaign_read`
- `test_read_turn_matches_turn_id_or_revert_target`
- `test_find_turn_by_request_uses_validated_player_input_payload`
- `test_filtered_read_fails_closed_on_corrupt_out_of_scope_row`
- `test_duplicate_event_id_leaves_database_unchanged`
- `test_connection_is_not_reused_across_operations`
- `test_event_store_has_no_public_next_sequence`
- `test_sqlite_database_has_no_public_generic_read_or_write`
- `test_typed_store_reads_are_the_only_public_reads`
- `test_sqlite_connections_use_fixed_pragmas`
- `test_migrate_sets_wal_outside_transaction_once`
- `test_migrate_and_write_share_process_lock`
- `test_read_uses_separate_connection_outside_write_lock`
- `test_read_connection_enables_query_only_as_defense_in_depth`
- `test_migration_is_idempotent`
- `test_migration_0001_creates_only_schema_migrations_and_events`
- `test_schema_migrations_shape_and_checksum_constraint`
- `test_schema_migrations_rejects_non_lowercase_hex_checksum`
- `test_events_schema_exposes_exact_columns_and_constraints`
- `test_schema_introspection_checks_table_info_index_list_index_xinfo_and_sqlite_master_sql`
- `test_event_schema_rejects_not_null_check_and_unique_sabotage`
- `test_event_json_storage_type_is_blob`
- `test_schema_set_maximum_is_one_without_gap_or_unknown_version`
- `test_bootstrap_checks_schema_migrations_existence_before_select`
- `test_bootstrap_validates_schema_migrations_shape_before_read`
- `test_bootstrap_does_not_swallow_unexpected_no_such_table`
- `test_migration_rejects_version_name_checksum_drift_before_ddl`
- `test_migration_rejects_gap_duplicate_out_of_order_and_unknown_version_before_ddl`
- `test_migration_validation_and_pending_detection_stay_inside_transaction`
- `test_migration_ddl_and_schema_row_share_transaction`
- `test_pending_migration_backups_existing_database_before_ddl`
- `test_new_database_does_not_create_backup`
- `test_noop_migration_does_not_backup_or_write`
- `test_backup_failure_prevents_ddl_and_schema_row_insert`
- `test_event_json_persists_exact_assembled_bytes`
- `test_materialized_domain_event_matches_body_and_assigned_sequence`
- `test_payload_json_requires_single_root_object`
- `test_payload_json_rejects_invalid_utf8`
- `test_payload_fragment_cannot_override_sequence_event_id_or_context`
- `test_payload_json_rejects_trailing_tokens`
- `test_payload_json_rejects_duplicate_object_keys_at_any_depth`
- `test_nested_payload_object_and_array_shapes_remain_distinct`
- `test_payload_boundary_failure_rolls_back_entire_batch`
- `test_unsequenced_envelope_materialization_stays_inside_event_store`
- `test_runtime_and_test_databases_stay_outside_repository_tree`
- `test_duplicate_event_id_becomes_sanitized_event_store_constraint_error`
- `test_other_integrity_error_becomes_generic_event_constraint_violation`
- `test_domain_event_validation_error_keeps_phase_zero_issue_codes`
- `test_database_error_becomes_safe_sqlite_operation_error`
- `test_domain_event_validation_error_is_not_wrapped`
- `test_migration_error_does_not_leak_sqlite_details`
- `test_backup_reopen_verification_precedes_ddl`
- `test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants`

`test_materialized_domain_event_matches_body_and_assigned_sequence`はscalar/envelopeの`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、transaction assigned `sequence`、`occurred_at`、`origin`、`visibility`の全fieldをstrict assertし、typed payload validationの成功と、persisted exact assembled `event_json`内のouter `payload` byte spanが元の`payload_json` bytesと一致することを別々にassertする。`model_dump*`や既存`FrozenJsonValue`のlossy representationを比較根拠にしない。
`test_payload_json_rejects_duplicate_object_keys_at_any_depth`は既存parserへ渡す前のEventStore materializer guardを対象にし、parser受理だけをduplicate key拒否の証拠にしない。
`test_read_campaign_validates_every_row_before_returning`はcampaign内の全rowをsequence連番として読み、各`event_json`、derived columns、parser readbackを検証し、途中rowが不正なら結果を返さないことを確認する。`test_read_session_filters_only_after_complete_campaign_read`、`test_read_turn_matches_turn_id_or_revert_target`、`test_find_turn_by_request_uses_validated_player_input_payload`は全て同じ完全列からのinspection-only filterであることを確認する。`test_filtered_read_fails_closed_on_corrupt_out_of_scope_row`はfilter対象外の壊れたrowでもfail-closedになることを確認する。
`test_migration_rejects_gap_duplicate_out_of_order_and_unknown_version_before_ddl`はcorruptな`schema_migrations`を用意し、DDL、backup、row insertが一つも起きないことを確認する。`test_pending_migration_backups_existing_database_before_ddl`は既存schema/dataのpending時だけmigration source connectionからrepository tree外の新しいdestination connectionへSQLite backup API copyを先に作ることを、`test_backup_reopen_verification_precedes_ddl`はdestination close/reopen後のschema/data検証をDDLより前に行うことを、`test_new_database_does_not_create_backup`と`test_noop_migration_does_not_backup_or_write`は不要なcopy/writeがないことを確認する。
`test_migration_validation_and_pending_detection_stay_inside_transaction`はpending判定をtransaction外へ出さないことを、`test_migration_ddl_and_schema_row_share_transaction`はmigration DDLと`schema_migrations` row insertを同じtransactionでcommitすることを確認する。
`test_duplicate_event_id_becomes_sanitized_event_store_constraint_error`は同じwrite transaction内の事前照合で`EventStoreConstraintError(code="duplicate_event_id")`になることを、`test_other_integrity_error_becomes_generic_event_constraint_violation`はその他の`sqlite3.IntegrityError`が`EventStoreConstraintError(code="event_constraint_violation")`になることを確認する。`test_domain_event_validation_error_keeps_phase_zero_issue_codes`はpayload/envelope/sequence/readback validationの既存`DomainEventValidationError`がPhase 0の既存issue codeのまま伝播し、Event Store constraint errorへ変換されないことを確認する。これらと`test_database_error_becomes_safe_sqlite_operation_error`、`test_migration_error_does_not_leak_sqlite_details`はsecretを埋めたsabotage exceptionを使い、message、args、cause、context、custom attr、logのどこにも元exceptionが残らず、安全なcodeだけが出ることを確認する。

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_event_store.py tests/test_repository_contracts.py -q
```

実装前のfocused commandでは、missing module、`0001_event_store.sql`のschema-set assertion、migration validation/backup順序、fixed PRAGMA/lock、atomicity、payload boundary（root object、strict UTF-8、trailing token、全階層duplicate key、fragment override）、campaign全列read、filter fail-closed、exception sanitization、production manifestの追記漏れまたは未許可pathを失敗理由として確認できる。collection errorや0 testだけを失敗根拠にしない。

```text
focused command exit non-zero with a failure reason tied to the missing implementation or one of the listed boundary assertions
```

**完了条件**

同じcommandがexit `0`となり、`tests/test_repository_contracts.py`のmanifest/forbidden guardもpassしたうえで、`0001_event_store.sql`が`schema_migrations`と`events`だけを作り、schema-setのapplied version最大値が1で欠落・未知versionがないことをevidenceとして示す。raw SQL bytes SHA-256、version/name/checksum drift、gap/duplicate/out-of-order/unknown applied versionのDDL前検証、必要時だけのrepository tree外SQLite backup API copy、backup失敗時のDDL無実行、no-op時のbackup/write無実行、DDLとschema rowの同一transactionが成立する。

strict UTF-8、single root object、全入力消費、trailing token拒否、全階層duplicate key拒否、fragment override拒否、nested object/array shape distinction、payload boundary failure時のbatch全体rollbackも成立する。固定順compact envelopeへbody scalarとassigned sequenceを一度ずつ出力し、検証済みpayload bytesをouter `payload` valueへ一度だけ挿入したexact assembled bytesが既存parserに受理され、scalar/envelope全fieldのstrict一致、typed payload validation、persisted `event_json`のpayload byte span一致が別々に成立し、そのexact bytesが保存される。

`SqliteDatabase`にpublic generic read/write、retry、workerがなく、fixed PRAGMAとsingle writer lockが成立する。`read_campaign`が全sequenceと全rowを検証してから返り、typed Storeのfiltered readが同じ完全列からだけ結果を作り、対象外rowの破損でもfail-closedになる。validated lifecycle payloadによるturn request検索とunsequenced envelope materializationの境界も成立し、caller側にsequence割当やgeneric public writeが存在しないこともassertする。Integrity/Database/Migrationのexceptionは安全なcodeだけを持ち、元exceptionを漏らさない。runtime/test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置く。`PRAGMA table_info(...)`、`PRAGMA index_list(...)`、`PRAGMA index_xinfo(...)`、`sqlite_master.sql`、`typeof(event_json) = 'blob'`、NOT NULL/CHECK/UNIQUE sabotage、backup close/reopen後のschema/data検証もpassする。

**コミット境界**

```powershell
git add -- src/neontof/persistence/__init__.py src/neontof/persistence/sqlite_database.py src/neontof/persistence/migrations.py src/neontof/persistence/migrations/0001_event_store.sql src/neontof/persistence/event_store.py tests/persistence/test_migrations.py tests/persistence/test_event_store.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、focused test、SQLite policy、migration schema-set、exception boundary、repository guardがGREENになった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。P1-01aのcommitには`0001_event_store.sql`だけを含め、後続migration/tableを含めない。

```text
feat: append-onlyなSQLite Event Storeと原子性を実装する
```

受入れ証拠:

- 故意に2件目を失敗させたbatch後のEvent件数`0`
- 同じEvent列のread結果が入力順と一致
- public State update methodが存在しない
- `0001_event_store.sql`適用後のschema-setが`schema_migrations`と`events`だけで、最大適用versionが1
- raw SQL bytes SHA-256、version/name/checksum drift、gap/duplicate/out-of-order/unknown applied versionのDDL前拒否
- pending existing schema/dataだけでrepository tree外backup API copy、backup failure時DDLなし、新規DB/no-op時backup/writeなし
- `read_campaign`の全sequence/全row/derived/readback検証、inspection-only filter、対象外破損rowでfail-closed
- fixed SQLite PRAGMA、shared write lock、別connection read、safe exception code、元exception非漏洩

### P1-01b — Projection snapshotとrebuild

**作成**

- `src/neontof/persistence/projection_store.py`
- `src/neontof/persistence/migrations/0002_projection_snapshots.sql`
- `tests/persistence/test_projection_store.py`

**変更**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

P1-01bのproduction manifest追加は`src/neontof/persistence/projection_store.py`だけである。`ProjectionStore`が`projection_snapshots` tableとsnapshot recordを所有し、migration pathは`src/neontof/persistence/migrations/0002_projection_snapshots.sql`とする。このSQLはproduction `.py` manifest entryではない。`0002`は`projection_snapshots` tableだけをadditiveに作り、down migrationを作らない。P1-01aの`0001_event_store.sql`へ追記しない。migration実行後のschema-setの最大適用versionは2で、1から2まで欠落・未知versionなし、version/name/raw SQL bytes SHA-256 checksumのdriftなしをevidenceにする。

`0002_projection_snapshots.sql`の最小schemaは次のとおりである。P1-01bで実装し、migration適用後に再検証する。P1-01aで先取りしない。

```sql
CREATE TABLE projection_snapshots (
    campaign_id TEXT PRIMARY KEY,
    through_sequence INTEGER NOT NULL CHECK (through_sequence >= 0),
    projection_json BLOB NOT NULL CHECK (typeof(projection_json) = 'blob')
);
```

**公開型とシグネチャ**

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

`rebuild()`は`SqliteDatabase._write()`の同じwrite lock critical section内で、(1) connection上のEvent read、(2) `read_campaign`と同じ全row/連番/derived/readback validation、(3)純粋な`rebuild_projection(events)`、(4) monotonicなsnapshot upsertを順に行う。`EventStore.read_campaign()`を内側から呼んでnested `_read`やlockを発生させず、`EventStore._read_campaign_on_connection()`を使う。filtered `read_session()`、`read_turn()`、`find_turn_by_request()`、既存snapshot、coordination record、observationをrebuild入力にしない。

upsertは`campaign_id`をconflict keyとし、`excluded.through_sequence > projection_snapshots.through_sequence`のときだけ更新する。保存済みsnapshotの`through_sequence`がcandidate以上ならcandidateを上書きせず、保存済みの新しいsnapshotを返す。これはstale readとして扱い、Event Logを変更しない。Event readからpure rebuild、monotonic upsertまでを同じwrite lock critical sectionに置くため、appendとのbarrierで古いsnapshotが新しいsnapshotを上書きしない。

Projection tableはderived cacheであり、`delete()`はEventを削除しない。`read()`は型付きsnapshot readだけを行い、snapshotをEvent Logのauthorityとして扱わない。

**テストファースト**

- `test_delete_projection_does_not_delete_events`
- `test_rebuild_after_delete_returns_identical_projection`
- `test_snapshot_through_sequence_matches_event_log`
- `test_projection_store_has_no_state_mutation_method`
- `test_reverted_turn_is_removed_after_rebuild`
- `test_migration_0002_creates_only_projection_snapshots`
- `test_projection_snapshots_schema_has_primary_key_sequence_check_and_blob`
- `test_schema_set_maximum_is_two_without_gap_or_unknown_version`
- `test_rebuild_reads_complete_campaign_before_pure_projection`
- `test_stale_rebuild_does_not_overwrite_newer_snapshot`
- `test_projection_rebuild_barrier_preserves_monotonic_through_sequence`
- `test_projection_rebuild_does_not_use_filtered_event_slice`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_projection_store.py tests/test_repository_contracts.py -q
```

実装前のfocused commandでは`ModuleNotFoundError: No module named 'neontof.persistence.projection_store'`、`0002_projection_snapshots.sql`のschema-set assertion、manifest追記漏れ、または未許可pathを失敗理由として確認する。実装途中は`AttributeError`で`rebuild`が無いこと、またはstale barrierでthrough sequenceが後退することを確認する。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassし、manifest/forbidden guardもexit `0`となる。`0002_projection_snapshots.sql`が`projection_snapshots`だけをadditiveに作り、`campaign_id` primary key、`through_sequence >= 0`、BLOBの`projection_json`を持ち、schema-set最大versionが2、1→2の連番、unknown versionなし、raw SQL bytes checksum一致を示す。delete前後の`projection.model_dump_json()`がbyte-for-byte一致すること。rebuildは全campaign Event read→pure rebuild→monotonic upsertを同じwrite lock critical sectionで行い、stale candidateが新しいsnapshotを上書きせず、barrier testで`through_sequence`が単調非減少であること。Projection test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`に置き、DB file、WAL sidecar、backupをmanifestやstatusへ出さない。

**コミット境界**

```powershell
git add -- src/neontof/persistence/projection_store.py src/neontof/persistence/migrations/0002_projection_snapshots.sql tests/persistence/test_projection_store.py tests/persistence/test_migrations.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、P1-01aのcommit、SQLite policy/local scan、`0002` schema-set、delete/rebuild/reverted-turn/stale-barrier focused commandがfailure `0`になった後、上記pathのtests、migration、implementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Eventから再生成できるProjection Storeを追加する
```

---

## P1-02: TranscriptとTelemetry Store

**作成**

- `src/neontof/observability/__init__.py`
- `src/neontof/observability/records.py`
- `src/neontof/observability/sanitization.py`
- `src/neontof/persistence/observation_store.py`
- `src/neontof/persistence/migrations/0003_observation_stores.sql`
- `tests/observability/test_sanitization.py`
- `tests/persistence/test_observation_store.py`
- `tests/integration/test_failed_turn_observations.py`

**変更**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

P1-02のproduction manifest追加は`src/neontof/observability/__init__.py`、`src/neontof/observability/records.py`、`src/neontof/observability/sanitization.py`、`src/neontof/persistence/observation_store.py`の4つである。`ObservationStore`が`transcript_entries`と`telemetry_entries` tableおよび各recordを所有し、migration pathは`src/neontof/persistence/migrations/0003_observation_stores.sql`とする。このSQLはproduction `.py` manifest entryではない。`0003`は`transcript_entries`と`telemetry_entries`だけをadditiveに作り、down migrationを作らない。`0001`/`0002`へ追記しない。migration実行後のschema-setの最大適用versionは3で、1→3の連番、unknown versionなし、version/name/raw SQL bytes checksum一致をevidenceにする。

`0003_observation_stores.sql`は次の最小schemaを持つ。各tableの`append_sequence`はtable-localで、unique scopeはそれぞれ`(campaign_id, append_sequence)`である。`TranscriptRecord`と`TelemetryRecord`の全fieldを保持し、JSON化したdataは`data_json`、rolesは`roles_json`へ保存する。enum/CHECK、NOT NULL、BLOB型、entry ID制約をP1-02で実装・再検証し、P1-01aで先取りしない。

```sql
CREATE TABLE transcript_entries (
    campaign_id TEXT NOT NULL,
    append_sequence INTEGER NOT NULL CHECK (append_sequence > 0),
    entry_id TEXT NOT NULL UNIQUE,
    session_id TEXT NULL,
    turn_id TEXT NULL,
    model_call_id TEXT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'player_input', 'model_request', 'model_response', 'narrative',
            'error', 'retry', 'correction', 'tool_call'
        )
    ),
    occurred_at TEXT NOT NULL,
    data_json BLOB NOT NULL CHECK (typeof(data_json) = 'blob'),
    PRIMARY KEY (campaign_id, append_sequence)
);

CREATE TABLE telemetry_entries (
    campaign_id TEXT NOT NULL,
    append_sequence INTEGER NOT NULL CHECK (append_sequence > 0),
    entry_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    model_call_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    roles_json BLOB NOT NULL CHECK (typeof(roles_json) = 'blob'),
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status TEXT NOT NULL CHECK (
        status IN ('succeeded', 'failed', 'timed_out', 'rejected')
    ),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cached_tokens INTEGER NOT NULL CHECK (cached_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    cost_microusd INTEGER NOT NULL CHECK (cost_microusd >= 0),
    error_code TEXT NULL,
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (campaign_id, append_sequence)
);
```

**公開型とシグネチャ**

```python
TranscriptKind = Literal[
    "player_input",
    "model_request",
    "model_response",
    "narrative",
    "error",
    "retry",
    "correction",
    "tool_call",
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
    def session_cost_microusd(self, campaign_id: CampaignId, session_id: SessionId) -> int: ...
```

`ObservationStore`へ渡すdataは、TranscriptKind/Telemetry statusごとのpurpose-specific allowlistから組み立てる。raw provider body、raw provider error、exception cause、prompt、API keyは保存対象にしない。invalid response/errorは安全なerror code、digest、byte lengthなど許可された要約だけを保存する。`sanitize_observation()`のrecursive key redaction（`api_key`、`authorization`、`token`、`secret`）は最終防御であり、raw dataを受け入れる主境界にはしない。

`0003_observation_stores.sql`の`transcript_entries`と`telemetry_entries`は、それぞれ独立したtable-local `append_sequence`を持ち、二表横断のglobal sequence allocatorを作らない。`ObservationStore.append_transcript()`と`append_telemetry()`はEvent Log appendとは別のwrite transactionで、自分のobservation tableだけを書き込む。Event append critical sectionの内側からObservationStore appendを呼ばず、同じDBのsingle writer lockをnested acquireしない。Turn pipelineの実行順は`player_input observation → model observations → Event append`とし、各observation appendはEvent appendの外側の別`_write`/connection/transactionで行う。Event appendがrollbackしてEventが0件でも、先行したTranscript/Telemetryとcostは保持し、`TurnReverted`で消さない。`EventStore.append()`、`TurnRequestStore`、Observation Storeのownershipを混ぜない。

**テストファースト**

- `test_player_input_is_retained_when_turn_fails`
- `test_timeout_records_transcript_and_telemetry_with_zero_events`
- `test_turn_revert_does_not_reduce_session_cost`
- `test_session_cost_is_campaign_scoped`
- `test_tool_call_transcript_kind_is_supported`
- `test_schema_set_maximum_is_three_without_gap_or_unknown_version`
- `test_purpose_allowlist_rejects_raw_provider_body_error_and_cause`
- `test_recursive_redaction_is_defense_not_primary_boundary`
- `test_raw_invalid_model_body_is_not_persisted`
- `test_failed_turn_persists_observation_with_zero_events`
- `test_observation_append_is_outside_event_append_critical_section`
- `test_observation_pipeline_orders_player_input_model_observations_then_event_append`
- `test_observation_append_does_not_nested_acquire_single_writer_lock`
- `test_transcript_and_telemetry_sequences_are_table_local`
- `test_observation_types_cannot_be_appended_to_event_store`
- `test_migration_0003_creates_only_observation_stores`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/observability tests/persistence/test_observation_store.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py -q
```

実装前のfocused commandではmissing module、`0003_observation_stores.sql`のschema-set assertion、manifest追記漏れ、未許可path、purpose-specific allowlist、Event transaction外append、またはtimeout integrationのTranscript件数`0`に対する`1`期待を失敗理由として確認する。

**完了条件**

- `0003_observation_stores.sql`が`transcript_entries`と`telemetry_entries`だけをadditiveに作り、TranscriptRecord/TelemetryRecordの全field、entry_id、enum/CHECK、`data_json`/`roles_json`、各tableの`(campaign_id, append_sequence)`を持ち、schema-set最大versionが3、1→3の連番、unknown versionなし、raw SQL bytes checksum一致
- timeout後のEvent count `0`
- Transcriptに`player_input`、`error`、`tool_call`を用途別allowlistで保持し、raw provider body/error/causeを保持しない
- Telemetryに`timed_out`
- session costは`campaign_id`と`session_id`のscopeでrevert前後同値
- secret sentinel hit `0`、recursive sanitizerは最終防御、table-local sequence scopeは各`(campaign_id, append_sequence)`、Event append critical section内のObservationStore append `0`
- `tests/test_repository_contracts.py`のexact manifest/forbidden guardがexit `0`

**コミット境界**

```powershell
git add -- src/neontof/observability/__init__.py src/neontof/observability/records.py src/neontof/observability/sanitization.py src/neontof/persistence/observation_store.py src/neontof/persistence/migrations/0003_observation_stores.sql tests/observability/test_sanitization.py tests/persistence/test_observation_store.py tests/persistence/test_migrations.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、P1-01bのcommit、`0003` schema-set、purpose-specific allowlist、tool_call、failed-turn retention、別transaction、table-local sequence、repository guardがfailure `0`になった後、上記pathのtests、migration、implementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: TranscriptとTelemetryをEvent transaction外へ保存する
```

---

## P1-03: Turn状態機械

**作成**

- `src/neontof/application/__init__.py`
- `src/neontof/application/turn_models.py`
- `src/neontof/application/turn_lifecycle.py`
- `src/neontof/persistence/turn_request_store.py`
- `src/neontof/persistence/migrations/0004_turn_requests.sql`
- `tests/application/test_turn_lifecycle.py`
- `tests/persistence/test_turn_request_store.py`
- `tests/integration/test_turn_idempotency.py`

**変更**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

P1-03のproduction manifest追加は`src/neontof/application/__init__.py`、`src/neontof/application/turn_models.py`、`src/neontof/application/turn_lifecycle.py`、`src/neontof/persistence/turn_request_store.py`の4つである。`src/neontof/persistence/migrations/0004_turn_requests.sql`はSQL migrationであり、production `.py` manifest entryではない。`0004`は`turn_requests`だけをadditiveに作り、down migrationを作らない。`0001`/`0002`/`0003`へ追記しない。`turn_requests`の`request_key`はDB-wide unique opaque key、canonical request identityは`(campaign_id, turn_request_id)`で管理する。migration実行後のschema-setの最大適用versionは4で、1→4の連番、unknown versionなし、version/name/raw SQL bytes SHA-256 checksum一致をevidenceにする。

`TurnRequestStore`が`turn_requests` tableとそのcoordination recordを所有し、migration pathは`src/neontof/persistence/migrations/0004_turn_requests.sql`とする。`0004_turn_requests.sql`の最小schemaは次のとおりである。P1-03で実装・再検証し、P1-01aで先取りしない。

```sql
CREATE TABLE turn_requests (
    request_key TEXT PRIMARY KEY,
    turn_request_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    root_turn_request_id TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'awaiting_player', 'committed', 'aborted')
    ),
    response_status_code INTEGER NULL,
    response_media_type TEXT NULL CHECK (
        response_media_type IN ('application/json', 'text/event-stream')
        OR response_media_type IS NULL
    ),
    response_body BLOB NULL,
    CHECK (
        (
            status = 'processing'
            AND response_status_code IS NULL
            AND response_media_type IS NULL
            AND response_body IS NULL
        )
        OR (
            status IN ('awaiting_player', 'committed', 'aborted')
            AND response_status_code IS NOT NULL
            AND response_media_type IS NOT NULL
            AND response_body IS NOT NULL
        )
    )
);

CREATE INDEX idx_turn_requests_campaign_turn_request_id
    ON turn_requests (campaign_id, turn_request_id);
```

このindexは`(campaign_id, turn_request_id)`の非unique indexであり、同一campaign内のcanonical request IDをDB-wide uniqueにはしない。identity列、`status`、response三列、`request_key` primary key、processing時のresponse全NULL、非processing completion時のresponse全NOT NULLをSQL CHECKで固定する。

**公開型とシグネチャ**

```python
from typing import Annotated

from pydantic import Field

RequestCompletionStatus = Literal["awaiting_player", "committed", "aborted"]
OpaqueRequestKey = StrictStr

class RequestKeyConflictError(ValueError):
    code: Literal["request_key_conflict"]

class RequestCompletionError(ValueError):
    code: Literal["request_not_found", "request_not_processing", "response_conflict"]

class CachedTurnResponse(ContractModel):
    status_code: int
    media_type: Literal["application/json", "text/event-stream"]
    body: StrictBytes

class TurnRequestIdentity(ContractModel):
    request_key: OpaqueRequestKey
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256

class ProcessingTurnRequestRecord(TurnRequestIdentity):
    status: Literal["processing"]
    response: None

class CompletedTurnRequestRecord(TurnRequestIdentity):
    status: RequestCompletionStatus
    response: CachedTurnResponse

TurnRequestRecord = Annotated[
    ProcessingTurnRequestRecord | CompletedTurnRequestRecord,
    Field(discriminator="status"),
]

class RequestClaim(ContractModel):
    type: Literal["new", "existing"]
    record: TurnRequestRecord

class ActiveTurnRegistry:
    def __init__(self) -> None: ...
    def register(self, request_key: OpaqueRequestKey) -> bool: ...
    def check(self, request_key: OpaqueRequestKey) -> bool: ...
    def release(self, request_key: OpaqueRequestKey) -> None: ...

class TurnRequestStore:
    def __init__(self, database: SqliteDatabase, event_store: EventStore) -> None: ...
    def claim(
        self,
        *,
        request_key: OpaqueRequestKey,
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
        *,
        request_key: OpaqueRequestKey,
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> CompletedTurnRequestRecord: ...
    def read(self, request_key: OpaqueRequestKey) -> TurnRequestRecord | None: ...

def build_started_events(
    *,
    metadata: TurnEventMetadata,
    input_digest: LowercaseSha256,
) -> EventBatch: ...

def build_resumed_event(
    *,
    metadata: TurnEventMetadata,
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
    record: ProcessingTurnRequestRecord,
    campaign_events: Sequence[DomainEvent],
) -> EventBatch: ...
```

`TurnRequestRecord`は`status`をdiscriminatorにしたunionであり、`ProcessingTurnRequestRecord`は`response=None`、`CompletedTurnRequestRecord`は`RequestCompletionStatus`と必須`response`だけを表す。`CachedTurnResponse.body`はUTF-8のcanonical JSONまたはSSE bytesであり、processing recordのresponseは常に`None`である。`complete()`の引数も`RequestCompletionStatus`だけなので、`processing`とresponseありを型上受け付けない。`request_key`はparseやcampaign prefixを持たないDB-wide opaque keyで、`turn_request_id`は`(campaign_id, turn_request_id)`のcampaign scopeで扱う。`RequestKeyConflictError`はcode `request_key_conflict`だけを、`RequestCompletionError`は`request_not_found`、`request_not_processing`、`response_conflict`のいずれかだけを外へ出す。

`ActiveTurnRegistry`は`src/neontof/application/turn_lifecycle.py`に置くprocess-lifetimeの具体実装であり、generic interfaceやprovider abstractionにしない。内部の単一lockで`register`、`check`、`release`の判定と集合変更をatomicに行う。`register(request_key)`は新規登録時だけ`True`、既にactiveなら`False`を返し、`release(request_key)`はactive集合から安全に除去する。`ApplicationRuntime`がこの一つのregistryを所有し、全request handlerとTurnEngineが同じinstanceを使う。

P1-03のlifecycle builderは`from neontof.event_metadata import EventBatch, RevertEventMetadata, TurnEventMetadata`でneutral metadataを参照する。`project_turn_status()`を変更せずreuseする。Event-derived `TurnStatus`がゲーム状態の権威であり、`TurnRequestStore`はHTTPの重複排除、processing claim、cached responseだけを持つ外部coordination recordで、Event Projectionへの入力にしない。

`PlayerInputAcceptedEvent`、`TurnAwaitingPlayerEvent`、`TurnResumedEvent`、`TurnCommittedEvent`、`TurnAbortedEvent`は、同じTurnなら全て`TurnEventMetadata.turn_request_id`をそのまま使う。`TurnAwaitingPlayer → TurnResumed`は同じ`turn_id`、同じcanonical `turn_request_id`であり、resume HTTPの新しい`request_key`はcoordination recordにだけ保存する。

`request_key`はDB-wide uniqueなopaque keyであり、`claim()`はlookupからinsert/既存record比較までを同じ`_write` transaction内で行う。内部claimはそのtransactionが受け取った同じSQLite connectionで`EventStore._read_campaign_on_connection(connection, campaign_id)`を呼び、EventStoreの別connection readやnested lockを起こさない。EventStore ownershipは変えず、TurnRequestStoreはそのprivate same-connection read helperをEvent-derived status/contextの検証にだけ使う。同じkeyが存在する場合は、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`root_turn_request_id`、canonical `turn_request_id`、`input_digest`を全て完全照合する。一つでも不一致ならcached bodyを返さず、値・SQLite messageを含まない`RequestKeyConflictError(code="request_key_conflict")`を返す。同一identityなら既存recordを返し、cached responseがあれば`status_code`、`media_type`、UTF-8 canonical JSON/SSE `body` bytesをbyte-for-byteで返す。Dice、Provider、Event appendは再実行しない。`scene_id`と`input_digest`はclaim時に保存し、同じcanonical `turn_request_id`のrecoveryへ渡す。`processing` recordの再送は、既存のTurn status parserのEvent順序で再構築したstatusを使い、次のrecovery ruleに従う。request key mismatchの比較結果やcached bodyをconflict errorへ含めない。`request_key`のDB-wide unique制約と、canonical requestのcampaign scopeは別であり、resumeの新しい`request_key`が同じ`(campaign_id, turn_request_id)`を参照できるよう、後者をDB-wideの一意制約へ置き換えない。

resumeで新しい`request_key`を使う場合は、`turn_request_id`のcampaign scope、`root_turn_request_id`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、現在のEvent-derived statusを同じclaim transaction内で検証してからrecordをinsertする。これにより、同じcanonical requestを正しい文脈でresumeすることだけを許可し、別campaign/別session/別scene/別turnへの再利用を拒否する。`TurnAwaitingPlayer`から`TurnResumed`へは同じTurn、同じcanonical `turn_request_id`を使い、resumeの新しい`request_key`はcoordination recordにだけ保存する。

`complete()`は`request_key`をprocessing recordに対してcompare-and-setする。同じ`_write` transaction内でrecordを読み、missingなら`RequestCompletionError(code="request_not_found")`を返す。現在のrecordがprocessingならresponse三列を同時に書いてcompletionへ更新し、processing時response全NULL、completion時response全NOT NULLを維持する。現在のrecordが非processingでstatus・media type・body bytesの全てが同一ならidempotentに既存`CompletedTurnRequestRecord`を返す。既完了recordのbody bytesが異なる場合は`RequestCompletionError(code="response_conflict")`、statusまたはmedia typeが異なる場合と不正な非processing recordは`RequestCompletionError(code="request_not_processing")`とし、cached bodyや比較値を返さない。missing、非processing、response conflictのmessageは固定文面とし、SQLite exceptionやidentityの値を漏らさない。

- Event-derived statusに`TurnCommitted`または`TurnAborted`が既にあれば、Event / Projectionからresponseを再構築して一度だけcacheし、Providerを再呼出ししない。
- persisted `processing` recordの再送では、まず`ActiveTurnRegistry.check(request_key)`を確認する。activeならprocessing responseだけを返し、Provider、Dice、Event append、crash recoveryを実行しない。activeでない場合だけ`register(request_key)`をatomicに行い、登録に成功した一つの実行者だけをcrash orphanとして一度だけrecoveryする。処理終了時は`release(request_key)`をatomicに行う。
- claim後の最初のEventがまだ無く、Event Logに同Turnの`PlayerInputAccepted`が無ければ、`TurnRequestRecord`の`campaign_id`、`session_id`、`scene_id`、`turn_id`、canonical `turn_request_id`、`input_digest`から`PlayerInputAccepted` draftを作り、その直後に`TurnAborted(reason="failed")` draftを置いた同一`EventBatch`をappendする。部分的な再実行やprovider retryは行わない。
- terminal Eventが無く、Event Logに同Turnの`PlayerInputAccepted`が既にあれば、recordのcanonical `turn_request_id`に一致する許可済みの`TurnAborted(reason="failed")` draftだけを同一batchへ置いてappendする。`PlayerInputAccepted`を二重作成しない。
- `TurnResumed`後のrunning crash windowはEvent-derived statusがrunningであることを確認して`TurnAborted`だけをappendする。`TurnAwaitingPlayer`後はawaiting responseを再構築してcacheし、入力を勝手にabortまたは再送しない。terminal後は既存terminal responseを再構築してcacheし、Eventを追加しない。
- `TurnAwaitingPlayer`のcached responseはそのまま返す。ユーザー入力を続けるresumeは同じTurnのcanonical request IDをLifecycle Eventへ渡し、外部dedupe用に新しい`request_key`を使う。

`build_started_events()`は初回の`PlayerInputAccepted` draftと`TurnResumed` draftだけをこの順序で同じ`EventBatch`へ置き、canonical `turn_request_id`と`input_digest`を検証する。resumeでは`build_resumed_event(metadata)`だけを使い、二つ目の`PlayerInputAccepted`を作らない。`build_awaiting_event()`とterminal builderも同じmetadataと既存status parserの許可された遷移だけを使う。`build_crash_recovery_batch()`のrecord引数は`ProcessingTurnRequestRecord`に限定し、`campaign_events: Sequence[DomainEvent]`にはturn sliceを渡さずcampaign全体のvalidated Event列を渡す。Request storeのwriteはEvent Storeのappend transactionとは別であり、Turn statusのauthorityではない。`ObservationStore.session_cost_microusd(campaign_id, session_id)`と、後続P1-06の`SessionBudget.campaign_id`を含むbudget scopeはcampaignを必須とする。これらのdedupe/recovery/context契約はP1-03側で実装・再検証し、P1-01aへ先取りしない。

**テストファースト**

- `test_new_request_is_claimed_once`
- `test_duplicate_processing_request_returns_existing_record`
- `test_request_key_is_database_wide_and_opaque`
- `test_request_key_conflict_compares_full_identity`
- `test_request_key_conflict_is_sanitized_and_does_not_return_cached_body`
- `test_request_key_conflict_does_not_expose_identity_or_cached_body`
- `test_canonical_turn_request_id_is_campaign_scoped`
- `test_duplicate_committed_request_returns_cached_response`
- `test_cached_response_replays_status_media_type_and_body_exactly`
- `test_cached_response_body_is_utf8_canonical_json_or_sse_bytes`
- `test_complete_missing_request_raises_request_not_found`
- `test_complete_non_processing_raises_safe_error`
- `test_complete_same_response_is_idempotent`
- `test_complete_conflicting_response_raises_response_conflict`
- `test_ambiguous_input_enters_awaiting_player_without_effect_events`
- `test_resume_uses_same_turn_id`
- `test_resume_uses_same_canonical_turn_request_id`
- `test_resume_uses_new_request_key_for_same_canonical_request`
- `test_resume_does_not_append_second_player_input_accepted`
- `test_build_resumed_event_emits_only_turn_resumed`
- `test_resume_context_is_validated_inside_claim_transaction`
- `test_processing_record_cannot_carry_response`
- `test_complete_cannot_accept_processing_status`
- `test_processing_crash_recovers_without_provider_reinvocation`
- `test_active_turn_registry_register_check_release_are_atomic`
- `test_active_processing_replay_only_returns_processing_response`
- `test_persisted_processing_without_active_registry_recovers_once`
- `test_active_processing_barrier_does_not_recover_or_duplicate_work`
- `test_claim_before_first_event_recovers_with_accepted_then_aborted_batch`
- `test_crash_after_player_input_accepted_appends_only_authorized_abort`
- `test_crash_after_turn_resumed_uses_event_derived_running_status`
- `test_crash_after_terminal_replays_terminal_without_append`
- `test_crash_after_awaiting_player_rebuilds_awaiting_response`
- `test_recovery_uses_existing_turn_status_parser_order`
- `test_processing_replay_with_committed_event_caches_rebuilt_response`
- `test_latest_committed_turn_can_be_reverted`
- `test_non_latest_turn_cannot_be_reverted`
- `test_duplicate_request_rolls_dice_once`
- `test_duplicate_request_invokes_model_once`
- `test_migration_0004_creates_only_turn_requests`
- `test_turn_requests_schema_has_identity_response_and_status_constraints`
- `test_schema_set_maximum_is_four_without_gap_or_unknown_version`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/application/test_turn_lifecycle.py tests/persistence/test_turn_request_store.py tests/integration/test_turn_idempotency.py tests/test_repository_contracts.py -q
```

実装前のfocused commandではmissing module、`0004_turn_requests.sql`のschema-set assertion、manifest追記漏れ、未許可path、full identity conflict、resume context transaction、processing/response type invariant、ActiveTurnRegistryのbarrier、またはduplicate requestでcall count `2`に対し`1`期待を失敗理由として確認する。

**完了条件**

`0004_turn_requests.sql`が`turn_requests`だけをadditiveに作り、全identity列、`status`、response三列、`request_key` primary key、`(campaign_id, turn_request_id)`の非unique index、processing時response全NULL、completion時response全NOT NULLのCHECKを持つ。schema-set最大versionが4、1→4の連番、unknown versionなし、raw SQL bytes checksum一致を示す。`request_key`のDB-wide uniquenessとcanonical requestのcampaign scopeはこのschemaとStore contractで再検証する。

同じRequestを2回送ったfixtureで次が成立する。

```text
model_logical_calls=1
dice_rolls=1
player_input_accepted_events=1
turn_committed_events=1
```

recovery testでは、claim-before-first-eventが`PlayerInputAccepted`→`TurnAborted`の2 draftを1 batchでappendし、after-accepted/after-resumedは`TurnAborted`だけ、after-`TurnAwaitingPlayer`はawaiting responseのcache、after-terminalはEvent追加なしとなる。各分岐は`TurnRequestStore.status`ではなくcampaign全体を渡す`build_crash_recovery_batch(..., record: ProcessingTurnRequestRecord, campaign_events: Sequence[DomainEvent])`と既存のEvent-derived status parserの順序、canonical `turn_request_id`で決める。same-keyの全identity照合、conflict時のcached body非返却、resumeの新request key・campaign context transaction検証、processing/response invariant、ActiveTurnRegistryのactive replay/orphan一度だけrecovery、`tests/test_repository_contracts.py`のmanifest/forbidden guardが同じcommandでexit `0`となる。barrier testの固定結果は`Provider=1`、`Dice=1`、`PlayerInputAccepted=1`、`abort=0`である。

**契約確認点**

C-01 decision gateがユーザー承認済みでない場合、P1-03の実装を開始しない。follow-up requestを新しい`PlayerInputAcceptedEvent`として暗黙に追加したり、model由来clarificationをpre-model ambiguityへ置き換えたりしない。承認後も、選択された契約に一致するEvent sequence、request ID、call count testだけを実装し、Phase 0 contractをこの計画から変更しない。

**コミット境界**

```powershell
git add -- src/neontof/application/__init__.py src/neontof/application/turn_models.py src/neontof/application/turn_lifecycle.py src/neontof/persistence/turn_request_store.py src/neontof/persistence/migrations/0004_turn_requests.sql tests/application/test_turn_lifecycle.py tests/persistence/test_turn_request_store.py tests/persistence/test_migrations.py tests/integration/test_turn_idempotency.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-01 decision gate承認後、P1-02のcommit、`0004` schema-set、DB-wide opaque request key、full identity conflict、campaign-scoped canonical request、resume context transaction、processing/response invariant、campaign-wide recovery、ActiveTurnRegistry barrier、idempotency focused commandがfailure `0`になった後、上記pathのtests、migration、implementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Request IDで直列化するTurn状態機械を追加する
```

---

## P1-04: Minimal RulesとDice

**作成**

- `src/neontof/rules/__init__.py`
- `src/neontof/rules/minimal_2d6.py`
- `tests/rules/test_minimal_2d6.py`
- `tests/rules/test_rule_effect_validation.py`

**変更**

- `tests/test_repository_contracts.py`

P1-04のproduction manifest追加は`src/neontof/rules/__init__.py`と`src/neontof/rules/minimal_2d6.py`だけである。P1-04はrulesとdeterminismだけを担当し、`event_metadata`、`EventMaterializationInput`、`TurnEventMetadata`をimportしない。

**公開型とシグネチャ**

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

**テストファースト**

- `test_same_inputs_produce_same_seed_and_dice`
- `test_different_roll_index_changes_seed`
- `test_global_random_state_does_not_affect_result`
- `test_result_is_between_two_and_twelve`
- `test_resource_change_cannot_cross_zero_or_maximum`
- `test_rules_module_does_not_import_event_metadata`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/rules tests/test_repository_contracts.py -q
```

期待REDはmissing module。skeleton後は再現性testで異なるdiceとなる失敗。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。固定fixtureを2回実行した`derived_seed`、`formula`、`result`が一致し、resultはEventのauthoritative fieldsだけから再計算可能である。manifest/forbidden guardの未登録production pathも検出されない。

**コミット境界**

```powershell
git add -- src/neontof/rules/__init__.py src/neontof/rules/minimal_2d6.py tests/rules/test_minimal_2d6.py tests/rules/test_rule_effect_validation.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、P1-00のneutral metadataを除くApplication依存がないことを確認した後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: 再現可能な最小Rulesetと資源境界を実装する
```

---

## P1-05: CharacterとScenarioの読み込み

### 依存更新

`PyYAML==6.0.3`を`requirements-dev.in`から`requirements.in`へ移す。production Character / Scenario loaderがYAMLを読むためである。`types-PyYAML`は`requirements-dev.in`に残す。`requirements.lock.txt`をhash付きで再生成する。他のPython dependencyを追加しない。

**作成**

- `src/neontof/authoring/__init__.py`
- `src/neontof/authoring/yaml_loader.py`
- `src/neontof/authoring/character_loader.py`
- `src/neontof/authoring/scenario_loader.py`
- `src/neontof/authoring/bootstrap.py`
- `tests/authoring/test_yaml_loader.py`
- `tests/authoring/test_character_loader.py`
- `tests/authoring/test_scenario_loader.py`
- `tests/authoring/test_bootstrap_events.py`

**変更**

- `requirements.in`
- `requirements-dev.in`
- `requirements.lock.txt`
- `tests/test_repository_contracts.py`

P1-05のproduction manifest追加は`src/neontof/authoring/__init__.py`、`src/neontof/authoring/yaml_loader.py`、`src/neontof/authoring/character_loader.py`、`src/neontof/authoring/scenario_loader.py`、`src/neontof/authoring/bootstrap.py`の5つである。`src/neontof/authoring/bootstrap.py`は`from neontof.event_metadata import EventBatch`と必要なneutral metadata型をimportする。

**公開型とシグネチャ**

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

`src/neontof/authoring/bootstrap.py`は`from neontof.event_metadata import EventBatch`と必要なneutral metadata型をimportし、`build_bootstrap_events()`はcaller-assigned sequenceを持たない`EventBatch`を返す。

### Phase 1 input・ID・Fact・authority契約

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

**テストファースト**

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

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring tests/test_repository_contracts.py -q
```

期待REDはmissing module。bootstrap skeleton後はProjectionのHP / location / secret Fact不足でassertion failure。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。bootstrap Event列を`rebuild_projection()`へ渡し、Character current HP、Resource、Location、Clock、Scenario ID、Scene ID、Factが期待値と一致する。manifest追記漏れと未許可pathがないことも同じcommandで確認する。

**Lockコマンド**

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

**コミット境界**

```powershell
git add -- src/neontof/authoring/__init__.py src/neontof/authoring/yaml_loader.py src/neontof/authoring/character_loader.py src/neontof/authoring/scenario_loader.py src/neontof/authoring/bootstrap.py tests/authoring/test_yaml_loader.py tests/authoring/test_character_loader.py tests/authoring/test_scenario_loader.py tests/authoring/test_bootstrap_events.py requirements.in requirements-dev.in requirements.lock.txt tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、上記pathのtestsとimplementation、依存更新を1つのlogical GREEN commitへまとめ、ScenarioV1/CharacterSheetV1 input、stable ID、Fact schema、bootstrap clock/authority、fresh lock install、focused authoring commandを確認して着地させる。

```text
feat: CharacterとScenarioをEventへ正規化する
```

---

## P1-06: Model Gateway

**作成**

- `src/neontof/model/gateway_models.py`
- `src/neontof/model/gateway.py`
- `tests/model_gateway/test_gateway_budget.py`
- `tests/model_gateway/test_gateway_retry.py`
- `tests/model_gateway/test_gateway_security.py`
- `tests/model_gateway/test_gateway_fake_provider.py`

**変更**

- `tests/test_repository_contracts.py`

P1-06のproduction manifest追加は`src/neontof/model/gateway_models.py`と`src/neontof/model/gateway.py`の2つである。

**公開型とシグネチャ**

```python
class SessionBudget(ContractModel):
    campaign_id: CampaignId
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

**テストファースト**

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

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/model_gateway tests/test_repository_contracts.py -q
```

実装前のfocused commandではmissing moduleを、gateway skeleton後はprovider call count `2`に対する`1`期待またはC-03 conditional provider-boundary assertion未実装を失敗理由として確認する。C-03で選択した契約に対応するtest/signatureが成立するまで、P1-06を完了扱いにしない。

**完了条件**

```text
max_attempts_observed=1
logical_model_calls_per_turn=1
provider_invocations_per_turn=1
budget_checked_before_call=True
secret_hits=0
```

に相当するassertionが全てpassし、provider直前の実際のrequestがpublic-onlyで`gm_only`を含まず、callerの`player_input`と`dice_result`が到達する。C-03で承認された契約をP1-06の型、signature、Fake / Recorded Gateway、testへ反映する。provider approvalが完了するまでconcrete real Provider adapterを実装、GREEN、commit扱いにしない。
`tests/test_repository_contracts.py`のmanifest/forbidden guardも同じcommandでexit `0`となる。

### C-03判断Gate — Provider request boundary

既存P0の`ModelRequest`は`context: tuple[FactRecord, ...]`だけを持ち、`player_input`と`dice_result`を表せない。`src/neontof/model/model_invoker.py`、`fake_provider.py`、`recorded_fixture.py`、既存`tests/model/**`はP1-06のForbidden pathであり、現契約だけでは、`ModelGateway`から既存providerの最終invoke境界へ秘密を渡さずにplayer inputとdiceを到達させるenvelope/mappingを確定できない。

C-03では次のいずれかをユーザーが明示承認し、選択された契約をP1-06の型、signature、dependency、testへ反映する。concrete real Provider adapterはprovider approvalが完了するまで開始しない。

1. **既存P0 ModelRequest契約を上位改訂する:** `ModelRequest`へplayer input/diceを表す既存契約準拠のfieldまたはcontext mappingを追加し、`model_invoker.py`、provider境界、既存model test、schema/validator、依存する上位文書の変更範囲を列挙して承認する。Phase 1 planからForbidden pathを直接編集せず、上位改訂を先に完了する。
2. **Phase 1の明示承認済みProviderRequest adapterとFake adapterを追加する:** `GatewayRequest`からpublic-onlyの最終envelopeを作るadapterを新設し、既存TestProvider境界へplayer input/diceを安全にmappingする。adapterのpath、signature、dependency、Fake adapter、provider spy test、secret boundary、staging pathをP1-06の契約として固定する。二つ目のProvider abstractionやregistryは作らない。

各選択肢の影響は、P0 `ModelRequest`のschema、既存invoke境界、provider spyの入力shape、Fake/Recorded fixtureのmapping、Forbidden pathの扱い、依存とtest pathに及ぶ。承認だけで曖昧な実Provider実装を開始しない。固定responseで`player_input`または`dice_result`を無視する方式は、Phase 1 completionとしない。

Provider approval後、C-03の選択に対応するconcrete real Provider adapterのexact path、signature、dependency、test path、git add pathをこの計画のP1-06契約へ反映する。Fake/Recorded Gatewayのlocal implementationとvalidationはC-03 contract approval後に先行できるが、承認されたexact contractが計画・実装・検証へ反映されるまでconcrete real Provider adapterを実装、GREEN、commitしない。

### Provider選定とapproval停止点（必須）

Roadmap P1-06の成果物は、Fake / Recorded Fixtureと交換可能な**一つの具体的な実Provider adapter**である。Fake-onlyではP1-06またはPhase 1を完了扱いにしない。

先にC-03でprovider request boundaryの方式を承認する。その後、Fake / Recorded Gateway、gateway budget、security、`max_attempts=1`、runtime testをAPI keyなし・external networkなしで実装し、normal invocation `1`、zero retry、C-03 contract approvedの条件でFake/Recorded GREENを確認する。Fake / Recordedのlocal validationはprovider approval前も続けてよい。Fake/Recorded GREENを確認した後、実Provider adapterと実行に必要なexact adapter path、signature、dependency、test path、git add pathをこの計画へ反映し、provider approval後にconcrete real Provider adapter 1つを実装する。

1. concrete Provider名
2. SDK名とversion、またはHTTP clientを使う場合の根拠
3. API key source（Browser、通常ログ、prompt、fixture、responseへ渡さないことを含む）
4. 想定costとsession budget
5. network destinationとdata visibility
6. 通常Turnの最大provider invocation数（`1`）とtimeout/error時のretry数（`0`）

provider approval前はSDK dependency、key reader、external HTTP call、concrete real Provider adapter、実Provider testを追加しない。provider approval後も、C-03で承認されたexact path/signature/dependency/test path/git add pathがこの計画・実装・検証へ反映されるまで実装しない。承認内容が既存契約またはこのplanの署名を変える場合は、実装せず上位文書の判断を求める。Fake / Recordedのlocal testはAPI key/networkなしでC-03 contract approval後に実行でき、provider approval前も継続してよい。C-03とprovider approvalの選択に対応しないconcrete real Provider adapterのGREEN/commitやPhase 1 completionは認めない。

**コミット境界**

```powershell
git add -- src/neontof/model/gateway_models.py src/neontof/model/gateway.py tests/model_gateway/test_gateway_budget.py tests/model_gateway/test_gateway_retry.py tests/model_gateway/test_gateway_security.py tests/model_gateway/test_gateway_fake_provider.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-03承認後、上記pathのFake/Recorded testsとimplementationを一つのlogical GREEN commitへまとめる。Fake/Recorded GREEN、provider approval、C-03で承認されたexact pathの確定後に、real adapter/test pathを明示して別のlogical GREEN commitへまとめる。承認されていないpathのconcrete real Provider adapterはGREEN/commit扱いにしない。

```text
feat: Model Gatewayの予算と安全なProvider境界を実装する
```

---

## P1-07: Context BuilderとEvidence Validation

**作成**

- `src/neontof/application/context_builder.py`
- `src/neontof/application/entity_resolver.py`
- `tests/application/test_context_builder.py`
- `tests/application/test_entity_resolver.py`
- `tests/integration/test_evidence_validation.py`

**変更**

- `tests/test_repository_contracts.py`

P1-07のproduction manifest追加は`src/neontof/application/context_builder.py`と`src/neontof/application/entity_resolver.py`の2つである。

**公開型とシグネチャ**

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

`build_context(..., publication_visibility="player_visible")`はactiveかつ`player_visible`のFactだけをtyped `PublicProjection`へ投影し、`subject_id=None`のpublic Factも落とさずに`PublicContext`を先に作る。secretを一度入れてから削除する方式ではなく、最初から選択しない。resources、locations、clocks、facts、campaign/session/scene/turn/request identifiersはEvent replay由来のtyped projectionとして明示する。full `Projection`はsemantic validationの内部入力に限り、Model Gateway、public HTTP view、Narrative auditへ渡さない。これらのsignatureは`PublicContext`または`PublicProjection`だけを受け取る。 `PublicProjection`を組み立てるcallerは、必ず`EventStore.read_campaign(campaign_id)`の全列からrebuildしたprojectionを渡す。filtered event tuple、snapshot、observation、coordination recordを入力にしない。対象外rowが壊れている場合も`read_campaign()`のfail-closedを伝播させる。

Entity resolutionはUnicode NFKC、casefold、前後空白除去後のcanonical name / exact alias一致だけを使う。曖昧な場合は複数候補を返し、推測しない。自由文からstate effectを生成しない。

Evidenceは既存`validate_semantic_result()`によりfact existence、visibility、predicate/value一致を検証する。

**テストファースト**

- `test_player_context_contains_only_player_visible_facts`
- `test_subjectless_public_fact_is_retained`
- `test_gm_only_fact_never_enters_intermediate_context_bundle`
- `test_context_digest_is_deterministic`
- `test_unknown_past_returns_undetermined_fixture`
- `test_unknown_past_provider_spy_cannot_read_or_mutate_context`
- `test_public_context_does_not_expose_full_projection`
- `test_public_projection_contains_event_derived_resources_locations_clocks_and_turn_ids`
- `test_public_projection_uses_complete_campaign_event_read`
- `test_public_projection_fails_closed_on_corrupt_out_of_scope_event`
- `test_public_static_data_contains_only_allowed_character_and_scenario_values`
- `test_zero_clock_is_registered_as_known_clock`
- `test_invisible_evidence_is_rejected`
- `test_claim_mismatch_is_rejected`
- `test_alias_resolves_to_stable_entity_id`
- `test_ambiguous_alias_returns_all_candidates`
- `test_unknown_alias_does_not_guess`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_context_builder.py tests/application/test_entity_resolver.py tests/integration/test_evidence_validation.py tests/test_repository_contracts.py -q
```

期待REDはmissing module。visibility filter skeleton後はsecret sentinelがContextに存在するassertion failure。

**完了条件**

- secret sentinel hit `0`
- unknown history fixtureのNarrativeまたはrejectionが「未決定」
- invisible Evidence outcomeが`RejectedSemanticResult`
- Alias resolutionが同じstable ID
- `tests/test_repository_contracts.py`のmanifest/forbidden guardがexit `0`

**コミット境界**

```powershell
git add -- src/neontof/application/context_builder.py src/neontof/application/entity_resolver.py tests/application/test_context_builder.py tests/application/test_entity_resolver.py tests/integration/test_evidence_validation.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、`ApplicationRegistry`、known clock ID `0`、PublicContext/PublicProjection、provider spy/sabotage、Evidence validationのfocused commandがfailure `0`になった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Visibility Filter、PublicProjection、Evidence validation、Alias解決を追加する
```

---

## P1-08: Semantic Result Pipeline

**作成**

- `src/neontof/application/event_materializer.py`
- `src/neontof/application/semantic_pipeline.py`
- `src/neontof/application/turn_engine.py`
- `tests/application/test_event_materializer.py`
- `tests/application/test_semantic_pipeline.py`
- `tests/integration/test_complete_fake_turn.py`
- `tests/integration/test_model_failure_atomicity.py`

**変更**

- `tests/test_repository_contracts.py`

P1-08のproduction manifest追加は`src/neontof/application/event_materializer.py`、`src/neontof/application/semantic_pipeline.py`、`src/neontof/application/turn_engine.py`の3つである。P1-08のpayload boundary checkpointと既存`FrozenJsonValue`のcomposite value round-trip開始前stopは維持し、P1-00で推測実装しない。

**公開型とシグネチャ**

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
    request_key: OpaqueRequestKey
    turn_request_id: TurnRequestId
    input_text: str

class ResumeTurnCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    request_key: OpaqueRequestKey
    root_turn_request_id: TurnRequestId
    turn_request_id: TurnRequestId
    input_text: str

class TurnExecutionResult(ContractModel):
    turn_id: TurnId
    turn_request_id: TurnRequestId
    request_key: OpaqueRequestKey
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
        active_turn_registry: ActiveTurnRegistry,
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

`EventMaterializationInput`はP1-00のneutral typeをimportして使い、P1-08で再定義しない。`materialize_accepted_result()`はcaller-assigned sequenceを持たない`EventBatch`を返し、`materialize_dice_event()`は未採番`EventDraft`を返す。`EventStore.append()`がsequence割当、既存DomainEvent parserによる再構築・再検証、全batch appendを同じtransactionで行う。P1-08のproducerは`DomainEvent`または`tuple[DomainEvent, ...]`を返さない。DiceのmaterializationとEvent replay projectionはP1-08の責務である。`rebuild_dice_projection(events: Sequence[DomainEvent])`のcallerは`EventStore.read_campaign(campaign_id)`の完全列だけを渡し、filtered event slice、snapshot、coordination record、observationを渡さない。`DiceProjection.rolls`と`DiceResult`は`DiceRolledPayload`の`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけをauthoritative fieldsとして保持する。対象外の壊れたEvent rowは`read_campaign()`のfail-closedで止める。

`P1-08`は`from neontof.event_metadata import EventBatch, EventDraft, EventMaterializationInput`でneutral typeをimportする。

### Payload boundary確認点

既存`FrozenJsonValue`のcomposite value round-tripをP1-00で推測実装しない。P1-08がsemantic resultのpayloadをlosslessにmaterializeするために既存Phase 0 semantic contractでは不足すると判明した場合、P1-08開始前に停止し、Phase 0 semantic contractの改訂または別の承認済みraw boundaryの確定を待つ。この計画からProduct Plan、ROADMAP、ADR、P0契約本文は変更しない。

Pipeline順序を固定する。

1. Player InputをTranscriptへappendする。
Player InputのTranscript appendはEvent append critical sectionの外で別の`_write` transactionとして行い、後続失敗でEventが0件でも観測記録を残せるようにする。
2. 外部`request_key`をclaimし、`EventStore.read_campaign(campaign_id)`の完全列からEvent-derived `TurnStatus`を確認する。filtered turn sliceやcoordination statusをauthorityにしない。
3. Alias / targetをdeterministicに解決する。
4. ambiguousならmodel call前に`awaiting_player` Event batchをappendする。
5. public Contextを構築する。
6. deterministic diceを解決する。
7. budgetを確認する。
8. Gatewayを1 logical call、provider invocation 1回だけ実行する。
9. request / response / timeout / error / usageをpurpose-specific allowlistでTranscript / Telemetryへ記録する。appendはEvent append critical sectionの内側で呼ばず、別の`_write` transactionとする。raw provider body/error/causeは保存しない。retry recordはPhase 1通常Turnでは作らない。
10. `validate_semantic_result()`を実行する。
11. Rule、reference、Evidence、Visibilityを検証する。
12. accepted proposal、Dice、Fact、lifecycle Eventを1 `EventBatch`へmaterializeする。
13. `EventStore.append(batch)`を1回だけ呼ぶ。sequence割当を別APIで呼ばない。
14. `EventStore.read_campaign(campaign_id)`の完全列からProjectionをrebuildする。filtered slice、snapshot、coordination record、observationを入力にしない。
15. validated Narrativeを公開候補にする。
16. post-public audit結果をcorrectionとして記録する。
17. semantic result、narrative、state、correction、doneを含む全frameを一つのcanonical frame bodyとして完成させ、選択されたJSONまたはSSE表現のUTF-8 bytesを作る。
18. `TurnRequestStore.complete(*, request_key=..., status=..., response=CachedTurnResponse(...))`でcache commitを完了する。cache commit前にHTTP adapterへframeを渡さない。
19. cache commit後だけHTTP adapterへ公開する。SSEとbufferedは同じ完成済みframe bodyから生成し、replayはcache済み`status_code`、`media_type`、body bytesをbyte-for-byteで返す。replayでProvider、Dice、Event append、frame再生成を行わない。

`ProposedResourceChanged`、`ProposedCharacterMoved`、`ProposedClockAdvanced`、`ProposedFact`だけをmaterializeする。不明Event typeを追加しない。

**テストファースト**

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
- `test_all_frames_complete_before_turn_request_cache_commit`
- `test_turn_request_cache_commits_before_http_publication`
- `test_sse_and_buffered_use_the_same_completed_frame_body`
- `test_cached_replay_is_byte_for_byte_without_execution`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py tests/test_repository_contracts.py -q
```

実装前のfocused commandではmissing moduleを、atomicity実装途中では1件以上のeffect Eventが残り期待`0`となるassertion failureを確認する。cache commit前公開、SSE/buffered同一body、byte-for-byte replayの境界も失敗理由として確認する。

**完了条件**

- valid Fake turnが`committed`
- invalid Eventが`rejected`または`aborted`
- failure時effect Event count `0`
- Narrative-only時Resource / Location / Clock / Fact projectionが不変
- 全frameのcanonical body完成後に`TurnRequestStore.complete()`が呼ばれ、cache commit後だけHTTP adapterが公開する
- SSEとbufferedが同じ完成済みframe bodyから生成され、replayがcache body bytesをbyte-for-byteで返す
- Suggested Actionsが2〜4件
- `tests/test_repository_contracts.py`のmanifest/forbidden guardがexit `0`

**契約確認点**

C-01 decision gateが未承認なら、P1-08の`clarification_request`実装、同じTurnのresume sequence、該当fixtureを開始しない。pre-model ambiguityだけに変換したり、model由来clarificationをtest-onlyへ限定したりしない。C-01承認後に限り、選択された影響範囲をこのWPのtype/signature/testへ反映する。Phase 0 contractの変更はこの計画から行わない。

**コミット境界**

```powershell
git add -- src/neontof/application/event_materializer.py src/neontof/application/semantic_pipeline.py src/neontof/application/turn_engine.py tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-01 decision gateが承認済みで、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。focused commandのfailure `0`、Event batch atomicity、dice replay、normal provider invocation count `1`、cache commit前公開なし、byte-for-byte replayを確認して着地させる。

```text
feat: 検証済みproposalだけをatomic appendするTurn Engineを実装する
```

---

## P1-09: provisional_detail Projection

**作成**

- `src/neontof/application/provisional_details.py`
- `tests/application/test_provisional_details.py`
- `tests/integration/test_provisional_detail_lifecycle.py`

**変更**

- `tests/test_repository_contracts.py`

P1-09のproduction manifest追加は`src/neontof/application/provisional_details.py`だけである。

P1-09は`from neontof.event_metadata import EventBatch, EventMaterializationInput`でneutral typeをimportする。

### C-02判断Gate — provisional_detail ID and Fact contract

既存semantic resultの`ProvisionalDetail.id`は`EntityId | NpcId`である。一方、Product Planの例は`pd:scene:...`で、既存validatorはknown Entity/NPCを要求する。この差を、`FactId`への置換や既知Entityの偽装で上位文書変更なしに黙って回避しない。

P1-09開始前にユーザーが次の選択肢のいずれかを明示承認するまで、type、ID、Fact schema、first-mentioned testを実装しない。

1. **既存ID contractを維持する:** `ProvisionalDetail.id`をknown `EntityId | NpcId`として扱う。`pd:scene:...`のProduct Plan例をどう解釈するか、またはPhase 1対象から外すかを上位文書で判断する。
2. **専用provisional IDを導入する:** `ProvisionalDetailId`と`pd:scene:...`形式を正式化し、semantic contract、validatorのknown-ID規則、Fact predicate/value schema、Product Plan例を改訂する。改訂なしには実装しない。
3. **P1-09を延期する:** provisional detailをPhase 1 Gateから外し、first-mentioned acceptanceを後続Phaseへ移す。

C-02承認後だけ、承認内容に対応する`ProvisionalDetail` type、stable ID mapping、`provisional_detail` Fact predicate/value schema、`test_first_mentioned_detail_uses_approved_id_schema`をこのWPへ追加する。承認前のP1-09は停止し、他のWPがこの未決定型へ依存しないようにする。

**公開型とシグネチャ**

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

**テストファースト**

- `test_mentioned_bookshelf_is_available_next_turn`
- `test_materialize_provisional_details_returns_unassigned_event_batch`
- `test_first_mentioned_detail_uses_approved_id_schema`
- `test_narrative_without_mentioned_detail_creates_nothing`
- `test_exact_label_reference_promotes_detail`
- `test_conflicting_canon_is_not_overwritten`
- `test_unreferenced_detail_disappears_after_scene_end`
- `test_transcript_retains_detail_after_scene_end`
- `test_gm_only_provisional_detail_never_enters_player_context`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py tests/test_repository_contracts.py -q
```

期待REDはmissing module、manifest追記漏れ、未許可path。scene filter未実装時は終了Sceneのdetail件数`1`に対し`0`期待の失敗。

**完了条件**

本棚fixtureで、次Turnに1件、昇格後canonical 1件、Scene終了後provisional 0件、Transcript narrative 1件が成立し、`tests/test_repository_contracts.py`のmanifest/forbidden guardもexit `0`となる。

**契約確認点**

C-02が未承認なら、P1-09のfocused testをGREENにせず、`ProvisionalDetail.id`、reserved Fact value、first-mentioned fixtureを決めない。C-02承認後にだけ承認済みschemaでtest-firstを再開する。

**コミット境界**

```powershell
git add -- src/neontof/application/provisional_details.py tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-02 decision gate承認後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめ、first-mentioned test、Fact schema、scene lifetime、conflict handlingのfocused commandを確認して着地させる。

```text
feat: Event由来のprovisional detail Projectionを追加する
```

---

## P1-10: Minimal Browser Client

### P1-10a — Client scaffold

**作成**

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

**変更**

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

**公開TypeScript型**

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

**テストファースト**

- `scaffold.spec.ts`でVite dev/preview serverのroot page、input、submit button、status regionのDOM scaffold存在を先に要求する。FastAPI、`/health`、readiness、static routeはこのWPの入力にしない。
- TypeScriptでunknown frame typeをexhaustive switchによりcompile errorへする。
- P1-00bのrepository guardがclient許可path、generated path、DB禁止、Python gate order、Windows runner assertionを検査する。

**実装前の検証条件**

```powershell
npm --prefix client ci
npm --prefix client run typecheck
npm --prefix client run build
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
npm --prefix client run test -- scaffold.spec.ts
```

package未作成時の最初のREDは`ENOENT: no such file or directory, open 'client/package.json'`。scaffold後はmissing DOM element testがfailする。Vite dev/preview serverの起動・readiness・cleanupはPlaywright `webServer`設定で扱い、FastAPI health endpoint未実装をRED理由にしない。

**完了条件**

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

exit `0`、P1-00bのrepository guard testもexit `0`、`client/dist`と`client/node_modules`は生成物としてstatusへ残さずcommitしない。P1-10aはproduction `.py`を作らず、production manifestを増やさない。DB fileをrepository treeへ作らない。CIでもこのguardをclient quality gateと同じ順序で実行し、node/npmはCIから拒否されず、Python gate orderとWindows runner assertionは維持される。

### ブラウザGate: Vite dev/preview scaffold

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

**コミット境界**

```powershell
git add -- .node-version client/package.json client/package-lock.json client/tsconfig.json client/vite.config.ts client/index.html client/src/main.ts client/src/api.ts client/src/models.ts client/src/styles.css client/tests/scaffold.spec.ts client/playwright.config.ts .gitignore .github/workflows/ci.yml
```

Test Firstではtestsを先に作成・実行し、package manifest/install output、Vite dev/preview scaffold spec、typecheck、buildがGREENになった後、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。FastAPI health/readiness/static routeはこのcommitの条件に含めない。

```text
feat: Viteとvanilla TypeScriptのClient scaffoldを追加する
```

### P1-10b — Playable UI

**作成**

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

**テストファースト**

- `test_processing_status_changes_immediately_after_submit`
- `test_session_view_displays_all_required_state`
- `test_suggested_action_populates_input`
- `test_reload_restores_last_session`
- `test_secret_sentinel_is_absent_from_dom`
- `test_complete_run_reaches_success_or_failure_end`

**実装前の検証条件**

```powershell
npm --prefix client run test
```

期待REDはrequired locator timeoutまたはmissing endpoint response。

**完了条件**

P1-11でGREENにしたFastAPI server start/readiness/cleanup helperで、FastAPIをlocalhost `127.0.0.1:8765`へ起動した状態で:

```powershell
npm --prefix client run test
```

全Playwright test pass。serverがreadiness 200になってからtestを開始し、test終了後にserverを停止する。DOM text全体にsecret sentinelが存在しない。

**Repository guard / 生成物Gate**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

P1-00bのrepository guard testがexit `0`となり、exact production manifest、forbidden path判定、Python gate order、Windows runner assertionが維持される。CIでもこのguardをPlaywright実行前に通す。`client/node_modules`と`client/dist`は生成物としてGitへ追加せず、repository tree内にDB fileを作らない。P1-10bはproduction `.py`を作らず、production manifestを増やさない。P1-11のserver lifecycleとrepository tree外temporary pathまたはpytest `tmp_path`のDB条件を満たす。

**コミット境界**

```powershell
git add -- client/src/render.ts client/src/stream.ts client/tests/session-view.spec.ts client/tests/reload.spec.ts client/tests/complete-run.spec.ts
```

Test Firstではtestsを先に作成・実行し、P1-10aのclient qualityとP1-11のserver readinessを通過したうえで、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめて着地させる。

```text
feat: Phase 1のplayable session UIとreload復元を実装する
```

---

## P1-11: Streamingまたは安全なFallback

**作成**

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

**変更**

- `src/neontof/app.py`
- `src/neontof/config.py`
- `src/neontof/main.py`
- `tests/test_app.py`
- `tests/test_main.py`
- `tests/test_repository_contracts.py`

**公開型とシグネチャ**

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
    active_turn_registry: ActiveTurnRegistry
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

`ApplicationRuntime`は`src/neontof/application/runtime.py`で上記shapeを定義し、process-lifetimeの具体的な`ActiveTurnRegistry`を所有する。`create_app`はその既存instanceを受け取り、TurnEngineと全request handlerへ同じregistryを渡す。`ActiveTurnRegistry`はP1-03の`turn_lifecycle.py`に実装し、新しいgeneric interface/provider abstractionを作らない。`PublicSessionView`、`PublicProjection`、`PublicContext`、`PublicStaticData`、`PublicDiceView`だけをpublic view、Gateway request、Narrative auditへ渡し、full `Projection`、raw `ScenarioV1`、raw `CharacterSheetV1`をwireまたはpublic serviceへ渡さない。

`build_public_session_view()`の入力は上記のexact signatureに固定する。`public_projection`はEvent replay由来のcampaign/session/scene/turn/request identifiers、resources、locations、clocks、factsを含み、`resource_projection`は同じEvent replayから得たcurrent values、`dice_projection`は`rebuild_dice_projection(EventStore.read_campaign(campaign_id))`から得る。staticなmax/label/inventory/objective textは`PublicStaticData`だけから読み、inventoryは`public_static_data.inventory`のlabelを表示する。secret/NPC `gm_only`本文を参照しない。full `Projection`、raw authoring model、Transcript、Telemetryをこのbuilderへ渡さない。

reloadでは`EventStore.read_campaign(campaign_id)`でcampaign全体を検証してから、Event Logを同じ順序でreplayし、`PublicProjection`、`PublicResourceProjection`、`DiceProjection`、`PublicSessionView`を再構築する。`test_reload_rebuilds_identical_dice_and_public_session_view_from_event_log`はprojection snapshotとcacheを削除した後でも、Eventだけから同じDiceとpublic view JSONになることをfocusedに確認する。

### Canonical JSONとHTTP契約

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
- `POST /api/sessions/{session_id}/turns`、`POST /api/sessions/{session_id}/turns/{turn_id}/resume`: bodyは`{"turn_request_id":"...","input_text":"..."}`、`Idempotency-Key` headerは外部`request_key`として必須。Turn pipelineは全frameをcanonical frame bodyとして完成し、`TurnRequestStore.complete()`で選択されたmedia typeのUTF-8 body bytesをcache commitしてからHTTP adapterへ公開する。SSEとbufferedは同じ完成済みframe bodyから生成する。同じ`Idempotency-Key`のreplayはcached `status_code`、`media_type`、body bytesをbyte-for-byteで返し、provider/dice/Event/frame再生成を行わない。persisted `processing` recordの再送で`ActiveTurnRegistry`がactiveならprocessing responseだけを返し、Provider、Dice、Event append、recoveryを実行しない。registryに無いpersisted `processing`だけをcrash orphanとして一度だけrecoveryする。
- malformed bodyまたはmissing headerは`422`と`HttpErrorBody`、既存Turnと矛盾するresume/undoは`409`と`HttpErrorBody`、server failureは対応する`ErrorFrame`を含む`200` responseとする。
- `POST /api/sessions/{session_id}/undo`: 成功は`200`とbuffered `TurnStreamFrame` response、対象外Turnは`409`。`GET /`と`GET /assets/*`はBrowser静的配信だけを返し、secretを含めない。

`SubmitTurnBody.turn_request_id`はLifecycle Eventのcanonical IDであり、`Idempotency-Key`とは別である。resumeは同じ`turn_id`と同じ`turn_request_id`を使い、headerだけを新しい外部request keyにできる。

HTTP adapterの公開順は、(1)全frameのcanonical body完成、(2)`TurnRequestStore.complete()`によるcache commit、(3)commit済みbodyのSSEまたはbuffered公開で固定する。adapterがexecution resultを独自に再serializeして先に公開する経路を作らない。SSEとbufferedは同じ完成済みframe bodyから各media typeへ変換し、replayは保存済み`status_code`、`media_type`、body bytesをそのまま返す。

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

**テストファースト**

- `test_sse_and_buffered_frames_are_semantically_equal`
- `test_narrative_frame_never_precedes_semantic_result_frame`
- `test_narrative_is_not_sent_when_validation_fails`
- `test_state_frame_is_sent_after_event_commit`
- `test_correction_is_displayed_and_logged`
- `test_reload_returns_running_or_last_committed_state`
- `test_http_response_never_contains_api_key_sentinel`
- `test_health_remains_database_independent`
- `test_duplicate_idempotency_replays_exact_cached_http_response`
- `test_http_publication_follows_turn_request_cache_commit`
- `test_sse_and_buffered_are_generated_from_same_completed_body`
- `test_active_processing_replay_returns_processing_only`
- `test_orphan_processing_recovery_runs_once_when_registry_is_absent`
- `test_public_view_and_narrative_audit_receive_no_full_projection`
- `test_public_view_builder_accepts_only_typed_public_inputs`
- `test_reload_rebuilds_identical_dice_and_public_session_view_from_event_log`
- `test_http_status_and_body_shapes_are_canonical`
- `test_server_lifecycle_uses_external_temporary_database`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/web tests/application/test_narrative_audit.py tests/test_app.py tests/test_main.py tests/test_repository_contracts.py -q
```

実装前のfocused commandでは404、missing module、またはNarrative frame indexがSemantic frameより小さいassertion failureを確認する。cache commit前の公開、SSE/bufferedの完成body不一致、active processingの誤recoveryも失敗理由として確認する。

**完了条件**

全test pass。SSEとbufferedのframeをJSON正規化したtupleが一致し、同じ完成済みframe bodyから生成される。`TurnRequestStore.complete()`のcache commit前にHTTP公開が起きず、replayは保存済みbody bytesをbyte-for-byteで返す。activeなpersisted processingの再送はprocessing responseだけでProvider/Dice/Event/recoveryを行わず、registryに無いpersisted processingは一度だけcrash recoveryする。validation failure responseにNarrative frameが存在しない。server start/readiness/rollbackのruntime/test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置き、`tests/test_repository_contracts.py`のguardがexit `0`で、生成DB、`client/node_modules`、`client/dist`、未manifest production pathをstatusへ残さない。

**コミット境界**

```powershell
git add -- src/neontof/web/__init__.py src/neontof/web/contracts.py src/neontof/web/routes.py src/neontof/web/streaming.py src/neontof/application/runtime.py src/neontof/application/public_view.py src/neontof/application/narrative_audit.py src/neontof/app.py src/neontof/config.py src/neontof/main.py tests/web/test_turn_routes.py tests/web/test_streaming.py tests/application/test_narrative_audit.py tests/test_app.py tests/test_main.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。canonical JSON、HTTP status/body、cache commit後の公開、SSE/buffered同値、cached replay、full Projection非公開、health lifecycle、Event-only reloadのfocused commandがGREENであることを確認して着地させる。

```text
feat: 検証後だけNarrativeを公開するHTTP経路と訂正表示を追加する
```

---

## P1-12: First Scenario Content

**作成**

- `content/characters/phase-01-investigator.v1.yaml`
- `content/scenarios/phase-01-clocktower.v1.yaml`
- `tests/fixtures/phase_01/complete-run-requests.v1.json`
- `tests/fixtures/phase_01/complete-run-provider.v1.json`
- `tests/authoring/test_phase_01_content.py`
- `src/neontof/scenario_runtime.py`
- `tests/application/test_scenario_runtime.py`

**変更**

- `tests/test_repository_contracts.py`

P1-12のproduction manifest追加は`src/neontof/scenario_runtime.py`だけである。

`ScenarioRuntime`は`from neontof.event_metadata import EventBatch, EventMaterializationInput`でneutral typeをimportする。

**Content契約**

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

**公開型とシグネチャ**

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

**テストファースト**

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

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring/test_phase_01_content.py tests/application/test_scenario_runtime.py tests/test_repository_contracts.py -q
```

期待REDはmissing content file、manifest追記漏れ、未許可path、またはcardinality assertion failure。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。complete-run fixtureの最終`SessionEnded.reason`は`completed`で、successまたはfailure Endの公開Factが存在する。manifest追記漏れと未許可pathがないことも同じcommandで確認する。

**コミット境界**

```powershell
git add -- content/characters/phase-01-investigator.v1.yaml content/scenarios/phase-01-clocktower.v1.yaml tests/fixtures/phase_01/complete-run-requests.v1.json tests/fixtures/phase_01/complete-run-provider.v1.json tests/authoring/test_phase_01_content.py src/neontof/scenario_runtime.py tests/application/test_scenario_runtime.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。ScenarioV1/CharacterSheetV1のcardinality、authoritative clock/end condition、secret visibility、clock-driven NPC、complete-run fixtureのfocused commandがfailure `0`であることを確認して着地させる。

```text
feat: 黄昏時計塔ScenarioとClock Runtimeを追加する
```

---

## P1-13: Complete PlaytestとPhase Gate

**作成**

- `tests/acceptance/phase_01_fake_complete_run.py`
- `tests/acceptance/phase_01_gate.py`
- `docs/playtests/phase-01-first-complete-run.md`
- `docs/status/phase-01-first-playable-local-web-slice.md`

### 自動complete run

`phase_01_fake_complete_run.py`はrepository tree外のtemporary directoryへSQLite DBを作り、production loader、Event Store、Fake / Recorded Fixture Gateway、Turn Engine、Projection、HTTP adapterを通してScenarioを完走する。pytestで起動する補助DBも`tmp_path`またはrepository tree外のtemporary pathだけを使い、repository内へDB fileやraw DB backupを生成しない。

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

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
```

期待REDは最初に未実装endpoint、未到達End、またはmissing fixtureでnon-zero exit。単なるprintだけでexit `0`にしない。

**完了条件**

上記9行を出力してexit `0`。

### 人手によるplaytest記録

`docs/playtests/phase-01-first-complete-run.md`には次を日本語で記録する。

- date
- commit
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

### Phase Gate用script

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
- P1-00b repository guard、exact production manifest、generated artifact、external DB location
- content cardinality
- playtest report required fields

unknown-past testはproviderへ固定の「未決定」文字列だけを返させて終わりにしない。spy providerで受信した`PublicContext`がtyped player-only viewであることを記録し、sabotage providerが過去の未記録Factを参照・注入・mutationしようとした場合にGatewayまたはvalidationが拒否し、Projection/Event Log/context digestが変わらないことをassertする。

**コマンド**

```powershell
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
.\.venv\Scripts\python.exe tests/acceptance/phase_01_gate.py
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
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

human playtest reportが存在しない、End未到達、replay desire未記入、unknown-past sabotageがcontext mutationを検出できない場合はexit non-zeroとする。P1-13はproduction `.py`を作らず、production manifestを増やさない。CIでもphase gateと同じrepository guardを実行する。P1-00bのrepository guard testもexit `0`となり、exact manifestの未登録production `.py`、forbidden/generated path、repository tree内DB、`client/node_modules`、`client/dist`を見逃さないことを確認する。Fake / Recorded Fixtureのcomplete runはAPI keyなしlocal acceptance evidenceであり、P1-06の一つの実Provider adapter成果物を置き換えない。

**コミット境界**

```powershell
git add -- tests/acceptance/phase_01_fake_complete_run.py tests/acceptance/phase_01_gate.py docs/playtests/phase-01-first-complete-run.md docs/status/phase-01-first-playable-local-web-slice.md
```

Test Firstではtestsを先に作成・実行する。Fake / Recorded complete run、phase gate、Browser Gate、unknown-past sabotage、playtest report required fields、local statusが全て実測で確認できた後、上記pathのtestsとdeliverablesを1つのlogical GREEN commitへまとめて着地させる。Remote CIはpending / 未確認として記録し、green/failureへ読み替えない。

```text
test: Phase 1の完全実行Gateと実測記録を追加する
```

Phase 2はこのcommit後も自動開始しない。ユーザーの明示指示を待つ。

---

# 10. 全体検証コマンド

Repository rootで次を順番どおり実行する。

## Runtimeと依存

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

## Remote CIの状況

Remote CIは**pending / 未確認**である。remote runのgreen/failureを判定できる証拠はなく、local Phase 0 baseline `605 passed, 2 warnings`とは別の検証事実として記録する。remote未確認をlocal greenまたはfailureへ読み替えない。pending / 未確認のままではFinal Gateのremote判定を保留する。

## Python品質

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

## Client品質

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

## Networkとsecretの境界

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_no_external_network.py -q
.\.venv\Scripts\python.exe -m pytest tests/model_gateway/test_gateway_security.py tests/application/test_context_builder.py tests/web/test_turn_routes.py -q
```

Success evidence:

- external network attempt `0`
- API key / secret sentinel hit `0`

## 受入れ

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

## Diffと範囲

```powershell
git diff --numstat
git diff --ignore-cr-at-eol --numstat
git diff --check
git status --short
```

2つの`numstat`が一致すること。`git diff --check`が空でexit `0`。生成物、`.env`、DB、raw log、`node_modules`、`dist`がstatusへ現れないこと。

Stagingはcommitごとに許可pathを明示列挙する。`git add .`と`git add -A`を使わない。

---

# 11. リスクレベルとロールバック戦略

## リスクレベル

**Heavy**

理由:

- SQLite transactionとsingle-writer ownershipを新設する。
- Event append、Projection rebuild、Turn idempotencyを実装する。
- Visibility Filter、Semantic Result materialization、Gateway budgetを実装する。
- BrowserとServerを結ぶ新しいpublic HTTP/SSE APIを作る。
- Phase 1 Gateにhuman playtestを含む。
- C-01のcontract tensionが残っている。
- C-03のProvider request boundaryとprovider approvalが未確定である。
- DomainEvent envelopeにtop-levelの`turn_request_id`がなく、producer coordination metadataとwire envelopeを混同できない。
- payloadはexact raw JSON bytes境界を必要とし、typed modelのserializationや既存`FrozenJsonValue`の推測round-tripを永続化の根拠にできない。
- production manifestはP1-00b後も完全一致で検査され、各WPが自分のproduction `.py` pathを明示追加する必要がある。P1-10a以降のclient/generated path、forbidden path、CI gate、persistence限定のSQLite scopeを同じguardで扱うため、WPごとの追加漏れと誤った一律禁止がリスクになる。
- `tests/test_repository_contracts.py`を共有するproduction WPを並列実行すると、exact manifest追記のlost updateまたは別WPの未検証entryをGREENにするリスクがある。manifest serialization laneで一つずつ着地させる。

## 既知のリスク

- P1-00の`EventDraftBody`が既存`DomainEventBase`のunsequenced field集合から外れると、P1-01のparser boundaryで再構築できない。
- `payload_json`のobject/array shapeまたはexact bytesを失うと、永続`event_json`とEvent replayの意味が変わる。
- lifecycle payloadのvalidation前にturn request検索を行うと、coordination metadataをDomainEvent envelopeのauthorityとして扱うことになる。
- P1-08でlosslessなraw boundaryが不足した場合、Phase 0 semantic contractの改訂または別の承認済みboundaryなしに進められない。
- repository test-sideのAST/import-aware SQLite scanと、`docs/agent-guide/build-and-verify.md`に定義されたguide-side scanの更新経路を混同すると、alias/import変形または許可範囲の不整合を見逃す。
- runtime/test DBをrepository tree内へ作ると、生成物・秘密・rollback対象の境界が壊れる。P1-01、P1-11、P1-13はrepository tree外temporary pathまたはpytest `tmp_path`に限定する。

## リスク対策

- P1-00はmetadata contract testとproduction manifest contract testを同じfocused commandで確認する。
- P1-01はparser受理とenvelope一致確認を通過したexact assembled bytesだけを`event_json`へ保存し、既存manifestの形式、既存migration、P0 contract fileを変更しない。production `.py`を作るWPは自分のpathだけをexact manifestへ明示追加し、Modify、staging、commitへ同じpathを含める。
- P1-00bでrepository guardのexact-match、forbidden判定、source scan、Python gate order、Windows runner assertionを固定し、P1-01aのSQLite usage導入前にMyWorkflow正本のguide-side scan policyを更新・deployしてから、repository test-side scanとguide-side SQLite scanを別経路で再検証する。
- `tests/test_repository_contracts.py`をModifyするproduction WPはmanifest serialization laneで一つずつfocused/full Gate、`git diff --check`、明示commit、clean worktreeを確認し、P1-10aなどmanifest lane外のclient/test-only WPだけを非共有pathの範囲で並列実行する。
- WPごとにtestsを先に作成・実行し、REDで失敗理由を確認する。focused testと最小implementationがGREENになった後、testsとimplementationを同じlogical GREEN commitへまとめる。
- Event Store、Projection、Visibility、Dice、Gateway、Turn Engineを別commitにする。
- dependency commitを通過するまで後続integrationを開始しない。
- SQLite migrationは`0001_event_store.sql`、`0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`に分割し、各WPが自分のadditive migrationだけを追加する。down migrationは作らない。
- migration runnerはraw SQL bytes SHA-256、version/name/checksum drift、gap/duplicate/out-of-order/unknown applied versionをDDL前に検証し、pending判定からDDL・schema row insert・COMMITまでを一つのtransactionに置く。
- pendingかつ既存schema/dataがある場合だけ、lock保持下でrepository tree外へSQLite backup API copyを作る。新規DB・backup不要・no-opでは作らず、backup失敗時はDDLを実行しない。backup file/sidecarをGitへ追加しない。
- `read_campaign`の全列検証をprojection/status/dice/public projection/recoveryの共通入力とし、typed filter、snapshot、coordination record、observationだけを入力にする経路を作らない。
- Event appendとObservation appendを別transactionにし、Projection snapshotはwrite lock内でmonotonic upsertする。request dedupeの全identity照合とresume context validationはP1-03の同一transaction内で行う。
- Event rowをmigrationで書き換えない。
- Projectionは削除・再構築可能とする。
- 実Providerは明示承認まで追加しない。

## ロールバック

- commit済み変更は依存逆順に`git revert`する。
- `git reset --hard`、`git checkout --`を使わない。
- P1-01 rollback時はServerを停止し、repository tree外temporary pathまたはpytest `tmp_path`に置いたPhase 1のDBだけを対象absolute path確認後に退避または削除する。repository tree内にDB fileが現れた場合はGate failureとして扱い、対象を確認せずに削除しない。
- Projection不具合はEventを残したままprojection tableだけを削除し、修正版でrebuildする。
- Gateway不具合はFake ProviderのままP1-06 commitをrevertし、API keyや外部通信へfallbackしない。
- Client不具合はclient commitだけをrevertし、Server contractを変更して帳尻を合わせない。
- C-01が未承認またはblockingの場合はP1-03以降を開始せず、P1-01 / P1-02 / P1-04 / P1-05の依存commitを保持してユーザー判断を待つ。
- C-02が未承認またはblockingの場合はP1-09とその依存integrationを開始せず、provisional detailのschemaを作らない。
- C-03が未承認またはblockingの場合はP1-06 Fake/Recorded Gatewayとその依存integrationを開始せず、GatewayのGREEN/commitを保留する。provider approvalが未承認またはblockingの場合はP1-06 concrete real Provider adapterとP1-07以降のprovider-dependent integrationを開始せず、real adapterのGREEN/commitを保留する。承認だけで固定responseや曖昧なadapterへfallbackしない。Fake / Recordedのlocal validationはprovider approval前も継続できる。
- P1-00またはP1-00bのmetadata、exact manifest、repository guard、envelope契約が失敗した場合はP1-01以降を開始せず、P0契約や禁止pathを変更しない。
- P1-08のpayload boundaryが未承認またはPhase 0 semantic contract改訂待ちの場合は、semantic materializationと依存integrationを開始しない。

---

# 12. コミット境界の概要

各WP sectionの`コミット境界`が、Test FirstのRED→最小GREENのfocused command、full-green条件、明示的な`git add -- <path...>`を定義する唯一の着地表である。下記の順序はcommit message順の要約であり、`tests/test_repository_contracts.py`をModifyするWPはmanifest serialization laneの順序を守る。P1-00とP1-00bは完了済みであり、後続のmanifest laneと並列開始できるのはP1-10aである。P1-10bとP1-13は依存成立後、非共有pathのtest-only作業とのみ並列可能であり、共有manifest pathを同時にstageしない。
Persistence migrationの対応は、P1-01a=`0001_event_store.sql`（`schema_migrations`/`events`のみ、schema-set最大version `1`）、P1-01b=`0002_projection_snapshots.sql`（最大version `2`）、P1-02=`0003_observation_stores.sql`（最大version `3`）、P1-03=`0004_turn_requests.sql`（最大version `4`）とする。各WPのfocused RED/GREEN command、schema-setの連番・未知versionなし・raw SQL bytes checksum evidence、SQLを含む明示的な`git add -- <path...>`は各WP sectionに定義し、全migrationをadditive、down migrationなし、P1-01aは後続tableなしとする。P1-01a、P1-01b、P1-02、P1-03、P1-04、P1-05、P1-06、P1-07、P1-08、P1-09、P1-11、P1-12のRED/GREEN focused commandは、各WPの既存focused testと`tests/test_repository_contracts.py`を同じpytest invocationへ含める。P1-00とP1-00bのfocused commandは既存の両test対象を維持し、P1-10a、P1-10b、P1-13はmanifest lane外のguard Gateとして別commandを使う。

完了済みの依存成果物:

- P1-00: `feat: Event draftとmetadataのneutral契約を固定する`（commit `b5c1bf3`）
- P1-00b: `test: Phase 1 repository guard transitionを固定する`（commit `31fab05`）

後続WPの着地順:

1. `feat: append-onlyなSQLite Event Storeと原子性を実装する`（P1-01a）
2. `feat: Eventから再生成できるProjection Storeを追加する`（P1-01b）
3. `feat: TranscriptとTelemetryをEvent transaction外へ保存する`（P1-02）
4. `feat: Request IDで直列化するTurn状態機械を追加する`（P1-03、C-01承認後）
5. `feat: 再現可能な最小Rulesetと資源境界を実装する`（P1-04）
6. `feat: CharacterとScenarioをEventへ正規化する`（P1-05）
7. `feat: Model Gatewayの予算と安全なProvider境界を実装する`（P1-06、C-03・provider approval・承認済みexact contract反映後）
8. `feat: Visibility Filter、PublicProjection、Evidence validation、Alias解決を追加する`（P1-07）
9. `feat: 検証済みproposalだけをatomic appendするTurn Engineを実装する`（P1-08、C-01承認後、payload boundary確認後）
10. `feat: Event由来のprovisional detail Projectionを追加する`（P1-09、C-02承認後）
11. `feat: Viteとvanilla TypeScriptのClient scaffoldを追加する`（P1-10a、manifest lane外）
12. `feat: 黄昏時計塔ScenarioとClock Runtimeを追加する`（P1-12、manifest lane）
13. `feat: 検証後だけNarrativeを公開するHTTP経路と訂正表示を追加する`（P1-11、P1-12後のmanifest lane）
14. `feat: Phase 1のplayable session UIとreload復元を実装する`（P1-10b、P1-10a/P1-11後）
15. `test: Phase 1の完全実行Gateと実測記録を追加する`（P1-13）

各commit前にfocused test、関連quality gate、diff scopeを確認する。依存する次WPを開始する前に、そのWPのcommitを着地させる。commit後も`git push`しない。

---

# 13. 最終Gate判定

Phase 1をPASSと記録できるのは、次の全条件を満たした場合だけである。

- P1-00のmetadata testと`tests/test_repository_contracts.py`が同じfocused commandでexit `0`となる
- P1-00bのrepository guard testがexit `0`となり、exact production manifest、forbidden/generated path、Python gate order、Windows runner assertion、persistence限定SQLite scope、repository tree外DB条件が確認される
- P1-01aの`0001_event_store.sql`が`schema_migrations`と`events`だけを作り、schema-set最大version `1`、欠落なし、unknown applied versionなし、raw SQL bytes SHA-256とversion/name/checksumの一致が確認される。P1-01aのproduction manifest entryは4つの`.py`だけで、SQLはmanifest entry外である。`PRAGMA table_info`、`PRAGMA index_list`、`PRAGMA index_xinfo`、`sqlite_master.sql`、`typeof(event_json) = 'blob'`、NOT NULL/CHECK/UNIQUE sabotageでexact schemaを再検証する
- P1-01b、P1-02、P1-03がそれぞれ`0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`だけを追加し、schema-set最大versionが順に`2`、`3`、`4`で、各段階に欠落・未知version・checksum driftがないことが確認される
- migration runnerが`BEGIN IMMEDIATE`からvalidation、必要時だけのrepository tree外SQLite backup API copy、DDL、schema row insert、`COMMIT`を固定順で実行し、backup失敗時にDDLを行わず、no-op時にbackup/writeを行わないことが確認される
- `SqliteDatabase`のpublic generic read/write、retry、workerがなく、typed Store read、fixed PRAGMA、shared write lock、別connection read、`query_only=ON`の多層防御が確認される。WAL `-wal`/`-shm` sidecarと`.db` variantsはrepository guardが拒否する
- `read_campaign`の全sequence・全row・derived/readback検証、inspection-only filter、対象外破損rowのfail-closed、`read_turn`のrevert target、validated `PlayerInputAccepted.payload.turn_request_id` lookupが確認される
- 既存`DomainEventValidationError`と`DomainEventValidationIssue`/`IssueCode`がparser・sequence・projection validationの既存codeのまま伝播し、Event Storeのduplicate event IDが`EventStoreConstraintError(code="duplicate_event_id")`、その他の`sqlite3.IntegrityError`が`EventStoreConstraintError(code="event_constraint_violation")`、その他のDatabase/Migration failureが安全なcodeへ写像される。元exceptionのmessage/args/cause/context/custom attr/logを保持せず、`DomainEventValidationError`をwrapしないことが確認される
- P1-01bのEvent read→pure rebuild→monotonic upsert、stale read処理、barrierが確認される。P1-02の`tool_call`、allowlist、raw provider情報非保存、Event transaction外append、failed Turn Event 0件、table-local sequenceが確認される
- P1-03のDB-wide opaque `request_key`、全identity conflict、cached body非返却、campaign-scoped canonical request、transaction内resume context validation、processing/response型不変条件、`complete()`のcompare-and-set/idempotency、process-lifetime `ActiveTurnRegistry`、active processing replay、orphan一度だけrecovery、campaign-wide recoveryが確認される。barrier testはProvider=1、Dice=1、PlayerInputAccepted=1、abort=0である
- P1-08/P1-11のTurn pipelineが全frameのcanonical body完成→`TurnRequestStore.complete()`のcache commit→HTTP adapter公開の順を守り、SSEとbufferedが同じ完成bodyから生成され、replayが保存済みstatus/media/body bytesをbyte-for-byteで返すこと、active processing replayがprocessing responseだけでProvider/Dice/Event/recoveryを行わないことが確認される
- P1-01のpayload shape preservation、invalid payload JSON batch rollback、validated lifecycle payloadのturn request検索、unsequenced envelope materialization boundaryがexit `0`で確認される
- P1-08のlossless raw boundaryが確認され、推測した`FrozenJsonValue` round-tripが残っていない
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
- C-03で承認されたexact adapter path、signature、dependency、test path、git add pathが計画・実装・検証へ反映されている
- provider approvalが承認済みで、承認された一つの具体的な実Provider adapterのpath、key source、cost、destination、call上限が実装とtestへ一致している
- P1-06のFake / Recorded Fixtureと交換可能な明示承認済みの具体的な実Provider adapterが1つ存在する。Fake-onlyはPASS条件を満たさない
- C-01、C-02、C-03、またはprovider approvalが未承認なら、該当WPをGREENまたはcommit扱いにしない。player input/diceを無視する固定response方式はPASS条件を満たさない
- 通常Turnの`max_attempts=1`、provider invocation `1`、timeout/error時retry `0`が実測される
- remote CIの状態を確認し、pending / 未確認ならPhase 1 Final Gateのremote判定を保留する。green/failureへ読み替えない

PASS後もPhase 2は開始しない。`docs/status/phase-01-first-playable-local-web-slice.md`へlocal Gate、remote **pending / 未確認**（green/failure未判定）、Known Issues、playtest結果、C-01/C-02/C-03/provider approvalの状態を記録する。
