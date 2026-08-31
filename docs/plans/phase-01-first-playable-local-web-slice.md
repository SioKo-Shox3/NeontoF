# Phase 1: First Playable Local Web Slice 詳細実装計画

**目標:** localhost で Server を起動し、Browser だけで一人用 Scenario を開始から成功または失敗 End まで遊べる Vertical Slice を作る。

**構成:** Event Log をゲーム状態の唯一の権威とする。現在のHEAD（P1-02完了時点）ではapplication-levelの`EventStore.append()` callerは0件であり、P1-03 Lifecycleで同じowner classの`TurnLifecycleCoordinator.execute()`と`revert_latest()`の2 callsiteを追加し、P1-05後に同クラスへ`append_bootstrap()`を追加して3 callsiteにする。EventStoreは永続化だけを所有し、State / Canon / provisional detailはEventから再構築する。Transcript / Telemetryとidempotency coordinationはゲーム状態transactionの外に置く。

**技術構成:** Python 3.14.3、FastAPI 0.141.1、Pydantic 2.13.4、Uvicorn 0.52.3、stdlib `sqlite3`、pytest 9.1.1、ruff 0.16.3、mypy 2.3.1、HTTP POST + SSE + buffered fallback。Vite、vanilla TypeScript、Playwright、Node、npmのversionはこの計画の時点で確認済みのRepository事実ではない。P1-10aのpackage manifest・lockfile・install/version outputで根拠が得られた値だけを採用し、既存ADRにないclient toolchainの固定はplan-level proposalとして扱う。

**参照仕様:** `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/0001-technology-stack.md`、Phase 0 の `docs/specs/**`、既存の `src/neontof/contracts/**` と `src/neontof/model/**` を再利用する。Phase 0 契約を暗黙に変更しない。

## 既存の完了成果物と検証事実

- P1-00（Event draftとmetadataの中立契約）はcommit `b5c1bf3`で完了している。
- P1-00b（Phase 1のリポジトリ検査境界）はcommit `31fab05`で完了している。
- P1-01a（SQLite Event Storeと`0001_event_store.sql`）はcommit `eb284f9`で完了している。
- P1-01b（Projection Storeと`0002_projection_snapshots.sql`）はcommit `9ee2074`で完了している。
- P1-02（Observation Storeと`0003_observation_stores.sql`）はcommit `e5b7aa4`で完了している。
- 現在のscanner検査基準は、same-connection reader `1`、application-level `EventStore.append()` caller `0`である。次のP1-01c補正後だけ、この基準を実コマンドのGreen結果として扱う。
- Phase 0 local baselineは`605 passed, 2 warnings`である。警告は件数・内容を実行時の証拠として記録し、新規警告を黙認しない。
- Remote CIは**pending / 未確認**であり、local baselineとは別の検証事実として扱う。local結果からgreen/failureへ読み替えない。

## 全体制約

- Event Log以外をゲーム状態の権威にしない。
- Stateを直接変更する public APIを作らない。
- LLMの自由文または Narrativeを parseしてEventへ変換しない。
- Semantic Resultのschema、reference、visibility、evidenceを検証してからEventへ変換する。
- Event batchは1回のSQLite transactionでappendし、失敗時に全件rollbackする。
- P1-01a の migration は `0001_event_store.sql` だけを適用し、`schema_migrations` と `events` だけを作る。P1-01b、P1-02、P1-03がそれぞれ `0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`を追加する。全migrationはadditiveで、down migrationを作らない。
- migration runnerは各SQLファイルのraw SQL bytesを`sha256`し、available migration file setの同一version重複を`_discover_migrations`側で検出し、applied rowsがcontiguous prefixであること、gap、unknown applied version、`version`、`name`、`checksum`のdriftをDDL前にfail-closedで検証する。applied schema_migrations rowのduplicateは`version PRIMARY KEY`が挿入時に拒否するため実DB validation対象にせず、pending migrationの判定もtransaction内で行う。exact schemaは適用順序を保持しないためPhase 1ではその検証を行わず、runnerは未適用migrationをversion昇順にだけ適用する。
- migrationの順序は`SqliteDatabase.migrate()` → process-wide shared `threading.Lock` → fixed migration connection open → filesystem pathとmigration `main.file`のsource open前検証 → migration connectionだけで必要ならtransaction外に`PRAGMA journal_mode=WAL`を一度設定 → `BEGIN IMMEDIATE` → `schema_migrations`の存在・shape・applied rows・migration filesのvalidationとpending判定 → pendingかつ既存schema/dataがある場合だけ専用read backup sourceをopen → 三者`samefile`検証 → sourceから新しいpartial destinationへSQLite backup → copy直後destinationのjournal mode実値readback → destination/source close → partial basenameのmain/`-wal`/`-shm`全exact path確認 → reopen verifierでdeadline付き実schema/data比較 → verifier closeとpath再確認 → clean close後の同一basename artifact set promotionまたは全exact path cleanup → `backup_verified` → DDL → `schema_migrations` row insert → `COMMIT`とする。専用sourceをlock/`BEGIN IMMEDIATE`前に開かず、migration connection自身をbackup sourceにしない。pendingかつ既存schema/dataがない場合、新規DB、またはno-opではbackupを作らず、backup失敗・実data/schema mismatch・verification deadline超過時はDDLを実行しない。
- migrationでDDLと`schema_migrations` rowを同一transactionに置く。no-op再実行はbackupもschema row writeも行わず、backup file/sidecarをGitへ入れない。このcopyはProduct Plan §20のWeb backup機能ではなく、W-Dで必要な最小copyだけである。
- `SqliteDatabase.migrate()`だけをpublic mutation entryとし、public `run_migrations`、public backup/restore/cleanup/diagnostic API、generic `read`/`write`/retry/worker APIを作らない。migration runnerはprivate `_run_migrations`へ閉じ、public型付きStore readだけを公開する。
- SQLiteはmigration main connectionの初回だけ`PRAGMA journal_mode=WAL`をtransaction外で一度設定し、dedicated source、copy destination、reopen verifierからjournal mode setterを発行しない。backup側はmigration main/source/copy直後destination/close-reopen後verifierのjournal mode実readback値を一致検証し、`DELETE`へ固定しない。全connectionの`timeout=5.0`、`isolation_level=None`、`check_same_thread=True`、`uri=False`、`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`を固定し、process内shared `threading.Lock`でwriteとmigrateを直列化し、typed Storeの`_read`はlock外の別connectionで行う。以後のno-op再実行ではschema/write/backupを行わない。
- `_read`はconnectionごとに`PRAGMA query_only=ON`を設定するが、多層防御でありsecurity boundaryとは過大表現しない。主境界はpublic surfaceとrepository source guardである。
- 既存`DomainEventValidationError`と`DomainEventValidationIssue`/`IssueCode`は、`src/neontof/contracts/event_parser.py`とcore specの既存契約を変更せず、parser・sequence・projection validationだけに使う。Event StoreのDB constraint violationはP1-01aのローカルな`EventStoreConstraintError`へ分離し、その他の`DatabaseError`は`locked`/`io`/`corrupt`/`other`だけを持つ`SqliteOperationError`へ変換する。元exceptionのmessage/args/cause/context/custom attr/logを残さない。
- `read_campaign`はcampaign内の全sequence連番を読み、全rowの`event_json`、derived columns、readbackを検証してから`tuple[DomainEvent, ...]`を返す。`read_session`、`read_turn`、`find_turn_by_request`も完全検証済み`DomainEvent`列へのinspection-only filterであり、対象外rowの破損でもfail-closedにする。`StoredEvent`は`EventStore.append()`のreturnと内部materializationだけで使う。
- Projection rebuild/status/dice/public projectionはfiltered sliceを入力にせず、`read_campaign`の完全な`DomainEvent`列だけを入力とする。Event Logだけがauthorityであり、coordination record・observation・snapshotを入力にしない。
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
| migration runnerの検証・backup・transaction順序 | raw SQL bytes SHA-256、`_discover_migrations`によるavailable migration file setの同一version重複検出、applied rowsのcontiguous prefix/gap/unknown applied version/version/name/checksum driftのDDL前実DB検証、`BEGIN IMMEDIATE`後の専用read source、三者`samefile`、copy→close→reopen verifier→deadline付き実schema/data比較→同一basename artifact set確定、DDLとrow insertの同一transaction。exact schemaは適用順序を保持しないためPhase 1ではその検証を行わず、未適用migrationはversion昇順にだけ適用する。 |
| SQLiteの公開境界とconcurrency | `SqliteDatabase.migrate()`だけをpublic mutation entryにし、private `_run_migrations`、`_read`/`_write`、固定connection kwargs/PRAGMA、shared write lock、別connection read、generic write/retry/workerなし。typed Storeの`_read`はlock外のままにする。 |
| exceptionの安全な境界 | 既存`DomainEventValidationError`と既存Domain `IssueCode`は変更せず、Event Storeのconstraint violationは`EventStoreConstraintError`、SQLite operation failureは`SqliteOperationError`、migrationのunsupported/identity/cleanup/backup/DDL failureは`MigrationError`の固定codeへ分離する。いずれも元exceptionの詳細・chain・logを保持しない。 |
| Event readの完全性 | `read_campaign`が全sequence・全row・derived columns・readbackを検証し、typed filterはその完全列に対するinspection-only処理とする。 |
| Event authorityの入力経路 | Projection、status、dice、public projection、recoveryはfiltered sliceやsnapshot等を入力にせず、campaign全体のvalidated Event列を使う。 |
| request dedupeとrecovery | DB-wide opaque `request_key`、campaign-scoped canonical `TurnRequestId`、全identity照合、transaction内resume context validation、processing/response型不変条件、campaign全体recovery。 |
| Observationの非transaction境界 | `tool_call`、purpose-specific allowlist、raw provider情報非保存、Event append外の別`_write`、failed TurnのEvent 0件保持、table-local sequence。 |
| Projection snapshotのmonotonicity | P1-01bでEvent read→pure rebuild→monotonic upsertを同じwrite lock critical sectionに置き、stale candidateを拒否する。 |
| Test Firstと着地 | REDで失敗理由を確認し、testsとimplementation（該当SQLを含む）を一つのlogical GREEN commitへまとめ、explicit `git add -- <path...>`で着地する。 |
| repository guardと証拠 | production manifestの4つのP1-01a `.py` entryを維持し、SQLはmanifest entry外、`tests/test_repository_contracts.py`をModify/stage/commitへ含め、DB本体・WAL sidecar・`.db` variants・partial/verified migration artifact・backup rootをrepository tree外へ限定する。 |
| Phase 1の境界 | `event_metadata.py`、contracts、上位文書、後続WPの実装をP1-01aで変更せず、C-01で固定したAの境界と、C-02/C-03/provider approvalのstop gateを維持する。 |

一般見出しは日本語で記述し、各migrationのschema-set evidence、RED/GREEN、commit boundaryは各WPの契約として定義する。Product Plan、Roadmap、ADR、specの改訂と、二つ目の具体実装がない抽象化はPhase 1の対象外とする。

---

## 1. Goal（目標と期待する挙動変化）

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

## 2. Non-goal（明示的な対象外）

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

## 3. Entry Conditions（入口条件）

実装開始時に次を確認する。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

期待証拠:

```text
605 passed, 2 warnings
```

P1-01aで満たしたEntry Conditionsは、P1-00（commit `b5c1bf3`）とP1-00b（commit `31fab05`）が完了していること、Phase 0 local baselineが`605 passed, 2 warnings`であること、P1-00bのrepository guard契約が利用できることである。pytestはexit `0`とfailure数`0`を判定基準にし、Phase 1のtest追加後は件数を固定値として扱わない。現在の次の実装入口は、P1-02後のP1-01c scanner-hardening補正である。

Entry判定:

- Phase 0 Gate: local PASS
- Phase 0 remote CI: **pending / 未確認**。remote runのgreen/failureを判定しない。
- P1-01a実履歴のEntry: P1-00とP1-00bの完了、local baselineのexit `0`、repository guard契約の利用可能性（確認済み）。次の開始条件: P1-02の着地と、P1-01cのscanner-hardening補正。

Remote未確認はlocal baselineの判定を変更せず、Phase 0のremote GateをPASSへ読み替える根拠にもならない。

## 4. Phase 1 Gate（ユーザー指定のPhase Gate）

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
- DB-wideの`request_key`（HTTPでは`Idempotency-Key`）の再送ではrequestを二重処理せず、canonical `TurnRequestId`はidentity/contextであってidempotency keyではない。resumeでは同じcanonical `TurnRequestId`を使っても新しい`request_key`を持つ。
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

## 5. Stop Conditions（停止条件）

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
- C-02、C-03、またはprovider approvalが未承認のまま、それぞれに依存するWPをGREENまたはcommit扱いにしようとした、またはC-01 Aの境界を外そうとした。
- Narrative自由文のparseがstate更新に必要になった。
- Scenarioが未実装機能へ依存した。
- C-01 Aの境界またはC-02 decision gateの承認済み契約なしに該当WPを開始しようとした。
- P1-00のproduction manifest exact-match、unsequenced DomainEvent envelope、exact payload bytes、またはcoordination metadataの境界が成立しない。
- P1-00bでexact production manifestをglob/prefixへ緩める、forbidden判定を削る、source scanを迂回する、またはPython gate order/Windows runner assertionを弱める必要が生じた。
- 各WPがproduction `.py` pathを同じexact manifestへ明示追加せずにGREENまたはcommitしようとした。
- `tests/test_repository_contracts.py`をModify/stageする二つのWPを同時にactiveにする、または前WPのfocused/full Gate、`git diff --check`、明示commit、clean worktree確認前にmanifest laneの次WPを開始する必要が生じた。
- P1-01 preflightで既存manifestの形式変更、既存migration/policy/P0 contract file変更、repository test-side scanとguide-side scanのいずれかの更新経路を飛ばす必要が生じた。
- `sqlite3.connect`が下記のruntime/migration exact callsite以外に現れる、`sqlite3.Connection`のtype annotation / `isinstance`以外のconstructorまたはunknown module attributeを追加する、arbitraryな`src/neontof/persistence/database.py`の`sqlite3.connect(':memory:')`を許可する、alias/import変形でsource scanを逃れる、またはruntime/test DBをrepository treeへ置く必要が生じた。
- migrationのavailable migration file setに同一versionの重複があることを`_discover_migrations`側で検出できない、またはapplied rowsがcontiguous prefixであること、gap、unknown applied version、`version`/`name`/raw SQL bytes SHA-256 checksumのdriftをDDL前に実DBから検証できない、applied schema_migrations rowのduplicateを実DB validation対象にする、またはpending判定をtransaction外へ移す必要が生じた。
- pending migrationで既存schema/dataがあるのに`BEGIN IMMEDIATE`後の専用read backup source、三者`samefile`、repository tree外のpartial destination、copy直後destination journal mode readback、close/reopen verifier、実schema/data比較、同一basename artifact setのpromotionまたは全exact path cleanupを完了できない、backupが失敗したのにDDLを続行する、または新規DB/no-op再実行で不要なbackupやschema row writeを行う必要が生じた。
- Phase 1 DBをfilesystem-backed regular fileに限定できない、URI/in-memory、directory、special fileをsource openまたはDDL前に拒否できない、canonical path・migration `main.file`・source `main.file`の三者`samefile`を検証できない、relative pathまたはhard-link aliasを誤拒否する、または別fileを受理する必要が生じた。
- migration main/source/copy直後destination/close-reopen後reopen verifierのjournal mode実readback値を一致検証できない、backup側がjournal mode setterを発行する、`SQLITE_OK`継続を含む10秒copy deadline、BUSY/LOCKED 200回上限、unexpected statusの固定境界を守れない必要が生じた。
- real schema/data verificationまたはtest-only restoreに明示deadlineまたは有限row/page境界を置けない、実data/schema mismatchまたはverification deadline超過をDDL前に`backup_failed`へできない、またはpartial/verified artifact setのcleanup失敗を`backup_cleanup_failed`へできない必要が生じた。
- `SqliteDatabase.migrate()`以外をpublic mutation entryにする、public `run_migrations`またはpublic backup/restore/cleanup/diagnosticを追加する、typed Storeの`_read`をwrite lock内へ移す、またはproductionへglobal recorder/diagnostic surfaceを追加する必要が生じた。
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

C-01はAを採用する。通常TurnのModel call上限は1回とする。model由来clarification completionはPhase 1受入れ対象外とする。P1-03/P1-08はこの決定に従う。

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
- typed Storeの`_read`は従来どおりshared write lock外でoperationごとの別connectionを開き、`PRAGMA query_only=ON`を設定する。専用read backup sourceだけが、既存のmigrate lockと`BEGIN IMMEDIATE`済みmigration transaction内で開くprivate exceptionである。これは多層防御であり、主security boundaryはpublic surfaceとrepository source guardである。
- migration backup中のsource、destination、reopen verifierは`migrations.py`の現在のprivate invocationが同一threadで所有し、各close完了まで他operationへ渡さない。promotion後のverified artifact setはoperator/test fixtureへ引き継ぐ。
- `EventStore`はDomain Event tableのpersistence writerである。P1-03のapplication-level append callerは`TurnLifecycleCoordinator.execute()`と`revert_latest()`の2 callsiteだけであり、P1-05で同じowner classへ`append_bootstrap()`をModifyした後だけ3 callsiteになる。owner classは常に`TurnLifecycleCoordinator`一つである。
- `ProjectionStore`はEventを読み、削除可能なprojection snapshotだけを置換する。
- `ObservationStore`はTranscript / Telemetryだけをappendする。
- `TurnRequestStore`はHTTP requestの重複実行を防ぐoperational recordを所有する。ゲーム状態のProjection入力にはしない。
- `TurnLifecycleCoordinator`が`EventStore.append()`を呼べる唯一のapplication serviceである。P1-03では`execute()`と`revert_latest()`の2 callsiteだけを実装し、`TurnEngine`とP1-08のSemantic Result pipelineはcoordinatorへ委譲して直接`EventStore.append()`を呼ばない。P1-05後の`BootstrapApplicationService`も`EventBatch`を作って追加された`append_bootstrap()`へ委譲するだけで、EventStore writerまたは別lockを持たない。
- `TurnLifecycleCoordinator.recover_processing()`は`RecoveryPlan`のmetadata CAS、recovery decision、optional candidate batch preparationだけを行い、`EventStore.append()`と`TurnRequestStore.complete()`のcallerではない。recovery candidateのappend、campaign reread、ResponseRebuilder、completeは`execute()`の既存callsiteが同じboundary lock内で順に行うため、Event append caller allowlistはP1-03の2件、P1-05後の3件から増えない。
- 既存architectureの「Turn Engine appendの唯一の入口」という責務名は維持する。`TurnEngine`が外部から受けるsubmit/resume/undoのappend経路を、実装上の唯一caller classである`TurnLifecycleCoordinator`へdelegationする構造として表現する。P1-05のbootstrapも同じowner classの追加methodへ委譲し、TurnEngine以外の直接append経路や二つ目のownerは作らない。
- FastAPI routeはHTTP validation、application call、frame serializationだけを担当する。
- Browserはserverが返したpublic viewだけを保持し、秘密、DB、API keyを持たない。

### スレッド

- Uvicornは`workers=1`を維持する。
- FastAPI route、SSE generator、threadpool間でConnectionを共有しない。
- SQLite writeとmigrationはprocess内shared `threading.Lock`と`BEGIN IMMEDIATE`で直列化する。generic retry、worker、public write bypassは作らない。
- `read`はoperationごとに別Connectionをlock外で開き、`isolation_level=None`、`busy_timeout=5000`、`synchronous=FULL`、`check_same_thread=True`を設定する。
- migration main connectionの`PRAGMA journal_mode=WAL` setterだけを初回migrate時にtransaction外で一度だけ許可する。dedicated source、copy destination、reopen verifierはjournal modeをread-onlyで実測し、setterを発行しない。WALの`-wal`/`-shm`とmigration artifact setはrepositoryへ置かない。
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

`ProjectionStore`から`EventStore.append()`を呼ばない。`ModelGateway`から`EventStore`を呼ばない。P1-08のmaterializer、C-02承認時のP1-09 promotion、P1-12の`ScenarioRuntime`はcurrent `TurnRequestIdentity`を受け、Event ID / `OccurredAt`を持たないpre-ID `PreparedEffect`候補を返し、Stateを直接更新しない。候補はP1-08のper-execute immutable `TurnPreparationContext`をclosureに保持する`TurnEngine.bind_turn_preparation(*, context=...)`が返すbound callbackで最終`PreparedTurn.effect_candidates`へ合流し、既存のTurnEventBatchFactoryとcoordinatorの一回のappendへ渡す。C-02延期時はP1-09 producerを作らず、P1-12はP1-08のbase preparationへ独立に候補を追加する。

### Event readの利用契約

`EventStore.read_campaign(campaign_id)`が唯一の完全列readであり、戻り値は検証済み`tuple[DomainEvent, ...]`である。Projection rebuild、Event-derived Turn status、dice replay、`PublicProjection`、`PublicSessionView`のEvent-derived subsetのcallerはこのcampaign全体の`DomainEvent`列だけを入力にする。`PublicSessionView`の`narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`はEvent-derived subsetではなく、P1-11のtyped `PublicSessionPresentation`から供給する。`read_session()`、`read_turn()`、`find_turn_by_request()`も完全列検証後のinspection-only filterとして`DomainEvent`列を返し、snapshot、`TurnRequestStore`、Transcript、Telemetryをprojection/replayの入力へ渡さない。`StoredEvent`はappend returnとEventStore内部だけに閉じる。対象外rowの破損も`read_campaign()`がfail-closedにするため、downstreamが壊れたrowを見落とさない。

`SqliteDatabase`のpublic surfaceは`migrate()`だけであり、generic public `read`/`write`/retry/workerを持たない。Storeが公開するのは型付きreadと責務ごとのappend/claimだけである。`DomainEventValidationError`はそのまま伝播させ、SQLite例外を含む内部例外は安全な列挙codeだけへ変換して外へ出す。

---

## 8. WP依存関係と並列実行計画

### Batch 0 — neutral Event metadataの前提（完了済み）

P1-00（commit `b5c1bf3`）はPhase 1のneutral contract landing unitとして完了している。Event draft、batch metadata、Turn lifecycle metadataの型を`src/neontof/event_metadata.py`に置き、P1-03/P1-05/P1-08がApplication固有の未定義型へ依存しない境界を固定する。P1-04はrulesとdeterminismだけを担当し、`event_metadata`をimportしない。

### Batch 0b — Phase 1 repository guardへの移行（完了済み）

P1-00b（commit `31fab05`）はP1-01 preflightとBatch Aが依存するguard transitionとして完了している。Phase 0のexact production manifest、forbidden判定、Python gate order、Windows runner assertionを維持したまま、Phase 1で作るclient/migrations pathと、後続WPがrepository scannerをModifyできる境界を固定した。P1-00b自身はsource/protocol/connect scannerを検証済みとは扱わず、scanner全体をGreenとする証拠も残していない。現行HEADのP1-02まででは`tests/test_repository_contracts.py`に旧いbroad connect positiveが残っているため、P1-01cで補正する。

### Manifest直列化lane — 実履歴反映後

P1-01a（commit `eb284f9`）、P1-01b（commit `9ee2074`）、P1-02（commit `e5b7aa4`）は既に着地している。`tests/test_repository_contracts.py`をModify/stageするP1-01c以降のproduction WPは一つのmanifest serialization laneへ入り、exact production manifestを共有するため同一時刻にactiveにできるlane内WPは一つだけとする。P1-01a/P1-01b/P1-02を未来のP1-01a本体commitとして再実行せず、次のWPは前WPのfocused test、full quality Gate、`git diff --check`、明示commit、clean worktreeを確認してから開始する。

laneの実行順は、技術的依存と実履歴を満たす範囲で次のとおり固定する。

```text
P1-01a (eb284f9) → P1-01b (9ee2074) → P1-02 (e5b7aa4)
  → P1-01c scanner-hardening → P1-03 → P1-04 → P1-05
  → P1-06 → P1-07 → P1-08
  → P1-09（C-02承認時のみ、serial extension） → P1-12 → P1-11
  （C-02延期時はP1-08 → P1-12 → P1-11。P1-09とP1-12は同時編集・同時stageしない）
```

### WP依存関係

| WP | 開始条件 | 次の依存先 |
|---|---|---|
| P1-01a | P1-00bとpreflightのrepository guard（着地済み `eb284f9`） | P1-01b |
| P1-01b | P1-01aのEvent Store / migration（着地済み `9ee2074`） | P1-02 |
| P1-02 | P1-01bのProjectionと`0002`（着地済み `e5b7aa4`） | P1-01c |
| P1-01c | P1-02の着地、same-connection reader `1`、application append caller `0` | P1-03 |
| P1-03 | P1-01c scanner Green、P1-02、C-01 A、Persistence → Lifecycleの順 | P1-04 |
| P1-04 | P1-03のlifecycle boundary | P1-05 |
| P1-05 | P1-03 Lifecycle、P1-04のrules、authoring input | P1-06、P1-07、P1-12 |
| P1-06 | P1-03/P1-04/P1-05、C-03、provider approval | P1-07 |
| P1-07 | P1-05、P1-06の承認済みProvider boundary、C-01 A | P1-08 |
| P1-08 | P1-07、payload boundary、C-01 A | P1-09（C-02承認時）またはP1-12 |
| P1-09 | P1-08、C-02（承認時のみ） | P1-12（P1-09を実施する場合だけserialに後続） |
| P1-10a | P1-00bのclient path許可 | P1-10b |
| P1-10b | P1-10a、P1-11のserver contract | P1-13 |
| P1-11 | P1-12、P1-10aのclient contract、P1-09（C-02承認時のみ） | P1-10b、P1-13 |
| P1-12 | P1-05のauthoring input、P1-08のpre-ID prepare/TurnEventBatchFactory boundary | P1-11、P1-13 |
| P1-13 | P1-10b、P1-11、P1-12、全Phase Gate | Phase 2開始不可 |

各行の開始条件は依存WPのfocused/full Gate、明示commit、clean worktreeを含む。P1-01a/P1-01b/P1-02は実履歴の着地として扱い、P1-01cはその直後にscanner補正を行う。P1-10aだけはmanifest serialization lane外であり、他の依存関係を飛び越えない。P1-03は`0004`を先にPersistence lane、次にLifecycle laneの順で着地させ、P1-05はそのcoordinatorへbootstrapを委譲する。

上記の各WPは自分のproduction `.py` pathをexact manifestへ追加し、同じpathをModify、staging、commitへ含める。C-01 A boundary、C-02、C-03、provider approval、payload boundaryなどのStop Conditionでlane内のWPが停止した場合、後続lane WPを開始しない。lane順は共有manifestの競合を解消するための直列化であり、各WPの技術的な入口条件も別途満たす。
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
  → manifest serialization lane（P1-01a `eb284f9` → P1-01b `9ee2074` → P1-02 `e5b7aa4` → P1-01c → P1-03 → P1-04 → P1-05 → P1-06 → P1-07 → P1-08 → P1-09（C-02承認時のみ） → P1-12 → P1-11）
P1-00b
  → P1-10a（manifest lane外。P1-00からの技術的依存はない）
P1-02 + P1-01c scanner Green + C-01 A boundary fixed
  → P1-03
P1-03 + P1-05 + C-03 approval
  → P1-06 Fake/Recorded Gateway（normal invocation 1、zero retry、C-03 contract approved）
P1-06 Fake/Recorded GREEN + Provider approval + C-03承認済みexact contract
  → P1-06 concrete real Provider adapter 1つ
P1-06 concrete real Provider adapter path確定 + P1-05
  → P1-07
P1-07 + C-01 A boundary + payload boundary confirmation
  → P1-08
P1-08
  → P1-12（P1-08のbase prepareをserialに拡張。P1-09は必須依存ではない）
P1-08 + C-02 approval
  → P1-09（provisionalのbound prepare extension。P1-12と同じ`turn_engine.py`を同時編集・同時stageしない）
P1-09（C-02承認時のみ）
  → P1-12（P1-09実施時はP1-12がその後にserial extension。C-02延期時はP1-08から直接）
P1-12
  → P1-11（composition rootが`scenario_runtime`を後から注入）
P1-11 + P1-10a
  → P1-10b
P1-10b + P1-12
  → P1-13
```

Fake / Recordedのlocal validationはprovider approval前も続けてよいが、concrete real Provider adapterなしでFinal GateをPASSにしない。

P1-12 content validationはP1-05a完了後に実行する。P1-12 runtime behaviorはP1-08のbase prepare後に統合し、P1-09がC-02承認済みで実施される場合だけ、そのserial extensionの後に`turn_engine.py`へ統合する。P1-12の開始条件にP1-09のPromotionOutcomeは含めない。

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

P1-00はP1-01、P1-03、P1-05、P1-08、P1-09、P1-12が共有するneutral locationであり、Application固有のmetadataをEvent StoreやRulesへ逆向きに導入しない。`tests/test_repository_contracts.py`のproduction manifestには`src/neontof/event_metadata.py`が明示されている。EventのsequenceはP1-00でも呼び出し側でも割り当てない。`EventDraftBody`は既存`DomainEventBase`と同じ未採番wire envelopeだが、必須の`event_id`と`occurred_at`を持つため、EventDraft/EventBatchはpost-ID構成後のneutral boundaryでだけ返す。P1-00はI/O、parser、Event Store、materializationを実装しない。P1-03/P1-08/P1-09/P1-12のprepare、materializer、promotion、evaluatorはcurrent identityとvalidated campaign eventsを根拠に、`PreparedEffect`（pre-ID候補）または`PreparedTurn` / `PromotionOutcome` / `ScenarioAdvance`の`effect_candidates`だけを扱い、`EventDraft`、`EventBatch`、`DomainEvent`をpre-ID producerの返却型や保持値にしない。P1-03の`TurnPreparation`が返す`PreparedTurn`もpre-ID候補を内包するだけで、post-ID batchは返さない。P1-03のpost-ID factory/helper（通常Turnの`TurnEventBatchFactory`とrecovery builder）だけがEvent ID / `OccurredAt`付きの`EventDraft` / `EventBatch`を構成し、通常factoryはpre-ID候補から、recovery builderは保存済みmetadataから作る。これらはprepare/materializer producerの境界には含めない。`StoredEvent`はEventStoreのappend returnと内部materializationだけに閉じ、EventStoreの公開readは検証済み`DomainEvent`列を返す。P1-04はrulesとdeterminismだけを担当し、`EventMaterializationInput`と`TurnEventMetadata`をimportしない。
P1-12のscenario outcome producerもこの共有pre-ID境界に含まれる。`scenario_end`のsuccess/failureは既存FactAssertedの`ScenarioOutcomeFact` candidateへ変換され、P1-12のresponse/replayはそのFactRecordから復元し、P1-08 core responseは`scenario_outcome=None`を保持する。P1-12はEvent ID、`OccurredAt`、`EventDraft`、`EventBatch`を作らず、SessionEndedのpost-ID構成は`TurnEventBatchFactory`だけが担う。

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
- `sqlite3.connect`のCallは、P1-01cで補正する次の2 exact callsiteだけを各count `1`で許可する。`sqlite3.Connection`のtype annotation / `isinstance` referenceはpure positiveとし、`Connection`、`Cursor`、`Blob` constructor、arbitraryなpersistence sourceのconnectはrejectする。import alias、`from sqlite3 import ...`、別名参照などの変形でrepository source scanを逃れる実装を許可しない。これはP1-00b、P1-01a、P1-01b、P1-02の検証済み結果ではなく、P1-01c補正後のtarget contractである。

| role | path | qualified name | exact call count |
|---|---|---|---:|
| runtime | `src/neontof/persistence/sqlite_database.py` | `neontof.persistence.sqlite_database.SqliteDatabase._open_connection` | 1 |
| migration | `src/neontof/persistence/migrations.py` | `neontof.persistence.migrations._open_backup_connection` | 1 |
- repository test-side source scanはAST/import-awareに実行し、単純な文字列一致だけを回避する別名・import変形を検出する。repository guardはrepository tree直下・再帰下の`*.db`、`*.db-wal`、`*.db-shm`、`*.db-*`、`*.sqlite`、`*.sqlite-wal`、`*.sqlite-shm`、`*.sqlite3`を拒否し、WAL sidecarとvariantをGitへ入れない。

### P1-01cで補正するRepository source-scanとDB protocol scan

この節全体はP1-01a/P1-01b/P1-02の着地後に置くP1-01cのrepository contract scanner補正であり、P1-00b、P1-01a、P1-01b、P1-02では実装・実行・検証済みとは扱わない。P1-01cは`tests/test_repository_contracts.py`の既存`_SqliteUsageVisitor` / `_sqlite_usage_violations`をModifyして、caller allowlistとstorage DML scanを別の判定器として実装する。source候補はimportの有無に関係なく`src/neontof/**/*.py`を全て走査し、`tests/**`はproduction source scanから除外する。migrationは`src/neontof/persistence/migrations/*.sql`をraw bytesで別走査する。`uses_sqlite=False`はpotential sinkがないsourceだけのskipに限り、sqlite importの有無を理由にunknown wrapperを許可しない。

#### caller allowlistとEvent DML

- application-levelの`EventStore.append()` caller allowlistは、path、enclosing qualified name、call countを一つのexact tupleとして検査する。現在のP1-02直後はcaller `0`であり、P1-01cのscanは許可callerなしをpositive baselineとして検査する。後続の追加は次の遷移だけに限定する。

| 状態/WP | path | enclosing qualified name | exact call count |
|---|---|---|---:|
| P1-02直後 / P1-01c baseline | — | — | 0 |
| P1-03 | `src/neontof/application/turn_lifecycle.py` | `neontof.application.turn_lifecycle.TurnLifecycleCoordinator.execute` | 1 |
| P1-03 | `src/neontof/application/turn_lifecycle.py` | `neontof.application.turn_lifecycle.TurnLifecycleCoordinator.revert_latest` | 1 |

P1-03 Persistenceではapplication append callerを追加せず、P1-03 Lifecycleで上の2 tupleを追加して実countを`0`から`2`へ遷移させる。P1-05で同じowner classの次の1 tupleだけを追加し、実countを`2`から`3`へ遷移させる。

| WP | path | enclosing qualified name | exact call count |
|---|---|---|---:|
| P1-05 | `src/neontof/application/turn_lifecycle.py` | `neontof.application.turn_lifecycle.TurnLifecycleCoordinator.append_bootstrap` | 1 |

`TurnEngine`、`BootstrapApplicationService`、`ProjectionStore`、`ModelGateway`、Scenario runtime、別owner、wrong-pathの同名class/methodはrejectする。P1-01c時点の実countは`0`、P1-03 Persistence後も`0`、P1-03 Lifecycle後は`2`、P1-05後は`3`で固定し、caller allowlistの検査とstorage DMLの検査を同じ文字列ルールへまとめない。
- `events`へのDMLは次のstorage tupleだけを許可する。

| path | enclosing qualified name | static statement | exact call count |
|---|---|---|---:|
| `src/neontof/persistence/event_store.py` | `neontof.persistence.event_store.EventStore.append.<locals>.operation`（lexical parent: `EventStore.append`、unique nested operation） | `INSERT INTO events` | 1 |

許可はASTのlexical enclosureで判定し、同名method・別owner・別closureの名前一致では代用しない。
- append内または別owner/別closureの2個目の`INSERT INTO events`、`UPDATE`、`DELETE`、`REPLACE`、`INSERT OR REPLACE`、`DROP`、`ALTER`、index、trigger、trigger body、`sqlite_schema` / `sqlite_master`を含むsqlite catalog/schemaへのwrite、DML bypassは全てrejectする。quoted target、schema-qualified target、alias、CTE、case変形も同じstatic target解析へ通す。
- `0001_event_store.sql`の固定`CREATE TABLE events`だけをevents schemaの許可DDLとし、eventsを別migration・dynamic statement・triggerで作り直す経路を許可しない。`0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`の自分のtable追加は各WPのschema contractとして別途検証する。
- static targetが`events`またはcatalogでないDMLは、storage ownerとtable scopeの証明がある場合だけallowする。対象には`schema_migrations`、`transcript_entries`、`telemetry_entries`、`projection_snapshots`、`turn_requests`などを含むが、allowlistを広い`sqlite3`/`execute`許可へ緩めない。
- migrationのdynamic statementは、raw bytesのstrict UTF-8 decode、BOM reject、CRLF/LFとstatement completenessの検証、comments / strings / quoted identifiers / CTEを扱うtoken lexerを通し、`events`、catalog、trigger、bypassが無いことを証明できた場合だけallowする。文字列substringだけでSQLのtarget・comment・quoted identifierを判定しない。
- unknown receiver、unknown alias、rebind、`getattr`、動的SQL、unresolved callable、closure外からのDMLはfail-closedでrejectする。`EventStore`以外のclassが`events`へ書く経路、`EventStore.append`外の同名SQL、別nested closureもrejectする。
- `tmp_path`で作るsynthetic sourceを使い、wrong-pathの同名class/method、duplicate/third caller、別owner、`EventStore.append`外のnested closureをcaller scannerへ渡してrejectする。`test_eventstore_append_caller_allowlist_requires_exact_qualified_path_and_count`、`test_eventstore_append_caller_allowlist_rejects_wrong_path_same_name_duplicate_and_other_owner`、`test_eventstore_append_caller_allowlist_rejects_third_callsite`、`test_events_dml_allowlist_requires_exact_storage_path_and_nested_operation`、`test_events_dml_allowlist_rejects_duplicate_insert_and_other_owner`をnamed testとする。

`getattr`はDB mutation sinkと同一の許可にせず、unknown receiverとしてfail-closedにする。現行の非DB read/validationだけを7 lexical locations / 9 callsのexact allowlistとし、path・qualified name・countを次に固定する。

| path | qualified location | exact call count |
|---|---|---:|
| `src/neontof/persistence/event_store.py` | `neontof.persistence.event_store._assert_event_scalar_fields` | 2 |
| `src/neontof/persistence/event_store.py` | `neontof.persistence.event_store._readback_event` | 2 |
| `src/neontof/persistence/event_store.py` | `neontof.persistence.event_store.EventStore.read_turn` | 1 |
| `src/neontof/persistence/event_store.py` | `neontof.persistence.event_store.EventStore.find_turn_by_request` | 1 |
| `src/neontof/contracts/semantic_result.py` | `neontof.contracts.semantic_result._failure_status` | 1 |
| `src/neontof/contracts/semantic_result.py` | `neontof.contracts.semantic_result._validate_context` | 1 |
| `src/neontof/main.py` | `neontof.main._install_ctrl_break_handler` | 1 |

この表の合計7 locations / 9 calls以外の`getattr`、DB receiverの`getattr`、unknown wrapper、rebind、dynamic attribute、またはcount増加はrejectする。`test_sqlite_scan_rejects_unknown_receiver_alias_rebind_and_getattr`はこのfail-closed境界を検査する。

#### SQLite call / protocol / mutationの分類

`execute`、`executemany`、`executescript`、`cursor`、`backup`、`deserialize`、`blobopen`、`iterdump`、`serialize`、`setconfig`、extension call、`Blob` methodを一つのallowにせず、receiver・引数・lexical path・戻り値の用途ごとに分類する。

- current positiveは`_query_bounded`のsafe `SELECT` / `PRAGMA`、`_next_sequence`のliteral caller 2件、`read_telemetry`のselect + suffix `BinOp` 2 branches、direct introspection、`busy_timeout`の`Final 5000`、`query_only`の`IfExp`、runtime/migrationの`connect` `isolation_level=None` exact callsite各1件、P1-02直後の`ProjectionStore.rebuild` same-connection reader 1件、証明済みcursor flow、下記backup chainだけである。P1-03 Persistenceのclaim追加後はsame-connection readerを2件、P1-03 Lifecycle追加後はapplication append callerを2件、P1-05 bootstrap追加後は同callerを3件として再検査する。
- backupの唯一のpositive chainは`_backup_existing_database` → `_open_backup_connection` / `_is_same_file_database` / `_new_partial_backup_path` → `_copy_database_with_deadline`内の`source.backup(destination)` → verify/promoteとする。destinationはartifact pathであり、source/destinationの向き、`name="main"`、`pages=256`、`sleep=0.05`、`progress` callback、timeout/deadline/defaultsをexactに検査する。別backup receiver、引数順序違い、名前違い、未証明destination、別のcopy APIはrejectする。
- `deserialize`、extension/config mutation、`Blob.write`、unapproved Blob method、writable/unknown Blob、unknown callback、`Blob`のSubscript Store（point / slice / nested）、Connection/BLOB Attribute Store、operator `setitem` / `delitem`、unbound Blob itemはrejectする。read-only Blob lifecycleとread subscript、proven non-SQL-only methodだけをallowする。
- `setattr`、`delattr`、`object.__setattr__`、descriptor mutation、`operator.setitem` / `operator.delitem`、`setattr`相当の間接呼出しはDB receiverまたはunknown receiverならrejectする。ただし`src/neontof/contracts/event_parser.py`の`DomainEventValidationError.__init__`にある`object.__setattr__(self, "_issues", issues)`だけは、非SQLの既存exception初期化としてexact allowする。
- `Connection`のwith/context、`commit`、`rollback`、`autocommit`、`isolation_level` attribute mutationはrejectする。transaction SQLはcustom parserで次の6 lexical locationだけをallowし、各exact SQLのcountを`1`に固定する。

| path | qualified name | exact SQL | expected count |
|---|---|---|---:|
| `src/neontof/persistence/sqlite_database.py` | `neontof.persistence.sqlite_database._rollback` | `ROLLBACK` | 1 |
| `src/neontof/persistence/sqlite_database.py` | `neontof.persistence.sqlite_database.SqliteDatabase._write` | `BEGIN IMMEDIATE` | 1 |
| `src/neontof/persistence/sqlite_database.py` | `neontof.persistence.sqlite_database.SqliteDatabase._write` | `COMMIT` | 1 |
| `src/neontof/persistence/migrations.py` | `neontof.persistence.migrations._rollback` | `ROLLBACK` | 1 |
| `src/neontof/persistence/migrations.py` | `neontof.persistence.migrations._run_migrations` | `BEGIN IMMEDIATE` | 1 |
| `src/neontof/persistence/migrations.py` | `neontof.persistence.migrations._run_migrations` | `COMMIT` | 1 |

transaction parserは各許可箇所で表のexact tokenだけを一つのstatementとして受け付け、token消費後はwhitespaceだけを許し、その直後がEOFであることを確認する。末尾semicolon、末尾comment、semicolon後の第2 statement、comment以外のtrailing token、未消費token、EOF不一致は全てrejectする。`END`、`SAVEPOINT`、`RELEASE`、別のtransaction spelling、implicit commit、unknown wrapperも許可しない。migration SQL全体のstrict lexerがcomments / strings / quoted identifiersをtokenとして扱う契約とは別に、transaction callsite parserではcommentを含む余剰入力を許可しない。lock orderと`ApplicationRuntime.event_boundary_lock`はSQLite `_WRITE_LOCK`と別objectとしてsource上でも検査する。`test_only_six_transaction_sql_sites_are_allowed`をcurrent positive、`test_sqlite_scan_rejects_transaction_sql_with_semicolon_comment_trailing_token_end_savepoint_and_release`を代表sabotageとして追加する。
- coordinatorのlock orderは`ActiveTurnRegistry` → `ApplicationRuntime.event_boundary_lock` → EventStore operation内のSQLite `_WRITE_LOCK`に固定し、claimの`_write`、nested `_write`、逆順取得、boundary lockと`_WRITE_LOCK`の同一object化をrejectする。
- `ExitStack` / `AsyncExitStack`の`enter`、`push`、`callback`、`push_async`、`methodcaller`、unknown callback、`partial`、lambda captureによるDB operationの高階関数化はrejectする。known callbackはexact lexical flowとreceiverが証明できる場合だけallowする。
- `sqlite3` module attributeはreference（annotation / `isinstance`）とCallを分離する。`Connection`、`Cursor`、`Blob` constructorはrejectする。`connect`はruntimeとmigrationの2つのexact pathだけ、qualified receiver、args、kwargs、count=1を全て満たす場合にallowする。`Binary`、`complete_statement`、status constants、error classesはpure reference/callとしてallowし、unknown module attributeはrejectする。
- PRAGMAはcallsite、name、getter/setter、value、countをexactに検査する。`PRAGMA journal_mode=WAL` setterはmigration main connectionの初回transaction外の1件だけ、`busy_timeout=5000`、`synchronous=FULL`、`query_only` getter/setterは既定のexact pathだけをallowし、source/destination/verifierのjournal mode setterや未知PRAGMAはrejectする。

#### positive / sabotageのnamed tests

探索期のright-sizeを保つため、各AST/rule familyでcurrent positiveを1つ以上と代表sabotageを1つ以上だけ名前付きで固定し、absent APIの組合せ順列は増やさない。全て`tests/test_repository_contracts.py`の既存visitor/violation testへ追加する。

| family | current positive | representative sabotage |
|---|---|---|
| DML / lexical enclosure | `test_event_store_append_has_one_nested_events_insert` | `test_repository_scan_rejects_second_events_insert_or_replace_update_delete` |
| dynamic SQL / migration lexer | `test_migration_dynamic_statement_is_allowed_after_strict_token_scan` | `test_repository_scan_rejects_dynamic_sql_comment_string_cte_and_quoted_bypass` |
| source classification | `test_source_candidate_without_sqlite_import_is_skipped_only_without_sink` | `test_source_scan_rejects_no_import_unknown_sqlite_wrapper` |
| Call receiver / alias | `test_sqlite_call_receiver_positive_paths_are_exact` | `test_sqlite_scan_rejects_unknown_receiver_alias_rebind_and_getattr` |
| Attribute/Subscript Store | `test_event_parser_exception_object_setattr_is_non_sql_positive` | `test_sqlite_scan_rejects_connection_blob_and_operator_store_mutation` |
| Blob lifecycle | `test_read_only_blob_lifecycle_and_read_subscript_are_allowed` | `test_sqlite_scan_rejects_blob_write_unknown_blob_and_nested_subscript_store` |
| transaction | `test_only_six_transaction_sql_sites_are_allowed` | `test_sqlite_scan_rejects_transaction_sql_with_semicolon_comment_trailing_token_end_savepoint_and_release` |
| PRAGMA | `test_exact_pragma_positive_calls_are_allowed` | `test_sqlite_scan_rejects_unapproved_pragma_setter_or_value` |
| constructor/connect | `test_sqlite_type_references_and_exact_runtime_migration_connects_are_allowed` | `test_sqlite_scan_rejects_arbitrary_persistence_connect_and_constructor`; `test_sqlite_connect_exact_allowlist_rejects_duplicate_call_count` |
| cursor flow | `test_bounded_cursor_flow_is_allowed` | `test_sqlite_scan_rejects_cursor_flow_escape_and_unknown_callback` |
| backup | `test_existing_backup_chain_and_source_backup_direction_are_allowed` | `test_sqlite_scan_rejects_backup_receiver_argument_and_destination_bypass` |
| protocol / higher-order | `test_pure_sqlite_constants_and_known_callback_are_allowed` | `test_sqlite_scan_rejects_deserialize_extension_exitstack_methodcaller_partial_and_lambda_capture` |
| cross-module claim/projection | `test_projection_rebuild_has_one_same_connection_reader_before_claim`（P1-02直後） | `test_cross_module_scan_rejects_claim_read_campaign_or_nested_write` |

source scanのGREENはimportの表記を変えたpositiveではなく、exact lexical ownership、DML target、protocol receiver、transaction location、cross-module flowまでの証明が揃うこととする。unknown receiver、dynamic SQL、別connection、copied events、nested `_write`は常にfail-closedとする。

**P1-01c scanner laneで補正後に検証するnamed tests（P1-00b/P1-01a/P1-01b/P1-02では未検証）**

- `test_generated_directory_names_include_node_modules`
- `test_phase_1_client_and_migrations_paths_are_allowed`
- `test_forbidden_dockerfile_sdk_registry_and_generated_paths_remain_forbidden`
- `test_exact_production_manifest_requires_explicit_entries`
- `test_node_and_npm_are_not_rejected_by_ci_guard`
- `test_python_gate_order_is_preserved`
- `test_windows_runner_assertion_is_preserved`
- `test_sqlite_type_references_and_exact_runtime_migration_connects_are_allowed`
- `test_sqlite_scan_rejects_arbitrary_persistence_connect_and_constructor`
- `test_sqlite_source_scan_rejects_arbitrary_persistence_connect_alias_and_import_variants`
- `test_sqlite_connect_exact_allowlist_rejects_duplicate_call_count`
- `test_repository_guard_rejects_database_files_in_repository_tree`
- `test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants`

上記testは`tests/test_repository_contracts.py`だけに置き、exact production manifestの既存entry、forbidden SDK/registry、Dockerfile、client/node_modules、client/dist、DB file、Python gate order、Windows runner assertionを回帰させない。

**P1-01c scanner laneの検証コマンド（P1-02後に実行する）**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

このfocused commandはP1-01cのRED→Greenで実行し、guardの許可path、generated directory、node/npm、SQLite scope、alias/import variant、caller/DML exact tuple、transaction parser、または既存exact manifest/forbidden assertionの失敗を検出する。P1-00b、P1-01a、P1-01b、P1-02の完了をこのcommandのgreenとは読み替えない。collection errorや0 testだけを失敗根拠にしない。

**P1-01c scanner lane完了時の契約**

P1-01cがこのcommandを実行してexit `0`となった後だけ、production manifestが完全一致のまま明示entryだけを受け付け、forbidden判定を維持し、Phase 1のclient/migrations pathを許可し、node/npmをCIから排除せず、Python gate orderとWindows runner assertionを維持し、runtime/migrationの2 exact `sqlite3.connect` callsiteだけを各count `1`で許可する。`sqlite3.Connection`のtype annotation / `isinstance` referenceは許可し、arbitraryなpersistence connect、alias/import変形によるsource scan bypass、repository tree内のDB file、`client/node_modules`、`client/dist`は検出される。P1-00b、P1-01a、P1-01b、P1-02からscannerがgreenだったとは先取りしない。


## P1-01: Event StoreとProjection

### P1-01 事前確認 — repository guard / manifest / migration / SQLite source-scan の停止条件

P1-00bのfocused commandとGuard GateがGREENであること、ならびにP1-01a（`eb284f9`）、P1-01b（`9ee2074`）、P1-02（`e5b7aa4`）が着地済みであることを、P1-01事前確認の入口条件とする。P1-01事前確認自身では`tests/test_repository_contracts.py`を変更しない。P1-01a/P1-01b/P1-02のproduction manifest追加は実履歴に含まれており、次の同ファイルModifyはP1-01cのscanner補正に限定する。

既存production manifestの完全一致、forbidden判定、manifestの形式は変更しない。P1-01aの`src/neontof/persistence/migrations/0001_event_store.sql`と`src/neontof/persistence/migrations` directoryはP1-00bで許可され、既に`eb284f9`で着地している。Phase 1のmigration file setは、P1-01aの`0001_event_store.sql`、P1-01bの`0002_projection_snapshots.sql`、P1-02の`0003_observation_stores.sql`、P1-03の`0004_turn_requests.sql`で構成する。既存のPhase 0 migration、migration policy、contract manifestの形式、P0 contract fileは変更しない。既存entryの削除、glob/prefix化、forbidden SDK/registryの解除、またはP1-00bで明示されたclient/migrations pathとnode/npm usageの範囲を超える変更が必要になった場合は、P1-01cの最初のfile edit前に停止する。

SQLiteの更新経路は二つに分ける。repository test-sideは`tests/test_repository_contracts.py`が所有し、exact manifest、generated path、forbidden path、Python gate order、Windows runner、production sourceのAST/import-aware SQLite scopeを検査する。guide-sideは`docs/agent-guide/build-and-verify.md`が定義するSQLite scanを使い、同文書は直接編集しない。

repository test-sideのfocused evidenceは次で取得する。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

このtest-side scanは`sqlite3.connect`、`sqlite3.Connection`、`import sqlite3 as ...`、`from sqlite3 import ...`などのalias/import変形をAST/import-awareに検出し、単純な文字列一致だけを通す回避を許さない。現在のP1-02直後は、same-connection reader `1`、application-level `EventStore.append()` caller `0`を検査する。既存testで任意の`src/neontof/persistence/database.py`内`sqlite3.connect(':memory:')`をpositiveとしていた判定の置換、runtime/migrationの2 exact callsite（各count `1`）だけをCallのpositive、type annotation / `isinstance`の`sqlite3.Connection` referenceをpure positive、arbitraryなpersistence sourceのconnectをnegativeとする補正は、P1-01cで行う。Callの許可は`src/neontof/persistence/sqlite_database.py`の`neontof.persistence.sqlite_database.SqliteDatabase._open_connection`と`src/neontof/persistence/migrations.py`の`neontof.persistence.migrations._open_backup_connection`の2 exact callsiteだけである。

guide-sideのSQLite scanは`docs/agent-guide/build-and-verify.md`の`production forbidden source scan`全体をそのまま実行する。SQLite判定部は同文書の`Get-RgHitCount`経由の次のpatternと`sqlite_connection_hits`出力を含む。

```powershell
$sqliteConnectionHits = Get-RgHitCount -Pattern '(?i)(?:sqlite3\.connect|sqlite(?:\+|:))' -Path @('src')
"sqlite_connection_hits=$sqliteConnectionHits"
```

P1-01c後のguide-side policyは、runtimeの`neontof.persistence.sqlite_database.SqliteDatabase._open_connection`とmigrationの`neontof.persistence.migrations._open_backup_connection`という2 exact `sqlite3.connect` callsiteを各count `1`で扱い、type annotation / `isinstance`の`sqlite3.Connection` referenceをpositive、arbitraryなpersistence connectをnegativeとする。`sqlite3.Connection`のimport aliasを含むscope判定はrepository test-sideのAST/import-aware scanが担当し、guide-sideの単純な文字列scanだけで完了扱いにしない。P1-00b、P1-01a、P1-01b、P1-02はこのpolicyを検証済みとは扱わない。

P1-01cでは`docs/agent-guide/**`またはMyWorkflow正本を変更・deployせず、既存guide-side scanは読み取り専用の補助evidenceとして扱う。P1-01cの実変更はrepository test-sideの`tests/test_repository_contracts.py`だけとし、runtime/migrationの2 exact `sqlite3.connect` callsite（各count `1`）、type annotation / `isinstance` reference positive、arbitrary persistence connect negative、alias/import変形を含むsource scanner contractをこのtest-sideで補正・再検証する。文字列一致だけでalias/import変形を見逃す実装や、remote repair/pushによる迂回は認めない。

P1-01、P1-11、P1-13のruntime/test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置き、repository内の`*.sqlite`、`*.sqlite3`、`*.db`、`*.db-wal`、`*.db-shm`、`*.sqlite-wal`、`*.sqlite-shm`、raw DB backupを生成しない。P1-01aではさらに`*.db-*`、`*.sqlite3-wal`、`*.sqlite3-shm`、partial/verified migration artifact、`.neontof-migration-backups`をrepository treeへ生成しない。P1-01aのmigration/atomicity、P1-11のserver start/readiness/rollback、P1-13のcomplete run/playtest/rollbackは、このDB locationとguard statusを同時に検証する。

### P1-01a — SQLite schemaとatomic Event Store（完了済み: `eb284f9`）

**実履歴で作成済み**

- `src/neontof/persistence/__init__.py`
- `src/neontof/persistence/sqlite_database.py`
- `src/neontof/persistence/migrations.py`
- `src/neontof/persistence/migrations/0001_event_store.sql`
- `src/neontof/persistence/event_store.py`
- `tests/persistence/test_event_store.py`

**実履歴で変更済み**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`（既存`_SqliteUsageVisitor` / `_sqlite_usage_violations`をP1-01aで初期統合し、旧いbroad connect positiveを含む残存scannerの補正はP1-01cで行う）

P1-01aのproduction manifest追加は`src/neontof/persistence/__init__.py`、`src/neontof/persistence/sqlite_database.py`、`src/neontof/persistence/migrations.py`、`src/neontof/persistence/event_store.py`の4つであり、`eb284f9`に着地している。`src/neontof/persistence/migrations/0001_event_store.sql`はmanifestの`.py` entryではなく、P1-00bで許可されたmigration pathとして扱う。P1-01aの実履歴のwrite scopeは上記のCreate/Modify pathだけであり、`src/neontof/event_metadata.py`、`src/neontof/contracts/**`、`docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/**`、`docs/specs/**`、その他の上位文書を変更しない。P1-01b/P1-02/P1-03のtable・migration・Store実装と、P1-01cのscanner-hardeningをP1-01aへ戻さない。

#### P1-01a実履歴のscanner状態（補正はP1-01c）

P1-01aの実履歴はP1-00bから許可path、初期Event Store、旧guardの入口を引き継いだ状態であり、現HEADの`tests/test_repository_contracts.py`には旧scannerのbroad connect positiveが残っている。P1-01cのscanner補正は既存`tests/test_repository_contracts.py`の`_SqliteUsageVisitor` / `_sqlite_usage_violations`をModifyし、別のproduction scannerや別のrepository testを作らない。P1-01cで任意`src/neontof/persistence/database.py`の`sqlite3.connect(':memory:')` positiveを削除し、runtime/migrationの2 exact callsiteを各count `1`、`sqlite3.Connection`のtype annotation / `isinstance` referenceをpure positive、arbitrary connectをnegativeへ置換する。

P1-01cのscanner laneは、P1-00b直後に定義されたcaller-level allowlist、storage DML、raw migration lexer、source classification、SQLite Call / Attribute / Subscript Store、Blob、transaction、PRAGMA、constructor/connect、cursor、backup、protocol / higher-order、cross-module claim/projectionの各current positiveと代表sabotageを、同じvisitor/violation testへ明示的に追加する。caller-level EventStore.append allowlistとstorage DML scanは別判定器のままにする。P1-02直後のcurrent positiveはsame-connection reader `1`とapplication append caller `0`である。`getattr`の7 lexical locations / 9 calls、exact runtime/migration connectの2 path / 各count `1`、`test_sqlite_connect_exact_allowlist_rejects_duplicate_call_count`、wrong-path / duplicate / third / other-owner sabotageをP1-01cのnamed testsとする。

P1-01aの実履歴ではRED/GREENを次のcommandで確認したが、旧scannerの残存broad connect positiveと、P1-01cで補正するDML/protocol/source-classification enforcementはP1-01aの完了済み契約へ読み替えない。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

P1-01cのscanner implementationとnamed testsはP1-02後の別補正へ置き、P1-01aの実履歴へ戻さない。P1-03がscanner greenを前提に開始できるのは、P1-01cの同じcommandがexit `0`となり、P1-02後の既存guard、exact manifest、same-connection reader `1`、application append caller `0`、runtime/migration 2 exact connect、type reference positive、arbitrary connect negative、全rule familyのcurrent positive / representative sabotageが揃った後だけである。

このscanner補正のlogical commit file listはModify対象の`tests/test_repository_contracts.py`だけであり、P1-01aのproduction path、migration、P1-01b、P1-02のpathを再stageしない。scanner test/implementationをP1-00b、P1-01a、P1-01b、P1-02のcommitへ戻さず、P1-02後のP1-01cでRED→Greenを実行して明示的な`git add -- tests/test_repository_contracts.py`へ含める。P1-01c commit後だけP1-03はこのscannerのgreenを依存条件として扱う。

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
    "unknown_applied_version",
    "unsupported_database",
    "database_identity_mismatch",
    "backup_cleanup_failed",
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

`SqliteDatabase`のpublic surfaceは`migrate()`だけである。`migrations.py`のmodule-level `run_migrations`は存在せず、migration runnerはprivate `_run_migrations`へ閉じる。public backup/restore/cleanup/diagnostic API、generic read/write、retry、workerを追加しない。`path`以外のconnectionを保持せず、`_read(self, operation: Callable[[sqlite3.Connection], T]) -> T`、`_write(self, operation: Callable[[sqlite3.Connection], T]) -> T`、`_open_connection(self) -> sqlite3.Connection`はprivate exact signatureとして固定する。`_open_connection()`は`isolation_level=None`、`check_same_thread=True`、`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`を設定する。`migrate()`はshared `threading.Lock`を保持したまま、初回だけmigration connection上でtransaction外に`PRAGMA journal_mode=WAL`を一度設定し、その後にmigration transactionを実行する。以後のno-op再実行ではschema/write/backupを行わない。`_read()`はshared write lockを取らず、operationごとの別connectionに`PRAGMA query_only=ON`を設定してcallbackを実行し、connectionをcloseする。query-onlyはdefense-in-depthであり、主な境界はpublic surfaceとrepository guardである。`_write()`はshared `threading.Lock`を保持して`BEGIN IMMEDIATE`、callback、`COMMIT`を実行し、例外時は`ROLLBACK`してconnectionをcloseする。retryやworkerを暗黙に追加しない。

P1-01aのmigration backup helperは次のprivate exact signatureだけを持つ。全helperは`persistence/__init__.py`からexportせず、production global recorderやdiagnostic surfaceを追加しない。

```python
_BACKUP_DEADLINE_SECONDS: Final[float] = 10.0
_BACKUP_VERIFY_DEADLINE_SECONDS: Final[float] = _BACKUP_DEADLINE_SECONDS
_BACKUP_PAGES_PER_STEP: Final[int] = 256
_BACKUP_RETRY_SLEEP_SECONDS: Final[float] = 0.05
_BACKUP_MAX_BUSY_OR_LOCKED_RETRIES: Final[int] = 200
_BACKUP_BUSY_TIMEOUT_MILLISECONDS: Final[int] = 5000
_BACKUP_ROOT_NAME: Final[str] = ".neontof-migration-backups"
_BACKUP_PARTIAL_MARKER: Final[str] = ".partial.sqlite3"
_BACKUP_VERIFIED_MARKER: Final[str] = ".verified.sqlite3"

def _open_backup_connection(path: Path, *, query_only: bool) -> sqlite3.Connection: ...

def _is_same_file_database(
    migration_connection: sqlite3.Connection,
    backup_source: sqlite3.Connection,
    database_path: Path,
) -> bool: ...

class _BackupSource(Protocol):
    def backup(
        self,
        target: sqlite3.Connection,
        *,
        pages: int,
        sleep: float,
        name: str,
        progress: Callable[[int, int, int], None],
    ) -> None: ...

def _copy_database_with_deadline(
    source: _BackupSource,
    destination: sqlite3.Connection,
    *,
    deadline_seconds: float = _BACKUP_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> None: ...

def _backup_existing_database(
    migration_connection: sqlite3.Connection,
    database_path: Path,
) -> Path: ...

def _verify_backup(
    migration_connection: sqlite3.Connection,
    backup_path: Path,
    *,
    expected_journal_mode: str,
    deadline_seconds: float = _BACKUP_VERIFY_DEADLINE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> None: ...

def _remove_unverified_backup(backup_path: Path) -> None: ...

def _run_migrations(
    connection: sqlite3.Connection,
    database_path: Path,
) -> None: ...
```

`_backup_existing_database()`は`migration_connection`を比較元として受け取るが、そのconnectionから`Connection.backup()`を実行しない。`_run_migrations()`だけが`BEGIN IMMEDIATE`済みconnectionからこのhelperをprivateに呼び、copy直後destinationのjournal mode実値を`expected_journal_mode`としてverification chainへ渡す。productionの`_run_migrations()`にrestore責務を置かず、verified artifactをrestore sourceとして再openしない。

`MigrationIssueCode`のmigration固有codeは次の意味とsanitized surfaceへ固定する。`version_name_drift`/`checksum_drift`はapplied rowとavailable migration fileのidentity drift、`gap`はapplied rowsがcontiguous prefixでない状態、`duplicate`は`_discover_migrations`が検出したavailable migration file setの同一version重複、`unknown_applied_version`はavailable setにないapplied versionを表す。`unsupported_database`はPhase 1のfilesystem-backed regular file条件違反、`database_identity_mismatch`はcanonical requested path・migration `main.file`・dedicated source `main.file`の三者`samefile`不一致、`backup_cleanup_failed`は同じtokenのpartial/verified main・`-wal`・`-shm`全exact pathをcleanupできない状態、`backup_failed`はsource/destination open、copy、status、retry、deadline、close、reopen、journal mode、schema/data比較、promotionの失敗を表す。全て`MigrationError(code="...")`、固定message `migration failed`、元exceptionなしで公開し、path、OS message、SQLite value、sentinel、stack、cause、context、custom attributeを漏らさない。test-only restoreのfailureはproduction `MigrationError`へ変換しない。`DomainEventValidationError`、`DomainEventValidationIssue`、既存Domain `IssueCode`は変更しない。

P1-01aのDBはfilesystem-backed regular fileに限定する。`:memory:`、`file:`/`file://` URI、`mode=memory`、`cache=shared`、directory、FIFO/device等のspecial file、regular fileでないexisting target、canonical pathを解決できないpath、空またはregular fileでない`PRAGMA database_list`の`main.file`は、source openとDDLより前に`MigrationError(code="unsupported_database")`へ変換する。新規DBは接続前にnon-strict canonical pathと親directoryを検証し、接続後の`main.file`をstrictに検証する。既存DBはsource open前に`Path.resolve(strict=True)`を完了する。

source open前に、指定`database_path`のcanonical pathとmigration connectionの`PRAGMA database_list`にある`main.file`をregular fileとして検証し、`os.path.samefile()`で一致させる。source open後は、(1)指定pathのcanonical path、(2)migration connectionの`main.file`、(3)dedicated backup source connectionの`main.file`の三者を`os.path.samefile()`で検証する。relative pathはcanonicalization後に受理し、hard-link aliasも三者が同一fileなら受理する。別fileを開いたsource、指定pathとmigration `main.file`の不一致、指定pathとsource `main.file`の不一致は`MigrationError(code="database_identity_mismatch")`としてDDL前に停止する。

source、destination、reopen verifierの`sqlite3.connect` kwargsは次だけに固定する。

```python
sqlite3.connect(
    path,
    timeout=5.0,
    isolation_level=None,
    check_same_thread=True,
    uri=False,
)
```

dedicated backup sourceとreopen verifierは`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`、`PRAGMA query_only=ON`を設定して値`1`をreadbackする。copy destinationは同じ`busy_timeout`と`synchronous`を設定し、`query_only`が`0`であることをreadbackする。source、destination、reopen verifierに未指定kwargs、`uri=True`、別`factory`、`detect_types`、`autocommit`、別`isolation_level`、別`check_same_thread`を追加しない。source、destination、reopen verifierは同じthreadで開閉し、他operationへ渡さない。

migration connectionも`timeout=5.0`、`isolation_level=None`、`check_same_thread=True`、`uri=False`、`PRAGMA busy_timeout=5000`、`PRAGMA synchronous=FULL`を固定し、`PRAGMA query_only`のreadbackを`0`として確認する。migration connectionの`main.file`はcanonical requested pathと`samefile`で一致し、copy destinationの`main.file`はpartial mainのcanonical path、reopen verifierの`main.file`はpartial mainのcanonical pathとそれぞれ`samefile`で一致しなければ`backup_failed`としてDDL前に停止する。destinationとreopen verifierはlive databaseとは別fileであることを確認し、artifact pathの文字列一致だけをidentityの根拠にしない。

初回の`PRAGMA journal_mode=WAL` setterはmigration main connectionだけにtransaction外で一度だけ許可する。dedicated source、copy destination、reopen verifierのhelperは`PRAGMA journal_mode=...` setterを発行せず、read-onlyの実値だけを取得する。migration main、source、`Connection.backup()`直後destination、close/reopen後reopen verifierのjournal mode実値を同一operationで比較し、`wal`、`delete`その他の値へ固定しない。WAL sourceからbackupしたdestinationが`wal`となる実測を受け入れ、journal modeを`DELETE`へ強制しない。

`EventStore`は`from neontof.event_metadata import EventBatch, EventDraftBody, StoredEvent`でneutral typeをimportし、EventBatchの永続化を所有する。application-levelで`EventStore.append()`へ検証済みbatchを渡すのは`TurnLifecycleCoordinator`だけである。`append(batch)`は未採番`EventDraftBody`を受け取り、同じ`BEGIN IMMEDIATE` transaction内でsequenceを割り当て、各draftについて`_materialize_event_json(*, body: EventDraftBody, sequence: int) -> tuple[bytes, DomainEvent]`を呼ぶ。public generic `SqliteDatabase.read()`は存在せず、typed Storeのreadだけを公開する。

`_materialize_event_json()`の`body.payload_json`は、UTF-8 strictでdecodeできる単一の完全なJSON objectであり、DomainEventの`payload`全体を表す。materializerはenvelope組み立て前にpayload bytesを全入力消費し、末尾tokenを許さず、全階層のduplicate object keyを拒否し、root object以外を拒否する。duplicate object key拒否は既存`parse_domain_event`の機能ではなくEventStore materializerの先行guardであり、parser受理だけではduplicate key guardの証拠にならない。nested object/arrayのshapeは保持し、元のpayload bytesを再encodeしない。

EventStoreは固定順・compact JSONでenvelopeを構成し、bodyのscalar（`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`occurred_at`、`origin`、`visibility`）とtransactionでassignedした`sequence`をそれぞれ一度だけ出力し、検証済み`payload_json` bytesをouter `payload` valueとして一度だけ挿入する。payload bytesをenvelope fragmentとして連結しない。

完成したassembled bytesを既存`parse_domain_event`へ渡す。照合は二つに分ける。第一に、parsed `DomainEvent`の`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`sequence`（transaction assigned）、`occurred_at`、`origin`、`visibility`というscalar/envelope全fieldがbodyとassigned sequenceにstrict一致することを検証する。第二に、既存parserによるtyped payload validationの成功とは別に、persisted exact assembled `event_json`から特定したouter `payload` valueのbyte spanが検証済み`payload_json`の元bytesと一致すること、nested object/array shapeが保たれていることを検証する。この二つを合わせてenvelope全体の一致とする。既存`FrozenJsonValue`のlossy representationを比較根拠にしない。
`_materialize_event_json`とenvelope assemblerでは`EventDraftBody.model_dump_json()`、`EventDraftBody.model_dump()`、`DomainEvent.model_dump_json()`、`DomainEvent.model_dump()`、typed modelの汎用再encodeを一切使わない。outer scalarは固定fieldを標準JSON encoderで出し、`payload_json`の元bytesをouter `payload`のnested valueへ一度だけ挿入する。永続化対象の`event_json`はparser受理、scalar/envelope全fieldのstrict一致、typed payload validation、payload byte span一致を通過したexact assembled bytesだけとし、payload boundary failureを含むbatchは同一transaction全体をrollbackする。callerへsequence取得APIを公開しない。`SqliteDatabase`のconnection lifecycleを使う各storeは、自分が所有するtableのwrite transactionだけを実行する。

`read_campaign(campaign_id)`は`events`の全rowを`campaign_id`単位で`sequence ASC`に読み、sequenceが`1..N`の連番であることを確認する。全rowについてraw `event_json`のUTF-8、既存parserの受理、derived columnsとparsed `DomainEvent`のstrict一致、readbackした全fieldの一致を検証し、1件でも不正なら何も返さずsanitized errorでfail-closedにする。全件検証が完了してからだけ`tuple[DomainEvent, ...]`を返す。`_read_campaign_on_connection(connection, campaign_id)`も検証済み`DomainEvent`列を返し、`StoredEvent`を公開readへ持ち出さない。

`read_session()`、`read_turn()`、`find_turn_by_request()`はそれぞれ先に`read_campaign()`と同じ完全列を取得し、read_campaign完了後のvalidated memory filterだけを行う。filtered SQLを直接実行して対象外rowを見落とさない。いずれも`tuple[DomainEvent, ...]`を返し、`read_session()`は指定`campaign_id`と`session_id`、`read_turn()`は指定`turn_id`に一致するEvent、またはvalidated `TurnReverted.payload.target_turn_id`が一致するEventを返す。`find_turn_by_request()`はvalidated `PlayerInputAccepted.payload.turn_request_id`だけを候補として走査し、top-level envelopeや`TurnRequestStore`のcoordination rowを参照しない。`0001_event_store.sql`にはrequest lookup indexを作らない。該当しなければ全て`()`を返し、全ID lookupは`campaign_id`のscope内に限定する。対象外の壊れたrowがあってもfilter結果を返さず、完全列検証のfailureをそのままfail-closedにする。Projection rebuild、Turn status、dice、public projectionはこの`read_campaign()`の完全な`DomainEvent`列だけを入力にする。

### migration runnerの固定契約

`migrations.py`はmigration directoryの`*.sql`をfilename bytesとして`Path.read_bytes()`し、raw bytesそのものに`hashlib.sha256(raw_bytes).hexdigest()`を適用する。checksum計算で改行・encoding・whitespaceを正規化しない。実行時だけUTF-8 strictでdecodeし、各statementを同じconnectionの明示transaction内で実行する。implicit commitを起こす実行経路を使わない。`schema_migrations`の各rowは`version`、`name`、`checksum_sha256`を持ち、現行fileのversion/name/checksumと完全照合する。

`migrate()`の順序と失敗境界は次のとおり固定する。

```text
SqliteDatabase.migrate()
  → process-wide write lockを取得
  → migration connectionを固定kwargsでopen
  → canonical pathとmigration main.fileをsource open前かつDDL前に検証
  → migration connectionだけで必要ならtransaction外にjournal_mode=WALを一度設定
  → BEGIN IMMEDIATE
  → sqlite_masterでtype='table'のschema_migrations存在を確認
  → 存在しない場合はapplied setを空にし、schema_migrationsをSELECTしない
  → 存在する場合はtable shapeを検証してからschema_migrations read
  → migration file setとapplied version/name/checksumのvalidationおよびpending判定
  → pendingかつ既存schema/dataがある場合だけdedicated read backup sourceをopen
  → canonical path・migration main.file・source main.fileの三者samefile検証
  → sourceからrepository外の新しいpartial destinationへConnection.backup()
  → copy直後destinationのjournal mode実値をreadback
  → destination/sourceをclose
  → partial basenameのmain/-wal/-shm全exact path集合を確認
  → partial mainをreopen verifierで開き、journal mode・identity・schema・table shape・全dataをdeadline付きで実比較
  → reopen verifierをcloseし、partial basenameの全exact path集合を再確認
  → clean close後に同一basenameのartifact setを対応するverified pathへpromotion、またはpartial/verified全exact pathをcleanup
  → backup_verified
  → pending migrationのDDL
  → schema_migrations row insert
  → COMMIT
```

`schema_migrations`の存在確認は`sqlite_master`への`type='table'`を含む明示的な照会で行う。存在しない場合だけapplied setを空にし、同tableへのSELECTを行わない。存在する場合は`PRAGMA table_info(schema_migrations)`等でtable shapeを検証してから読む。任意の`no such table`をbootstrap扱いにして握り潰さない。schema_migrationsのtable shape不一致、予期しないSQLite error、またはread failureはその場で安全な`MigrationError`として扱い、空setへ置換しない。available migration file setの同一version重複は`_discover_migrations`側で検出する。applied rowsがcontiguous prefixであること、gap、unknown applied version、version/name/checksum driftは同じtransaction内でDDL前に実DBから検証する。applied schema_migrations rowのduplicateは`schema_migrations.version`のPRIMARY KEYが挿入時に拒否するため実DB validation対象にしない。exact schemaは適用順序を保持しないためPhase 1では適用順序を検証対象外とし、runnerは未適用migrationをversion昇順にだけ適用する。pendingがなければDDL、row insert、backupを行わず、no-op再実行とする。

pending migrationがあり、DBに既存のnon-system schemaまたはdataがある場合だけ、write lockと`BEGIN IMMEDIATE`を保持したmigration transaction内で専用read backup sourceをopenする。migration connection自身を`Connection.backup()`のsourceにせず、sourceからrepository tree外の新しいpartial destinationへcopyする。destination、source、reopen verifierをcloseし、copy直後destinationとclose/reopen後verifierのjournal mode実値がmigration main/sourceのreadback実値と同値であることを検証する。partial basenameのmain/`-wal`/`-shm`を一つのartifact setとしてclean close後にpromotionし、集合不整合、実schema/data mismatch、copyまたはverification deadline超過、unexpected status、close失敗、promotion失敗時はDDL前に停止して全exact path cleanupを行う。cleanup不能時は`MigrationError(code="backup_cleanup_failed")`、その他は`MigrationError(code="backup_failed")`へsanitizedに変換する。新規DB、zero-byte DB、または既存schema/dataがなくbackup不要な場合はcopyしない。copyとverificationはProduct Plan §20のWeb backup機能を先取りするものではなく、W-Dで必要な最小copyである。backup file、partial/verified artifact set、`-wal`/`-shm`はGitへ入れない。

copyの呼び出しは次だけに固定する。

```python
source.backup(
    destination,
    pages=_BACKUP_PAGES_PER_STEP,
    sleep=_BACKUP_RETRY_SLEEP_SECONDS,
    name="main",
    progress=progress,
)
```

copy開始時の`time.monotonic()`に`_BACKUP_DEADLINE_SECONDS == 10.0`秒を加え、callbackごと、BUSY/LOCKED retry前、`backup()` return直後にdeadlineを確認する。`SQLITE_OK`は`0 <= remaining < total`のcopy進行中statusとして受理し、`SQLITE_DONE`は`remaining == 0`の最終statusとしてだけ成功扱いにする。`SQLITE_BUSY`/`SQLITE_LOCKED`は最大`_BACKUP_MAX_BUSY_OR_LOCKED_RETRIES == 200`回までretryし、上限、deadline、SQLite例外、unexpected status、invalid progress、`SQLITE_DONE`なしのreturnは`MigrationError(code="backup_failed")`へ変換する。`pages=1`とscripted `monotonic`で`SQLITE_OK`を継続させても、`SQLITE_DONE`前の10秒超過でDDL/schema row writeを0にする。

`_verify_backup()`には`_BACKUP_VERIFY_DEADLINE_SECONDS == 10.0`秒を適用する。schema object、table shape、row/page batchの開始前とquery完了後に`monotonic`を確認し、全schema/data比較がdeadline内に完了しない場合はpromotionせず、partial/verifiedの全exact pathをcleanupして`MigrationError(code="backup_failed")`でDDL前に停止する。無期限のrow iterator、無制限の比較loop、deadlineを確認しない`fetchall`依存を許可しない。

backup rootはcanonical database pathのparentに隣接するrepository tree外の次のdirectoryに固定する。

```text
<canonical database path.parent>/.neontof-migration-backups/
```

root、partial artifact set、verified artifact setは`migrations.py`の現在のbackup invocationが所有する。background cleanup、global共有temp root、Web UI、generic backup service、public restore API、artifact一覧・世代管理・公開diagnosticを追加しない。

artifactはdatabase basenameと一意のlowercase hexadecimal tokenを含み、partialとverifiedそれぞれについて同一basenameのmain/`-wal`/`-shm`全exact pathを候補集合とする。

```text
<database.name>.migration-<lowercase-hex-token>.partial.sqlite3
<database.name>.migration-<lowercase-hex-token>.partial.sqlite3-wal
<database.name>.migration-<lowercase-hex-token>.partial.sqlite3-shm
<database.name>.migration-<lowercase-hex-token>.verified.sqlite3
<database.name>.migration-<lowercase-hex-token>.verified.sqlite3-wal
<database.name>.migration-<lowercase-hex-token>.verified.sqlite3-shm
```

copy destinationは新規regular fileとし、journal modeを`DELETE`へ固定しない。`Connection.backup()`直後、destinationがopenの状態でjournal modeの実値をread-onlyで取得して記録し、destinationとdedicated sourceをcloseする。close後にpartial basenameのmain、同じbasenameの`-wal`、同じbasenameの`-shm`をそれぞれexact pathで確認する。partial mainをreopen verifierで開き、migration main・source・copy直後destination・close/reopen後verifierのjournal mode実値、identity、schema、table shape、全dataを比較する。reopen verifierをcloseした後に同じ全exact path集合を再確認し、clean closeが成立した場合だけpromotionまたは全exact path cleanupへ進む。

sidecarが存在する場合はpartial mainだけをverifiedへrenameせず、同一basenameのpartial全存在pathを対応するverified全pathへ同じtokenのままpromotionする。sidecarが存在しない場合だけpartial mainをverified mainへpromotionする。異なるbasenameのsidecar、partial/verified間で不揃いなpath、close後のpath変化、close失敗、promotion途中の失敗を検出した場合はpromotionせず、partial main、partial `-wal`、partial `-shm`、同じtokenのverified main、verified `-wal`、verified `-shm`の全exact pathをcleanup対象にする。いずれかを削除できなければ`MigrationError(code="backup_cleanup_failed")`としてDDL前に停止し、全pathのcleanupに成功した場合は`MigrationError(code="backup_failed")`としてDDL前に停止する。無関係なpath、別basenameのsidecar、globによる無差別削除、recursive deleteは使わない。

promotion後のverified artifact setは、同一basenameでpromotion時に存在したmain、`-wal`、`-shm`だけを保持し、別basenameのsidecarを引き継がない。成功`COMMIT`後も、verified化後の後続DDL failureでlive DBをrollbackする場合も、verified artifact setはoperator/test fixtureへ引き継いで保持する。operator/testが明示的に保持期間を終えた場合だけ同一basenameのverified全exact pathをcleanupし、そのcleanup failureは成功扱いにしない。migrationはartifact pathをpublic return、通常log、DB rowへ書かない。

`_verify_backup(migration_connection, backup_path, *, expected_journal_mode, deadline_seconds, monotonic)`は、destination/sourceのclose完了後にpartial mainをreopen verifierで開き、`sqlite_master`、各tableの`PRAGMA table_info`/`index_list`/`index_xinfo`/table SQL、全tableの全row、BLOB bytes、`schema_migrations`、`events`のderived columns、`typeof(event_json) = 'blob'`、raw `event_json` bytesを実比較する。文字列、file size、checksum、mockのverify callだけを成功根拠にしない。全schema/data比較を読み終えるまでrow/page batchごとにdeadlineを確認し、実data/schema mismatchまたはverification deadline超過はpromotionせず`backup_failed`としてDDL前に停止する。

test-only timelineはproductionへglobal recorder、diagnostic field、Telemetry、通常logを追加せず、各private helperの実関数へ委譲するspyと、test側だけでmigration connectionへ設定する`set_trace_callback`を組み合わせて記録する。spyはイベント記録後に実helperを実行し、trace callbackはmigration connectionの実SQLを同じtest-local timelineへ記録する。copy直後のpartial artifact変更が必要なtestは、実際のcopy helperを委譲するprivate helper spyまたはtest-only filesystem substitutionをdestination/sourceのclose後かつreal `_verify_backup()`前に挿入し、partialの同一basename main/`-wal`/`-shm`を別connectionで実際に変更する。verifierの成功値をmock注入しない。

最低限のtest-local timelineは`begin_immediate`、`backup_source_opened`、`three_way_identity_verified`、`destination_opened`、`copy_progress_SQLITE_OK`、`copy_done_SQLITE_DONE`、`destination_journal_mode_recorded`、`destination_closed`、`source_closed`、`partial_artifact_set_checked`、`reopen_verifier_opened`、`pragma_compared`、`schema_compared`、`table_shape_compared`、`data_compared`、`reopen_verifier_closed`、`partial_artifact_set_rechecked_after_close`、`artifact_promoted`、`backup_verified`、`ddl`、`schema_row_insert`、`commit`とする。実schema/data比較とartifact set promotionが完了した後にだけ`backup_verified`を記録し、`backup_verified < ddl`を同じtimelineでassertする。production timelineにrestoreを含めない。

restoreの責務はtest-onlyの独立検証に限定する。productionの`_run_migrations()`と`_backup_existing_database()`はverified artifactをrestore sourceとして再openせず、restore API/helperを持たない。`test_verified_backup_artifact_restores_schema_and_data`だけが、成功commit後または後続DDL failure後に保持されたverified basenameのmainを同一basenameの`-wal`/`-shm`と共にreopenし、disposable regular destinationへ実際にSQLite backupしてmigration前のschema、table shape、全data、BLOB、derived columnsを比較する。このcopyは`_copy_database_with_deadline()`を使い、schema/data比較も`_BACKUP_VERIFY_DEADLINE_SECONDS`または明示的row/page batch境界でboundedにする。test-only restoreのdeadline超過や不一致を成功扱いにしない。

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
- `test_schema_set_maximum_is_one_without_unknown_version`
- `test_bootstrap_checks_schema_migrations_existence_before_select`
- `test_bootstrap_validates_schema_migrations_shape_before_read`
- `test_bootstrap_does_not_swallow_unexpected_no_such_table`
- `test_migration_rejects_version_name_checksum_drift_before_ddl`
- `test_discover_migrations_rejects_duplicate_file_version_before_ddl`
- `test_migration_rejects_applied_gap_before_ddl`
- `test_migration_rejects_unknown_applied_version_before_ddl`
- `test_migration_validation_and_pending_detection_stay_inside_transaction`
- `test_migration_ddl_and_schema_row_share_transaction`
- `test_pending_migration_backups_existing_database_before_ddl`
- `test_new_database_does_not_create_backup`
- `test_noop_migration_does_not_backup_or_write`
- `test_backup_failure_prevents_ddl_and_schema_row_insert`
- `test_backup_reopen_verification_precedes_ddl`
- `test_backup_sidecar_state_is_closed_before_promotion`
- `test_backup_verifier_rejects_actual_data_mismatch_before_ddl`
- `test_backup_verifier_deadline_stops_before_ddl`
- `test_backup_source_uses_fixed_query_only_pragmas`
- `test_backup_source_destination_and_reopen_use_exact_connection_kwargs`
- `test_backup_connections_never_set_journal_mode`
- `test_backup_source_query_only_write_sabotage_fails`
- `test_backup_source_is_not_migration_connection`
- `test_backup_accepts_sqlite_ok_progress_until_done`
- `test_backup_deadline_applies_while_sqlite_ok_progresses`
- `test_backup_busy_deadline_stops_retry_before_ddl`
- `test_backup_unexpected_progress_status_fails_before_ddl`
- `test_backup_closes_source_destination_and_verification_connections`
- `test_backup_validates_migration_main_file_before_source_open`
- `test_backup_accepts_relative_database_path`
- `test_backup_accepts_hard_link_database_alias`
- `test_backup_rejects_database_identity_mismatch_before_ddl`
- `test_backup_required_for_in_memory_database_fails_before_ddl`
- `test_backup_rejects_uri_directory_and_special_file_before_ddl`
- `test_backup_artifacts_use_database_adjacent_root_and_exact_names`
- `test_unverified_backup_artifact_and_sidecars_are_removed`
- `test_verified_backup_artifact_is_retained_after_commit`
- `test_verified_backup_artifact_is_retained_when_later_ddl_fails`
- `test_verified_backup_artifact_restores_schema_and_data`
- `test_verified_backup_restore_is_bounded`
- `test_backup_timeline_records_schema_data_verify_before_ddl`
- `test_backup_cleanup_failure_is_sanitized`
- `test_sqlite_database_public_mutation_surface_is_only_migrate`
- `test_migrations_runner_is_private`
- `test_repository_guard_rejects_public_migration_runner`
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
- `test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants`

`test_materialized_domain_event_matches_body_and_assigned_sequence`はscalar/envelopeの`type`、`event_id`、`event_version`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、transaction assigned `sequence`、`occurred_at`、`origin`、`visibility`の全fieldをstrict assertし、typed payload validationの成功と、persisted exact assembled `event_json`内のouter `payload` byte spanが元の`payload_json` bytesと一致することを別々にassertする。`model_dump*`や既存`FrozenJsonValue`のlossy representationを比較根拠にしない。
`test_payload_json_rejects_duplicate_object_keys_at_any_depth`は既存parserへ渡す前のEventStore materializer guardを対象にし、parser受理だけをduplicate key拒否の証拠にしない。
`test_read_campaign_validates_every_row_before_returning`はcampaign内の全rowをsequence連番として読み、各`event_json`、derived columns、parser readbackを検証し、途中rowが不正なら結果を返さないことを確認する。`test_read_session_filters_only_after_complete_campaign_read`、`test_read_turn_matches_turn_id_or_revert_target`、`test_find_turn_by_request_uses_validated_player_input_payload`は全て同じ完全列からのinspection-only filterであることを確認する。`test_filtered_read_fails_closed_on_corrupt_out_of_scope_row`はfilter対象外の壊れたrowでもfail-closedになることを確認する。
`test_discover_migrations_rejects_duplicate_file_version_before_ddl`はavailable migration file setに同一versionのmigration fileを用意し、`_discover_migrations`側がDDL前に拒否することを確認する。`test_migration_rejects_applied_gap_before_ddl`と`test_migration_rejects_unknown_applied_version_before_ddl`は`_read_applied_migrations`のmonkeypatchを使わず、exact schemaの実DBへCHECK/UNIQUE/PRIMARY KEYを満たす`schema_migrations` rowを直接挿入してからmigrationを実行し、DDL、backup、row insertが一つも起きないことを確認する。applied schema_migrations rowのduplicateは`version PRIMARY KEY`が挿入時に拒否するため、実DB validation testにしない。`test_pending_migration_backups_existing_database_before_ddl`は既存schema/dataのpending時だけmigration source connectionからrepository tree外の新しいdestination connectionへSQLite backup API copyを先に作ることを、`test_backup_reopen_verification_precedes_ddl`はdestination close/reopen後のschema/data検証をDDLより前に行うことを、`test_new_database_does_not_create_backup`と`test_noop_migration_does_not_backup_or_write`は不要なcopy/writeがないことを確認する。
`test_migration_validation_and_pending_detection_stay_inside_transaction`はpending判定をtransaction外へ出さないことを、`test_migration_ddl_and_schema_row_share_transaction`はmigration DDLと`schema_migrations` row insertを同じtransactionでcommitすることを確認する。
`test_duplicate_event_id_becomes_sanitized_event_store_constraint_error`は同じwrite transaction内の事前照合で`EventStoreConstraintError(code="duplicate_event_id")`になることを、`test_other_integrity_error_becomes_generic_event_constraint_violation`はその他の`sqlite3.IntegrityError`が`EventStoreConstraintError(code="event_constraint_violation")`になることを確認する。`test_domain_event_validation_error_keeps_phase_zero_issue_codes`はpayload/envelope/sequence/readback validationの既存`DomainEventValidationError`がPhase 0の既存issue codeのまま伝播し、Event Store constraint errorへ変換されないことを確認する。これらと`test_database_error_becomes_safe_sqlite_operation_error`、`test_migration_error_does_not_leak_sqlite_details`はsecretを埋めたsabotage exceptionを使い、message、args、cause、context、custom attr、logのどこにも元exceptionが残らず、安全なcodeだけが出ることを確認する。

P1-01aのbackup testは、`test_pending_migration_backups_existing_database_before_ddl`でprocess-wide write lockと`BEGIN IMMEDIATE`後、DDL/schema row write前にdedicated sourceを開き、sourceがmigration connectionと別objectで、三者`samefile`が成立し、repository tree外の新しいpartial destinationへ実copyすることを確認する。`test_backup_reopen_verification_precedes_ddl`はmigration main/source/copy直後destination/close-reopen後reopen verifierのjournal mode実readback値一致、destination/source close、partial artifact set確認、real schema/data比較、reopen verifier close、path再確認、同一basename set promotion、`backup_verified`、DDLの順をtest-local timelineでassertする。production timelineにrestoreを含めない。

`test_backup_sidecar_state_is_closed_before_promotion`は`Connection.backup()`直後のdestination実journal modeをreadbackし、destination/source/reopen verifierがclean closeした後にpartial basenameのmain/`-wal`/`-shm`全exact pathを確認する。sidecarがあればmainだけをrenameせず、同一basenameの存在pathを対応するverified pathへpromotionし、不整合またはpromotion失敗ならpartial/verified全exact pathをcleanupする。削除不能は`backup_cleanup_failed`、DDL/schema row writeは0とする。`test_backup_verifier_rejects_actual_data_mismatch_before_ddl`は実copy helperを委譲するtest-only spyまたはfilesystem substitutionをcopy直後・destination/source close後・real `_verify_backup()`前に挿入し、partial artifactのschemaとdataを別connectionで実際に変更する。mockの成功値を使わずreal verifierが`backup_failed`を返し、DDL/schema row writeが0、cleanupが完了することを確認する。

`test_backup_source_uses_fixed_query_only_pragmas`、`test_backup_source_destination_and_reopen_use_exact_connection_kwargs`、`test_backup_connections_never_set_journal_mode`はsource/destination/reopen verifierのkwargs、`busy_timeout=5000`、`synchronous=FULL`、query-only、journal mode setter禁止、migration main/source/copy直後destination/close-reopen後verifierの実readback値一致を個別にassertする。`test_backup_source_query_only_write_sabotage_fails`、`test_backup_source_is_not_migration_connection`はsourceのwrite拒否とmigration connection自身をsourceにしないことを確認する。`test_backup_accepts_sqlite_ok_progress_until_done`、`test_backup_deadline_applies_while_sqlite_ok_progresses`、`test_backup_busy_deadline_stops_retry_before_ddl`、`test_backup_unexpected_progress_status_fails_before_ddl`は`SQLITE_OK`進行、`pages=1`、scripted `monotonic`、10秒deadline、BUSY/LOCKED 200回上限、unexpected statusを固定し、failure時はDDL/schema row writeを0にする。`test_backup_verifier_deadline_stops_before_ddl`はreal schema/data比較中の10秒verification deadline超過を`backup_failed`としてDDL前に止め、promotionとDDL/schema row writeを0、全exact path cleanupをassertする。

`test_backup_validates_migration_main_file_before_source_open`、`test_backup_accepts_relative_database_path`、`test_backup_accepts_hard_link_database_alias`、`test_backup_rejects_database_identity_mismatch_before_ddl`、`test_backup_required_for_in_memory_database_fails_before_ddl`、`test_backup_rejects_uri_directory_and_special_file_before_ddl`はfilesystem-backed regular file、canonical path、migration `main.file`、source `main.file`の三者identityを実filesystemで確認し、不正variantを`unsupported_database`または`database_identity_mismatch`としてDDL前に止める。`test_backup_artifacts_use_database_adjacent_root_and_exact_names`、`test_unverified_backup_artifact_and_sidecars_are_removed`、`test_verified_backup_artifact_is_retained_after_commit`、`test_verified_backup_artifact_is_retained_when_later_ddl_fails`はrepository外root、同一basenameのmain/`-wal`/`-shm`全exact path、owner、promotion、cleanup、commit後・後続DDL failure後の保持を確認する。`test_verified_backup_artifact_restores_schema_and_data`はproductionとは独立してverified artifact setをdisposable destinationへrestoreし、`test_verified_backup_restore_is_bounded`はrestore copyとschema/data比較にdeadlineまたは有限row/page batch境界を適用する。両testはrestore APIやproduction timelineを追加しない。

`test_backup_timeline_records_schema_data_verify_before_ddl`は、test-localのprivate helper spyが実helperへ委譲したイベントと、migration connectionへtest側だけで設定した`set_trace_callback`の実SQLイベントを同一timelineへ記録し、実schema/data比較・artifact set promotion完了後の`backup_verified < ddl < schema_row_insert`をassertする。productionへglobal recorder、diagnostic field、Telemetry、通常logを追加しない。`test_backup_cleanup_failure_is_sanitized`はpartial/verified全exact pathの削除不能を`backup_cleanup_failed`とし、残存path、OS message、sentinel、元exceptionをsurfaceへ漏らさないことを確認する。`test_sqlite_database_public_mutation_surface_is_only_migrate`、`test_migrations_runner_is_private`、`test_repository_guard_rejects_public_migration_runner`は`migrate()`以外のpublic mutation、module-level `run_migrations`、public backup/restore/cleanup/diagnosticを拒否する。`tests/test_repository_contracts.py`の`test_repository_guard_rejects_sqlite_wal_sidecars_and_db_variants`はrepository tree内の`*.sqlite`、`*.sqlite3`、`*.db`、`*.sqlite-wal`、`*.sqlite-shm`、`*.sqlite3-wal`、`*.sqlite3-shm`、`*.db-wal`、`*.db-shm`、partial/verified migration artifact、backup rootを拒否する。

既存のchecksum/driftテスト（`test_migration_rejects_version_name_checksum_drift_before_ddl`）、available migration file setの重複検出テスト（`test_discover_migrations_rejects_duplicate_file_version_before_ddl`）、applied rowsのgap/unknown検証テスト（`test_migration_rejects_applied_gap_before_ddl`、`test_migration_rejects_unknown_applied_version_before_ddl`）、BLOB/derived検証テスト（`test_event_json_storage_type_is_blob`、`test_materialized_domain_event_matches_body_and_assigned_sequence`）、read-lock境界テスト（`test_read_uses_separate_connection_outside_write_lock`、`test_read_connection_enables_query_only_as_defense_in_depth`）は、P1-01aの実履歴でdedicated source、artifact lifecycle、real schema/data verification、既存のlock外`_read`契約を検査した。`tests/test_repository_contracts.py`のpublic surface/DB variant guardも、P1-01aのprivate runnerと同一basename artifact setを含む形で実履歴に反映されている。

**着地時の検証条件（実履歴）**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_event_store.py tests/test_repository_contracts.py -q
```

着地時のfocused commandは、`0001_event_store.sql`のschema-set assertion、migration validation（`_discover_migrations`のavailable migration file set同一version重複、exact schemaの実DBへrowを直接挿入するapplied gap/unknown、contiguous prefix、version/name/checksum drift）/backup順序、専用source ownership、fixed connection kwargs/PRAGMA、filesystem identity、journal mode実値一致、artifact set lifecycle、bounded copy/verification/restore、atomicity、payload boundary（root object、strict UTF-8、trailing token、全階層duplicate key、fragment override）、campaign全列read、filter fail-closed、exception sanitization、production manifestの追記漏れまたは未許可pathを検証した。collection errorまたは0 testを成功根拠にはしない。

```text
実履歴のfocused command exit 0、failure 0。列挙したboundary assertionとmanifest/forbidden guardを確認済み。
```

**完了済みの契約**

同じcommandがexit `0`となり、`tests/test_repository_contracts.py`のmanifest/forbidden guardもpassしたうえで、`0001_event_store.sql`が`schema_migrations`と`events`だけを作り、schema-setのapplied version最大値が1で欠落・未知versionがないことをevidenceとして示す。raw SQL bytes SHA-256、`_discover_migrations`によるavailable migration file setの同一version重複検出、applied rowsのcontiguous prefix/gap/unknown applied version/version/name/checksum driftのDDL前実DB検証、`SqliteDatabase.migrate()`だけのpublic mutation entry、private `_run_migrations`、必要時だけの`BEGIN IMMEDIATE`後dedicated sourceによるrepository tree外SQLite backup API copy、三者`samefile`、journal mode実値一致、同一basename artifact setのpromotion/cleanup、backup失敗・実data/schema mismatch・verification deadline超過時のDDL無実行、no-op時のbackup/write無実行、DDLとschema rowの同一transactionが成立する。exact schemaは適用順序を保持しないためPhase 1では適用順序を検証せず、未適用migrationはversion昇順にだけ適用する。

strict UTF-8、single root object、全入力消費、trailing token拒否、全階層duplicate key拒否、fragment override拒否、nested object/array shape distinction、payload boundary failure時のbatch全体rollbackも成立する。固定順compact envelopeへbody scalarとassigned sequenceを一度ずつ出力し、検証済みpayload bytesをouter `payload` valueへ一度だけ挿入したexact assembled bytesが既存parserに受理され、scalar/envelope全fieldのstrict一致、typed payload validation、persisted `event_json`のpayload byte span一致が別々に成立し、そのexact bytesが保存される。

`SqliteDatabase`にpublic generic read/write、retry、worker、public `run_migrations`、public backup/restore/cleanup/diagnosticがなく、fixed connection kwargs/PRAGMA、journal mode実値一致、single writer lockが成立する。`read_campaign`が全sequenceと全rowを検証してから返り、typed Storeのfiltered readが同じ完全列からだけ結果を作り、対象外rowの破損でもfail-closedになる。validated lifecycle payloadによるturn request検索とunsequenced envelope materializationの境界も成立し、caller側にsequence割当やgeneric public writeが存在しないこともassertする。Integrity/Database/Migrationのexceptionは安全なcodeだけを持ち、元exceptionを漏らさない。runtime/test DBとbackup rootはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置く。`PRAGMA table_info(...)`、`PRAGMA index_list(...)`、`PRAGMA index_xinfo(...)`、`sqlite_master.sql`、`typeof(event_json) = 'blob'`、NOT NULL/CHECK/UNIQUE sabotage、backup close/reopen後のreal schema/data検証、artifact set promotion/cleanup、bounded verifier、test-only restoreもpassする。

**実履歴のコミット境界**

```powershell
git add -- src/neontof/persistence/__init__.py src/neontof/persistence/sqlite_database.py src/neontof/persistence/migrations.py src/neontof/persistence/migrations/0001_event_store.sql src/neontof/persistence/event_store.py tests/persistence/test_migrations.py tests/persistence/test_event_store.py tests/test_repository_contracts.py
```

実履歴ではtests、SQLite policy、migration schema-set、exception boundary、repository guardを確認したうえで、上記pathを一つのlogical GREEN commitへまとめた。P1-01aのcommitには`0001_event_store.sql`だけを含め、後続migration/tableを含めていない。

```text
feat: append-onlyなSQLite Event Storeと原子性を実装する
```

受入れ証拠:

- 故意に2件目を失敗させたbatch後のEvent件数`0`
- 同じEvent列のread結果が入力順と一致
- public State update methodが存在しない
- `0001_event_store.sql`適用後のschema-setが`schema_migrations`と`events`だけで、最大適用versionが1
- raw SQL bytes SHA-256、`_discover_migrations`によるavailable migration file setの同一version重複検出、applied rowsのcontiguous prefix/gap/unknown applied version/version/name/checksum driftのDDL前実DB検証
- pending existing schema/dataだけで`BEGIN IMMEDIATE`後のdedicated sourceからrepository tree外backup API copy、source/migration/destination/reopenのidentity・journal mode実値一致、backup failure・実data/schema mismatch・verification deadline超過時DDLなし、新規DB/no-op時backup/writeなし
- partial/verifiedの同一basename main/`-wal`/`-shm` artifact setのclean close後promotion、全exact path cleanup、cleanup failure時`backup_cleanup_failed`、成功commit時・後続DDL failure時のverified artifact set保持
- test-onlyのprivate helper委譲spy・migration connection `set_trace_callback` timeline、copy後partial改変からreal verifierが返すfailure、bounded test-only restore
- `read_campaign`の全sequence/全row/derived/readback検証、inspection-only filter、対象外破損rowでfail-closed
- fixed SQLite PRAGMA、shared write lock、別connection read、safe exception code、元exception非漏洩

### P1-01b — Projection snapshotとrebuild（完了済み: `9ee2074`）

**実履歴で作成済み**

- `src/neontof/persistence/projection_store.py`
- `src/neontof/persistence/migrations/0002_projection_snapshots.sql`
- `tests/persistence/test_projection_store.py`

**実履歴で変更済み**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`

P1-01bのproduction manifest追加は`src/neontof/persistence/projection_store.py`だけである。`ProjectionStore`が`projection_snapshots` tableとsnapshot recordを所有し、migration pathは`src/neontof/persistence/migrations/0002_projection_snapshots.sql`とする。このSQLはproduction `.py` manifest entryではない。`0002`は`projection_snapshots` tableだけをadditiveに作り、down migrationを作らない。P1-01aの`0001_event_store.sql`へ追記しない。migration実行後のschema-setの最大適用versionは2で、1から2まで欠落・未知versionなし、version/name/raw SQL bytes SHA-256 checksumのdriftなしをevidenceにする。

`0002_projection_snapshots.sql`の最小schemaは次のとおりである。P1-01bで実装済みで、実履歴ではmigration適用後に再検証した。P1-01aで先取りしていない。

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

`rebuild()`は`SqliteDatabase._write()`の同じwrite lock critical section内で、(1) connection上のEvent read、(2) `read_campaign`と同じ全row/連番/derived/readback validation、(3)返されたvalidated `DomainEvent`列を純粋な`rebuild_projection(events)`へ渡す、(4) monotonicなsnapshot upsertを順に行う。`EventStore.read_campaign()`を内側から呼んでnested `_read`やlockを発生させず、`EventStore._read_campaign_on_connection()`を使う。このsame-connection readerはP1-01bの1 callsiteである。filtered `read_session()`、`read_turn()`、`find_turn_by_request()`、既存snapshot、coordination record、observationをrebuild入力にしない。

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

**実履歴の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_projection_store.py tests/test_repository_contracts.py -q
```

実履歴のfocused commandでは`0002_projection_snapshots.sql`のschema-set assertion、manifest追記漏れ、未許可path、またはstale barrierでthrough sequenceが後退することを失敗理由として確認した。collection errorまたは0 testを成功根拠にはしない。

**完了済みの契約**

全testと`tests/test_repository_contracts.py`がpassし、manifest/forbidden guardもexit `0`となる。`0002_projection_snapshots.sql`が`projection_snapshots`だけをadditiveに作り、`campaign_id` primary key、`through_sequence >= 0`、BLOBの`projection_json`を持ち、schema-set最大versionが2、1→2の連番、unknown versionなし、raw SQL bytes checksum一致を示す。delete前後の`projection.model_dump_json()`がbyte-for-byte一致すること。rebuildは全campaign Event read→pure rebuild→monotonic upsertを同じwrite lock critical sectionで行い、stale candidateが新しいsnapshotを上書きせず、barrier testで`through_sequence`が単調非減少であること。Projection test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`に置き、DB file、WAL sidecar、backupをmanifestやstatusへ出さない。

**実履歴のコミット境界**

```powershell
git add -- src/neontof/persistence/projection_store.py src/neontof/persistence/migrations/0002_projection_snapshots.sql tests/persistence/test_projection_store.py tests/persistence/test_migrations.py tests/test_repository_contracts.py
```

実履歴ではP1-01aのcommit、SQLite policy、`0002` schema-set、delete/rebuild/reverted-turn/stale-barrier focused commandがfailure `0`になった後、上記pathのtests、migration、implementationを一つのlogical GREEN commitへまとめた。

```text
feat: Eventから再生成できるProjection Storeを追加する
```

---

## P1-02: TranscriptとTelemetry Store（完了済み: `e5b7aa4`）

**実履歴で作成済み**

- `src/neontof/observability/__init__.py`
- `src/neontof/observability/records.py`
- `src/neontof/observability/sanitization.py`
- `src/neontof/persistence/observation_store.py`
- `src/neontof/persistence/migrations/0003_observation_stores.sql`
- `tests/observability/test_sanitization.py`
- `tests/persistence/test_observation_store.py`

**実履歴で変更済み**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`
- `tests/integration/test_failed_turn_observations.py`（既存skip testのModify）

P1-02のproduction manifest追加は`src/neontof/observability/__init__.py`、`src/neontof/observability/records.py`、`src/neontof/observability/sanitization.py`、`src/neontof/persistence/observation_store.py`の4つである。`ObservationStore`が`transcript_entries`と`telemetry_entries` tableおよび各recordを所有し、migration pathは`src/neontof/persistence/migrations/0003_observation_stores.sql`とする。このSQLはproduction `.py` manifest entryではない。`0003`は`transcript_entries`と`telemetry_entries`だけをadditiveに作り、down migrationを作らない。`0001`/`0002`へ追記しない。migration実行後のschema-setの最大適用versionは3で、1→3の連番、unknown versionなし、version/name/raw SQL bytes checksum一致をevidenceにする。

`0003_observation_stores.sql`は次の最小schemaを持つ。各tableの`append_sequence`はtable-localで、unique scopeはそれぞれ`(campaign_id, append_sequence)`である。`TranscriptRecord`と`TelemetryRecord`の全fieldを保持し、JSON化したdataは`data_json`、rolesは`roles_json`へ保存する。enum/CHECK、NOT NULL、BLOB型、entry ID制約はP1-02で実装・再検証済みで、P1-01aで先取りしていない。

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

**実履歴の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/observability tests/persistence/test_observation_store.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py -q
```

実履歴のfocused commandでは`0003_observation_stores.sql`のschema-set assertion、manifest追記漏れ、未許可path、purpose-specific allowlist、Event transaction外append、またはtimeout integrationのTranscript件数`0`に対する`1`期待を失敗理由として確認した。collection errorまたは0 testを成功根拠にはしない。

**完了済みの契約**

- `0003_observation_stores.sql`が`transcript_entries`と`telemetry_entries`だけをadditiveに作り、TranscriptRecord/TelemetryRecordの全field、entry_id、enum/CHECK、`data_json`/`roles_json`、各tableの`(campaign_id, append_sequence)`を持ち、schema-set最大versionが3、1→3の連番、unknown versionなし、raw SQL bytes checksum一致
- timeout後のEvent count `0`
- Transcriptに`player_input`、`error`、`tool_call`を用途別allowlistで保持し、raw provider body/error/causeを保持しない
- Telemetryに`timed_out`
- session costは`campaign_id`と`session_id`のscopeでrevert前後同値
- secret sentinel hit `0`、recursive sanitizerは最終防御、table-local sequence scopeは各`(campaign_id, append_sequence)`、Event append critical section内のObservationStore append `0`
- `tests/test_repository_contracts.py`のexact manifest/forbidden guardがexit `0`

**実履歴のコミット境界**

```powershell
git add -- src/neontof/observability/__init__.py src/neontof/observability/records.py src/neontof/observability/sanitization.py src/neontof/persistence/observation_store.py src/neontof/persistence/migrations/0003_observation_stores.sql tests/observability/test_sanitization.py tests/persistence/test_observation_store.py tests/persistence/test_migrations.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py
```

実履歴ではtests、P1-01bのcommit、`0003` schema-set、purpose-specific allowlist、tool_call、failed-turn retention、別transaction、table-local sequence、repository guardがfailure `0`になった後、上記pathのtests、migration、implementationを一つのlogical GREEN commitへまとめた。

```text
feat: TranscriptとTelemetryをEvent transaction外へ保存する
```

---

## P1-01c: scanner-hardening補正

### Goal

P1-02（commit `e5b7aa4`）までに着地した実装を前提に、現存する`tests/test_repository_contracts.py`のbroad connect positiveを、runtime/migrationのexact SQLite contractとP1-03以降のEventStore caller遷移へ補正する。P1-01a/P1-01b/P1-02のproduction path、migration、既存commitを再記述・再stageしない。

### Entry Conditions

- P1-01a（`eb284f9`）、P1-01b（`9ee2074`）、P1-02（`e5b7aa4`）が着地済みで、P1-02のfocused/full Gateとclean worktreeが確認できる。
- 補正開始時点の検査期待値はsame-connection reader `1`、application-level `EventStore.append()` caller `0`である。
- P1-00bはrepository guardの入口だけを提供し、source/protocol/connect/DML scannerのGreen証拠を提供しない。

### Phase 1 Gate

`tests/test_repository_contracts.py`の既存`_SqliteUsageVisitor` / `_sqlite_usage_violations`をModifyし、source候補`src/neontof/**/*.py`（import有無を問わず）とraw bytesの`src/neontof/persistence/migrations/*.sql`を走査する。`tests/**`はproduction source scanから除外する。runtimeの`neontof.persistence.sqlite_database.SqliteDatabase._open_connection`とmigrationの`neontof.persistence.migrations._open_backup_connection`の`sqlite3.connect`だけを各count `1`で許可し、`sqlite3.Connection`のtype annotation / `isinstance` reference、`Binary`、`complete_statement`、status constants、error classesのpure reference/callだけをpositiveとする。任意の`src/neontof/persistence/database.py`の`sqlite3.connect(':memory:')`、arbitrary persistence connect、no-import unknown wrapper、alias/import variant、constructorはrejectする。

caller-level `EventStore.append()` allowlistとstorage DML scanは別判定器とし、補正時点のcaller countは`0`とする。storage側は`src/neontof/persistence/event_store.py` / `neontof.persistence.event_store.EventStore.append.<locals>.operation`（lexical parent `EventStore.append`、unique nested operation）/ static `INSERT INTO events` / count `1`だけを許可する。P1-03 Persistence後はsame-connection reader `2`、P1-03 Lifecycle後は`TurnLifecycleCoordinator.execute`と`revert_latest`のcaller `2`、P1-05後は同じowner classの`append_bootstrap`を加えてcaller `3`へ遷移する。

### Stop Conditions

- P1-01a/P1-01b/P1-02のpathを再stageする必要が生じる。
- broad connect positive、caller count `0`、same-connection reader `1`、raw migration strict scan、またはexact tupleを維持できない。
- unknown receiver/alias/rebind/`getattr`、dynamic SQL、別connection、copied events、nested `_write`をfail-closedにできない。

### Create / Modify / Forbidden path

**Create**

- なし。

**Modify**

- `tests/test_repository_contracts.py`（既存visitor/violation testのみ。broad connect positiveの置換、DML/protocol/connect/source classificationの補正、caller allowlistとstorage DMLの分離）

**Forbidden**

- `src/neontof/**`
- `tests/persistence/**`
- `tests/integration/**`
- `docs/agent-guide/**`
- `AGENTS.md`
- `CLAUDE.md`
- `docs/PRODUCT_PLAN.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/adr/**`
- `git index`

### Test First / RED / Green

先に次のnamed testsを追加・Modifyし、P1-02直後の旧broad positive、未実装のexact connect count、caller count、DML/protocol/source classification、transaction parserのいずれかに結び付く非`0`のREDを得る。

- `test_sqlite_type_references_and_exact_runtime_migration_connects_are_allowed`
- `test_sqlite_scan_rejects_arbitrary_persistence_connect_and_constructor`
- `test_sqlite_source_scan_rejects_no_import_unknown_sqlite_wrapper`
- `test_sqlite_connect_exact_allowlist_rejects_duplicate_call_count`
- `test_eventstore_append_caller_allowlist_requires_exact_qualified_path_and_count`
- `test_eventstore_append_caller_allowlist_rejects_wrong_path_same_name_duplicate_and_other_owner`
- `test_eventstore_append_caller_allowlist_rejects_third_callsite`
- `test_events_dml_allowlist_requires_exact_storage_path_and_nested_operation`
- `test_events_dml_allowlist_rejects_duplicate_insert_and_other_owner`
- `test_only_six_transaction_sql_sites_are_allowed`
- `test_sqlite_scan_rejects_transaction_sql_with_semicolon_comment_trailing_token_end_savepoint_and_release`
- `test_projection_rebuild_has_one_same_connection_reader_before_claim`

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository_contracts.py -q
```

REDは旧`src/neontof/persistence/database.py` positiveがexact allowlistに入らないこと、duplicate connect count、wrong-path/duplicate/third/other-owner caller、別closureのevents DML、6箇所以外のtransaction SQL、末尾semicolon・末尾comment・semicolon後の第2 statement・comment以外のtrailing token・EOF不一致、`END`/`SAVEPOINT`/`RELEASE`を検出した非`0`である。raw migrationはstrict UTF-8/BOM reject、CRLF-LF/completeness、comments/strings/quoted identifiers/CTEをtokenizeするが、transaction callsite parserは余分なcommentを含めてwhitespace後のEOF以外をrejectする。

補正実装後の同じcommandがexit `0`となり、current baselineのsame-connection reader `1`、application append caller `0`、runtime/migration connect各count `1`、type reference positive、arbitrary connect negative、7 lexical `getattr` locations / 9 calls、DML、protocol、transaction、PRAGMA、cursor、backup、cross-module positive/sabotageが揃うことをGreen条件とする。P1-01cのGreen後だけP1-03をscanner Green前提で開始する。P1-03 Persistence / Lifecycle / P1-05の実装後は、遷移表のreader `2` / caller `2` / caller `3`を同じscanner契約で再検査する。

### Commit単位

```powershell
git add -- tests/test_repository_contracts.py
```

`tests/test_repository_contracts.py`だけを一つのscanner-hardening logical GREEN commitへまとめる。P1-01a/P1-01b/P1-02のproduction path、`0001`/`0002`/`0003`、各既存test、manifestをこのcommitへ混ぜず、P1-03 Persistenceのclaim reader追加、P1-03 Lifecycleの2 caller追加、P1-05のbootstrap caller追加はそれぞれの依存commitで行う。

---

## P1-03: Turn状態機械とLifecycle Coordinator

### Goal

- DB-wide opaque `request_key`、campaign-scoped canonical `TurnRequestId`、全identity照合、processing claim、cached response、crash recoveryを固定する。
- `TurnLifecycleCoordinator`を唯一のapplication-level Event append ownerとし、EventStoreは永続化ownerとしてだけ使う。Stateは直接変更せず、検証済みEventBatchのappendだけで変更する。
- `submit`、`resume`、`awaiting_player`、terminal、undoのEvent sequenceと、Event-derived `TurnStatus`を既存契約のまま固定する。
- candidate batchをappend前にcampaign全体へ適用して`project_turn_status()`と`rebuild_projection()`を実行し、non-committed effectsを拒否する。
- Transcript / TelemetryをEvent append transactionの外へ保持し、失敗Turnでも観測を失わない。
- Lifecycle laneの所有pathは`src/neontof/application/turn_models.py`（`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、結果union、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`）と`src/neontof/application/turn_lifecycle.py`（`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、coordinator）である。これらはLifecycle commitで一度だけstageし、P1-08は未着地symbolを再定義せずimportする。

### Non-goal

- raw `request_key` parser、HTTP body JSON parser、JSON/SSE serializationを作らない。
- Model request / response、Provider、Model call、Semantic Result、Narrative、Diceを扱わない。これらの観測・Provider境界・call countはP1-08へ移す。
- `EventStore.append()`の直接呼び出しをP1-08や`TurnEngine`へ公開しない。P1-03のapplication-level callerは`TurnLifecycleCoordinator.execute()`と`revert_latest()`の2件に限定し、P1-05で同じowner classへ追加するbootstrapはこのWPの対象外とする。
- `src/neontof/contracts/**`、`src/neontof/event_metadata.py`、既存のEvent Store実装、Phase 0 transport契約を変更しない。新しいgeneric repository、Provider、registry abstractionを作らない。

### Entry Conditions

- P1-00、P1-00b、P1-01a、P1-01b、P1-02の依存commitとfocused/full Gateが完了している。
- `0001`、`0002`、`0003`が適用済みで、EventStoreのcampaign readは検証済み`tuple[DomainEvent, ...]`を返す。`StoredEvent`はappend returnとEventStore内部だけに閉じる。
- C-01はAを採用済みで、通常TurnのModel call上限は1回、model由来clarification completionはPhase 1受入れ対象外である。
- 実装開始時のfocused commandは、P1-02のcommitとrepository guardのclean状態を確認してから実行する。remote CIのpendingはlocal entryを変更しない。

### Phase 1 Gate

- `request_key`はDB-wideで一意なopaque keyで、HTTPの`Idempotency-Key`として再送を同じrequestの二重処理なしに収束させる。canonical `TurnRequestId`は`(campaign_id, turn_request_id)`のidentity/context scopeでありidempotency keyではない。resumeは同じcanonical `TurnRequestId`でも新しい`request_key`を使う。
- claimは同一`_write` transaction / SQLite connectionでlookup、campaign processing row確認、Event-derived status/context validation、insertまでを行う。request key miss直後に別keyのprocessing rowがあれば`turn_already_processing`へ写像する。
- same-keyは全identityを完全照合し、conflictでcached body、identity値、SQLite messageを返さない。processing recordのresponseは`None`、completion recordのresponseは必須である。
- 通常のterminal pathでは`submit`は`PlayerInputAccepted -> TurnResumed -> Turn terminal`、`resume`は`TurnResumed -> Turn terminal`であり、effectsはTurn terminal直前だけに置く。resumeで二つ目の`PlayerInputAccepted`を作らない。pre-model ambiguityだけは既存`TurnStatus`の`awaiting_player`へ遷移し、`TurnAwaitingPlayer`をeffectsなしで最後に置く。これはterminalではなく、後続resumeを許可する状態である。`PreparedTurn.scenario_end`がある場合だけ、factoryが`TurnCommitted -> SessionEnded`を追加し、SessionEndedをsession terminalとして最後に置く。
- coordinatorはcandidate validation、append、rebuild、completeを一つのlifecycle boundaryで順序付け、全例外をsanitized codeへ変換する。Event appendとObservation appendをnested transactionにしない。
- recoveryはcampaign全体のvalidated Event列と既存turn-status parserの順序だけで分岐し、Provider、Model、Diceを再実行しない。undoは削除ではなく`TurnReverted`のappendである。

### Stop Conditions

- Event append以外でState / Canon / authoritative effectを変更する必要が生じた場合。
- candidate validationがappend前に`project_turn_status()`と`rebuild_projection()`を完了できない、またはnon-committed effectを拒否できない場合。
- `request_key`のDB-wide PK、campaign processing partial UNIQUE、canonical non-unique index、request kind/status/media/payload/response CHECKのいずれかを弱める必要が生じた場合。
- `sqlite3.IntegrityError`のraw message、constraint名、identity値、cached body、cause、contextを外へ出す必要が生じた場合。
- coordinatorがregistryまたはboundary lockを例外時に`finally`で解放できない、SQLite `_WRITE_LOCK`とboundary lockを同一objectにする、またはcoordinatorが`sqlite3`をimportする必要が生じた場合。
- P1-03でraw key parser/JSON/SSE/Model/Provider/Diceを扱う必要が生じた場合、またはP1-08へ移したmodel request/response/provider観測を戻す必要が生じた場合。
- 許可されたCreate/Modify path外、Phase 0契約、Product Plan、Roadmap、ADR、specを変更する必要が生じた場合。

### Heavy判定

P1-03は`0004`のデータ形式、公開Store API、transaction / concurrency境界、Event append ownership、recovery / undoを同時に固定するため、`architecture.md`の危険地帯（danger-zone）に触れるheavy WPである。探索期でもこのWPにはfull heavy gateを適用する。

### Create / Modify / Forbidden path

**Create**

- `src/neontof/application/__init__.py`
- `src/neontof/application/turn_models.py`
- `src/neontof/application/turn_lifecycle.py`
- `src/neontof/persistence/turn_request_store.py`
- `src/neontof/persistence/migrations/0004_turn_requests.sql`
- `tests/application/test_turn_lifecycle.py`
- `tests/persistence/test_turn_request_store.py`
- `tests/integration/test_turn_idempotency.py`

**Modify**

- `tests/persistence/test_migrations.py`
- `tests/test_repository_contracts.py`
- `tests/integration/test_failed_turn_observations.py`（既存skip testのModify）

**Forbidden**

- `src/neontof/contracts/**`
- `src/neontof/event_metadata.py`
- `src/neontof/persistence/event_store.py`
- `src/neontof/application/turn_engine.py`
- `src/neontof/model/**`
- `src/neontof/web/**`
- `client/**`
- `tests/contracts/**`
- `tests/model/**`
- `tests/web/**`
- `tests/integration/test_complete_fake_turn.py`
- `tests/integration/test_model_failure_atomicity.py`
- `docs/PRODUCT_PLAN.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/adr/**`
- `docs/specs/**`
- `AGENTS.md`
- `CLAUDE.md`

禁止pathの変更が必要になった場合は実装せずStop Conditionとして報告する。

P1-03のproduction manifest追加は`src/neontof/application/__init__.py`、`src/neontof/application/turn_models.py`、`src/neontof/application/turn_lifecycle.py`、`src/neontof/persistence/turn_request_store.py`の4つである。`src/neontof/persistence/migrations/0004_turn_requests.sql`はmanifestの`.py` entryではない。Persistence commitで`turn_models.py`のpersistence固有symbolと`turn_request_store.py`、Lifecycle commitで同じ`turn_models.py`のLifecycle symbolと`application/__init__.py` / `turn_lifecycle.py`を順に追加し、P1-03の2 callsite allowlistを維持する。`append_bootstrap`、`BootstrapApplicationService`、bootstrap test/authoring pathはP1-05までmanifest、Modify、staging、commitへ追加しない。

symbolの所有と依存方向は固定する。`src/neontof/application/turn_models.py`のPersistence laneは`TurnRequestIdentity`、pre-claim `TurnRequestIntent`、`ProcessingTurnRequestRecord`、`FinalTurnRequestRecord`、`CompletedTurnRequestRecord`、`TurnRequestRecord`、`NewClaim`、`ExistingProcessingClaim`、`ExistingFinalClaim`、`ClaimResult`、`RecoveryEventMetadata`、`RecoveryReason`、`RecoverySelector`、`CachedTurnResponse`、`StoreError`を所有する。同じfileのLifecycle laneは型/aliasだけを所有し、`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、`TurnEventBatchFactory`、`TurnEventIdSequence`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnExecutionResult`、`CoordinatorResult`、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`、`derive_revert_event_id`を所有する。`src/neontof/application/turn_lifecycle.py`は`ActiveTurnToken`、`OwnedActiveTurn`、`ExistingActiveTurn`、`ActiveTurnAcquisition`、`ActiveTurnRegistry`、`TurnLifecycleCoordinator`と、`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、`build_started_events`、`build_resumed_event`、`build_awaiting_event`、`build_committed_event`、`build_aborted_event`、`build_revert_event`、`build_submit_events`、`build_resume_events`、`build_crash_recovery_batch`、`matches_current_turn_identity`、`validate_and_materialize_candidate`、`select_latest_committed_turn`、`select_response_payload`を実装する。`recover_processing`は`turn_lifecycle.py`のcoordinator methodとして`RecoveryPlan`を返すだけであり、`EventStore.append()`または`TurnRequestStore.complete()`の追加callerにならない。`turn_lifecycle.py`は`turn_models.py`の型、neutralな`EventBatch` / `TurnEventMetadata`、P1-01b/P1-02のtyped Storeを一方向にimportし、`turn_models.py`は`turn_lifecycle.py`からimportしない。
Lifecycle laneの追加bundleは`src/neontof/application/turn_models.py`が所有する型/alias `RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`と、`src/neontof/application/turn_lifecycle.py`だけが実装する具体関数`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`に分ける。`RecoveryEventIdSource`は一回の呼出しで6 roleのreservationを返し、内部のdeterministic derivationだけがroleを引数に取る。

### 0004 schema

`TurnRequestStore`が`turn_requests` tableとcoordination recordを所有し、migration pathは`src/neontof/persistence/migrations/0004_turn_requests.sql`とする。`0004`は`turn_requests` tableとこのtableのindexだけをadditiveに作り、`0001` / `0002` / `0003`へ追記せず、down migrationを作らない。

```sql
CREATE TABLE turn_requests (
    request_key BLOB NOT NULL PRIMARY KEY CHECK (
        typeof(request_key) = 'blob'
        AND length(request_key) BETWEEN 1 AND 256
    ),
    request_kind TEXT NOT NULL CHECK (
        typeof(request_kind) = 'text'
        AND request_kind IN ('submit', 'resume')
    ),
    requested_media_type TEXT NOT NULL CHECK (
        typeof(requested_media_type) = 'text'
        AND requested_media_type IN ('application/json', 'text/event-stream')
    ),
    turn_request_id TEXT NOT NULL CHECK (
        typeof(turn_request_id) = 'text'
        AND length(turn_request_id) > 0
    ),
    campaign_id TEXT NOT NULL CHECK (
        typeof(campaign_id) = 'text'
        AND length(campaign_id) > 0
    ),
    session_id TEXT NOT NULL CHECK (
        typeof(session_id) = 'text'
        AND length(session_id) > 0
    ),
    scene_id TEXT NOT NULL CHECK (
        typeof(scene_id) = 'text'
        AND length(scene_id) > 0
    ),
    turn_id TEXT NOT NULL CHECK (
        typeof(turn_id) = 'text'
        AND length(turn_id) > 0
    ),
    root_turn_request_id TEXT NOT NULL CHECK (
        typeof(root_turn_request_id) = 'text'
        AND length(root_turn_request_id) > 0
    ),
    input_digest TEXT NOT NULL CHECK (
        typeof(input_digest) = 'text'
        AND length(input_digest) > 0
    ),
    base_event_sequence INTEGER NOT NULL CHECK (
        typeof(base_event_sequence) = 'integer'
        AND base_event_sequence >= 0
    ),
    status TEXT NOT NULL CHECK (
        typeof(status) = 'text'
        AND status IN ('processing', 'awaiting_player', 'committed', 'aborted')
    ),
    recovery_reason TEXT NULL CHECK (
        recovery_reason IS NULL
        OR (
            typeof(recovery_reason) = 'text'
            AND recovery_reason IN (
            'claim_before_first_event',
            'after_player_input_accepted',
            'after_turn_resumed',
            'after_turn_awaiting_player',
            'after_terminal'
            )
        )
    ),
    recovery_selector TEXT NULL CHECK (
        recovery_selector IS NULL
        OR (
            typeof(recovery_selector) = 'text'
            AND recovery_selector IN (
                'no_lifecycle_events',
                'accepted_without_terminal',
                'resumed_without_terminal',
                'awaiting_player',
                'terminal'
            )
        )
    ),
    accepted_event_id TEXT NULL CHECK (
        accepted_event_id IS NULL
        OR (
            typeof(accepted_event_id) = 'text'
            AND length(accepted_event_id) > 0
        )
    ),
    resumed_event_id TEXT NULL CHECK (
        resumed_event_id IS NULL
        OR (
            typeof(resumed_event_id) = 'text'
            AND length(resumed_event_id) > 0
        )
    ),
    awaiting_player_event_id TEXT NULL CHECK (
        awaiting_player_event_id IS NULL
        OR (
            typeof(awaiting_player_event_id) = 'text'
            AND length(awaiting_player_event_id) > 0
        )
    ),
    committed_event_id TEXT NULL CHECK (
        committed_event_id IS NULL
        OR (
            typeof(committed_event_id) = 'text'
            AND length(committed_event_id) > 0
        )
    ),
    aborted_event_id TEXT NULL CHECK (
        aborted_event_id IS NULL
        OR (
            typeof(aborted_event_id) = 'text'
            AND length(aborted_event_id) > 0
        )
    ),
    recovery_aborted_event_id TEXT NULL CHECK (
        recovery_aborted_event_id IS NULL
        OR (
            typeof(recovery_aborted_event_id) = 'text'
            AND length(recovery_aborted_event_id) > 0
        )
    ),
    occurred_at TEXT NULL CHECK (
        occurred_at IS NULL
        OR (
            typeof(occurred_at) = 'text'
            AND length(occurred_at) > 0
        )
    ),
    initial_recovery_payload BLOB NOT NULL CHECK (
        typeof(initial_recovery_payload) = 'blob'
        AND length(initial_recovery_payload) > 0
    ),
    staged_recovery_payload BLOB NULL CHECK (
        staged_recovery_payload IS NULL
        OR (
            typeof(staged_recovery_payload) = 'blob'
            AND length(staged_recovery_payload) > 0
        )
    ),
    recovery_payload_version INTEGER NOT NULL CHECK (
        typeof(recovery_payload_version) = 'integer'
        AND (
        (
            recovery_payload_version = 1
            AND staged_recovery_payload IS NULL
        )
        OR (
            recovery_payload_version = 2
            AND staged_recovery_payload IS NOT NULL
        )
        )
    ),
    response_status_code INTEGER NULL CHECK (
        response_status_code IS NULL
        OR (
            typeof(response_status_code) = 'integer'
            AND response_status_code = 200
        )
    ),
    response_media_type TEXT NULL CHECK (
        response_media_type IS NULL
        OR (
            typeof(response_media_type) = 'text'
            AND response_media_type = requested_media_type
        )
    ),
    response_body BLOB NULL CHECK (
        response_body IS NULL
        OR (
            typeof(response_body) = 'blob'
            AND length(response_body) > 0
        )
    ),
    CHECK (
        (
            recovery_reason IS NULL
            AND recovery_selector IS NULL
            AND accepted_event_id IS NULL
            AND resumed_event_id IS NULL
            AND awaiting_player_event_id IS NULL
            AND committed_event_id IS NULL
            AND aborted_event_id IS NULL
            AND recovery_aborted_event_id IS NULL
            AND occurred_at IS NULL
        )
        OR (
            recovery_reason IS NOT NULL
            AND recovery_selector IS NOT NULL
            AND occurred_at IS NOT NULL
        )
    ),
    CHECK (
        (
            status = 'processing'
            AND response_status_code IS NULL
            AND response_media_type IS NULL
            AND response_body IS NULL
        )
        OR (
            status IN ('awaiting_player', 'committed', 'aborted')
            AND typeof(response_status_code) = 'integer'
            AND response_status_code = 200
            AND typeof(response_media_type) = 'text'
            AND response_media_type = requested_media_type
            AND typeof(response_body) = 'blob'
            AND length(response_body) > 0
        )
    )
);

CREATE UNIQUE INDEX uq_turn_requests_campaign_processing
    ON turn_requests (campaign_id)
    WHERE status = 'processing';

CREATE INDEX idx_turn_requests_campaign_turn_request_id
    ON turn_requests (campaign_id, turn_request_id);
```

`request_key`はdatabase-wideのBLOB PRIMARY KEYで、1..256 bytesだけを受け付ける。campaign processingのpartial UNIQUEは同一campaignに同時に一つの`processing` recordだけを許可する。`idx_turn_requests_campaign_turn_request_id`はcanonical request用の非unique indexであり、DB-wide uniqueにしない。`request_kind`、`requested_media_type`、受理したcanonical ID（`turn_request_id`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`root_turn_request_id`、`input_digest`）、`base_event_sequence`、`status`、`recovery_selector`、`recovery_reason`、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`、`occurred_at`、`recovery_payload_version`、initial/staged recovery payload、response code/media/bodyの型と範囲をSQL CHECKで固定する。`aborted_event_id`はnormal `TurnAborted`専用、`recovery_aborted_event_id`はrecovery abort専用であり、同じactual Eventの別名にしない。`recovery_payload_version`は`staged_recovery_payload IS NULL`なら1、non-NULLなら2に限る。初期recordではimmutableな`request_kind`、version 1、initial payloadが確定し、lifecycle recovery metadata（`recovery_reason`、`recovery_selector`、6つのEvent ID、`occurred_at`）は全てNULLで、`stage_recovery_metadata()`の一度だけのCASで確定する。保存IDは候補・再利用用で、未使用予約IDがactual Event Logに不在でもよい。Event Logの`owned_suffix`に存在するlifecycle Eventは同一roleの非NULL予約IDとtype/context/canonical requestまで一致するsubsetでなければならず、normal terminal actualとrecovery abort actualの同時存在、role違いのID再利用、非NULL予約IDとのtype/context/canonical request mismatch、予約外actual Eventはfull validationで`recovery_identity_mismatch`へfail-closedにする。`processing`ではresponse三列が全NULL、final statusではstatus codeが200、mediaが`requested_media_type`と一致し、bodyがnon-empty BLOBである。`complete()`はrecovery metadata、identity、payload、`recovery_payload_version`を更新引数にも`SET`にも持たず、version 1/2のどちらでもそれらを不変にしたままresponse/statusだけをCAS更新する。migration後のschema-setは最大version `4`、`1 -> 4`の連番、unknown versionなし、raw SQL bytes SHA-256 checksum一致である。

### 公開型とシグネチャ

```python
import hashlib

from collections.abc import Callable, Sequence
from threading import Lock
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBytes, StrictInt, StrictStr, model_validator
from neontof.event_metadata import OccurredAt

RequestKind = Literal["submit", "resume"]
RequestCompletionStatus = Literal["awaiting_player", "committed", "aborted"]
RequestedMediaType = Literal["application/json", "text/event-stream"]
RecoveryReason = Literal[
    "claim_before_first_event",
    "after_player_input_accepted",
    "after_turn_resumed",
    "after_turn_awaiting_player",
    "after_terminal",
]
RecoverySelector = Literal[
    "no_lifecycle_events",
    "accepted_without_terminal",
    "resumed_without_terminal",
    "awaiting_player",
    "terminal",
]
StoreErrorCode = Literal[
    "request_key_conflict",
    "turn_already_processing",
    "request_not_found",
    "request_not_processing",
    "stage_conflict",
    "response_conflict",
    "invalid_record",
    "store_integrity_error",
    "invalid_response",
    "turn_not_found",
    "turn_not_in_session",
    "undo_conflict",
    "recovery_identity_mismatch",
]
OpaqueRequestKey = Annotated[
    StrictBytes,
    Field(min_length=1, max_length=256),
]
RequestKey = OpaqueRequestKey
NonEmptyBytes = Annotated[StrictBytes, Field(min_length=1)]

class StoreError(ValueError):
    code: StoreErrorCode

    def __init__(self, code: StoreErrorCode) -> None: ...

class CachedTurnResponse(ContractModel):
    status_code: Literal[200]
    media_type: RequestedMediaType
    body: NonEmptyBytes

class TurnRequestIdentity(ContractModel):
    request_key: OpaqueRequestKey
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    base_event_sequence: Annotated[StrictInt, Field(ge=0)]
    recovery_payload_version: Literal[1, 2]
    recovery_reason: RecoveryReason | None
    recovery_selector: RecoverySelector | None
    accepted_event_id: EventId | None
    resumed_event_id: EventId | None
    awaiting_player_event_id: EventId | None
    committed_event_id: EventId | None
    aborted_event_id: EventId | None
    recovery_aborted_event_id: EventId | None
    occurred_at: OccurredAt | None
    initial_recovery_payload: NonEmptyBytes
    staged_recovery_payload: NonEmptyBytes | None

class TurnRequestIntent(ContractModel):
    request_key: OpaqueRequestKey
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    initial_recovery_payload: NonEmptyBytes

class ProcessingTurnRequestRecord(TurnRequestIdentity):
    status: Literal["processing"]
    response: None

class FinalTurnRequestRecord(TurnRequestIdentity):
    status: RequestCompletionStatus
    response: CachedTurnResponse

CompletedTurnRequestRecord = FinalTurnRequestRecord

TurnRequestRecord = Annotated[
    ProcessingTurnRequestRecord | FinalTurnRequestRecord,
    Field(discriminator="status"),
]

class NewClaim(ContractModel):
    type: Literal["new"]
    record: ProcessingTurnRequestRecord

class ExistingProcessingClaim(ContractModel):
    type: Literal["existing_processing"]
    record: ProcessingTurnRequestRecord

class ExistingFinalClaim(ContractModel):
    type: Literal["existing_final"]
    record: FinalTurnRequestRecord

ClaimResult = Annotated[
    NewClaim | ExistingProcessingClaim | ExistingFinalClaim,
    Field(discriminator="type"),
]

class RecoveryEventMetadata(ContractModel):
    request_kind: RequestKind
    recovery_payload_version: Literal[1, 2]
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    turn_request_id: TurnRequestId
    root_turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    recovery_reason: RecoveryReason
    recovery_selector: RecoverySelector
    occurred_at: OccurredAt
    accepted_event_id: EventId | None
    resumed_event_id: EventId | None
    awaiting_player_event_id: EventId | None
    committed_event_id: EventId | None
    aborted_event_id: EventId | None
    recovery_aborted_event_id: EventId | None
    event_ids: tuple[EventId, ...]  # 6 role別fieldのうち非NULLの個別Event IDだけをlifecycle順にまとめたメモリ上の派生値。SQLには保持しない。

RecoveryEventRole = Literal[
    "accepted",
    "resumed",
    "awaiting_player",
    "committed",
    "aborted",
    "recovery_aborted",
]

class RecoveryEventIdReservation(ContractModel):
    accepted_event_id: EventId
    resumed_event_id: EventId
    awaiting_player_event_id: EventId
    committed_event_id: EventId
    aborted_event_id: EventId
    recovery_aborted_event_id: EventId

class RecoveryMetadataInputs(ContractModel):
    occurred_at: OccurredAt
    reservation: RecoveryEventIdReservation

RecoveryEventIdDeriver = Callable[[TurnRequestIdentity, RecoveryEventRole], EventId]
RecoveryEventIdSource = Callable[[TurnRequestIdentity], RecoveryEventIdReservation]

def derive_recovery_event_id(
    identity: TurnRequestIdentity,
    role: RecoveryEventRole,
) -> EventId: ...

def reserve_recovery_event_ids(
    identity: TurnRequestIdentity,
) -> RecoveryEventIdReservation: ...

`src/neontof/application/turn_lifecycle.py::reserve_recovery_event_ids(identity: TurnRequestIdentity) -> RecoveryEventIdReservation`がP1-03の唯一のconcrete `RecoveryEventIdSource`である。内部では`derive_recovery_event_id(identity, role)`を6 roleごとに使い、request identity/keyとroleからdeterministicなIDを作る。`EventStore`、SQLite connection、clockをcaptureせず、coordinatorからは一回のsource callでbundleとして受け取る。

class PreparedEffect(ContractModel):
    """Event ID と occurred_at をまだ持たない、current identity由来の候補。"""

    type: StrictStr
    event_version: Literal[1]
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility
    payload_json: RawEventPayloadJson

# producerはTurnRequestIdentityを受け、上記envelopeをcurrent identityから構成する。
# producerが過去Turnまたはglobal contextからcampaign/session/scene/turnを推測してはならない。


class PreparedTurn(ContractModel):
    effect_candidates: tuple[PreparedEffect, ...]
    terminal_status: Literal["awaiting_player", "committed", "aborted"]
    scenario_end: Literal["success", "failure"] | None
    abort_reason: Literal["failed", "cancelled", "table_correction"] | None
    staged_recovery_payload: NonEmptyBytes | None

    @model_validator(mode="after")
    def require_staged_response_seed_for_terminal(self) -> Self:
        if self.terminal_status in ("committed", "aborted") and self.staged_recovery_payload is None:
            raise ValueError("terminal PreparedTurn requires a staged recovery payload")
        return self

`PreparedTurn`のvalidatorはnormal `committed` / normal `aborted`をv2 staged outer payloadなしで返すことを拒否する。provider、semantic validation、candidate validationの失敗をnormal `aborted`へ写像するproducerは、canonical failure `StagedResponseSeed`からouter v2 bytesを作ってからこの型を返し、recovery abort（保存済みinitial payloadを使う別経路）と混同しない。

RecoveryPlanState = Literal["normal_terminal", "awaiting_player", "recovery_abort"]

`base_event_sequence`が当該requestのowned Event境界を固定する。全sequenceがcontiguousなvalidated Event Logから得た`campaign_events`に対し、`prefix = {event | event.sequence <= record.base_event_sequence}`、`owned_suffix = {event | event.sequence > record.base_event_sequence}`とする。prefixはNewClaim以前の履歴、owned_suffixは当該requestのowned lifecycle Event候補である。full tupleはcandidate validation / projection rebuildへ渡してよいが、owned ID・state・payloadは全履歴を直接使わず、prefixとowned_suffixを分離して判定する。未appendのauthorized candidateはowned_suffixの直後に仮想的に加えた候補列としてだけ検証し、actual membershipには数えない。
class RecoveryPlan(ContractModel):
    record: ProcessingTurnRequestRecord
    campaign_events: tuple[DomainEvent, ...]
    prefix_events: tuple[DomainEvent, ...]
    owned_suffix: tuple[DomainEvent, ...]
    state: RecoveryPlanState
    recovery_selector: RecoverySelector  # metadata CAS時点のimmutableなorigin selector
    candidate_batch: EventBatch | None
    accepted_event_id: EventId | None
    resumed_event_id: EventId | None
    awaiting_player_event_id: EventId | None
    committed_event_id: EventId | None
    aborted_event_id: EventId | None
    recovery_aborted_event_id: EventId | None

`RecoveryPlan`は`record`、full validated `campaign_events`、sequence境界そのものの`prefix_events` / `owned_suffix`、CAS時点のimmutableな`recovery_selector`、現在の`state`、optionalな`candidate_batch`、6個のrole別予約IDだけを公開する。`prefix_events`と`owned_suffix`は`record.base_event_sequence`から導出し、recovery decisionではさらに`matches_current_turn_identity()`でcurrent identityに一致する`current_prefix_events` / `current_owned_suffix_events`を一時的に導出する。以前の完了turnのEventがprefixにあってもcurrent matchでなければ判定へ入れず、payloadの選択は`select_response_payload()`だけに委ねる。`RecoveryPlan`へpayload選択booleanは置かない。

TurnEventBatchFactory = Callable[
    [TurnRequestIdentity, PreparedTurn, tuple[DomainEvent, ...], OccurredAt, Sequence[EventId]],
    tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch],
]
TurnEventIdSequence = Callable[[TurnRequestIdentity, PreparedTurn], Sequence[EventId]]

class CompletedTurnResult(ContractModel):
    type: Literal["completed"]
    request_key: OpaqueRequestKey
    turn_id: TurnId
    turn_request_id: TurnRequestId
    status: TurnStatus
    response: CachedTurnResponse
    appended_events: tuple[StoredEvent, ...]

class ExistingFinalTurnResult(ContractModel):
    type: Literal["existing_final"]
    request_key: OpaqueRequestKey
    turn_id: TurnId
    turn_request_id: TurnRequestId
    status: TurnStatus
    response: CachedTurnResponse
    appended_events: tuple[StoredEvent, ...]

class ProcessingTurnResult(ContractModel):
    type: Literal["processing"]
    request_key: OpaqueRequestKey
    turn_id: TurnId
    turn_request_id: TurnRequestId
    status: Literal["processing"]
    http_status_code: Literal[202]
    response: None

TurnExecutionResult = Annotated[
    CompletedTurnResult | ExistingFinalTurnResult | ProcessingTurnResult,
    Field(discriminator="type"),
]
CoordinatorResult = Annotated[
    CompletedTurnResult | ExistingFinalTurnResult | ProcessingTurnResult,
    Field(discriminator="type"),
]

class RevertedTurnResult(ContractModel):
    target_turn_id: TurnId
    revert_event_id: EventId
    response: CachedTurnResponse

class UndoBlockedResult(ContractModel):
    type: Literal["blocked"]
    http_status_code: Literal[409]
    code: Literal["turn_already_processing"]
    response: None

UndoResult = RevertedTurnResult | UndoBlockedResult

class UndoCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    request_key: OpaqueRequestKey
    occurred_at: OccurredAt

TurnPreparation = Callable[[TurnRequestIdentity, tuple[DomainEvent, ...]], PreparedTurn]
ResponseRebuilder = Callable[[ProcessingTurnRequestRecord, tuple[DomainEvent, ...], TurnStatus, StrictBytes], CachedTurnResponse]
UndoResponseRebuilder = Callable[[UndoCommand, tuple[DomainEvent, ...], TurnStatus, TurnId, EventId], CachedTurnResponse]
RecoveryMetadataFactory = Callable[
    [ProcessingTurnRequestRecord, tuple[DomainEvent, ...], RecoveryMetadataInputs],
    RecoveryEventMetadata,
]

def build_recovery_metadata(
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
    inputs: RecoveryMetadataInputs,
) -> RecoveryEventMetadata: ...

ActiveTurnToken = Annotated[StrictBytes, Field(min_length=1)]

class OwnedActiveTurn(ContractModel):
    type: Literal["owned"]
    intent: TurnRequestIntent
    token: ActiveTurnToken

class ExistingActiveTurn(ContractModel):
    type: Literal["existing_active"]
    intent: TurnRequestIntent
    token: ActiveTurnToken

ActiveTurnAcquisition = Annotated[
    OwnedActiveTurn | ExistingActiveTurn,
    Field(discriminator="type"),
]

class ActiveTurnRegistry:
    def __init__(self) -> None: ...
    def try_acquire(self, *, intent: TurnRequestIntent) -> ActiveTurnAcquisition: ...
    def release(self, *, token: ActiveTurnToken) -> None: ...

class TurnRequestStore:
    def __init__(self, database: SqliteDatabase, event_store: EventStore) -> None: ...
    def claim(self, *, intent: TurnRequestIntent) -> ClaimResult: ...
    def stage_recovery_metadata(
        self,
        *,
        request_key: RequestKey,
        metadata: RecoveryEventMetadata,
    ) -> ProcessingTurnRequestRecord: ...
    def stage(
        self,
        *,
        request_key: OpaqueRequestKey,
        expected_version: Literal[1],
        staged_recovery_payload: NonEmptyBytes,
    ) -> ProcessingTurnRequestRecord: ...
    def read(self, *, request_key: RequestKey) -> TurnRequestRecord | None: ...
    def read_processing(self, *, campaign_id: CampaignId) -> ProcessingTurnRequestRecord | None: ...
    def complete(
        self,
        *,
        request_key: OpaqueRequestKey,
        expected_version: Literal[1, 2],
        status: RequestCompletionStatus,
        response: CachedTurnResponse,
    ) -> FinalTurnRequestRecord: ...

def build_started_events(metadata: TurnEventMetadata, input_digest: LowercaseSha256) -> EventBatch: ...
def build_resumed_event(metadata: TurnEventMetadata) -> EventBatch: ...
def build_awaiting_event(metadata: TurnEventMetadata) -> EventBatch: ...
def build_committed_event(metadata: TurnEventMetadata) -> EventBatch: ...
def build_aborted_event(metadata: TurnEventMetadata, reason: Literal["failed", "cancelled", "table_correction"]) -> EventBatch: ...
def build_revert_event(metadata: RevertEventMetadata, payload: TurnRevertedPayload) -> EventBatch: ...
def build_submit_events(started: EventBatch, prepared: PreparedTurn) -> EventBatch: ...
def build_resume_events(resumed: EventBatch, prepared: PreparedTurn) -> EventBatch: ...
def build_crash_recovery_batch(record: ProcessingTurnRequestRecord, campaign_events: Sequence[DomainEvent]) -> EventBatch: ...
def matches_current_turn_identity(
    event: DomainEvent,
    *,
    record: ProcessingTurnRequestRecord,
) -> bool: ...
def validate_and_materialize_candidate(existing_events: tuple[DomainEvent, ...], candidate_batch: EventBatch) -> tuple[DomainEvent, ...]: ...
def select_latest_committed_turn(campaign_events: Sequence[DomainEvent]) -> TurnCommittedEvent: ...
def select_response_payload(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> StrictBytes: ...
def derive_revert_event_id(*, campaign_id: CampaignId, request_key: OpaqueRequestKey) -> EventId: ...

class TurnLifecycleCoordinator:
    def __init__(
        self,
        *,
        event_store: EventStore,
        request_store: TurnRequestStore,
        observation_store: ObservationStore,
        active_turn_registry: ActiveTurnRegistry,
        response_rebuilder: ResponseRebuilder,
        undo_response_rebuilder: UndoResponseRebuilder,
        turn_event_factory: TurnEventBatchFactory,
        event_id_sequence: TurnEventIdSequence,
        utc_occurred_at: Callable[[], OccurredAt],
        recovery_event_id_source: RecoveryEventIdSource,
        recovery_metadata_factory: RecoveryMetadataFactory,
        event_boundary_lock: Lock,
    ) -> None: ...

    def execute(
        self,
        *,
        intent: TurnRequestIntent,
        prepare: TurnPreparation,
    ) -> CoordinatorResult: ...

    def recover_processing(
        self,
        *,
        record: ProcessingTurnRequestRecord,
        campaign_events: tuple[DomainEvent, ...],
    ) -> RecoveryPlan: ...

    def revert_latest(
        self,
        *,
        command: UndoCommand,
    ) -> UndoResult: ...
```

`matches_current_turn_identity(event: DomainEvent, *, record: ProcessingTurnRequestRecord) -> bool`は既存`DomainEvent` unionの実在fieldだけを使うrole-aware matcherである。全role共通で、Event envelopeの`campaign_id`、`session_id`、`scene_id`、`turn_id`をrecordの同名identityと照合する。`PlayerInputAccepted`、`TurnAwaitingPlayer`、`TurnResumed`、`TurnCommitted`、`TurnAborted`では各payload自身のcanonical `turn_request_id`だけをrecordの`turn_request_id`と照合する。`PlayerInputAccepted`のpayload `input_digest`は、current submitのaccepted anchorである場合に限りsubmit recordの`input_digest`と照合する。resumeのprefixにあるaccepted anchorは元のaccepted requestのdigestが既に検証済みであり、resume requestの新しい`input_digest`をそのprefix Eventや`TurnResumed` / `TurnAwaitingPlayer` / terminal payloadへ比較しない。resumeのowned suffixに新しい`PlayerInputAccepted`を置くことは許可しない。

`root_turn_request_id`は`DomainEventBase`にも各DomainEvent payloadにも存在しないため、matcherはEvent fieldとして比較しない。recordのrootはrecord identityに保存されたcurrent canonical turnのrootとして扱う。submitではrecord作成時に`root_turn_request_id == turn_request_id`であること、accepted anchorのpayload `turn_request_id`がrecordのcanonical `turn_request_id`と一致することをclaim時のimmutable identity validationで確認する。resumeではprefixのcurrent accepted / awaiting anchorのenvelopeとpayload `turn_request_id`がrecordのcampaign/session/scene/turnとcanonical IDに一致し、recordのrootがそのcanonical turnのrecord-level lineageと一致することをclaim時に検証する。Event側へrootを要求せず、accepted anchorにrootを推測して補うこともしない。accepted anchorが無い、rootとcanonicalのrecord-level関係が壊れている、または別contextのanchorしかない場合は`recovery_identity_mismatch`とする。`DiceRolled`、`ResourceChanged`、`CharacterMoved`、`ClockAdvanced`、`FactAsserted`、`FactSuperseded`などのeffect / Fact roleはcurrent turn envelope/contextとrole-aware reservationまたはauthorized candidateだけで扱い、`input_digest`や存在しないroot Event fieldを要求しない。過去の別turn、同じcampaignの別session/scene、同じcanonical IDでも別contextのEventはcurrent-turn matchではない。

`select_response_payload(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> StrictBytes`はfull validated tupleを受け取るが、まず`prefix = {event | event.sequence <= record.base_event_sequence}`と`owned_suffix = {event | event.sequence > record.base_event_sequence}`へ分割し、さらに`current_prefix_events = {event in prefix | matches_current_turn_identity(event, record=record)}`、`current_owned_suffix_events = {event in owned_suffix | matches_current_turn_identity(event, record=record)}`を導出する。origin `recovery_selector`とorigin statusはcurrent identityに一致するprefixから、current requestのrole/type/context/canonical request、terminal membership、payload選択はcurrent identityに一致するowned suffix（または今回のauthorized candidate）から導く。prefixにある以前のTurnや同じcanonical turnでもidentity tupleが異なる`PlayerInputAccepted` / `TurnAwaitingPlayer`をcurrent requestのowned Eventとして再利用しない。P1-03のこのselectorが行うのはEventのcurrent owned membership、DBの`recovery_payload_version`、initial/stagedのNULL stateだけの判定であり、DBに保存されたstaged列の値を常にopaqueなouter bytesとしてそのまま返すことである。normal `committed` / normal `aborted` actualではversion 2 outer bytesだけ、recovery-aborted actualでは保存済みversion 1のinitial outer bytes、awaiting actualではversion 2 outer bytesを優先し、無い場合だけversion 1のinitial outer bytesを返し、typed presentation defaultはP1-08のstrict decode後だけに適用し、P1-03 selectorはdefaultを選ばない。version 1 / initialのみのnormal terminal、staged outer欠落はP1-03 selectorが内容をdecodeせず`recovery_identity_mismatch`へ写像し、outer/innerのdiscriminator、payload内version、identity、media、strict UTF-8、secretの検証はP1-03 selectorの責務ではなく、返されたouter bytesを受けるP1-08の`ResponseDocumentBuilder` / `ResponseRebuilder`だけが行い、必要なstrict decode/validation failureをsanitized `recovery_identity_mismatch`へ写像する。この関数だけがopaque payload bytesを選ぶ唯一のauthorityであり、`RecoveryPlan`からpayload選択booleanを参照しない。

`TurnRequestRecord`は`status`をdiscriminatorにしたunionであり、`ProcessingTurnRequestRecord`は`response=None`、`FinalTurnRequestRecord`（互換名`CompletedTurnRequestRecord`）は`RequestCompletionStatus`と必須`response`だけを表す。両recordはSQLと同じ列名の`recovery_payload_version`、`request_kind`、`recovery_reason`、`recovery_selector`、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`、`occurred_at`のrecovery metadataを保持する。`aborted_event_id`はnormal `TurnAborted`専用、`recovery_aborted_event_id`はrecovery abort専用で、同じactual Eventの別名にしない。初期processing recordではimmutableな`request_kind`とversion 1、`initial_recovery_payload`が確定し、lifecycle recovery metadata（`recovery_reason`、`recovery_selector`、6つのEvent ID、`occurred_at`）は全てnullableである。metadata CAS後は`RecoveryEventMetadata`の非nullableな`request_kind` / version / `recovery_reason` / `recovery_selector` / `occurred_at`と、selectorで不要なものをNULLにできる6個のEvent IDのnullable状態をそのまま保持する。予約されたIDだけではterminalを確定せず、Event Logのcurrent identity一致の`owned_suffix` membershipがactual authority（prefixは以前の履歴として除外）である。`ClaimResult`も`type`をdiscriminatorにした三分岐で、`NewClaim`は新規processing record、`ExistingProcessingClaim`は既存processing record、`ExistingFinalClaim`は既存final recordだけを表す。`CachedTurnResponse`はstatus code `200`、requestで指定したmedia type、non-emptyなstrict UTF-8 body bytesを保持する。processing recordのresponseは常に`None`で、final recordのresponseは必須である。`complete()`はprocessing statusを受け付けず、同じ`expected_version`に対するcompare-and-setでresponse/statusだけを確定する。`request_key`はparseやcampaign prefixを持たない1..256 bytesのDB-wide opaque keyで、`turn_request_id`は`(campaign_id, turn_request_id)`のcampaign scopeで扱う。pre-claimの`TurnRequestIntent`はcaller supplied `base_event_sequence`と`staged_recovery_payload`を持たず、`base_event_sequence`はmissした`NewClaim`のfull campaign readにある`COALESCE(MAX(sequence), 0)`から`TurnRequestIdentity`へ一度だけ導出する。existing claimでは保存済みbaseを現在MAXと比較しない。`initial_recovery_payload`は初回復旧用の既にtypedなpayload bytes、`staged_recovery_payload`はstage後に保持するopaque payload bytesであり、P1-03はraw JSON parserを持たない。全てのEventStore readはvalidated `DomainEvent` tupleを返し、`StoredEvent`はappend returnとEventStore内部だけで使う。

`RecoveryEventMetadata`はrecoveryで生成するEventの唯一のmetadata shapeとして、`request_kind`、`recovery_payload_version`、campaign/session/scene/turn/canonical request identity、input digest、`recovery_reason`、`recovery_selector`、`occurred_at` timestamp、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`を同じ名前のフィールド集合として固定する。roleと予約IDの対応は`PlayerInputAccepted`=`accepted_event_id`、`TurnResumed`=`resumed_event_id`、`TurnAwaitingPlayer`=`awaiting_player_event_id`、`TurnCommitted`=`committed_event_id`、normal `TurnAborted`=`aborted_event_id`、recovery `TurnAborted`=`recovery_aborted_event_id`とする。`aborted_event_id`はnormal `TurnAborted`、`recovery_aborted_event_id`はrecovery abortだけを示す。metadata objectは`stage_recovery_metadata()`のCAS時に初めて確定し、初期recordではlifecycle metadata（`recovery_reason`、`recovery_selector`、6つのEvent ID、`occurred_at`）だけがnullableであり、immutableな`request_kind`、`recovery_payload_version = 1`、`initial_recovery_payload`は非nullableである。確定後は`request_kind`、version、reason、origin selector、occurred_atを必須とし、6つのlifecycle Event IDはroleごとの予約・candidateに応じてnullableとする。normal terminal用に予約した未使用の`recovery_aborted_event_id`のように、actual Eventにならない予約IDを保持してよい。`request_key`、`initial_recovery_payload` / `staged_recovery_payload`、response bodyはEvent metadataへ入れず、coordination recordだけが保持する。recoveryのEvent metadataは`TurnEventMetadata`と同じcanonical `turn_request_id`を使い、coordination recordの外部keyをDomain Eventへ混ぜない。`event_ids`はこの6つの個別Event IDのうちnon-NULLな値をlifecycle順にまとめたメモリ上の派生値であり、SQL columnとして二重保持しない。

P1-03のRecoveryMetadataFactory concrete implementationは`src/neontof/application/turn_lifecycle.py::build_recovery_metadata(record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...], inputs: RecoveryMetadataInputs) -> RecoveryEventMetadata`の一つだけであり、ownerはP1-03 Lifecycle laneの同moduleである。この関数はfactory aliasに適合し、`record.base_event_sequence`でfull validated tupleをprefix / owned_suffixへ分け、既存DomainEventのrole-aware fieldだけからmetadataをdeterministicに作り、注入された`inputs.occurred_at`と`inputs.reservation`の6 role IDを保存する。全roleのenvelopeは`campaign_id`、`session_id`、`scene_id`、`turn_id`、lifecycle payloadはpayload自身のcanonical `turn_request_id`を照合し、`PlayerInputAccepted`のpayload `input_digest`はsubmitのcurrent accepted anchorだけでrecordと照合する。`root_turn_request_id`をEvent fieldとして読まず、recordのrootとcanonical IDおよびcurrent accepted anchorの関係はclaim時のimmutable identity validationで確認する。effect / Fact roleはinput digestを要求しない。factoryは新しいID、timestamp、selector、EventStore readを内部で生成・captureせず、normal `TurnEventBatchFactory`の引数を直接共有しない。metadata CAS後のrecovery builderは保存済みmetadataを全て再利用する。

SQL、record、metadataのnullabilityは次の一形状に揃える。`request_kind`と`recovery_payload_version`はSQL / `ProcessingTurnRequestRecord` / `FinalTurnRequestRecord` / `RecoveryEventMetadata`の全てで非nullable、`recovery_reason`、`recovery_selector`、`occurred_at`は初期processing recordだけNULLを許し、`RecoveryEventMetadata`とmetadata CAS後のrecordでは非nullable、6つのlifecycle Event IDはSQL / 両record / metadataの全てで`EventId | None`（origin `recovery_selector`ごとの候補・role条件はfull Event validationで検証）とする。初期recordではimmutableな`request_kind`、version 1、`initial_recovery_payload`だけが確定し、lifecycle recovery metadata（`recovery_reason`、`recovery_selector`、6つのEvent ID、`occurred_at`）は全てNULLである。`stage_recovery_metadata()`成功後はrecordの6つの個別Event IDを含む全metadata値が`RecoveryEventMetadata`と同名・同値になり、version、identity、`initial_recovery_payload` / `staged_recovery_payload`は不変である。予約されたIDはcandidate/reuse用のrecord値に過ぎず、未使用予約IDが`owned_suffix`のEvent Logにactual membershipを持たなくてもよい。Event Logの`owned_suffix`に存在するlifecycle Eventは同一roleの非NULL予約IDとtype/context/canonical requestまで一致するsubsetであり、normal terminal actualと`recovery_aborted_event_id` actualの同時存在、role違いのID再利用、非NULL予約IDとのtype/context/canonical request mismatch、予約外actual Eventは`StoreError(code="recovery_identity_mismatch")`へ写像する。origin `recovery_selector`はCAS時点のimmutable fieldであり、現在状態selectorとの単純一致を要求しない。metadata stage前のcrashではmetadataを推測せずprocessingを保持する。

`ActiveTurnRegistry`は`src/neontof/application/turn_lifecycle.py`に置くprocess-lifetimeの具体実装であり、generic interfaceやprovider abstractionにしない。内部の単一lockで`try_acquire`と`release`をatomicに行い、戻り値は`OwnedActiveTurn`または`ExistingActiveTurn`のtyped unionだけとする。両variantはimmutableな`intent`とopaque `token`を保持し、`ExistingActiveTurn.intent`は先行requestの保存済みimmutable request identityとして比較に使う。`ApplicationRuntime`がprocess lifetimeでこの一つの`ActiveTurnRegistry`を所有し、`TurnLifecycleCoordinator`だけへ注入する。`TurnEngine`、route、各request handlerは`ActiveTurnRegistry`を受け取らず、registryの判定はcoordinator経由だけで行う。

P1-03 Persistence / Lifecycleと`TurnRequestStore`は`initial_recovery_payload` / `staged_recovery_payload`をnon-empty opaque bytesとして保存・CAS・再利用するだけで、`RecoveryPayload`をdecodeしない。version、`kind`、identity、media、inner responseのcanonical codecとsanitized validationはP1-08 `src/neontof/application/turn_responses.py`の`encode_recovery_payload()` / `decode_recovery_payload()`、`ResponseDocumentBuilder`、recovery `ResponseRebuilder`だけが担当する。
DBに保存する`staged_recovery_payload`は、常に`encode_recovery_payload(StagedRecoveryPayload(..., response_payload=encode_staged_response_seed(seed)))`で構成したouter bytesである。P1-03の`select_response_payload()`はvalidated Eventのcurrent owned membership、DBの`recovery_payload_version`、initial/stagedのNULL stateだけを使ってこのopaqueなouter bytesを選択して返す。P1-03のselectorとStoreはouter/inner bytesをdecodeせず、outer/innerのdiscriminator、version、identity、media、strict UTF-8、secretを検証しない。normal `committed` / normal `aborted`のv2 staged outer payload必須、awaitingのv2優先/v1 default、recovery-abortedのv1 initialという選択結果を受けたouter/inner strict decode、identity/media validation、sanitized errorはP1-08の`ResponseDocumentBuilder` / `ResponseRebuilder`だけが担当する。

この計画で「v2 staged outer payload」と記す場合、DB、record、`select_response_payload()`が保持・返却するのは必ずouter `StagedRecoveryPayload` bytesであり、canonical inner `StagedResponseSeed` bytesを直接指さない。inner seedへのdecode、identity/media validation、response documentへのmaterializeはP1-08だけが行う。

### claimとIntegrityErrorの固定境界

`TurnRequestStore.claim(*, intent: TurnRequestIntent) -> ClaimResult`は`TurnLifecycleCoordinator`がshared `event_boundary_lock`を保持している閉区間内からだけ呼ぶ。claim自身は必ず一つの`SqliteDatabase._write()` transaction / connectionで完了し、順序は request-key lookup → miss直後の同じconnectionによる`campaign_id`の`status = 'processing'` row SELECT → 同じconnectionでの`EventStore._read_campaign_on_connection(connection, campaign_id)`によるcampaign全体の`DomainEvent` readとfull validation → `COALESCE(MAX(sequence), 0)`からの`base_event_sequence`導出 → processing INSERT とする。`TurnRequestIntent`からcaller supplied `base_event_sequence`と`staged_recovery_payload`を受け取らず、insertしたrecordからだけ`TurnRequestIdentity`を返す。別keyのprocessing rowがあれば`StoreError(code="turn_already_processing")`へ写像する。EventStoreの別connection read、`read_campaign()`の別呼出し、copied event tuple、nested `_write`、filtered turn readを使わない。`ProjectionStore.rebuild()`のsame-connection readerが1 callsite、P1-03 claimが2 callsite目であり、cross-module same-connection readerは合計2 callsiteに固定する。

same-keyが存在する場合は、intentが持つ`request_kind`、`requested_media_type`、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`root_turn_request_id`、canonical `turn_request_id`、`input_digest`などの保存済みimmutable identityだけをrecordと完全照合する。claim前にEngineが供給した`initial_recovery_payload` bytesはNewClaimのINSERT seedにだけ使い、ExistingProcessingClaim / ExistingFinalClaimでは比較・上書きせず捨て、保存済みrecordのinitial/staged payloadだけをauthorityにする。既存recordでは`base_event_sequence`を現在のEvent Logの`MAX(sequence)`と比較せず、`base_event_sequence`を再導出せず、recovery payload version / payload / durable metadataも保存値をそのまま再利用する。一つでもimmutable identityが不一致ならcached body、identity値、SQLite messageを返さず`StoreError(code="request_key_conflict")`を返す。同一identityなら`ExistingProcessingClaim`または`ExistingFinalClaim`を返し、finalのcached responseがあれば`status_code=200`、requested `media_type`、non-empty body bytesをbyte-for-byteで返す。完了後のsame-key replayは保存済みcacheのbyte-for-byte replayであり、`request_key_conflict`にならず、prepare / Provider / Dice / Event appendを再実行しない。`base_event_sequence`をfull campaign readの`COALESCE(MAX(sequence), 0)`から確定するのはmissした`NewClaim`のclaim transaction内だけである。resumeの新しい`request_key`は同じcampaign-scoped canonical requestを参照できるが、`campaign_id`、`session_id`、`scene_id`、`turn_id`、`root_turn_request_id`、Event-derived statusが一致する場合だけ`NewClaim`を返す。claimの戻り型でnew / existing processing / existing finalを混同しない。

`stage_recovery_metadata(*, request_key: RequestKey, metadata: RecoveryEventMetadata) -> ProcessingTurnRequestRecord`は、`status = 'processing'`かつrecovery metadataが未確定（`recovery_reason`、`recovery_selector`、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`、`occurred_at`が全てNULL）のrecordに対してだけ、一つの`_write` transaction / connection内で一度だけCASを成功させる。`request_kind`、`recovery_payload_version`、全canonical identity、payloadは既存recordと再照合し、成功時はmetadataの`recovery_reason`、`recovery_selector`、6つの個別Event ID、`occurred_at`だけを保存する。既に同一metadataが保存済みなら同じrecordをidempotentに返し、異なるmetadata、異なる`request_kind`、version不一致、または一部だけ保存されたmetadataは`StoreError(code="recovery_identity_mismatch")`または`StoreError(code="request_key_conflict")`へsanitizedに写像する。このAPIはidentity、`base_event_sequence`、`recovery_payload_version`、initial/staged payload、status、responseを更新しない。metadata確定後にだけrecoveryまたはnormal Event appendへ進み、`ResponseRebuilder`と`complete()`はその後に実行する。metadataがrecordにない段階でcrashしてもEvent Logから推測せず、同一metadataの再送だけをidempotentに許す。

INSERT / UPDATEで発生したSQLite `IntegrityError`はpersistence境界内で固定codeへ写像し、raw SQLite messageを通常log、exception message、response、Transcript、Telemetryへ出さない。`request_key` PRIMARY KEY違反は`request_key_conflict`、`uq_turn_requests_campaign_processing` partial UNIQUE違反は`turn_already_processing`、request kind/status/media/recovery payload/responseのCHECK違反は`invalid_record`、その他のSQLite `IntegrityError`は`store_integrity_error`とする。PK、partial UNIQUE、CHECK、その他のどのconstraintでもraw SQLite messageやconstraint nameを外へ出さない。元exceptionのmessage、args、cause、context、custom attributeを保持しない。

`stage()`は同じ`_write` transaction内で`request_key`、`status = 'processing'`、`recovery_payload_version = expected_version`、`staged_recovery_payload IS NULL`をcompare-and-setし、成功時の`SET`では`staged_recovery_payload = ...`と`recovery_payload_version = 2`を同時に行い、version 1から2へ一度だけ進める。missing、非processing、version不一致、既stageは`request_not_found`、`request_not_processing`、`stage_conflict`のsanitizedな固定codeへ写像し、partial updateを残さない。`complete()`は正確に`complete(*, request_key, expected_version, status, response) -> FinalTurnRequestRecord`だけを受け取り、同じ`_write` transaction内で`request_key`と`expected_version`をprocessing recordに対してcompare-and-setする。`complete()`はrecovery metadata、identity、initial/staged payload、`recovery_payload_version`を更新引数にも`SET`にも持たず、version 1/2のどちらでもそれらを不変にしたままresponse三列とstatusだけを同時更新する。`CachedTurnResponse.body`は`complete()`前に必ず`body.decode("utf-8", errors="strict")`で検証し、invalid bytesは`StoreError(code="invalid_response")`へsanitizedに写像してcompleteを実行せず、rowをprocessingのまま保持する。missingは`request_not_found`、非processingまたは不正recordは`request_not_processing`、既完了recordとstatus/media/body bytesが一致すればidempotentに既存recordを返し、body bytesが異なれば`response_conflict`へ写像する。processing時response三列は全NULL、completion時はcode `200`、requested media、non-emptyなstrict UTF-8 bodyを必ず保持する。complete cacheはEvent append後のcanonical bodyを保存し、HTTP公開前に確定する。SQLの`response_body` CHECKはBLOBかつnon-emptyを固定し、strict UTF-8はBLOB境界でCoordinator / Storeが担保する。

### PreparedTurn、candidate validation、Event順序

`TurnPreparation`は`Callable[[TurnRequestIdentity, tuple[DomainEvent, ...]], PreparedTurn]`であり、`TurnRequestIdentity`とNewClaim直後に同じ`event_boundary_lock`内で取得したcampaign全体のvalidated `tuple[DomainEvent, ...]`を受け取り、typedな`PreparedTurn`を返す。callbackは`rebuild_projection(campaign_events)`等でEvent-derived Projection/contextを先に作り、既存active target/conditionのFactIdを解決し、target/conditionのcandidateを確定してからpre-IDの`PreparedEffect`列を返す。`PreparedEffect`は`EventId`と`OccurredAt`を持たず、`EventDraftBody`と同じ`type` / `event_version=1`、campaign/session/scene/turn context、origin、visibility、lossless `payload_json` bytesだけを保持する。`PreparedTurn`は`effect_candidates`、`terminal_status`、`scenario_end`、`abort_reason`、`staged_recovery_payload`だけを持ち、`EventDraft`、`EventBatch`、response bodyをfieldとして保持しない。coordinatorはcallbackの戻り後、最終`effect_candidates`と`scenario_end`が確定してから`event_id_sequence`を呼び、post-IDのcandidate batchとterminal builderを作る。responseはcampaign全体の`DomainEvent`列からP1-08の`ResponseRebuilder`で再構築し、P1-03のbuilderはraw request JSON、Model output、Dice output、JSON responseを解釈しない。

`TurnEventBatchFactory`と`TurnEventIdSequence`は`src/neontof/application/turn_models.py`のLifecycle symbolとして注入し、次のexact `Callable`を隠さない。normal factoryの第三引数はEvent authorityであるcampaign全体のvalidated `tuple[DomainEvent, ...]`であり、factoryはEventStoreをcaptureしない。受け取ったtupleを`prefix = {event | event.sequence <= identity.base_event_sequence}`と`owned_suffix = {event | event.sequence > identity.base_event_sequence}`へ分け、origin selector/statusはcurrent identityに一致するprefixから、candidate metadataとowned roleはcurrent identityに一致するowned_suffixおよび`identity` / `PreparedTurn` / `OccurredAt` / Event ID sequenceから作る。matcherは既存DomainEventのenvelope `campaign_id` / `session_id` / `scene_id` / `turn_id`を全role共通で照合し、lifecycle roleではpayloadの`turn_request_id`を照合する。`PlayerInputAccepted`のpayload `input_digest`はsubmitのaccepted anchorとsubmit recordだけで照合し、resumeの新しい`input_digest`を既存accepted anchorやresume/awaiting/terminal payloadへ比較しない。`root_turn_request_id`はEvent fieldとして読まず、accepted anchorとrecord identityのroot/canonical関係をclaim時に検証する。Dice/Resource/Clock/Fact等はturn envelope/contextとrole-aware reservation / authorized candidateだけでcurrent roleを判定する。campaign eventsなしでselectorを推測する実装は契約違反とする。

```python
TurnEventBatchFactory = Callable[
    [TurnRequestIdentity, PreparedTurn, tuple[DomainEvent, ...], OccurredAt, Sequence[EventId]],
    tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch],
]
TurnEventIdSequence = Callable[[TurnRequestIdentity, PreparedTurn], Sequence[EventId]]
```

`TurnEventIdSequence(identity, prepared)`は、最終的に確定した`PreparedTurn.effect_candidates`、submit/resume prefix、Turn terminalに必要なEvent IDを順番に返し、`prepared.scenario_end is not None`のときだけ追加のSessionEnded用Event IDを末尾に一つ含める。SessionEnded用IDをRecovery metadataの6 lifecycle予約IDへ混ぜたり、ScenarioRuntimeが先に予約したりしない。

`RecoveryMetadataFactory(record, campaign_events, inputs)`は、validated full tupleから`prefix = {event | event.sequence <= record.base_event_sequence}`と`owned_suffix = {event | event.sequence > record.base_event_sequence}`を決め、`current_prefix_events = {event in prefix | matches_current_turn_identity(event, record=record)}`と`current_owned_suffix_events = {event in owned_suffix | matches_current_turn_identity(event, record=record)}`を導出する。matcherの全role共通部分はEvent envelopeの`campaign_id` / `session_id` / `scene_id` / `turn_id`だけをrecordと照合し、lifecycle roleは各payloadのcanonical `turn_request_id`を照合する。`PlayerInputAccepted`の`input_digest`はsubmitのaccepted anchorとsubmit recordだけで照合し、resumeのprefix anchorはその元requestで検証済みとしてresume recordの新しいdigestとは比較しない。`root_turn_request_id`はEvent fieldではなく、accepted anchorとrecordのroot/canonical identity関係としてclaim時に検証する。Dice/Resource/Clock/Fact等のeffect roleはcurrent turn envelope/contextとrole-aware reservationまたはauthorized candidateだけで扱い、input digestを要求しない。origin `recovery_selector`、origin status、recovery reasonはcurrent identityに一致するprefixから、保存済みIDとのrole/type/context/canonical request照合はcurrent identityに一致するowned_suffixから導き、以前のTurnや同じcanonical requestでもidentity tupleが異なる`PlayerInputAccepted` / `TurnAwaitingPlayer`を現在のresume requestのEventとして再利用しない。factoryはこのexact三引数で`inputs.occurred_at`と`inputs.reservation`を加えてdeterministic metadataを作り、通常`TurnEventBatchFactory`のidentity / `PreparedTurn` / campaign events / `OccurredAt` / event ID sequenceを直接共有しない。`RecoveryEventIdSource`とnormal `TurnEventIdSequence`は別の注入sourceである。

coordinatorは`NewClaim`を受け取った直後、同じ`event_boundary_lock`内で`EventStore.read_campaign(record.campaign_id)`を一度だけ明示的に呼び、campaign全体のvalidated `tuple[DomainEvent, ...]`を取得する。これはclaim transaction内の`EventStore._read_campaign_on_connection(connection, campaign_id)`によるfull readとは別の、TurnPreparationへ渡すためのreadであり、filtered slice、EventStore capture、copied eventを使わない。そのtupleをexecuteへ注入された`prepare: TurnPreparation`へ渡し、`prepare(identity, campaign_events)`を一度だけ呼ぶ。coordinatorはP1-08固有のbound factoryや具体的なpreparation methodを呼ばず、callbackの責務である`rebuild_projection(campaign_events)`等のEvent-derived Projection/context構築、target/conditionのFactId解決、semantic validation、pre-ID effect candidates確定の結果だけを受ける。`prepare`後にstaged payloadがあれば`stage()`でversion 1から2へCASし、その戻りrecordからversion 2の`TurnRequestIdentity`を再構成する。staged payloadがなければversion 1のidentityをそのまま使う。target/conditionを含む最終`effect_candidates`が確定した後にだけ、注入された`event_id_sequence(identity, prepared)`を一度呼んで未採番Event IDのsequenceを得、注入された`utc_occurred_at()`からUTCの`OccurredAt`を一度取得し、`turn_event_factory(identity, prepared, campaign_events, occurred_at, event_ids)`を一度呼ぶ。factoryは受け取ったfull tupleを`prefix = {event | event.sequence <= identity.base_event_sequence}`と`owned_suffix = {event | event.sequence > identity.base_event_sequence}`へ分け、origin selector/statusはcurrent identityに一致するprefixから、candidate metadataとowned roleはcurrent identityに一致するowned_suffixおよびidentity / `PreparedTurn` / UTC `OccurredAt` / event ID sequenceから作り、`TurnEventMetadata`、SQLと同じ名前・nullable状態の`RecoveryEventMetadata`、`EventBatch`を返す。`event_id_sequence`のEvent IDはEventStoreのtransaction-assigned sequenceとは別の値であり、callerへSQLite sequence allocatorを公開しない。coordinatorは返されたrecovery metadataを`stage_recovery_metadata()`へEvent append前に渡し、candidate validation後にだけappendする。NewClaim後のこのreadがprepare後へ遅延したり、prepare後に別のProjectionを作ったりしてはならない。ExistingProcessingClaimのrecoveryでは、metadataが未確定のときだけ同じ`event_boundary_lock`内で注入済み`utc_occurred_at()`を一回、`recovery_event_id_source(identity)`を一回呼び、`RecoveryMetadataInputs(occurred_at=..., reservation=...)`を作って`recovery_metadata_factory(record, campaign_events, inputs)`を一回呼び、metadata CAS後にcandidate appendへ進む。`RecoveryEventIdSource`はEventStoreをcaptureせず、request identityと6 roleの組からdeterministicなreservationを返す。metadataが既に保存済みならclock source、ID source、factoryを再実行せず、保存metadataだけを使う。recovery branchはnormal factoryと`event_id_sequence`を呼ばず、recordから全metadataを復元する。`RecoveryMetadataFactory = Callable[[ProcessingTurnRequestRecord, tuple[DomainEvent, ...], RecoveryMetadataInputs], RecoveryEventMetadata]`はrecord、campaign全体のvalidated `DomainEvent` tuple、typed inputsの三引数を受け取り、`current_prefix_events`からorigin selector/statusを、`current_owned_suffix_events`からcurrent owned identity/stateを導き、inputsのtimestampと6 role IDを加えてdeterministicなrecovery metadataを作る。通常の`TurnEventBatchFactory`は別経路で、`TurnRequestIdentity`、`PreparedTurn`、campaign全体のvalidated `DomainEvent` tuple、UTC `OccurredAt`、event ID sequenceからmetadataと`EventBatch`を作る。Recoveryはnormal factoryの引数を直接共有せず、保存済みrecord、prefix origin、current identity一致のowned_suffix actual stateからだけmetadataを復元・確定する。`RecoveryMetadataFactory`とnormal `TurnEventBatchFactory`が作る6個のlifecycle Event IDはrecord上の候補・再利用値であり、`aborted_event_id`はnormal `TurnAborted`専用、`recovery_aborted_event_id`はrecovery abort専用として別々に保存する。recovery abort batchは後者だけを使い、未使用の予約IDがEvent Logに存在しなくてもよい。metadata CAS後のretryは保存済み6 IDとtimestampを再利用し、新しいfactory、ID、clockを作らない。

normal preparationの境界はpre-IDとpost-IDを混在させない。`prepare(identity, campaign_events)`、`materialize_accepted_result(*, identity, outcome, projection, context, dice_result)`、`materialize_dice_event(*, identity, result)`は`PreparedEffect`またはそのtupleだけを返し、Event ID、`OccurredAt`、`EventDraftBody`、`EventDraft`、`EventBatch`を生成しない。各pre-ID producerはcurrent `TurnRequestIdentity`から`PreparedEffect`のenvelopeを構成し、過去Turn/global contextの推測やidentity mismatchを許可しない。target/conditionのsupersede/no-opを含む`PreparedTurn.effect_candidates`が確定してから`event_id_sequence(identity, prepared)`、`utc_occurred_at()`を順に一度ずつ呼ぶ。`TurnEventBatchFactory(identity, prepared, campaign_events, occurred_at, event_ids)`だけが各pre-ID候補から必須のEvent ID / `OccurredAt`を持つ`EventDraftBody`、`EventDraft`、`EventBatch`を構成し、candidate validationとEventStore appendへ渡せるpost-ID batchにする。

`build_started_events()`は初回submitの`PlayerInputAccepted`と`TurnResumed`だけをこの順で同じbatchへ置く。通常のterminal pathのsubmit Event順序は`PlayerInputAccepted -> TurnResumed -> Turn terminal`であり、validated effectsは`TurnResumed`とTurn terminalの間だけに置く。`build_resumed_event()`は`TurnResumed`だけを返し、resumeのEvent順序は`TurnResumed -> Turn terminal`であり、二つ目の`PlayerInputAccepted`を作らない。`build_awaiting_event()`は`TurnAwaitingPlayer`一件だけを返し、pre-model ambiguityのcandidateではstarted prefixの後に最後に置く。`TurnAwaitingPlayer`は既存`TurnStatus`の`awaiting_player`へ遷移し、effectsを持たず、後続resumeを許可する。Turn terminalは`build_committed_event()`または`build_aborted_event()`で構成し、`scenario_end`がある場合のsession terminal `SessionEnded`だけをfactoryがその後に置く。

`build_submit_events` / `build_resume_events`は`TurnEventBatchFactory`内部でpost-ID metadataを受けた後だけ呼ぶhelperであり、P1-08のprepare/materializerから直接呼ばない。`build_submit_events(started, prepared)`は、`prepared.terminal_status`が`committed`または`aborted`なら`started`のsubmit prefix、`prepared.effect_candidates`由来のpost-ID effect candidate、対応するTurn terminalをこの順で連結する。`prepared.terminal_status == "awaiting_player"`ならeffect candidateを作らず、`build_awaiting_event()`をstarted prefixの後に連結する。`build_resume_events(resumed, prepared)`は`prepared.terminal_status`が`committed`または`aborted`のときだけ`resumed`のresume prefix、effect candidate、terminalを連結し、`awaiting_player`はrejectする。通常のsubmit Event順序は`PlayerInputAccepted -> TurnResumed -> Turn terminal`、resume Event順序は`TurnResumed -> Turn terminal`である。`Turn terminal`は通常Turnで最後だが、`prepared.scenario_end is not None`のときだけfactoryが`TurnCommitted -> SessionEnded`を構成し、SessionEndedをsession terminalとして最後に置く。SessionEndedのenvelopeは`campaign_id` / `session_id`、`scene_id=None`、`turn_id=None`、payload `reason="completed"`とし、`scenario_end`のsuccess/failure自体のEvent authorityはP1-12の`ScenarioOutcomeFact` candidateをreplayした値である。effectsは`terminal_status == "committed"`のときだけTurnCommitted直前に置く。`awaiting_player`と`aborted`にはeffectsを許可しない。両者はmetadata、campaign、turn、canonical request、root request、Event IDの整合を検証し、callerへsequenceを割り当てさせない。`PreparedEffect`を`EventDraftBody`へ変換して`EventBatch`を構成できるのは、event IDとoccurred_atを受け取る`TurnEventBatchFactory`だけである。`build_revert_event(metadata, payload)`は削除を行わず、`TurnRevertedPayload`を持つ一件のEventBatchを返す。

`validate_and_materialize_candidate(existing_events: tuple[DomainEvent, ...], candidate_batch: EventBatch)`は、EventStoreの全readが返すvalidated `DomainEvent`列だけを受け取り、`tuple[DomainEvent, ...]`を返す。public readを`StoredEvent`へ包み直したり、copiedまたは未検証のEventを渡したりしない。append transactionの予測sequenceはcoordinator内部のappend-return/internal-only materializationで扱い、`StoredEvent`を既存readの型として使わない。candidateをtyped `DomainEvent`列へmaterializeし、既存列の末尾から予測したsequenceをcandidateへ割り当てた仮想列へ、append前に`project_turn_status()`と`rebuild_projection()`を実行する。Event sequence、campaign/turn/request context、既存`TurnStatus`から許可されたstatus transition、payload validationを全て検証し、失敗したcandidateはappendしない。Resource、Character、Clock、Factなどのauthoritative effect Eventは、同じcandidateの最後に`TurnCommitted`があり、かつcandidate全体のprojectionが正常な場合だけ許可する。`TurnAwaitingPlayer`または`TurnAborted`とeffect Eventの組み合わせ、terminal後のEvent、`TurnCommitted`なしのeffect、non-committed effectsは拒否する。つまりeffectsは`TurnCommitted`なしでは常に禁止し、`TurnAwaitingPlayer` / `TurnAborted` batchには入れない。candidate validationはprojectionやstatusを直接更新せず、predicted sequenceを含むappend前の純粋な検証とmaterializationだけを行う。

`PreparedTurn.scenario_end`が`None`なら通常TurnはTurn terminal（`TurnCommitted`または`TurnAborted`）で終了する。`scenario_end`が`"success"`または`"failure"`なら`terminal_status`は`"committed"`でなければならず、candidate validationは`TurnCommitted`の直後にだけsession terminal `SessionEnded`を許可し、SessionEndedをcandidate列の最後とする。`SessionEnded`は`campaign_id` / `session_id`を持ち、`scene_id=None`、`turn_id=None`、payload `reason="completed"`である。`scenario_end`のsuccess/failureをEvent Log上で復元する`ScenarioOutcomeFact` candidateはP1-12のScenarioRuntimeだけが供給し、P1-03はそのcandidateを作らず、genericな`scenario_end`をSessionEndedの制御にだけ使う。`TurnEventIdSequence`はこの追加Event IDを一つだけ予約し、P1-12のfixtureやScenarioRuntimeがSessionEndedを直接appendしない。

`TurnLifecycleCoordinator.execute()`はpre-claim `TurnRequestIntent`を受け取り、次の順序を一つの閉区間として実行する。

```text
ActiveTurnRegistry.try_acquire(intent)
  ├ ExistingActiveTurn
  │   → registryが保持するimmutable intent/tokenと入力intentを照合
  │   → ProcessingTurnResult(status="processing", http_status_code=202, response=None)
  └ OwnedActiveTurn（registry miss/restartを含む非fast path）
      → ApplicationRuntime.event_boundary_lock
      → TurnRequestStore.claim(intent=...) をこのexecute呼出しで正確に一回
      → ExistingProcessingClaim（INSERT 0、保存済みbase不変）
          → campaign全体のvalidated DomainEvent read
          → RecoveryPlan = recover_processing(*, record=record, campaign_events=campaign_events)
          → optional candidate validation
          → execute内の既存唯一の EventStore.append callsite（candidateがある場合だけ一回）
          → campaign全体を再read / select
          → coordinator-only ResponseRebuilder 一回
          → strict response validation
          → execute内の TurnRequestStore.complete 一回
      → ExistingFinalClaim → ExistingFinalTurnResult
      → NewClaim → `EventStore.read_campaign(record.campaign_id)`（TurnPreparation用のcampaign全体validated `DomainEvent` tuple）
          → `prepare(identity, campaign_events)`を一回（Projection/context、target/condition、effect_candidatesを確定）
          → staged payloadがあればstage
          → 最終effect_candidates確定後にevent_id_sequence + utc_occurred_at
          → turn_event_factory(identity, prepared, campaign_events, occurred_at, event_ids)
          → factoryだけがPreparedEffectをEventDraftBody/EventDraft/EventBatchへ構成
          → stage_recovery_metadata
          → candidate full validation
          → EventStore.append
          → campaign全体read / rebuild / ResponseRebuilder
          → TurnRequestStore.complete
          → CompletedTurnResult
```

`ActiveTurnRegistry.try_acquire(*, intent=...)`の結果が`ExistingActiveTurn`なら、先行requestのimmutableな`intent`（保存済みrequest identity）と入力intentをboundary lockなし・claimなしで照合する。同じrequest keyでimmutable fieldが違えばtypedな`StoreError(code="request_key_conflict")`、別request keyならtypedな`StoreError(code="turn_already_processing")`とし、どちらも先行処理のlockを奪わない。同一identityなら`ProcessingTurnResult(status="processing", http_status_code=202, response=None)`として返し、prepare、stage、claim、provider、dice、append、rebuild、complete、recoveryを実行しない。これはregistry active hitだけの高速202であり、永続recordを読み直すregistry missの結果とは区別する。

`OwnedActiveTurn`の場合（registry miss/restartでregistryが空の場合を含む）だけ、registry tokenを保持したままshared `ApplicationRuntime.event_boundary_lock`を取得し、その同じ閉区間で`TurnRequestStore.claim(intent=...)`をこのexecute呼出しで正確に一回呼ぶ。claimの`ExistingProcessingClaim`は単なる`ProcessingTurnResult`返却にせず、同じcampaignの全validated `DomainEvent`列をreadし、`prefix` / `owned_suffix`へ分割してから、正確な`RecoveryPlan = recover_processing(*, record=..., campaign_events=...)`を得る。別process/restartでregistryがmissした場合もこのdurable claimへ進むが、`recover_processing()`はmetadata未確定時の`RecoveryMetadataFactory`と`stage_recovery_metadata()`の一度のCAS、recovery decision、optional recovery candidate batchの準備だけを行う。`recover_processing()`はclaim、prepare、Provider、Dice、`EventStore.append()`、`ResponseRebuilder`、`TurnRequestStore.complete()`を呼ばない。executeはその`RecoveryPlan.candidate_batch`がある場合だけcandidate full validationを行い、execute内の既存唯一のapplication-level `EventStore.append()` callsiteを一度使い、campaign全体を再read / selectし、coordinatorだけが`ResponseRebuilder`を一度実行してstrict UTF-8の`CachedTurnResponse`を検証し、execute内で`TurnRequestStore.complete()`を一度実行する。candidateがない既存terminal / awaitingも同じ再read、rebuild、complete順で処理する。このexecute呼出しでdurable claimは既に正確に一回済みであり、同じrequestの次回でもINSERTとbaseの再導出をせず、`recover_processing()`自身はclaimを呼ばない。`NewClaim`の場合は、まずNewClaim直後の同じlock内で`EventStore.read_campaign(record.campaign_id)`を一度だけ呼び、そのfull validated tupleを注入済みの`prepare: TurnPreparation`へ渡して`prepare(identity, campaign_events)`を一回実行する。TurnPreparationはここで`rebuild_projection(campaign_events)`等のEvent-derived Projection/contextを作り、target/conditionのFactId解決と最終`effect_candidates`を確定する。`PreparedTurn.staged_recovery_payload`がnon-NULLのときだけその後に`stage()`を一度だけ行い、最終effect_candidates確定後に注入済み`event_id_sequence(identity, prepared)`を一度、`utc_occurred_at()`を一度呼び、`turn_event_factory(identity, prepared, campaign_events, occurred_at, event_ids)`を一度呼ぶ。そのfactoryが返す`RecoveryEventMetadata`を`stage_recovery_metadata()`へ一度だけ渡し、submit/resume prefix builder、semantic responseとpredicted sequenceを含むfull candidate validation、terminalを含む唯一のapplication-level `EventStore.append()`、全Event read、coordinatorだけの`ResponseRebuilder`一回、strict UTF-8検証済み`CachedTurnResponse`の`TurnRequestStore.complete()`一回をこの順で行い、`CompletedTurnResult`として返す。NewClaim後のpreparation readをprepare後へ遅延させたり、prepare後に別のProjection/contextを作ったりしない。通常Turnはcandidateとresponseを検証してからterminal Eventをappendし、append後の必要な全Event reread/rebuildで最終`CachedTurnResponse`を検証してからcache/turn requestをcompleteする。metadata確定 → recovery/normal Event append（recovery appendもexecuteの同じcallsite）→ 全Event read / selector → coordinatorだけの`ResponseRebuilder` → response/statusだけの`complete()`という順序を崩さない。`ExistingFinalClaim`は`ExistingFinalTurnResult`として保存済み`CachedTurnResponse` bytesをそのまま返し、rebuildとcompleteを実行しない。`CompletedTurnResult`と`ExistingFinalTurnResult`は`CachedTurnResponse.status_code`、`media_type`、body bytesを`TurnEngine`からrouteへforwardし、再serializeしない。`ProcessingTurnResult`はresponseを持たず、routeが`http_status_code=202`と`status="processing"`へmapする。`ResponseRebuilder`と通常Turnの`complete()`のcallerは常にこのcoordinator一つであり、response rebuildまたはcompleteが失敗した場合はその試行でcompleteを再実行せずprocessing recordを保持し、次回executeのrecovery branchで再開する。

lock orderは`ActiveTurnRegistry.try_acquire` → `ApplicationRuntime.event_boundary_lock` → EventStore operation内のSQLite `_WRITE_LOCK`で固定し、逆順取得やlockの兼用を行わない。先行`OwnedActiveTurn`は最初のclaimからprepare / stage / candidate validation / append / read / rebuild / completeまでboundary lockを保持し、complete後の`finally`でだけregistry tokenとboundary lockを解放する。registryの`ExistingActiveTurn` fast pathだけはboundary lockを取得せず、先行requestのlockを奪わない。`OwnedActiveTurn`取得後にclaim / prepare / stage / candidate validation / append / read / rebuild / complete / `recover_processing`のどの例外が起きても、lockを取得済みか記録して`try/finally`でevent boundary lockとregistry tokenを解放する。呼出し側は注入済みのprepareを渡すだけで、`TurnLifecycleCoordinator`はP1-08のEngineを呼ばず、`execute()`内に唯一の`EventStore.append()`、`TurnRequestStore.claim()`、`TurnRequestStore.complete()` callsiteを持つ。`TurnLifecycleCoordinator`は`sqlite3`をimportせず、boundary lockはSQLiteの`_WRITE_LOCK`とは別objectである。single-process / single-worker前提で、coordinatorはconnectionをlock越しに保持せず、nested `_write`を行わない。registry miss後の`ExistingProcessingClaim`は同じboundary lock内で`recover_processing()`へ入り、単なる202返却や通常prepareの再実行にはしない。

一つの`execute()`呼出しでは、`ExistingActiveTurn` fast pathだけがdurable claimなし、それ以外（`OwnedActiveTurn`、registry miss、restart、recovery retryを含む）は同じ`event_boundary_lock`内で`TurnRequestStore.claim(intent=...)`を正確に一回行う。`ExistingProcessingClaim`では保存recordを返すだけでINSERT、`base_event_sequence`の再導出、現在MAXとの比較を行わず、その後に`recover_processing()`へ進む。`recover_processing()`はclaimを呼ばず、recovery retryでもexecuteのdurable claim一回 → `RecoveryPlan`の順序を崩さない。別keyのprocessingはclaimの`turn_already_processing`（HTTP `409`）、same-key processingはclaim一回・INSERT `0`・保存base不変である。

### recovery、undo、観測保持

recovery branchの全入力はvalidated full `campaign_events`を`prefix`と`owned_suffix`へ分けて扱う。`prefix = {event | event.sequence <= record.base_event_sequence}`はNewClaim以前の履歴、`owned_suffix = {event | event.sequence > record.base_event_sequence}`は当該requestのowned lifecycle Eventであり、`RecoveryPlan.prefix_events` / `RecoveryPlan.owned_suffix`へ保存する。origin `recovery_selector` / statusはcurrent identityに一致するprefixから、予約IDとのrole/type/context/canonical request照合、normal/recovery terminal、current payloadはcurrent identityに一致するowned_suffix（candidateがあるときはauthorized candidateを続けた仮想suffix）から導く。以前のTurnや同じcanonical turnの`PlayerInputAccepted` / `TurnAwaitingPlayer`をcurrent requestのowned Eventとして二重利用しない。full tupleをrebuildへ渡すことは許可するが、owned state/payloadの判定に全履歴を直接使わない。

`build_crash_recovery_batch(record, campaign_events)`の`campaign_events`はturn sliceではなくcampaign全体のvalidated `DomainEvent`列である。builderと`TurnLifecycleCoordinator.recover_processing(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> RecoveryPlan`は最初に`record.request_kind`と`base_event_sequence`でfull tupleを`prefix = {event | event.sequence <= record.base_event_sequence}` / `owned_suffix = {event | event.sequence > record.base_event_sequence}`へ分ける。`record.request_kind == "submit"`でcurrent identityに一致するprefixに`PlayerInputAccepted`がなく、同じcurrent identityに一致するowned_suffixにもaccepted/terminalがないときだけ`accepted_event_id`を使う`PlayerInputAccepted -> recovery TurnAborted` candidateを作り、`record.request_kind == "resume"`でcurrent identityに一致するprefixに既存の`PlayerInputAccepted` / `TurnAwaitingPlayer`などがあり、同じcurrent identityに一致するowned_suffixに今回の`TurnResumed`またはterminalがないときはprefixのIDを検証するだけで`recovery_aborted_event_id`のrecovery `TurnAborted` candidateだけを作る。どちらもprefix Eventをcurrent requestのowned Eventとして再appendせず、resume recoveryで二つ目の`PlayerInputAccepted`を作らない。builderはrecordに保存済みの一つの`RecoveryEventMetadata` shape（`request_kind`、`recovery_payload_version`、`recovery_reason`、`recovery_selector`、`occurred_at`、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`）を再利用し、新しいselector、identity、Event ID、timestampをbuilder内で生成しない。`recover_processing()`はregistry miss後の`ExistingProcessingClaim`から同じ`event_boundary_lock`内で明示的に呼び、metadata未確定時の注入済み`RecoveryMetadataFactory`と`stage_recovery_metadata()`の一度のCAS、recovery decision、optional candidate batchの準備だけを行う。`recover_processing()`はclaimを呼ばず、prepare、Provider、Dice、`EventStore.append()`、`ResponseRebuilder`、`TurnRequestStore.complete()`を呼ばず、executeが返されたplanを使って同じ既存append / rebuild / complete順を実行する。既存metadataがある場合はrecordから6 IDを含む全fieldを復元し、factory、fresh ID、clock、prepare、Provider、Diceを実行しない。

`TurnRequestStore.read_processing(*, campaign_id: CampaignId) -> ProcessingTurnRequestRecord | None`はunique partial indexによりcampaignごとに最大一件を返すdurable guardであり、再起動後も同じcampaignのorphan processingを確認できる。`recover_processing(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> RecoveryPlan`は、保存済みmetadataの全fieldとcampaign全体のvalidated Event列を照合し、metadata未確定時だけdeterministic factoryと`stage_recovery_metadata()`の一度のCASを行い、既存terminal / awaiting / recovery abortの判定とoptional `build_crash_recovery_batch()`の準備をした`RecoveryPlan`を返す。このmethodはclaimを呼ばず、prepare、Provider、Dice、`EventStore.append()`、`ResponseRebuilder`、`TurnRequestStore.complete()`を呼ばない。executeはplanのcandidateがある場合だけfull candidate validationを行い、execute内の既存唯一のEventStore append callsiteで一度appendし、campaign全体を再read / selectした後にcoordinator-only `ResponseRebuilder`を一度呼び、strict UTF-8検証済み`CachedTurnResponse`を検証してexecute内の`TurnRequestStore.complete()`を一度呼ぶ。candidateがないnormal terminal / awaiting / recovery abort後も同じread/select → rebuild → complete順であり、recovery専用callerや別ownerを増やさない。executeは各呼出しでdurable claimを正確に一回行い、`recover_processing()`はclaimを呼ばず、prepare、Provider、Diceを再実行せず、appendできなければprocessingを保持する。response rebuildが失敗した場合もcompleteを呼ばずprocessingを保持し、同じrequest keyの次回はregistry miss後に同じrecord/metadataを使ってexecuteのrecovery branchを再開する。recovery abortがcomplete済みになった後のsame-key replayは`ExistingFinalClaim`の保存済みcache bytesを返す。

- `record.request_kind == "submit"`で、current identityに一致する`prefix`に`PlayerInputAccepted`がなく、同じcurrent identityに一致する`owned_suffix`にもaccepted/terminalがないときだけ、metadataに確定した`accepted_event_id`と`recovery_aborted_event_id`を使い、recordの`initial_recovery_payload`から`PlayerInputAccepted`、続けてrecovery用`TurnAborted(reason="failed")`を一つのbatchへ置く。submitのこの条件以外ではprefixのEventを再appendせず、recovery abortだけを候補にするか`recovery_identity_mismatch`へfail-closedにする。recovery abortは`staged_recovery_payload`を使わず、normal `aborted_event_id`を流用しない。
- `record.request_kind == "resume"`で、current identityに一致する`prefix`に既存の`PlayerInputAccepted` / `TurnAwaitingPlayer`などがあり、同じcurrent identityに一致する`owned_suffix`に今回の`TurnResumed`またはterminalが一件もない場合は、prefixの`accepted_event_id` / `awaiting_player_event_id`を検証・再利用し、`recovery_aborted_event_id`のrecovery `TurnAborted`だけを今回のauthorized candidateにする。prefixのacceptedを再appendせず、resume recoveryで二つ目の`PlayerInputAccepted`を作らない。`RecoveryEventMetadata.recovery_aborted_event_id`をrecovery roleのcandidate / current identity一致のowned_suffix actual Event IDへ一致させ、origin `recovery_selector`はCAS時点の値として保持する。normal `aborted_event_id`はnormal TurnAbortedのみに予約する。
- `TurnAwaitingPlayer`後はawaiting responseをrebuildしてcacheし、input、prepare、Provider、Diceをabortまたは再送しない。
- `TurnCommitted`またはnormal `TurnAborted`後は既存terminal responseをrebuildしてcacheし、Eventを追加しない。normal terminal / recovery abortのresponse payloadは、current identity一致のowned_suffix actual membershipとversionに基づき`select_response_payload()`だけが選ぶ。normal `committed` / normal `aborted`はversion 2のstaged outer payloadを必須とし、version 1 / initialのみまたはstaged outer payload欠落は`recovery_identity_mismatch`へfail-closedにする。recovery abortはrecovery roleの`recovery_aborted_event_id`でnormal terminalと区別し、versionに関係なく`initial_recovery_payload`を使う。awaitingだけはversion 2のstaged outer payloadを優先し、無い場合に限りversion 1のinitial outer bytes（typed presentation defaultはP1-08がstrict decode後に適用）を使う。origin `recovery_selector`を書き換えない。
- `recovery_payload_version`とstaged payloadのNULL state、recovery identity、origin `recovery_selector`、または既存current identity一致のowned_suffix actual / authorized candidateに実在するlifecycle Eventの対応する予約IDが一致しない場合は`StoreError(code="recovery_identity_mismatch")`へ写像し、部分appendもcompleteも行わない。append前は、既存current identity一致のowned_suffix actual Eventまたは今回のauthorized candidate batchに含まれるlifecycle Eventについて、対応する予約IDとのrole・type・context・canonical request一致を検証する。今回使わない予約IDはcurrent identity一致のowned_suffix actualまたはcandidateに対応しなくてもよい。append後は、Event Logのcurrent identity一致のowned_suffixに存在するlifecycle Eventが同一roleの非NULL予約IDと完全一致し、type・context・canonical requestも一致するというsubset/role規則で検証する。保存済みIDは候補・再利用用なので、実際に使われなかった予約ID（normal terminal完了時の未使用`recovery_aborted_event_id`を含む）がEvent Logに不在でもよい。owned_suffixのnormal terminal actualとrecovery abort actualの同時存在、role違いのID再利用、非NULL予約IDとcurrent identity一致のowned_suffix actual Eventのtype/context/canonical request不一致、予約外actual Eventは`recovery_identity_mismatch`でfail-closedにする。origin `recovery_selector`はCAS時点のimmutable fieldであり、現在状態selectorとの単純一致を要求しない。6個のIDとcurrent identity一致のowned_suffix actual membershipの組み合わせが許可遷移外の場合も同じ固定errorとする。recordに無いEventを推測すること、fresh ID/timestampを発行すること、metadataの一部だけを保存することは許可しない。

metadata stage前にprocessが落ちた場合は、metadata未確定の`processing` recordを保持し、recordにないEvent、selector、Event IDをEvent列から推測しない。registry miss後のexecuteが同じboundary lock内で`recover_processing()`を呼び、注入済みdeterministic `RecoveryMetadataFactory`を一度だけ使って6個のrole別予約IDとtimestampを作り、`stage_recovery_metadata()`の一度のCASで全metadataを確定して`RecoveryPlan`を返す。そのCAS後append前にprocessが落ちた場合は、次回executeが保存済みversion、全metadata、`recovery_aborted_event_id`を`read_processing(campaign_id=...)`から再利用し、current identity一致のowned_suffix actual terminalがなければrecovery abortのauthorized batchをinitial payloadで一度だけprepareする。executeはplanをcandidate validationし、同じ既存append callsiteで一度appendする。owned_suffix normal committed / normal aborted actualがある場合はそれぞれ`committed_event_id` / normal `aborted_event_id`を使い、version 2のstaged outer payloadを必須とする。version 1 / initialのみまたはstaged outer payload欠落は`recovery_identity_mismatch`へfail-closedにする。owned_suffix awaiting actualがある場合はversion 2のstaged outer payloadを優先し、無い場合に限りversion 1のinitial outer bytes（typed presentation defaultはP1-08がstrict decode後に適用）でresponseを再構築する。owned_suffix recovery abort actualがある場合はversionに関係なくinitialを選び、appendしない。recovery abort append後、complete前に再度落ちた場合は、次回executeがEvent Log上のcurrent identity一致のowned_suffix actual `recovery_aborted_event_id`を根拠にplanのcandidateを`None`とし、campaign全体をread/selectして`ResponseRebuilder`一回、strict response validation、`complete()`一回を実行し、Eventを追加しない。metadata CASが成功した後のいずれのretryでも保存済み6 ID、timestamp、metadata、record、owned_suffix Event Log membershipを再利用し、fresh ID/timestamp、factory、Provider、Dice、prepare、stage、`stage_recovery_metadata()`を再実行しない。各`execute()`呼出しはdurable claimを正確に一回行い、`recover_processing()`はclaimを呼ばない。response rebuild failureならprocessingを残して同key retryを許可する。metadata確定 → recovery/normal Event append（recovery abortもexecuteの同じcallsite）→全Event read / selector → Coordinator-only rebuilder → response/statusだけのcompleteという順序を固定する。

state machineのpre/post-append境界は次の表で固定する。表の回数は全て「そのexecute呼出し内」の`append / rebuild / complete`であり、`recover_processing`自身の回数は常に0である。初回normal executionは`NewClaim`でcandidateをappendする呼出し、crash後の再試行は`ExistingProcessingClaim`でcandidateなしの呼出しとして別に数える。`record`の予約IDだけではterminalを推測せず、`prefix origin`は`prefix`から、`current identity一致のowned_suffix actual Event ID`は`owned_suffix`またはauthorized candidateからだけ確定する。prefixにある以前のTurnを現在requestのowned Eventとみなさない。 表の`ExistingProcessingClaim`行はdurable claim 1回・processing INSERT 0、`NewClaim`行はdurable claim 1回・processing INSERT 1とし、candidateありの行とcandidateなしの行を明示する。CAS後append前crashはその試行のcandidateをappendせず、正常完走・recovery abort初回はcandidateを一度appendする。

| state（そのexecute呼出し内） | `record.status` | version / payload選択 | prefix origin / current identity一致のowned_suffix actual Event ID | 次の操作 | append / rebuild / complete |
|---|---|---|---|---|---:|
| metadata未確定（通常継続） | `processing` | v1 / `initial_recovery_payload`（entry時の6 IDはNULL） | prefix originだけを観測し、owned_suffix terminalはまだない | durable claim（1） → ExistingProcessingClaim（INSERT 0） → `recover_processing` → `RecoveryMetadataFactory` / `stage_recovery_metadata` CAS（1） → recovery candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| metadata CAS後append前crash（partial failed attempt） | `processing`保持 | CAS済みv1またはv2、保存済みpayload/6 ID | prefix originは保存済み、current identity一致のowned_suffix terminal actualなし。candidateは準備済みだが未append | durable claim（1） → ExistingProcessingClaim（INSERT 0） → `recover_processing`（metadata再CAS 0） → candidate validation後のfault injectionでappend前停止。結果を返さずprocessingを保持し、次回executeが同じmetadataを再利用 | 0 / 0 / 0 |
| metadata確定 / submit / current prefixにidentity一致の`PlayerInputAccepted`なし / current owned_suffixにaccepted・terminalなし | `processing` → final `aborted` | versionに関係なくrecovery abortはinitial | 過去の別turn Eventは無関係。current identity一致のprefixにacceptedなし、current identity一致のowned_suffixにowned Eventなし。candidateは`PlayerInputAccepted -> recovery TurnAborted` | durable claim（1） → ExistingProcessingClaim（INSERT 0） → `recover_processing` → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| metadata確定 / resume / current prefixにidentity一致のacceptedまたはawaitingあり / current owned_suffixに`TurnResumed`・terminalなし | `processing` → final `aborted` | versionに関係なくrecovery abortはinitial | current identity一致のprefixのaccepted/awaiting IDを検証して再利用し、current identity一致のowned_suffixにowned Eventなし。candidateはrecovery `TurnAborted`だけ | durable claim（1） → ExistingProcessingClaim（INSERT 0） → `recover_processing` → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete。prefixを再appendせず、二つ目の`PlayerInputAccepted`を作らない | 1 / 1 / 1 |
| 初回normal execution: committed | `processing` → final `committed` | v2 / staged outer payload必須。v1 / initialのみ、またはstaged outer payload欠落は`recovery_identity_mismatch` | current identity一致のowned_suffix actual `committed_event_id`。未使用の`recovery_aborted_event_id`は不在でもよい | durable claim（1; processing INSERT 1） → `NewClaim` → candidateあり → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| 初回normal execution: normal aborted | `processing` → final `aborted` | v2 / staged outer payload必須。v1 / initialのみ、またはstaged outer payload欠落は`recovery_identity_mismatch` | current identity一致のowned_suffix actual normal `aborted_event_id`。未使用の`recovery_aborted_event_id`は不在でもよい | durable claim（1; processing INSERT 1） → `NewClaim` → candidateあり → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| 初回normal execution: awaiting_player | `processing` → final `awaiting_player` | v2ならstaged outer payload、v2がない場合だけv1 initial outer bytes + P1-08適用のtyped presentation default（`narrative=()`、`suggested_actions=()`、`cost_microusd=0`、`processing_status="done"`、`corrections=()`） | current identity一致のowned_suffix actual `awaiting_player_event_id`（terminal IDはなし）。未使用のterminal予約IDは不在でもよい | durable claim（1; processing INSERT 1） → `NewClaim` → candidateあり → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| normal committed append後〜complete前の再試行 | `processing` → final `committed` | v2 / staged outer payload必須。v1 / initialのみ、またはstaged outer payload欠落は`recovery_identity_mismatch` | current identity一致のowned_suffix actual `committed_event_id` | durable claim（1; processing INSERT 0） → `ExistingProcessingClaim` → `RecoveryPlan(candidate_batch=None)` → campaign全体を再read/select → ResponseRebuilder → complete。normal Eventを二重appendしない | 0 / 1 / 1 |
| normal aborted append後〜complete前の再試行 | `processing` → final `aborted` | v2 / staged outer payload必須。v1 / initialのみ、またはstaged outer payload欠落は`recovery_identity_mismatch` | current identity一致のowned_suffix actual normal `aborted_event_id` | durable claim（1; processing INSERT 0） → `ExistingProcessingClaim` → `RecoveryPlan(candidate_batch=None)` → campaign全体を再read/select → ResponseRebuilder → complete。normal Eventを二重appendしない | 0 / 1 / 1 |
| awaiting_player append後〜complete前の再試行 | `processing` → final `awaiting_player` | v2ならstaged outer payload、v2がない場合だけv1 initial outer bytes + P1-08適用のtyped presentation default（`narrative=()`、`suggested_actions=()`、`cost_microusd=0`、`processing_status="done"`、`corrections=()`） | current identity一致のowned_suffix actual `awaiting_player_event_id`（terminal IDはなし） | durable claim（1; processing INSERT 0） → `ExistingProcessingClaim` → `RecoveryPlan(candidate_batch=None)` → campaign全体を再read/select → ResponseRebuilder → complete。awaiting Eventを二重appendしない | 0 / 1 / 1 |
| 初回recovery abort append | `processing` → final `aborted` | versionに関係なくinitial | current identity一致のowned_suffix actual recovery `recovery_aborted_event_id`（normal `aborted_event_id`とは別） | durable claim（1; processing INSERT 0） → ExistingProcessingClaim → candidateあり → `RecoveryPlan` → candidate validation → executeの既存append callsite → campaign全体を再read/select → ResponseRebuilder → complete | 1 / 1 / 1 |
| recovery abort append後〜complete前の再試行 | `processing` → final `aborted` | versionに関係なくinitial | Event Log上のcurrent identity一致のowned_suffix actual `recovery_aborted_event_id` | durable claim（1; processing INSERT 0） → ExistingProcessingClaim → `RecoveryPlan(candidate_batch=None)` → stored metadataとactual Eventを再read/select → ResponseRebuilder → complete。recovery abortを二重appendしない | 0 / 1 / 1 |

current identity一致の`owned_suffix` actual `committed_event_id`またはnormal `aborted_event_id`が見つかった場合、`select_response_payload()`はversion 2のstaged outer payloadだけを受け付ける。version 1 / initialのみ、staged outer欠落は`recovery_identity_mismatch`へfail-closedにし、normal committed / normal abortedをv1 payloadで完了させる経路は作らない。current identity一致の`owned_suffix` actual `awaiting_player_event_id`ではversion 2のstaged outer payloadを優先し、v2が無い場合だけversion 1のinitial outer bytes（typed presentation defaultはP1-08がstrict decode後に適用）を使う。current identity一致の`owned_suffix` actual `recovery_aborted_event_id`が見つかった場合はversionに関係なくinitialを選ぶ。current identity一致の`owned_suffix`にactual terminal/recovery IDがまだない段階でrecordだけからterminalを推測せず、Event Logのcurrent identity一致の`owned_suffix`に存在するlifecycle Eventは同一roleの非NULL予約IDとtype/context/canonical requestまで完全一致するsubsetであることを要求する。未使用の予約IDは不在を許可し、current identity一致の`owned_suffix`のnormal terminal actualとrecovery-aborted actualの同時存在、role違いのID再利用、非NULL予約IDとactual Eventのtype/context/canonical request不一致、予約外actual Eventは`StoreError(code="recovery_identity_mismatch")`へfail-closedにする。inner seedのidentity/media不一致はP1-08のstrict decode時だけ検証し、P1-03 selectorは検証しない。origin `recovery_selector`と現在状態selectorの単純一致は要求しない。

`recovery_selector`はmetadata CAS時点にvalidated Event Logから観測したorigin selectorであり、CAS成功後もappend後も書き換えないimmutable fieldとする。現在状態はvalidated full Event Logをprefix/suffixに分けたうちcurrent identity一致のowned_suffixのactual owned-event membershipだけから導出し、origin selectorと現在状態selectorが同値であることは要求しない。`select_response_payload(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> StrictBytes`だけがcurrent identity一致のowned_suffix actual membership、role、type、context、canonical request、versionを検証してpayload bytesを選ぶ唯一の関数/authorityであり、`RecoveryPlan`や別のbooleanからpayloadを選ばない。

ここでのrole / type / context / canonical request検証はvalidated Eventのowned membershipを確認するためだけに行い、保存payloadのouter/innerをdecodeしたり、そのidentity・media・strict UTF-8・secretを検証したりする意味ではない。P1-03 selectorとStoreは常にopaque outer bytesを返し、payload validationはP1-08だけが行う。

origin selectorごとの許可遷移は次の表で固定する。各rowのoriginはCAS時点の値であり、表中の`current identity一致のowned_suffix actual membership`は`matches_current_turn_identity()`に一致するEventだけをその後のvalidated Event Logから、prefixとは分離して再判定した結果を指す。過去の別turnがprefixにあってもこのcurrent-turn判定へ入れない。

| origin `recovery_selector` | current identity一致のowned-suffix actual owned-event membershipからの許可遷移（`RecoveryPlan.state` / candidate / payload） |
|---|---|
| `no_lifecycle_events` | current identity一致のowned_suffix terminal actualがなく`awaiting_player_event_id`もない場合は`recovery_abort` / recovery-abort candidateあり / `select_response_payload`がinitialを選ぶ。current identity一致のowned_suffix awaiting actualなら`awaiting_player` / candidateなし / v2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped defaultを選ぶ。owned_suffix normal `committed_event_id`またはnormal `aborted_event_id` actualなら`normal_terminal` / candidateなし / v2 staged outer payload必須（v1 / initialのみはerror）。owned_suffix `recovery_aborted_event_id` actualなら`recovery_abort` / candidateなし / versionに関係なくinitial。owned_suffix normal/recovery actual同時、role/context/type/canonical request mismatch、予約外actualはerror。 |
| `accepted_without_terminal` | current identity一致のowned_suffix terminal actualがなく`awaiting_player_event_id`もない場合は`recovery_abort` / recovery-abort candidateあり / initial。current identity一致のowned_suffix awaiting actualなら`awaiting_player` / candidateなし / v2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped default。owned_suffix normal `committed_event_id`またはnormal `aborted_event_id` actualなら`normal_terminal` / candidateなし / v2 staged outer payload必須（v1 / initialのみはerror）。owned_suffix `recovery_aborted_event_id` actualなら`recovery_abort` / candidateなし / versionに関係なくinitial。owned_suffix normal/recovery actual同時、role/context/type/canonical request mismatch、予約外actualはerror。 |
| `resumed_without_terminal` | current identity一致のowned_suffix terminal actualがなく`awaiting_player_event_id`もない場合は`recovery_abort` / recovery-abort candidateあり / initial。current identity一致のowned_suffix awaiting actualなら`awaiting_player` / candidateなし / v2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped default。owned_suffix normal `committed_event_id`またはnormal `aborted_event_id` actualなら`normal_terminal` / candidateなし / v2 staged outer payload必須（v1 / initialのみはerror）。owned_suffix `recovery_aborted_event_id` actualなら`recovery_abort` / candidateなし / versionに関係なくinitial。owned_suffix normal/recovery actual同時、role/context/type/canonical request mismatch、予約外actualはerror。 |
| `awaiting_player` | current identity一致のowned_suffix terminal actualがなく`awaiting_player_event_id`もない場合は`recovery_abort` / recovery-abort candidateあり / initial。current identity一致のowned_suffix awaiting actualなら`awaiting_player` / candidateなし / v2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped default。owned_suffix normal `committed_event_id`またはnormal `aborted_event_id` actualなら`normal_terminal` / candidateなし / v2 staged outer payload必須（v1 / initialのみはerror）。owned_suffix `recovery_aborted_event_id` actualなら`recovery_abort` / candidateなし / versionに関係なくinitial。owned_suffix normal/recovery actual同時、role/context/type/canonical request mismatch、予約外actualはerror。 |
| `terminal` | current identity一致のowned_suffix terminal actualがなく`awaiting_player_event_id`もない場合は`recovery_abort` / recovery-abort candidateあり / initial。current identity一致のowned_suffix awaiting actualなら`awaiting_player` / candidateなし / v2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped default。owned_suffix normal `committed_event_id`またはnormal `aborted_event_id` actualなら`normal_terminal` / candidateなし / v2 staged outer payload必須（v1 / initialのみはerror）。owned_suffix `recovery_aborted_event_id` actualなら`recovery_abort` / candidateなし / versionに関係なくinitial。owned_suffix normal/recovery actual同時、role/context/type/canonical request mismatch、予約外actualはerror。 |

recovery-abort candidateは`owned_suffix`の`recovery_aborted_event_id`だけをrecovery roleで使い、normal `aborted_event_id`を流用しない。current identity一致のowned_suffix actual normal committed / normal abortedではv2 staged outer payloadを`select_response_payload()`が必須として選び、v1 / initialのみは固定errorにする。current identity一致のowned_suffix actual recovery-abortedではversionに関係なくinitialを選ぶ。awaiting actualではv2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped presentation defaultを選ぶ。未使用の`recovery_aborted_event_id`予約が残っていてもnormal terminalのpayload選択を妨げず、recordの予約IDだけではterminalを確定しない。

`select_latest_committed_turn(campaign_events)`はCampaign全体の最大sequenceを先に見てから、global latestの`TurnCommittedEvent`を一つ選ぶ。先にsession filterを適用せず、選択結果の`session_id`が`UndoCommand.session_id`と異なる場合は古いTurnへfallbackせず`turn_not_in_session`として安全に拒否する。

`TurnEngine.undo_latest(command: UndoCommand) -> UndoResult`は`TurnLifecycleCoordinator.revert_latest(command=command) -> UndoResult`へ委譲する。`revert_latest()`は同じ`event_boundary_lock`閉区間で、(1)`TurnRequestStore.read_processing(campaign_id=command.campaign_id)`を先に読むcampaign-scoped durable guard、(2)processing rowがあれば`UndoBlockedResult(type="blocked", http_status_code=409, code="turn_already_processing", response=None)`を返してundo selectorへ進まない、(3)rowがなければcampaign全体のvalidated `DomainEvent` full history、status、targetを一度だけ読み、campaign/session/scene/turn/canonical `turn_request_id`/`root_turn_request_id`の同一identity tupleから対象候補を導出する、(4)coordinatorだけが`derive_revert_event_id(campaign_id=command.campaign_id, request_key=command.request_key)`を一度だけ計算する、(5)derived IDで既存`TurnReverted`をlookupする、(6)campaign/session/target/context/origin/visibility/payloadの全contextが完全一致する既存Revertなら、full campaign Event列・status・target・derived IDを`UndoResponseRebuilder`へ一回渡してresponseを再構築し、append=0 / rebuild=1で返す、同じIDでもcontextが異なれば`StoreError(code="undo_conflict")`、(7)ID不存在時だけCampaign全体の最大sequenceを先に見てglobal latest committed Turnをselectorで一つ選び、session mismatchで古いTurnへfallbackせず`StoreError(code="turn_not_in_session")`、(8)full candidate validation → EventStore.append一回 → campaign全体再read / `UndoResponseRebuilder`一回、の順で固定する。`UndoResponseRebuilder(command, campaign_events, status, target_turn_id, revert_event_id)`にはcoordinatorがderive済みIDとselector済みtargetを一度だけ渡し、rebuilderはID再derive・latest再selector・append・request cache更新を行わない。既存matching Revertのrebuildが失敗した場合はEvent追加なし（append=0）のままsanitized errorを返し、同じtargetへのretryを許可する。rebuild failure後、後続Turn後、clock進行後のretryも元targetに対するappendを0件、rebuildを1件とし、既存Revertを全context一致で再利用する。UndoはEvent削除でもTelemetry費用のrollbackでもなく、`TurnReverted`をappendしてProjectionから対象Turnのeffectを除外する。Undoは`turn_requests`のclaim、stage、complete、cacheを使わず、通常Turnのresponse cache経路にも入らない。通常のsame-key request identity readは`TurnRequestStore.read(*, request_key=...)`または既存claim recordを使い、campaign-scoped `read_processing()`と混同しない。別campaignの同じrequest keyはundo durable guardの対象にせず、誤反応させない。成功戻り値は`RevertedTurnResult(target_turn_id, revert_event_id, response)`、processing guardの戻り値は`UndoBlockedResult`、その他のsanitized conflict/errorは`StoreError`とする。

`derive_revert_event_id`はtrim、casefold、Unicode normalize、`hash()`、clockを使わず、campaign IDをUTF-8 bytes、opaque request keyをそのままbytesとして扱う。SHA-256 preimageは次で固定する。

```python
campaign_bytes = str(campaign_id).encode("utf-8")
request_key_bytes = bytes(request_key)
preimage = (
    b"NEONTOF:TURN-REVERT:v1\0"
    + str(len(campaign_bytes)).encode("ascii")
    + b":"
    + campaign_bytes
    + b"\0"
    + str(len(request_key_bytes)).encode("ascii")
    + b":"
    + request_key_bytes
)
return EventId("event:" + hashlib.sha256(preimage).hexdigest())
```

KATは次の三つを固定し、実装が入力のtrim/casefold/normalizeや現在時刻に依存しないことを確認する。

```text
campaign:alpha + idem-v1-alpha = event:2d0292a9b4ed5d419b02934e39d9a3665b7218609d3a8372036fcb2021d9f424
campaign:beta + idem-v1-alpha = event:6c20c0f38ed22254404d1a18a8e07544ad7e33769b57a0eee3509875f15a002e
campaign:alpha + 再送-α = event:7eb0347547f6c03c11173ef6b5ddac520b9ac46cfe6f7274215946c5adbe31c8
```

Observationはゲーム状態transactionの外にあり、`TurnRequestStore`のclaim、Event append、completeと同じtransactionへ混ぜない。`tests/integration/test_failed_turn_observations.py`は既存skip testのModifyであり、P1-03ではinjected `prepare`内のplayer input Transcript / Telemetry appendと、その後のEvent append failureだけを検証する。Eventが0件でもplayer input transcript、telemetry、costは保持する。model request / response / Provider observationはP1-08へ移し、P1-03へ戻さない。P1-03のobservation testはProvider、Model、Diceの実行や観測を含めない。

### テストファースト（Store / schema / coordinator / idempotency / recovery / undo / observation）

- `test_new_request_is_claimed_once`
- `test_duplicate_processing_request_returns_existing_record`
- `test_request_key_is_database_wide_and_opaque`
- `test_request_key_conflict_compares_full_identity`
- `test_request_key_conflict_is_sanitized_and_does_not_return_cached_body`
- `test_request_key_conflict_does_not_expose_identity_or_cached_body`
- `test_existing_claim_compares_only_immutable_identity_not_current_base_sequence`
- `test_same_key_final_replay_is_byte_for_byte_and_never_conflicts`
- `test_request_key_is_blob_between_one_and_256_bytes`
- `test_canonical_turn_request_id_is_campaign_scoped`
- `test_claim_selects_campaign_processing_row_on_same_write_connection`
- `test_claim_is_called_only_inside_coordinator_event_boundary_lock`
- `test_claim_result_distinguishes_new_processing_and_final_branches`
- `test_preclaim_intent_has_no_caller_supplied_base_sequence_or_staged_payload`
- `test_base_event_sequence_is_derived_from_full_campaign_read`
- `test_resume_with_prior_campaign_events_partitions_prefix_and_owned_suffix`
- `test_campaign_processing_partial_unique_maps_to_turn_already_processing`
- `test_integrity_errors_map_to_fixed_store_codes_without_sqlite_message`
- `test_recovery_payload_version_and_identity_mismatch_is_fixed_error`
- `test_request_record_persists_requested_media_type_and_base_sequence`
- `test_processing_and_final_records_persist_recovery_version_and_metadata`
- `test_stage_recovery_metadata_is_one_time_cas_and_same_metadata_is_idempotent`
- `test_stage_recovery_metadata_conflict_is_sanitized_and_does_not_change_payload`
- `test_recovery_reason_selector_event_ids_and_timestamp_are_durable`
- `test_recovery_event_id_source_is_deterministic_and_role_scoped_without_event_store_capture`
- `test_recovery_metadata_factory_receives_occurred_at_and_reservation_once`
- `test_saved_recovery_metadata_does_not_reinvoke_clock_id_source_or_factory`
- `test_recovery_metadata_shape_matches_sql_record_and_event_ids_are_memory_derived`
- `test_recovery_builder_reuses_all_stored_metadata_without_fresh_ids_or_timestamp`
- `test_turn_event_batch_factory_receives_identity_prepared_turn_utc_time_event_id_sequence_and_campaign_events`
- `test_turn_event_batch_factory_cannot_infer_origin_selector_without_campaign_events`
- `test_turn_event_batch_factory_is_only_post_id_event_batch_constructor`
- `test_duplicate_committed_request_returns_cached_response`
- `test_cached_response_replays_status_media_type_and_body_exactly`
- `test_cached_response_body_is_non_empty_and_media_bound`
- `test_cached_response_rejects_invalid_utf8_before_complete`
- `test_valid_japanese_response_is_strict_utf8_and_completes`
- `test_cached_response_replays_valid_utf8_bytes_byte_for_byte`
- `test_complete_missing_request_raises_request_not_found`
- `test_complete_non_processing_raises_safe_error`
- `test_complete_same_response_is_idempotent`
- `test_complete_conflicting_response_raises_response_conflict`
- `test_complete_updates_only_status_and_response_with_immutable_identity_and_recovery`
- `test_stage_is_compare_and_set_and_moves_recovery_payload_version_one_to_two`
- `test_stage_rejects_lost_update_without_partial_write`
- `test_read_processing_survives_process_restart`
- `test_read_processing_is_campaign_scoped_and_returns_at_most_one_row`
- `test_processing_record_cannot_carry_response`
- `test_complete_cannot_accept_processing_status`
- `test_submit_emits_player_input_accepted_then_turn_resumed_then_terminal`
- `test_resume_emits_turn_resumed_then_terminal`
- `test_ambiguous_input_enters_awaiting_player_without_effect_events`
- `test_resume_uses_same_turn_id`
- `test_resume_uses_same_canonical_turn_request_id`
- `test_resume_uses_new_request_key_for_same_canonical_request`
- `test_resume_does_not_append_second_player_input_accepted`
- `test_build_resumed_event_emits_only_turn_resumed`
- `test_resume_context_is_validated_inside_claim_transaction`
- `test_full_candidate_validation_runs_status_and_projection_before_append`
- `test_turn_preparation_receives_full_campaign_events_before_projection_and_materialization`
- `test_coordinator_invokes_only_injected_prepare_without_turn_engine_dependency`
- `test_turn_event_batch_factory_is_only_post_id_event_batch_constructor`
- `test_turn_event_factory_appends_session_ended_after_committed_when_scenario_end_is_set`
- `test_non_committed_effects_are_rejected_before_append`
- `test_projection_rebuild_and_claim_have_two_same_connection_readers`
- `test_p1_03_has_only_execute_and_revert_append_callsites`
- `test_recover_processing_returns_recovery_plan_without_append_rebuild_or_complete`
- `test_coordinator_calls_response_rebuilder_and_complete_once`
- `test_coordinator_validates_cached_response_and_completes_once_after_rebuild`
- `test_active_turn_registry_try_acquire_returns_owned_or_existing_with_immutable_intent_and_token`
- `test_existing_active_returns_processing_without_boundary_lock_or_claim`
- `test_owned_active_acquires_boundary_then_claims`
- `test_same_key_active_identity_conflict_is_request_key_conflict`
- `test_different_key_active_conflict_is_turn_already_processing`
- `test_owned_request_holds_boundary_until_complete`
- `test_active_processing_replay_only_returns_processing_response`
- `test_registry_miss_uses_durable_claim_after_restart`
- `test_registry_miss_existing_processing_claim_enters_recovery_without_reexecution`
- `test_persisted_processing_recovery_reuses_durable_metadata_once`
- `test_active_processing_barrier_does_not_recover_or_duplicate_work`
- `test_undo_processing_guard_returns_fixed_409_blocked_result`
- `test_coordinator_releases_registry_and_boundary_lock_on_prepare_failure`
- `test_coordinator_releases_registry_and_boundary_lock_on_append_failure`
- `test_coordinator_releases_registry_and_boundary_lock_on_rebuild_or_complete_failure`
- `test_submit_claim_before_first_event_recovers_with_accepted_then_aborted_batch`
- `test_prior_completed_turn_in_prefix_does_not_identify_current_submit_before_first_append`
- `test_resume_claim_before_first_owned_event_appends_only_recovery_abort`
- `test_crash_after_player_input_accepted_appends_only_authorized_abort`
- `test_crash_after_turn_resumed_uses_event_derived_running_status`
- `test_crash_after_terminal_replays_terminal_without_append`
- `test_normal_committed_append_crash_retries_with_zero_append_one_rebuild_one_complete`
- `test_normal_aborted_append_crash_retries_with_zero_append_one_rebuild_one_complete`
- `test_awaiting_player_append_crash_retries_with_zero_append_one_rebuild_one_complete`
- `test_crash_after_awaiting_player_rebuilds_awaiting_response`
- `test_recovery_uses_existing_turn_status_parser_order`
- `test_processing_replay_with_committed_event_caches_rebuilt_response`
- `test_prepared_turn_rejects_terminal_without_v2_staged_recovery_payload`
- `test_select_response_payload_returns_opaque_outer_bytes_without_decoding`
- `test_prepared_turn_scenario_end_is_materialized_only_by_turn_event_factory`
- `test_payload_stage_before_append_crash_preserves_version_and_reuses_staged_payload`
- `test_recovery_abort_uses_initial_payload_after_metadata_stage`
- `test_metadata_stage_before_append_crash_sets_deterministic_metadata_then_recovers_abort`
- `test_metadata_cas_continues_to_recovery_abort_in_same_execute`
- `test_recovery_abort_append_before_complete_crash_retries_without_append`
- `test_recovery_aborted_event_id_is_distinct_from_normal_aborted_event_id`
- `test_recovery_metadata_reserves_recovery_abort_id_without_event_membership`
- `test_recovery_abort_double_crash_reuses_actual_id_without_append`
- `test_normal_terminal_and_recovery_abort_actual_ids_fail_closed`
- `test_response_rebuild_failure_keeps_processing_for_same_key_retry`
- `test_latest_committed_turn_can_be_reverted`
- `test_non_latest_turn_cannot_be_reverted`
- `test_session_mismatch_does_not_fallback_to_an_older_turn`
- `test_global_latest_committed_turn_is_selected_before_session_check`
- `test_existing_revert_requires_full_context_match`
- `test_revert_derives_event_id_once`
- `test_revert_event_id_known_answer_vectors`
- `test_revert_reads_validates_appends_and_rebuilds_under_one_boundary_lock`
- `test_existing_revert_replays_response_with_zero_append_and_one_rebuild`
- `test_existing_revert_response_rebuild_failure_keeps_event_log_and_allows_retry`
- `test_undo_does_not_claim_stage_complete_or_cache`
- `test_undo_retry_after_rebuild_later_turn_and_clock_has_zero_append_and_one_rebuild`
- `test_undo_reads_campaign_processing_guard_before_full_event_read`
- `test_undo_processing_guard_does_not_match_same_key_in_other_campaign`
- `test_undo_normal_same_key_read_uses_request_key_not_campaign_guard`
- `test_injected_prepare_failure_preserves_player_input_observations_when_event_append_fails`
- `test_observation_append_is_outside_event_append_critical_section`
- `test_migration_0004_creates_only_turn_requests`
- `test_turn_requests_schema_has_identity_response_and_status_constraints`
- `test_schema_set_maximum_is_four_without_gap_or_unknown_version`

`test_resume_with_prior_campaign_events_partitions_prefix_and_owned_suffix`は、以前のTurnがあるcampaignでNewClaimの一つのclaim transactionがfull validated readから`base_event_sequence = COALESCE(MAX(sequence), 0)`を保存し、registry miss / restart後の`recover_processing()`が`prefix = {event | sequence <= record.base_event_sequence}`と`owned_suffix = {event | sequence > record.base_event_sequence}`を分けることを確認する。current identityに一致しないprefixの`PlayerInputAccepted` / `TurnAwaitingPlayer`だけではcurrent requestをcompleteせず、owned_suffixの`TurnResumed`とterminalだけを一度処理し、ExistingProcessingClaimでbaseを再導出・現在MAX比較しない。これは`test_registry_miss_uses_durable_claim_after_restart`（registry empty、durable processing row、durable claim `1`、processing INSERT `0`、保存base不変）と同じresumeケースで固定する。

`test_prior_completed_turn_in_prefix_does_not_identify_current_submit_before_first_append`は、過去に完了した別turnの`PlayerInputAccepted`がprefixに存在するcampaignで、現在のsubmit recordのEvent envelope（`campaign_id`、`session_id`、`scene_id`、`turn_id`）とaccepted payloadのcanonical `turn_request_id`、current submitの`input_digest`に一致するEventがprefixにもowned suffixにもない状態を作り、過去Eventだけではcurrent submitをresume扱い・completeしないことを確認する。current identityに一致するPlayerInputAcceptedがなくowned Eventもないため、候補は現在recordの`accepted_event_id`による`PlayerInputAccepted -> recovery TurnAborted`となり、過去turnのacceptedを再利用しない。Eventに存在しない`root_turn_request_id`を比較せず、recordのroot/canonical relationshipはclaim時に検証する。

`test_turn_preparation_receives_full_campaign_events_before_projection_and_materialization`は、NewClaim後の同じ`event_boundary_lock`内で`EventStore.read_campaign(record.campaign_id)`を一度だけ先に実行し、その完全なvalidated `tuple[DomainEvent, ...]`を注入済みの`prepare: TurnPreparation`へ渡し、`prepare(identity, campaign_events)`を一回呼ぶことを確認する。`TurnPreparation`は受け取ったtupleから`rebuild_projection(campaign_events)`とEvent-derived contextを作り、closureのimmutable input context、既存active target/conditionのFactId、target/condition candidateを`event_id_sequence`より前に確定する。factory用readをprepare後に遅延させず、`event_id_sequence(identity, prepared)`は最終`effect_candidates`確定後にだけ一度呼ぶ。campaign eventsなしのcallback、instance field/Transcriptからのinput補完、後から作ったProjection/contextでのmaterializationは契約違反とする。

`test_turn_event_batch_factory_receives_identity_prepared_turn_utc_time_event_id_sequence_and_campaign_events`は、NewClaim後に同じ`event_boundary_lock`内で明示的に取得した`EventStore.read_campaign(record.campaign_id)`のfull validated tupleを、`TurnRequestIdentity`、`PreparedTurn`、UTC `OccurredAt`、event ID sequenceとともにnormal `TurnEventBatchFactory`へ渡すことを確認する。factoryはcampaign eventsなしでorigin selector/statusを推測できず、全role共通のenvelope、lifecycle payloadのcanonical ID、submit accepted anchorだけの`input_digest`、record-levelのroot/canonical relationshipという境界を守る。resumeの新しい`input_digest`をprefix acceptedやresume/awaiting/terminal payloadへ比較しない。`test_turn_event_batch_factory_cannot_infer_origin_selector_without_campaign_events`はcampaign eventsを渡さずにorigin selector/statusを推測できないこと、factoryがEventStoreをcaptureしないこと、`RecoveryMetadataFactory(record, campaign_events, inputs)`が別経路のexact三引数であること、`RecoveryMetadataInputs(occurred_at=..., reservation=...)`をnormal factoryが受け取らないことを確認する。claim transaction内のsame-connection `_read_campaign_on_connection(connection, campaign_id)`はこのfactory用readと混同しない。
`test_turn_event_batch_factory_is_only_post_id_event_batch_constructor`は、pre-ID materializerと注入済みの`prepare` callbackが`PreparedEffect`列だけを返して`event_id` / `occurred_at`を持つ`EventDraftBody`、`EventDraft`、`EventBatch`を作らず、最終`effect_candidates`、`event_id_sequence`、UTC `OccurredAt`の後にnormal `TurnEventBatchFactory`だけがpost-ID batchを構成することを確認する。candidate validationへ渡るまでEventDraft/EventBatchを保持するP1-03 symbolが存在しないことをassertし、consecutive target supersede/replayのcandidate順もこの境界で検証する。

`test_resume_claim_before_first_owned_event_appends_only_recovery_abort`は、以前のcampaign Eventとawaiting prefixがあるresumeのExistingProcessingClaimで、current identityに一致するprefixの`PlayerInputAccepted` / `TurnAwaitingPlayer`を再appendせず、`recovery_aborted_event_id`のrecovery `TurnAborted`だけをauthorized candidateにすることを確認する。current identityに一致するaccepted/terminalがないsubmitケースは`test_submit_claim_before_first_event_recovers_with_accepted_then_aborted_batch`で別に検証し、resumeでは二つ目の`PlayerInputAccepted`を作らない。

`test_metadata_cas_continues_to_recovery_abort_in_same_execute`はfaultなしでmetadata未確定のprocessingからdurable claim `1`、metadata CAS `1`、recovery candidate、executeの既存append、reread/select、rebuild、completeまでを同一execute呼出し内で完走し、append / rebuild / complete `1 / 1 / 1`を確認する。`test_metadata_stage_before_append_crash_sets_deterministic_metadata_then_recovers_abort`はCAS後append前のpartial failed attemptだけを別に扱い、その試行は`0 / 0 / 0`で結果なし・processing保持、次回executeが保存metadataを再利用してrecovery abortを`1 / 1 / 1`で完了することを確認する。

P1-03のnamed testsはStore/schema/coordinator/idempotency/recovery/undo/observationのcontract/danger-zone検証だけに限定し、Model request / response / Provider / Diceのcall countまたはpayload検証を含めない。それらはP1-08の契約とtestsで扱う。

`test_recovery_metadata_shape_matches_sql_record_and_event_ids_are_memory_derived`はSQL / record / metadataの6個のID shape、同一roleのcurrent identity一致のowned_suffix actual Eventとのtype/context/canonical request一致、未使用予約IDの不在許可を確認する。`test_payload_stage_before_append_crash_preserves_version_and_reuses_staged_payload`はstage済みversion `2`と`staged_recovery_payload`を不変にし、`test_recovery_abort_uses_initial_payload_after_metadata_stage`はversionに関係なくinitial payloadと保存済み`recovery_aborted_event_id`を選ぶ。`test_recovery_abort_append_before_complete_crash_retries_without_append`は二重crash後にowned_suffix Event Log actual IDを根拠としてappend `0` / rebuild `1` / complete `1`を確認し、`test_recovery_aborted_event_id_is_distinct_from_normal_aborted_event_id`はnormal `aborted_event_id`をrecovery abortへ流用しないことを確認する。`test_recovery_metadata_reserves_recovery_abort_id_without_event_membership`は未使用の予約IDだけでterminalを確定せず、normal terminal完了時の未使用`recovery_aborted_event_id`を許容すること、`test_normal_terminal_and_recovery_abort_actual_ids_fail_closed`は両actualの同時存在を`recovery_identity_mismatch`へ写像することを確認する。各normal terminalのappend後crash再試行は`test_normal_committed_append_crash_retries_with_zero_append_one_rebuild_one_complete`、`test_normal_aborted_append_crash_retries_with_zero_append_one_rebuild_one_complete`、`test_awaiting_player_append_crash_retries_with_zero_append_one_rebuild_one_complete`でappend `0` / rebuild `1` / complete `1`と二重appendなしを確認する。metadata stage前crashではmetadata未確定のprocessingを保持し、recordにないEventを推測しない。

`test_prepared_turn_rejects_terminal_without_v2_staged_recovery_payload`は`terminal_status`が`committed`または`aborted`の`PreparedTurn`で`staged_recovery_payload=None`を拒否し、`awaiting_player`だけがv1 initial outer bytes + P1-08適用のtyped defaultを許可することを確認する。`test_select_response_payload_returns_opaque_outer_bytes_without_decoding`はP1-03 selectorがEvent membership、DB version、NULL stateだけから保存済みouter bytesを選び、outer/inner decode、identity/media/UTF-8/secret validationを行わないことを確認する。outer/innerのstrict decodeとidentity/media validationはP1-08の`ResponseDocumentBuilder` / `ResponseRebuilder`に限定する。

### RED / GREEN command

PersistenceのREDは、次のfocused commandでmissing module、`0004_turn_requests.sql`のschema-set assertion、manifest追記漏れ、request key / partial UNIQUE / CHECKの固定code写像のfailureを確認する。実装前の期待exitは非0であり、collection errorまたは対象assertion failureを含む。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_turn_request_store.py tests/test_repository_contracts.py -q
```

PersistenceのGREENは同じcommandで、`0004` schema-set、Store型不変条件、same-connection claim、IntegrityErrorのsanitized code、repository guardがfailure `0`になることを確認する。

LifecycleのREDは、次のfocused commandでmissing coordinator、Event順序、candidate validation、lock/finally、recovery / undo、injected observation failureのfailureを確認する。実装前の期待exitは非0であり、collection errorまたは対象assertion failureを含む。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_turn_lifecycle.py tests/integration/test_turn_idempotency.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py -q
```

LifecycleのGREENは同じcommandで、submit / resumeのEvent順序、full candidate validation、non-committed effects拒否、registry / boundary lock解放、campaign-wide recovery / undo、player input observation retentionがfailure `0`になることを確認する。P1-03のGREENではModel request / response / Provider / Diceを実行しない。

P1-03のfocused integration commandはPersistenceとLifecycleの両laneが揃った後に一度実行する。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_turn_request_store.py tests/application/test_turn_lifecycle.py tests/integration/test_turn_idempotency.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py -q
```

期待する出力はcollection error・failure・errorがなく、`passed`を含むexit `0`である。P1-03のfocused commandはModel request / response / Provider / Diceを起動しない。

P1-03のfull quality commandは`compileall`、計画全体のpytest、ruff、mypyを分けて実行する。

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
```

五つともexit `0`、compileallは構文エラーなし、pytestはfailure/error `0`、ruff formatは`files already formatted`、ruff checkは`All checks passed!`、mypyは`Success: no issues found`を期待する。いずれかが失敗した場合はP1-03のcommit境界を閉じず、未確認をGREENと扱わない。

### 完了条件

- `0004_turn_requests.sql`が`turn_requests`だけをadditiveに作り、1..256 bytesのBLOB `request_key` DB-wide PRIMARY KEY、`request_kind`、`requested_media_type`、受理した全canonical ID、`base_event_sequence >= 0`、status、`recovery_selector`、`recovery_reason`、`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`、`occurred_at`、`recovery_payload_version` 1/2、non-empty initial/staged recovery payload、campaign processing partial UNIQUE、canonical `(campaign_id, turn_request_id)`非unique index、request kind/status/media/recovery payload/response CHECKを持つ。初期processing recordでは`request_kind`とversion 1、initial payloadが非NULLで、6つのrecovery metadataはNULL、`stage_recovery_metadata()`で一度だけCAS確定し、processing時response三列は全NULL、completion時はcode `200`、requested media、non-empty bodyである。normal `aborted_event_id`と`recovery_aborted_event_id`は別のEvent種別を表し、recordの予約IDだけではterminalを確定せずcurrent identity一致の`owned_suffix`のEvent Log actual membershipを権威（prefixは以前の履歴として除外）とする。
- schema-set最大versionが4、`1 -> 4`の連番、unknown versionなし、raw SQL bytes SHA-256 checksum一致を示す。
- claimはcoordinatorの`event_boundary_lock`閉区間内の`TurnRequestStore.claim(*, intent: TurnRequestIntent) -> ClaimResult`として、miss直後のcampaign processing row SELECTから`EventStore._read_campaign_on_connection(connection, campaign_id)`の全`DomainEvent` validation、`COALESCE(MAX(sequence), 0)`由来の`base_event_sequence`、insertまでを同一write transaction / connectionで行い、別keyのprocessingを`turn_already_processing`へ写像する。`base_event_sequence`は`NewClaim`だけで確定し、existing claimはimmutable identityだけを比較して現在MAXと比較しない。ClaimResultは`NewClaim`、`ExistingProcessingClaim`、`ExistingFinalClaim`を型で区別する。`ProjectionStore.rebuild`の1 callsiteと合わせてsame-connection readerを2 callsiteに固定する。
- PK / partial UNIQUE / CHECK / その他SQLite `IntegrityError`が固定`StoreErrorCode`へ写像され、raw SQLite message、identity値、cached body、cause、contextを外へ漏らさない。
- 通常のterminal pathではsubmitは`PlayerInputAccepted -> TurnResumed -> terminal`、resumeは`TurnResumed -> terminal`であり、既存`TurnStatus`の`pending` / `running` / `awaiting_player` / `committed` / `aborted`だけを使う。pre-model ambiguityはstarted prefixの後に`TurnAwaitingPlayer`を最後に置く非terminal pathとし、resumeで`PlayerInputAccepted`を二重作成しない。
- `test_prior_completed_turn_in_prefix_does_not_identify_current_submit_before_first_append`で、過去に完了した別turnのPlayerInputAcceptedがprefixにあっても、Event envelope（campaign/session/scene/turn）とlifecycle payloadのcanonical `turn_request_id`、submit accepted anchorだけの`input_digest`がcurrent recordに一致しないEventをcurrent submitのacceptedとして扱わず、current identity一致のprefix/owned_suffixにEventがない場合だけ`PlayerInputAccepted -> recovery TurnAborted`を候補にすることを確認する。`root_turn_request_id`はEvent fieldとの一致ではなく、record-levelのroot/canonical relationshipとしてclaim時に検証する。
- `test_turn_preparation_receives_full_campaign_events_before_projection_and_materialization`で、NewClaim直後の`EventStore.read_campaign(record.campaign_id)`一回のfull validated tupleが`TurnPreparation`へ先に渡り、`rebuild_projection(campaign_events)`、target/condition FactId、最終pre-ID effect candidatesが`event_id_sequence`前に確定することを確認する。prepareはcampaign eventsなしでは成立せず、append後のauthority rebuild readやP1-11のpresentation型をpreparation入力へ流用しない。
- `validate_and_materialize_candidate()`がappend前にcampaign全体のEventへ`project_turn_status()`と`rebuild_projection()`を適用し、non-committed effects、awaiting/abortedとeffectsの組み合わせ、terminal後のEventを拒否する。
- `PreparedTurn.scenario_end`が`None`の通常TurnはTurn terminalで終了し、`"success"` / `"failure"`のときだけ`TurnEventIdSequence`がSessionEnded用IDを追加し、`TurnEventBatchFactory`が`TurnCommitted -> SessionEnded`（`scene_id=None`、`turn_id=None`、`reason="completed"`）を最後に構成する。P1-03はこのpost-ID構成だけを所有し、ScenarioRuntimeやfixtureからの直接SessionEnded appendを許可しない。
- coordinatorのprepare / candidate validation / append / rebuild / completeの全例外で`try/finally`がregistryとshared `ApplicationRuntime.event_boundary_lock`を解放する。boundary lockはSQLite `_WRITE_LOCK`と別objectで、coordinatorは`sqlite3`をimportせず、connectionをlock越しに保持せず、nested `_write`を行わない。
- 通常Turnはsemantic response/candidateを検証し、committed / normal abortedではversion 2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）を確定してからterminal Eventを一度appendし、全Event read/rebuildでstrict UTF-8のresponseを検証してからcache/turn requestの`complete()`を一度だけ行う。recoveryはvalidated full campaign Event列を`prefix` / `owned_suffix`へ分け、current identityは全role共通のEvent envelope（`campaign_id`、`session_id`、`scene_id`、`turn_id`）、lifecycle roleのpayload `turn_request_id`、submit accepted anchorだけのpayload `input_digest`で照合し、存在しないEvent fieldの`root_turn_request_id`は比較せずrecord-level relationをclaim時に検証する。そのうえでcurrent identityに一致するprefixからoriginを、current identityに一致するowned_suffixからcurrent owned stateを導き、stored `RecoveryEventMetadata`のorigin `recovery_selector` / identity / 6個のEvent IDを再利用し、`recover_processing(*, record=..., campaign_events=...) -> RecoveryPlan`はmetadata CASとdecision/batch preparationだけを行う。`submit`でcurrent identityに一致するprefixに`PlayerInputAccepted`がなく、同じcurrent identityに一致するowned_suffixにもaccepted/terminalがなければinitial payloadで`PlayerInputAccepted`→recovery `TurnAborted`、`resume`でcurrent identityに一致するprefixに既存accepted/awaitingがあり、同じcurrent identityに一致するowned_suffixに`TurnResumed`/terminalがなければrecovery `TurnAborted`だけ（prefix acceptedは再appendしない）、owned_suffix awaiting/normal terminal/recovery abort actual後ではEvent追加なしでresponseを再構築する。normal terminalのcurrent identity一致のowned_suffix actual `committed_event_id` / normal `aborted_event_id`のresponse payloadは`select_response_payload()`がversion 2のstaged outer payloadだけを選び、version 1 / initialのみは固定errorにする。awaiting actualはv2 staged outer payloadを優先し、v2が無い場合だけv1 initial outer bytes + P1-08適用のtyped defaultを使う。recovery abortのcurrent identity一致のowned_suffix actual `recovery_aborted_event_id`はrecord versionに関係なく保存済みversion 1のinitial payloadを選ぶ。`aborted_event_id`と`recovery_aborted_event_id`は同じactual Eventの別名にしない。Event Logのcurrent identity一致のowned_suffix actualは同一roleの予約IDのsubsetであり、未使用予約IDの不在を許可する。各executeはdurable claimを正確に一回行い、`recover_processing()`はclaimを呼ばず、orphan recoveryはprepare/Provider/Diceを再実行せず、metadata未確定時だけ`stage_recovery_metadata()`を一度CASし、executeの同じ唯一のappend callsiteでcandidateを必要時に一度appendし、post-read→coordinator-only `ResponseRebuilder`一回→strict response validation→response/statusだけの`complete()`一回とし、初回recovery abortは`1 / 1 / 1`、recovery abort append後の再試行は`0 / 1 / 1`、normal committed / normal aborted / awaiting_playerのappend後complete前再試行も各`0 / 1 / 1`としてrebuild failure時はprocessingを保持する。Undoはこのnormal/recovery cache complete経路に入らない。
- `select_latest_committed_turn()`はCampaign全体の最大sequenceを先に選び、session mismatch時に古いTurnへfallbackしない。undoは`TurnReverted` appendであり、Event、Transcript、Telemetry、costを削除またはrollbackしない。Undoのread_processing durable guard、append/rebuild各一回、既存Revert全context照合、derive済み`revert_event_id`・selector済み`target_turn_id`・statusを受ける`UndoResponseRebuilder`一回、retry後のappend 0を満たす。
- `tests/integration/test_failed_turn_observations.py`の既存skip testをModifyし、injected `prepare`内のplayer input Transcript / TelemetryとEvent append failureだけをP1-03で検証する。Event count `0`でも観測とcostを保持する。Model request / response / Provider観測はP1-08で検証する。
- `tests/test_repository_contracts.py`のexact manifest / forbidden guardが各commitでexit `0`になり、source scan・DB mutation/protocol scan・cross-module claim/projection scanのcurrent positiveと代表sabotageを検証する。

### 契約確認点

C-01はAを採用する。通常TurnのModel call上限は1回とし、model由来clarification completionはPhase 1受入れ対象外とする。P1-03ではmodel由来clarificationを実装せず、P1-08もこの境界を維持する。

P1-03 Gateでは`RecoveryPayload`をdecodeするcallerがP1-03/Storeに存在せず、P1-08だけが`InitialRecoveryPayload` / `StagedRecoveryPayload`の`kind` / version / identity / media / inner responseをstrictに検証することも確認する。recordの予約IDは未使用ならEvent Logに不在でよく、normal terminalとrecovery abortのactual roleは分離する。P1-12の`scenario_outcome` candidateや`SessionEnded`のpost-ID構成をP1-03へ前倒ししない。

### コミット境界（Persistence / Lifecycleの2単位）

#### Persistence commit

Persistence laneのrecovery型は`RecoveryEventMetadata`の`accepted_event_id`、`resumed_event_id`、`awaiting_player_event_id`、`committed_event_id`、normal `aborted_event_id`、`recovery_aborted_event_id`の6個を同じshapeで保持する。`turn_models.py`、`0004`、record、stage/readback/CAS、Store testsはこの6個と初期NULL条件を同じcommitでstageし、Lifecycle symbolやcoordinatorのappendを混ぜない。

P1-02のcommit後、Persistence laneのREDが失敗理由付きで確認できたら、次の所有pathだけをstageする。`turn_models.py`のpersistence固有symbol（`TurnRequestIdentity`、pre-claim `TurnRequestIntent`、record、claim result、`RecoveryEventMetadata`、`RecoveryReason`、`RecoverySelector`、`CachedTurnResponse`、`StoreError`）と`turn_request_store.py`、`0004`、Store / migration tests、manifest guardを一つのlogical GREEN commitへまとめ、Lifecycleのsymbol、coordinator test、observation integrationはこのcommitへ含めない。`turn_models.py`は物理pathを共有するが、Persistence laneとLifecycle laneは同時に編集・stageせず、symbol単位で直列に着地させる。

Persistence laneの所有pathは`src/neontof/application/turn_models.py`（`TurnRequestIdentity`、pre-claim `TurnRequestIntent`、record、claim result、`RecoveryEventMetadata`、`RecoveryReason`、`RecoverySelector`、`CachedTurnResponse`、`StoreError`だけ）、`src/neontof/persistence/turn_request_store.py`、`src/neontof/persistence/migrations/0004_turn_requests.sql`、`tests/persistence/test_turn_request_store.py`、`tests/persistence/test_migrations.py`、`tests/test_repository_contracts.py`である。named testsはschema、claim、same-connection、sanitized IntegrityError、`test_recovery_metadata_shape_matches_sql_record_and_event_ids_are_memory_derived`、stage CAS、read/read_processing、complete cacheだけに限定し、Undoやcoordinatorのappendを含めない。

```powershell
git add -- src/neontof/application/turn_models.py src/neontof/persistence/turn_request_store.py src/neontof/persistence/migrations/0004_turn_requests.sql tests/persistence/test_turn_request_store.py tests/persistence/test_migrations.py tests/test_repository_contracts.py
```

```text
feat: Turn request persistence契約を追加する
```

#### Lifecycle commit

Lifecycle laneが同じ`turn_models.py`で作る型/aliasは`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、`TurnEventBatchFactory`、`TurnEventIdSequence`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnExecutionResult`、`CoordinatorResult`、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`、`derive_revert_event_id`である。具体実装`derive_recovery_event_id(identity: TurnRequestIdentity, role: RecoveryEventRole) -> EventId`、`reserve_recovery_event_ids(identity: TurnRequestIdentity) -> RecoveryEventIdReservation`、`build_recovery_metadata(record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...], inputs: RecoveryMetadataInputs) -> RecoveryEventMetadata`は`src/neontof/application/turn_lifecycle.py`が一つだけ所有する。`RecoveryEventIdSource = Callable[[TurnRequestIdentity], RecoveryEventIdReservation]`はrequest identity/keyと6 roleからdeterministicにIDを導出し、EventStoreをcaptureしない。`TurnLifecycleCoordinator.recover_processing(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> RecoveryPlan`はここでstageし、metadata未確定時だけ注入済みclock sourceとID sourceを各一回呼んで`RecoveryMetadataInputs`を作り、三引数のfactoryを一回呼び、metadata CASとdecision/batch preparationだけを行う。`EventStore.append()`と`TurnRequestStore.complete()`は`execute()`の既存callsiteが担当し、`recover_processing`内には置かない。

Persistence commitとそのfocused/full Gateが完了した後、Lifecycle laneのREDが失敗理由付きで確認できたら、`turn_models.py`のLifecycle type/alias（`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、`TurnEventBatchFactory`、`TurnEventIdSequence`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnExecutionResult`、`CoordinatorResult`、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`、`derive_revert_event_id`）と`turn_lifecycle.py`の具体関数`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、`ActiveTurnToken`、`OwnedActiveTurn`、`ExistingActiveTurn`、`ActiveTurnAcquisition`、`ActiveTurnRegistry`、`TurnLifecycleCoordinator`、builder、candidate validator、selector、idempotency、recovery、undo、injected observation testを一つのlogical GREEN commitへまとめる。Persistence laneが所有する`TurnRequestIdentity`、`TurnRequestIntent`、record、claim result、`RecoveryEventMetadata`、`RecoveryReason`、`RecoverySelector`、`CachedTurnResponse`、`StoreError`はこのcommitで再定義せずimportして使う。`tests/test_repository_contracts.py`はLifecycle production manifest pathとP1-03のEvent append caller 2件をこのcommitでserialに追加し、manifest laneを並列化しない。Persistence symbolを再編集・再stageせず、`turn_models.py`の物理pathを共有するためPersistence commit後にだけ連続してstageする。

Lifecycle laneの所有pathは`src/neontof/application/turn_models.py`（型/alias `RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、`TurnEventBatchFactory`、`TurnEventIdSequence`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnExecutionResult`、`CoordinatorResult`、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`、`derive_revert_event_id`）、`src/neontof/application/__init__.py`、`src/neontof/application/turn_lifecycle.py`（具体関数`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、`ActiveTurnToken`、`OwnedActiveTurn`、`ExistingActiveTurn`、`ActiveTurnAcquisition`、`ActiveTurnRegistry`、`TurnLifecycleCoordinator`、全lifecycle builder / validator / selector）、`tests/application/test_turn_lifecycle.py`、`tests/integration/test_turn_idempotency.py`、`tests/integration/test_failed_turn_observations.py`、`tests/test_repository_contracts.py`である。Persistence laneのrecord / recovery metadata / response / error symbolはimportする。named testsはcoordinator、`test_recover_processing_returns_recovery_plan_without_append_rebuild_or_complete`、`test_build_recovery_metadata_uses_role_aware_domain_event_fields`、Event順序、full candidate validation、`test_turn_event_batch_factory_receives_identity_prepared_turn_utc_time_event_id_sequence_and_campaign_events`, `test_turn_event_batch_factory_cannot_infer_origin_selector_without_campaign_events`, `test_resume_claim_before_first_owned_event_appends_only_recovery_abort`, `test_metadata_cas_continues_to_recovery_abort_in_same_execute`、`test_recovery_builder_reuses_all_stored_metadata_without_fresh_ids_or_timestamp`、lock/finally、active acquisition、recovery、undo、idempotency、player input observation retentionだけに限定し、Bootstrap APIを含めない。

P1-03 Lifecycleのstageには`turn_models.py`の`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、結果union、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`と、`turn_lifecycle.py`の`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、coordinatorを含める。P1-05/P1-08がこのLifecycle symbolを並列にModify・stageしない。

Lifecycle commitのnamed testには、terminal `PreparedTurn`のv2 staged outer payload必須、P1-03 `select_response_payload()`のopaque outer bytes選択、`PreparedTurn.scenario_end`を`TurnEventBatchFactory`だけが`TurnCommitted -> SessionEnded(reason="completed")`へ構成する契約を含める。このP1-03のgeneric factory testはactual `ScenarioOutcomeFact` candidateを要求せず、P1-12がそのcandidateの供給・append・replayを所有する。P1-08のnamed testもactual `ScenarioOutcomeFact` candidateを前提にせず、`scenario_outcome=None`のcore response bundleまでを検証する。

```powershell
git add -- src/neontof/application/turn_models.py src/neontof/application/__init__.py src/neontof/application/turn_lifecycle.py tests/application/test_turn_lifecycle.py tests/integration/test_turn_idempotency.py tests/integration/test_failed_turn_observations.py tests/test_repository_contracts.py
```

```text
feat: Turn lifecycle coordinatorを追加する
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

P1-04のproduction manifest追加は`src/neontof/rules/__init__.py`と`src/neontof/rules/minimal_2d6.py`だけである。P1-04は既存Phase 0 domain contractを変更せず、rulesとdeterminismだけを担当する。`event_metadata`、`EventMaterializationInput`、`TurnEventMetadata`、Application runtimeをimportしない。P1-05以降がこのrules moduleのtyped resultを既存Domain Eventへ変換する。

**公開型とシグネチャ**

```python
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from neontof.contracts.character_sheet import ResourceState
from neontof.contracts.domain import (
    ClockAdvancedPayload,
    DiceRolledPayload,
    ResourceChangedPayload,
    derive_dice_seed,
)
from neontof.contracts.ids import ActionId, CampaignId, EntityId, LowercaseSha256, ResourceId, TurnId
from neontof.contracts.projection import FactRecord, Projection
from neontof.contracts.semantic_result import ProposedResourceChanged
from neontof.contracts.base import ContractModel

NonNegativeStrictInt = Annotated[StrictInt, Field(ge=0)]
PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]
TargetNumber = Annotated[StrictInt, Field(ge=2, le=12)]
StatusCondition = Literal["injured", "shaken"]

class DiceResult(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: StrictInt

class PublicDiceView(ContractModel):
    campaign_seed: LowercaseSha256
    action_id: ActionId
    roll_index: NonNegativeStrictInt
    derived_seed: LowercaseSha256
    formula: Literal["2d6"]
    result: StrictInt

class ResourceLimit(ContractModel):
    resource_id: ResourceId
    entity_id: EntityId
    minimum: NonNegativeStrictInt
    maximum: NonNegativeStrictInt

class RuleValidationIssue(ContractModel):
    path: str
    code: Literal[
        "out_of_bounds",
        "unsupported_formula",
        "unknown_resource",
        "invalid_target_number",
        "invalid_condition",
        "unknown_clock",
    ]
    message: str

class CheckResult(ContractModel):
    dice: DiceResult
    target: TargetNumber
    success: bool

def resolve_2d6(
    *,
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: NonNegativeStrictInt,
) -> DiceResult: ...

def resolve_2d6_check(
    *,
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: NonNegativeStrictInt,
    target: TargetNumber,
) -> CheckResult: ...

def validate_target_number(value: StrictInt) -> TargetNumber: ...

def validate_status_condition(value: str) -> StatusCondition: ...

def validate_resource_changes(
    *,
    projection: Projection,
    proposals: Sequence[ProposedResourceChanged],
    limits: Sequence[ResourceLimit],
) -> tuple[RuleValidationIssue, ...]: ...

def validate_clock_advance(
    *,
    current: NonNegativeStrictInt,
    delta: PositiveStrictInt,
    maximum: PositiveStrictInt,
) -> tuple[RuleValidationIssue, ...]: ...

```

`resolve_2d6()`は既存の`derive_dice_seed()`を呼び、そのdigestから生成したlocal `random.Random`だけを使う。`resolve_2d6_check()`の`success`は`dice.result >= target`から導出し、LLMが返したdice値、target、success flag、Eventに存在しないmodifierをauthorityにしない。`DiceResult` / `PublicDiceView`は既存`DiceRolledPayload`のauthoritative fieldsに対応し、`formula`は`Literal["2d6"]`、resultは2..12、Event materializationとreplay projectionはP1-08で行う。targetは`TargetNumber`（strict integer 2..12）というrules moduleのtyped valueであり、semantic resultから未検証で受け取らない。P1-08は検証済みtargetを既存`FactAssertedPayload(kind="fact", holder="world", subject_id=None, predicate="target_number", value=target)`へ変換してEvent Logへ記録する。新しいEvent/contractを追加せず、Event Logをtargetのauthorityとする。

HPは既存`CharacterSheetV1.hp`と`ResourceChangedPayload`の`resource_id="resource:hp"`で扱い、Character Sheetの一資源はその既存`ResourceId`を同じ`ResourceChangedPayload`で扱う。`validate_resource_changes()`は`Projection.resources`と`ResourceLimit`を使って0..maximumを超えるdeltaを拒否し、P1-08がHPとresourceを既存Eventへ変換する。Clockは既存`ClockAdvancedPayload(clock_id, delta)`とScenarioV1の唯一のclockを使い、`validate_clock_advance()`でcurrent + deltaがmaximumを超えないことを検証する。clock current/maxはEvent-derived ProjectionとScenarioV1 definitionから確認する。

状態異常は新しいFactKindやEventを作らず、少数のclosed convention `StatusCondition = Literal["injured", "shaken"]`で扱う。P1-08は検証済みconditionを既存`FactAssertedPayload(kind="fact", holder="player_character", subject_id=character_entity_id, predicate="condition", value=condition)`へ変換し、置換時は既存`FactSupersededPayload`を使う。P1-07のPublicFactは`target_number`と`condition`をtyped predicate/valueとしてrebuildしてUIへ渡し、rules / Event / rebuild / UI testで値域と表示を確認する。P1-04は本格戦闘、二つ目のconcrete Ruleset、Narrative parseを作らない。既存Event/Fact契約だけで上記の2d6判定、目標値、HP、Resource 1種、少数の状態異常、Clock 1本、Dice Seed導出を表現できないことが判明した場合は、P1-04を開始せずRoadmapまたは上位contractの改訂をStop Conditionとして報告する。

**テストファースト**

- `test_same_inputs_produce_same_seed_and_dice`
- `test_different_roll_index_changes_seed`
- `test_global_random_state_does_not_affect_result`
- `test_result_is_between_two_and_twelve`
- `test_target_number_is_strict_and_bounded`
- `test_check_success_is_derived_from_dice_and_target`
- `test_resource_change_cannot_cross_zero_or_maximum`
- `test_hp_and_one_resource_use_existing_resource_ids`
- `test_status_condition_uses_closed_two_value_convention`
- `test_clock_advance_respects_single_clock_bounds`
- `test_rules_module_does_not_import_event_metadata`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/rules tests/test_repository_contracts.py -q
```

期待REDはmissing module。skeleton後は、seed再現性、2..12のstrict result、targetの2..12境界、diceからのsuccess導出、HP/resourceの0..maximum、conditionのclosed literal、single clockの上限でassertion failureとなる。rules moduleが既存contract以外のEvent/metadataをimportした場合はrepository contract testがREDになる。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。固定fixtureを2回実行した`derived_seed`、`formula`、`result`が一致し、global random stateに依存せず、resultは既存`DiceRolledPayload`のauthoritative fieldsだけから再計算可能である。targetはstrict 2..12で`FactAsserted`の`predicate="target_number"` / typed valueへ、conditionは`FactAsserted`の`predicate="condition"` / `StatusCondition`へ変換できる。HPと一つのResourceが既存`ResourceChangedPayload`でProjectionへrebuildされ、唯一のClockが既存`ClockAdvancedPayload`で上限検証される。P1-04はcontracts/**を変更せず、本格戦闘と二つ目のRulesetを追加しない。manifest/forbidden guardの未登録production pathも検出されない。

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

- `src/neontof/application/bootstrap_service.py`
- `src/neontof/authoring/__init__.py`
- `src/neontof/authoring/yaml_loader.py`
- `src/neontof/authoring/character_loader.py`
- `src/neontof/authoring/scenario_loader.py`
- `src/neontof/authoring/bootstrap.py`
- `tests/application/test_bootstrap_service.py`
- `tests/authoring/test_yaml_loader.py`
- `tests/authoring/test_character_loader.py`
- `tests/authoring/test_scenario_loader.py`
- `tests/authoring/test_bootstrap_events.py`

**変更**

- `requirements.in`
- `requirements-dev.in`
- `requirements.lock.txt`
- `src/neontof/application/turn_lifecycle.py`（`append_bootstrap`だけをModify）
- `tests/test_repository_contracts.py`

P1-05のproduction manifest追加は`src/neontof/application/bootstrap_service.py`と、`src/neontof/authoring/__init__.py`、`src/neontof/authoring/yaml_loader.py`、`src/neontof/authoring/character_loader.py`、`src/neontof/authoring/scenario_loader.py`、`src/neontof/authoring/bootstrap.py`の6つである。`src/neontof/authoring/bootstrap.py`は`from neontof.event_metadata import EventBatch`と必要なneutral metadata型をimportする。P1-03 Lifecycle commitとfocused/full Gateが先に完了し、P1-05だけが`TurnLifecycleCoordinator.append_bootstrap()`をModifyしてbootstrapのEvent boundaryを追加する。P1-03ではこのAPIを定義・実装・test・stageしない。P1-05後のapplication-level `EventStore.append()` callerはcoordinatorの`execute()`、`revert_latest()`、`append_bootstrap()`の3 callsiteであり、owner classは引き続き`TurnLifecycleCoordinator`一つである。P1-03のRecovery bundleは`src/neontof/application/turn_models.py`が型/alias `RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`を所有し、`src/neontof/application/turn_lifecycle.py`だけが具体関数`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`を実装する分離であり、P1-05で再定義・再stageしない。
`ApplicationRuntime.bootstrap_service`のfield追加と`POST /api/campaigns`へのwireは、runtimeが作成されるP1-11の`src/neontof/application/runtime.py` / `src/neontof/app.py` composition stageで行う。P1-05はserviceとcoordinator APIを完成させるが、route、runtime factory、別のappend callerは追加しない。

**公開型とシグネチャ**

```python
from collections.abc import Callable, Sequence

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
    occurred_at: OccurredAt,
    event_ids: Sequence[EventId],
) -> EventBatch: ...

BootstrapEventBuilder = Callable[
    [BootstrapInput, OccurredAt, Sequence[EventId]],
    EventBatch,
]

BootstrapPreparation = Callable[[], EventBatch]

class TurnLifecycleCoordinator:
    def append_bootstrap(
        self,
        *,
        campaign_id: CampaignId,
        prepare: BootstrapPreparation,
    ) -> tuple[StoredEvent, ...]: ...

class BootstrapApplicationService:
    def __init__(
        self,
        coordinator: TurnLifecycleCoordinator,
        build_bootstrap_events: BootstrapEventBuilder,
    ) -> None: ...

    def create_campaign(
        self,
        *,
        input_value: BootstrapInput,
        occurred_at: OccurredAt,
        event_ids: Sequence[EventId],
    ) -> tuple[StoredEvent, ...]: ...
```

`src/neontof/authoring/bootstrap.py`は`from neontof.event_metadata import EventBatch`と必要なneutral metadata型をimportし、唯一の具体実装`build_bootstrap_events(input_value: BootstrapInput, occurred_at: OccurredAt, event_ids: Sequence[EventId]) -> EventBatch`を提供する。`BootstrapEventBuilder`は`src/neontof/application/bootstrap_service.py`のexact `Callable[[BootstrapInput, OccurredAt, Sequence[EventId]], EventBatch]` aliasであり、`Protocol`、代替builder class、二つ目の具体実装を作らない。P1-05でだけ`from collections.abc import Callable`を使って`BootstrapPreparation = Callable[[], EventBatch]`を定義し、`TurnLifecycleCoordinator.append_bootstrap(*, campaign_id: CampaignId, prepare: BootstrapPreparation) -> tuple[StoredEvent, ...]`をModifyする。`BootstrapApplicationService`は`from neontof.application.turn_lifecycle import BootstrapPreparation, TurnLifecycleCoordinator`を使うが、`EventStore`をfieldまたはwriterとしてimportしない。

`BootstrapApplicationService`は`coordinator`と`build_bootstrap_events`だけをfieldとして持ち、`EventStore` field、EventStore writer、独自lock、sqlite connectionを持たない。`create_campaign()`は`input_value.campaign_id`をcaptureした`BootstrapPreparation` closureを一回だけ作り、そのclosure内で唯一の具体実装`build_bootstrap_events(input_value, occurred_at, event_ids)`を一回呼び、`coordinator.append_bootstrap(campaign_id=input_value.campaign_id, prepare=prepare)`へ委譲する。service自身はEventをappendせず、EventBatchを作ってcoordinatorへ渡すだけである。`append_bootstrap()`はshared `ApplicationRuntime.event_boundary_lock`を取得し、全DomainEvent読込、既存Event拒否、prepare一回、predicted sequenceによる`project_turn_status()` / `rebuild_projection()`検証、append一回、全Event再読検証を行い、取得したlockを`finally`で解放する。SQLite `_WRITE_LOCK`とは別objectであり、connectionをlock越しに保持せず、nested `_write`を行わない。これによりapplication-levelのEventStore.append callerはP1-03の`execute()`、`revert_latest()`、P1-05後の`append_bootstrap()`の3 callsiteで止まる。

### Phase 1 input・ID・Fact・authority契約

P1-05は既存の`ScenarioV1`と`CharacterSheetV1`をloaderの入力型として使う。`ScenarioV1`は`schema_version: Literal[1]`とcontent versionの`version: str`を持ち、`CharacterSheetV1`は`schema_version: Literal[1]`だけをversion fieldとして持つ。Character Sheetへ別のversion fieldを参照・追加せず、Scenarioの`version`とCharacterの`schema_version`を混同しない。P1-05は`contracts/**`を変更せず、bootstrapで別のad hoc JSON schemaを作らない。

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
| `inventory_item` | `fact` | `player_character` | required: character `EntityId` | stable `ItemId` | `player_visible` | `CharacterSheetV1.initial_items`からbootstrapした`FactAsserted` |
| `objective` | `fact` | `world` | nullable (`None`) | `SceneId` strict value object | `player_visible` | `ScenarioV1.initial_scene.id`からbootstrapした`FactAsserted` |
| `location` | `fact` | `player_character` | required: character `EntityId` | stable `LocationId` | `player_visible` | `CharacterMoved` Event |
| `clue` | `fact` | `world` | nullable (`None`) | stable clue `EntityId` | `player_visible` | `ScenarioV1.clues`とvalidated `FactAsserted` |
| `scenario_version` | `fact` | `world` | nullable (`None`) | `ScenarioV1.version`のstrict string | `player_visible` | `ScenarioV1.version`からbootstrapした`FactAsserted` |
| `character_schema_version` | `fact` | `player_character` | required: character `EntityId` | strict `Literal[1]`を既存`FactAssertedPayload.value: FrozenJsonValue`へ格納 | `player_visible` | `CharacterSheetV1.schema_version`からbootstrapした`FactAsserted` |
| `target_number` | `fact` | `world` | nullable (`None`) | P1-04 `TargetNumber`（strict integer 2..12） | `player_visible` | P1-04で検証した値を既存`FactAsserted`へ変換 |
| `condition` | `fact` | `player_character` | required: character `EntityId` | P1-04 `StatusCondition`（`"injured"`または`"shaken"`） | `player_visible` | P1-04で検証した値を既存`FactAsserted`へ変換し、置換は`FactSuperseded` |
| `scenario_outcome` | `fact` | `world` | `None` | `Literal["success", "failure"]` | `player_visible` | P1-12 `ScenarioRuntime`が既存`FactAsserted`へ変換 |

`npc_notice`はPhase 1許可predicateから外す。`condition`、`target_number`、`character_schema_version`はP1-04/P1-05が定める既存`FactAsserted`のtyped conventionで扱い、`scenario_outcome`は`kind="fact"`、`holder="world"`、`subject_id=None`、`value=Literal["success", "failure"]`、`visibility="player_visible"`を満たすP1-12 `ScenarioRuntime` producerのclosed armとして扱う。別のidentifier namespaceやEventを発明しない。ObjectiveのFact valueは`ScenarioV1.initial_scene.id`の`SceneId`とし、表示textはFact valueへ入れず、`ScenarioV1.initial_scene.objective.text`をP1-07のtyped `PublicStaticData`から読む。

authoritative sourceは次のとおりである。

- HP maxと初期HP、resource maxと初期resourceはCharacterSheetV1のresource定義からbootstrapする。currentの以後の値はEvent-derived Projectionだけをauthorityとする。
- Objectiveのauthoritative valueは`ScenarioV1.initial_scene.id`の`SceneId`であり、表示textは同じScenarioV1の`initial_scene.objective.text`をtyped `PublicStaticData`から読む。clock maxとend conditionはScenarioV1のversioned definitionから読む。clock currentはEvent-derived Projectionで、初期値`0`をbootstrap規約とする。
- success/failure EndはScenarioV1の既存end condition定義だけを`ScenarioRuntime`が評価する。Model、Narrative、Factの自由文をauthoritative sourceにしない。
- CharacterSheetV1/ScenarioV1の`schema_version`、ScenarioV1の`version`、stable IDはloaderが検証し、bootstrap Eventへversionを記録する場合も`scenario_version`または`character_schema_version`の既存`FactAsserted` conventionだけを使う。

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
- `test_character_loader_uses_initial_items_and_schema_version`
- `test_scenario_loader_returns_scenario_v1`
- `test_bootstrap_uses_only_existing_domain_event_types`
- `test_bootstrap_returns_event_batch_with_event_ids_and_occurred_at`
- `test_bootstrap_events_rebuild_initial_hp_resource_location_and_clock`
- `test_bootstrap_secret_fact_is_gm_only`
- `test_mutating_yaml_result_cannot_mutate_contract`
- `test_bootstrap_batch_is_atomic`
- `test_append_bootstrap_rejects_existing_events_and_prepares_once`
- `test_append_bootstrap_validates_predicted_sequence_and_rereads_all_events`
- `test_bootstrap_application_service_delegates_batch_to_coordinator`
- `test_bootstrap_application_service_has_no_event_store_writer_or_lock`
- `test_p1_05_adds_only_the_third_eventstore_append_callsite`
- `test_fact_allowlist_accepts_only_closed_scenario_outcome_shape`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring tests/application/test_bootstrap_service.py tests/test_repository_contracts.py -q
```

期待REDはmissing module。bootstrap skeleton後はProjectionのHP / location / secret Fact不足でassertion failure。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。loaderが`CharacterSheetV1.initial_items`と`CharacterSheetV1.schema_version: Literal[1]`を返し、`ScenarioV1.version`をCharacterへ混入させない。bootstrap Event列を`rebuild_projection()`へ渡し、Character current HP、Resource、Location、Clock、Scenario ID、Scene ID、Factが期待値と一致する。manifest追記漏れと未許可pathがないことも同じcommandで確認する。

**Lockコマンド**

`docs/agent-guide/build-and-verify.md`のcanonical fresh TEMP venv手順を使い、次の入力からlockを再生成する。

```powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) {
    throw "git rev-parse --show-toplevel failed or returned an empty repository root."
}
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
if ([System.IO.Path]::GetFullPath((Get-Location).Path) -ne $repositoryRoot) {
    throw "repository root was not set directly."
}
$customCompileCommandWasPresent = Test-Path -LiteralPath 'Env:CUSTOM_COMPILE_COMMAND'
$customCompileCommandValue = if ($customCompileCommandWasPresent) { $env:CUSTOM_COMPILE_COMMAND } else { $null }
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$lockTempFull = [System.IO.Path]::GetFullPath((Join-Path $tempRoot ('neontof-lock-' + [guid]::NewGuid().ToString('N'))))
$tempPrefix = $tempRoot
if (-not $tempPrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $tempPrefix += [System.IO.Path]::DirectorySeparatorChar
}
if ($lockTempFull.Equals($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $lockTempFull.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a lock TEMP path outside the validated TEMP directory."
}

try {
    & py -3.14 -m venv $lockTempFull
    $venvExit = $LASTEXITCODE
    if ($venvExit -ne 0) {
        throw "lock venv creation failed with exit $venvExit."
    }

    $lockPython = Join-Path $lockTempFull 'Scripts\python.exe'
    $lockCompile = Join-Path $lockTempFull 'Scripts\pip-compile.exe'
    & $lockPython -m pip install --disable-pip-version-check 'pip-tools==7.6.1'
    $pipToolsInstallExit = $LASTEXITCODE
    if ($pipToolsInstallExit -ne 0) {
        throw "pip-tools install failed with exit $pipToolsInstallExit."
    }

    & $lockPython -c "import importlib.metadata; print('pip-tools ' + importlib.metadata.version('pip-tools'))"
    $pipToolsVersionExit = $LASTEXITCODE
    if ($pipToolsVersionExit -ne 0) {
        throw "pip-tools version check failed with exit $pipToolsVersionExit."
    }

    $env:CUSTOM_COMPILE_COMMAND = 'pip-compile --generate-hashes --output-file requirements.lock.txt requirements-dev.in'
    & $lockCompile --generate-hashes --output-file requirements.lock.txt requirements-dev.in
    $lockExit = $LASTEXITCODE
    if ($lockExit -ne 0) {
        throw "pip-compile failed with exit $lockExit."
    }
    "pip-compile exit $lockExit"
    $lockText = Get-Content -Raw -LiteralPath 'requirements.lock.txt'
    $machineLocalPathHits = ([regex]::Matches($lockText, '(?im)(?:[A-Z]:\\|/Users/|/home/|/tmp/)')).Count
    $openAiHits = ([regex]::Matches($lockText, '(?im)\bopenai\b')).Count
    "lock machine-local path hits $machineLocalPathHits"
    "openai hits $openAiHits"
    if ($machineLocalPathHits -ne 0) {
        throw "lock contains machine-local paths."
    }
    if ($openAiHits -ne 0) {
        throw "lock contains openai references."
    }
} finally {
    try {
        if ($customCompileCommandWasPresent) {
            $env:CUSTOM_COMPILE_COMMAND = $customCompileCommandValue
        } else {
            Remove-Item -LiteralPath 'Env:CUSTOM_COMPILE_COMMAND' -ErrorAction SilentlyContinue
        }
    } finally {
        if ([System.IO.Directory]::Exists($lockTempFull)) {
            [System.IO.Directory]::Delete($lockTempFull, $true)
        }
        "TEMP exists after cleanup=$([System.IO.Directory]::Exists($lockTempFull))"
    }
}
if ((Test-Path -LiteralPath 'Env:CUSTOM_COMPILE_COMMAND') -ne $customCompileCommandWasPresent) {
    throw "CUSTOM_COMPILE_COMMAND presence was not restored."
}
if ($customCompileCommandWasPresent -and $env:CUSTOM_COMPILE_COMMAND -ne $customCompileCommandValue) {
    throw "CUSTOM_COMPILE_COMMAND value was not restored."
}
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

P1-05後のcanonical build-and-verify commandは`docs/agent-guide/build-and-verify.md`の順序に合わせ、repository rootから次を実行する。

```powershell
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
.\.venv\Scripts\python.exe -m pytest -q
```

各commandはexit `0`、formatは`files already formatted`、lintは`All checks passed!`、mypyは`Success: no issues found`、pytestはfailure/error `0`を期待する。lock生成block内で使う`$repositoryRoot`、`$lockTempFull`、`$lockPython`、`$lockCompile`、`$customCompileCommandWasPresent`、`$customCompileCommandValue`、`$tempRoot`、`$tempPrefix`、`$venvExit`、`$pipToolsInstallExit`、`$pipToolsVersionExit`、`$lockExit`、`$lockText`、`$machineLocalPathHits`、`$openAiHits`は全て同block内で定義し、repository rootからcanonical commandを実行する。未定義variableやrepository root外からのrelative outputを使わない。

**コミット境界**

```powershell
git add -- src/neontof/application/bootstrap_service.py src/neontof/application/turn_lifecycle.py src/neontof/authoring/__init__.py src/neontof/authoring/yaml_loader.py src/neontof/authoring/character_loader.py src/neontof/authoring/scenario_loader.py src/neontof/authoring/bootstrap.py tests/application/test_bootstrap_service.py tests/authoring/test_yaml_loader.py tests/authoring/test_character_loader.py tests/authoring/test_scenario_loader.py tests/authoring/test_bootstrap_events.py requirements.in requirements-dev.in requirements.lock.txt tests/test_repository_contracts.py
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
from collections.abc import Sequence
from typing import Literal, Self

from pydantic import StrictInt, StrictStr, TypeAdapter, ValidationError, model_validator

from neontof.contracts.base import ContractModel
from neontof.contracts.character_sheet import CharacterSheetV1
from neontof.contracts.ids import (
    CampaignId,
    ClockId,
    EntityId,
    EventId,
    FactId,
    ItemId,
    LocationId,
    LowercaseSha256,
    NpcId,
    ResourceId,
    SceneId,
    SessionId,
    TurnId,
    TurnRequestId,
)
from neontof.contracts.projection import FactRecord, Projection
from neontof.contracts.scenario import ScenarioV1
from neontof.contracts.semantic_result import PublicationVisibility, SemanticValidationContext
from neontof.rules.minimal_2d6 import StatusCondition, TargetNumber

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

_ENTITY_ID_ADAPTER = TypeAdapter(EntityId)
_ITEM_ID_ADAPTER = TypeAdapter(ItemId)
_LOCATION_ID_ADAPTER = TypeAdapter(LocationId)
_SCENE_ID_ADAPTER = TypeAdapter(SceneId)

def _matches(adapter: TypeAdapter[object], value: object) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True

PublicFactValue = (
    EntityId
    | ItemId
    | LocationId
    | SceneId
    | TargetNumber
    | StatusCondition
    | Literal[1]
    | StrictStr
)

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
        "character_schema_version",
        "target_number",
        "condition",
    ]
    value: PublicFactValue
    source_event_id: EventId

    @model_validator(mode="after")
    def validate_predicate_shape(self) -> Self:
        if self.predicate == "inventory_item":
            expected_holder, subject_required = "player_character", True
            valid_value = _matches(_ITEM_ID_ADAPTER, self.value)
        elif self.predicate == "objective":
            expected_holder, subject_required = "world", False
            valid_value = _matches(_SCENE_ID_ADAPTER, self.value)
        elif self.predicate == "location":
            expected_holder, subject_required = "player_character", True
            valid_value = _matches(_LOCATION_ID_ADAPTER, self.value)
        elif self.predicate == "clue":
            expected_holder, subject_required = "world", False
            valid_value = _matches(_ENTITY_ID_ADAPTER, self.value)
        elif self.predicate == "scenario_version":
            expected_holder, subject_required = "world", False
            valid_value = type(self.value) is str
        elif self.predicate == "character_schema_version":
            expected_holder, subject_required = "player_character", True
            valid_value = type(self.value) is int and self.value == 1
        elif self.predicate == "target_number":
            expected_holder, subject_required = "world", False
            valid_value = type(self.value) is int and 2 <= self.value <= 12
        else:  # condition
            expected_holder, subject_required = "player_character", True
            valid_value = self.value in ("injured", "shaken")
        if self.holder != expected_holder:
            raise ValueError("public fact holder does not match predicate")
        if subject_required != (self.subject_id is not None):
            raise ValueError("public fact subject does not match predicate")
        if not valid_value:
            raise ValueError("public fact value does not match predicate")
        return self

ScenarioOutcome = Literal["success", "failure"]

class ScenarioOutcomeFact(ContractModel):
    fact_id: FactId
    kind: Literal["fact"]
    holder: Literal["world"]
    subject_id: None
    predicate: Literal["scenario_outcome"]
    value: ScenarioOutcome
    visibility: Literal["player_visible"]
    source_event_id: EventId

def select_public_target_and_conditions(
    facts: Sequence[PublicFact],
) -> tuple[TargetNumber | None, tuple[StatusCondition, ...]]: ...

def select_scenario_outcome(
    facts: Sequence[FactRecord],
) -> ScenarioOutcome | None: ...

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
    scenario_outcome: ScenarioOutcome | None
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

`PublicFact`のpredicate/value/holder/subject shapeは`validate_predicate_shape()`で閉じた表として強制する。`inventory_item`は`ItemId` / `player_character` / character `EntityId`必須、`objective`は`SceneId` / `world` / `None`可、`location`は`LocationId` / `player_character` / character `EntityId`必須、`clue`はclue `EntityId` / `world` / `None`、`scenario_version`はstrict `str` / `world` / `None`、`character_schema_version`はstrict `Literal[1]` / `player_character` / character `EntityId`必須、`target_number`はP1-04 `TargetNumber` / `world` / `None`、`condition`はP1-04 `StatusCondition` / `player_character` / character `EntityId`必須とする。`kind="fact"`と`source_event_id`は全armで必須のままにし、predicateと別armのvalue、holder、subject_idは`PublicFact`生成時に拒否する。`build_context()`、`PublicProjection`、`PublicContext`はこのvalidatorを通過した`PublicFact`だけを受け、raw dictや独立`FactValue` unionをpublic contextへ渡さない。`target_number=1`、未知condition、`schema_version=2`、predicate/arm不一致を代表sabotageとして固定する。

`ScenarioOutcomeFact`は`PublicFact`のpredicate unionへ追加しない、scenario outcome専用のvalidated projection armである。`kind="fact"`、`holder="world"`、`subject_id=None`、`predicate="scenario_outcome"`、`value=Literal["success", "failure"]`、`visibility="player_visible"`、`source_event_id`、`fact_id`だけを許可し、未知value、別holder、subject、visibilityは拒否する。`select_scenario_outcome(facts: Sequence[FactRecord]) -> ScenarioOutcome | None`がこの契約の唯一のselector/authorityであり、replay済み`FactRecord`をclosed shapeの`ScenarioOutcomeFact`へstrictに検証する。active outcomeが0件なら`None`、1件ならそのvalue、複数またはpredicate/value/holder/subject/visibility/sourceが壊れたfactならfail-closedで返す。`select_public_target_and_conditions()`とは別のselectorであり、fixtureへFactを直接挿入せず、P1-08/P1-12がEvent replayからこのoutcomeを再構築する。

`ApplicationRegistry`はP1-05でloadした`ScenarioV1`と`CharacterSheetV1`から作る。`build_public_static_data()`はHP max、resource ID/label/max、`CharacterSheetV1.initial_items`の各InitialItemを`PublicInventoryItem(item_id: ItemId, label: StrictStr)`へ写し、objective_scene_idへ`ScenarioV1.initial_scene.id`の`SceneId`、objective_textへ`ScenarioV1.initial_scene.objective.text`、clock ID/label/maxだけをtyped `PublicStaticData`へ写す。`PublicFact`はpredicateごとのmodel validatorでvalue、holder、subject_idを同時に検証するため、独立した`FactValue` unionだけでtarget/condition/schema versionを受理しない。`target_number`はP1-04の`TargetNumber`、`condition`は`StatusCondition`、`character_schema_version`はstrict `Literal[1]`だけを受け、全て既存`FactAsserted`からrebuildする。secret本文、NPCの`gm_only`本文、任意のraw Scenario/Characterを含めない。location/NPC/clockのregistryは引数として明示し、bootstrap clockがcurrent `0`でもScenarioV1のclock IDを`known_clock_ids`へ登録する。`build_semantic_validation_context()`は`projection`だけからlocation、clock、NPC registryを推測せず、必ずregistryを受け取る。

`build_public_session_view()`は`public_static_data.inventory`の各`label`を順序どおり`PublicSessionView.inventory: tuple[str, ...]`へ写す。Factの`ItemId`と`PublicInventoryItem.item_id`はそのまま保持し、`EntityId`へ変換しない。

`build_context(..., publication_visibility="player_visible")`はactiveかつ`player_visible`のFactだけをtyped `PublicProjection`へ投影し、`subject_id=None`のpublic Factも落とさずに`PublicContext`を先に作る。secretを一度入れてから削除する方式ではなく、最初から選択しない。resources、locations、clocks、facts、`scenario_outcome`、campaign/session/scene/turn/request identifiersはEvent replay由来のtyped projectionとして明示する。full `Projection`はsemantic validationの内部入力に限り、Model Gateway、public HTTP view、Narrative auditへ渡さない。これらのsignatureは`PublicContext`または`PublicProjection`だけを受け取る。`PublicProjection`を組み立てるcallerは、必ず`EventStore.read_campaign(campaign_id)`が返すcampaign全体の`DomainEvent`列をrebuildしたprojectionを渡す。filtered event tuple、snapshot、observation、coordination recordを入力にしない。対象外rowが壊れている場合も`read_campaign()`のfail-closedを伝播させる。

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
- `test_public_projection_preserves_target_number_and_condition_facts`
- `test_public_fact_rejects_target_number_one`
- `test_public_fact_rejects_unknown_condition`
- `test_public_fact_rejects_character_schema_version_two`
- `test_public_fact_rejects_predicate_value_holder_subject_mismatch`
- `test_scenario_outcome_fact_accepts_only_closed_success_failure_shape`
- `test_scenario_outcome_selector_fails_closed_on_multiple_or_corrupt_facts`
- `test_public_context_accepts_only_validated_public_facts`
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
- `ScenarioOutcomeFact`が既存FactRecordからsuccess/failureだけをvalidatedにrebuildし、複数・壊れた・別shapeをfail-closedにする
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
- `src/neontof/application/turn_responses.py`
- `src/neontof/application/turn_engine.py`
- `tests/application/test_event_materializer.py`
- `tests/application/test_semantic_pipeline.py`
- `tests/application/test_turn_responses.py`
- `tests/integration/test_complete_fake_turn.py`
- `tests/integration/test_model_failure_atomicity.py`

**変更**

- `src/neontof/application/turn_models.py`（P1-03 Lifecycle symbolは変更せず、P1-08固有のSemantic Result / response型を追加する場合だけserialにModify）
- `tests/test_repository_contracts.py`

P1-08のproduction manifest追加は`src/neontof/application/event_materializer.py`、`src/neontof/application/semantic_pipeline.py`、`src/neontof/application/turn_responses.py`、`src/neontof/application/turn_engine.py`の4つである。`src/neontof/application/turn_models.py`はP1-03で既にmanifestへ追加した共有pathであり、P1-08で再Modifyする場合もP1-03 Lifecycle commit後にSemantic Result / response型だけをserialに追加する。P1-08のpayload boundary checkpointと既存`FrozenJsonValue`のcomposite value round-trip開始前stopは維持し、P1-00で推測実装しない。

P1-08では`src/neontof/application/turn_responses.py`が`InitialRecoveryPayload`、`StagedResponseSeed`、`StagedRecoveryPayload`、`RecoveryPayload`、`encode_staged_response_seed`、`decode_staged_response_seed`、`encode_recovery_payload`、`decode_recovery_payload`、`build_initial_recovery_payload`、`build_staged_recovery_payload`、`TurnResponseDocument`、`ResponseDocumentBuilder`のtyped response/codecを所有し、`src/neontof/application/turn_engine.py`が`TurnPreparationContext`、`derive_input_digest`、`derive_turn_id`、`TurnCommand`、`ResumeTurnCommand`、`TurnEngine.bind_turn_preparation(*, context=...)`、`TurnEngine.prepare_turn(*, context=..., identity=..., campaign_events=...)`を所有する。P1-03はこれらをimportせず、coordinator callbackの`TurnPreparation` aliasだけを所有する。

P1-08のpayload authorityは、各inbound `Engine.execute`相当の呼出しでclaim前に`build_initial_recovery_payload(...)`を純粋・決定的に一回だけ呼ぶことを許可する。`NewClaim`では供給bytesをseedとして採用するが、`ExistingProcessingClaim` / `ExistingFinalClaim`では供給値を破棄し、保存recordのinitial/staged bytesだけをauthorityにする。claim後、`recover_processing()`、prepareではbuilderを再実行しない。normal `committed` / normal `aborted`の完成にはversion 2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）を必須とし、recovery abortはversionに関係なく保存済みversion 1 initial payloadを使う。P1-03 / Storeはbytesをdecodeせず、P1-08の`ResponseDocumentBuilder` / recovery `ResponseRebuilder`だけがinner seedとouter `RecoveryPayload`をstrict decodeする。

**公開型とシグネチャ**

```python
import hashlib

from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBytes, StrictInt, StrictStr

from neontof.application.turn_models import (
    CachedTurnResponse,
    CampaignId,
    CompletedTurnResult,
    ExistingFinalTurnResult,
    LowercaseSha256,
    NonEmptyBytes,
    OpaqueRequestKey,
    ProcessingTurnRequestRecord,
    ProcessingTurnResult,
    UndoCommand,
    PreparedEffect,
    PreparedTurn,
    UndoResult,
    ResponseRebuilder,
    RequestedMediaType,
    RequestKind,
    SceneId,
    SessionId,
    TurnId,
    TurnRequestId,
    TurnRequestIdentity,
    TurnPreparation,
    TurnExecutionResult,
    UndoResponseRebuilder,
)
from neontof.application.turn_lifecycle import TurnLifecycleCoordinator
from neontof.application.context_builder import (
    PublicContext,
    PublicProjection,
    PublicResourceProjection,
    ScenarioOutcome,
    ScenarioOutcomeFact,
    select_public_target_and_conditions,
    select_scenario_outcome,
)
from neontof.contracts.domain import DomainEvent
from neontof.contracts.projection import Projection
from neontof.rules.minimal_2d6 import StatusCondition, TargetNumber

def derive_input_digest(input_text: StrictStr) -> LowercaseSha256:
    return LowercaseSha256(hashlib.sha256(input_text.encode("utf-8")).hexdigest())

def materialize_accepted_result(
    *,
    identity: TurnRequestIdentity,
    outcome: AcceptedSemanticResult,
    projection: Projection,
    context: PublicContext,
    dice_result: DiceResult | None,
) -> tuple[PreparedEffect, ...]: ...

def materialize_dice_event(
    *,
    identity: TurnRequestIdentity,
    result: DiceResult,
) -> PreparedEffect: ...

class DiceProjection(ContractModel):
    rolls: tuple[DiceResult, ...]

def rebuild_dice_projection(
    events: Sequence[DomainEvent],
) -> DiceProjection: ...

class TurnPreparationContext(ContractModel):
    model_config = ConfigDict(frozen=True, strict=True)
    input_text: StrictStr
    provisional_reference_text: StrictStr | None = None

class InitialRecoveryPayload(ContractModel):
    model_config = ConfigDict(frozen=True, strict=True)
    kind: Literal["initial_recovery_payload"]
    recovery_payload_version: Literal[1]
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    turn_request_id: TurnRequestId
    input_digest: LowercaseSha256

class StagedResponseSeed(ContractModel):
    model_config = ConfigDict(frozen=True, strict=True)
    kind: Literal["staged_response_seed"]
    seed_version: Literal[1]
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    narrative: tuple[StrictStr, ...]
    suggested_actions: tuple[StrictStr, ...]
    cost_microusd: Annotated[StrictInt, Field(ge=0)]
    processing_status: Literal[
        "accepted",
        "building_context",
        "invoking_model",
        "validating",
        "committing",
        "done",
        "failed",
    ]
    corrections: tuple[StrictStr, ...]
    semantic_result: AcceptedSemanticResult | None

class StagedRecoveryPayload(ContractModel):
    model_config = ConfigDict(frozen=True, strict=True)
    kind: Literal["staged_recovery_payload"]
    recovery_payload_version: Literal[2]
    request_kind: RequestKind
    requested_media_type: RequestedMediaType
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    root_turn_request_id: TurnRequestId
    turn_request_id: TurnRequestId
    input_digest: LowercaseSha256
    response_payload: NonEmptyBytes  # canonical encode_staged_response_seed(...) bytes

RecoveryPayload = Annotated[
    InitialRecoveryPayload | StagedRecoveryPayload,
    Field(discriminator="kind"),
]

def encode_recovery_payload(payload: RecoveryPayload) -> NonEmptyBytes: ...

def decode_recovery_payload(raw: StrictBytes) -> RecoveryPayload: ...

def build_initial_recovery_payload(
    *,
    request_kind: RequestKind,
    requested_media_type: RequestedMediaType,
    campaign_id: CampaignId,
    session_id: SessionId,
    scene_id: SceneId,
    turn_id: TurnId,
    root_turn_request_id: TurnRequestId,
    turn_request_id: TurnRequestId,
    input_digest: LowercaseSha256,
) -> NonEmptyBytes: ...

def build_staged_recovery_payload(
    *,
    identity: TurnRequestIdentity,
    response_payload: NonEmptyBytes,
) -> NonEmptyBytes: ...

def encode_staged_response_seed(seed: StagedResponseSeed) -> NonEmptyBytes: ...

def decode_staged_response_seed(raw: StrictBytes) -> StagedResponseSeed: ...

class TurnCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    request_key: OpaqueRequestKey
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    input_text: StrictStr
    provisional_reference_text: StrictStr | None = None

class ResumeTurnCommand(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId
    turn_id: TurnId
    request_key: OpaqueRequestKey
    requested_media_type: RequestedMediaType
    turn_request_id: TurnRequestId
    input_text: StrictStr
    provisional_reference_text: StrictStr | None = None

class TurnResponseDocument(ContractModel):
    turn_id: TurnId
    turn_request_id: TurnRequestId
    status: TurnStatus
    semantic_result: AcceptedSemanticResult | None
    narrative: tuple[str, ...]
    public_projection: PublicProjection
    resource_projection: PublicResourceProjection
    dice_projection: DiceProjection
    dice_result: DiceResult | None
    target_number: TargetNumber | None
    conditions: tuple[StatusCondition, ...]
    scenario_outcome: ScenarioOutcome | None
    suggested_actions: tuple[StrictStr, ...]
    cost_microusd: Annotated[StrictInt, Field(ge=0)]
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

ResponseSerializer = Callable[[TurnResponseDocument, RequestedMediaType], StrictBytes]
ResponseDocumentBuilder = Callable[
    [ProcessingTurnRequestRecord, tuple[DomainEvent, ...], TurnStatus, StrictBytes],
    TurnResponseDocument,
]
UndoResponseDocumentBuilder = Callable[
    [UndoCommand, tuple[DomainEvent, ...], TurnStatus, TurnId, EventId],
    TurnResponseDocument,
]

def build_response_document(
    *,
    record: ProcessingTurnRequestRecord,
    campaign_events: tuple[DomainEvent, ...],
    turn_status: TurnStatus,
    response_payload: StrictBytes,
) -> TurnResponseDocument: ...

def build_response_rebuilder(
    *,
    build_document: ResponseDocumentBuilder,
    serialize: ResponseSerializer,
) -> ResponseRebuilder: ...

def build_undo_response_rebuilder(
    *,
    build_document: UndoResponseDocumentBuilder,
    serialize: ResponseSerializer,
) -> UndoResponseRebuilder: ...

class TurnEngine:
    def __init__(
        self,
        *,
        coordinator: TurnLifecycleCoordinator,
        gateway: ModelGateway,
        registry: ApplicationRegistry,
    ) -> None: ...

    def bind_turn_preparation(
        self,
        *,
        context: TurnPreparationContext,
    ) -> TurnPreparation: ...

    def prepare_turn(
        self,
        *,
        context: TurnPreparationContext,
        identity: TurnRequestIdentity,
        campaign_events: tuple[DomainEvent, ...],
    ) -> PreparedTurn: ...

    def submit(self, command: TurnCommand) -> TurnExecutionResult: ...
    def resume(self, command: ResumeTurnCommand) -> TurnExecutionResult: ...
    def undo_latest(self, command: UndoCommand) -> UndoResult: ...
```

P1-08はP1-00のneutral aliasをmaterializerへ渡さず、同typeを再定義もしない。`materialize_accepted_result(*, identity, outcome, projection, context, dice_result) -> tuple[PreparedEffect, ...]`と`materialize_dice_event(*, identity, result) -> PreparedEffect`はEvent IDと`OccurredAt`を持たないpre-ID候補だけを返す。両producerはcurrent `TurnRequestIdentity`を受けて`PreparedEffect`のcampaign/session/scene/turn envelopeをidentityから構成し、identity mismatchを拒否する。P1-08はSemantic ResultとNarrativeを分離し、validated Semantic Resultからだけcandidateを作る。`TurnExecutionResult`、`CoordinatorResult`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnPreparation`、`PreparedTurn`、`PreparedEffect`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`はP1-03 Lifecycle commitで`src/neontof/application/turn_models.py`が所有するunion/typeであり、P1-08は着地していないsymbolを`turn_lifecycle.py`からimportせず、そこからimportして再定義しない。P1-08が`turn_models.py`を再Modifyする場合は追加のSemantic Result / response symbolだけをP1-03 Lifecycle後に直列でstageする。`TurnEngine.submit(command: TurnCommand) -> TurnExecutionResult`、`resume(command: ResumeTurnCommand) -> TurnExecutionResult`、`undo_latest(command: UndoCommand) -> UndoResult`はそれぞれpre-claim `TurnRequestIntent`と`TurnPreparation`を構成して`TurnLifecycleCoordinator.execute(intent=..., prepare=...)`へ、undoは`revert_latest(command=command)`へ委譲する。`CompletedTurnResult`と`ExistingFinalTurnResult`の`CachedTurnResponse`はcoordinatorからEngine、routeへ同じ`status_code`、`media_type`、body bytesのままforwardし、P1-11で再serializeしない。`ProcessingTurnResult`は`response=None`、`status="processing"`、`http_status_code=202`を明示する。これはregistryの`ExistingActiveTurn` hitだけのactive fast pathに使い、registry missで`ExistingProcessingClaim`になった場合は単なる202返却ではなく、`TurnLifecycleCoordinator.execute()`内のboundary lock下で`recover_processing()`へ入る。recovery結果は同じ`TurnExecutionResult`のfinal variantとして返し、recovery不能な安全な失敗は固定`StoreError`とする。P1-08の`TurnEngine`、Semantic Result pipeline、producerは`EventStore.append()`、`TurnRequestStore.claim()`、`TurnRequestStore.stage()`、`TurnRequestStore.complete()`、`read_processing()`を直接呼ばない。sequence割当、candidate full validation、Event append、rebuild、response cache completeはcoordinatorへ委譲する。P1-08のproducerは`DomainEvent`または`tuple[DomainEvent, ...]`を返さず、EventBatchやEventDraftも構成しない。Diceのpre-ID materializationとEvent replay projectionはP1-08の責務である。`rebuild_dice_projection(events: Sequence[DomainEvent])`のcallerは`EventStore.read_campaign(campaign_id)`が返すcampaign全体のvalidated `DomainEvent`列をそのまま渡し、filtered event slice、snapshot、coordination record、observationを渡さない。`DiceProjection.rolls`と`DiceResult`は`DiceRolledPayload`の`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけをauthoritative fieldsとして保持する。対象外の壊れたEvent rowは`read_campaign()`のfail-closedで止める。

`TurnEngine`のnormal callbackは`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`が返す二引数bound callbackである。P1-08の`TurnEngine.submit()` / `resume()`はcommandからimmutable context、derived identity、initial recovery payload、pre-claim intentを一度だけ作り、`prepare = self.bind_turn_preparation(context=context)`を作ってからcoordinatorへ注入する。coordinatorはNewClaim後の同じ`event_boundary_lock`内で先に一度取得したfull validated tupleだけをcallbackへ渡し、closureが保持するimmutable contextとともに`rebuild_projection`、target/condition FactId、pre-ID `effect_candidates`をEvent ID allocation前に確定させる。append後のfull readはcommit結果のauthority rebuild/response reconstruction専用であり、NewClaim後のpreparation readを後から置き換えたり、campaign eventsを欠くcallbackを許可したりしない。P1-03のLifecycle commitはP1-08の`TurnEngine`未着地でも、このinjected callback typeだけで型検査できる。`TurnEngine`は`EventStore`、`ProjectionStore`、`TurnRequestStore`、`ObservationStore`、`ActiveTurnRegistry`、`event_boundary_lock`をfield/constructor引数として所有しない。それらのread/write、registry、lock寿命は`TurnLifecycleCoordinator` / `ApplicationRuntime`の責務であり、P1-08のconstructorは`coordinator`、`gateway`、`registry`だけを受け取る。

ここでP1-08のconstructorの`registry: ApplicationRegistry`はscenario/public model用の別型であり、process-lifetimeの`ActiveTurnRegistry`とは別の所有物・責務である。`ActiveTurnRegistry`は`ApplicationRuntime`から`TurnLifecycleCoordinator`にだけ注入し、Engine、route、handlerへ渡さない。

`P1-08`はneutralなmetadata、`EventDraft`、`EventBatch`をmaterializerからimportしない。normal preparationのpre-ID候補は`PreparedEffect`だけであり、post-IDの`EventDraftBody` / `EventDraft` / `EventBatch`は`TurnEventBatchFactory`だけが構成する。

`TurnPreparationContext`はP1-08の`src/neontof/application/turn_engine.py`が所有するimmutableなper-execute contextであり、`input_text: StrictStr`と、C-02承認時の明示的なpromotionに使う`provisional_reference_text: StrictStr | None`だけを持つ。`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`はこのcontextをclosureへ一度だけ保持し、`TurnPreparation = Callable[[TurnRequestIdentity, tuple[DomainEvent, ...]], PreparedTurn]`の二引数callbackを返す。callbackは`context.input_text`をそのexecuteのModel requestへ一度だけ渡し、P1-09が有効な場合だけ`context.provisional_reference_text`を明示的なpromotion referenceとして使う。`TurnEngine`のmutable instance field、global、Transcript、以前のrequestからinputを補わず、interleaved commandでcontextを共有しない。bound callbackを介さない公開または単独のinput探索APIは作らない。
このcontextの実装設定は`ConfigDict(frozen=True, strict=True)`であり、coordinatorへ渡した後にfieldを変更できない。`InitialRecoveryPayload` / `StagedRecoveryPayload`も同じ`ConfigDict(frozen=True, strict=True)`を使い、`RecoveryPayload` unionの各memberをstrict/frozenに検証する。

`src/neontof/application/turn_responses.py::build_initial_recovery_payload(...) -> NonEmptyBytes`と`build_staged_recovery_payload(*, identity: TurnRequestIdentity, response_payload: NonEmptyBytes) -> NonEmptyBytes`はP1-08所有のpure/deterministic typed builderである。前者のexact signatureは`build_initial_recovery_payload(*, request_kind: RequestKind, requested_media_type: RequestedMediaType, campaign_id: CampaignId, session_id: SessionId, scene_id: SceneId, turn_id: TurnId, root_turn_request_id: TurnRequestId, turn_request_id: TurnRequestId, input_digest: LowercaseSha256) -> NonEmptyBytes`とし、request keyはpayloadへ二重保持せず、DB-wide row keyと同じrequest identityにEngine/Store側で結び付ける。後者は`TurnRequestIdentity`のimmutable identity/media/digestと、`encode_staged_response_seed(seed: StagedResponseSeed)`でcanonical化済みのtyped `response_payload`だけからversion 2のouter staged `StagedRecoveryPayload` bytesを構成し、任意のNonEmptyBytesを受け付けない。`InitialRecoveryPayload`は`kind="initial_recovery_payload"`、`recovery_payload_version=1`、`request_kind`、campaign/session/scene/turn、`root_turn_request_id`、canonical `turn_request_id`、`input_digest`、`requested_media_type`を必須にし、`StagedRecoveryPayload`は同じidentity/media/digest fieldsに`kind="staged_recovery_payload"`、`recovery_payload_version=2`、canonical encoded `StagedResponseSeed` bytesである`response_payload: NonEmptyBytes`を必須にする。`RecoveryPayload = Annotated[InitialRecoveryPayload | StagedRecoveryPayload, Field(discriminator="kind")]`を唯一のunionとする。stagedの内側はP1-08のtyped response/presentation bytesだけであり、Projection/status/diceをauthorityとして重複保持しない。どちらもraw input、API key、raw provider body/error、secret/GM-only text、未検証のNarrative自由文を含めない。`StagedResponseSeed`だけはvalidated public Narrativeをtypedな`narrative` fieldsとして保持できる。
`StagedResponseSeed`は`kind="staged_response_seed"`、`seed_version=1`、outer payloadと同じrequest/identity/media/digest、`narrative: tuple[StrictStr, ...]`、`suggested_actions: tuple[StrictStr, ...]`、strict nonnegative `cost_microusd`、closed `processing_status`、`corrections: tuple[StrictStr, ...]`、必要な場合だけ公開済みtyped `semantic_result: AcceptedSemanticResult | None`を持つ。Event-derivedなProjection、Turn status、Dice projection/resultはseedへ重複保存せず、append後のfull Event replayから再構築する。`encode_staged_response_seed(seed: StagedResponseSeed) -> NonEmptyBytes`と`decode_staged_response_seed(raw: StrictBytes) -> StagedResponseSeed`はcanonical compact JSONのstrict UTF-8 codecであり、unknown field、duplicate key、trailing token、root/discriminator/version、identity/media、secret/provider/raw inputをfail-closedにする。
`encode_recovery_payload(payload: RecoveryPayload) -> NonEmptyBytes`はcanonical compact JSONのstrict UTF-8 bytesを作り、`decode_recovery_payload(raw: StrictBytes) -> RecoveryPayload`はduplicate key、trailing token、root object、outer discriminator/version、identity、media、`StagedResponseSeed`のinner discriminator/version/identity、`response_payload`が`encode_staged_response_seed(seed)`で作られたcanonical inner bytesであることを検証する。未知field、kind/version不一致、identity/media mismatch、改ざん、secret/provider bytesは固定されたsanitized validation errorへ写像し、raw exceptionを漏らさない。P1-03とStoreはこのouter bytesをdecodeせず、P1-08の`ResponseDocumentBuilder` / recovery `ResponseRebuilder`だけがouterのstrict decoder後にinner `decode_staged_response_seed()`を呼ぶ。`PreparedTurn.staged_recovery_payload`は`build_staged_recovery_payload()`が返すcanonical outer bytes（内側は`encode_staged_response_seed(seed)`のbytes）を保持し、`TurnRequestStore.stage()`はそのopaque bytesをversion 1から2へ一度だけCASする。
JSON内の`response_payload: NonEmptyBytes`はcanonical base64 ASCII stringとして表現し、decoderだけがbase64からnon-empty strict UTF-8 bytesへ戻す。bytesをJSONへ暗黙にrepr化せず、initial/stagedのkindとversionを別々に解釈しない。

`build_staged_recovery_payload(*, identity: TurnRequestIdentity, response_payload: NonEmptyBytes) -> NonEmptyBytes`の`response_payload`は`encode_staged_response_seed(seed)`が返したcanonical inner bytesに限る。この関数だけが`StagedRecoveryPayload(..., response_payload=response_payload)`を作って`encode_recovery_payload(...)`へ渡し、DB保存用のouter bytesを返す。任意の`NonEmptyBytes`をstaged outer payloadとして通過させず、P1-03のselectorへinner bytesを渡さない。

claim前は既存recordの有無を判定できないため、P1-08 Engineは各inbound executeで`build_initial_recovery_payload(...)`を純粋・決定的に一回だけ呼ぶ。`NewClaim`では供給bytesをINSERTのseedに使い、`ExistingProcessingClaim` / `ExistingFinalClaim`では供給bytesを捨てて保存済みrecordのinitial/staged bytesだけをauthorityにする。`recover_processing()`、claim後、prepare内ではinitial/staged payloadを再buildしない。same-key replay、registry miss recovery、append後complete前のrestartではpre-claim供給値を採用せず保存bytesを再利用し、claim後・recovery内ではprovider、dice、prepare、payload builderを再実行しない。この不変条件は、各inbound executeのclaim前にinitial payload builderを一回呼ぶことを妨げない。

`TurnCommand` / `ResumeTurnCommand`から`TurnRequestIntent`への写像はP1-08の`TurnEngine.submit()` / `resume()`だけが行う。Commandはrouteが提供できるraw/validated inputに限定し、`request_key`、`requested_media_type`、`campaign_id`、`session_id`、`scene_id`、canonical `turn_request_id`、resume URLの`turn_id`、`input_text`、optional `provisional_reference_text`だけを持つ。Engineは`request_kind`、server-owned `turn_id`、`root_turn_request_id`、`input_digest`、immutable `TurnPreparationContext`、`initial_recovery_payload`、その他の`TurnRequestIntent` required fieldをこの入力から一度だけ構成する。submitでは`root_turn_request_id = command.turn_request_id`、resumeでも`root_turn_request_id = command.turn_request_id`とし、`ResumeTurnCommand`にserver-resolved root fieldを要求しない。resume URLの`turn_id`とbody canonical IDはEngineが同一Command内のtyped ID grammar / 構文整合だけを検証する。過去Eventのaccepted/awaiting anchor、campaign/session/scene/turn context、canonical/root relationshipのstrict validationは、shared `event_boundary_lock`内の`TurnRequestStore.claim()`だけがfull validated Event/recordを使って行い、Engineはclaim外で読み取り・照合・推測しない。`base_event_sequence`と`staged_recovery_payload`はpre-claim intentへ写さずNewClaim/後続stageだけが確定する。routeは派生値やcontext/payload/intentをCommandへ積まず、同じ値を二重にderiveしない。

submitのserver-owned `TurnId`は`src/neontof/application/turn_engine.py::derive_turn_id(campaign_id: CampaignId, session_id: SessionId, turn_request_id: TurnRequestId) -> TurnId`で一度だけ導出する。`campaign_bytes`、`session_bytes`、`request_bytes`を各IDのUTF-8 bytesとし、preimageを`b"NEONTOF:TURN-ID:v1\\0" + ASCII byte length(campaign_bytes) + b":" + campaign_bytes + b"\\0" + ASCII byte length(session_bytes) + b":" + session_bytes + b"\\0" + ASCII byte length(request_bytes) + b":" + request_bytes`とする。`hashlib.sha256(preimage).hexdigest()`を`"turn:"`へ連結して`TurnId`にする。KATは`derive_turn_id("campaign:alpha", "session:main", "turn-request:one") == TurnId("turn:029aa820ddd031e8ce12f5e3e37b610a72eb693a611817e9309008830bb9013c")`であり、trim、casefold、Unicode normalize、clock、Python `hash()`を使わない。resumeはこのderiveを呼ばず、URLの`turn_id`とbodyのcanonical `turn_request_id`をvalidated Commandとして受け、`root_turn_request_id = command.turn_request_id`とする。existing Eventとのaccepted/awaiting anchor、context、record-level root/canonical relationshipのstrict照合はboundary lock内のclaimだけが行う。

CommandからIntentへの写像は次の表だけを正本とする。

| Intent field | submit | resume | owner / validation |
|---|---|---|---|
| `request_key` | `command.request_key` | `command.request_key` | P1-08 Engineがsafe-parsed opaque keyをそのまま渡す |
| `request_kind` | `"submit"` | `"resume"` | Engineが固定literalを設定 |
| `requested_media_type` | `command.requested_media_type` | `command.requested_media_type` | routeの`Accept` parse済み値を再deriveしない |
| `campaign_id` / `session_id` / `scene_id` | 各`command` field | 各`command` field | Engineがcontextを補わない |
| `turn_request_id` | `command.turn_request_id` | `command.turn_request_id` | canonical identity。idempotency keyではない |
| `turn_id` | `derive_turn_id(command.campaign_id, command.session_id, command.turn_request_id)` | `command.turn_id` | submitだけserver-owned derive、resumeはURL値をclaimで照合 |
| `root_turn_request_id` | `command.turn_request_id` | `command.turn_request_id` | `root_turn_request_id = command.turn_request_id`。anchor/contextの関係はclaim内だけで検証 |
| `input_digest` | `derive_input_digest(command.input_text)` | `derive_input_digest(command.input_text)` | Engineが一回だけ計算。resumeのprefix accepted digestとは比較しない |
| `initial_recovery_payload` | `build_initial_recovery_payload(...)` | `build_initial_recovery_payload(...)` | claim前にEngineが一回生成し、NewClaimだけがseedとして採用 |
| `base_event_sequence` / `staged_recovery_payload` | pre-claimでは未設定 | pre-claimでは未設定 | NewClaim / `stage()`だけが確定し、Engineは供給しない |

この表のmapping testは、submit/resumeの全Intent identity、requested media、digest、root、server-ownedまたはURLの`turn_id`、initial payloadが一度ずつ構成され、routeがこれらを作らないことをassertする。`TurnRequestStore.claim()`はboundary lock内でaccepted/awaiting anchor、campaign/session/scene/turn context、canonical/root relationshipをstrictに検証し、Engineはclaim外で過去Eventを推測しない。

`TurnResponseDocument`はP1-08が所有するtyped response bundleであり、`public_projection`、`resource_projection`、`dice_projection`、`dice_result`、`narrative`、`suggested_actions`、nonnegative `cost_microusd`、closed `processing_status`、`corrections`、`target_number`、`conditions`、`scenario_outcome`、`turn_id`、canonical `turn_request_id`、`status`を含む。P1-08の`ResponseDocumentBuilder` / `build_response_document()`はfull validated Event replay、`TurnStatus`、`select_response_payload()`が返すopaque `StrictBytes`からこのtyped documentを作る。target/conditionは`select_public_target_and_conditions()`から一度だけ導出し、P1-08 core pathの`scenario_outcome`は`None`とする。P1-12がScenarioOutcomeFact candidateをappendした拡張pathだけ、replayed `FactRecord`を`ScenarioOutcomeFact`として検証する`select_scenario_outcome()`からscenario outcomeを一度だけ導出し、Factを直接documentへ注入しない。normal `committed` / normal `aborted`の完成は`select_response_payload()`が返すversion 2のcanonical outer `StagedRecoveryPayload` bytes（内側は`encode_staged_response_seed(seed)`のbytes）を必須とし、version 1のinitial payloadだけで完了できる限定経路を作らない。`PreparedTurn.staged_recovery_payload`はこのcanonical outer bytes（内側は`encode_staged_response_seed(seed)`のbytes）を保持してstageでき、P1-03はそのbytesをopaqueに運搬するだけでJSONをdecodeまたは解釈しない。recovery abortではrecord versionに関係なく保存済みversion 1のinitial payloadを使い、awaitingでは保存済みv2 staged outer payloadを優先し、無い場合だけv1 initial payloadと固定typed presentation defaultを使う。recovery時は保存済み`initial_recovery_payload`または`staged_recovery_payload`だけを`ResponseRebuilder`へ渡し、Model、Provider、Dice、semantic pipelineを再実行しない。P1-08からP1-11へはこのdocumentとneutral/public projection型だけが流れ、P1-03はP1-11の`PublicSessionView`、`PublicSessionPresentation`、`StateFrame`をimportしない。

`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`はP1-08の具体的なbound preparation factoryであり、返すcallbackは`TurnPreparation = Callable[[TurnRequestIdentity, tuple[DomainEvent, ...]], PreparedTurn]`に適合する。callback内部の`self.prepare_turn(*, context=context, identity=identity, campaign_events=campaign_events)`だけがprepare本体を呼び、coordinatorはこのEngine methodを知らない。coordinatorがNewClaim後に先に渡したfull tupleをclosureが`rebuild_projection(campaign_events)`へ渡し、Event-derived Projection/contextを作ってからcontext.input_textでsemantic result、Dice、target/condition materializationを実行する。`materialize_accepted_result(*, identity, outcome, projection, context, dice_result) -> tuple[PreparedEffect, ...]`はmetadataを受けず、current identityとProjection/contextからpre-ID候補だけを返し、`materialize_dice_event(*, identity, result) -> PreparedEffect`も同じ境界を守る。両producerは`PreparedEffect`のenvelopeをcurrent identityから構成し、identity mismatchをEvent ID allocation前に拒否する。target/conditionのFact candidateと最終`effect_candidates`が確定するまでEvent IDを割り当てず、coordinatorから後段で渡される`event_id_sequence`を先に呼ばない。P1-08はbound callbackをcoordinatorへ渡し、`TurnPreparation`を`turn_lifecycle.py`で再定義しない。
normal pathのresponse payloadは、bound preparation callbackが返す`PreparedTurn.staged_recovery_payload`（non-NULLならstageして保存）をEvent candidateと共にcoordinatorが運び、append後に`select_response_payload(record=..., campaign_events=...)`が選んだopaque `StrictBytes`を`ResponseRebuilder`へ渡す。`ResponseDocumentBuilder`はそのpayloadとappend後のfull replayからtyped `TurnResponseDocument`を作り、P1-03はこのbytesをdecode・JSON解釈せず、P1-11のserializerへ渡された完成bytesだけをcacheする。

normal `TurnEventBatchFactory`のP1-08 injectionは`Callable[[TurnRequestIdentity, PreparedTurn, tuple[DomainEvent, ...], OccurredAt, Sequence[EventId]], tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch]]`に固定する。NewClaim後のcoordinatorが同じ`event_boundary_lock`内で明示的に一度だけ行う`EventStore.read_campaign(record.campaign_id)`のfull validated tupleを第三引数へ渡し、factoryはEventStoreをcaptureせず、`prefix = {event | event.sequence <= identity.base_event_sequence}` / `owned_suffix = {event | event.sequence > identity.base_event_sequence}`を分ける。全role共通のenvelope（`campaign_id`、`session_id`、`scene_id`、`turn_id`）、lifecycle payloadのcanonical `turn_request_id`、submit accepted anchorだけのpayload `input_digest`をcurrent identity照合に使い、`root_turn_request_id`をEvent fieldとして要求しない。resumeの新しい`input_digest`はprefix acceptedや`TurnResumed` / `TurnAwaitingPlayer` / terminal payloadへ比較しない。`matches_current_turn_identity()`に一致するprefix/suffixだけをorigin/statusとcurrent owned stateの判定へ使う。`RecoveryMetadataFactory(record, campaign_events, inputs)`はnormal factoryとは別経路のexact三引数であり、metadata未確定時だけP1-03注入の`RecoveryEventIdSource`とUTC sourceを各一回呼んだ`RecoveryMetadataInputs`を受け取り、既存metadata時は再実行しない。P1-08は`StatusCondition` / `TargetNumber`をP1-04のrules moduleからimportして既存`FactAsserted`のtyped valueへ渡す。

P1-03 Lifecycleが所有する`TurnExecutionResult`、`CoordinatorResult`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnPreparation`、`PreparedTurn`、`RecoveryPlan`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`は`src/neontof/application/turn_models.py`からimportする。registry missの`ExistingProcessingClaim`は`TurnLifecycleCoordinator.execute()`内で`recover_processing()`に入り、`RecoveryPlan`のdecision/batch preparation後のcandidate validation、append、reread、rebuild、completeはexecuteの既存callsiteが行う。P1-08は`recover_processing()`内のappend/rebuild/completeを前提にせず、未着地symbolを`turn_lifecycle.py`からimportしない。 `ExistingActiveTurn` hit以外（OwnedActiveTurn、registry miss、restart、recovery retryを含む）の各`execute()`は同じboundary lock内でdurable claimを正確に一回行い、`ExistingProcessingClaim`はstored baseを変えずINSERT `0`で`recover_processing()`へ渡す。`recover_processing()`はclaimを呼ばない。

`UndoResponseRebuilder`は`Callable[[UndoCommand, tuple[DomainEvent, ...], TurnStatus, TurnId, EventId], CachedTurnResponse]`に固定する。`TurnLifecycleCoordinator.revert_latest(command: UndoCommand) -> UndoResult`は、同じ`event_boundary_lock`内でdurable `read_processing(campaign_id=command.campaign_id)`、campaign全体read、coordinatorによる`derive_revert_event_id(campaign_id=command.campaign_id, request_key=command.request_key)`一回、derived ID lookup、既存Revertのcampaign/session/target/context/origin/visibility/payload全context照合、ID absent時だけglobal latest committed Turn selector、validate、append一回、reread/rebuild一回を順に行う。processing rowがあれば`UndoBlockedResult(http_status_code=409, code="turn_already_processing")`を返してselectorへ進まず、same campaignのprocessingを解消しない。既存Revertの全context一致時は、保存されたEventをresponse sourceとしてcoordinatorがfull campaign Event列・status・target・derive済みIDを`UndoResponseRebuilder`へ一回渡し、`append=0`、`rebuild=1`でresponseを返す。同じID別contextはconflictとし、rebuilder failureはEvent追加なしのままsanitized errorを返してretryを許可する。rebuilderへはcoordinatorがderive済み`revert_event_id`、selector済み`target_turn_id`、必要status、campaign全体Event列を一度だけ渡し、rebuilderはID再derive・latest再selector・Event append・request cache更新を行わない。`RevertedTurnResult`は`src/neontof/application/turn_models.py`のLifecycle symbolとしてP1-03で所有し、`target_turn_id`、`revert_event_id`、`response`を返す。Undoのresponseは`turn_requests`/cacheへcompleteせず、coordinatorからEngine、routeへ直接forwardする。P1-08はnormal / undoのResponseRebuilder builderとdocument/serializer契約を提供するだけで、rebuilderを実行しない。

`TurnResponseDocument`はnormal / undoのvalidated semantic result、narrative、public projection、statusを表し、`ResponseSerializer`は指定された`RequestedMediaType`に対するnon-empty strict UTF-8 `StrictBytes`だけを返す。serializerはmedia typeを勝手に変更せず、`CachedTurnResponse`へ渡す前にCoordinatorとStoreが同じstrict UTF-8 decode、non-empty、requested media/type contractを検証する。`build_response_rebuilder()`と`build_undo_response_rebuilder()`はこの契約を実装するcallableを一つずつ組み立てるfactoryであり、P1-08はfactoryとdocument/serializer契約を提供するだけで実行主体ではない。Coordinatorだけがnormal Turnまたはrecoveryのfinal時に対応するrebuilderを一回呼び、検証済み`CachedTurnResponse`をnormal/recoveryの一回の`complete()`へ渡す。UndoではCoordinatorが`UndoResponseRebuilder`を一回呼んで`RevertedTurnResult`を直接返し、`complete()`を呼ばない。P1-11のcomposition root（`src/neontof/app.py`）はP1-11の`make_response_serializer()`からnormal / undo rebuilderを一回ずつ構築してconstructorへinjectし、route / serializerはrebuilder、`EventStore.append()`、`TurnRequestStore.complete()`を実行しない。

通常Turnのprovider failure、semantic validation failure、candidate validation failureを`PreparedTurn(terminal_status="aborted")`へ写像する場合は、abortを返す前にcanonical failure `StagedResponseSeed`を一度だけ構成し、`encode_staged_response_seed(seed)`から`build_staged_recovery_payload(*, identity=..., response_payload=...)`を通してversion 2のouter bytesを作る。P1-12の`scenario_candidate_conflict`も同じ失敗seed経路を使い、`staged_recovery_payload`を`None`にしない。したがってnormal `committed` / normal `aborted`は常にv2 staged outer payloadをstageし、append後complete前のretryは保存済み同一outer/inner bytesを再利用する。

### Payload boundary確認点

既存`FrozenJsonValue`のcomposite value round-tripをP1-00で推測実装しない。P1-08がsemantic resultのpayloadをlosslessにmaterializeするために既存Phase 0 semantic contractでは不足すると判明した場合、P1-08開始前に停止し、Phase 0 semantic contractの改訂または別の承認済みraw boundaryの確定を待つ。この計画からProduct Plan、ROADMAP、ADR、P0契約本文は変更しない。

Pipeline順序を固定する。

1. Player InputをTranscriptへappendする。
Player InputのTranscript appendはEvent append critical sectionの外で別の`_write` transactionとして行い、後続失敗でEventが0件でも観測記録を残せるようにする。
2. `TurnEngine.submit(command)` / `resume(command)`だけがcommandからpre-claim `TurnRequestIntent`、`TurnPreparationContext`、initial recovery payloadを作る。`base_event_sequence`と`staged_recovery_payload`は渡さず、claim、full Event read、`TurnStatus`確認はcoordinatorへ委譲する。Engineは`prepare = self.bind_turn_preparation(context=context)`をexecute呼出し前に作り、`TurnLifecycleCoordinator.execute(intent=intent, prepare=prepare)`へ注入する。routeは派生値を作らず、P1-08から`TurnRequestStore.claim()`を呼ばない。
3. coordinatorがregistry判定とdurable claimを`event_boundary_lock`内で行い、`NewClaim`、`ExistingProcessingClaim`、`ExistingFinalClaim`を分岐する。registryの`ExistingActiveTurn` hitだけは既に前処理が保持するlockを奪わず`ProcessingTurnResult(response=None, status="processing", http_status_code=202)`として返す。registry miss後の`ExistingProcessingClaim`はこのvariantを返さず、recovery state machineへ入る。P1-08からEventを直接appendしない。
4. `NewClaim`の直後、同じ`event_boundary_lock`内で`EventStore.read_campaign(record.campaign_id)`を一度だけ先に呼び、完全なvalidated `tuple[DomainEvent, ...]`を、executeへ注入済みの`prepare: TurnPreparation`（P1-08の`bind_turn_preparation(*, context=...)`が返すcallback）へ渡す。このreadはclaim transaction内のsame-connection readとは別のpreparation readであり、prepare後へ遅延させず、filtered sliceやsnapshotで代用しない。
5. bound callbackはP1-08の具体的なpreparationとして`rebuild_projection(campaign_events)`とEvent-derived `PublicContext`を作り、closureのimmutable contextと受け取ったvalidated campaign tupleのcurrent identity / `base_event_sequence`境界からAlias、target、condition、statusを解決する。ambiguousならmodel call前に`PreparedTurn(effect_candidates=(), terminal_status="awaiting_player", scenario_end=None, abort_reason=None, staged_recovery_payload=None)`を返し、coordinatorはstarted prefixの後に`TurnAwaitingPlayer`を最後に置き、effectsなしで止める。
6. bound callback内でcontext.input_text、public Context、deterministic dice、budgetを順に確定し、Gatewayを1 logical call、provider invocation 1回だけ実行する。request / response / timeout / error / usageはpurpose-specific allowlistでTranscript / Telemetryへ記録し、append critical sectionの内側へ入れず別の`_write` transactionとする。raw provider body/error/causeは保存せず、retry recordはPhase 1通常Turnでは作らない。instance field、global、Transcriptからinputを補わず、closure外の別commandのcontextを参照しない。
7. `validate_semantic_result()`とRule / reference / Evidence / Visibility validationを行い、検証済み`TargetNumber` / `StatusCondition`を`materialize_accepted_result(identity=identity, outcome=..., projection=..., context=..., dice_result=...)`へ渡す。materializerはmetadataを受けず、current `identity`とEvent-derived projection/contextからcurrent active targetのFactIdを得てpre-ID `PreparedEffect`列を返す。Dice producerも`materialize_dice_event(identity=identity, result=...)`として同じcurrent identityを使い、resumeの新しいinput digestや過去Turnからenvelopeを推測しない。P1-09が有効な場合はcontext.provisional_reference_textだけを明示的なpromotion referenceに使う。
8. target/conditionのassertionを最終pre-ID effect candidatesより前に決定する。target変更時は既存active FactのEvent-derived `fact_id`を対象に`FactSuperseded`を先に、続けて`FactAsserted(predicate="target_number")`をcandidateへ含め、同値ならtarget Factを追加しない。conditionの初回は`FactAsserted(predicate="condition")`、置換は既存`FactSuperseded`を使う。active targetが複数、壊れている、missing/不明なFactId、`PublicFact` validator不合格、target `1`、未知condition、schema version `2`はfail-closedとする。ここでeffect_candidatesを確定し、`event_id_sequence`より後にこの判断を行わない。
9. `PreparedTurn`をcoordinatorへ返す。`PreparedTurn.staged_recovery_payload`がnon-NULLなら`stage()`を一度だけ行い、最終`effect_candidates`確定後に`event_id_sequence(identity, prepared)`を一度、`utc_occurred_at()`を一度呼ぶ。その後に`turn_event_factory(identity, prepared, campaign_events, occurred_at, event_ids)`を一度呼ぶ。factoryだけが各`PreparedEffect`へEvent ID / `OccurredAt`を割り当てて`EventDraftBody`、`EventDraft`、`EventBatch`を構成する。contextはこのcallbackのclosureから外へ漏らさない。
10. coordinatorがsubmit/resume prefixを組み立て、candidate full validationを行い、唯一のapplication-level `EventStore.append()` callsiteをcandidateがある場合だけ一度使う。P1-08から直接appendしない。
11. append成功後は、NewClaim直後に一度取得済みのpreparation tupleを置き換えず、commit結果のauthority検証とresponse rebuildのために`EventStore.read_campaign(campaign_id)`で全validated `DomainEvent`列を読む。このpost-append authority readはpreparation readの代替ではなく、filtered slice、snapshot、coordination record、observationを入力にしない。
12. `ResponseDocumentBuilder` / `build_response_document()`が全Event read、status、選択済みpayload、rebuild済みpublic projection/resource projection/dice projection/resultから、P1-08所有のvalidated `TurnResponseDocument`を組み立てる。`target_number`と`conditions`はvalidated `PublicFact`から`select_public_target_and_conditions()`で一度導出し、P1-08 core pathの`scenario_outcome`は`None`とし、P1-12 serial extensionでだけreplayed `FactRecord`を`ScenarioOutcomeFact`として検証する`select_scenario_outcome()`から一度導出する。narrative、suggested_actions、cost_microusd、processing_status、correctionsもtyped documentへ含める。
13. validated Narrativeとpost-public audit結果をcorrectionとしてresponse documentへ含める。auditはEventをrollbackまたはState変更しない。
14. `TurnLifecycleCoordinator`だけが`ResponseRebuilder`を一回呼び、P1-08のtyped documentをP1-11のserializerへ渡してJSON/SSEまたはbuffered frame bytesを完成させ、`CachedTurnResponse`のstatus code、media、non-empty strict UTF-8 body bytesを検証する。P1-03はこのpayloadをopaque bytesとして運び、JSONを解釈しない。
15. coordinatorだけが`TurnRequestStore.complete(*, request_key=..., expected_version=..., status=..., response=...)`を一回呼ぶ。cache commit前にHTTP adapterへframeを渡さず、P1-08は`complete()`を呼ばない。
16. cache commit後だけHTTP adapterへ公開する。SSEとbufferedは同じ完成済みframe bodyから生成し、routeはcoordinatorからforwardされたcache bytesを再serializeしない。replayでProvider、Dice、Event append、frame再生成を行わない。

`ProposedResourceChanged`、`ProposedCharacterMoved`、`ProposedClockAdvanced`、`ProposedFact`だけをmaterializeする。不明Event typeを追加しない。

通常TurnはGatewayを1 logical call、Model callを1回、Provider invocationを1回だけ許可する。`FakeProvider`またはRecorded Fixtureはdependency injectionで`TurnEngine`/pipelineへ渡し、API keyなし・external networkなしで同じ`TurnPreparation`を検証できるようにする。retryは0回、model由来clarification completionはPhase 1受入れ対象外であり、ambiguityはmodel call前の`awaiting_player`で止める。P1-08のmodel request / response / Provider observation testはこのsectionで所有し、P1-03のinjected player input observation testと混ぜない。

`tests/integration/test_complete_fake_turn.py::test_complete_fake_turn_materializes_target_and_condition_facts_through_coordinator_and_replay`は、validated `TargetNumber` / `StatusCondition`をsemantic validationへ渡し、materializerが`FactAsserted` / `FactSuperseded` candidateを作り、`TurnLifecycleCoordinator`のcandidate validationと唯一のappendを通し、Event replayでvalidated `PublicFact` / `PublicProjection`を再構築して、P1-08の`TurnResponseDocument.target_number` / `conditions`までを一度通す。P1-11のpresentation変換とBrowser JSON/DOMへの変換は別testとし、このP1-08 testの依存にしない。fixtureへFactを直接置くだけのsetup、ProjectionやPublicFact/PublicProjection/TurnResponseDocumentへの直接代入、coordinatorを迂回するappendではGreenにできないことをtest contractにする。

`tests/integration/test_complete_fake_turn.py::test_consecutive_turns_supersede_active_target_before_asserting_new_target`は、連続する二つのTurnをsemantic validation / materializer / coordinator candidate validation / append / full Event replayの順に通す。2回目のtarget変更では、Event-derivedな旧active targetの`fact_id`を対象に`FactSuperseded`を先にcandidateへ入れ、その直後に新しい`FactAsserted(predicate="target_number")`を入れる。replay後のactive targetは1件だけ、P1-08の`TurnResponseDocument` rebuildは成功し、P1-11のpresentation layerとBrowser JSON/DOMはこのtestの依存にしない。targetが変わらない場合はtarget Factを追加せず、active targetが複数または壊れている場合はfail-closedとする。直接Projectionを更新したfixture、Factを直接置いたfixture、P1-11 presentation変換の迂回ではGreenにできない。

`tests/application/test_turn_responses.py::test_turn_response_document_contains_dice_projection_result_typed_presentation_inputs_and_scenario_outcome_none_core_path`は、full Event replayから得た`DiceProjection` / `DiceResult` / `PublicProjection` / `PublicResourceProjection`とvalidated `narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`、`target_number`、`conditions`、`scenario_outcome=None`を`ResponseDocumentBuilder`へ渡し、P1-08所有のtyped `TurnResponseDocument`に揃うことを確認する。実ScenarioRuntimeの`scenario_outcome` candidate、Fact append、replay、`select_scenario_outcome()`によるsuccess/failure復元はP1-12のnamed testで検証し、P1-11の`PublicSessionView`やBrowser DOMはこのtestへ持ち込まない。P1-08ではcore response bundleがpublication入力を欠かず、scenario outcomeが未接続時に`None`であることだけを検証する。

**テストファースト**

- `test_invalid_event_type_is_rejected_before_append`
- `test_unknown_entity_is_rejected_before_append`
- `test_dice_projection_rebuilds_from_authoritative_event_fields`
- `test_materializers_return_pre_id_prepared_effect_candidates_without_event_id_or_occurred_at`
- `test_prepared_effect_rejects_mismatched_turn_identity_before_event_id_allocation`
- `test_submit_command_maps_every_intent_identity_field_and_initial_recovery_payload`
- `test_resume_command_maps_existing_turn_identity_and_requested_media`
- `test_turn_engine_does_not_read_event_store_for_resume_identity_validation`
- `test_resume_context_and_root_conflict_is_rejected_by_claim`
- `test_derive_submit_turn_id_has_fixed_vector`
- `test_initial_recovery_payload_excludes_raw_input_api_key_and_provider_output`
- `test_initial_recovery_payload_codec_round_trips_canonical_bytes`
- `test_initial_recovery_payload_codec_rejects_tampered_identity_or_media`
- `test_recovery_payload_union_round_trips_initial_and_staged_variants`
- `test_recovery_payload_codec_rejects_duplicate_keys_trailing_tokens_and_secret_bytes`
- `test_staged_response_seed_rejects_raw_provider_secret_and_event_derived_projection_duplication`
- `test_staged_response_seed_codec_rejects_unknown_fields_and_identity_tamper`
- `test_initial_payload_is_built_once_before_claim_and_existing_claim_payload_is_discarded`
- `test_restart_reuses_saved_staged_recovery_payload_without_rebuilding`
- `test_append_before_complete_crash_reuses_staged_response_seed_and_cached_presentation_without_reexecution`
- `test_bound_preparation_keeps_interleaved_input_context_isolated`
- `test_turn_engine_binds_prepare_before_coordinator_execute`
- `test_turn_preparation_receives_full_campaign_events_before_projection_and_materialization`
- `test_complete_fake_turn_materializes_target_and_condition_facts_through_coordinator_and_replay`
- `test_consecutive_turns_supersede_active_target_before_asserting_new_target`
- `test_turn_response_document_contains_dice_projection_result_typed_presentation_inputs_and_scenario_outcome_none_core_path`
- `test_narrative_only_result_appends_no_state_effect_event`
- `test_proposed_events_are_appended_only_after_validation`
- `test_all_effect_events_and_turn_commit_are_atomic`
- `test_provider_failure_leaves_no_effect_events`
- `test_provider_semantic_and_candidate_abort_builds_canonical_v2_staged_failure_seed`
- `test_model_request_observation_is_recorded`
- `test_model_response_observation_is_recorded`
- `test_provider_invocation_is_once_for_normal_turn`
- `test_fake_provider_is_injected_without_api_key`
- `test_model_failure_preserves_request_response_and_provider_observations`
- `test_model_derived_clarification_completion_is_outside_phase_1_acceptance`
- `test_rejection_aborts_without_effect_events`
- `test_suggested_actions_are_preserved`
- `test_mentioned_details_are_not_parsed_from_narrative`
- `test_duplicate_request_returns_cached_turn_result`
- `test_all_frames_complete_before_turn_request_cache_commit`
- `test_turn_request_cache_commits_before_http_publication`
- `test_sse_and_buffered_use_the_same_completed_frame_body`
- `test_cached_replay_is_byte_for_byte_without_execution`
- `test_turn_engine_forwards_cached_response_bytes_without_reserializing`
- `test_processing_turn_result_has_no_response_and_maps_to_http_202`
- `test_build_response_rebuilder_validates_document_and_serializes_once`
- `test_build_undo_response_rebuilder_receives_target_status_and_id_without_rederiving`
- `test_response_serializer_emits_valid_japanese_utf8_bytes_for_requested_media`
- `test_response_serializer_rejects_invalid_utf8_cached_body`
- `test_coordinator_rebuilds_response_and_completes_once`
- `test_p1_08_has_no_direct_claim_or_complete_callsite`
- `test_p1_08_has_no_direct_eventstore_append_or_request_complete_callsite`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/application/test_turn_responses.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py tests/test_repository_contracts.py -q
```

実装前のfocused commandではmissing moduleを、atomicity実装途中では1件以上のeffect Eventが残り期待`0`となるassertion failureを確認する。cache commit前公開、SSE/buffered同一body、byte-for-byte replayの境界も失敗理由として確認する。

**完了条件**

- valid Fake turnが`committed`
- invalid Eventが`rejected`または`aborted`
- 連続Turnでtarget変更時は`FactSuperseded(existing_fact_id)` → `FactAsserted(predicate="target_number")`の順にcandidateをappendし、full replay後のactive targetが1件、target不変時は追加candidateなし、複数/破損targetはfail-closedとなる。P1-08のcore pathでは`scenario_end=None`、`scenario_outcome=None`のtyped response bundleまでで完了し、実ScenarioRuntimeの`scenario_outcome` FactAsserted candidate、同じappend、replay後のsuccess/failure復元はP1-12で検証する。P1-08のintegrationはvalidated `PublicFact` / `PublicProjection`と`TurnResponseDocument`までで完了し、presentation / Browser表示はP1-11/P1-13で検証する。
- failure時effect Event count `0`
- Narrative-only時Resource / Location / Clock / Fact projectionが不変
- `TurnLifecycleCoordinator`だけがnormal Turnまたはrecoveryの全frameのcanonical body完成後に`ResponseRebuilder`、`CachedTurnResponse` validation、`TurnRequestStore.complete()`をそれぞれ一回行い、cache commit後だけHTTP adapterが公開する。初回normal `committed` / normal `aborted`はv2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）を必須として、初回normal `awaiting_player`はv2 staged outer payloadを優先し、無い場合だけv1 initial outer bytes + P1-08適用のtyped defaultを使う。初回normal terminal / awaiting_playerと初回recovery abortはそのexecute呼出し内で`append / rebuild / complete = 1 / 1 / 1`、各Event append後〜complete前の再試行はcandidateなしで`0 / 1 / 1`とし、Eventを二重appendしない。recovery abortではcurrent identity一致のowned_suffix actual `recovery_aborted_event_id`をnormal `aborted_event_id`と分離し、`select_response_payload()`が保存済みversion 1のinitial payloadを選ぶ。Undoでは`UndoResponseRebuilder`を一回実行して`RevertedTurnResult`を直接返し、`TurnRequestStore.complete()`を呼ばない。P1-08はbuilder / semantic pipelineを提供するだけで、EventStore.appendまたはTurnRequestStore.completeを呼ばない。current identityに一致するprefixにaccepted/terminalがないsubmit recovery candidateは`PlayerInputAccepted -> recovery TurnAborted`、current identityに一致するprefixにaccepted/awaitingがあり、同じcurrent identityに一致するowned_suffixに`TurnResumed`/terminalがないcandidateはrecovery `TurnAborted`だけであり、prefix acceptedを再appendしない。metadata未確定をfaultなしで継続するexecuteはCASからappend/rebuild/complete `1 / 1 / 1`、CAS後append前crashのpartial attemptは`0 / 0 / 0`、次回executeはrecovery abort `1 / 1 / 1`とする。
`TurnEngine.submit(command: TurnCommand)` / `resume(command: ResumeTurnCommand)`はcommandからdigest、server-owned `turn_id`、requested media、immutable `TurnPreparationContext`、P1-08 `build_initial_recovery_payload(...)`を各一回構成してからclaimし、`bind_turn_preparation(context=context)`のclosure以外からinputを読まない。initial payloadはclaim前に一回だけ供給し、ExistingProcessing/ExistingFinalでは捨てて保存bytesを使う。interleaved context、fixed turn ID KAT、initial/staged payloadのraw input/API key/provider output非包含、保存staged presentationのrestart再利用がnamed testsで確認される。
- SSEとbufferedが同じ完成済みframe bodyから生成され、replayがcache body bytesをbyte-for-byteで返す
- Suggested Actionsが2〜4件
- `tests/test_repository_contracts.py`のmanifest/forbidden guardがexit `0`

P1-08 Gateでは`build_initial_recovery_payload(...)`を各inbound executeのclaim前に一回だけ呼び、NewClaim以外では供給bytesを捨てて保存済みpayloadを再利用すること、`RecoveryPayload`のinitial/staged unionをP1-08 response codecだけがdecodeすることを確認する。`TurnResponseDocument`のcore pathは`scenario_outcome=None`を保持し、P1-12のactual candidateへ依存しない。success/failureの`ScenarioOutcomeFact` candidate、append、full replay、`select_scenario_outcome()`による復元はP1-12 Gateだけの責務であり、P1-08の前提・testにせず、fixtureへの直接挿入を許可しない。

**契約確認点**

C-01はAを採用する。通常TurnのModel call上限は1回とする。model由来clarification completionはPhase 1受入れ対象外とする。P1-03/P1-08はこの決定に従う。

P1-08ではpre-model ambiguityだけを`TurnAwaitingPlayer`として扱い、request / response / Provider observationを所有し、`TurnLifecycleCoordinator`へLifecycleを委譲する。Phase 0 contractの変更はこの計画から行わない。

**コミット境界**

```powershell
git add -- src/neontof/application/event_materializer.py src/neontof/application/semantic_pipeline.py src/neontof/application/turn_responses.py src/neontof/application/turn_engine.py src/neontof/application/turn_models.py tests/application/test_event_materializer.py tests/application/test_semantic_pipeline.py tests/application/test_turn_responses.py tests/integration/test_complete_fake_turn.py tests/integration/test_model_failure_atomicity.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-01 Aの境界（通常TurnのModel call上限`1`、model由来clarification completionはPhase 1受入れ対象外）と上記pathのtests、implementationを1つのlogical GREEN commitへまとめる。focused commandのfailure `0`、Event batch atomicity、dice replay、normal provider invocation count `1`、request / response / Provider observationの保持、`build_response_rebuilder()`のdocument/serializer一回、normal/recovery coordinatorのrebuildとcomplete一回、Undoのrebuild一回・complete 0回、cache commit前公開なし、byte-for-byte replayを確認して着地させる。command mapping全field、fixed `derive_turn_id` KAT、P1-08 `build_initial_recovery_payload(...)`のclaim前一回、immutable `TurnPreparationContext`のinterleaved isolation、`bind_turn_preparation(context=context)`の二引数callbackも同じfocused commandで検証する。P1-08のcore pathでは`PreparedTurn.scenario_end=None`、`scenario_outcome=None`のtyped response bundleまでを検証する。genericな`PreparedTurn.scenario_end`の伝搬、scenario end時だけの`TurnEventIdSequence`追加ID、`TurnEventBatchFactory`だけによる`TurnCommitted -> SessionEnded`（`reason="completed"`）はP1-03の`test_prepared_turn_scenario_end_is_materialized_only_by_turn_event_factory`とP1-12のintegration/Gateで検証し、P1-08のfocused commandはactual ScenarioRuntime candidateへ依存しない。`src/neontof/application/turn_models.py`はP1-03 Lifecycle commitの後に同時編集なしで必要な場合だけModify/stageし、P1-08と同一作業単位で重ねて編集しない。

```text
feat: 検証済みproposalをLifecycle Coordinatorへ委譲するTurn Engineを実装する
```

---

## P1-09: provisional_detail Projection

**作成**

- `src/neontof/application/provisional_details.py`
- `tests/application/test_provisional_details.py`
- `tests/integration/test_provisional_detail_lifecycle.py`

**変更**

- `tests/test_repository_contracts.py`
- `src/neontof/application/turn_engine.py`（P1-08が作成したbound preparation callbackをC-02承認後にserial Modify/stageするproduction integration path）
- `tests/integration/test_complete_fake_turn.py`（P1-08が作成したintegration pathのserial Modify）

P1-09のproduction manifest追加は`src/neontof/application/provisional_details.py`だけである。`PreparedEffect`、`PreparedTurn`、`TurnEventBatchFactory`、`turn_engine.py`はP1-03/P1-08の所有pathであり、P1-09はC-02承認時だけ既存`turn_engine.py`のbound preparationをserialにModify/stageする。P1-09は新しいownerやproduction manifest entryを追加せず、C-02延期時はこのmodule/type/importと`turn_engine.py`変更を作らない。

P1-09は`EventMaterializationInput`をimportしない。P1-08が作成した`tests/integration/test_complete_fake_turn.py`は、P1-08のcommit後にP1-09がserialにModify/stageする共有integration pathである。P1-09は`TurnLifecycleCoordinator`、`turn_models.py`、`turn_engine.py`のownerやapplication-level append callerを増やさず、同じ`turn_engine.py`をP1-12と同時編集・同時stageしない。

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
    effect_candidates: tuple[PreparedEffect, ...]
    message: str | None

def project_provisional_details(
    *,
    projection: Projection,
    current_scene_id: SceneId | None,
) -> ProvisionalProjection: ...

def materialize_provisional_details(
    *,
    identity: TurnRequestIdentity,
    details: Sequence[ProvisionalDetail],
) -> tuple[PreparedEffect, ...]: ...

def promote_provisional_detail(
    *,
    identity: TurnRequestIdentity,
    reference_text: str,
    provisional: ProvisionalProjection,
    projection: Projection,
) -> PromotionOutcome: ...
```

`mentioned_details`はNarrative parseではなくSemantic Result fieldからのみ受け取る。`materialize_provisional_details(*, identity, details) -> tuple[PreparedEffect, ...]`と`promote_provisional_detail(*, identity, reference_text, provisional, projection) -> PromotionOutcome`は、current `TurnRequestIdentity`と既存Projectionを根拠に、Event ID / `OccurredAt`を持たないpre-ID `PreparedEffect`候補だけを返す。candidateのcampaign/session/scene/turn envelopeはidentityから構成し、identity mismatchや過去Turn/global contextからの推測は拒否する。
この`effect_candidates`はC-02承認時だけ、P1-08の`TurnEngine.bind_turn_preparation(context=context)`が返す二引数bound callbackでP1-08のsemantic/dice candidatesへ合流して最終`PreparedTurn.effect_candidates`にする。候補確定後に`event_id_sequence` → `utc_occurred_at` → `TurnEventBatchFactory`だけが`EventDraftBody` / `EventDraft` / `EventBatch`を構成する。P1-09はEventStore、coordinator、別lock、sequence割当、別EventStore.append callerを持たない。

C-02承認時のbound integrationは、`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`が返す二引数bound callback内で、Semantic Result由来のcore candidatesへ`materialize_provisional_details(identity=identity, details=...)`と必要な`promote_provisional_detail(identity=identity, reference_text=context.provisional_reference_text, provisional=..., projection=...)`の結果を順序付きで合流する。P1-09が独自のprepare、Event ID allocation、factory、candidate validation、appendを持つことはない。C-02延期時はP1-09のmodule/type/importを作らず、P1-12はP1-08のbase `bind_turn_preparation(context=context)`から独立にScenario candidatesだけを加える。

`project_provisional_details()`は現在Sceneと一致するactive Factだけを返す。Scene終了後もEventとTranscriptは残るがContextへ入れない。

昇格時は既存Canonとsubject/predicate/valueを比較する。矛盾時は上書きせず`conflict`を返す。成功時はprovisional Factの`FactSuperseded`とcanonical `FactAsserted`を同じpre-ID candidate列へこの順で入れ、P1-08のcandidate validationを通す。未採番candidateをこのWPで`EventBatch`へ包まず、Event ID / `OccurredAt`付きのEventBatch構成とappendは既存のTurnEventBatchFactory / coordinatorだけが行う。

**テストファースト**

- `test_mentioned_bookshelf_is_available_next_turn`
- `test_materialize_provisional_details_returns_pre_id_effect_candidates`
- `test_provisional_effect_rejects_mismatched_turn_identity`
- `test_provisional_effect_candidates_merge_into_bound_preparation_before_event_id_allocation`
- `test_first_mentioned_detail_uses_approved_id_schema`
- `test_narrative_without_mentioned_detail_creates_nothing`
- `test_exact_label_reference_promotes_detail`
- `test_conflicting_canon_is_not_overwritten`
- `test_unreferenced_detail_disappears_after_scene_end`
- `test_transcript_retains_detail_after_scene_end`
- `test_gm_only_provisional_detail_never_enters_player_context`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py tests/integration/test_complete_fake_turn.py tests/test_repository_contracts.py -q
```

期待REDはmissing module、manifest追記漏れ、未許可path。scene filter未実装時は終了Sceneのdetail件数`1`に対し`0`期待の失敗。

**完了条件**

本棚fixtureで、次Turnに1件、昇格後canonical 1件、Scene終了後provisional 0件、Transcript narrative 1件が成立する。C-02承認時はprovisional materializationとpromotionがcurrent identityを使ったpre-ID `PreparedEffect`候補だけを返し、P1-08が作成した`TurnEngine.bind_turn_preparation(context=context)`のbound preparationへ合流後に`event_id_sequence` → `OccurredAt` → `TurnEventBatchFactory` → candidate validation → coordinator唯一appendでEvent Logへ入ることを確認する。C-02延期時はP1-09のmodule/type/importと`turn_engine.py`変更を作らず、このcompletionを要求しない。いずれの分岐でもP1-03のappend caller数を増やさず、`tests/integration/test_complete_fake_turn.py`と`tests/test_repository_contracts.py`のmanifest/forbidden guardもexit `0`となる。

**契約確認点**

C-02が未承認なら、P1-09のfocused testをGREENにせず、`ProvisionalDetail.id`、reserved Fact value、first-mentioned fixtureを決めない。C-02承認後にだけ承認済みschemaでtest-firstを再開する。

**コミット境界**

```powershell
git add -- src/neontof/application/provisional_details.py src/neontof/application/turn_engine.py tests/application/test_provisional_details.py tests/integration/test_provisional_detail_lifecycle.py tests/integration/test_complete_fake_turn.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、C-02 decision gate承認後、P1-08 commitを先に着地させてから上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。first-mentioned test、current identity一致、pre-ID candidate、P1-08 `TurnEngine.bind_turn_preparation(context=context)`が返す二引数callbackへの合流、Fact schema、scene lifetime、conflict handling、`context.provisional_reference_text`の明示利用をfocused commandで確認して着地させる。`turn_engine.py`はP1-08のbound preparationをP1-09がserialにModify/stageする場合だけこのcommitへ含め、P1-12と同時編集・同時stageしない。P1-09はC-02承認前に実装せず、P1-03の`EventStore.append()` caller allowlistを変更しない。

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

export type StatusCondition = "injured" | "shaken";

export type ScenarioOutcome = "success" | "failure";

export interface PublicSessionPresentation {
  narrative: readonly string[];
  suggested_actions: readonly string[];
  cost_microusd: number;
  processing_status: ProcessingStatus;
  corrections: readonly string[];
}

export interface PublicSessionView extends PublicSessionPresentation {
  campaign_id: string;
  session_id: string;
  scene_id: string | null;
  turn_status: "pending" | "running" | "awaiting_player" | "committed" | "aborted";
  location: string | null;
  hp_current: number;
  hp_max: number;
  resource_label: string;
  resource_current: number;
  resource_max: number;
  inventory: readonly string[];
  objective: string;
  target_number: number | null;
  conditions: readonly StatusCondition[];
  scenario_outcome: ScenarioOutcome | null;
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
}

export interface ProcessingFrame {
  readonly type: "processing";
  readonly data: "accepted" | "building_context" | "invoking_model" | "validating" | "committing";
}

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

export interface SemanticResultFrame {
  readonly type: "semantic_result";
  readonly data: JsonValue;
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
  readonly data: "running" | "awaiting_player" | "aborted";
}

export type Phase0TransportFrame =
  | SemanticResultFrame
  | NarrativeFrame
  | DoneFrame;

export type TurnStreamFrame =
  | SemanticResultFrame
  | NarrativeFrame
  | DoneFrame
  | ProcessingFrame
  | StateFrame
  | CorrectionFrame
  | ErrorFrame;

export interface PendingTurnRetry {
  readonly session_id: string;
  readonly request_key: string;
  readonly turn_request_id: string;
  readonly input_text: string;
}

export function savePendingTurnRetry(pending: PendingTurnRetry): void;
export function loadPendingTurnRetry(): PendingTurnRetry | null;
export function clearPendingTurnRetry(): void;

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

P1-10の`Phase0TransportFrame`はPhase 0のflat discriminated unionをそのまま写し、`SemanticResultFrame`、`NarrativeFrame`、`DoneFrame`をnested response objectや別のenvelopeへ包まない。`DoneFrame.data`はPhase 0 transportのstatus literal（`"running" | "awaiting_player" | "aborted"`）を保持し、`PublicSessionView`を代入しない。P1-10で追加する`ProcessingFrame`、`StateFrame`、`CorrectionFrame`、`ErrorFrame`も同じtop-level `type` discriminatorを持つflat union memberとする。`StateFrame`はcommit後の`PublicSessionView`だけを運び、Stateを直接更新しない。

`PendingTurnRetry`と`savePendingTurnRetry()`、`loadPendingTurnRetry()`、`clearPendingTurnRetry()`は`client/src/retry.ts`に置く。`PendingTurnRetry`は`localStorage`に保存できる公開retry recordであり、`session_id`、opaqueな`request_key`、canonicalな`turn_request_id`、未加工のplayer inputだけを持つ。reloadまたは一時的なtransport failure後のretryは同じ`request_key`と`turn_request_id`を再利用し、新しいTurnやprovider invocationを作らない。terminal responseまたはcached replayを受け取った後だけclearし、API key、secret、raw Model response、full Projection、Transcript / Telemetryを`localStorage`へ保存しない。storage値のparseとschema validationに失敗した場合はretryせず、既存sessionの再読込だけを行う。

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
- `client/src/retry.ts`
- `client/tests/session-view.spec.ts`
- `client/tests/reload.spec.ts`
- `client/tests/complete-run.spec.ts`

**変更**

- `client/src/styles.css`（P1-10aで作成した既存styleへtarget/conditionsの表示領域を追加）

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
#target-number
#conditions
#scenario-outcome
#clock
#dice
#cost
#processing-status
#corrections
```

`client/src/render.ts`は`StateFrame.data.target_number`を`#target-number`へ表示し、`null`なら空状態を表示する。`StateFrame.data.conditions`は安定順の`StatusCondition[]`を`#conditions`へ表示し、空配列なら空状態とする。`StateFrame.data.scenario_outcome`は`#scenario-outcome`へ表示し、`null`なら空状態とする。`client/src/stream.ts`、`client/src/api.ts`、`client/src/retry.ts`はこのflat snake_case shapeをそのまま運び、`PublicDiceView`へtargetやcondition/outcomeを追加しない。reload/replayではEvent由来のsubset（campaign/session/scene/turn、location、hp、resource、target_number、conditions、scenario_outcome、clock、dice）を再構築し、Event Logにないpresentation fieldsは明示的なtyped defaultまたは同じHTTP responseから渡されたpresentationを使う。full `PublicSessionView`のEvent-only同一性は主張しない。

**テストファースト**

- `test_processing_status_changes_immediately_after_submit`
- `test_session_view_displays_all_required_state`
- `test_session_view_renders_target_number_and_conditions`
- `test_session_view_renders_replayed_scenario_outcome`
- `test_suggested_action_populates_input`
- `test_reload_restores_event_derived_session_subset`
- `test_reload_restores_target_number_and_conditions`
- `test_reload_restores_replayed_scenario_outcome`
- `test_reload_retry_reuses_pending_request_key_and_turn_request_id`
- `test_secret_sentinel_is_absent_from_dom`
- `test_complete_run_reaches_success_or_failure_end`
- `test_replay_preserves_target_number_and_conditions`
- `test_replay_preserves_scenario_outcome`

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
git add -- client/src/render.ts client/src/stream.ts client/src/retry.ts client/src/styles.css client/tests/session-view.spec.ts client/tests/reload.spec.ts client/tests/complete-run.spec.ts
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
- `src/neontof/web/response_serializer.py`
- `src/neontof/application/runtime.py`
- `src/neontof/application/public_view.py`
- `src/neontof/application/narrative_audit.py`
- `tests/web/test_turn_routes.py`
- `tests/web/test_streaming.py`
- `tests/web/test_response_serializer.py`
- `tests/application/test_narrative_audit.py`
- `tests/application/test_public_view.py`

**変更**

- `src/neontof/app.py`
- `src/neontof/config.py`
- `src/neontof/main.py`
- `tests/test_app.py`
- `tests/test_main.py`
- `tests/test_repository_contracts.py`

P1-11のproduction manifest追加は`src/neontof/web/__init__.py`、`src/neontof/web/contracts.py`、`src/neontof/web/routes.py`、`src/neontof/web/streaming.py`、`src/neontof/web/response_serializer.py`、`src/neontof/application/runtime.py`、`src/neontof/application/public_view.py`、`src/neontof/application/narrative_audit.py`の8つである。P1-11はResponseSerializerをwireするだけで、`EventStore.append()`と`TurnRequestStore.complete()`のcallerにならない。
**公開型とシグネチャ**

```python
from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Annotated, Literal, Sequence, TypeAlias

from pydantic import Field
from pydantic import StrictBytes, StrictInt, StrictStr
from neontof.application.bootstrap_service import BootstrapApplicationService, BootstrapEventBuilder
from neontof.application.turn_models import (
    OpaqueRequestKey,
    RequestedMediaType,
    TurnEventBatchFactory,
    TurnEventIdSequence,
    UndoCommand,
)
from neontof.application.turn_lifecycle import (
    TurnLifecycleCoordinator,
    build_recovery_metadata,
    reserve_recovery_event_ids,
)
from neontof.event_metadata import OccurredAt
from neontof.application.turn_responses import (
    ResponseDocumentBuilder,
    ResponseSerializer,
    TurnResponseDocument,
    UndoResponseDocumentBuilder,
)
from neontof.application.context_builder import ScenarioOutcome, select_public_target_and_conditions
from neontof.rules.minimal_2d6 import StatusCondition, TargetNumber
from neontof.contracts.transport import (
    DoneFrame,
    NarrativeFrame,
    SemanticResultFrame,
    TransportFrame,
)

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
    event_boundary_lock: Lock
    server_clock: Callable[[], int]
    public_static_data: PublicStaticData
    scenario_runtime: ScenarioRuntime
    turn_engine: TurnEngine
    bootstrap_service: BootstrapApplicationService

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

WebTurnStreamFrame: TypeAlias = Annotated[
    SemanticResultFrame
    | NarrativeFrame
    | DoneFrame
    | ProcessingFrame
    | StateFrame
    | CorrectionFrame
    | ErrorFrame,
    Field(discriminator="type"),
]

Phase0TransportFrame: TypeAlias = TransportFrame

class BufferedTurnResponse(ContractModel):
    frames: tuple[WebTurnStreamFrame, ...]

PublicProcessingStatus: TypeAlias = Literal[
    "accepted",
    "building_context",
    "invoking_model",
    "validating",
    "committing",
    "done",
    "failed",
]
NonNegativeMicrousd: TypeAlias = Annotated[StrictInt, Field(ge=0)]

class PublicSessionPresentation(ContractModel):
    narrative: tuple[StrictStr, ...]
    suggested_actions: tuple[StrictStr, ...]
    cost_microusd: NonNegativeMicrousd
    processing_status: PublicProcessingStatus
    corrections: tuple[StrictStr, ...]

class PublicSessionView(ContractModel):
    campaign_id: CampaignId
    session_id: SessionId
    scene_id: SceneId | None
    turn_status: TurnStatus
    narrative: tuple[StrictStr, ...]
    suggested_actions: tuple[StrictStr, ...]
    location: str | None
    hp_current: int
    hp_max: int
    resource_label: str
    resource_current: int
    resource_max: int
    inventory: tuple[str, ...]
    objective: str
    target_number: TargetNumber | None
    conditions: tuple[StatusCondition, ...]
    scenario_outcome: ScenarioOutcome | None
    clock_label: str
    clock_current: int
    clock_max: int
    dice: PublicDiceView | None
    cost_microusd: NonNegativeMicrousd
    processing_status: PublicProcessingStatus
    corrections: tuple[StrictStr, ...]

def build_public_session_presentation(
    *,
    response_document: TurnResponseDocument,
    suggested_actions: tuple[StrictStr, ...],
    cost_microusd: NonNegativeMicrousd,
    processing_status: PublicProcessingStatus,
) -> PublicSessionPresentation: ...

def build_public_session_view(
    *,
    public_projection: PublicProjection,
    public_static_data: PublicStaticData,
    resource_projection: PublicResourceProjection,
    dice_projection: DiceProjection,
    turn_status: TurnStatus,
    presentation: PublicSessionPresentation,
) -> PublicSessionView: ...

def encode_sse(frame: WebTurnStreamFrame) -> bytes: ...

def make_response_serializer(
    *,
    public_static_data: PublicStaticData,
    encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes],
    encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes],
) -> ResponseSerializer: ...

def build_buffered_turn_response(
    frames: Sequence[WebTurnStreamFrame],
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
    input_text: StrictStr
    provisional_reference_text: StrictStr | None = None

class HttpErrorBody(ContractModel):
    code: str
    message: str

def parse_idempotency_key(value: str | None) -> OpaqueRequestKey: ...

def parse_requested_media_type(value: str | None) -> RequestedMediaType: ...

def build_undo_command(
    *,
    runtime: ApplicationRuntime,
    campaign_id: CampaignId,
    session_id: SessionId,
    request_key: OpaqueRequestKey,
) -> UndoCommand: ...

def compose_application_runtime(
    *,
    database: SqliteDatabase,
    event_store: EventStore,
    projection_store: ProjectionStore,
    request_store: TurnRequestStore,
    observation_store: ObservationStore,
    gateway: ModelGateway,
    registry: ApplicationRegistry,
    active_turn_registry: ActiveTurnRegistry,
    event_boundary_lock: Lock,
    server_clock: Callable[[], int],
    public_static_data: PublicStaticData,
    scenario_runtime: ScenarioRuntime,
    build_bootstrap_events: BootstrapEventBuilder,
    turn_event_factory: TurnEventBatchFactory,
    event_id_sequence: TurnEventIdSequence,
    utc_occurred_at: Callable[[], OccurredAt],
    build_response_document: ResponseDocumentBuilder,
    build_undo_response_document: UndoResponseDocumentBuilder,
    encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes],
    encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes],
) -> ApplicationRuntime: ...

def create_app(runtime: ApplicationRuntime | None = None) -> FastAPI: ...
```

P1-11のcomposition rootはP1-12の`ScenarioRuntime`作成・serial `turn_engine.py`拡張後に、`TurnEngine(coordinator=coordinator, gateway=gateway, registry=registry, scenario_runtime=scenario_runtime)`として具体runtimeを注入する。P1-11は`ScenarioRuntime`やbound preparationを先行作成せず、P1-12未着地時にこのconstructorを仮実装しない。`TurnEngine`へ`EventStore`、`ProjectionStore`、`TurnRequestStore`、`ObservationStore`、`ActiveTurnRegistry`を渡さず、これらと`event_boundary_lock`はcoordinator / `ApplicationRuntime`の所有のままにする。

`ApplicationRuntime`は`src/neontof/application/runtime.py`で上記shapeを定義し、process-lifetimeの具体的な`ActiveTurnRegistry`と共有`event_boundary_lock`を所有する。composition rootの`active_turn_registry`引数は起動時に一度だけ構成したその具体instanceをruntimeへ移すための初期化境界であり、runtime作成後に別instanceを生成・差し替えない。既存の`public_static_data`と`scenario_runtime`を保持し、P1-11で削除・改名・別runtimeへの移設をしない。`compose_application_runtime()`だけが`runtime.active_turn_registry`と`event_boundary_lock=runtime.event_boundary_lock`を`TurnLifecycleCoordinator`へ一度だけ渡し、`create_app`は構成済みruntimeとcoordinatorを受け取るだけである。`TurnEngine`と全request handlerへ`ActiveTurnRegistry`を渡さない。`ActiveTurnRegistry`はP1-03の`turn_lifecycle.py`に実装し、新しいgeneric interface/provider abstractionを作らない。Phase 0の`TransportFrame`（`SemanticResultFrame`、`NarrativeFrame`、`DoneFrame`）をimportし、P1-11で追加するのはHTTP表示専用の`ProcessingFrame`、`StateFrame`、`CorrectionFrame`、`ErrorFrame`だけである。importした`DoneFrame.data`のstatus literal（`"running" | "awaiting_player" | "aborted"`）を変更せず、`StateFrame`へ`PublicSessionView`を置く。これらweb-only frameはEventやStateを直接変更せず、`StateFrame.data`はcommit後にrebuildした`PublicSessionView`だけを運ぶ。`PublicSessionView`、`PublicProjection`、`PublicContext`、`PublicStaticData`、`PublicDiceView`だけをpublic view、Gateway request、Narrative auditへ渡し、full `Projection`、raw `ScenarioV1`、raw `CharacterSheetV1`をwireまたはpublic serviceへ渡さない。
`compose_application_runtime()`はP1-11のcomposition rootであり、`src/neontof/app.py`のruntime factoryに置く。exact signatureで受け取る`public_static_data: PublicStaticData`、`encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes]`、`encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes]`から、まず`make_response_serializer(public_static_data=public_static_data, encode_buffered_document=encode_buffered_document, encode_sse_document=encode_sse_document)`を一回だけ構築し、その`ResponseSerializer`を`build_response_rebuilder(build_document=build_response_document, serialize=response_serializer)`と`build_undo_response_rebuilder(build_document=build_undo_response_document, serialize=response_serializer)`へそれぞれ一回だけ渡す。serializerはP1-08のtyped `TurnResponseDocument`から`PublicSessionPresentation`、`PublicSessionView`、`StateFrame`、buffered/SSE bytesを組み立て、これをHTTPへ公開する完成bodyのsourceにする。`turn_event_factory`、`event_id_sequence`、`utc_occurred_at`は同じcompositionから注入する。composition rootはP1-03が所有する`src/neontof/application/turn_lifecycle.py::build_recovery_metadata(record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...], inputs: RecoveryMetadataInputs) -> RecoveryEventMetadata`と`src/neontof/application/turn_lifecycle.py::reserve_recovery_event_ids(identity: TurnRequestIdentity) -> RecoveryEventIdReservation`をexact importし、`TurnLifecycleCoordinator(..., recovery_event_id_source=reserve_recovery_event_ids, recovery_metadata_factory=build_recovery_metadata, ...)`として一度だけ注入する。`compose_application_runtime(...) -> ApplicationRuntime`のexact signatureには外部の`recovery_event_id_source`やgeneric recovery factory引数を置かず、P1-03 concrete implementationをproduction defaultとして必ず使う。Coordinator unit testだけはsource差し替えを許す。そのcoordinatorから`BootstrapApplicationService(coordinator, build_bootstrap_events)`と`TurnEngine`を構成して`ApplicationRuntime.bootstrap_service`と`ApplicationRuntime.turn_engine`へ保存する。composition root以外でrebuilder、recovery metadata factory、recovery Event ID sourceを構築せず、route / serializerはrebuilderを実行しない。P1-11はResponseSerializerとP1-03 concrete recovery source/factoryをwireするcompositionだけを所有し、P1-03の`turn_lifecycle.py`を再Modify/stageしない。`EventStore.append()`、`TurnRequestStore.claim()`、`TurnRequestStore.stage()`、`TurnRequestStore.complete()`を直接呼ばない。NewClaim後のnormal `TurnEventBatchFactory`には同じ`event_boundary_lock`内で一度だけ明示的に取得した`EventStore.read_campaign(record.campaign_id)`のcampaign全体validated `tuple[DomainEvent, ...]`を渡し、factoryの第三引数を省略・EventStore capture・filtered sliceにしない。claim transaction内のsame-connection readは別callsiteとして保持する。

`build_public_session_view()`の入力は上記のexact signatureに固定する。`public_projection`はEvent replay由来のcampaign/session/scene/turn/request identifiers、resources、locations、clocks、factsを含み、`resource_projection`は同じEvent replayから得たcurrent values、`dice_projection`は`rebuild_dice_projection(EventStore.read_campaign(campaign_id))`から得る。`read_campaign()`は検証済み`DomainEvent`列を返すため、`StoredEvent.event`のunwrapを行わない。staticなmax/label/inventory/objective textは`PublicStaticData`だけから読み、inventoryは`public_static_data.inventory`のlabelを表示する。secret/NPC `gm_only`本文を参照しない。full `Projection`、raw authoring model、Transcript、Telemetryをこのbuilderへ渡さない。
`select_public_target_and_conditions(facts)`はvalidatedなactive `PublicFact`だけを受け、`target_number` predicateが1件ならその`TargetNumber`を、0件なら`None`を返す。active targetが複数、またはvalidatorを通らないtargetはfail-closedにする。`condition` predicateは`(subject_id, value, source_event_id)`の安定順に並べた`tuple[StatusCondition, ...]`を返し、0件なら空tupleとする。`select_scenario_outcome(facts: Sequence[FactRecord])`はreplayed `FactRecord`をclosedな`ScenarioOutcomeFact`へ検証し、active outcomeが1件ならsuccess/failureを、0件なら`None`を返す。複数、predicate/value/holder/subject/visibility/sourceが壊れたfactはfail-closedにする。`build_public_session_view()`はこの二つのselectorの結果を`target_number`、`conditions`、`scenario_outcome`へ写し、Factを直接fixtureや静的JSONへ置いて表示を成立させない。`PublicDiceView`は既存`DiceRolledPayload`の`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけを保持し、target/conditions/outcomeはEvent replayで検証済みのFactを集約する`PublicSessionView`側に置く。
これによりRoadmapが要求するDice/Rulingの最小結果は、P1-04のdeterministic `DiceResult` / `TargetNumber` / `StatusCondition`、P1-08のvalidated `FactAsserted` / `FactSuperseded`とreplay、P1-11の`PublicSessionView` / `TurnResponseDocument` / Browser DOMという一方向の経路で公開される。`scenario_outcome`も既存FactAssertedのreplayed `ScenarioOutcomeFact`として同じEvent authority経路を通る。PublicFactを直接wireせず、`PublicDiceView`へtarget/conditions/outcomeを混ぜない。
`make_response_serializer(*, public_static_data: PublicStaticData, encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes], encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes]) -> ResponseSerializer`はP1-11の`src/neontof/web/response_serializer.py`だけが実装し、`ResponseSerializer = Callable[[TurnResponseDocument, RequestedMediaType], StrictBytes]`をHTTP adapterへwireする。serializerはP1-08のtyped `TurnResponseDocument`と`RequestedMediaType`を受け、documentの`public_projection`、`resource_projection`、`dice_projection` / `dice_result`、`narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`、`target_number`、`conditions`、`scenario_outcome`を用いて`build_public_session_presentation(response_document=document, suggested_actions=document.suggested_actions, cost_microusd=document.cost_microusd, processing_status=document.processing_status)`、`build_public_session_view(..., public_static_data=public_static_data, presentation=presentation)`、`StateFrame`、buffered responseを順に作り、`encode_buffered_document(buffered_response)`または`encode_sse_document(buffered_response)`から指定mediaのnon-empty strict UTF-8 `StrictBytes`を返す。serializerはEventStore、TurnRequestStore、coordinator、lock、recoveryを参照せず、ResponseRebuilderを実行しない。`CachedTurnResponse.body`と`complete()`前のbodyは同じstrict UTF-8 / non-empty / requested media contractでCoordinatorとStoreが検証し、invalid bytesは`StoreError(code="invalid_response")`としてcompleteせずprocessingを保持する。P1-11のroute / serializerは`EventStore.append()`、`TurnRequestStore.claim()`、`TurnRequestStore.stage()`、`TurnRequestStore.complete()`を直接呼ばず、ResponseRebuilderを実行しない。ResponseRebuilderを構築するのは`src/neontof/app.py`のcomposition rootだけであり、P1-11はその完成済みrebuilderをcoordinatorへ注入する。normal/recoveryのResponseRebuilderがこのserializerでbody bytesとStateFrameを確定した後にだけCoordinatorが`complete()`し、routeはcache済みbodyをforwardして再serializeしない。`ApplicationRuntime.server_clock: Callable[[], int]`はUTC epoch secondsを返し、HTTP undo routeだけがこれを`OccurredAt`へ変換する。`build_undo_command()`の順序はrequired `Idempotency-Key`のsafe parse → UTC seconds `runtime.server_clock` → `UndoCommand` → `runtime.turn_engine.undo_latest()` → coordinatorで固定する。turn routeのregistry miss + `ExistingProcessingClaim`は`TurnLifecycleCoordinator.execute()`内の同じboundary lockで`RecoveryPlan`を受け、planのoptional candidateをexecuteの既存append callsiteで処理した後にcoordinator-only rebuild/completeへ進む。route / serializerは`recover_processing()`を直接実行せず、EventStore appendとTurnRequestStore completeのcallerにもならない。

reloadでは`EventStore.read_campaign(campaign_id)`でcampaign全体を検証してから、Event Logを同じ順序でreplayし、`PublicProjection`、`PublicResourceProjection`、`DiceProjection`、`PublicSessionView`のevent-derived subsetを再構築する。`PublicSessionPresentation`が渡されない場合は前項のtyped defaultを使い、Event Logにないpresentation fieldsを推測しない。`test_reload_rebuilds_event_derived_public_session_subset_from_event_log`はprojection snapshotとcacheを削除した後でも、Eventだけからcampaign/session/scene/turn、location、HP、Resource、target_number、conditions、`scenario_outcome`、Clock、Diceのsubsetが一致し、narrative、suggested_actions、cost、processing status、correctionsのfull view equalityを要求しないことをfocusedに確認する。

`PublicSessionPresentation`、`PublicProcessingStatus`、`NonNegativeMicrousd`、`build_public_session_presentation()`、`PublicSessionView`、`build_public_session_view()`のowner pathは`src/neontof/application/public_view.py`に固定する。`build_public_session_presentation(*, response_document: TurnResponseDocument, suggested_actions: tuple[StrictStr, ...], cost_microusd: NonNegativeMicrousd, processing_status: PublicProcessingStatus) -> PublicSessionPresentation`は、validated `TurnResponseDocument.narrative` / `corrections`と、HTTPへ渡すtyped `suggested_actions` / `cost_microusd` / `processing_status`だけからpresentationを作る。raw provider response、secret、full Projectionをこの入力へ渡さない。HTTP application pathはresponse document → `build_public_session_presentation(...)` → `build_public_session_view(..., presentation=presentation)`の順で呼び、`PublicSessionView`のpresentation fieldsをbuilderの隠れたglobalやEvent Log推測で埋めない。`processing_status`は`PublicProcessingStatus`のclosed literal、`cost_microusd`は`NonNegativeMicrousd`のstrict nonnegative integerである。

Event-only reloadで復元できるのは、validated Event replayから得る`campaign_id`、`session_id`、`scene_id`、`turn_status`、`location`、HP、Resource、`target_number`、`conditions`、Clock、Diceのsubsetだけである。`narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`はEvent Logに存在しないため、reload時にpresentationが渡されなければ`narrative=()`、`suggested_actions=()`、`cost_microusd=0`、`processing_status="done"`、`corrections=()`というtyped defaultを使う。presentationが明示されていればその値を使う。Event-only reloadでfull `PublicSessionView`の同一性は主張せず、event-derived subsetだけを比較する。

P1-08の`TurnResponseDocument`がpublication inputの正本であり、`public_projection`、`resource_projection`、`dice_projection` / `dice_result`、`narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`、`target_number`、`conditions`をtyped fieldとして一つだけ保持する。P1-11の`PublicSessionPresentation` / `PublicSessionView` / `StateFrame`はそのdocumentから作るpresentation layerの所有型であり、同じfieldを別のP1-11 response documentとして複製しない。P1-03はP1-08のdocumentをopaqueな`StrictBytes`として運ぶだけで、JSONをdecode・解釈せず、P1-11へ逆依存しない。

`ResponseRebuilder`はappend後のfull Event replayと`select_response_payload()`の保存済みpayloadからP1-08の`ResponseDocumentBuilder`を一度呼び、typed `TurnResponseDocument`を作る。続けてP1-11の`ResponseSerializer`がそのdocumentから`PublicSessionPresentation`、`PublicSessionView`、`StateFrame`を作り、canonicalな`BufferedTurnResponse.frames`を一度だけ完成させる。`encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes]`と`encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes]`には同じ完成済み`BufferedTurnResponse`を渡し、buffered JSONとSSEのframe列・body sourceを分岐させない。完成bodyのstrict UTF-8 / non-empty検証後、Coordinatorが`complete()`するため、routeはcache済みbytesをbyte-for-byteでforwardし、document、`PublicSessionView`、`StateFrame`、JSON、SSEを再serializeしない。

### Canonical JSONとHTTP契約

PythonとTypeScriptのcanonical JSONは一つだけとし、flatなsnake_caseを使う。Pydanticのalias、camelCase、nested `hp`/`resource`/`clock` shapeを併用しない。`PublicSessionView`のJSON fieldsは`campaign_id`、`session_id`、`scene_id`、`turn_status`、`narrative`、`suggested_actions`、`location`、`hp_current`、`hp_max`、`resource_label`、`resource_current`、`resource_max`、`inventory`、`objective`、`target_number`、`conditions`、`scenario_outcome`、`clock_label`、`clock_current`、`clock_max`、`dice`、`cost_microusd`、`processing_status`、`corrections`である。`target_number`はstrict integerまたはnull、`conditions`は安定順の`StatusCondition[]`（空配列可）、`scenario_outcome`は`"success" | "failure" | null`とする。`dice`はnullまたは`campaign_seed`、`action_id`、`roll_index`、`derived_seed`、`formula`、`result`だけを持ち、`PublicDiceView`へtarget/conditions/outcomeを追加しない。

Phase 0 transportのframeは次のshapeを保ち、web-only frameを同じtop-level `type` discriminatorで追加する。

```json
{"type":"processing","data":"accepted"}
{"type":"semantic_result","data":{"...":"validated semantic result"}}
{"type":"narrative","data":"validated narrative"}
{"type":"state","data":{ "campaign_id":"...", "session_id":"...", "...":"PublicSessionView fields" }}
{"type":"correction","data":"display-only correction"}
{"type":"error","code":"timeout","message":"..."}
{"type":"done","data":"running"}
```

SSEは各frameをcanonical compact JSONで`data: <json>\n\n`へencodeし、buffered responseは`{"frames":[<WebTurnStreamFrame>, ...]}`とする。`Accept: text/event-stream`は`200`と`Content-Type: text/event-stream`、`Accept: application/json`は`200`と`Content-Type: application/json`を返す。Phase 0のvalidated semantic/narrative/done dataは同値であり、`DoneFrame.data`は`"running" | "awaiting_player" | "aborted"`のstatus literalを使う。

HTTP status/bodyは次に固定する。

- `GET /health`: `200`, `{"status":"ok"}`。database、provider、API keyに依存しない。
- `POST /api/campaigns`: `201`, bodyはcanonical `PublicSessionView`。campaign creation routeはkeyword-onlyの`runtime.bootstrap_service.create_campaign(input_value=..., occurred_at=..., event_ids=...)`だけを呼び、`EventStore.append()`、`TurnLifecycleCoordinator.append_bootstrap()`、独自lock、builderの二重実行を行わない。`BootstrapApplicationService`からcoordinatorへのdelegationだけがbootstrap append経路である。
- `GET /api/sessions/{session_id}`: foundなら`200`と`PublicSessionView`、未発見なら`404`と`{"code":"session_not_found","message":"..."}`。
- `POST /api/sessions/{session_id}/turns`、`POST /api/sessions/{session_id}/turns/{turn_id}/resume`: bodyは`{"turn_request_id":"...","input_text":"...","provisional_reference_text":"..."}`（最後のfieldはoptional）、`Idempotency-Key` headerは外部`request_key`として必須。P1-08の`TurnEngine.submit(command: TurnCommand) -> TurnExecutionResult`または`resume(command: ResumeTurnCommand) -> TurnExecutionResult`がpre-claim intentとprepareを作り、TurnLifecycleCoordinatorがclaim、candidate validation、Event append、rebuild、ResponseRebuilder、cache completeを所有する。`CompletedTurnResult`と`ExistingFinalTurnResult`はcoordinatorからEngine、routeへ`CachedTurnResponse.status_code`、`media_type`、body bytesをbyte-for-byteでforwardし、route/serializerで再serializeしない。`ProcessingTurnResult`はresponseなしの`status="processing"` / `http_status_code=202`へmapする。P1-11は完成済みbodyをwireするだけで、direct `EventStore.append()`、direct `TurnRequestStore.complete()`、独自rebuildを行わない。同じ`Idempotency-Key`のreplayはcached `status_code`、`media_type`、body bytesをbyte-for-byteで返し、provider/dice/Event/frame再生成を行わない。`ActiveTurnRegistry.try_acquire()`が`ExistingActiveTurn`を返すときだけactive fast pathとして`ProcessingTurnResult`を返す。registry miss後のdurable claimが`ExistingProcessingClaim`を返す場合は、execute内の同じboundary lock下で`recover_processing()`へ入り、保存metadataからrecovery abortまたはterminal responseを復元する。各`execute()`呼出しはdurable claimを正確に一回行い、`recover_processing()`はclaimを呼ばず、recoveryはProvider、Dice、prepareを再実行しない。orphan recoveryはこのcampaign-scoped durable recovery policyで一度だけ行う。
- registry missの`ExistingProcessingClaim`ではrouteが`ProcessingTurnResult`を直接返さず、`TurnLifecycleCoordinator.execute()`が同じboundary lock内で`recover_processing(*, record=..., campaign_events=...) -> RecoveryPlan`を呼ぶ。`RecoveryPlan`のmetadata CAS / decision / optional candidate preparation後、同じexecute append callsite、全Event reread/select、coordinator-only `ResponseRebuilder`一回、strict response validation、`TurnRequestStore.complete()`一回の順でfinal responseを作る。`recover_processing`、route、serializerはEventStore.appendまたはcompleteを呼ばない。active registry hitだけは202であり、processing rowが残る場合は次回のdurable recovery入口へ進む。
- malformed bodyまたはmissing headerは`422`と`HttpErrorBody`、既存Turnと矛盾するresume/undoは`409`と`HttpErrorBody`、server failureは対応する`ErrorFrame`を含む`200` responseとする。
- `POST /api/sessions/{session_id}/undo`: 成功は`200`とbuffered `WebTurnStreamFrame` response、対象外Turnは`409`。`GET /`と`GET /assets/*`はBrowser静的配信だけを返し、secretを含めない。

`SubmitTurnBody.turn_request_id`はLifecycle Eventのcanonical IDであり、`Idempotency-Key`とは別である。resumeは同じ`turn_id`と同じ`turn_request_id`を使い、headerだけを新しい外部request keyにできる。

HTTP routeのmappingは次の一つに固定する。`Accept` headerは`parse_requested_media_type(value: str | None) -> RequestedMediaType`でstrictに`application/json`または`text/event-stream`へ変換し、未知・複数・欠落値は`422`とする。bodyの`turn_request_id`と`input_text`、URLの`session_id` / resume `turn_id`、server route contextの`campaign_id` / `scene_id`をcommandへ写す。`Idempotency-Key`は`parse_idempotency_key()`でsafe parseしたDB-wide `OpaqueRequestKey`へ写し、routeはraw headerを下流へ渡さない。submit routeは`TurnCommand(campaign_id=..., session_id=..., scene_id=..., request_key=..., requested_media_type=..., turn_request_id=..., input_text=..., provisional_reference_text=...)`だけを構成し、resume routeはstrictなURL path validation後に`ResumeTurnCommand(campaign_id=..., session_id=..., scene_id=..., turn_id=..., request_key=..., requested_media_type=..., turn_request_id=..., input_text=..., provisional_reference_text=...)`だけを構成する。routeは`derive_turn_id`、`derive_input_digest`、`build_initial_recovery_payload`、`TurnPreparationContext`、`TurnRequestIntent`を呼ばず、submit `turn_id` / `root_turn_request_id`もcommandへ積まない。`TurnEngine.submit(command)` / `resume(command)`だけが、submitのserver-owned `derive_turn_id(campaign_id, session_id, turn_request_id)`、root/canonical relationship、`derive_input_digest(command.input_text)`、immutable context、P1-08の`build_initial_recovery_payload(...)`、完全な`TurnRequestIntent`をこの順に一度だけ構成し、`prepare = self.bind_turn_preparation(context=context)`を作って`TurnLifecycleCoordinator.execute(intent=intent, prepare=prepare)`へ注入する。resumeはURLの`turn_id`とbody canonical IDのtyped grammar / 構文整合だけをEngineで検証する。過去Eventのaccepted/awaiting anchor、campaign/session/scene/turn context、canonical/root relationshipのstrict validationは、shared `event_boundary_lock`内の`TurnRequestStore.claim()`だけがfull validated Event/recordを使って行い、Engineはclaim外で読み取り・照合・推測しない。同じcanonical `turn_request_id`に対する新しいrequest keyは許可し、campaign/session/scene/turn contextとcanonical/root relationshipのstrict validationはshared `event_boundary_lock`内の`TurnRequestStore.claim()`だけがfull validated Event/recordを使って行う。routeから`TurnRequestStore`または`EventStore`を直接呼ぶ経路はない。`base_event_sequence`と`staged_recovery_payload`だけはNewClaim/後続stageが決める。

`POST /api/sessions/{session_id}/undo`はrequired `Idempotency-Key`をsafe parseしてopaque `OpaqueRequestKey`にし、`runtime.server_clock()`のUTC secondsを`OccurredAt`へ変換して`UndoCommand(campaign_id=..., session_id=..., request_key=..., occurred_at=...)`を作る。routeは`runtime.turn_engine.undo_latest(command)`だけを呼び、Engineからcoordinatorへ委譲する。coordinatorは同じ`event_boundary_lock`内で durable `read_processing(campaign_id=...)` → rowがなければcampaign全体read → `derive_revert_event_id()`一回 → derived ID lookup / full context check → ID absent時だけglobal latest committed selector → validate → append one → reread / `UndoResponseRebuilder` rebuild oneを実行し、routeはこの順序を変更しない。既存matching Revertでもappend=0 / rebuild=1でresponseを供給し、rebuilder failure時はEvent追加なしでretry可能とする。route、Engine、P1-11はturn_requestsのclaim/stage/complete/cacheを呼ばず、undoの再送はrebuild failure後、後続Turn後、clock進行後でも同じ元targetへのappend 0を返す。

HTTP adapterの公開順は、normal Turnでは(1)全frameのcanonical body完成、(2)`TurnRequestStore.complete()`によるcache commit、(3)commit済みbodyのSSEまたはbuffered公開で固定する。adapterがexecution resultを独自に再serializeして先に公開する経路を作らない。SSEとbufferedは同じ完成済みframe bodyから各media typeへ変換し、replayは保存済み`status_code`、`media_type`、body bytesをそのまま返す。Undoはturn request cacheを使わず、coordinatorが一度rebuildしたresponseをEngineからrouteへ直接forwardする。

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

`POST /api/sessions/{session_id}/turns`と`POST /api/sessions/{session_id}/turns/{turn_id}/resume`は、`Accept: text/event-stream`でSSE、`Accept: application/json`でbuffered responseを返す。両経路のPhase 0 transport由来のvalidated semantic / narrative / done payloadは同値でなければならず、web-only frameは同じflat unionのmemberとして扱う。

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

`done` frameは`DoneFrame.data`のstatus literal（`running`、`awaiting_player`、`aborted`）を使い、`PublicSessionView`を埋め込まない。NarrativeはSemantic Result validationとEvent commitの完了前に送らない。Streaming非対応Providerでもserverがvalidated Narrativeを1 frameとして送る。

Narrative auditは表示訂正だけを生成し、EventをrollbackまたはState変更しない。訂正はTranscriptへappendする。

**テストファースト**

- `test_sse_and_buffered_frames_are_semantically_equal`
- `test_narrative_frame_never_precedes_semantic_result_frame`
- `test_narrative_is_not_sent_when_validation_fails`
- `test_state_frame_is_sent_after_event_commit`
- `test_correction_is_displayed_and_logged`
- `test_reload_returns_event_derived_running_or_last_committed_state`
- `test_http_response_never_contains_api_key_sentinel`
- `test_health_remains_database_independent`
- `test_duplicate_idempotency_replays_exact_cached_http_response`
- `test_http_publication_follows_turn_request_cache_commit`
- `test_sse_and_buffered_are_generated_from_same_completed_body`
- `test_active_processing_replay_returns_processing_only`
- `test_application_runtime_owns_one_active_turn_registry_and_only_coordinator_receives_it`
- `test_registry_miss_existing_processing_enters_recovery_without_reexecution`
- `test_turn_routes_map_accept_body_and_idempotency_key_without_direct_store`
- `test_resume_route_rejects_url_turn_id_mismatch`
- `test_orphan_processing_recovery_is_separate_from_normal_retry`
- `test_public_view_and_narrative_audit_receive_no_full_projection`
- `test_public_view_builder_accepts_only_typed_public_inputs`
- `test_public_session_presentation_is_typed_and_supplied_to_view_builder`
- `test_reload_rebuilds_event_derived_public_session_subset_from_event_log`
- `test_public_session_view_renders_target_number_and_condition_from_rebuilt_facts`
- `test_public_session_view_renders_scenario_outcome_from_replayed_fact`
- `test_public_session_view_projects_one_active_target_number_and_stable_conditions`
- `test_public_session_view_keeps_one_active_target_after_consecutive_turns`
- `test_response_document_contains_target_number_and_conditions_and_scenario_outcome`
- `test_http_status_and_body_shapes_are_canonical`
- `test_server_lifecycle_uses_external_temporary_database`
- `test_make_response_serializer_receives_explicit_public_static_data`
- `test_make_response_serializer_wires_buffered_and_sse_without_store`
- `test_response_serializer_builds_state_frame_and_buffered_sse_bytes_before_complete`
- `test_turn_route_forwards_completed_and_existing_final_cached_response_bytes`
- `test_turn_route_forwards_cached_response_without_reserializing`
- `test_turn_route_maps_processing_result_to_http_202_without_response`
- `test_campaign_creation_route_delegates_only_to_bootstrap_service`
- `test_application_runtime_composes_normal_and_undo_rebuilders_once`
- `test_application_runtime_injects_p1_03_factory_and_concrete_recovery_event_id_source`
- `test_application_runtime_injects_scenario_runtime_into_turn_engine_after_p1_12`
- `test_undo_route_parses_required_idempotency_key_and_uses_runtime_clock`
- `test_web_layer_never_calls_eventstore_append_or_request_complete`

P1-11のGateでは`PublicSessionView.scenario_outcome`がreplayed `ScenarioOutcomeFact`から供給され、`PublicSessionPresentation`のpresentation fieldsとは混同しないこと、P1-10の`#scenario-outcome` locatorとJSON/SSEが同じvalueを運ぶことを確認する。success/failureのEvent replayとappend後crash/retryはP1-12で検証し、Browser表示はP1-11/P1-13で検証する。

P1-11のpresentation/reload完了条件は、`build_public_session_presentation(*, response_document: TurnResponseDocument, suggested_actions: tuple[StrictStr, ...], cost_microusd: NonNegativeMicrousd, processing_status: PublicProcessingStatus) -> PublicSessionPresentation`を通してから`build_public_session_view(..., presentation=...)`を呼び、Event-derived subsetとpresentation fieldsを混同しないことである。Event-only reloadはcampaign/session/scene/turn、location、HP、Resource、`target_number`、`conditions`、`scenario_outcome`、Clock、DiceだけをEvent Logから再構築し、presentation fieldsは明示presentationまたは`narrative=()`、`suggested_actions=()`、`cost_microusd=0`、`processing_status="done"`、`corrections=()`のtyped defaultを使う。P1-11の`test_public_session_presentation_is_typed_and_supplied_to_view_builder`、`test_reload_rebuilds_event_derived_public_session_subset_from_event_log`、P1-10のDOM/reload/replay test、P1-13のcomplete-run表示assertionがこの境界を検証する。P1-11はP1-08の`TurnResponseDocument`からtyped presentationを供給するが、P1-08のmaterialization integrationへ`PublicSessionView`を要求しない。

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/web tests/application/test_narrative_audit.py tests/application/test_public_view.py tests/test_app.py tests/test_main.py tests/test_repository_contracts.py -q
```

P1-11 composition Gateでは`src/neontof/app.py`がP1-03の`build_recovery_metadata`と`reserve_recovery_event_ids`をexact importし、`TurnLifecycleCoordinator(..., recovery_metadata_factory=build_recovery_metadata, recovery_event_id_source=reserve_recovery_event_ids, ...)`へ一度だけ注入することを`test_application_runtime_injects_p1_03_factory_and_concrete_recovery_event_id_source`で検査する。`compose_application_runtime(...)`に外部`recovery_event_id_source`引数がなく、production defaultが差し替えられていないこと、P1-11 route/serializerがrebuilder、append、completeを直接呼ばないことも同じGateで確認する。

`test_make_response_serializer_receives_explicit_public_static_data`は`compose_application_runtime(...)`から`make_response_serializer(public_static_data=..., encode_buffered_document=..., encode_sse_document=...)`へ明示入力が渡ることを、`test_response_serializer_builds_state_frame_and_buffered_sse_bytes_before_complete`はP1-08のtyped `TurnResponseDocument`から`PublicSessionPresentation` / `PublicSessionView` / `StateFrame` / buffered/SSE bytesが作られてからCoordinatorの`complete()`が呼ばれることを確認する。`test_turn_route_forwards_cached_response_without_reserializing`はrouteがCoordinatorのcache bodyをそのままforwardし、route側でdocumentまたはJSON/SSEを再serializeしないことを確認する。

実装前のfocused commandでは404、missing module、またはNarrative frame indexがSemantic frameより小さいassertion failureを確認する。cache commit前の公開、SSE/bufferedの完成body不一致、active processingの誤recoveryも失敗理由として確認する。

**完了条件**

全test pass。P1-08 coordinatorがnormal Turnのcache commitを完了する前にHTTP公開が起きず、P1-11の`ResponseSerializer`はcommit済み`TurnResponseDocument`だけをJSON/SSEへwireする。SSEとbufferedのframeをJSON正規化したtupleが一致し、同じ完成済みframe bodyから生成される。replayは保存済みbody bytesをbyte-for-byteで返す。registryの`ExistingActiveTurn` hitだけがclaimなしのprocessing `202` fast pathであり、registry miss後のdurable claimを正確に一回行った`ExistingProcessingClaim`は`recover_processing()`へ入り、`recover_processing()`はclaimを呼ばず、保存metadataからrecovery abortまたはterminal responseを再構築してexecuteがresponse/status-onlyのcache completeを一度行う。normal committed / normal aborted / awaiting_playerの初回はそのexecute呼出し内で`1 / 1 / 1`、各Event append後〜complete前の再試行は`0 / 1 / 1`、recovery abortの初回は`1 / 1 / 1`、recovery abort append後の再試行は`0 / 1 / 1`であり、Eventを二重appendしない。`recover_processing()`はclaimを呼ばず、recoveryはProvider/Dice/prepareを再実行しない。validation failure responseにNarrative frameが存在しない。Undo routeはrequired keyをsafe parseし、UTC seconds `runtime.server_clock`からcommandを作り、Undo responseをcache completeなしで直接forwardする。server start/readiness/rollbackのruntime/test DBはrepository tree外のtemporary pathまたはpytest `tmp_path`だけに置き、`tests/test_repository_contracts.py`のguardがexit `0`で、生成DB、`client/node_modules`、`client/dist`、未manifest production pathをstatusへ残さない。 current-submit（current identity一致のprefixにacceptedなし・owned_suffixにaccepted/terminalなし）のrecoveryは`PlayerInputAccepted -> recovery TurnAborted`、current-resume（current identity一致のprefixにaccepted/awaitingあり・owned_suffixにTurnResumed/terminalなし）のrecoveryはrecovery `TurnAborted`だけであり、以前のprefix Eventを二重appendしない。metadata未確定のfaultなし同一execute継続は`1 / 1 / 1`、CAS後append前crashのpartial failed attemptは`0 / 0 / 0`でprocessingを保持し、次回executeのrecovery abortは`1 / 1 / 1`、append後complete前の各retryは`0 / 1 / 1`とする。`src/neontof/app.py::compose_application_runtime(...)`はP1-03 concrete `build_recovery_metadata`と`reserve_recovery_event_ids`をそれぞれexact importして`recovery_metadata_factory`と`recovery_event_id_source`へ注入し、`test_application_runtime_injects_p1_03_factory_and_concrete_recovery_event_id_source`で両方を確認する。

**コミット境界**

```powershell
git add -- src/neontof/web/__init__.py src/neontof/web/contracts.py src/neontof/web/routes.py src/neontof/web/streaming.py src/neontof/web/response_serializer.py src/neontof/application/runtime.py src/neontof/application/public_view.py src/neontof/application/narrative_audit.py src/neontof/app.py src/neontof/config.py src/neontof/main.py tests/web/test_turn_routes.py tests/web/test_streaming.py tests/web/test_response_serializer.py tests/application/test_narrative_audit.py tests/application/test_public_view.py tests/test_app.py tests/test_main.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。canonical JSON、HTTP status/body、cache commit後の公開、SSE/buffered同値、cached replay、full Projection非公開、health lifecycle、Event-only reloadのfocused commandがGREENであることを確認して着地させる。P1-11の完了条件には、P1-12後に`ScenarioRuntime`を構築して`TurnEngine(..., scenario_runtime=scenario_runtime)`へ注入する`test_application_runtime_injects_scenario_runtime_into_turn_engine_after_p1_12`、`build_public_session_presentation`によるtyped presentation供給、P1-03の`build_recovery_metadata`と`reserve_recovery_event_ids`のexact import/injection、Event-only reloadがpresentation fieldsのfull equalityを要求しないこと、連続Turn後のactive targetが1件であることを含める。

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
- `src/neontof/application/turn_engine.py`（P1-08が作成したbound preparation callbackをP1-08後にserial Modify/stageし、`ScenarioRuntime`を所有するconstructorとsame-Turn candidate-aware integrationを追加）
- `tests/integration/test_complete_fake_turn.py`（P1-08が作成したintegration pathのserial Modify/stage）

P1-12のproduction manifest追加は`src/neontof/scenario_runtime.py`だけである。`PreparedEffect`、`PreparedTurn`、`TurnEventBatchFactory`、`turn_engine.py`、`turn_models.py`はP1-03/P1-08の所有pathであり、P1-12は既存のP1-08 `TurnEngine.bind_turn_preparation(context=context)`が返すbound callbackと`TurnEngine.__init__`をP1-08 commit後にserial Modify/stageする。`PreparedTurn.scenario_end`はP1-03が所有するneutral fieldであり、P1-12はその値を変更・再定義せず`ScenarioAdvance.reached_end`をbound prepareから伝搬する。P1-12は`turn_models.py`を変更せず、ScenarioRuntime用のgeneric hook/pluginや独自のlifecycle ownerを追加しない。P1-09がC-02承認済みで先にbound preparationを拡張した場合だけ、そのcommit後にP1-12が同じpathをserialに拡張する。C-02延期時もP1-12はP1-08のbase prepareから開始でき、P1-09のmodule/type/importを参照しない。

`ScenarioRuntime`は`EventMaterializationInput`をimportせず、`TurnRequestIdentity`と`PreparedEffect`を`src/neontof/application/turn_models.py`からimportする。`EventDraft` / `EventBatch`はP1-03/P1-08の`TurnEventBatchFactory`だけが構成する。`ScenarioCandidateValidationError`はこのmoduleのclosed errorであり、`recovery_identity_mismatch`を流用しない。

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
ScenarioCandidateErrorCode = Literal[
    "scenario_candidate_conflict",
    "scenario_candidate_invalid",
]

class ScenarioCandidateValidationError(Exception):
    code: ScenarioCandidateErrorCode

    def __init__(self, code: ScenarioCandidateErrorCode) -> None: ...

class ScenarioAdvance(ContractModel):
    effect_candidates: tuple[PreparedEffect, ...]
    reached_end: Literal["success", "failure"] | None
    public_notice: str | None

def build_scenario_outcome_candidate(
    *,
    identity: TurnRequestIdentity,
    outcome: Literal["success", "failure"],
) -> PreparedEffect: ...

class ScenarioRuntime:
    def __init__(self, scenario: ScenarioV1) -> None: ...
    def evaluate_after_turn(
        self,
        *,
        identity: TurnRequestIdentity,
        projection: Projection,
        effect_candidates: tuple[PreparedEffect, ...],
    ) -> ScenarioAdvance: ...

class TurnEngine:
    def __init__(
        self,
        *,
        coordinator: TurnLifecycleCoordinator,
        gateway: ModelGateway,
        registry: ApplicationRegistry,
        scenario_runtime: ScenarioRuntime,
    ) -> None: ...

    def bind_turn_preparation(
        self,
        *,
        context: TurnPreparationContext,
    ) -> TurnPreparation: ...
```

Director conceptはこのconcrete runtimeが担う。secret-aware判断とplayer-facing Narrativeを同じmodel callで生成しない。唯一のproduction evaluatorである`evaluate_after_turn(*, identity, projection, effect_candidates)`は、pre-turn `Projection`へ先行して確定したpre-ID `effect_candidates`をpureに仮適用し、そのsame-TurnのClock / Fact / Clue / `ProposedCharacterMoved`結果を含めてEndと必要なscene transitionを判定する。scene transitionは独立APIではなく、validated semantic resultを`materialize_accepted_result(*, identity=..., ...)`が作った`ProposedCharacterMoved`候補として先に渡す。pre-turn ProjectionだけからEndを判定してはならない。`reached_end`がnon-NULLなら、ScenarioRuntimeは`build_scenario_outcome_candidate(identity=identity, outcome=reached_end)`を一度だけ呼び、既存Phase 0 `FactAsserted` payloadのpre-ID `PreparedEffect`を一件追加する。candidateは`kind="fact"`、`holder="world"`、`subject_id=None`、`predicate="scenario_outcome"`、`value="success" | "failure"`、`visibility="player_visible"`、current identity envelopeとし、P1-07の`ScenarioOutcomeFact`でreplay時に検証する。`ScenarioAdvance.effect_candidates`はEvent ID・`OccurredAt`を持たないcurrent identity由来のpre-ID `PreparedEffect`候補であり、identity mismatchや過去Turn/global contextの推測はfail-closedとする。`scenario_end`はSessionEndedの制御用であり、success/failureの正本はreplayed outcome Factである。
ScenarioRuntimeはsequence割当、`EventDraft` / `EventBatch`構成、EventStore、coordinator、独自lock、`EventStore.append()`を持たない。

`TurnEngine.__init__(*, coordinator: TurnLifecycleCoordinator, gateway: ModelGateway, registry: ApplicationRegistry, scenario_runtime: ScenarioRuntime) -> None`はP1-12がP1-08後に追加するexact constructor fieldであり、`EventStore`、`ProjectionStore`、`TurnRequestStore`、`ObservationStore`、`ActiveTurnRegistry`、`event_boundary_lock`をEngineへ渡さず、coordinator / `ApplicationRuntime`の所有権を重複させない。`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`をserialに拡張する。bound preparationはNewClaim後に同じ`event_boundary_lock`内で一度だけ取得したfull validated `tuple[DomainEvent, ...]`からpre-turn Projection/contextを作り、先行して確定したsemantic/dice candidate列を`evaluate_after_turn(identity=identity, projection=projection, effect_candidates=effect_candidates)`へ渡す。`ScenarioAdvance.effect_candidates`はそのsame-Turn候補を一つの最終`PreparedTurn.effect_candidates`へ合流し、`ScenarioAdvance.reached_end`を`PreparedTurn.scenario_end`へコピーする。P1-12はこの順路でP1-08のbase preparationへserial extensionし、他WPのoptional producer型をimport・参照しない。
candidateのtarget/condition、Clock、`ProposedCharacterMoved`、Endを全て確定した後にだけ一回`event_id_sequence(identity, prepared)`を呼ぶ。続けて`utc_occurred_at()`、`TurnEventBatchFactory(identity, prepared, campaign_events, occurred_at, event_ids)`、candidate validation、Coordinator唯一appendへ渡す。P1-12のScenarioRuntime、service、route、composition rootはこの経路を迂回してappendしない。P1-11はP1-12後に`ScenarioRuntime`を構築し、`TurnEngine(..., scenario_runtime=scenario_runtime)`として注入する。

`evaluate_after_turn()`は入力candidate列をproducer順に一度だけ仮適用するpure functionである。先行するsemantic/dice candidate、C-02承認時だけのprovisional candidate、ScenarioのClock / Fact / Clue / `ProposedCharacterMoved` candidateをこの順に一つの仮Projectionへ適用し、同一`identity`のenvelopeであることを検証する。完全一致の重複candidateは最初の一件を保持し、同じrole/keyでpayloadが異なるcandidate、複数active target、壊れた/missing FactIdは`ScenarioCandidateValidationError(code="scenario_candidate_conflict")`または`ScenarioCandidateValidationError(code="scenario_candidate_invalid")`へfail-closedにする。raw SQLite、details、causeはこのclosed errorに漏らさない。Scenarioが返す追加candidateは安定したscenario定義順に並べ、End判定に必要な候補を先に返す。`ScenarioAdvance.reached_end`はbound prepareが`PreparedTurn.scenario_end`へ伝搬し、non-NULLなら`build_scenario_outcome_candidate(identity=identity, outcome=reached_end)`の一件を`effect_candidates`へ追加して、Event ID allocation前に確定する。outcome candidateの`kind="fact"`、`holder="world"`、`subject_id=None`、`predicate="scenario_outcome"`、`value="success" | "failure"`、`visibility="player_visible"`とcurrent identity envelopeは既存FactAssertedへ適用し、P1-07の`ScenarioOutcomeFact`でreplayする。P1-12 bound prepareはこのclosed errorをEvent ID allocation前に捕捉し、canonical failure `StagedResponseSeed`を一度だけ作り、`encode_staged_response_seed(failure_seed)` → `build_staged_recovery_payload(identity=identity, response_payload=...)`でnormal aborted用のv2 outer bytesを確定したうえでeffectなしの`PreparedTurn(effect_candidates=(), terminal_status="aborted", abort_reason="failed", scenario_end=None, staged_recovery_payload=build_staged_recovery_payload(identity=identity, response_payload=encode_staged_response_seed(failure_seed)))`へ固定写像して、通常のCoordinator append / rebuild / complete / replayへ渡す。`scenario_candidate_conflict`を`recovery_identity_mismatch`へ写像しない。最終`SessionEnded`は`TurnEventBatchFactory`だけが構成し、ScenarioRuntimeがEvent ID、EventBatch、terminal Eventを構成しない。シーン遷移は独立引数やraw inputではなく、validated semantic `ProposedCharacterMoved` candidateのsame-Turn仮適用だけで決める。

**テストファースト**

- `test_content_loads_with_production_loader`
- `test_scenario_has_five_locations`
- `test_scenario_has_four_npcs`
- `test_scenario_has_one_gm_only_secret`
- `test_scenario_has_three_clues`
- `test_two_clues_have_multiple_acquisition_locations`
- `test_clock_drives_active_npc_event`
- `test_scenario_advance_returns_pre_id_effect_candidates`
- `test_scenario_candidates_merge_into_bound_preparation_before_event_id_allocation`
- `test_scenario_runtime_applies_same_turn_candidates_before_end_evaluation`
- `test_scenario_runtime_rejects_conflicting_same_turn_candidates`
- `test_scenario_candidate_conflict_maps_to_aborted_before_event_id_allocation`
- `test_scenario_runtime_adds_pre_id_outcome_fact_for_success_and_failure`
- `test_scenario_outcome_fact_replays_after_append_and_crash_without_direct_fixture_fact`
- `test_scenario_end_propagates_to_prepared_turn_and_session_ended`
- `test_scenario_has_one_success_and_one_failure_end`
- `test_scenario_uses_only_phase_1_runtime_features`
- `test_secret_sentinel_is_absent_from_public_context`
- `test_complete_run_fixture_reaches_an_end_condition`

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/authoring/test_phase_01_content.py tests/application/test_scenario_runtime.py tests/integration/test_complete_fake_turn.py tests/test_repository_contracts.py -q
```

期待REDはmissing content file、manifest追記漏れ、未許可path、またはcardinality assertion failure。

`test_scenario_candidate_conflict_maps_to_aborted_before_event_id_allocation`は、同じrole/keyでpayloadが異なるsame-Turn candidateを与え、`ScenarioCandidateValidationError(code="scenario_candidate_conflict")`をP1-12 bound prepareが捕捉してcanonical failure `StagedResponseSeed`を一度だけouter v2 bytesへencodeしてから`effect_candidates=()`、`terminal_status="aborted"`、`abort_reason="failed"`、`scenario_end=None`、`staged_recovery_payload=build_staged_recovery_payload(...)`の固定`PreparedTurn`へ写像すること、Event ID allocation前に失敗を確定することを確認する。`test_scenario_runtime_adds_pre_id_outcome_fact_for_success_and_failure`は`ScenarioAdvance.reached_end`ごとに`build_scenario_outcome_candidate(identity=..., outcome=...)`の一件だけを既存FactAsserted candidateとして返し、success/failure以外、world以外、subject付き、非公開visibilityを拒否することを確認する。`test_scenario_outcome_fact_replays_after_append_and_crash_without_direct_fixture_fact`はsuccess/failureのcandidateをcoordinator appendとappend後crash/restartのresponse rebuildへ通し、replayed `ScenarioOutcomeFact`から同じvalueを復元する。`test_scenario_end_propagates_to_prepared_turn_and_session_ended`は`ScenarioAdvance.reached_end`が`PreparedTurn.scenario_end`へ伝搬し、`TurnEventIdSequence`が追加IDを一つだけ割り当て、`TurnEventBatchFactory`だけが`TurnCommitted -> SessionEnded`（`scene_id=None`、`turn_id=None`、`reason="completed"`）を構成することを確認する。fixtureがFactまたはSessionEndedを直接appendしたり、ScenarioRuntimeがEventBatchを返したりしてGreenにできない。

**完了条件**

全testと`tests/test_repository_contracts.py`がpassする。唯一のproduction evaluatorである`ScenarioRuntime.evaluate_after_turn(identity=..., projection=projection, effect_candidates=effect_candidates)`が先行same-Turn candidateをpureに仮適用し、Clock / Fact / Clue / `ProposedCharacterMoved`を含む結果からEndと必要なscene transitionを判定する。scene transition専用APIはなく、`ScenarioAdvance.effect_candidates`がpre-IDのままP1-08の`TurnEngine.bind_turn_preparation(context=context)`から返るbound callbackへ合流する。候補確定後の一回の`event_id_sequence`から`OccurredAt`、`TurnEventBatchFactory`、candidate validation、Coordinator唯一appendへ進み、Event Logへ永続化される。`ScenarioAdvance.reached_end`は`PreparedTurn.scenario_end`へ伝搬し、non-NULLなら既存FactAssertedの`ScenarioOutcomeFact` candidateを一件だけ追加する。P1-12のresponse/reloadはreplayed FactRecordを`select_scenario_outcome()`で復元し、success/failureを保持する。P1-08は`scenario_outcome=None`のcore response bundleまでを提供する。`scenario_end`がある場合だけfactoryが`TurnCommitted -> SessionEnded`を構成し、SessionEndedは`scene_id=None`、`turn_id=None`、payload `reason="completed"`で最後に一件だけ存在する。same-Turn candidateの完全一致重複は安定順に一件へ畳み、`ScenarioCandidateValidationError`のconflict/invalid、複数active target、壊れた/missing FactIdはfail-closedとする。P1-11が後続で`TurnEngine(..., scenario_runtime=scenario_runtime)`を注入する。complete-run fixtureの最終`SessionEnded.reason`は`completed`で、successまたはfailureのreplayed outcome Factが存在する。manifest追記漏れと未許可pathがないことも同じcommandで確認する。

**コミット境界**

```powershell
git add -- content/characters/phase-01-investigator.v1.yaml content/scenarios/phase-01-clocktower.v1.yaml tests/fixtures/phase_01/complete-run-requests.v1.json tests/fixtures/phase_01/complete-run-provider.v1.json tests/authoring/test_phase_01_content.py src/neontof/scenario_runtime.py src/neontof/application/turn_engine.py tests/application/test_scenario_runtime.py tests/integration/test_complete_fake_turn.py tests/test_repository_contracts.py
```

Test Firstではtestsを先に作成・実行し、P1-08 commitを先に着地させてから上記pathのtestsとimplementationを1つのlogical GREEN commitへまとめる。`turn_engine.py`と`test_complete_fake_turn.py`はP1-08の同じpathをP1-12がserialにModify/stageする共有integrationであり、P1-09が有効な場合はそのserial extension後に、C-02延期時はP1-08から直接、同時編集しない。ScenarioV1/CharacterSheetV1のcardinality、authoritative clock/end condition、secret visibility、clock-driven NPC、pre-turn Projectionと先行candidateを使うsame-Turn評価、pre-ID candidatesのbound preparation合流、candidateの安定順・duplicate/conflict fail-closed、一回のEvent ID allocation/Factory/append、complete-run fixtureのfocused commandがfailure `0`であることを確認して着地させる。

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

complete-run fixtureは`TargetNumber`と`StatusCondition`をFake Providerのsemantic resultへ入力し、P1-08のvalidation / materializer、coordinator append、Event replay、`PublicSessionView` / responseを通した後に`target_number`と`conditions`をassertする。`ScenarioAdvance.reached_end`から`PreparedTurn.scenario_end`とreplayed `scenario_outcome` Factを経て、`TurnEventBatchFactory`が実際に追加した最後の`SessionEnded`（payload `reason="completed"`、`scene_id=None`、`turn_id=None`）もEvent replayでassertする。`test_complete_run_fixture_asserts_target_number_condition_and_scenario_outcome`相当のassertionをfixtureへ置き、FactまたはSessionEndedを直接fixtureへ追加して表示・完走だけを満たす経路は受け入れない。

期待最終出力:

```text
phase_01_complete_run=end_reached
projection_rebuild=identical
partial_events_after_failure=0
failed_turn_transcript=retained
failed_turn_telemetry=retained
secret_hits=0
dice_replay=identical
target_number=8
conditions=injured
scenario_outcome=success
duplicate_request_effects=1
browser_state=complete
```

**実装前の検証条件**

```powershell
.\.venv\Scripts\python.exe tests/acceptance/phase_01_fake_complete_run.py
```

期待REDは最初に未実装endpoint、未到達End、またはmissing fixtureでnon-zero exit。単なるprintだけでexit `0`にしない。

**完了条件**

上記12行を出力してexit `0`。complete-run fixtureはP1-08のsemantic validation → `FactAsserted` / `FactSuperseded` materialization → Scenario candidate評価 → coordinatorの一回のID allocation / `TurnEventBatchFactory` / append → Event replay → `PublicSessionView` / response表示を通じてtarget number、condition、replayed `scenario_outcome`、最後の`SessionEnded.reason="completed"`を検証し、fixtureへFactまたはSessionEndedを直接置いてこのassertionだけを満たす実装を受け入れない。

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
- Event-derived `target_number` and stable `conditions` are present in the rebuilt Browser `PublicSessionView` and response
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

### P1-01a focused migration verification（実履歴）

P1-01aの実履歴では、次のfocused commandをtestsと実装のGREEN後に実行し、missing private runner、`_discover_migrations`のavailable migration file set同一version重複、exact schemaの実DBへrowを直接挿入するapplied gap/unknown、contiguous prefix、version/name/checksum drift、dedicated source ownership、filesystem identity、fixed connection kwargs/PRAGMA、journal mode実値一致、progress、artifact set、bounded schema/data verification、test-only restore、public surface/DB variant guardを確認した。collection errorや0 testだけをGREENの根拠にしない。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/persistence/test_migrations.py tests/persistence/test_event_store.py tests/test_repository_contracts.py -q
```

実履歴のGREENはexit `0`、failure `0`であり、`_discover_migrations`のavailable migration file set同一version重複検出、exact schemaの実DBへrowを直接挿入して検証するapplied gap/unknown、contiguous prefix、version/name/checksum drift、実schema/data比較、`backup_verified < ddl`の同一test-local timeline、journal mode実値一致、artifact set promotion/cleanup、identity/PRAGMA/query_only/close/reopen、verification deadline、test-only restoreのbounded条件を含む。fake call countだけの一致をGREENとしない。

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
- C-01はA（通常TurnのModel call上限1回、model由来clarification completionはPhase 1受入れ対象外）で固定され、P1-03/P1-08が同じ境界を保つ必要がある。
- C-03のProvider request boundaryとprovider approvalが未確定である。
- DomainEvent envelopeにtop-levelの`turn_request_id`がなく、producer coordination metadataとwire envelopeを混同できない。
- payloadはexact raw JSON bytes境界を必要とし、typed modelのserializationや既存`FrozenJsonValue`の推測round-tripを永続化の根拠にできない。
- P1-01aのmigration backupはdedicated read source、migration main、copy destination、reopen verifierのconnection lifecycleとfilesystem identityをDDL前に揃える必要があり、journal modeを`DELETE`へ固定せず実readback値を一致させる必要がある。WAL時の同一basename `main`/`-wal`/`-shm` artifact setを個別fileとして扱うとpromotionまたはcleanupの原子性を失う。
- partial artifactのreal schema/data verificationとtest-only restoreはcopyと別のboundednessを必要とし、`SQLITE_OK`継続、actual mismatch、verification deadline超過をDDL前に失敗させないと未検証artifactを承認済み状態として扱う危険がある。test-only timelineをproduction global recorderへ実装するとpublic diagnostic surfaceを拡張する。
- production manifestはP1-00b後も完全一致で検査され、各WPが自分のproduction `.py` pathを明示追加する必要がある。P1-10a以降のclient/generated path、forbidden path、CI gate、runtime/migrationのexact SQLite connect scopeを同じguardで扱うため、WPごとの追加漏れと誤った一律禁止がリスクになる。
- `tests/test_repository_contracts.py`を共有するproduction WPを並列実行すると、exact manifest追記のlost updateまたは別WPの未検証entryをGREENにするリスクがある。manifest serialization laneで一つずつ着地させる。

## 既知のリスク

- P1-00の`EventDraftBody`が既存`DomainEventBase`のunsequenced field集合から外れると、P1-01のparser boundaryで再構築できない。
- `payload_json`のobject/array shapeまたはexact bytesを失うと、永続`event_json`とEvent replayの意味が変わる。
- lifecycle payloadのvalidation前にturn request検索を行うと、coordination metadataをDomainEvent envelopeのauthorityとして扱うことになる。
- P1-08でlosslessなraw boundaryが不足した場合、Phase 0 semantic contractの改訂または別の承認済みboundaryなしに進められない。
- repository test-sideのAST/import-aware SQLite scanと、`docs/agent-guide/build-and-verify.md`に定義されたguide-side scanの更新経路を混同すると、alias/import変形、arbitrary persistence connect、または2 exact callsite scopeの不整合を見逃す。
- runtime/test DBをrepository tree内へ作ると、生成物・秘密・rollback対象の境界が壊れる。P1-01、P1-11、P1-13はrepository tree外temporary pathまたはpytest `tmp_path`に限定する。
- relative path、hard-link alias、URI/in-memory、directory、special file、別fileのidentity判定をpath文字列だけで行うと、sourceがmigration mainと異なるfileを受理する。canonical path、migration `main.file`、source `main.file`の三者`samefile`をsource open前後の正しい境界で検証する。

## リスク対策

- P1-00はmetadata contract testとproduction manifest contract testを同じfocused commandで確認する。
- P1-01はparser受理とenvelope一致確認を通過したexact assembled bytesだけを`event_json`へ保存し、既存manifestの形式、既存migration、P0 contract fileを変更しない。production `.py`を作るWPは自分のpathだけをexact manifestへ明示追加し、Modify、staging、commitへ同じpathを含める。
- P1-00bでrepository guardのexact-match、forbidden判定の入口、Python gate order、Windows runner assertionを固定した。P1-01a/P1-01b/P1-02の実履歴を前提に、P1-02後のP1-01cでrepository test-side scanを補正・検証し、guide-side SQLite scanは読み取り専用の補助evidenceとして別経路で確認する。P1-00b、P1-01a、P1-01b、P1-02の完了をsource/protocol/connect scannerの検証済み結果へ読み替えない。
- `tests/test_repository_contracts.py`をModifyするproduction WPはmanifest serialization laneで一つずつfocused/full Gate、`git diff --check`、明示commit、clean worktreeを確認し、P1-10aなどmanifest lane外のclient/test-only WPだけを非共有pathの範囲で並列実行する。
- WPごとにtestsを先に作成・実行し、REDで失敗理由を確認する。focused testと最小implementationがGREENになった後、testsとimplementationを同じlogical GREEN commitへまとめる。
- Event Store、Projection、Visibility、Dice、Gateway、Turn Engineを別commitにする。
- dependency commitを通過するまで後続integrationを開始しない。
- SQLite migrationは`0001_event_store.sql`、`0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`に分割し、各WPが自分のadditive migrationだけを追加する。down migrationは作らない。
- migration runnerはraw SQL bytes SHA-256、`_discover_migrations`によるavailable migration file setの同一version重複、applied rowsのcontiguous prefix/gap/unknown applied version/version/name/checksum driftをDDL前に実DBから検証し、applied schema_migrations rowのduplicateは`version PRIMARY KEY`の挿入時拒否に委ね、pending判定からDDL・schema row insert・COMMITまでを一つのtransactionに置く。exact schemaは適用順序を保持しないためPhase 1では適用順序を検証せず、未適用migrationをversion昇順にだけ適用する。
- P1-01aのpending existing schema/dataだけ、process-wide write lockと`BEGIN IMMEDIATE`内でdedicated read sourceを開き、migration connection自身をsourceにせず、固定connect kwargs/PRAGMA、三者`samefile`、copy直後destinationとclose/reopen後verifierのjournal mode実値一致を確認する。source→partial copy→close→reopen verifier→deadline付きreal schema/data比較→同一basename artifact setのclean close後promotionまたは全exact path cleanup→`backup_verified`→DDL→schema row insert→COMMITを固定し、新規DB/no-opではcopyしない。
- P1-01aのcopyは`pages=256`、`sleep=0.05`、`SQLITE_OK`進行を許可し、10秒deadlineとBUSY/LOCKED 200回上限を適用する。partial/verified main/`-wal`/`-shm`のfull exact pathを一つのsetとして扱い、cleanup不能は`backup_cleanup_failed`、その他のcopy/verification/status/identity failureは`backup_failed`としてDDL前に止める。backup側journal mode setterとproduction global recorder/diagnostic surfaceは作らない。
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
- C-01 Aの境界に反する変更またはblockingな契約差分が生じた場合はP1-03以降を進めず、P1-01 / P1-02 / P1-04 / P1-05の依存commitを保持してユーザー判断を待つ。
- C-02が未承認またはblockingの場合はP1-09とその依存integrationを開始せず、provisional detailのschemaを作らない。
- C-03が未承認またはblockingの場合はP1-06 Fake/Recorded Gatewayとその依存integrationを開始せず、GatewayのGREEN/commitを保留する。provider approvalが未承認またはblockingの場合はP1-06 concrete real Provider adapterとP1-07以降のprovider-dependent integrationを開始せず、real adapterのGREEN/commitを保留する。承認だけで固定responseや曖昧なadapterへfallbackしない。Fake / Recordedのlocal validationはprovider approval前も継続できる。
- P1-00またはP1-00bのmetadata、exact manifest、repository guard、envelope契約が失敗した場合はP1-01以降を開始せず、P0契約や禁止pathを変更しない。
- P1-01aのbackup/verification failureではmigration transactionをrollbackし、DDL/schema row insertを行わない。partial/verifiedの同一basename main/`-wal`/`-shm`全exact pathをcleanupし、削除不能時は`backup_cleanup_failed`と残存artifactをoperatorへ引き継ぐ。promotion済みverified artifact setは成功commit時も後続DDL rollback時も保持し、restoreはtest-onlyの独立検証で行う。
- P1-08のpayload boundaryが未承認またはPhase 0 semantic contract改訂待ちの場合は、semantic materializationと依存integrationを開始しない。

---

# 12. コミット境界の概要

P1-03 Lifecycleの`RecoveryPlan`は`turn_models.py`でstageし、`TurnLifecycleCoordinator.recover_processing(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> RecoveryPlan`をmetadata CASとrecovery decision/batch preparationだけのmethodとして固定する。recovery candidateのvalidation、EventStore append、全Event reread/select、Coordinator-only `ResponseRebuilder`、strict response validation、`TurnRequestStore.complete()`はすべて`execute()`の既存唯一callsiteが順に担い、`recover_processing`内にappend/rebuild/completeを置かない。P1-03のapplication append callerは`execute()`と`revert_latest()`の2件、P1-05後は`append_bootstrap()`を加えた3件のままとする。`RecoveryEventMetadata`、SQL、record、state tableはnormal `aborted_event_id`とrecovery `recovery_aborted_event_id`を分離した6個のEvent ID shapeを共有し、`owned_suffix` actual Event Log membershipをpayload選択の権威（prefixは以前の履歴でありcurrent requestのowned Eventではない）とする。予約IDとactual Eventの関係はrole-aware subsetとし、未使用予約IDの不在を許可する。表のnormal初回はappend / rebuild / complete = `1 / 1 / 1`、normal committed / normal aborted / awaiting_playerのappend後complete前再試行は各`0 / 1 / 1`、recovery abortの初回は`1 / 1 / 1`、recovery abort append後の再試行は`0 / 1 / 1`で、全てそのexecute呼出し内の回数として検証する。 `ExistingActiveTurn` fast pathだけはclaimなし、その他の`execute()`はdurable claim一回であり、registry missのrecoveryも同じexecute append/rebuild/complete順を使う。 `base_event_sequence`から`prefix = {event | event.sequence <= record.base_event_sequence}`と`owned_suffix = {event | event.sequence > record.base_event_sequence}`を分け、originはcurrent identityに一致するprefixからoriginを、current identityに一致するowned_suffix（authorized candidateを含む）からcurrent owned ID/stateとrole-aware actual membershipを導く。`select_response_payload()`がpayloadの唯一authorityであり、以前のTurnをcurrent requestへ再利用しない。 Normal `TurnEventBatchFactory`は`Callable[[TurnRequestIdentity, PreparedTurn, tuple[DomainEvent, ...], OccurredAt, Sequence[EventId]], tuple[TurnEventMetadata, RecoveryEventMetadata, EventBatch]]`としてcampaign全体のvalidated tupleを明示的に受け、NewClaim後の`EventStore.read_campaign(record.campaign_id)` readをfactoryへ渡す。factory用readとclaim transaction内のsame-connection readを混同せず、normal factoryはEventStoreをcaptureしない。current-submit（current identity一致のprefixにacceptedなし・owned_suffixにaccepted/terminalなし） recoveryだけが`PlayerInputAccepted -> recovery TurnAborted`、current-resume（current identity一致のprefixにaccepted/awaitingあり・owned_suffixにTurnResumed/terminalなし） recoveryはrecovery `TurnAborted`だけとする。metadata未確定のfaultなし継続は同一executeで`1 / 1 / 1`、CAS後append前のpartial failed attemptは`0 / 0 / 0`、次回recovery abortとappend後complete前retryは表の回数を使う。
Recovery payloadの選択は`select_response_payload()`だけが行う。normal `committed` / normal `aborted` actualはversion 2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）を必須とし、version 1 / initialのみで完了する経路を作らない。awaiting actualはv2 staged outer payloadを優先し、無い場合だけv1 initial outer bytes + P1-08適用のtyped presentation defaultを使い、recovery-aborted actualはrecord versionに関係なく保存済みversion 1のinitial payloadを使う。P1-08の`StagedResponseSeed`は`narrative`、`suggested_actions`、`cost_microusd`、`processing_status`、`corrections`、必要時の公開済みtyped semantic dataとidentity/media bindingだけを持ち、Event-derived Projection/status/diceを重複保存しない。claim前のinitial builder一回はNewClaimのseedにだけ採用し、Existing claim / claim後 / recovery内では保存bytesを再利用して再生成しない。

各WP sectionの`コミット境界`が、Test FirstのRED→最小GREENのfocused command、full-green条件、明示的な`git add -- <path...>`を定義する唯一の着地点表である。下記の順序はcommit message順の要約であり、`tests/test_repository_contracts.py`をModifyするWPはmanifest serialization laneの順序を守る。P1-00、P1-00b、P1-01a、P1-01b、P1-02は完了済みであり、現在の次の着地点はP1-02直後のP1-01c scanner-hardening補正である。P1-10aとP1-01c以降の非共有path作業は、依存とmanifest serializationを壊さない範囲でのみ並列可能とし、共有manifest pathを同時にstageしない。
P1-03 Lifecycle commitの`turn_models.py` stage listには、Persistence laneの型とは別にLifecycleの型/alias `RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`を必ず含める。`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`の具体関数は`src/neontof/application/turn_lifecycle.py`だけが実装し、Lifecycle commitの`turn_lifecycle.py` stage listへ含める。P1-11はこのconcrete `reserve_recovery_event_ids`と`build_recovery_metadata`をexact importしてproduction coordinatorへ注入し、`compose_application_runtime(...)`へ外部source/factory引数を追加しない。

Persistence migrationの対応は、P1-01a=`0001_event_store.sql`（`schema_migrations`/`events`のみ、schema-set最大version `1`）、P1-01b=`0002_projection_snapshots.sql`（最大version `2`）、P1-02=`0003_observation_stores.sql`（最大version `3`）、P1-03=`0004_turn_requests.sql`（最大version `4`）とする。各WPのfocused RED/GREEN command、schema-setの連番・未知versionなし・raw SQL bytes checksum evidence、SQLを含む明示的な`git add -- <path...>`は各WP sectionに定義し、全migrationをadditive、down migrationなし、P1-01aは後続tableなしとする。P1-01aのmigrationだけは`SqliteDatabase.migrate()`を唯一のpublic mutation entryとし、private `_run_migrations`が`BEGIN IMMEDIATE`後のdedicated read source、bounded copy/verification、同一basename artifact set、DDL、schema row insert、COMMITを固定順で担う。P1-01a、P1-01b、P1-02、P1-03、P1-04、P1-05、P1-06、P1-07、P1-08、P1-09、P1-11、P1-12のRED/GREEN focused commandは、各WPの既存focused testと`tests/test_repository_contracts.py`を同じpytest invocationへ含める。

P1-08のtarget materializationはEvent-derivedなcurrent active targetの0/1件を確認し、変更時だけ`FactSuperseded(existing_fact_id)` → `FactAsserted(predicate="target_number")`の順でcandidateを作る。target不変時は追加Factなし、複数/破損active targetはfail-closedとし、full replay後のactive target 1件をP1-08で検証する。P1-08 integrationはvalidated `PublicFact` / `PublicProjection`と`TurnResponseDocument`までで完了し、`PublicSessionView`への変換はP1-11、Browser表示を含む全WP確認はP1-13が担当する。P1-11の`test_public_session_view_keeps_one_active_target_after_consecutive_turns`とP1-13のcomplete-run display assertionを別境界で実行する。
P1-11は`src/neontof/application/public_view.py`の`PublicSessionPresentation`と`build_public_session_presentation(*, response_document: TurnResponseDocument, suggested_actions: tuple[StrictStr, ...], cost_microusd: NonNegativeMicrousd, processing_status: PublicProcessingStatus) -> PublicSessionPresentation`を経由して`build_public_session_view(..., presentation=...)`を呼ぶ。Event-only reloadはevent-derived subsetだけを比較し、presentation fieldsのfull equalityを要求しない。P1-11の`test_application_runtime_injects_p1_03_factory_and_concrete_recovery_event_id_source`はP1-03の`build_recovery_metadata` / `reserve_recovery_event_ids`のexact import・production injectionを検査し、`test_public_session_view_keeps_one_active_target_after_consecutive_turns`とP1-13の表示assertionは二つのFact更新後もactive targetが1件であることを確認する。

P1-03はPersistenceとLifecycleの2 logical commitだけを順に着地させる。Persistence commitは`src/neontof/application/turn_models.py`のpersistence固有symbol（`TurnRequestIdentity`、pre-claim `TurnRequestIntent`、`ProcessingTurnRequestRecord`、`FinalTurnRequestRecord`、`CompletedTurnRequestRecord`、`TurnRequestRecord`、`NewClaim`、`ExistingProcessingClaim`、`ExistingFinalClaim`、`ClaimResult`、`RecoveryEventMetadata`、`RecoveryReason`、`RecoverySelector`、`CachedTurnResponse`、`StoreError`）、`src/neontof/persistence/turn_request_store.py`、`src/neontof/persistence/migrations/0004_turn_requests.sql`、`tests/persistence/test_turn_request_store.py`、`tests/persistence/test_migrations.py`、`tests/test_repository_contracts.py`だけをstageする。Persistence commit後のscanner検査でsame-connection readerを`1`から`2`へ遷移させる。Lifecycle commitはPersistence commit後に、同じ`turn_models.py`の`RecoveryEventRole`、`RecoveryEventIdReservation`、`RecoveryMetadataInputs`、`RecoveryEventIdDeriver`、`RecoveryEventIdSource`、`RecoveryMetadataFactory`、`PreparedEffect`、`PreparedTurn`、`RecoveryPlan`、`TurnEventBatchFactory`、`TurnEventIdSequence`、`CompletedTurnResult`、`ExistingFinalTurnResult`、`ProcessingTurnResult`、`TurnExecutionResult`、`CoordinatorResult`、`TurnPreparation`、`ResponseRebuilder`、`UndoResponseRebuilder`、`UndoCommand`、`RevertedTurnResult`、`UndoBlockedResult`、`UndoResult`、`derive_revert_event_id`、`src/neontof/application/__init__.py`、`src/neontof/application/turn_lifecycle.py`（`ActiveTurnToken`、`OwnedActiveTurn`、`ExistingActiveTurn`、`ActiveTurnAcquisition`、`ActiveTurnRegistry`、`TurnLifecycleCoordinator`、`derive_recovery_event_id`、`reserve_recovery_event_ids`、`build_recovery_metadata`、全lifecycle builder / validator / selector）、`tests/application/test_turn_lifecycle.py`、`tests/integration/test_turn_idempotency.py`、`tests/integration/test_failed_turn_observations.py`、`tests/test_repository_contracts.py`だけをstageする。Lifecycle commit後のscanner検査でapplication append callerを`0`から`2`へ遷移させる。LifecycleはPersistence laneのrecovery metadata symbolを再定義せずimportする。P1-03のapplication EventStore.append callsiteは`execute()`と`revert_latest()`の2件だけで、`append_bootstrap`、`BootstrapApplicationService`、bootstrap test/authoring pathはこのWPのどちらのcommitにも含めない。物理的に同じ`turn_models.py`を共有するが、両laneを同時編集・同時stageしない。

P1-05はP1-03 Lifecycle commit後だけに、`src/neontof/application/turn_lifecycle.py`の`append_bootstrap`追加、`src/neontof/application/bootstrap_service.py`、`tests/application/test_bootstrap_service.py`、authoring 5 path、authoring test 4 path、requirements 3 path、`tests/test_repository_contracts.py`を一つのlogical GREEN commitへstageする。P1-05後のapplication EventStore.append callsiteは同じowner classの`execute()`、`revert_latest()`、`append_bootstrap()`の3件であり、`BootstrapEventBuilder`はexact `Callable`と唯一の具体実装`src/neontof/authoring/bootstrap.py::build_bootstrap_events`に限定する。`BootstrapApplicationService`はEventBatch builderとcoordinator delegationだけを持つ。P1-11の`src/neontof/app.py::compose_application_runtime(...)`はP1-03の`build_recovery_metadata`を`recovery_metadata_factory`へ注入するだけで、P1-03のconcrete implementationを再Modify・再stageしない。

P1-08はP1-07、payload boundary確認、P1-03/P1-05の連続commit後に、`src/neontof/application/event_materializer.py`、`src/neontof/application/semantic_pipeline.py`、`src/neontof/application/turn_responses.py`、`src/neontof/application/turn_engine.py`、`src/neontof/application/turn_models.py`、対応tests、`tests/test_repository_contracts.py`をstageする。`turn_models.py`はP1-03 Lifecycle commitの所有pathであり、P1-08はそこからmodel型をimportする。P1-08で再Modifyする場合はSemantic Result / response型の追加だけをP1-03 Lifecycle commit後に行い、P1-03 Lifecycle symbolを変更せず、同じpathを並列編集・同時stageしない。P1-08 commit listには`src/neontof/application/turn_models.py`と`tests/application/test_turn_responses.py`を必ず含める。

P1-09は`EventMaterializationInput`をimportせず、`EventDraft` / `EventBatch`またはappend callerを持たない。
`materialize_provisional_details(*, identity, details)`と`promote_provisional_detail(*, identity, reference_text, provisional, projection)`は`tuple[PreparedEffect, ...]` / `PromotionOutcome.effect_candidates`だけを返す。C-02承認時にP1-09がserial Modifyする`src/neontof/application/turn_engine.py`のP1-08の`bind_turn_preparation(*, context=context)`が返す二引数callbackが、P1-08のsemantic/dice candidatesへprovisional candidatesを合流させ、`tests/integration/test_complete_fake_turn.py::test_provisional_effect_candidates_merge_into_bound_preparation_before_event_id_allocation`で候補確定後の一回の`event_id_sequence` → `OccurredAt` → `TurnEventBatchFactory` → Coordinator唯一appendを検証する。C-02延期時はP1-09のmodule/type/importと`turn_engine.py`変更を作らず、P1-12はP1-08のbase prepareから独立に進む。P1-09は`turn_models.py`の型を再定義せず、P1-12と同じ`turn_engine.py`を同時編集・同時stageしない。

P1-12の`ScenarioAdvance.effect_candidates`も同じpre-ID boundaryであり、唯一の`evaluate_after_turn(*, identity, projection, effect_candidates)`がmetadataなしでcurrent identity由来の候補を返す。シーン遷移が必要な場合は、P1-08の`materialize_accepted_result(*, identity=..., ...)`がvalidated semantic `ProposedCharacterMoved`をpre-ID候補にし、同じ`evaluate_after_turn`へ先行candidate列として渡す。P1-12は`src/neontof/scenario_runtime.py`を作成し、P1-08後に`src/neontof/application/turn_engine.py`と`tests/integration/test_complete_fake_turn.py`をserial Modify/stageしてScenario候補をbound preparationへ合流させる。`TurnEngine.__init__(..., scenario_runtime: ScenarioRuntime) -> None`と`TurnEngine.bind_turn_preparation(*, context: TurnPreparationContext) -> TurnPreparation`をこのserial extensionで固定し、`ScenarioAdvance.reached_end`を`PreparedTurn.scenario_end`へ伝搬する。全候補確定後にだけ一回の`TurnEventIdSequence`、`OccurredAt`、`TurnEventBatchFactory`へ進み、`scenario_end`時のfactoryが`TurnCommitted -> SessionEnded`（`campaign_id` / `session_id`、`scene_id=None`、`turn_id=None`、payload `reason="completed"`）を構成する。P1-12はP1-03のpost-ID型やSessionEndedを構成せず、他WPのoptional producer型を必須依存にしない。ScenarioRuntime、P1-12 service、routeは`EventStore.append()`を追加せず、P1-03のapplication append caller allowlistを2件から増やさない（P1-05後の3件はbootstrapだけである）。
P1-11のcomposition rootはP1-12のserial commit後にだけ`ScenarioRuntime`を構築し、`TurnEngine(..., scenario_runtime=scenario_runtime)`へ注入する。P1-11の`app.py`はこのwiringと既存`public_static_data`の保持だけを担当し、P1-12が未着地の状態でconstructorを仮実装しない。
P1-03のPersistence / Lifecycle各laneは自分の所有pathだけを明示stageし、依存laneを混ぜない。P1-00とP1-00bのfocused commandは既存の両test対象を維持し、P1-10a、P1-10b、P1-13はmanifest lane外のguard Gateとして別commandを使う。

P1-03/P1-08のnormal preparationは、NewClaim直後の同じ`event_boundary_lock`内で一度だけ行う`EventStore.read_campaign(record.campaign_id)`のfull validated `tuple[DomainEvent, ...]`を`TurnPreparation = Callable[[TurnRequestIdentity, tuple[DomainEvent, ...]], PreparedTurn]`へ渡し、`rebuild_projection(campaign_events)`、target/condition FactId、最終pre-ID effect candidatesをEvent ID allocation前に確定する。append後のreadはcommit結果のauthority rebuild専用であり、campaign eventsを欠くprepareや後付けProjectionは許可しない。P1-08はこの結果と保存済みpayloadから、dice projection/result、public/resource projection、narrative、suggested_actions、cost_microusd、processing_status、corrections、target_number、conditionsを含むtyped `TurnResponseDocument`を作る。P1-11の`make_response_serializer(*, public_static_data: PublicStaticData, encode_buffered_document: Callable[[BufferedTurnResponse], StrictBytes], encode_sse_document: Callable[[BufferedTurnResponse], StrictBytes]) -> ResponseSerializer`がpresentation、view、StateFrame、buffered/SSE bytesを組み立て、Coordinatorの`complete()`前にcache bodyを確定し、routeは再serializeせずforwardする。

完了済みの依存成果物:

- P1-00: `feat: Event draftとmetadataの中立契約を固定する`（commit `b5c1bf3`）
- P1-00b: `test: Phase 1のリポジトリ検査境界を固定する`（commit `31fab05`）
- P1-01a: `feat: SQLite Event Storeとmigration基盤を実装する`（commit `eb284f9`）
- P1-01b: `feat: Eventから再生成できるProjection Storeを追加する`（commit `9ee2074`）
- P1-02: `feat: TranscriptとTelemetryをEvent transaction外へ保存する`（commit `e5b7aa4`）

後続WPの着地順:

1. `test: scanner-hardening補正を固定する`（P1-01c、P1-02後。current reader `1` / application append caller `0`）
2. `feat: Turn request persistence契約を追加する`（P1-03 Persistence、`0004`。reader `1`→`2`）
3. `feat: Turn lifecycle coordinatorを追加する`（P1-03 Lifecycle、Persistence後。application append caller `0`→`2`）
4. `feat: 再現可能な最小Rulesetと資源境界を実装する`（P1-04。2d6判定、目標値、HP、Resource 1種、少数の状態異常、Clock 1本、Dice Seed導出）
5. `feat: CharacterとScenarioをEventへ正規化する`（P1-05。append caller `2`→`3`）
6. `feat: Model Gatewayの予算と安全なProvider境界を実装する`（P1-06、C-03・provider approval・承認済みexact contract反映後）
7. `feat: Visibility Filter、PublicProjection、Evidence validation、Alias解決を追加する`（P1-07）
8. `feat: 検証済みproposalだけをcoordinatorへ委譲するTurn Engineを実装する`（P1-08、payload boundary確認後）
9. `feat: Event由来のprovisional detail Projectionを追加する`（P1-09、C-02承認後）
10. `feat: Viteとvanilla TypeScriptのClient scaffoldを追加する`（P1-10a、manifest lane外）
11. `feat: 黄昏時計塔ScenarioとClock Runtimeを追加する`（P1-12、manifest lane）
12. `feat: 検証後だけNarrativeを公開するHTTP経路と訂正表示を追加する`（P1-11、P1-12後のmanifest lane）
13. `feat: Phase 1のplayable session UIとreload復元を実装する`（P1-10b、P1-10a/P1-11後）
14. `test: Phase 1の完全実行Gateと実測記録を追加する`（P1-13）

各commit前にfocused test、関連quality gate、diff scopeを確認する。依存する次WPを開始する前に、そのWPのcommitを着地させる。commit後も`git push`しない。

---

§12の型・composition・replay要約は、P1-08 `src/neontof/application/turn_responses.py`が`InitialRecoveryPayload` / `StagedResponseSeed` / `StagedRecoveryPayload` / `RecoveryPayload`と、`encode_staged_response_seed` / `decode_staged_response_seed`を含むcodec/builderを所有し、claim前のinitial bytesはNewClaimだけがseedとして採用し、ExistingProcessing/ExistingFinalとrecoveryは保存bytesだけを使うことを含む。normal committed / normal abortedはv2 staged outer payloadを必須とし、awaitingはv2 staged outer payloadまたはv1 initial outer bytes + P1-08適用のtyped default、recovery-abortedはrecord versionに関係なくv1 initialを選ぶ。P1-07のvalidated `ScenarioOutcomeFact`、P1-12のpre-ID `scenario_outcome` FactAsserted candidate、P1-08の`TurnResponseDocument.scenario_outcome`、P1-11のPython/TypeScript `PublicSessionView.scenario_outcome`、P1-13のreplayed outcome assertionは同じEvent authority経路を使う。`ScenarioRuntime` / `TurnEngine`はEventBatchを返さず、non-NULL `scenario_end`時のSessionEndedは`TurnEventBatchFactory`だけが`TurnCommitted -> SessionEnded(reason="completed")`として構成する。P1-08 focused testは`scenario_outcome=None`のcore typed response bundleまで、実ScenarioRuntimeのoutcome candidate / append / replayはP1-12、P1-11がview/JSON/DOM、P1-13が全WPのcomplete-runを担当する。

# 13. 最終Gate判定

P1-03 Gateでは、registry missの`ExistingProcessingClaim`が同じ`event_boundary_lock`内で`recover_processing(*, record: ProcessingTurnRequestRecord, campaign_events: tuple[DomainEvent, ...]) -> RecoveryPlan`へ入り、metadata未確定時の一度のCASとdecision/batch preparationだけを行うことを確認する。optional candidate validation、EventStore append、campaign全体の再read/select、Coordinator-only `ResponseRebuilder`一回、strict response validation、`TurnRequestStore.complete()`一回はexecuteの既存唯一callsiteで行う。P1-03のcaller数は`execute()` / `revert_latest()`の2件、P1-05後は`append_bootstrap()`を加えた3件であり、`RecoveryEventMetadata`の6個のIDはcurrent identity一致の`owned_suffix`にあるactual Event Logへrole別に照合し、未使用予約IDの不在を許可する。 `ExistingActiveTurn` fast path以外の各`execute()`呼出しは同じboundary lock内のdurable claimを正確に一回だけ行い、`ExistingProcessingClaim`はINSERT `0`・保存base不変のまま`recover_processing()`へ渡され、`recover_processing()`自身はclaimを呼ばない。

P1-03 Gateの回数検証はそのexecute呼出し内で行う。初回normal committed / normal aborted / awaiting_playerは各`append / rebuild / complete = 1 / 1 / 1`、normal Event append後〜complete前の各再試行はcandidateなしで`0 / 1 / 1`、初回recovery abortは`1 / 1 / 1`、recovery abort append後の再試行は`0 / 1 / 1`とする。Event Logのcurrent identity一致の`owned_suffix`に実在するlifecycle Eventだけが同一roleの予約IDのsubsetとして一致し、未使用予約IDは不在を許可する。current identityに一致する`prefix`からorigin `recovery_selector` / statusを得て、current identityに一致する`owned_suffix`からcurrent owned stateを得る。origin `recovery_selector`はCAS時点のimmutable fieldで、現在状態selectorとの単純一致を要求しない。 current-submit（current identity一致のprefixにacceptedなし・owned_suffixにaccepted/terminalなし）のrecovery abort candidateは`PlayerInputAccepted -> recovery TurnAborted`、current-resume（current identity一致のprefixにaccepted/awaitingあり・owned_suffixにTurnResumed/terminalなし）のcandidateはrecovery `TurnAborted`だけで、prefix Eventを再appendしない。metadata未確定のfaultなし継続はdurable claim 1回・metadata CAS 1回を含む同一executeで`1 / 1 / 1`、CAS後append前のpartial failed attemptは`0 / 0 / 0`で結果なし・processing保持、次回executeが`1 / 1 / 1`、normal/recovery append後complete前retryは`0 / 1 / 1`である。

Phase 1をPASSと記録できるのは、次の全条件を満たした場合だけである。

- P1-00のmetadata testと`tests/test_repository_contracts.py`が同じfocused commandでexit `0`となる
- P1-00bのrepository guard testがexit `0`となり、exact production manifest、forbidden/generated path、Python gate order、Windows runner assertion、repository tree外DB条件が確認される。P1-02直後の検査基準はsame-connection reader `1`、application-level `EventStore.append()` caller `0`であり、runtime/migration 2 exact SQLite connect callsite、type annotation / `isinstance` positive、arbitrary persistence connect negative、source/protocol/DML scannerの検証済み扱いはP1-01cのscanner-hardening Green後だけとする。
- P1-01aの`0001_event_store.sql`が`schema_migrations`と`events`だけを作り、schema-set最大version `1`、欠落なし、unknown applied versionなし、raw SQL bytes SHA-256とversion/name/checksumの一致が確認される。P1-01aのproduction manifest entryは4つの`.py`だけで、SQLはmanifest entry外である。`_discover_migrations`がavailable migration file setの同一version重複を拒否し、applied rowsのcontiguous prefix/gap/unknown applied version/version/name/checksum driftをexact schemaの実DBからDDL前に検証する。`schema_migrations.version`のPRIMARY KEYによるapplied row duplicateの挿入時拒否は実DB validation対象にしない。exact schemaは適用順序を保持しないためPhase 1では適用順序を検証せず、runnerは未適用migrationをversion昇順にだけ適用する。`PRAGMA table_info`、`PRAGMA index_list`、`PRAGMA index_xinfo`、`sqlite_master.sql`、`typeof(event_json) = 'blob'`、NOT NULL/CHECK/UNIQUE sabotageでexact schemaを再検証する
- P1-01b、P1-02、P1-03がそれぞれ`0002_projection_snapshots.sql`、`0003_observation_stores.sql`、`0004_turn_requests.sql`だけを追加し、schema-set最大versionが順に`2`、`3`、`4`で、各段階に欠落・未知version・checksum driftがないことが確認される
- migration runnerが`SqliteDatabase.migrate()`を唯一のpublic mutation entryとして、private `_run_migrations`のexact signatureで、`BEGIN IMMEDIATE`からvalidation、必要時だけのdedicated read sourceによるrepository tree外SQLite backup API copy、close/reopen verifier、実schema/data比較、同一basename artifact setのpromotionまたは全exact path cleanup、DDL、schema row insert、`COMMIT`を固定順で実行し、backup/verification失敗時にDDLを行わず、no-op時にbackup/writeを行わないことが確認される。migration connection自身をbackup sourceにせず、public `run_migrations`、public backup/restore/cleanup/diagnosticを持たない
- `SqliteDatabase`のpublic generic read/write、retry、workerがなく、typed Storeの`_read`がlock外、fixed connect kwargs/PRAGMA、migration main/source/copy直後destination/close-reopen後reopen verifierのjournal mode実readback値一致、shared write lock、別connection read、`query_only=ON`の多層防御が確認される。WAL `-wal`/`-shm`、同一basename partial/verified artifact set、`.db` variantsはrepository guardとartifact cleanup契約で管理する
- filesystem-backed regular file、canonical path・migration `main.file`・source `main.file`の三者`samefile`、relative path/hard-link alias受理、URI/in-memory/directory/special file/別file拒否、`SQLITE_OK`継続を含む10秒copy deadline、BUSY/LOCKED 200回上限、actual schema/data mismatchとverification deadline超過のDDL前`backup_failed`、cleanup不能の`backup_cleanup_failed`、test-only bounded restoreが確認される。test-local timelineはprivate helperの実関数委譲spyとmigration connectionの`set_trace_callback`だけで記録され、production global recorder/diagnostic surfaceを追加しない
- `read_campaign`の全sequence・全row・derived/readback検証、inspection-only filter、対象外破損rowのfail-closed、`read_turn`のrevert target、validated `PlayerInputAccepted.payload.turn_request_id` lookupが確認される
- 既存`DomainEventValidationError`と`DomainEventValidationIssue`/`IssueCode`がparser・sequence・projection validationの既存codeのまま伝播し、Event Storeのduplicate event IDが`EventStoreConstraintError(code="duplicate_event_id")`、その他の`sqlite3.IntegrityError`が`EventStoreConstraintError(code="event_constraint_violation")`、その他のDatabase/Migration failureが安全なcodeへ写像される。元exceptionのmessage/args/cause/context/custom attr/logを保持せず、`DomainEventValidationError`をwrapしないことが確認される
- P1-01bのEvent read→pure rebuild→monotonic upsert、stale read処理、barrierが確認される。P1-02の`tool_call`、allowlist、raw provider情報非保存、Event transaction外append、failed Turn Event 0件、table-local sequenceが確認される
- P1-03のDB-wide 1..256 bytes BLOB `request_key`（HTTPでは`Idempotency-Key`）の再送で二重処理しないこと、canonical `TurnRequestId`はidentity/contextでありidempotency keyではないこと、全identity conflict、requested media、`base_event_sequence`、`recovery_payload_version` 1/2、initial/staged recovery payload、recovery reason/IDs/timestamp、cached body非返却、campaign-scoped canonical request、transaction内resume context validation、processing/response型不変条件、`claim/stage/read/read_processing/complete`のsanitized error/CAS/cache契約、process-lifetime `ActiveTurnRegistry`、active hitだけのprocessing `202`、registry missでexecuteがdurable claimを正確に一回行って`recover_processing()`へ入り、`recover_processing()`はclaimを呼ばないorphan一度だけrecovery、current identity一致のprefixをorigin、current identity一致のowned_suffixを当該requestのactualとして分離したcampaign-wide recoveryが確認される。通常のterminal pathのsubmitは`PlayerInputAccepted -> TurnResumed -> terminal`、resumeは`TurnResumed -> terminal`、pre-model ambiguityはstarted prefix後の`TurnAwaitingPlayer`非terminal path、effectsのcommitted-only、predicted sequenceによる`project_turn_status()` / `rebuild_projection()`のappend前full validation、P1-03の`TurnLifecycleCoordinator.execute()` / `revert_latest()`だけの2 callsite allowlist、global latest-first undo、revert ID KAT、read_processing durable guardが確認される。barrier testはprepare / candidate validation / append / rebuild / completeの例外時にregistryとshared `ApplicationRuntime.event_boundary_lock`を解放し、injected prepare内のplayer input observationをEvent append failure後も保持する。P1-03では`append_bootstrap`、BootstrapApplicationService、Provider、Model、Diceを定義・実装・test・stageしない。初回normal terminal / awaiting_playerと初回recovery abortはそのexecute呼出し内で`1 / 1 / 1`、各Event append後〜complete前の再試行は`0 / 1 / 1`で、Eventを二重appendしない。current identity一致の`owned_suffix`のactual lifecycle Eventは同一roleの予約IDのsubsetとしてtype/context/canonical requestまで一致し、未使用予約IDは不在を許可する。metadata未確定のfaultなし継続は同一executeでdurable claim 1回・CAS 1回・candidate append / rebuild / complete `1 / 1 / 1`、CAS後append前crashのpartial failed attemptは`0 / 0 / 0`、次回のcurrent-submit（current identity一致のprefixにacceptedなし・owned_suffixにaccepted/terminalなし）は`PlayerInputAccepted -> recovery TurnAborted`、current-resume（current identity一致のprefixにaccepted/awaitingあり・owned_suffixにTurnResumed/terminalなし）はrecovery `TurnAborted`だけで`1 / 1 / 1`、append後complete前retryは`0 / 1 / 1`とし、prefix Eventを二重appendしない。`PreparedTurn.scenario_end`がある場合は、P1-12の`ScenarioAdvance.reached_end`からこのLifecycle fieldへ伝搬し、`TurnEventIdSequence`がSessionEnded用IDを一つだけ追加し、`TurnEventBatchFactory`だけが`TurnCommitted -> SessionEnded`（`scene_id=None`、`turn_id=None`、payload `reason="completed"`）を最後に構成することも確認する。
- recovery payloadのGateは、claim前の`build_initial_recovery_payload()`一回の供給値をNewClaimだけがseedとして採用し、Existing claim・claim後・recovery内では再生成しないこと、normal committed / normal aborted actualではversion 2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）を必須にし、version 1 / initialのみを選択しないこと、awaitingはv2 staged outer payloadまたはv1 initial outer bytes + P1-08適用のtyped default、recovery-aborted actualはrecord versionに関係なくv1 initialとすることを確認する。P1-08 `ResponseDocumentBuilder` / recovery `ResponseRebuilder`だけが`RecoveryPayload`とinner `StagedResponseSeed`をstrict decodeし、P1-03 / Storeはopaque bytesを解釈しない。
- P1-05だけが`TurnLifecycleCoordinator.append_bootstrap(*, campaign_id: CampaignId, prepare: BootstrapPreparation) -> tuple[StoredEvent, ...]`をModifyし、`BootstrapApplicationService`がexact `BootstrapEventBuilder`を一回呼んでcoordinatorへ委譲する。P1-05後にapplication-level `EventStore.append()` callerは同じowner classの`execute()`、`revert_latest()`、`append_bootstrap()`の3 callsiteとなり、bootstrapの既存Event拒否・predicted sequence validation・append一回・全Event再readとserviceのEventStore writer/lockなしが確認される。`ApplicationRuntime.bootstrap_service`がcomposition rootに保持され、`POST /api/campaigns`が`create_campaign()`だけを呼ぶことも確認される
- P1-08/P1-11のTurn pipelineがnormal Turnの全frameのcanonical body完成→`TurnRequestStore.complete()`のcache commit→HTTP adapter公開の順を守り、SSEとbufferedが同じ完成bodyから生成され、replayが保存済みstatus/media/body bytesをbyte-for-byteで返すこと、active registry hitだけがprocessing `202`を返し、registry missのexecuteがdurable claimを一回行って`ExistingProcessingClaim`を得て`recover_processing()`へ入り、recoveryがProvider/Dice/prepareを再実行しないことが確認される。composition rootがnormal / undo `ResponseRebuilder`を一回ずつ構築してcoordinatorへ注入し、coordinatorだけがnormal/recoveryのrebuilderを実行してCached responseを検証し、normal/recoveryだけ`complete()`を一回呼ぶこと、Undoはrebuild済みresponseを直接返して`complete()`を呼ばないこと、P1-08/P1-11からdirect append/completeがないことも確認される。normal committed / normal aborted / awaiting_playerの初回は`1 / 1 / 1`、各Event append後〜complete前の再試行は`0 / 1 / 1`、recovery abortの初回は`1 / 1 / 1`、recovery abort append後の再試行は`0 / 1 / 1`で、current identity一致のprefix originとcurrent identity一致のowned_suffix actualのrole subsetとして照合し、未使用予約IDの不在を許可する。 current-submit（current identity一致のprefixにacceptedなし・owned_suffixにaccepted/terminalなし）とcurrent-resume（current identity一致のprefixにaccepted/awaitingあり・owned_suffixにTurnResumed/terminalなし）のrecovery candidateを分離し、metadata CASから同一executeで完走する`1 / 1 / 1`、CAS後append前crashの`0 / 0 / 0`、normal/recovery append後complete前retryの`0 / 1 / 1`を表どおり確認する。
- P1-08 response Gateはnormal `committed` / normal `aborted`でv2のcanonical outer `StagedRecoveryPayload` bytes（内側は`StagedResponseSeed`）をstage・保存してからappend後のfull replayと組み合わせ、v1 initialだけで完了させないこと、awaitingのv2優先/v1 defaultとrecovery-abortedのv1 initial、append後complete前crashで同じnarrative・suggested_actions・cost・body bytesを再利用することを確認する。Engineのclaim前builder一回、ExistingProcessing/ExistingFinalの供給値破棄、P1-08 codecだけのstrict decode、P1-11の再serializeなしforwardも同じfocused commandで検証する。
- C-02承認時のP1-09 `PromotionOutcome.effect_candidates`とP1-12の`ScenarioAdvance.effect_candidates`はpre-ID `PreparedEffect`列だけであり、P1-08の`TurnEngine.bind_turn_preparation(context=context)`が返す二引数bound callbackへそれぞれのserial extensionとして合流した後に一回だけ`event_id_sequence` → `OccurredAt`へ進む。P1-09延期時もP1-12はP1-08のbase preparationへ独立に候補を追加し、旧metadata入力型をどちらのproducerへimportしない。
続けて`TurnEventBatchFactory` → candidate validation → P1-03 coordinator appendへ進む。`test_materialize_provisional_details_returns_pre_id_effect_candidates`、`test_scenario_advance_returns_pre_id_effect_candidates`、`test_provisional_effect_candidates_merge_into_bound_preparation_before_event_id_allocation`、`test_scenario_candidates_merge_into_bound_preparation_before_event_id_allocation`が、未採番candidateを直接`EventBatch`へ包まないこと、P1-09/P1-12がappend callerを追加しないこと、consecutive target/scene candidateのEvent replayを確認する。C-02未承認時はP1-09を実装・GREEN・commit扱いにせず、P1-12はC-02の型へ依存しない。
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
- C-01 A（通常TurnのModel call上限`1`、model由来clarification completionはPhase 1受入れ対象外）がP1-03/P1-08のTurn lifecycle/call count testと一致する
- C-02 decision gateが承認済みで、選択内容に一致するprovisional detail ID/Fact/first-mentioned testがある（P1-09を含める場合）
- C-03 decision gateが承認済みで、選択内容に一致するProvider request boundary、player input/dice到達、public-only provider spy testがある
- C-03で承認されたexact adapter path、signature、dependency、test path、git add pathが計画・実装・検証へ反映されている
- provider approvalが承認済みで、承認された一つの具体的な実Provider adapterのpath、key source、cost、destination、call上限が実装とtestへ一致している
- P1-06のFake / Recorded Fixtureと交換可能な明示承認済みの具体的な実Provider adapterが1つ存在する。Fake-onlyはPASS条件を満たさない
- C-02、C-03、またはprovider approvalが未承認なら、該当WPをGREENまたはcommit扱いにしない。player input/diceを無視する固定response方式はPASS条件を満たさない。C-01はAの境界を維持する
- 通常Turnの`max_attempts=1`、provider invocation `1`、timeout/error時retry `0`が実測される
- remote CIの状態を確認し、pending / 未確認ならPhase 1 Final Gateのremote判定を保留する。green/failureへ読み替えない

PASS後もPhase 2は開始しない。`docs/status/phase-01-first-playable-local-web-slice.md`へlocal Gate、remote **pending / 未確認**（green/failure未判定）、Known Issues、playtest結果、C-01 A/C-02/C-03/provider approvalの状態を記録する。
