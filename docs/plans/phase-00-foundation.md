# Phase 0: Foundation Contracts 詳細 Implementation Plan（候補B実行版）

> **実行エージェント向け:** この計画はユーザー承認済みの候補Bを前提にする。P0-01b以降は
> Pythonのfresh venv、locked dependency、src layout、Test First、RED/Green、実コマンドの順で
> Work Packageを完了させる。承認後の実行経路にNode、npm、TypeScript、Fastify、Zod、Vitestは
> 存在しない。P0-02aの候補比較と過去評価に現れるA/Cは背景であり、再実行しない。

**Goal:** Event履歴、セーブデータ、テスト、後続機能へ波及する最小契約と、APIキーなしで反証
可能な品質基盤を固定し、Phase 1の実装を開始できる状態にする。

**現在地と期待する挙動変化:** 現在はP0-03入口であり、P0-01/P0-01b/P0-02は完了済み、HEADは
`503a9a3`である。Phase 0完了時には、候補Bを記録した承認済みStack ADR、起動可能な空
Application、CIとローカルで同じPython Build/Test/Format/Lint/型チェック、Domain・Semantic
Result・Character Sheet・Scenarioの契約テスト、Fake / Scripted / Recorded Fixture Providerが
存在する。実ScenarioのTurn、Web UI、client、永続Event Store、実Provider、migrations directoryは
まだ存在しない。

**Architecture:** Event Logをゲーム状態の唯一の権威とし、State / CanonはEventから再構築する
Projectionとする。Semantic ResultはNarrativeと分離し、検証済みのproposed_events（非Fact
Event）とproposed_facts（FactAsserted）だけが将来のTurn Engineのappend経路へ進められる。
Transcript / Telemetryはゲーム状態transactionの外へ記録する。Phase 0は契約、純粋関数、
test-only Provider、空HTTP Application、HTTP POST + SSE + buffered fallbackの契約境界に
限定し、Event Store、Turn Engine、Context Builder、実Provider AdapterはPhase 1に残す。

**承認済み Stack（候補B）:**

| 項目 | Phase 0で固定する値 |
|---|---|
| Runtime | Python 3.14.3 |
| Server | FastAPI 0.141.1 / Uvicorn 0.52.3 |
| Contract validation | Pydantic 2.13.4 |
| Database | Python標準 sqlite3。Phase 0は接続を作らない |
| Test / format / lint / type | pytest 9.1.1 / ruff 0.16.3 / mypy 2.3.1 |
| Client | Vite + vanilla TypeScript。ClientはPhase 1でありPhase 0にclient/**を作らない |
| Transport | HTTP POST + SSE + buffered fallback。Phase 0は契約境界だけ |
| Migration | versioned SQL migration files。将来のmigrations/0001_initial.sqlだけを記録し、Phase 0にmigrations/**を作らない |
| Phase 1 first Provider候補 | OpenAI Responses API + official Python SDK。Phase 0の依存・import・networkには含めない |
| Phase 0 Provider | Fake / Scripted / Recorded Fixture。API key、network、課金なし |

上位仕様はdocs/PRODUCT_PLAN.md、docs/IMPLEMENTATION_ROADMAP.md、docs/agent-guide/architecture.md、
docs/agent-guide/build-and-verify.md、docs/agent-guide/coding-style.mdである。上位仕様の改訂が
必要になった場合は実装せず停止する。

---

## 1. Phase 定義と承認境界

### 1.1 Goal

後から変更するとEvent互換性、保存データ、テスト、全機能へ波及する契約だけを決め、Phase 1
のVertical Sliceを迷わず実装できる最小の土台を作る。Phase 0はフレームワークやゲーム機能
を完成させるPhaseではない。

### 1.2 Non-goal

- 実Scenarioを開始・進行・終了できるTurn Engine
- 完成したWeb UI、Browser Client、client/**、Streaming UI
- 永続Event Store、完成したState / Canon Projection
- 完全なCanon Ledger、Recall、日本語全文検索、Vector Database
- 実Providerへのnetwork呼び出し、API key、課金をCIまたはlocal testの前提にすること
- Phase 0のsqlite3 connection、migration runner、migrations/**、SQLite schema
- Plugin、Hook、Profile、Manifest、Capability Graph
- 二つ目の実Provider、二つ目のRuleset、二つ目のScenario形式
- Provider / Ruleset / Scenario / Memoryの汎用拡張Interface
- 認証、Docker配布、公開deploy、複数人、Scenario Editor、本格戦闘
- Phase 1のCharacter / Scenario Loader、Model Gateway、Context Builder、production pipeline
- Vite、vanilla TypeScript、package.json、tsconfig、Vitest、Zod、FastifyのPhase 0実装

### 1.3 Entry Conditions と実測状態

| 条件 | 2026-08-18の実測 | 判定 |
|---|---|---|
| docs/PRODUCT_PLAN.mdがある | Draft v0.2を確認 | 満たす |
| docs/IMPLEMENTATION_ROADMAP.mdがある | Draft v0.1を確認 | 満たす |
| Git運用方針がある | AGENTS.mdにbranch / commit / no-push規律がある | 満たす |
| 作業branchがPhase専用 | docs/phase-00-foundation | 満たす |
| コード未着地 | 実装・Build設定なし | 満たす |
| 候補Bが承認済み | Python 3.14.3を含む候補Bの承認範囲を受領 | 満たす |

### 1.4 Phase Gate

次をすべて満たした場合だけPhase 0 Gateを通過とする。CI remote runを確認できない場合は
該当Gateをpendingとし、完了扱いにしない。

- docs/adr/0001-technology-stack.mdが候補BをAcceptedとして記録し、承認引用、採用値、
  不採用理由、再評価条件がある。
- Python 3.14.3のfresh venvへrequirements.lock.txtをhash付きでinstallし、pip checkが
  成功する。requirements.inのdirect root setはfastapi / pydantic / uvicornだけ、
  requirements-dev.inの`-r`を除くdirect root setはPyYAML / httpx / mypy / pytest / ruff /
  types-PyYAMLだけで、余分なrootをFAILにする。runtime dependencyにPyYAMLがなく、
  lock生成はTEMP tool venvのpip-tools==7.6.1で固定する。
- compileall、ruff format check、ruff check、mypy strict、pytestがAPI keyなしで成功し、
  CIが同じcommandを実行する。
- 空Applicationが127.0.0.1にsingle process / single workerで起動し、明示された
  --workers 1でGET /healthがHTTP 200と{"status":"ok"}を返す。shutdown後にPIDが終了し、
  同一portへ再bindでき、stdout / stderrが空である。
- Phase 0 production codeにsqlite3 connection、Event Store、migration runner、YAML file I/O、
  OpenAI import、外部socket呼び出しがない。
- 全contract modelがContractModel（BaseModel + ConfigDict(strict=True, extra="forbid",
  frozen=True)）を通り、tuple / frozensetなどのimmutable collectionを使う。mutation sabotageと
  revalidation testがPASSする。
- Domain Eventの受信・fixture・保存境界がPydantic TypeAdapterを通り、unknown field、
  unknown version、stable ID grammar、payload不正をrejectする。model_construct(、typing.cast(、
  検証を迂回する# type: ignoreはproductionと通常quality対象にない。
- Event列から同じProjectionを再構築でき、Turn statusがpending → running → awaiting_player
  → running → committed、またはabortedへ遷移し、再起動後もawaiting_playerを保つ。
- NarrativeだけではEventが生成されない。proposed_events / proposed_factsだけが状態変更
  Proposalの宣言源であり、Evidenceの存在・可視性・predicate/value一致、duplicate proposal、
  clarification、rejectionを検証する。
- Character SheetとScenarioのYAML fixtureはtestだけがPyYAML 6.0.3のsafe_loadで読み、
  Pydanticへ渡す。production codeはYAML file I/Oを持たない。required Visibility欠落と
  gm_onlyのplayer公開をrejectする。
- Fake / Scripted / Recorded Fixtureがsuccess、failure、retry、timeout、invalid JSONを
  API key、network、課金なしで再現し、sanitized call logにraw request、context、payload、
  secretが出ない。全pytest sessionのautouse network/socket禁止境界がPASSし、network call 0を
  確認する。
- OpenAI / Anthropic / sqlite3 connectionのsource-only検索は`src/neontof`を対象に0件とし、
  requirementsの`openai`も0件にする。testsではreject caseとして語を含むことを許す。`src/**/provider_registry.py`、
  client/**、migrations/**、Dockerfile、package系、TypeScript実行経路が存在しない。禁止file /
  directoryはTest-Path / Get-ChildItemで存在そのものをFAILにする。
- docs/status/phase-00-foundation.mdにGate結果、実commandと実出力、Known Issues、CI remote
  pending、Phase 1 Entry Conditions、Playtest非該当理由が記録される。
- Gate通過後もPhase 1へ自動的に進まず、ユーザー判断を待つ。

### 1.5 Stop Conditions

次のいずれかを検出したら新機能を足さず、該当Work Packageを停止して計画・契約を縮小する。

- Specが最小fixtureと契約testで使わない型を増やし始めた。
- 二つ目の実装を想定したclass hierarchy、Provider registry、Plugin、Hook、Profile、
  Manifest、Capability Graphが現れた。
- 承認Bと異なるruntime、dependency、transport、migration方式を必要とする。
- P0-02aの過去評価記録と承認Bの間に解消不能な不一致がある。
- P0-03〜P0-07がEvent Store、Turn Engine、実Provider、Browser UI、YAML production loader
  を実装し始めた。
- State / Canonを直接更新するAPI、NarrativeをparseしてEventを作る関数、公開向けContextへ
  不可視情報を混ぜる経路が提案された。
- sqlite3.Connectionをroute、event loop、thread間で共有する設計が必要になった。
- 同一手法が2回失敗した。3回目を試さず、commandと実出力を親へ返す。
- docs/PRODUCT_PLAN.mdまたはdocs/IMPLEMENTATION_ROADMAP.mdの改訂が必要になった。

### 1.6 承認状態と次の入口

1. 本文の更新は候補Bの承認範囲を実行計画へ反映する作業である。計画review完了後、実装
   開始前にユーザーの判断を待つ。
2. Stack承認B（Python 3.14.3、FastAPI 0.141.1、Pydantic 2.13.4、Uvicorn 0.52.3、
   pytest 9.1.1、ruff 0.16.3、mypy 2.3.1、標準sqlite3、Vite + vanilla TypeScript、
   HTTP POST + SSE + buffered fallback、versioned SQL migration、Phase 1のOpenAI Responses
   API候補）は完了済みである。追加のStack比較やA/C再probeを行わず、ADRを確定してP0-01b
   へ進む。
3. A/B/C比較と過去評価の証拠はdocs/status/p0-02-technology-stack-evaluation.mdの背景
   として保持してよい。ただし承認後の実行経路は候補Bだけで、A/Cのtoolchain commandを
   実行しない。
4. エージェントはpushしない。local qualityが成功してもremote run未確認はpendingとして
   残し、ユーザーがbranchをremoteへ反映してrun結果を共有する。

---

## 2. 中核不変条件

1. Event Logがゲーム状態の唯一の権威である。State / CanonはEventから再構築可能なProjection
   であり、直接更新する公開APIを作らない。
2. Semantic ResultとNarrativeを分離する。自由文をparseして状態へ反映しない。Structured
   ResultをSchemaと文脈で検証してからEvent Proposalへ変換する。
3. Entityはstable IDを主キーとし、名前・Alias・表示名を主キーにしない。
4. Visibilityはgm_only、player_visible、対象NPC Entity IDの最小集合を持つ。公開向け呼び出し
   へ不可視情報を渡さない。
5. API keyをBrowser、通常log、Prompt、Fixture、Transcriptへ渡さない。秘密は渡さないことで守る。
6. 非信頼テキストを読むRoleへ状態変更Toolを渡さない。
7. Turnはpending / running / awaiting_player / committed / abortedを表現し、statusの権威は
   Event列とproject_turn_statusにある。runtime変数、Transcript、Telemetryを権威にしない。
8. Event appendは将来の単一transaction境界で行う。Transcript / Telemetryはその外へappendし、
   失敗Turnの記録と消費済み費用を消さない。
9. UndoはEvent削除ではなくTurnReverted appendで表現する。
10. Dice SeedはH(campaign_seed, turn_id, action_id, roll_index)から導出する。Phase 0は式と
    Contract Fixtureを固定し、Dice Runtimeは作らない。
11. 実Providerなし・API keyなしで必須testを実行する。
12. P0-07のModelInvokerは一つのCallable境界に限定し、二つ目の具体実装がないProvider
    hierarchy、registry、capabilityを作らない。

---

## 3. Scope と書き込み境界

### 3.1 この計画作成ターン

**許可:** docs/plans/phase-00-foundation.md

**禁止:** 上記以外の全ファイル。特にdocs/PRODUCT_PLAN.md、docs/IMPLEMENTATION_ROADMAP.md、
docs/adr/**、docs/specs/**、実装コード、MyWorkflow正本は編集しない。

### 3.2 承認後のPhase 0実行

NeontoFリポジトリ内で許可するpathは次の集合だけである。

- .python-version
- pyproject.toml
- requirements.in
- requirements-dev.in
- requirements.lock.txt
- .env.example
- .gitignore
- .github/workflows/ci.yml
- src/neontof/**
- tests/**
- docs/adr/**
- docs/specs/**
- docs/status/**

P0-02aのthrowaway probeはRepository外の一意なtemporary directoryだけを使う。承認後に
A/Cのprobeを再実行しない。generated venv、cache、log、実データはcommitしない。
Phase 0のchanged-pathは入口で記録した`phaseBaseCommit`から次のallowed root path manifestとの
集合差分で検査する。manifest外の変更が1つでもあればFAILとする。

~~~text
.python-version
pyproject.toml
requirements.in
requirements-dev.in
requirements.lock.txt
.env.example
.gitignore
.github/workflows/ci.yml
src/neontof/**
tests/**
docs/adr/**
docs/specs/**
docs/status/**
~~~

### 3.3 禁止パスと禁止成果物

- client/**、migrations/**、Dockerfile
- package.json、package-lock.json、.node-version、tsconfig*.json、eslint.config.mjs、
  prettier.config.mjs、vitest.config.ts、*.ts、npm script、Node toolchain設定
- TypeScriptの@ts-expect-errorを残さない。Phase 0の型負例はPythonのmypy fixtureだけで表現する
- Fastify、Zod、Vitest、ESLint、PrettierをPhase 0の依存または実行経路へ追加すること
- OpenAI SDK、openai import、API key、実Provider Adapter、src/**/provider_registry.py
- Event Store、sqlite3.Connection、migration runner、database file
- Plugin / Hook / Profile / Manifest / Capability Graph用ファイル
- .env、API key、匿名化前のProvider response、secretを含むFixture
- *.sqlite、*.db、Transcript / Telemetryの実記録、build出力、.venv、cache、coverage
- Phase 0 production codeからのYAML file I/O。YAMLはtests/**のsafe_loadだけが扱う

禁止pathは内容検索だけで済ませない。Repository内の`package.json`、`package-lock.json`、
`.node-version`、`tsconfig*.json`、`eslint.config.mjs`、`prettier.config.mjs`、
`vitest.config.ts`、`client`、`migrations`、`Dockerfile`、`src/**/openai*.py`、
`src/**/provider_registry.py`、`*.sqlite`、`*.db`の存在そのものをTest-Path / Get-ChildItem
で検査し、1件でもあればFAILとする。`sqlite3.connect`と`sqlite3.Connection`のsource hitも
0件でなければFAILとする。

---

## 4. 実装方針

### 4.1 Ownership と寿命

- Phase 0 productionは副作用を持たない純粋なContract/reducerだけとする。
  test-only reference reducerは作らない。raw fixture → production parser → production rebuildを唯一の検証経路とし、
  永続Event Storeの所有権はPhase 1でTurn Engineのappend経路へ与える。
- `src/neontof/contracts/projection.py`が`FactRecord`、`Projection`、`derive_fact_id`、
  `rebuild_projection`を所有する。これらの重複定義を`domain.py`、tests、test-only supportへ
  置かない。
- `domain.py`はEvent payload、Event envelope、Event subtype、`DomainEvent` unionを所有する。
  `event_parser.py`はraw parserと`DomainEventValidationIssue` / `DomainEventValidationError`、`turn_status.py`は
  `project_turn_status`を所有し、`ids.py`はID / `Visibility`、`base.py`はcanonical
  `ContractModel`とimmutable JSONを所有する。
- `config.py`の`ContractModel`は`src/neontof/contracts/base.py`からのre-exportだけにする。
  `app.py`はconfig側の別定義を参照せず、canonicalな`contracts/base.py`の`ContractModel`を参照
  する。ContractModelを他のpathで再定義しない。
- TranscriptEntryとTelemetryEntryはDomainEvent unionに含めず、Projection reducerの入力型
  にも含めない。
- Fake / Scripted Providerのscript cursorとcall logはprovider instanceが所有する。
  global singletonにせず、外部へ返すcallsはtuple snapshotとする。
- Fixtureはversioned・sanitized・API keyなしとし、同じ入力から同じ出力を返す。実responseを
  取得する機能はPhase 0に置かない。
- Character Sheet / Scenarioは初期入力であり、Campaign開始時にEventへ正規化される前提を
  Specに記す。元YAMLはEvent Logの代わりの権威にしない。
- ContractModelのnested modelもstrict / forbid / frozenを継承し、list / dictのmutable
  collectionを公開型に使わない。sequenceはtuple、集合はfrozensetまたはsorted tupleとする。

### 4.2 Dependency direction

~~~text
src/neontof/main.py
    └─ src/neontof/app.py / config.py / uvicorn。DomainやProviderを所有しない
src/neontof/app.py
    └─ src/neontof/contracts/base.pyのcanonical ContractModelだけを参照。Game state、Event、
       sqlite3、Providerを所有しない
src/neontof/config.py
    └─ src/neontof/contracts/base.pyをre-exportするだけで、ContractModelを定義しない
src/neontof/contracts/event_parser.py ─┐
src/neontof/contracts/turn_status.py ──┼─> src/neontof/contracts/domain.py
src/neontof/contracts/projection.py ───┘       └─ src/neontof/contracts/ids.py / base.py
src/neontof/contracts/__init__.py
    └─ contractsのcanonical exportだけを参照し、別のContractModelを定義しない
src/neontof/contracts/semantic_result.py
    └─ domain.pyのEvent / ID / Visibilityを参照。NarrativeをEventへ変換しない
src/neontof/contracts/character_sheet.py
src/neontof/contracts/scenario.py
    └─ domain.pyのstable ID / Visibilityだけを参照。file I/Oを持たない
src/neontof/model/*
    └─ semantic_result.py / domain.pyのprovider-neutral contractを参照
tests/** → src/neontof/**
tests/**のsupportはfixture / driverだけを所有し、reference reducerを所有しない
src/neontof/** → tests/** は参照しない
~~~

依存順は`event_parser.py / turn_status.py / projection.py → domain.py → ids.py / base.py`で固定
する。`domain.py`から`projection.py`、`event_parser.py`、`turn_status.py`への逆依存はない。
`projection.py`から`domain.py`への依存は許可するが、Stateを直接更新するAPIは作らない。
Model outputからStateへの直接依存矢印は作らない。Semantic validationの成功値もProposalで
あり、Phase 1 Turn EngineがDomain Ruleと現在Stateを検証してEvent envelopeを付けるまで
権威を持たない。FastAPI routeからDomain stateを直接更新する公開APIも作らない。

### 4.3 Threading / concurrency とSQLite所有権

- Phase 0のUvicornはsingle process / single workerに固定する。実entrypointは必ず--workers 1
  を明示し、workers=1以外をrejectする。background worker、queue、同時Event appendは作らない。
- FastAPIの同期def routeはthreadpoolへ移る可能性がある。route、event loop、thread間で
  sqlite3.Connectionを共有しない。
- Event Store未実装のPhase 0ではsqlite3.connectを一度も呼ばず、DB connectionとmigration
  transactionを作らない。health routeはDBに触れない。
- Phase 1の同期writer境界でconnectionの生成・利用・closeを同一ownerへ閉じ込め、write
  serializationとatomic appendをP1-01で決める。migration transactionとEvent append
  transactionは別契約とする。
- Projection reducerとValidatorは純粋関数とし、時刻、global random、process-global cacheを
  参照しない。Scripted Providerは1instanceを1test / 1Turn用に使う。

### 4.4 Compatibility / migration

- Eventはevent_version、Semantic Resultはschema_version、Character Sheetはschema_version、
  Scenarioはschema_versionとversion、Recorded Fixtureはfixture_versionを持つ。
- Phase 0はversion 1だけを受理し、未知versionを暗黙変換しない。
- Event IDからFact IDを決定論的に導出し、ID generation algorithmはenvelopeの互換契約から
  分離する。
- versioned SQL migration filesを採用するが、将来のmigrations/0001_initial.sqlの存在だけを
  ADRと計画へ記録し、migration file、schema、runnerはPhase 1 P1-01まで作らない。
- Phase 0には永続save dataがないため、契約撤回はWork Package commitを逆順にgit revertする。

---

## 5. 判断境界

### 5.1 Phase 0で固定する判断

| 判断 | 固定する範囲 | 固定しない境界 |
|---|---|---|
| Stack | Python 3.14.3、FastAPI、Pydantic、Uvicorn、標準sqlite3、locked requirements、pytest/ruff/mypy、HTTP POST + SSE + buffered fallback | Phase 1前にProvider Plugin APIを作らない |
| Client | Vite + vanilla TypeScriptをPhase 1候補として記録 | Phase 0にclient/**を作らない |
| Provider | Phase 0はFake / Scripted / Recorded Fixture、Phase 1 first候補はOpenAI Responses API + official Python SDK | Phase 0にSDK、registry、実networkを作らない |
| Migration | versioned SQL files、将来migrations/0001_initial.sql | Phase 0にmigrations/**、schema、runnerを作らない |
| Event / Projection | envelope、version、stable ID、順序、rebuild規則 | Database table、完全payload、全Rulesetを固定しない |
| Turn | status集合、request ID冪等性、TurnReverted、awaiting_player | lock、retry runtime、Turn Engineを作らない |
| Semantic Result | field、Authority、Evidence validation、Narrative非権威 | PromptやNarration Styleを固定しない |
| Authoring | Character / Scenarioの手書きYAML一形式、test-only safe_load、version | Editor、万能Schema、production loaderを作らない |

### 5.2 後回しにする判断

Event Store、SQLite table / index、migration runner、Turn Engine retry / lock、OpenAI SDKの
mapping / Tool Calling / 課金、SSE本番endpoint、WebSocket、Browser rendering、Vite client、
検索、Embedding、Auth、Docker、Plugin、Hook、Profile、二つ目のProvider / Ruleset / Scenario
形式はPhase 1以降へ残す。

---

## 6. Work Package依存関係と並列化

P0-02aの候補比較は完了済みの背景であり、候補B承認後はP0-02b ADR確定から開始する。
P0-01aのStack非依存baselineが存在する場合は再作成せず、P0-01bのPython設定を追加する。

~~~text
候補B承認済み
  ↓
P0-02b ADR確定
  ↓
MyWorkflow guide branch / 3-file commit / deploy差分0
  ↓
P0-01b Python Repository / Quality baseline + 空Application + CI
  ↓
MyWorkflow build-and-verify actual command反映commit / deploy差分0
  ↓
P0-03 Core Domain / Event Contract
  ├────────────┬────────────┐
  ↓            ↓            ↓
P0-04        P0-05        P0-06       ← 互いに素なpathで並列
  ↓
P0-07                              ← P0-04 commit後
  └────────────┴────────────┘
                 ↓
統合シーム監査・Phase Gate・Status Report
~~~

| Package | 直列依存 | 並列可否 |
|---|---|---|
| P0-02b | 候補B承認 | ADR commit後、MyWorkflowの`docs/neontof-phase-00-guides` branchで3ファイルを更新・review・commit・deploy。NeontoFのP0-01bとは別commit |
| P0-01b | P0-02bとMyWorkflowのB guide commit | Python共通設定、entrypoint、CIを所有するため単独。実測後にMyWorkflowの`build-and-verify.md`を別commitでactual commandへ更新 |
| P0-03 | P0-01b + P0-01b実測後のMyWorkflow `build-and-verify.md` commit | 共通ID / Event / Visibilityを所有するため単独 |
| P0-04 | P0-03 | P0-05 / P0-06と並列可 |
| P0-05 | P0-03 | P0-04 / P0-06と並列可 |
| P0-06 | P0-03 | P0-04 / P0-05と並列可 |
| P0-07 | P0-04 | P0-05 / P0-06のreviewと並列可 |

依存元diffは一次review、非メイン側AI二次review、検証、commitまで着地させてから後続を開始
する。全diff統合後は重複、Signature衝突、versionずれ、Python経路へのNode / OpenAI混入、
SQLite所有権の合成退行だけを1回シーム監査する。

---

## 7. P0-02: Technology Stack ADR

### 7.1 Goal、決定境界、Non-goal

**Goal:** 承認済み候補Bを再現可能なADRへ固定し、P0-01b以降を一つのPython実行経路で進め
られるようにする。ADRは採用値、dependency境界、threading / SQLite所有権、Phase 1候補、
再評価条件を明示する。

**Non-goal:** 複数Provider、Plugin API、Database schema、Browser UI、実Provider Prompt、
検索実装、Dockerfile。

### 7.2 候補比較と承認結果

A/CはP0-02aの過去評価を識別する背景であり、承認後の実行経路ではない。

| 候補 | 過去評価の構成 | 承認後の扱い |
|---|---|---|
| A | TypeScript / Node、Fastify、SQLite、Zod、Vitest、Vite + vanilla TypeScript | 背景記録のみ。command、依存、source、clientを作らない |
| B | Python 3.14.3、FastAPI 0.141.1、Pydantic 2.13.4、Uvicorn 0.52.3、標準sqlite3、pytest 9.1.1、ruff 0.16.3、mypy 2.3.1、Vite + vanilla TypeScript | **承認済み。P0-02b以降の唯一の実行経路** |
| C | Go / net-http、strict JSON decoder、SQLite、Vite + vanilla TypeScript | 背景記録のみ。再probe、source、moduleを作らない |
| D | 何もしない／今は決めない | P0-01b Gateを実行できないため不採用 |

候補Bの内部値は次で固定する。

| 項目 | 採用値 |
|---|---|
| Runtime | Python 3.14.3。.python-versionとpy -3.14 version assert |
| Production dependency | fastapi==0.141.1、pydantic==2.13.4、uvicorn==0.52.3 |
| Database | Python標準sqlite3。P0は接続ゼロ |
| Development dependency | pytest==9.1.1、ruff==0.16.3、mypy==2.3.1、PyYAML==6.0.3、httpx、types-PyYAML |
| YAML | P0-05/P0-06のtest/dev-only fixture parser。runtime production dependencyではない |
| Transport | HTTP POST + SSE + buffered fallback。P0はpure contractだけ |
| Client | Vite + vanilla TypeScript。Phase 1だけで使用しP0にclient/**を作らない |
| Migration | versioned SQL migration files。P1でmigrations/0001_initial.sqlを作る候補として記録 |
| Provider | P0はFake / Scripted / Recorded Fixture。P1 first候補だけOpenAI Responses API + official Python SDKと記録 |

### 7.3 ファイルと責務

承認B後に作成するADRはdocs/adr/0001-technology-stack.mdだけである。過去評価reportがある
場合は書き換えず、比較結果と現在の承認を混同しない。

ADR commit完了後、P0-02bの同じ承認B範囲で、別RepositoryのMyWorkflowにbranch
`docs/neontof-phase-00-guides`を作る。Bの実pathは`.python-version`、`pyproject.toml`、
`requirements.in`、`requirements-dev.in`、`requirements.lock.txt`、`.env.example`、`.gitignore`、
`.github/workflows/ci.yml`、`src/neontof/**`、`tests/**`、`docs/adr/**`、`docs/specs/**`、
`docs/status/**`であり、MyWorkflow側で更新対象にするのは
`architecture.md`、`coding-style.md`、`build-and-verify.md`の3ファイルだけである。
`architecture.md`にはBの実path、FastAPIのasync/sync routeとsync routeのthreadpool移行、
Uvicorn single worker、sqlite3 connectionのowner / non-sharing / single writer boundary、
Event appendとTranscript / Telemetryのtransaction分離を記録する。`coding-style.md`には
Python type hints、Pydantic strict / frozen / tuple、薄いFastAPI adapter、ruff / mypy / pytest、
Vite TypeScript clientがsecretとDBを保持しない境界を記録する。P0-02b時点の
`build-and-verify.md`は「Bのstackと未確定blockは確定済み、実測command / expected output / CI
parityはP0-01b完了後に置換する」と整理する。P0-01b完了後に同じbranchで
`build-and-verify.md`だけを実確定値へ更新する。

MyWorkflow側の操作はNeontoFと別のcommit boundaryで行い、MyWorkflow `main`へ直接commitせず、
pushもしない。レビュー後に明示pathだけをstageし、
`node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs --apply NeontoF`、続けて
`node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs NeontoF`を実行し、展開差分0を
確認する。以下は計画へ戻す実行順であり、今回の計画編集ターンではMyWorkflowを編集しない。

ADRには次の補助probe証拠をそのまま記録する。

~~~text
PyYAML=6.0.3
safe_load=utf8_and_mapping_pass
No broken requirements found.
api_call=False
~~~

これはPyYAML 6.0.3がUTF-8 mapping fixtureをsafe_loadでき、requirementsに壊れた参照がなく、
API callを行っていないという証拠である。Phase 0 production codeはYAML file I/Oを持たず、
tests/**だけがsafe_loadを使う。PyYAMLをruntime production dependencyへ移さない。

ADRには将来のversioned SQL migrationとしてmigrations/0001_initial.sqlを記録するが、
Phase 0のpathとしてmigrations/**を許可しない。SQLite migration transactionとEvent append
transactionはP1-01で別契約として決める。OpenAI Responses API + official Python SDKは
Phase 1 first Provider候補として記録するだけで、P0のrequirements、lock、source、test、
fixtureへopenaiを混入させない。

### 7.4 外部調査、独立裏取り、過去評価の扱い

1. P0-02aのCodex / Claude調査、公式一次資料URL、実測command、A/B/C probe結果、temporary
   directory cleanup結果は過去評価reportに保持する。
2. 本計画の実装者はA/Cのtoolchainを再インストールせず、比較を再probeへ拡張しない。
3. ADRではBを選んだ理由をSchema Validation、fixture記述性、API keyなしのFake、single
   worker境界、HTTP fallback、標準sqlite3の所有権明示として記録する。
4. 再評価triggerは、security fix停止、locked installの再現不能、strict schema / unknown
   field rejectionの破綻、HTTP POST + SSE fallbackでPhase 1の再開が表現できない実例2件以上
   とする。

### 7.5 承認後に実行するB境界、Test First、期待結果

P0-02bはADR commitの後にMyWorkflowのbranchを切り、指定3ファイルだけを更新してreview / commit /
deployする。そのcommitが着地してからP0-01bのPython fresh venv / lock install / pip checkを
始める。P0-01bの実測後にMyWorkflowの`build-and-verify.md`だけをactual command、expected
output、CI parityへ更新し、NeontoFのcommitとは分離する。A/Cのnpm、Vitest、Zod、Fastify、
TypeScript、Goの実行経路は承認後手順に存在しない。

ADRのGreen条件は、versions、requirementsのruntime/dev分離、PyYAML dev-only、lockのopenai
不在、Uvicorn single worker、FastAPI sync routeとsqlite3 ownership、P1 migration境界、
Pydantic strict / frozen、TypeAdapter discriminator、mypy plugin、negative fixture方針、
transportが契約境界だけであることが文書にあることである。

### 7.6 Commit boundary、Gate証拠、rollback

過去評価のcommit（既存の場合）はdocs: 技術スタック候補の比較結果を記録する。
承認B後のADR commit名は docs: NeontoFのPython技術スタックを決定する とする。
stageはdocs/adr/0001-technology-stack.mdだけとし、Accepted、承認引用、exact dependency、
PyYAML証拠、SQLite ownership、migration境界、OpenAI Phase 1候補、A/C/D不採用理由、
再評価triggerを揃える。

ADR commit後のMyWorkflow側は、次の境界で実行する。

~~~powershell
Set-Location -LiteralPath C:\Users\KINGkawamura\Documents\MyWorkflow
git switch -c docs/neontof-phase-00-guides
# architecture.md、coding-style.md、build-and-verify.mdだけを編集する
git add architecture.md coding-style.md build-and-verify.md
git diff --cached -- architecture.md coding-style.md build-and-verify.md
git diff --cached --name-only
# staged diffのreview完了を確認してからcommitする
git commit -m "docs: NeontoFのPythonガイドを更新する"
git show --check --stat HEAD
node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs --apply NeontoF
node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs NeontoF
~~~

`git diff --cached --name-only`の期待結果は上記3ファイルだけであり、deployの期待結果は
展開差分0である。P0-01b完了後の`build-and-verify.md`実測反映は同じbranchで
`git add build-and-verify.md`だけを行う別commitとし、同じreview / deployを通す。
MyWorkflowの`main`へ直接commitしない、pushしない、NeontoFと同一commitにしない。

リスクは高。Phase 1着手前ならADR commitをgit revertする。過去評価reportは削除せず、
選択変更時は新しいADRまたはsupersede記録で根拠を残す。

---

## 8. P0-01: Repository and Quality Baseline

### 8.1 Goal、決定境界、Non-goal

**Goal:** 候補Bでfresh venv、exact lock、src layout、空Application、API key不要のPython
quality commandをlocalとCIの両方で実行できるようにする。

**決定する:** Python version、requirements runtime/dev分離、lock install、Pydantic plugin、
ruff / mypy / pytest設定、localhost bind、Uvicorn single worker、entrypoint、CI parity、
.env.example、生成物除外。

**Non-goal:** Game endpoint、Browser Client、client/**、Database、sqlite3 connection、Event
Store、migration、実Provider、Secret Store、Turn処理。

### 8.2 作成・変更ファイルと責務

作成pathは3.2の集合を超えない。

- .python-version — 3.14.3。実行時にpy -3.14 version assertも行う。
- requirements.in — fastapi==0.141.1、pydantic==2.13.4、uvicorn==0.52.3だけ。
- requirements-dev.in — `-r requirements.in`でruntime inputをincludeし、PyYAML==6.0.3、
  httpx、mypy==2.3.1、pytest==9.1.1、ruff==0.16.3、types-PyYAMLだけをdev/test-onlyとして
  記す。`-r`行を除くdirect root setはこの6名だけとする。
- requirements.lock.txt — `requirements-dev.in`をsource inputにしたruntime + devの完全resolved
  lock。`--generate-hashes`で生成し、Python 3.14.3のfresh venvへhash付きinstall可能で、
  openaiを含めない。lock生成用のpip-toolsはこのroot setに含めない。
- pyproject.toml — src layoutのpytest path、ruff、mypy strict、Pydantic mypy plugin、
  warn_unused_ignores、pytest設定。package系、tsconfig、Node設定は作らない。
- .env.example — NEONTOF_HOST=127.0.0.1、NEONTOF_PORT=8765、NEONTOF_WORKERS=1。API keyなし。
- .gitignore — .venv、Python cache、coverage、*.sqlite、*.db、.env、temporary output。
- .github/workflows/ci.yml — localと同じPython install、pip check、compileall、ruff format
  check、ruff check、mypy、pytest。Node commandを列挙しない。
- src/neontof/__init__.py — package marker。global stateを作らない。
- src/neontof/config.py — host、port、workers=1を検証。API key、DB、Providerを読まない。
- src/neontof/app.py — FastAPI factoryとGET /healthだけ。Game state、sqlite3、Providerを所有しない。
- src/neontof/main.py — python -m neontof.mainのentrypoint。--workers 1を固定する。
- tests/test_app.py — health HTTP 200 / JSON、localhost、API key不要。
- tests/conftest.py — 全pytest sessionへautouseのnetwork/socket禁止境界を適用する。
- tests/support/no_external_network.py — socket、HTTP client、urllibの外部接続をfail-fastする
  test-only support。外部API / socketを使う実装はpytest全体でFAILにする。
- tests/typecheck_fixtures/** — Transcript / TelemetryをDomainEventへ渡せないnegative mypy
  fixtureだけ。通常mypyからexcludeし別commandでexpected exit 1を証拠にする。

pyproject.tomlの設定は次を満たす。

~~~toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
target-version = "py314"
line-length = 100
src = ["src", "tests"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"

[tool.mypy]
python_version = "3.14"
strict = true
warn_unused_ignores = true
plugins = ["pydantic.mypy"]
exclude = "(^|/)(tests/typecheck_fixtures)(/|$)"

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
warn_untyped_fields = true
~~~

通常qualityのmypyはpython -m mypy --strict src tests --exclude tests/typecheck_fixturesを
使う。negative fixtureは通常qualityから除外し、python -m mypy --strict
tests/typecheck_fixtures/transcript_telemetry_into_domain_event.pyを別に実行する。この
別commandはstdout / stderrを捕捉してexpected exit 1、error line exactly 2、両方`[arg-type]`、
その他のerror 0件を確認し、fixture filename、`TranscriptEntry`、`TelemetryEntry`、`DomainEvent`の
各fragmentも出力に含める。任意の`[arg-type]` 2件だけを成功扱いにしない。

negative fixtureは次のように、productionの実型`DomainEvent`、`TranscriptEntry`、`TelemetryEntry`を
importするtyped sinkへTranscript / Telemetryを渡す型境界を明示する。`# type: ignore`、
`assert_type`、`cast(`はfixtureにも他のsource / testsにも置かない。

~~~python
from neontof.contracts.domain import DomainEvent, TelemetryEntry, TranscriptEntry
from neontof.contracts.projection import rebuild_projection

def project_domain_event(event: DomainEvent) -> None:
    rebuild_projection((event,))

def typed_sink(transcript_entry: TranscriptEntry, telemetry_entry: TelemetryEntry) -> None:
    project_domain_event(transcript_entry)
    project_domain_event(telemetry_entry)
~~~

### 8.3 型とSignature

~~~python
from collections.abc import Mapping, Sequence
from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

class HealthResponse(ContractModel):
    status: Literal["ok"]

class ServerOptions(ContractModel):
    host: str
    port: int
    workers: Literal[1] = 1

def load_server_options(env: Mapping[str, str]) -> ServerOptions: ...
def create_app() -> FastAPI: ...
def main(argv: Sequence[str] | None = None) -> None: ...
~~~

load_server_optionsはhost=127.0.0.1、port=8765、workers=1をdefaultする。不正port、空host、
workers != 1は起動前にrejectする。health routeは同期defでもよいが、sqlite3 connectionや
共有mutable objectを参照しない。mainはUvicornへworkers=1を固定して渡す。

全P0 contract modelはContractModelを継承する。ConfigDict(strict=True, extra="forbid",
frozen=True)を全modelへ適用し、公開fieldにはlist / dictを使わずtuple / frozenset /
sorted tupleを使う。再検証はmodel_validateまたはTypeAdapter.validate_pythonだけを使い、
model_construct、typing.cast、# type: ignoreによる迂回を作らない。ID grammarは
Annotated[str, StringConstraints(pattern=...)]、object unionはTypeAdapter + Field(
discriminator="type")で定義する。

### 8.4 Test First、RED / Green

1. Runner bootstrap: .python-version、requirements、pyproject、.gitignore、.env.example、
   CIのinstallとpytest設定を作り、fresh venvへのlock installとpip checkを確認する。test
   fileなしのpytest exit 5をRED扱いにせず、import REDを使う。
2. 最初のRED: tests/test_app.pyがneontof.appのcreate_appとGET /healthを要求する。app.pyを
   まだ作らず、python -m pytest tests/test_app.py -qを実行し、pytest runner起動後の
   ModuleNotFoundErrorまたはexport不在でexit 1になることを確認する。
3. 最小Green: src/neontof/__init__.py、config.py、app.py、main.pyを追加し、同じtestを
   exit 0にする。GET /healthだけを実装し、DB、Event、Provider、clientを追加しない。
4. Quality: compileall、ruff format check、ruff check、mypy strict、pytestを同じfresh venvで
   実行し、Pydantic pluginとwarn_unused_ignoresの実出力を記録する。
5. Entrypoint probe:実際のpython -m neontof.mainを`PYTHONPATH=src`で--workers 1でspawnし、
   HTTP 200 / JSONの後にCTRL_BREAK_EVENT相当でgraceful shutdownを要求する。強制killだけを
   成功証拠にせず、graceful wait、exit code、stdout / stderr empty、同一portへの2回目のHTTP
   health responseを検証する。Phase 0にはshutdown endpointを作らない。これは新しい公開APIを
   増やさず、OS signal lifecycleをentrypoint契約にするというNon-goal判断である。
6. CIのquality commandへ一時的にexit 1を注入し、actionlintまたはrunner / remote runが
   failureをnon-zeroで検出することを確認してworkflowを復元する。remote未確認はpending。

### 8.5 実行コマンドと期待結果

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) {
  throw "Unable to determine repository root"
}
Set-Location -LiteralPath $repositoryRoot

py -3.14 --version
py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
$lockToolRoot = Join-Path $env:TEMP ("neontof-p0-lock-tool-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $lockToolRoot -Force | Out-Null
$lockToolVenv = Join-Path $lockToolRoot ".venv"
$lockToolPython = Join-Path $lockToolVenv "Scripts/python.exe"
py -3.14 -m venv $lockToolVenv
& $lockToolPython -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
& $lockToolPython -m pip install --require-virtualenv "pip-tools==7.6.1"
$pipToolsVersion = (& $lockToolPython -c "import importlib.metadata; print(importlib.metadata.version('pip-tools'))").Trim()
if ($pipToolsVersion -ne "7.6.1") { throw "Unexpected pip-tools version: $pipToolsVersion" }
Write-Output "pip-tools ($pipToolsVersion)"
$pipCompile = Join-Path $lockToolVenv "Scripts/pip-compile.exe"
$customCompileCommand = "pip-compile --generate-hashes --output-file requirements.lock.txt requirements-dev.in"
$customCompileCommandWasSet = Test-Path Env:CUSTOM_COMPILE_COMMAND
$customCompileCommandOriginal = $env:CUSTOM_COMPILE_COMMAND
try {
  $env:CUSTOM_COMPILE_COMMAND = $customCompileCommand
  & $pipCompile --generate-hashes --output-file requirements.lock.txt requirements-dev.in
  if ($LASTEXITCODE -ne 0) { throw "pip-compile failed" }
}
finally {
  if ($customCompileCommandWasSet) {
    $env:CUSTOM_COMPILE_COMMAND = $customCompileCommandOriginal
  } else {
    Remove-Item Env:CUSTOM_COMPILE_COMMAND -ErrorAction SilentlyContinue
  }
}
if ($lockToolRoot -notlike (Join-Path $env:TEMP "neontof-p0-lock-tool-*") ) {
  throw "Refusing to remove an unvalidated lock tool path"
}
Remove-Item -LiteralPath $lockToolRoot -Recurse -Force

function Get-DirectRootNames([string] $path) {
  $names = @()
  foreach ($line in Get-Content -LiteralPath $path) {
    $entry = ($line -replace "\s+#.*$", "").Trim()
    if ($entry -eq "" -or $entry.StartsWith("#") -or $entry -match "^-r\s+") { continue }
    if ($entry -notmatch "^(?<name>[A-Za-z0-9][A-Za-z0-9_.-]*)\s*(?:==|~=|!=|<=|>=|<|>|;|$)") {
      throw "Unsupported direct requirement syntax in ${path}: $entry"
    }
    $names += $Matches.name.ToLowerInvariant()
  }
  return @($names | Sort-Object -Unique)
}
$runtimeExpected = @("fastapi", "pydantic", "uvicorn") | Sort-Object
$devExpected = @("pyyaml", "httpx", "mypy", "pytest", "ruff", "types-pyyaml") | Sort-Object
$runtimeActual = @(Get-DirectRootNames "requirements.in")
$devActual = @(Get-DirectRootNames "requirements-dev.in")
if (Compare-Object -ReferenceObject $runtimeExpected -DifferenceObject $runtimeActual) {
  throw "requirements.in direct root set mismatch"
}
if (Compare-Object -ReferenceObject $devExpected -DifferenceObject $devActual) {
  throw "requirements-dev.in direct root set mismatch"
}
if (($runtimeActual + $devActual) -contains "openai") { throw "openai is an extra direct root" }
Write-Output "requirements_runtime_root_set=fastapi,pydantic,uvicorn"
Write-Output "requirements_dev_root_set=pyyaml,httpx,mypy,pytest,ruff,types-pyyaml"

py -3.14 -m venv .venv
$neontofPython = (Resolve-Path -LiteralPath ".venv/Scripts/python.exe").Path
& $neontofPython -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
& $neontofPython -m pip install --require-hashes -r requirements.lock.txt
& $neontofPython -m pip check
$lockText = Get-Content -Raw -LiteralPath "requirements.lock.txt"
if ($lockText -match "(?im)^\s*openai(?:[<=>!~;\s]|$)") { throw "openai must not be in requirements.lock.txt" }
Write-Output "requirements_lock=openai_absent"
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
& $neontofPython -m compileall -q src
& $neontofPython -m ruff format --check src tests
& $neontofPython -m ruff check src tests
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
& $neontofPython -m pytest -q
~~~

期待結果はPython 3.14.3 version assert、`pip-tools (7.6.1)`、pip checkのNo broken requirements found.、
direct root setの集合一致、requirements.lock.txtのopenai不在、compileall exit 0、ruff
format差分なし、ruff error 0、mypy error 0、全pytest passedである。`--no-deps`は使わない。
lockはfresh venvへ`python -m pip install --require-hashes -r requirements.lock.txt`でinstall
できる完全lockとする。pip-toolsのtool venvはRepository外のTEMPだけに作り、生成後に検証済み
TEMP pathをcleanupし、runtime/dev dependency root setとcommitへ含めない。

negative mypy evidence:

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
$negativeOutput = (& $neontofPython -m mypy --strict tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py 2>&1 | Out-String)
$negativeExit = $LASTEXITCODE
$negativeOutput
$negativeLines = @($negativeOutput -split "`r?`n" | Where-Object { $_ -ne "" })
$errorLines = @($negativeLines | Where-Object { $_ -match 'error:' })
$argTypeLines = @($errorLines | Where-Object { $_ -match '\[arg-type\]' })
$otherErrorLines = @($errorLines | Where-Object { $_ -notmatch '\[arg-type\]' })
if ($negativeExit -ne 1) { throw "negative mypy expected exit 1, got $negativeExit." }
if ($errorLines.Count -ne 2 -or $argTypeLines.Count -ne 2 -or $otherErrorLines.Count -ne 0) { throw "negative mypy error surface mismatch." }
foreach ($fragment in @('tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py', 'TranscriptEntry', 'TelemetryEntry', 'DomainEvent')) {
  if ($negativeOutput -notmatch [regex]::Escape($fragment)) { throw "negative mypy output lacks fragment: $fragment" }
}
"negative mypy exit $negativeExit; errors=$($errorLines.Count); arg-type=$($argTypeLines.Count); other-errors=$($otherErrorLines.Count)"
~~~

期待結果はstdout / stderrを捕捉したexit 1、error lines exactly 2、両方`[arg-type]`、other errors 0、
fixture filename / `TranscriptEntry` / `TelemetryEntry` / `DomainEvent`の各fragmentありである。通常qualityは
negative fixtureを除外してexit 0、負例単独は型境界が壊れた場合にexit 1となる。

実entrypoint probeはRepository外のtemporary outputへredirectする。`PYTHONPATH=src`を一貫して
使い、HTTP 200 / JSONの後にWindows process groupへCTRL_BREAK_EVENT相当を送る。graceful
shutdownを待ち、exit code 0、stdout / stderr empty、同一portの2回目のHTTP health 200 / JSON、
2回目のgraceful exitを実測する。bind failure、health timeout、graceful wait timeout、非0
exit codeはFAILである。Phase 0にはshutdown endpointを作らない。`Stop-Process -Force`は失敗時
の環境cleanupに限り、正常終了の証拠にはしない。Uvicornのsingle process / single workerを
明示し、--workers 1省略を成功扱いにしない。

~~~powershell
$probeRoot = Join-Path $env:TEMP ("neontof-p0-entry-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
$stdoutPath = Join-Path $probeRoot "stdout.txt"
$stderrPath = Join-Path $probeRoot "stderr.txt"
$stdoutPath2 = Join-Path $probeRoot "stdout-rebind.txt"
$stderrPath2 = Join-Path $probeRoot "stderr-rebind.txt"
$ctrlBreakPath = Join-Path $probeRoot "send-ctrl-break.py"
$ctrlBreakSource = @'
import os
import signal
import sys

os.kill(int(sys.argv[1]), signal.CTRL_BREAK_EVENT)
'@
[System.IO.File]::WriteAllText($ctrlBreakPath, $ctrlBreakSource, [System.Text.UTF8Encoding]::new($false))
$port = 18765
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
$process = $null
$rebind = $null
function Wait-Health([int] $TargetPort, [System.Diagnostics.Process] $TargetProcess) {
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    if ($TargetProcess.HasExited) { throw "Bind failed: process exited before health" }
    try { return Invoke-WebRequest -Uri "http://127.0.0.1:$TargetPort/health" -UseBasicParsing }
    catch { Start-Sleep -Milliseconds 250 }
  }
  throw "Health timeout or bind failure"
}
function Stop-Gracefully([System.Diagnostics.Process] $Target) {
  if ($Target.HasExited) { throw "Process exited before graceful signal" }
  & $neontofPython $ctrlBreakPath $Target.Id
  if ($LASTEXITCODE -ne 0) { throw "CTRL_BREAK_EVENT helper failed" }
  if (-not $Target.WaitForExit(10000)) { throw "Graceful shutdown timeout" }
  if ($Target.ExitCode -ne 0) { throw "Unexpected graceful exit code: $($Target.ExitCode)" }
}
try {
  $process = Start-Process -FilePath $neontofPython -ArgumentList @("-m", "neontof.main", "--host", "127.0.0.1", "--port", "$port", "--workers", "1") -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden
  $health = Wait-Health $port $process
  if ($health.StatusCode -ne 200) { throw "Unexpected health status" }
  if (($health.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected health JSON" }
  Stop-Gracefully $process
  if (-not $process.HasExited) { throw "PID did not exit after graceful shutdown" }
  if ((Get-Content -Raw -LiteralPath $stdoutPath) -ne "") { throw "stdout is not empty" }
  if ((Get-Content -Raw -LiteralPath $stderrPath) -ne "") { throw "stderr is not empty" }

  $rebind = Start-Process -FilePath $neontofPython -ArgumentList @("-m", "neontof.main", "--host", "127.0.0.1", "--port", "$port", "--workers", "1") -RedirectStandardOutput $stdoutPath2 -RedirectStandardError $stderrPath2 -PassThru -WindowStyle Hidden
  $health2 = Wait-Health $port $rebind
  if ($health2.StatusCode -ne 200) { throw "Unexpected rebind health status" }
  if (($health2.Content | ConvertFrom-Json).status -ne "ok") { throw "Unexpected rebind health JSON" }
  Stop-Gracefully $rebind
  if (-not $rebind.HasExited) { throw "Rebind PID did not exit gracefully" }
  if ((Get-Content -Raw -LiteralPath $stdoutPath2) -ne "") { throw "rebind stdout is not empty" }
  if ((Get-Content -Raw -LiteralPath $stderrPath2) -ne "") { throw "rebind stderr is not empty" }
  Write-Output "entrypoint_lifecycle=graceful_exit_0_rebind_health_200"
} finally {
  # Force-kill is cleanup after a failed assertion, never a success criterion.
  if ($null -ne $process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
  if ($null -ne $rebind -and -not $rebind.HasExited) { Stop-Process -Id $rebind.Id -Force }
  Remove-Item -LiteralPath $probeRoot -Recurse -Force
}
~~~

CI quality jobはlocalと同じ順序を固定する。

~~~yaml
- run: py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
- run: py -3.14 -m venv .venv
- run: .venv/Scripts/python -m pip install --require-hashes -r requirements.lock.txt
- run: .venv/Scripts/python -m pip check
- run: .venv/Scripts/python -m compileall -q src
- run: .venv/Scripts/python -m ruff format --check src tests
- run: .venv/Scripts/python -m ruff check src tests
- run: .venv/Scripts/python -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
- run: .venv/Scripts/python -m pytest -q
~~~

### 8.6 Commit boundary、Gate証拠、rollback

1. chore: PythonのRepository境界を固定する — .python-version、.gitignore、.env.example。
2. chore: Pythonのlocked quality runnerをbootstrapする — pyproject.toml、requirements、
   CI install / quality設定。
3. test: localhost healthの最初のREDを固定する — tests/test_app.py。
4. feat: 空のFastAPI ApplicationとPython entrypointを追加する — src/neontof/**。
5. chore: CIにPython quality gateを再現する — .github/workflows/ci.yml。

Gate証拠はversion assert、fresh install、pip check、compileall、ruff、mypy、pytest、
`pip-tools (7.6.1)`のTEMP tool venv、固定pip-compile、requirements direct root set集合一致、
openai不在、health JSON、HTTP status、graceful exit code 0、PID終了、rebind後の2回目health、
stdout / stderr、CI failure / green run、sqlite3接続0件とする。MyWorkflow側の3ファイルcommitと
展開差分0はNeontoFのcommitとは別の証拠として記録する。

---

## 9. P0-03: Core Domain and Event Model Specification

### 9.1 Goal、決定境界、Non-goal

**Goal:** Event Log単一権威、stable ID、Visibility、Turn status、version、Projection rebuild、
Transcript / Telemetry分離を、文書と実行可能な純粋Contractで固定する。

**決定する:** ID grammar、Event envelope、最低Event type、TurnAwaitingPlayer / TurnResumed /
TurnAborted、Fact ID導出、parser Signature、Projection reducer、project_turn_status、revert
semantics、Event順序、version rejection。

**Non-goal:** P0-03では次を実装・公開しない。

- Event append、Event Store、Store interface、DB、database table、sqlite3 transaction、
  migration runner、Turn Engine。
- 実HTTP resend冪等、resend時の既存結果返却、任意revert、部分revert、recursive revert、
  TurnStarted、EmptyPayload。
- test-only reference reducer、decoded `Mapping` を受け取るpublic parser、versionを暗黙変換する
  parser、Narrative / Transcript / TelemetryをEvent payloadへ入れる経路。
- Plugin、Hook、Profile、Manifest、Capability Graph、二つ目のProvider / Ruleset / Scenario。

Event typeは17種を維持し、`TurnStarted`を追加しない。P0のsame-request規則はcanonical Event列の
対象Turn Eventが同一`turn_request_id`を持つこと、二重`PlayerInputAccepted`とrequest mismatchを
rejectすることまでを検証する。実HTTP再送の既存結果返却はP1-03で扱う。

### 9.2 作成ファイルと責務

P0-03の新規pathは次の完全列挙だけである。ここにない新規pathを追加しない。

**新規path:**

- `docs/specs/core-domain-and-events.md`
- `src/neontof/contracts/__init__.py`
- `src/neontof/contracts/base.py`
- `src/neontof/contracts/ids.py`
- `src/neontof/contracts/domain.py`
- `src/neontof/contracts/event_parser.py`
- `src/neontof/contracts/projection.py`
- `src/neontof/contracts/turn_status.py`
- `tests/contracts/__init__.py`
- `tests/contracts/test_contract_model.py`
- `tests/contracts/test_domain.py`
- `tests/contracts/test_event_parser.py`
- `tests/contracts/test_turn_status.py`
- `tests/fixtures/events/minimal-session.v1.json`
- `tests/fixtures/events/invalid-unknown-field.v1.json`
- `tests/fixtures/events/invalid-unknown-version.v1.json`
- `tests/fixtures/events/invalid-unknown-event.v1.json`
- `tests/fixtures/events/invalid-payloads.v1.json`
- `tests/fixtures/events/turn-status-sequences.v1.json`
- `tests/fixtures/events/same-request-resend.v1.json`

**変更path:**

- `src/neontof/config.py`
- `src/neontof/app.py`
- `tests/test_config.py`
- `tests/test_repository_contracts.py`
- `tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py`

`tests/contracts/support/reference_projection.py`は作らない。期待値生成helperも作らず、production
のparser / `rebuild_projection`を直接テストする。

| path | 責務 |
|---|---|
| `docs/specs/core-domain-and-events.md` | Event wire契約、ID、Projection、Turn status、parser、version、秘密境界を固定する。 |
| `src/neontof/contracts/__init__.py` | contractの公開exportだけを行い、型の重複定義を持たない。 |
| `src/neontof/contracts/base.py` | 唯一の`ContractModel`、strict設定、immutable JSON、再検証設定を所有する。 |
| `src/neontof/contracts/ids.py` | stable ID grammar、`Visibility`、ID用adapterを所有する。 |
| `src/neontof/contracts/domain.py` | 17 Eventのpayload / envelope / subtypeと`DomainEvent`、Transcript / Telemetryの非Event型を所有する。 |
| `src/neontof/contracts/event_parser.py` | raw `str | bytes`だけを受けるversion先行parserと、秘密を保持しない`DomainEventValidationIssue` / `DomainEventValidationError`を所有する。 |
| `src/neontof/contracts/projection.py` | `FactRecord`、`Projection`、`derive_fact_id`、`rebuild_projection`と純粋reducerを所有する。 |
| `src/neontof/contracts/turn_status.py` | `project_turn_status(turn_id, events)`と遷移検証を所有する。 |
| `src/neontof/config.py` | `base.py`のcanonical `ContractModel`をre-exportする。別定義しない。 |
| `src/neontof/app.py` | canonical `contracts/base.py`を参照する既存health Applicationのregressionを保つ。 |
| `tests/contracts/*` | raw fixtureをproduction parser / reducerへ渡し、handwritten expected valueと比較する。 |
| `tests/fixtures/events/*` | 7つのsanitized versioned JSON fixture。secret / API key / raw promptを含めない。 |
| `tests/test_config.py` / `tests/test_repository_contracts.py` | config identity、app regression、production manifest、extra pathを検証する。 |
| `tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py` | 実型のproduction sinkへTranscript / Telemetryを渡すnegative mypyだけを保持する。 |

P0-03のproduction manifestは次の11相対pathに固定する。既存pathも含め、実装者はこの集合を
勝手に拡張しない。

~~~text
src/neontof/__init__.py
src/neontof/main.py
src/neontof/config.py
src/neontof/app.py
src/neontof/contracts/__init__.py
src/neontof/contracts/base.py
src/neontof/contracts/ids.py
src/neontof/contracts/domain.py
src/neontof/contracts/event_parser.py
src/neontof/contracts/projection.py
src/neontof/contracts/turn_status.py
~~~

`tests/test_repository_contracts.py`は固定globの書き漏れで済ませず、
`Path("src/neontof").rglob("*.py")`で実ファイルを列挙し、POSIX相対pathへ正規化した集合と
上の11相対pathの差分を検証する。production manifest外の`.py`、manifestにないpath、
`projection.py`以外の`FactRecord` / `Projection`定義をFAILにする。

MyWorkflowの正本
`C:\Users\KINGkawamura\Documents\MyWorkflow\projects\NeontoF\agent-guide\build-and-verify.md`
はNeontoFのscopeへ混ぜない。P0-03実測後にMyWorkflow側の別branch / 別commitで更新し、NeontoFの
commitとは分離する。

### 9.3 型とSignature

P0-03のContractModelは`src/neontof/contracts/base.py`だけを唯一の定義元とする。

~~~python
from pydantic import ConfigDict

class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
~~~

`config.py`はこの型をre-exportし、`app.py`はcanonicalな`base.py`を参照する。
`tests/test_config.py`は`config.ContractModel is base.ContractModel`と、appがcanonical baseを
参照するidentityを検証する。strict / forbid / frozen / `revalidate_instances="always"`を
config側や各subtype側で別の設定にしない。

Immutable JSONの公開型には`list` / `dict`を使わない。arrayはtuple、objectはkeyがsortedかつ
uniqueな`tuple[tuple[str, FrozenJsonValue], ...]`、scalarは`None | str | bool | strict int |
finite float`とする。`bool`は`int`として受理しない。finiteでないfloatはrejectする。入力の
aliasを保持せずにdeep copyして凍結し、nested mutationも拒否する。

~~~python
import re
from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from pydantic import BeforeValidator, Field, StrictInt, StringConstraints, TypeAdapter

CampaignId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^campaign:[a-z0-9]+(?:-[a-z0-9]+)*$")]
SessionId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^session:[a-z0-9]+(?:-[a-z0-9]+)*$")]
SceneId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^scene:[a-z0-9]+(?:-[a-z0-9]+)*$")]
TurnId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^turn:[a-z0-9]+(?:-[a-z0-9]+)*$")]
TurnRequestId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^turn-request:[a-z0-9]+(?:-[a-z0-9]+)*$")]
EventId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^event:[a-z0-9]+(?:-[a-z0-9]+)*$")]
FactId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^fact:[0-9a-f]{64}:(0|[1-9][0-9]*)$")]
NpcId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^npc:[a-z0-9]+(?:-[a-z0-9]+)*$")]
ActionId: TypeAlias = Annotated[str, StringConstraints(strict=True, pattern=r"^action:[a-z0-9]+(?:-[a-z0-9]+)*$")]
LowercaseSha256: TypeAlias = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Visibility: TypeAlias = Literal["gm_only", "player_visible"] | NpcId
VISIBILITY_ADAPTER = TypeAdapter(Visibility)
FactKind: TypeAlias = Literal["fact", "ruling", "agreement", "plan", "promise"]
FactHolder: TypeAlias = Literal["world", "player_character", "rumor"] | NpcId
SceneEndReason: TypeAlias = Literal["completed", "aborted", "table_correction"]
SessionEndReason: TypeAlias = Literal["completed", "aborted", "table_correction"]

def validate_occurred_at(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None:
        raise ValueError("occurred_at must be an ASCII UTC timestamp")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value

OccurredAt: TypeAlias = Annotated[str, BeforeValidator(validate_occurred_at)]
~~~

EntityId、FactSubjectId、CharacterId、LocationId、ItemId、ClockId、ResourceId、ActionId、
ScenarioId、SecretId、ClueId、InvariantId、EndConditionId、TranscriptId、TelemetryId、
ModelCallIdもkind:slug grammarで個別に定義する。Event typeは次の17種を固定し、
`TurnStarted`を追加しない。

`CampaignCreated`、`SessionStarted`、`SceneStarted`、`SceneEnded`、`PlayerInputAccepted`、
`DiceRolled`、`ResourceChanged`、`CharacterMoved`、`ClockAdvanced`、`FactAsserted`、
`FactSuperseded`、`TurnAwaitingPlayer`、`TurnResumed`、`TurnAborted`、`TurnCommitted`、
`TurnReverted`、`SessionEnded`。

#### Event v1 wire契約

全Eventは次のtop-level fieldを持つ。fieldを省略せず、nullableなfieldも必ず明示的な`null`を
送る。`event_version`はv1だけを受理し、subtypeの`type`をdiscriminatorにする。

| field | type / invariant |
|---|---|
| `type` | 上記17種のliteral。v1 adapterのdiscriminator。 |
| `event_id` | `EventId`。Event列全体でunique。 |
| `event_version` | strict intのliteral `1`。未知versionはreject。 |
| `campaign_id` | `CampaignId`。全Eventでrequired。 |
| `session_id` | `SessionId | None`。context表に従いrequiredまたは明示的`null`。 |
| `scene_id` | `SceneId | None`。context表に従いrequiredまたは明示的`null`。 |
| `turn_id` | `TurnId | None`。context表に従いrequiredまたは明示的`null`。 |
| `sequence` | strict int。campaign-localで1開始、欠落なしの連番。同一campaign内で一意。 |
| `occurred_at` | `OccurredAt`。ASCIIの正確な`YYYY-MM-DDTHH:MM:SSZ`と実在する日時だけ。offset、fraction、local time、lowercase `z`を受理しない。 |
| `origin` | 一般Eventは`in_world | table_correction`だけ。`TurnReverted`は`Literal["table_correction"]`だけで、`system`は追加しない。 |
| `visibility` | `Visibility`。Event単位の可視範囲。 |
| `payload` | Event subtypeごとのstrict ContractModel。raw input、Narrative、Transcript、Telemetry、API keyを入れない。 |

`sequence`の連番と`event_id` uniquenessはparse後のcanonical sequence validationで検証する。
複数Eventの並びは入力sequence順を使い、`occurred_at`でsortしない。DST foldなどの`fold`を
`occurred_at`のsortで解決しない。

| Event type | `session_id / scene_id / turn_id` context |
|---|---|
| `CampaignCreated` | `null / null / null` |
| `SessionStarted` | `required / null / null` |
| `SceneStarted` / `SceneEnded` | `required / required / null` |
| `PlayerInputAccepted` / `DiceRolled` / `ResourceChanged` / `CharacterMoved` / `ClockAdvanced` / `TurnAwaitingPlayer` / `TurnResumed` / `TurnAborted` / `TurnCommitted` | `required / required / required` |
| `FactAsserted` / `FactSuperseded` | `required / nullable / nullable` |
| `TurnReverted` | `required / nullable / nullable` |
| `SessionEnded` | `required / null / null` |

#### 17 payloadのfield / type / effect

| Event type | payload field / type | Projectionへのeffect |
|---|---|---|
| `CampaignCreated` | `name: strict non-empty str` | Campaign名を設定する。 |
| `SessionStarted` | `scenario_id: ScenarioId | None`、`title: strict non-empty str` | Sessionとscenario/titleを設定する。 |
| `SceneStarted` | `label: strict non-empty str` | 現在Sceneとlabelを開始し、`scene_end_reason`を`None`へ戻す。 |
| `SceneEnded` | `reason: SceneEndReason` | 現在Sceneを終了し、`scene_end_reason`を記録する。 |
| `PlayerInputAccepted` | `turn_request_id: TurnRequestId`、`input_digest: LowercaseSha256` | Turnのcanonical inputを一度だけ受理する。digest以外のraw inputは保持しない。 |
| `DiceRolled` | `campaign_seed: LowercaseSha256`、`action_id: ActionId`、`roll_index: strict non-negative int`、`derived_seed: LowercaseSha256`、`formula: strict non-empty str`、`result: strict int` | `derived_seed = H(campaign_seed, turn_id, action_id, roll_index)`の導出材料・seed・式・結果を監査可能なEventとして記録する。 |
| `ResourceChanged` | `resource_id: ResourceId`、`entity_id: EntityId`、`delta: strict int` | 対象Entityのresource値へdeltaを適用する。 |
| `CharacterMoved` | `character_id: CharacterId`、`from_location_id: LocationId | None`、`to_location_id: LocationId` | locationの前値と新値を検証して適用する。 |
| `ClockAdvanced` | `clock_id: ClockId`、`delta: positive strict int` | clockをdeltaだけ進める。 |
| `FactAsserted` | `kind: Literal["fact", "ruling", "agreement", "plan", "promise"]`、`holder: Literal["world", "player_character", "rumor"] | NpcId`、`subject_id: EntityId | None`、`predicate: strict non-empty str`、`value: FrozenJsonValue` | Event IDとordinalからFactを追加する。 |
| `FactSuperseded` | `target_fact_id: FactId` | target Factのstatusをsupersededにする。 |
| `TurnAwaitingPlayer` | `turn_request_id: TurnRequestId` | Turn statusをawaiting_playerへ進める。 |
| `TurnResumed` | `turn_request_id: TurnRequestId` | Turn statusをrunningへ戻す。 |
| `TurnAborted` | `turn_request_id: TurnRequestId`、`reason: Literal["failed", "cancelled", "table_correction"]` | Turn statusをabortedへ終端化する。 |
| `TurnCommitted` | `turn_request_id: TurnRequestId` | Turn statusをcommittedへ終端化する。 |
| `TurnReverted` | `target_turn_id: TurnId` | target Turnのstate / fact effectをProjectionから除外し、`reverted_turn_ids`へ表示する。statusは変えない。 |
| `SessionEnded` | `reason: strict SessionEndReason` | `session_id`をclearせず、`session_end_reason`へreasonを設定する。 |

`EmptyPayload`は作らない。raw input、LLM Narrative、Transcript、Telemetry、API key、prompt、
secretはどのpayloadにも入れない。`DiceRolled`は上表の6 fieldをstrictに持ち、extra fieldを受理しない。
`seed = H(campaign_seed, turn_id, action_id, roll_index)`を導出して`derived_seed`へ記録し、
fixtureではcampaign seed、envelopeのturn ID、action ID、roll index、derived seed、formula、resultの
全てを検証する。API keyとraw narrativeはfixtureにもログにも入れない。
`session_end_reason`はSessionEnded専用であり、SceneEnded / SceneStartedが管理する
`scene_end_reason`と混同しない。

Dice seedのsignatureは次だけに固定する。

~~~python
def derive_dice_seed(
    campaign_seed: LowercaseSha256,
    turn_id: TurnId,
    action_id: ActionId,
    roll_index: StrictInt,
) -> LowercaseSha256: ...
~~~

#### Fact ID導出

`derive_fact_id(event_id: EventId, ordinal: int) -> FactId`は次で固定する。

- grammarは`^fact:[0-9a-f]{64}:(0|[1-9][0-9]*)$`。
- preimageは`b"neontof:fact-id:v1\0" + event_id ASCII + b"\0" + decimal ordinal`とする。
- SHA-256 digestのlowercase hexを使い、`fact:{digest}:{ordinal}`を返す。
- `ordinal`はstrictな`int`、0-based、0以上とし、`bool`はrejectする。

固定vectorは次の通り。実装はこの値をテストへそのまま記録する。

| `event_id / ordinal` | expected `FactId` |
|---|---|
| `event:alpha / 0` | `fact:bd64e06f407fa7ae48f0dd712f0817622f6fab8b9ea11905979745c1426b2ef4:0` |
| `event:alpha / 1` | `fact:977fdf29ed9b0faeaf966c4ac373e2e209c939d32b4329674b922d21680de4e2:1` |
| `event:z9 / 42` | `fact:7d9055cf0f3053fabcf237138adc2ec54a67353e2e9b953be2239c3caf050b95:42` |

#### ParserとDomainEventValidationError

public signatureは次だけにする。P0ではdecoded `Mapping`をpublicに受理しない。

~~~python
def parse_domain_event(raw: str | bytes) -> DomainEvent: ...
def parse_domain_event_sequence(raw: str | bytes) -> tuple[DomainEvent, ...]: ...
def derive_fact_id(event_id: EventId, ordinal: int) -> FactId: ...
def rebuild_projection(events: Sequence[DomainEvent]) -> Projection: ...
def project_turn_status(turn_id: TurnId, events: Sequence[DomainEvent]) -> TurnStatus: ...
~~~

`parse_domain_event`はUTF-8 JSON object、`parse_domain_event_sequence`はUTF-8 JSON arrayだけを
rawとして受理する。parser内部のprivate adapterは次の3つだけを持ち、全てraw JSON境界から
`TypeAdapter.validate_json(raw, strict=True)`を呼ぶ。

~~~python
_RAW_EVENT_ADAPTER = TypeAdapter(...)
_DOMAIN_EVENT_V1_ADAPTER = TypeAdapter(...)
_SEQUENCE_JSON_ADAPTER = TypeAdapter(...)
~~~

version probeは`_RAW_EVENT_ADAPTER.validate_json(raw, strict=True)`、単体v1の検証は
`_DOMAIN_EVENT_V1_ADAPTER.validate_json(raw, strict=True)`、sequenceの配列検証は
`_SEQUENCE_JSON_ADAPTER.validate_json(raw, strict=True)`で行う。sequence要素はdecoded objectを
`validate_python`へ渡さず、UTF-8 JSON bytesへ再シリアライズして`parse_domain_event`へ渡す。
version probe、単体v1、sequence要素の全てをraw JSON境界から検証し、3 adapterはprivateで
public exportにしない。JSON decode済みの`Mapping`、任意object、`Sequence[object]`をpublic parser
signatureへ戻さない。public parser内部のcanonical経路ではdecoded `Mapping`への
`validate_python`も使わない。

`DomainEventValidationIssue`は`path`、`code`、`message`だけを持つfrozen ContractModelとする。許可する
codeは`schema`、`unknown_field`、`unknown_event`、`unknown_version`、`invalid_id`、
`invalid_sequence`、`invalid_payload`である。raw input、URL、ctx、repr、secret、cause、
contextはissueへ保存しない。Pydantic errorを変換するときも
`errors(include_input=False, include_url=False, include_context=False)`相当で取り出す。
JSON、Pydantic、sequenceのvalidation failureは`DomainEventValidationError(ValueError)`だけを
raiseする。signatureは次の通りで、`issues`だけをread-onlyで公開し、他のcustom instance attributeを
持たせない。

~~~python
class DomainEventValidationError(ValueError):
    def __init__(self, issues: tuple[DomainEventValidationIssue, ...]) -> None: ...

    @property
    def issues(self) -> tuple[DomainEventValidationIssue, ...]: ...
~~~

wrong Python typeはrawのreprを含まない固定`TypeError("raw must be str or bytes")`だけをraiseする。
Pydantic errorはcatch中に`errors(include_input=False, include_url=False, include_context=False)`相当の
sanitized issueへ抽出し、catchを抜けてから`DomainEventValidationError(issues) from None`としてraiseする。
元errorをcause / contextへ保持しない。sentinel testは入力、`str`、`repr`、`args`、`__dict__`、
`__cause__`、`__context__`、`.issues`、通常log、fixtureの全観測面にraw input、`input_value`、URL、
ctx、secret sentinelが残らないことと、このraise規則を確認する。

#### Projection concrete fields

`projection.py`が次のconcrete modelとreducerを所有する。公開collectionはimmutable tuple /
frozensetだけで、resource / location / clockはstable ID順、factsはfact ID順、
`audit_event_ids`は入力sequence順にcanonicalizeする。

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

`rebuild_projection`はglobalな単一campaignの全canonical Event列を、sequence、event ID、wire invariant
を先に検証する。各`TurnReverted`について、payloadのtargetがそのEventより前に一度だけ
`TurnCommitted`されたTurnであり、同一targetへの`TurnReverted`も一度だけであることをfail-closedに
検証する。検証に失敗したらProjectionを返さない。その後、対象Turnのstate / fact effectを適用せず、
`TurnReverted`自身を含む全監査Eventを`audit_event_ids`へ残す。input Eventを削除・sort・
`occurred_at`順へ並べ替えない。

#### Turn status遷移

`project_turn_status(turn_id, events)`の`events`は、事前にfilterされた列ではなく、単一campaignの
全canonical Event列である。まず全列をcampaign ID、sequenceの1開始連番、event ID uniqueness、
Event envelope、payload、origin、同一campaignのwire invariantまで検証する。その全検証後にだけ
`event.turn_id == turn_id`の対象Eventを選択する。別turnの正当なEventはrejectせず無視する。
`turn_id=null`のCampaign / Session / Scene / Fact Eventも無視し、`TurnReverted`だけはpayloadの
`target_turn_id`が対象ならstatusを変更せず扱う。対象Eventが一つも無ければ`pending`を返す。

対象Turnの`PlayerInputAccepted`で設定した`turn_request_id`を基準に、対象Turnの全Eventで同一
request IDを要求する。同じturn requestの遷移は次だけを許可する。

| current / Event | next status |
|---|---|
| no target Event / initial | `pending` |
| initial / `PlayerInputAccepted` | `pending` |
| `pending` / `TurnResumed` | `running` |
| `running` / `TurnAwaitingPlayer` | `awaiting_player` |
| `awaiting_player` / `TurnResumed` | `running` |
| `running` or `awaiting_player` / `TurnCommitted` | `committed` |
| `pending` or `running` or `awaiting_player` / `TurnAborted` | `aborted` |
| `committed` / `TurnReverted` targeting this Turn | `committed`（status unchanged） |

terminal後の対象Event、対象Turnのrequest ID mismatch、二重`PlayerInputAccepted`、未許可遷移は
rejectする。別turnの正当なEventのrequest ID mismatchは無視する。`TurnReverted`はpayloadのtargetが
対象ならstatusを変えず、`Projection.reverted_turn_ids`で表示する。P0で許可するrevertはcanonicalな
committed Turnへの一回の`origin='table_correction'`だけで、任意revertはNon-goalである。

TranscriptEntryとTelemetryEntryは`DomainEvent` unionにも`rebuild_projection`の入力にも含めない。
sequenceはCampaign内で厳密な1開始連番、`event_id`はunique、`occurred_at`は表示用metadataであり、
ゲーム判断や順序付けへ使わない。

### 9.4 Test First、RED / Green

- [ ] `ContractModel`のstrict、extra forbid、frozen、`revalidate_instances="always"`、
  tuple / frozenset、finite float、bool/int分離、alias切断、nested mutation、revalidation
  sabotageを先に書く。`tests/test_config.py`でcanonical baseとのidentityも固定する。
- [ ] 7つのraw fixtureを全てproduction `parse_domain_event_sequence`へ渡し、decoded Mappingを
  直接渡す経路を作らない。unknown field / version / event、payload不正、sequence欠落、
  duplicate `event_id`、ID grammar違反、same-request duplicate、wrong origin、存在しない日時・
  offset・fraction・lowercase `z`の`occurred_at`をfixtureごとに検証し、wrong Python typeはraw reprを
  含まない固定`TypeError`だけを返すことを検証する。
- [ ] 17 Event typeのpayloadを最低1件ずつ、field type、strict int、nullable、effectまで検証し、
  unknown top-level / payload fieldと`TurnStarted` / `EmptyPayload`をrejectする。
- [ ] minimal fixtureのseq 6 `DiceRolled`で`campaign_seed`、envelopeの`turn_id`、`action_id`、
  `roll_index`、`derived_seed`、`formula`、`result`を全て固定し、`seed = H(campaign_seed, turn_id,
  action_id, roll_index)`の導出値とresultを同時に検証する。API keyとraw narrativeはfixtureにない。
- [ ] raw fixture → production parser → production `rebuild_projection`の順だけを使う。
  `tests/contracts/support/reference_projection.py`、reference reducer、期待値生成helperは作らない。
- [ ] 同一Event列の2回rebuildがdeep equal、sequence 1開始・欠落なし、`occurred_at`非sort、
  Fact ID vector、TurnRevertedの先行committed target / 一回性のfail-closed検証と監査Event保持、
  turn status、same-request、別turn Eventの無視、null context Eventの無視、対象Eventなしのpending、
  再起動後`awaiting_player`をtestする。
- [ ] `tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py`はproductionから実型
  `DomainEvent`、`TranscriptEntry`、`TelemetryEntry`をimportするtyped sinkへTranscript / Telemetryを
  渡す。`# type: ignore`、`assert_type`、`cast(`を置かず、negative mypyはちょうど2件の`[arg-type]`、
  それ以外のerror 0件、exit 1を記録する。
- [ ] secret redaction testで、raw input / URL / ctx / repr / cause / context / API key sentinelが
  `DomainEventValidationIssue`、`DomainEventValidationError`の`str` / `repr` / `args` / `__dict__` /
  `__cause__` / `__context__` / `.issues`、通常log、fixture、payloadへ残らないことを確認する。
- [ ] `tests/test_config.py`のconfig/app regression、`tests/test_repository_contracts.py`の
  11-path production manifestと`rglob`集合差分、P0-01bで作成済みApplicationのhealth regression
  を同じP0-03変更で壊さない。

`minimal-session.v1.json`はEvent `event:e01`〜`event:e27`をsequence 1〜27へ一つずつ持つ。
type列は次の固定順であり、別の最終sequenceや期待値へ変更しない。

~~~text
1 CampaignCreated
2 SessionStarted
3 SceneStarted
4 PlayerInputAccepted (turn:one)
5 TurnResumed (turn:one)
6 DiceRolled
7 ResourceChanged
8 CharacterMoved
9 ClockAdvanced
10 FactAsserted (turn:one)
11 TurnAwaitingPlayer
12 TurnResumed
13 TurnCommitted
14 PlayerInputAccepted (turn:two)
15 TurnResumed (turn:two)
16 ResourceChanged
17 CharacterMoved
18 ClockAdvanced
19 FactAsserted (turn:two)
20 TurnCommitted
21 FactSuperseded (table correction, target turn:one Fact)
22 SceneEnded
23 SceneStarted
24 PlayerInputAccepted (turn:three)
25 TurnAborted
26 TurnReverted (target_turn_id=turn:two, origin=table_correction)
27 SessionEnded
~~~

このfixtureのhandwritten expected Projectionは次で固定する。seq 4〜13は`turn:one`、seq 14〜20は
`turn:two`、seq 24〜25は`turn:three`である。seq 21の`FactSuperseded`は`event:e10 / 0`の
turn:one Factをsupersedeするtable correction、seq 26の`TurnReverted`は
`target_turn_id='turn:two'`かつ`origin='table_correction'`である。したがってrevert対象のturn:two
resource / location / clock / Fact effectは消えるが、seq 26を含む全監査Eventは残る。seq 22の
`SceneEnded`とseq 23の`SceneStarted`の後は`scene_end_reason=None`であり、seq 27の
`SessionEnded`は`session_end_reason='completed'`を設定する。

~~~python
Projection(
    campaign_id='campaign:alpha',
    campaign_name='NeontoF',
    session_id='session:one',
    scenario_id='scenario:minimal',
    session_title='Minimal Session',
    scene_id='scene:hall',
    scene_label='Hall',
    scene_end_reason=None,
    session_end_reason='completed',
    resources=(
        ResourceState(resource_id='resource:gold', entity_id='entity:hero', value=5),
    ),
    locations=(
        CharacterLocation(character_id='character:hero', location_id='location:gate'),
    ),
    clocks=(ClockState(clock_id='clock:session', value=2),),
    facts=(
        FactRecord(
            fact_id='fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d:0',
            event_id='event:e10',
            kind='fact',
            holder='world',
            subject_id='entity:door',
            predicate='is_open',
            value=True,
            visibility='player_visible',
            status='superseded',
        ),
    ),
    reverted_turn_ids=frozenset({'turn:two'}),
    applied_through_sequence=27,
    audit_event_ids=(
        'event:e01', 'event:e02', 'event:e03', 'event:e04', 'event:e05',
        'event:e06', 'event:e07', 'event:e08', 'event:e09', 'event:e10',
        'event:e11', 'event:e12', 'event:e13', 'event:e14', 'event:e15',
        'event:e16', 'event:e17', 'event:e18', 'event:e19', 'event:e20',
        'event:e21', 'event:e22', 'event:e23', 'event:e24', 'event:e25',
        'event:e26', 'event:e27',
    ),
)
~~~

最終ProjectionのFactはturn:oneの`event:e10 / 0`から導出した
`fact:27cd642ddc52f1783e19c77e74c0f38a6bcf4ed9e8f200232704938d155b34d:0`だけで、statusは
`superseded`である。turn:twoの`event:e19 / 0`から導出した
`fact:eb2fd634b619f44a9e029abaff4b66d4bf82f699f6ebb6fd5b988cfaa0c6700e:0`はrevertにより不在である。
期待値はfixtureから自動生成せず、testへ手書きする。

### 9.5 実行コマンドと期待結果

PowerShellの各blockは別々に実行できるよう、毎回repository rootと`.venv/Scripts/python.exe`
を解決する。各native commandの直後に`$LASTEXITCODE`を保存し、期待値以外は即座にthrowする。
現在のshellのlocationや`$neontofPython`のような前blockの変数を引き継がない。

#### focused RED

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }
$env:PYTHONPATH = Join-Path $repositoryRoot 'src'
$focusedOutput = (& $pythonExe -m pytest tests/contracts/test_contract_model.py tests/contracts/test_domain.py tests/contracts/test_event_parser.py tests/contracts/test_turn_status.py -q 2>&1 | Out-String)
$focusedRedExit = $LASTEXITCODE
"$focusedOutput"
if ($focusedRedExit -ne 1) { throw "focused RED expected exit 1, got $focusedRedExit." }
foreach ($fragment in @('SyntaxError', 'FileNotFoundError', 'No such file', 'INTERNALERROR', 'collection error', 'collected 0', 'file or directory not found')) {
    if ($focusedOutput -match [regex]::Escape($fragment)) { throw "focused RED contains forbidden failure fragment: $fragment" }
}
$allowedRedExceptionPattern = '(?i)(ModuleNotFoundError|ImportError).*(neontof\.contracts|ContractModel|DomainEvent|Projection|parse_domain_event|project_turn_status)'
$redExceptionLines = @($focusedOutput -split "`r?`n" | Where-Object { $_ -match '(?i)([A-Za-z]+Error|ImportError)' })
if ($redExceptionLines.Count -eq 0 -or ($redExceptionLines | Where-Object { $_ -notmatch $allowedRedExceptionPattern }).Count -ne 0) {
    throw "focused RED was not limited to an expected contracts module/export absence."
}
"focused RED exit $focusedRedExit"
~~~

これはrunner起動後のexpectedなcontracts module/export不在だけをRED証拠とする。実装後は同じfocused
command（同じ4 test pathと`-q`）をstdout / stderr付きで再実行し、禁止fragmentなし・exit exactly 0を
Greenとして確認する。exit 0以外、またはRED専用fragmentが残る場合はFAILとする。

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }
$env:PYTHONPATH = Join-Path $repositoryRoot 'src'
$focusedGreenOutput = (& $pythonExe -m pytest tests/contracts/test_contract_model.py tests/contracts/test_domain.py tests/contracts/test_event_parser.py tests/contracts/test_turn_status.py -q 2>&1 | Out-String)
$focusedGreenExit = $LASTEXITCODE
$focusedGreenOutput
if ($focusedGreenExit -ne 0) { throw "focused Green expected exit 0, got $focusedGreenExit." }
if ($focusedGreenOutput -match '(?i)(ModuleNotFoundError|ImportError)') { throw 'focused Green still contains a missing module/export error.' }
foreach ($fragment in @('SyntaxError', 'FileNotFoundError', 'No such file', 'INTERNALERROR', 'collection error', 'collected 0', 'file or directory not found')) {
    if ($focusedGreenOutput -match [regex]::Escape($fragment)) { throw "focused Green contains forbidden failure fragment: $fragment" }
}
~~~

#### compileall / ruff / normal mypy / all pytest

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }
$env:PYTHONPATH = Join-Path $repositoryRoot 'src'

& $pythonExe -m compileall -q src
$compileallExit = $LASTEXITCODE
if ($compileallExit -ne 0) { throw "compileall failed with exit $compileallExit." }

& $pythonExe -m ruff format --check src tests
$ruffFormatExit = $LASTEXITCODE
if ($ruffFormatExit -ne 0) { throw "ruff format check failed with exit $ruffFormatExit." }

& $pythonExe -m ruff check src tests
$ruffCheckExit = $LASTEXITCODE
if ($ruffCheckExit -ne 0) { throw "ruff check failed with exit $ruffCheckExit." }

& $pythonExe -m mypy --strict src tests --exclude tests/typecheck_fixtures
$mypyExit = $LASTEXITCODE
if ($mypyExit -ne 0) { throw "normal mypy failed with exit $mypyExit." }

& $pythonExe -m pytest -q
$pytestExit = $LASTEXITCODE
if ($pytestExit -ne 0) { throw "all pytest failed with exit $pytestExit." }
~~~

期待値はcompileall / ruff format / ruff check / normal mypy / 全pytestが全てexit 0である。
normal mypyへnegative fixtureを混ぜない。

#### negative mypy

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }

$negativeFixture = 'tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py'
$negativeOutput = (& $pythonExe -m mypy --strict $negativeFixture 2>&1 | Out-String)
$negativeExit = $LASTEXITCODE
$negativeOutput
$negativeLines = @($negativeOutput -split "`r?`n" | Where-Object { $_ -ne '' })
$errorLines = @($negativeLines | Where-Object { $_ -match 'error:' })
$argTypeLines = @($errorLines | Where-Object { $_ -match '\[arg-type\]' })
$otherErrorLines = @($errorLines | Where-Object { $_ -notmatch '\[arg-type\]' })
if ($negativeExit -ne 1) { throw "negative mypy expected exit 1, got $negativeExit." }
if ($errorLines.Count -ne 2 -or $argTypeLines.Count -ne 2 -or $otherErrorLines.Count -ne 0) { throw "negative mypy error surface mismatch." }
foreach ($fragment in @($negativeFixture, 'TranscriptEntry', 'TelemetryEntry', 'DomainEvent')) {
    if ($negativeOutput -notmatch [regex]::Escape($fragment)) { throw "negative mypy output lacks fragment: $fragment" }
}
"negative mypy exit $negativeExit; arg-type=$($argTypeLines.Count); other-errors=$($otherErrorLines.Count)"
~~~

expected outputはstdout / stderrを捕捉したexit 1、error lines exactly 2、両方`[arg-type]`、
その他error 0、fixture filename / `TranscriptEntry` / `TelemetryEntry` / `DomainEvent`の各fragmentあり
である。fixtureには`# type: ignore`、`assert_type`、`cast(`を置かない。

#### required語検索とforbidden検索

required語はOR正規表現へまとめず、一語ずつ`rg -n -w`する。各`rg`の直後にexit codeを保存し、
required語のexit 1やtool errorはFAILとする。

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }

$requiredWords = @('Event', 'Projection', 'Transcript', 'Telemetry', 'TurnReverted', 'TurnAwaitingPlayer', 'TurnResumed', 'TurnAborted', 'awaiting_player', 'event_version', 'parse_domain_event', 'unknown_version', 'invalid_payload')
foreach ($word in $requiredWords) {
    & rg -n -w -- $word docs/specs/core-domain-and-events.md src/neontof/contracts
    $requiredExit = $LASTEXITCODE
    if ($requiredExit -ne 0) { throw "required word '$word' search failed with exit $requiredExit." }
}

$productionForbiddenPatterns = @('TurnStarted', 'EmptyPayload', 'reference_projection', 'Plugin', 'Hook', 'Profile', 'ProviderRegistry')
foreach ($pattern in $productionForbiddenPatterns) {
    & rg -n -- $pattern src/neontof
    $productionForbiddenExit = $LASTEXITCODE
    if ($productionForbiddenExit -eq 1) { continue }
    if ($productionForbiddenExit -eq 0) { throw "production forbidden hit for '$pattern'." }
    throw "production forbidden search tool failure for '$pattern' with exit $productionForbiddenExit."
}

$sourceOnlyPatterns = @('openai', 'anthropic', 'sqlite3\.connect', 'sqlite3\.Connection', 'provider_registry')
foreach ($pattern in $sourceOnlyPatterns) {
    & rg -ni -- $pattern src/neontof
    $sourceOnlyExit = $LASTEXITCODE
    if ($sourceOnlyExit -eq 1) { continue }
    if ($sourceOnlyExit -eq 0) { throw "source-only forbidden hit for '$pattern'." }
    throw "source-only forbidden search tool failure for '$pattern' with exit $sourceOnlyExit."
}

$normalBypassPatterns = @('setState', 'updateState', 'mutateState', 'saveProjection', 'model_construct\(', 'cast\(')
foreach ($pattern in $normalBypassPatterns) {
    & rg -n -- $pattern src/neontof tests
    $normalBypassExit = $LASTEXITCODE
    if ($normalBypassExit -eq 1) { continue }
    if ($normalBypassExit -eq 0) { throw "validation bypass hit for '$pattern'." }
    throw "validation bypass search tool failure for '$pattern' with exit $normalBypassExit."
}

$negativeFixture = 'tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py'
& rg -n -- '# type: ignore' $negativeFixture
$negativeIgnoreExit = $LASTEXITCODE
if ($negativeIgnoreExit -eq 0) { throw 'negative fixture contains # type: ignore.' }
if ($negativeIgnoreExit -ne 1) { throw "negative fixture # type: ignore search failed with exit $negativeIgnoreExit." }
& rg -n -- 'assert_type' $negativeFixture
$negativeAssertTypeExit = $LASTEXITCODE
if ($negativeAssertTypeExit -eq 0) { throw 'negative fixture contains assert_type.' }
if ($negativeAssertTypeExit -ne 1) { throw "negative fixture assert_type search failed with exit $negativeAssertTypeExit." }
& rg -n -- 'cast\(' $negativeFixture
$negativeCastExit = $LASTEXITCODE
if ($negativeCastExit -eq 0) { throw 'negative fixture contains cast(.' }
if ($negativeCastExit -ne 1) { throw "negative fixture cast( search failed with exit $negativeCastExit." }
~~~

forbidden検索は実装内容とテスト内容を分離する。`TurnStarted`、`EmptyPayload`、
`reference_projection`、`Plugin`、`Hook`、`Profile`、`ProviderRegistry`はproduction sourceの
`src/neontof`だけをscanし、testsがreject caseとして語を含むことを許す。一方、
`setState`、`updateState`、`mutateState`、`saveProjection`、`model_construct`、`cast`は
`src/neontof`と通常testsをscanし、negative fixtureをbypass scan全体から除外しない。
negative fixture自身の`# type: ignore`、`assert_type`、`cast(`は別々の`rg`で各exit 1を要求する。
source-only patternには`openai`、`anthropic`、`sqlite3.connect`、`sqlite3.Connection`、
`provider_registry`を含める。全`rg`でexit 1だけをzero-hit成功、exit 0をhitによるFAIL、exit 2以上を
tool failureとして扱う。

#### rglob source scan

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$pythonExe = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.venv/Scripts/python.exe'))
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "P0-03 .venv python was not found." }

$rglobOutput = & $pythonExe -c "from pathlib import Path; expected=['src/neontof/__init__.py','src/neontof/main.py','src/neontof/config.py','src/neontof/app.py','src/neontof/contracts/__init__.py','src/neontof/contracts/base.py','src/neontof/contracts/ids.py','src/neontof/contracts/domain.py','src/neontof/contracts/event_parser.py','src/neontof/contracts/projection.py','src/neontof/contracts/turn_status.py']; actual=sorted(path.as_posix() for path in Path('src/neontof').rglob('*.py')); print('actual=', actual); raise SystemExit(0 if actual == sorted(expected) else 1)"
$rglobExit = $LASTEXITCODE
$rglobOutput
if ($rglobExit -ne 0) { throw "rglob production manifest mismatch with exit $rglobExit." }
~~~

`rglob`のactual集合と11相対path manifestが完全一致し、extra source / missing sourceが0件で
あることを確認する。

#### P0-01bで確定した最終Gateの再実行

P0-03の最終Gateでは、P0-01bで確定したlock / install / compileall / ruff / mypy / pytest /
network / API key / lifecycle / workers=2 / source scanを再実行する。最初に
`docs/agent-guide/build-and-verify.md`のfresh venv / lock / install blockを、Python 3.14.3、
`requirements-dev.in`、`requirements.lock.txt`、`--generate-hashes`、`pip install --require-hashes`
を含めて一字一句変更せずに実行する。その実行は既存repository `.venv`だけを証拠にせず、uniqueな
TEMPまたはfresh isolated venvを作る。既存`.venv`はfocused local checkにのみ使え、fresh Gateの代用に
しない。`pip-compile exit 0`、machine-local path 0、openai 0、fresh install / pip check /
compileall / ruff format / ruff check / mypy / pytestのexit 0、cleanup後の存在Falseを実出力で記録する。

~~~powershell
$repositoryRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
$repositoryRootExit = $LASTEXITCODE
if ($repositoryRootExit -ne 0 -or [string]::IsNullOrWhiteSpace($repositoryRoot)) { throw "repository root resolution failed." }
$repositoryRoot = [System.IO.Path]::GetFullPath($repositoryRoot)
Set-Location -LiteralPath $repositoryRoot
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$freshRoot = [System.IO.Path]::GetFullPath((Join-Path $tempRoot ('neontof-p0-03-final-' + [guid]::NewGuid().ToString('N'))))
$tempPrefix = $tempRoot
if (-not $tempPrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar)) { $tempPrefix += [System.IO.Path]::DirectorySeparatorChar }
if ($freshRoot.Equals($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $freshRoot.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to use a fresh gate path outside TEMP." }
$freshVenv = [System.IO.Path]::GetFullPath((Join-Path $freshRoot 'venv'))
$pythonPathWasPresent = Test-Path -LiteralPath 'Env:PYTHONPATH'
$pythonPathValue = if ($pythonPathWasPresent) { $env:PYTHONPATH } else { $null }
$env:PYTHONPATH = Join-Path $repositoryRoot 'src'

$openAiKeyWasPresent = Test-Path -LiteralPath 'Env:OPENAI_API_KEY'
$openAiKeyValue = if ($openAiKeyWasPresent) { $env:OPENAI_API_KEY } else { $null }
$anthropicKeyWasPresent = Test-Path -LiteralPath 'Env:ANTHROPIC_API_KEY'
$anthropicKeyValue = if ($anthropicKeyWasPresent) { $env:ANTHROPIC_API_KEY } else { $null }
try {
    Remove-Item -LiteralPath 'Env:OPENAI_API_KEY' -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath 'Env:ANTHROPIC_API_KEY' -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath 'Env:OPENAI_API_KEY') -or (Test-Path -LiteralPath 'Env:ANTHROPIC_API_KEY')) { throw "API key variable remained in the test process." }

    New-Item -ItemType Directory -LiteralPath $freshRoot -Force | Out-Null
    py -3.14 --version
    $pythonVersionExit = $LASTEXITCODE
    if ($pythonVersionExit -ne 0) { throw "Python version check failed with exit $pythonVersionExit." }
    py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
    $pythonAssertExit = $LASTEXITCODE
    if ($pythonAssertExit -ne 0) { throw "Python 3.14.3 assertion failed with exit $pythonAssertExit." }
    & py -3.14 -m venv $freshVenv
    $venvCreateExit = $LASTEXITCODE
    if ($venvCreateExit -ne 0) { throw "fresh venv creation failed with exit $venvCreateExit." }
    $pythonExe = Join-Path $freshVenv 'Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "fresh venv python was not found." }
    & $pythonExe -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
    $freshPythonAssertExit = $LASTEXITCODE
    if ($freshPythonAssertExit -ne 0) { throw "fresh venv Python assertion failed with exit $freshPythonAssertExit." }
    & $pythonExe -m pip install --require-hashes -r requirements.lock.txt
    $installExit = $LASTEXITCODE
    if ($installExit -ne 0) { throw "locked install failed with exit $installExit." }
    & $pythonExe -m pip check
    $pipCheckExit = $LASTEXITCODE
    if ($pipCheckExit -ne 0) { throw "pip check failed with exit $pipCheckExit." }
    $openAiOutput = (& $pythonExe -c "import importlib.util; print('openai absent' if importlib.util.find_spec('openai') is None else 'openai present')" | Out-String).Trim()
    $openAiExit = $LASTEXITCODE
    if ($openAiExit -ne 0 -or $openAiOutput -ne 'openai absent') { throw "fresh environment openai absence check failed with exit $openAiExit." }
    $openAiOutput
    & $pythonExe -m compileall -q src
    $compileallExit = $LASTEXITCODE
    if ($compileallExit -ne 0) { throw "compileall failed with exit $compileallExit." }
    & $pythonExe -m ruff format --check src tests
    $ruffFormatExit = $LASTEXITCODE
    if ($ruffFormatExit -ne 0) { throw "ruff format check failed with exit $ruffFormatExit." }
    & $pythonExe -m ruff check src tests
    $ruffCheckExit = $LASTEXITCODE
    if ($ruffCheckExit -ne 0) { throw "ruff check failed with exit $ruffCheckExit." }
    & $pythonExe -m mypy --strict src tests --exclude tests/typecheck_fixtures
    $mypyExit = $LASTEXITCODE
    if ($mypyExit -ne 0) { throw "normal mypy failed with exit $mypyExit." }
    & $pythonExe -m pytest -q
    $pytestExit = $LASTEXITCODE
    if ($pytestExit -ne 0) { throw "all pytest failed with exit $pytestExit." }
    & $pythonExe -m pytest tests/test_no_external_network.py -q
    $networkExit = $LASTEXITCODE
    if ($networkExit -ne 0) { throw "network-blocking test failed with exit $networkExit." }
    & $pythonExe -m pytest tests/test_no_external_network.py --setup-plan -q
    $networkSetupExit = $LASTEXITCODE
    if ($networkSetupExit -ne 0) { throw "network setup-plan failed with exit $networkSetupExit." }
    & $pythonExe tests/acceptance/entrypoint_lifecycle.py
    $lifecycleExit = $LASTEXITCODE
    if ($lifecycleExit -ne 0) { throw "entrypoint lifecycle failed with exit $lifecycleExit." }
    $workersOutput = (& $pythonExe -m neontof.main --workers 2 2>&1 | Out-String)
    $workersExit = $LASTEXITCODE
    $workersOutput
    if ($workersExit -ne 2 -or $workersOutput -notmatch 'NEONTOF_WORKERS must be 1') { throw "workers=2 expected exit 2 and exact message, got $workersExit." }
    "install=$installExit; pip-check=$pipCheckExit; compileall=$compileallExit; ruff-format=$ruffFormatExit; ruff=$ruffCheckExit; mypy=$mypyExit; pytest=$pytestExit; network=$networkExit; network-setup=$networkSetupExit; lifecycle=$lifecycleExit; workers=2=$workersExit"
} finally {
    if ($openAiKeyWasPresent) { $env:OPENAI_API_KEY = $openAiKeyValue } else { Remove-Item -LiteralPath 'Env:OPENAI_API_KEY' -ErrorAction SilentlyContinue }
    if ($anthropicKeyWasPresent) { $env:ANTHROPIC_API_KEY = $anthropicKeyValue } else { Remove-Item -LiteralPath 'Env:ANTHROPIC_API_KEY' -ErrorAction SilentlyContinue }
    if ($pythonPathWasPresent) { $env:PYTHONPATH = $pythonPathValue } else { Remove-Item -LiteralPath 'Env:PYTHONPATH' -ErrorAction SilentlyContinue }
    if ([System.IO.Directory]::Exists($freshRoot)) { [System.IO.Directory]::Delete($freshRoot, $true) }
    "fresh gate cleanup=$([System.IO.Directory]::Exists($freshRoot))"
}
if ((Test-Path -LiteralPath 'Env:OPENAI_API_KEY') -ne $openAiKeyWasPresent) { throw "OPENAI_API_KEY presence was not restored." }
if ($openAiKeyWasPresent -and $env:OPENAI_API_KEY -ne $openAiKeyValue) { throw "OPENAI_API_KEY value was not restored." }
if ((Test-Path -LiteralPath 'Env:ANTHROPIC_API_KEY') -ne $anthropicKeyWasPresent) { throw "ANTHROPIC_API_KEY presence was not restored." }
if ($anthropicKeyWasPresent -and $env:ANTHROPIC_API_KEY -ne $anthropicKeyValue) { throw "ANTHROPIC_API_KEY value was not restored." }
if ((Test-Path -LiteralPath 'Env:PYTHONPATH') -ne $pythonPathWasPresent) { throw "PYTHONPATH presence was not restored." }
if ($pythonPathWasPresent -and $env:PYTHONPATH -ne $pythonPathValue) { throw "PYTHONPATH value was not restored." }
~~~

API keyの元のpresence / valueは保存・復元するが、値は出力しない。network guard、lifecycle、
workers probeはfresh Gateでも維持する。workers probeはstdout / stderrを捕捉し、exit exactly 2かつ
`NEONTOF_WORKERS must be 1`を含むことを要求する。source scanは上の
forbidden検索とrglob scanを最終Gateでも同じroot / python解決で再実行し、openai / forbidden
API / sqlite connection / network / validation bypass / manifest外sourceを0件にする。
P0-01bで確定した期待出力は`No broken requirements found.`、network test成功、
`entrypoint_lifecycle=graceful_exit_0_rebind_health_200`、`workers=2 exit 2`であり、未確認の
remote CIは成功と扱わずpendingにする。

P0-03実測後、MyWorkflow正本
`C:\Users\KINGkawamura\Documents\MyWorkflow\projects\NeontoF\agent-guide\build-and-verify.md`
を別branch / 別commitで更新する。そこへactual commandを反映した後、MyWorkflow rootで
次の絶対pathだけでapply、report、hash、mirrorを実行する。

~~~powershell
$myWorkflowRoot = 'C:\Users\KINGkawamura\Documents\MyWorkflow'
$myWorkflowDeploy = 'C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs'
$sourceNeontoFRoot = 'C:\Users\KINGkawamura\Documents\MyWorkflow\projects\NeontoF'
$deployedNeontoFRoot = 'C:\Users\KINGkawamura\Documents\NeontoF'
if (-not (Test-Path -LiteralPath $myWorkflowRoot -PathType Container)) { throw 'MyWorkflow source root was not found.' }
if (-not (Test-Path -LiteralPath $myWorkflowDeploy -PathType Leaf)) { throw 'MyWorkflow deploy script was not found.' }
if (-not (Test-Path -LiteralPath $sourceNeontoFRoot -PathType Container)) { throw 'NeontoF source root was not found.' }
if (-not (Test-Path -LiteralPath $deployedNeontoFRoot -PathType Container)) { throw 'NeontoF deployed root was not found.' }

node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs --apply NeontoF
$applyExit = $LASTEXITCODE
if ($applyExit -ne 0) { throw "MyWorkflow apply failed with exit $applyExit." }
node C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs NeontoF
$reportExit = $LASTEXITCODE
if ($reportExit -ne 0) { throw "MyWorkflow deploy report failed with exit $reportExit." }

$sourceAgents = 'C:\Users\KINGkawamura\Documents\MyWorkflow\projects\NeontoF\AGENTS.md'
$sourceClaude = 'C:\Users\KINGkawamura\Documents\MyWorkflow\projects\NeontoF\CLAUDE.md'
$deployedAgents = 'C:\Users\KINGkawamura\Documents\NeontoF\AGENTS.md'
$deployedClaude = 'C:\Users\KINGkawamura\Documents\NeontoF\CLAUDE.md'
foreach ($path in @($sourceAgents, $sourceClaude, $deployedAgents, $deployedClaude)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Mirror file was not found: $path" }
}
$sourceAgentsHash = (Get-FileHash -LiteralPath $sourceAgents -Algorithm SHA256).Hash
$sourceAgentsHashExit = 0
$sourceClaudeHash = (Get-FileHash -LiteralPath $sourceClaude -Algorithm SHA256).Hash
$sourceClaudeHashExit = 0
$deployedAgentsHash = (Get-FileHash -LiteralPath $deployedAgents -Algorithm SHA256).Hash
$deployedAgentsHashExit = 0
$deployedClaudeHash = (Get-FileHash -LiteralPath $deployedClaude -Algorithm SHA256).Hash
$deployedClaudeHashExit = 0
if ($sourceAgentsHash -ne $deployedAgentsHash -or $sourceClaudeHash -ne $deployedClaudeHash) { throw 'source/deployed AGENTS or CLAUDE hash mismatch.' }

$sourceMirror = Compare-Object -ReferenceObject (Get-Content -LiteralPath $sourceAgents) -DifferenceObject (Get-Content -LiteralPath $sourceClaude)
$sourceMirrorExit = if ($null -eq $sourceMirror) { 0 } else { 1 }
if ($sourceMirrorExit -ne 0) { throw 'source AGENTS.md / CLAUDE.md mirror mismatch.' }
$deployedMirror = Compare-Object -ReferenceObject (Get-Content -LiteralPath $deployedAgents) -DifferenceObject (Get-Content -LiteralPath $deployedClaude)
$deployedMirrorExit = if ($null -eq $deployedMirror) { 0 } else { 1 }
if ($deployedMirrorExit -ne 0) { throw 'deployed AGENTS.md / CLAUDE.md mirror mismatch.' }
$sourceToDeployedAgents = Compare-Object -ReferenceObject (Get-Content -LiteralPath $sourceAgents) -DifferenceObject (Get-Content -LiteralPath $deployedAgents)
$sourceToDeployedAgentsExit = if ($null -eq $sourceToDeployedAgents) { 0 } else { 1 }
if ($sourceToDeployedAgentsExit -ne 0) { throw 'source/deployed AGENTS.md mismatch.' }
$sourceToDeployedClaude = Compare-Object -ReferenceObject (Get-Content -LiteralPath $sourceClaude) -DifferenceObject (Get-Content -LiteralPath $deployedClaude)
$sourceToDeployedClaudeExit = if ($null -eq $sourceToDeployedClaude) { 0 } else { 1 }
if ($sourceToDeployedClaudeExit -ne 0) { throw 'source/deployed CLAUDE.md mismatch.' }
"apply=$applyExit; report=$reportExit; source-agents-hash=$sourceAgentsHashExit; source-claude-hash=$sourceClaudeHashExit; deployed-agents-hash=$deployedAgentsHashExit; deployed-claude-hash=$deployedClaudeHashExit; source-mirror=$sourceMirrorExit; deployed-mirror=$deployedMirrorExit; source-to-deployed-agents=$sourceToDeployedAgentsExit; source-to-deployed-claude=$sourceToDeployedClaudeExit"
~~~

MyWorkflow source rootは`C:\Users\KINGkawamura\Documents\MyWorkflow`、scriptは
`C:\Users\KINGkawamura\Documents\MyWorkflow\deploy.mjs`に固定し、cwdに依存する相対script指定、
相対`AGENTS.md` / `CLAUDE.md`比較、`--dry-run`形式は使わない。
この外部pathの更新・deploy・hash・mirror確認はNeontoFの変更pathやcommitへ含めない。

### 9.6 Commit boundary、Gate証拠、rollback

P0-03の実装は次の3 logical commitだけに分ける。各commitのscope外pathを混ぜない。

1. `test: Core Domain契約のREDを固定する`
   - `tests/fixtures/events/minimal-session.v1.json`
   - `tests/fixtures/events/invalid-unknown-field.v1.json`
   - `tests/fixtures/events/invalid-unknown-version.v1.json`
   - `tests/fixtures/events/invalid-unknown-event.v1.json`
   - `tests/fixtures/events/invalid-payloads.v1.json`
   - `tests/fixtures/events/turn-status-sequences.v1.json`
   - `tests/fixtures/events/same-request-resend.v1.json`
   - `tests/contracts/__init__.py`
   - `tests/contracts/test_contract_model.py`
   - `tests/contracts/test_domain.py`
   - `tests/contracts/test_event_parser.py`
   - `tests/contracts/test_turn_status.py`
   - `tests/test_config.py`
   - `tests/test_repository_contracts.py`
   - `tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py`
   これはtests/fixtures、contracts、config、manifest、negativeのREDだけを含む。
2. `feat: Core DomainとProjectionの最小実装を追加する`
   - `src/neontof/contracts/__init__.py`
   - `src/neontof/contracts/base.py`
   - `src/neontof/contracts/ids.py`
   - `src/neontof/contracts/domain.py`
   - `src/neontof/contracts/event_parser.py`
   - `src/neontof/contracts/projection.py`
   - `src/neontof/contracts/turn_status.py`
   - `src/neontof/config.py`
   - `src/neontof/app.py`
   11-path production manifestのうちP0-03で新規・変更するproduction pathだけを含む。
3. `docs: Core DomainとEvent仕様を確定する`
   - `docs/specs/core-domain-and-events.md`だけを含む。

この計画ファイルの更新は上のP0-03実装3 commitへ含めず、作業役の許可pathである
`docs/plans/phase-00-foundation.md`の別の計画更新として扱う。MyWorkflow guideの更新も別repoの
別branch / 別commitであり、上の3 commitへ含めない。

P0-03 integrated diffの`check-scope`は、上の3 commitが全て着地し、レビュー済みdiffを統合した
後に、オーケストレーターが全着地diffへ1回だけ実行する。各子commitで重複実行しない。

Gate証拠は7 raw fixture、17 payload、DomainEventValidationIssue / DomainEventValidationErrorのredaction、Projection handwritten
expected（最終sequence 27）、turn status、Fact ID vector、ContractModel sabotage、config/app
identity、11-path rglob manifest、normal mypy 0、negative mypy exit 1 / `[arg-type]` 2 / 他error
0、error lines exactly 2、fixture filename / `TranscriptEntry` / `TelemetryEntry` / `DomainEvent` fragment、
required語、forbidden検索0件、P0-01b最終Gate再実行の実出力とする。リスクは高い。
後続着手前ならこの3 commitを逆順revertし、永続Eventがないためdata migrationは作らない。

---

## 10. P0-04: Semantic Result Specification

### 10.1 Goal、決定境界、Non-goal

**Goal:** LLM自由文を状態更新入力にしない出力契約を、Pydantic Schema、Authority表、
Evidence validation、fixture、HTTP POST + SSE + buffered fallbackのpure boundaryで固定する。

**Non-goal:** Prompt、実Model call、Event append、公開UI、本番SSE endpoint、自然言語矛盾検出、
Context Builder、production Semantic Result pipeline。

### 10.2 作成ファイルと責務

- docs/specs/semantic-result.md — field authority、validation順、secret境界、transport frame、
  buffered fallback。
- src/neontof/contracts/semantic_result.py — Pydantic modelとTypeAdapterの構造Schemaだけ。
- src/neontof/contracts/transport.py — HTTP POST request、SSE frame、buffered responseの
  pure contract。本番endpointは持たない。
- tests/contracts/support/evaluate_semantic_contract.py — test-only validation oracle。
- tests/contracts/support/materialize_proposed_events.py — test-only一対一materialize oracle。
- tests/contracts/test_semantic_result.py、test_transport.py — valid / invalid / Evidence /
  narrative-only / duplicate / mutation / SSE / buffered。
- tests/fixtures/semantic-results/** — valid、invalid、evidence、duplicate、control fixture。

### 10.3 型とSignature

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

ProposedEvent: TypeAlias = Annotated[
    ProposedResourceChanged | ProposedCharacterMoved | ProposedClockAdvanced,
    Field(discriminator="type"),
]
PROPOSED_EVENT_ADAPTER = TypeAdapter(ProposedEvent)

class EventProposalRef(ContractModel):
    type: Literal["event"]
    index: int

class FactProposalRef(ContractModel):
    type: Literal["fact"]
    index: int

ProposalRef: TypeAlias = Annotated[
    EventProposalRef | FactProposalRef,
    Field(discriminator="type"),
]
PROPOSAL_REF_ADAPTER = TypeAdapter(ProposalRef)

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

SEMANTIC_RESULT_ADAPTER = TypeAdapter(SemanticResultV1)
~~~

Ruling、ProposedFact、KnowledgeChange、VisibilityChange、RollSpec、ClarificationRequest、
Rejection、NarrativeBeat、ProvisionalDetail、EvidenceClaim、EvidenceRef、SuggestedAction、
EvidenceFactもContractModelとする。全modelはstrict / forbid / frozen、collectionはtuple /
frozensetとする。

~~~python
class SemanticValidationContext(ContractModel):
    known_entity_ids: frozenset[EntityId]
    known_fact_subject_ids: frozenset[FactSubjectId]
    facts_by_id: tuple[tuple[FactId, EvidenceFact], ...]
    current_turn_status: Literal["running", "awaiting_player"]
    publication_visibility: Literal["player_visible"] | NpcId

class AcceptedSemanticResult(ContractModel):
    type: Literal["accepted"]
    value: SemanticResultV1
    next_status: Literal["running", "awaiting_player"]

class RejectedSemanticResult(ContractModel):
    type: Literal["rejected"]
    issues: tuple[ValidationIssue, ...]
    next_status: Literal["awaiting_player", "aborted"]

SemanticValidationOutcome: TypeAlias = Annotated[
    AcceptedSemanticResult | RejectedSemanticResult,
    Field(discriminator="type"),
]
SEMANTIC_OUTCOME_ADAPTER = TypeAdapter(SemanticValidationOutcome)

def normalize_evidence_claim(input_value: object) -> EvidenceClaim: ...
def validate_semantic_result(input_value: object, context: SemanticValidationContext) -> SemanticValidationOutcome: ...
def materialize_semantic_result_for_test(result: SemanticResultV1, context: FixtureEventContext) -> tuple[DomainEvent, ...]: ...

class TurnPostRequest(ContractModel):
    type: Literal["turn_post"]
    turn_request_id: TurnRequestId
    input_text: str

class TransportFrame(ContractModel):
    type: Literal["semantic_result", "narrative", "done"]
    data: JsonValue

def build_buffered_response(result: SemanticResultV1) -> tuple[TransportFrame, ...]: ...
def build_sse_frames(result: SemanticResultV1) -> tuple[TransportFrame, ...]: ...
~~~

materializeはtests/contracts/supportだけに置き、production Turn Engineではない。
build_buffered_responseとbuild_sse_framesはvalidated SemanticResultを受け取った後のpure
contractであり、FastAPI endpoint、SSE connection、Browser、retryを作らない。SSEでもbuffered
でもsemantic_result frameを先に置き、検証前Narrativeを送信しない。両形式の終端payloadは
同一である。

proposed_eventsとproposed_factsだけが状態変更Proposalの宣言配列である。Ruling、knowledge、
visibilityは注釈であり別Eventの源ではない。lifecycle Event、DiceRolled、FactSuperseded、
TurnRevertedはwhitelist外。同じProposal、範囲外ProposalRef、type不一致、二重materializeは
rejectする。clarificationとrejectionは同時指定できない。Evidenceは存在、公開先からの
可視性、structured predicate/value deep equalを検証し、自由文の含意判定をしない。
narrative、narrative_plan、suggested_actions、mentioned_detailsからEventを生成しない。

### 10.4 Test First、RED / Green

- [ ] valid、unknown field / version、invalid Event、invisible / unknown / unrelated-visible /
  claim mismatch Evidenceを最初のREDとして書く。
- [ ] Narrativeを変更してもproposed_eventsが空ならEvent 0件であるtestを書く。
- [ ] SemanticResultのmutation、extra field、string number、再validationをrejectする。
- [ ] duplicate resource、duplicate fact、duplicate materializationを期待codeでrejectする。
- [ ] materializeのProposal件数とEvent件数を一対一にし、注釈配列を増やしてもEvent件数が
  増えないことをPASSさせる。
- [ ] clarification / rejectionはEvent proposalを空にし、awaiting_player / abortedへ遷移。
- [ ] transport testでvalidated semantic_resultがSSE / bufferedの両方の先頭に現れ、検証前
  Narrativeが送信されず、同じresultから同じ終端payloadになることを確認する。
- [ ] 次を実行し、module/export不在の初回REDと最小実装後Greenを記録する。

~~~powershell
& $neontofPython -m pytest tests/contracts/test_semantic_result.py tests/contracts/test_transport.py -q
~~~

### 10.5 実行コマンドと期待結果

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $neontofPython -m pytest tests/contracts/test_semantic_result.py -q
& $neontofPython -m pytest tests/contracts/test_transport.py -q
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
rg -n "自由文|Narrative|Authority|公開前|公開後|awaiting_player|aborted|Evidence|duplicate_proposal|proposed_events|proposed_facts|buffer" docs/specs/semantic-result.md src/neontof/contracts
rg -n "parse_narrative|events_from_narrative|narrative_to_event|state_from_narrative" src/neontof tests --glob "!tests/typecheck_fixtures/**"
~~~

PASSはvalid accepted、Evidence / duplicateの期待code、Narrative-only Event 0、materialize
一対一、SSE / buffered同値、禁止関数検索0件である。

### 10.6 Commit boundary、Gate証拠、rollback

1. test: Semantic Resultの拒否条件を固定する
2. feat: PythonのSemantic Result Schemaを追加する
3. docs: Semantic ResultとNarrativeの契約を分離する

リスクは高い。Gate証拠はAuthority表、Evidence判定、ValidationIssue、duplicate reject、
Event件数、Narrative-only Event 0、SSE / buffered同値、mutation sabotageとする。
P0-07より先にrevertでき、P0-03は独立して残す。

---

## 11. P0-05: Character Sheet Specification

### 11.1 Goal、決定境界、Non-goal

**Goal:** 手書きYAML一fileからCharacter初期状態を読み取れるversioned契約を固定する。

**決定する:** YAML一形式、stable Character ID、Name / Alias、HP、resource一種、items、
location、optional speech style、最小Ruleset値、必須Visibility。

**Non-goal:** UI、Skill Tree、複数Ruleset、万能Schema、production loader、loaderからEventへ
変換するcode、YAML file I/Oをsrcへ追加すること。

### 11.2 作成ファイルと責務

- docs/specs/character-sheet.md — field、制約、Event正規化規則、Visibility、YAML version。
- src/neontof/contracts/character_sheet.py — YAML parse後objectを検証するPydantic modelと
  TypeAdapter。file I/Oは持たない。
- tests/contracts/test_character_sheet.py — test-only safe_load、valid、duplicate Alias、
  HP範囲、ID、strict / frozen。
- tests/fixtures/characters/minimal-character.v1.yaml — 日本語名・Aliasを持つcontract fixture。

PyYAML==6.0.3はrequirements-dev.inとrequirements.lock.txtにのみ存在するtest/dev-only
fixture parserである。testだけがyaml.safe_load(fixture_text)を呼び、Pydantic TypeAdapterへ
objectを渡す。src/neontofにはyaml import、safe_load、YAML filesystem readを置かない。
fixtureはUTF-8で読み、日本語Name / Aliasをround-tripする。yaml.load、unsafe loader、evalは
使わない。

### 11.3 型とSignature

~~~python
class HitPoints(ContractModel):
    current: int
    max: int

class ResourceState(ContractModel):
    id: ResourceId
    label: str
    current: int
    max: int

class SpeechStyle(ContractModel):
    first_person: str
    second_person: str
    endings: tuple[str, ...]
    forbidden_patterns: tuple[str, ...]

class InitialItem(ContractModel):
    id: ItemId
    canonical_name: str

class CharacterRuleset(ContractModel):
    id: Literal["ruleset:neontof-minimal-2d6-v1"]
    action_modifier: int

class CharacterSheetV1(ContractModel):
    schema_version: Literal[1]
    id: CharacterId
    canonical_name: str
    aliases: tuple[str, ...]
    description: str
    hp: HitPoints
    resource: ResourceState
    initial_items: tuple[InitialItem, ...]
    initial_location_id: LocationId
    speech_style: SpeechStyle | None
    ruleset: CharacterRuleset

CHARACTER_SHEET_ADAPTER = TypeAdapter(CharacterSheetV1)
~~~

0 <= hp.current <= hp.max、resourceも同じ、Aliasは空文字と重複禁止、display nameとIDは
分離する。strict / extra forbid / frozenで文字列数値coercion、unknown field、mutationを
rejectする。初期fileの修正で既存Campaign状態を変えず、Campaign開始時のEvent snapshotが権威。

### 11.4 Test First と実行コマンド

- [ ] valid fixtureをyaml.safe_loadで読み、CHARACTER_SHEET_ADAPTER.validate_pythonへ渡す。
- [ ] ID kind違反、HP超過、負値、duplicate Alias、unknown field、string number、frozen mutation
  をrejectする。
- [ ] python -m pytest tests/contracts/test_character_sheet.py -qでmodule/export不在のRED、
  最小Pydantic model後のGreenを記録する。
- [ ] 日本語Name / AliasのUTF-8 round-tripをPASSさせる。
- [ ] src/neontofのyaml / safe_load検索が0件である。

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $neontofPython -m pytest tests/contracts/test_character_sheet.py -q
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
rg -n "Character ID|Aliases|HP|Resource|Initial Items|Initial Location|Speech Style|Ruleset|visibility" docs/specs/character-sheet.md src/neontof/contracts tests/contracts
rg -n "yaml|safe_load" src/neontof
~~~

### 11.5 Commit boundary、Gate証拠、rollback

1. test: Character Sheetの最小YAML入力契約を固定する
2. feat: 手書きCharacter SheetのPydantic Schemaを追加する
3. docs: Character Sheetの単一形式とYAML境界を定義する

Gate証拠はPyYAML=6.0.3、safe_load=utf8_and_mapping_pass、valid / invalid fixture、
field path、strict / frozen sabotage、日本語round-trip、src YAML I/O検索0件とする。

---

## 12. P0-06: Scenario Format Specification

### 12.1 Goal、決定境界、Non-goal

**Goal:** 公開情報とGM専用情報を分離した、手書きYAML一fileの最小Scenario形式を固定する。

**決定する:** YAML一形式、Scenario ID / version、initial Scene、4〜6 Locations、3〜4 NPCs、
World Invariants、Secret 1、Clues 3、Clock 1、success / failure End Condition、全初期事実と
objective / goal / End Conditionの必須Visibility。

**Non-goal:** Editor、二つ目のformat、Graph DSL、汎用Validator、実Scenario本文、Runtime、
Director、production YAML loader、Context Builder。

### 12.2 作成ファイルと責務

- docs/specs/scenario-format.md — field、count、stable ID、Visibility、Safety優先、Event正規化。
- src/neontof/contracts/scenario.py — 一形式だけのPydantic modelとTypeAdapter。file I/Oなし。
- tests/contracts/support/validate_scenario_publication.py — test-only Visibility oracle。
- tests/contracts/test_scenario.py — count、ID reference、secret visibility、end conditions、
  required Visibility、strict / frozen。
- tests/fixtures/scenarios/minimal-scenario.v1.yaml — 4 locations、3 NPCs、secret 1、clues 3、
  clock 1のsynthetic fixture。
- tests/fixtures/scenarios/missing-objective-visibility.v1.yaml
- tests/fixtures/scenarios/missing-npc-goal-visibility.v1.yaml
- tests/fixtures/scenarios/missing-end-condition-visibility.v1.yaml
- tests/fixtures/scenarios/gm-only-player-publication.v1.yaml

PyYAML==6.0.3はdev/test-onlyである。testがyaml.safe_loadでUTF-8 YAMLをobjectへ読み、
SCENARIO_ADAPTER.validate_pythonへ渡す。src/neontofはYAMLもfilesystemも読まない。全fieldの
Visibilityを宣言値として検証し、field名、section名、文字列内容から推測しない。

### 12.3 型とSignature

~~~python
class ScenarioText(ContractModel):
    text: str
    visibility: Visibility

class SceneDefinition(ContractModel):
    id: SceneId
    location_id: LocationId
    npc_ids: tuple[NpcId, ...]
    objective: ScenarioText

class LocationDefinition(ContractModel):
    id: LocationId
    canonical_name: str
    description: str
    visibility: Visibility

class NpcDefinition(ContractModel):
    id: NpcId
    canonical_name: str
    aliases: tuple[str, ...]
    goal: ScenarioText
    knowledge: tuple[ScenarioText, ...]

class WorldInvariant(ContractModel):
    id: InvariantId
    statement: str
    visibility: Visibility

class SecretDefinition(ContractModel):
    id: SecretId
    text: str
    visibility: Literal["gm_only"]

class ClueDefinition(ContractModel):
    id: ClueId
    text: str
    location_ids: tuple[LocationId, ...]
    visibility: Visibility

class ClockDefinition(ContractModel):
    id: ClockId
    label: str
    segments: int
    initial: int
    visibility: Visibility

class CluesDiscoveredEndCondition(ContractModel):
    type: Literal["clues_discovered"]
    id: EndConditionId
    clue_ids: tuple[ClueId, ClueId, ClueId]
    visibility: Visibility

class ClockReachedEndCondition(ContractModel):
    type: Literal["clock_reached"]
    id: EndConditionId
    clock_id: ClockId
    value: int
    visibility: Visibility

EndCondition: TypeAlias = Annotated[
    CluesDiscoveredEndCondition | ClockReachedEndCondition,
    Field(discriminator="type"),
]
END_CONDITION_ADAPTER = TypeAdapter(EndCondition)

class ScenarioV1(ContractModel):
    schema_version: Literal[1]
    id: ScenarioId
    version: str
    initial_scene: SceneDefinition
    locations: tuple[LocationDefinition, ...]
    npcs: tuple[NpcDefinition, ...]
    world_invariants: tuple[WorldInvariant, ...]
    secret: SecretDefinition
    clues: tuple[ClueDefinition, ClueDefinition, ClueDefinition]
    clock: ClockDefinition
    end_conditions: tuple[EndCondition, EndCondition]

SCENARIO_ADAPTER = TypeAdapter(ScenarioV1)

def validate_scenario_publication_for_test(scenario: ScenarioV1, publication_visibility: Literal["player_visible"] | NpcId) -> tuple[ScenarioVisibilityIssue, ...]: ...
~~~

object unionのdiscriminatorはtypeを使い、section名から推測しない。Location数4〜6、NPC数3〜4、
Secret exactly 1、Clue exactly 3、Clock exactly 1。全reference IDは同一file内で解決する。
Scene.objective、Npc.goal、両End Condition、Location、Knowledge、World Invariant、Secret、
Clue、Clockなど全初期事実は必須visibilityを持つ。Secretはgm_onlyに限定し、player-visible
Secretをrejectする。Phase 1 Loaderは宣言済みVisibilityだけをfilterへ渡す。

### 12.4 Test First と実行コマンド

- [ ] valid fixtureをsafe_loadしSCENARIO_ADAPTER.validate_pythonへ渡す。
- [ ] Location 3件、NPC 5件、Secret visibility変更、unknown reference、missing failure End、
  unknown field、string number、frozen mutationをrejectする。
- [ ] objective、goal、success/failure End Condition、各初期事実のVisibilityを検証する。
  missing-* fixtureはmissing_visibility、gm-only player公開はinvisible_scenario_contentで
  rejectする。
- [ ] python -m pytest tests/contracts/test_scenario.py -qでmodule/export不在のREDとGreenを
  記録する。secret sentinelをpublic subsetへ出さないtestを入れる。
- [ ] src/neontofのyaml / safe_load検索が0件である。

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $neontofPython -m pytest tests/contracts/test_scenario.py -q
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
rg -n "Scenario ID|Version|Initial Scene|Locations|NPC|objective|goal|World Invariants|Secret|Clues|Clock|Success|Failure|visibility|gm_only" docs/specs/scenario-format.md src/neontof/contracts tests/contracts
rg -n "yaml|safe_load" src/neontof
~~~

### 12.5 Commit boundary、Gate証拠、rollback

1. test: Scenarioの最小YAML入力契約を固定する
2. feat: 手書きScenarioのPydantic Schemaを追加する
3. docs: Scenarioの単一形式と秘密境界を定義する

Gate証拠はrequired Visibility schema、欠落 / gm_only公開のValidationIssue、正常系、
safe_load evidence、production YAML I/O検索0件とする。P0-05 / P0-04と独立してrevertできる。

---

## 13. P0-07: Test Provider and Fixture Strategy

### 13.1 Goal、決定境界、Non-goal

**Goal:** API key、課金、network、出力揺れなしでsuccess、failure、retry、timeout、invalid
JSON、同一Fixtureの決定性を表現できるTest Providerを持つ。

**決定する:** provider-neutral request / response、single Callable injection、Fake、Scripted
step、Recorded Fixture、sanitized call log、公開Context filter、error taxonomy、socket禁止。

**Non-goal:** 実Provider Adapter、Provider registry、capability negotiation、複数実Provider、
production retry loop、Turn Engine、raw実Response、OpenAI SDK。

### 13.2 作成ファイルと責務

- docs/specs/test-provider-and-fixtures.md — Fixture version、sanitization、error、call log、
  CI policy、network / API keyなし。
- src/neontof/model/model_invoker.py — narrow Callableとrequest / response model。
- src/neontof/model/publication_visibility.py — 公開ContextのVisibility filterだけ。
- src/neontof/model/fake_provider.py — 固定responseまたはerrorのfactory。
- src/neontof/model/scripted_provider.py — step列とinstance-local call log。
- src/neontof/model/recorded_fixture.py — sanitized JSON fixture load / validate。networkなし。
- tests/model/test_fake_provider.py、test_scripted_provider.py、test_recorded_fixture.py、
  test_provider_security.py。
- tests/model/support/run_invocation_scenario.py、materialize_proposed_events.py — test-only
  driver / oracle。
- tests/fixtures/providers/normal-turn.v1.json、model-error.v1.json、timeout.v1.json、
  invalid-json.v1.json、retry-then-success.v1.json、sanitized-call-log.v1.json。

### 13.3 型とSignature

~~~python
Role: TypeAlias = Literal["referee", "world_simulator", "npc_actor", "narrator"]
PublicationVisibility: TypeAlias = Literal["player_visible"] | NpcId

class ModelRequest(ContractModel):
    model_call_id: ModelCallId
    turn_id: TurnId
    roles: tuple[Role, ...]
    publication_visibility: PublicationVisibility
    context: JsonValue
    output_schema: Literal["semantic-result-v1"]
    # API key、secret、credential、SecretStore参照値をfieldに持たない

class ModelUsage(ContractModel):
    input_tokens: int
    output_tokens: int
    cached_tokens: int

class ModelResponse(ContractModel):
    payload: JsonValue
    usage: ModelUsage

ModelInvoker: TypeAlias = Callable[[ModelRequest], ModelResponse]

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
PROVIDER_STEP_ADAPTER = TypeAdapter(ProviderStep)

class ProviderCallLogMeta(ContractModel):
    attempt: int
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    usage: ModelUsage | None
    context_item_count: int
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None

class SanitizedProviderCallLogEntry(ContractModel):
    request_id: ModelCallId
    attempt: int
    publication_visibility: PublicationVisibility
    context_digest: str
    context_item_count: int
    usage: ModelUsage | None
    status: Literal["succeeded", "failed", "timed_out", "rejected"]
    error_code: Literal["model_error", "timeout", "invalid_json", "script_exhausted"] | None

ProviderCallLogEntry: TypeAlias = SanitizedProviderCallLogEntry

class RecordedFixtureV1(ContractModel):
    fixture_version: Literal[1]
    name: str
    steps: tuple[ProviderStep, ...]
    expected_call_count: int
    expected_final_outcome: Literal["success", "model_error", "timeout", "invalid_json"]
    expected_proposed_events: tuple[ProposedEvent, ...]

class TestProvider:
    def invoke(self, request: ModelRequest) -> ModelResponse: ...
    @property
    def calls(self) -> tuple[SanitizedProviderCallLogEntry, ...]: ...

def create_fake_provider(step: ProviderStep) -> TestProvider: ...
def create_scripted_provider(steps: Sequence[ProviderStep]) -> TestProvider: ...
def load_recorded_fixture(source: str) -> RecordedFixtureV1: ...
def create_recorded_fixture_provider(source: str) -> TestProvider: ...
def sanitize_provider_call_log(input_request: ModelRequest, meta: ProviderCallLogMeta) -> SanitizedProviderCallLogEntry: ...
def filter_context_by_visibility(facts: Sequence[FactRecord], publication_visibility: PublicationVisibility) -> tuple[FactRecord, ...]: ...
~~~

TestProviderはP0-07の観測用具であり、production Provider hierarchyではない。ModelInvokerは
一つのCallable境界であり、二つ目の実Providerを正当化する抽象階層を作らない。
ModelRequestにAPI key / secret fieldを作らない。filterはplayer_visibleまたは対象NPCへ明示的
に可視なFactだけを返し、gm_onlyを返さない。Context Builder、Prompt生成、OpenAI request
mappingはPhase 1に残す。

sanitize_provider_call_logはmodel_call_id、publication_visibility、canonical JSONのSHA-256
context_digest、context_item_count、usage、status、error_codeだけを返す。raw ModelRequest、
context、roles、payload、任意JSON、環境変数、error messageを保持しない。ModelResponse.payload
をstateへ直接渡さず、SemanticResult adapterを通す。invalid_jsonは成功扱いにしない。

### 13.4 Test First、RED / Green

- [ ] fixed success、model error、timeout、invalid JSON、retry-then-success、script exhaustを
  testに書く。最初のREDはpytest runner起動後のmodule/export不在とする。
- [ ] sanitized call logにrequest、context、任意JSON、API key / secret fieldがないことを
  testする。
- [ ] gm_only、player_visible、対象外NPC、対象NPCのFactのfilter結果を固定する。
- [ ] TOP_SECRET_SENTINELはtest memory上だけに注入し、output、captured log、Fixture、
  tests/fixturesへ現れないことを検証する。
- [ ] call count / order、同一Fixtureから同一validated proposed Event Sequenceをtestする。
- [ ] `tests/conftest.py`から全pytest sessionへautouseで
  `tests/support/no_external_network.py`を適用する。socket.socket、socket.create_connection、
  socket.getaddrinfo、http.client、urllib、外部HTTP clientをfail-fastへpatchし、srcの外部
  socket / API使用はpytest全体でFAILにする。P0-07専用testだけの境界にしない。
- [ ] python -m pytest tests/model -qでmodule missingのRED、3 factory実装後のGreenを記録する。
- [ ] Narrativeだけを変えてもEvent Sequence不変、proposed_events変更でtest失敗を確認する。
- [ ] 実Provider、network、.envなしで全testを再実行し、OpenAI SDKをinstallしない。

### 13.5 実行コマンドと期待結果

~~~powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $neontofPython -m pytest tests/model -q
& $neontofPython -m pytest tests/contracts/test_semantic_result.py tests/model/test_recorded_fixture.py -q
& $neontofPython -m pytest -q
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
rg -n "sk-[A-Za-z0-9]{20,}|TOP_SECRET_SENTINEL" src/neontof tests/fixtures
rg -ni "^(from|import) openai|openai" src/neontof
rg -ni "provider_registry\.py|ProviderRegistry|Capability|Plugin|Hook|Profile" src/neontof
rg -ni "anthropic|sqlite3\.connect|sqlite3\.Connection|provider_registry" src/neontof
rg -n "socket\.(socket|create_connection|create_server|getaddrinfo)|http\.client|urllib\.(request|parse)|requests\.|httpx\.(Client|AsyncClient)|urlopen" src/neontof
~~~

PASSはprovider test全成功、retry call count一致、Event Sequence deep equal、sanitized logに
raw request / contextなし、filter正常、src/neontofとtests/fixturesにsecret・sentinelなし、
openai・registry等なし、source network pattern 0件、全pytest sessionのautouse network禁止PASS、
API keyなし、network call 0である。Provider testはFake / Scripted / Recorded Fixtureだけで、
OpenAI SDKはPhase 1候補のADR記録だけにする。
このP0-07のproduction-only forbidden scanでもtestsのreject case語を許し、forbidden source patternの
`rg`はexit 1だけをzero-hit成功、exit 0をhitによるFAIL、exit 2以上をtool failureとする。

### 13.6 Commit boundary、Gate証拠、rollback

1. test: Test Providerの成功失敗Fixtureを固定する
2. feat: API不要のFakeとScripted Providerを追加する
3. feat: 記録済みProvider Fixtureを再生する
4. docs: Test ProviderとFixtureの安全境界を定義する

Gate証拠はFixture別test、call count、Event Sequence、sanitized shape、Signature、filter、
socket禁止、sentinel不在、実Provider file 0件、openai検索0件とする。匿名化前responseが混入
した場合はcommitせず停止し、credential rotationの要否を報告する。

---

## 14. 重量パスのレビューと統合

1. 実装者と別の最上位impl-reviewerがAuthority、Visibility、version、Phase Non-goal、
   Pydantic strict / frozen、SQLite ownership、Python commandを一次reviewする。
2. 非メイン側AIがclean contextで独立二次reviewする。Codexメイン時の直接CLIは次の形である。

~~~powershell
claude -p "docs/plans/phase-00-foundation.mdと対象diffを突き合わせ、Event Log単一権威、Semantic Result/Narrative分離、Visibility/秘密、Transcript/Telemetry分離、Pydantic strict/frozen、SQLite ownership、Phase 0 Non-goalをレビューし、blocking/non-blockingを日本語で返せ。" --model opus --permission-mode plan
~~~

3. blockingだけを修正し、再reviewは対応diffだけ最大2周。3周目を作らない。
4. P0-04 / P0-05 / P0-06は独立review可能。P0-07はP0-04 commit後にreviewする。
5. 統合後は重複、Signature / version衝突、dependency逆転、Node / OpenAI混入、SQLite
   ownershipの合成退行だけを1回シーム監査する。
6. review済みdiffを後続開始前にcommitし、git add -A / git add .を使わずpathを列挙する。

---

## 15. Phase Gate 検証表

| Gate | 証拠command / artifact | 成功条件 |
|---|---|---|
| Stack承認 | docs/adr/0001-technology-stack.md | Accepted、承認引用、Bのexact version |
| MyWorkflow guide boundary | `docs/neontof-phase-00-guides` branch、3 files、review / commit / deploy | architecture.md、coding-style.md、build-and-verify.mdだけ、MyWorkflow mainへ直接commitなし、pushなし、展開差分0。P0-01b実測後にbuild guideをactual commandへ別commit |
| Runtime | py -3.14 version assert、.python-version | 3.14.3一致 |
| Dependency install | unique TEMP / fresh isolated venv、`pip install --require-hashes -r requirements.lock.txt`、pip check、openai absence | exit 0、No broken requirements found.、`openai absent`。既存repository `.venv`だけは証拠にしない |
| Lock generation | TEMP tool venv、pip-tools==7.6.1、固定pip-compile | Python 3.14.3 version assert、`requirements-dev.in` input、`--generate-hashes`、明示output、`pip-tools (7.6.1)` |
| Dependency root set | requirements.in / requirements-dev.in / requirements.lock.txt | runtime root setがfastapi/pydantic/uvicornだけ、dev root setがPyYAML/httpx/mypy/pytest/ruff/types-PyYAMLだけ、余分なrootはFAIL |
| Dependency boundary | requirements.in / requirements-dev.in / requirements.lock.txt | runtime/dev分離、PyYAML 6.0.3はdev-only、openai 0件 |
| Build | python -m compileall -q src | exit 0 |
| Format | python -m ruff format --check src tests | 差分なし、exit 0 |
| Lint | python -m ruff check src tests | error 0 |
| Type | python -m mypy --strict src tests --exclude tests/typecheck_fixtures | error 0、Pydantic plugin、warn_unused_ignores |
| Negative type | negative fixture単独mypy | stdout / stderrを捕捉してexpected exit 1、error lines exactly 2、両方`[arg-type]`、other errors 0、fixture filename / `TranscriptEntry` / `TelemetryEntry` / `DomainEvent` fragment |
| Test | python -m pytest -q | 全test passed、API keyなし |
| Empty Application | 実entrypoint probe | HTTP 200、{"status":"ok"}、127.0.0.1 |
| Process lifecycle | entrypoint probe | --workers 1、CTRL_BREAK_EVENT相当、graceful exit code 0、PID終了、2回目health 200 / JSON、rebind、stdout/stderr empty。bind failure / timeoutはFAIL |
| Worker rejection probe | fresh gateの`python -m neontof.main --workers 2`、stdout / stderr capture | exit exactly 2、outputにexact message `NEONTOF_WORKERS must be 1` |
| SQLite ownership | src検索、test | Phase 0のsqlite3.connect / Connection 0件、P1-01 owner契約 |
| Contract model | test_contract_model.py | strict、forbid、frozen、immutable、mutation/revalidation PASS |
| Event parser | parser testと禁止検索 | unknown field/version、ID、payload reject、bypass 0件 |
| Projection | domain / turn status test | 同一Event→同一Projection、revert、awaiting_player、resend |
| Semantic | semantic result test | Narrative Event 0、Evidence reject、duplicate、一対一materialize |
| Transport | transport test | HTTP POST、SSE / buffered同値、検証前Narrative非送信、本番endpoint 0件 |
| Character | character sheet test | YAML safe_load、valid/invalid、strict/frozen、UTF-8 |
| Scenario | scenario test | required Visibility欠落、gm_only player公開reject |
| YAML boundary | requirements、probe証拠、src検索 | PyYAML=6.0.3、safe_load=utf8_and_mapping_pass、No broken requirements found.、api_call=False、src YAML I/O 0件 |
| Fake / Fixture | 全pytest session、pytest tests/model | success/failure/retry/timeout/invalid JSON、sanitized、filter、全session autouse network/socket禁止、source network pattern 0、API key/network call 0、sentinel不在 |
| OpenAI contamination | requirementsとsource検索 | lock openai不在、import検索expected 0、ADRのPhase 1候補記録だけ |
| Non-goal absence | Test-Path / Get-ChildItem + allowed root manifest | 禁止file / directoryの存在0件、`src/**/openai*.py`、`src/**/provider_registry.py`、`*.sqlite`、`*.db` 0件、manifest外changed path 0件 |
| CI parity | ci.yml、failure probe、remote run | localと同じPython command、故意exit 1、復元後green。remote未確認はpending |
| Status | docs/status/phase-00-foundation.md | Gate結果、実出力、Known Issues、Phase 1停止 |
| Line ending | git diff --numstat / --ignore-cr-at-eol --numstat | 2つが一致 |
| Generated output | git status --short --untracked-files=all | venv、cache、DB、secret、client、migrationsをcommitしない |

Pydantic bypass検索はnegative fixtureを除外せず、`src/neontof`と通常`tests`の全体をscanする。
negative fixtureの`# type: ignore`、`assert_type`、`cast(`は別々にscanし、各zero-hitのrg exit 1を
要求する。

~~~powershell
$bypassPatterns = @('setState', 'updateState', 'mutateState', 'saveProjection', 'model_construct\(', 'cast\(')
foreach ($pattern in $bypassPatterns) {
    & rg -n -- $pattern src/neontof tests
    $bypassExit = $LASTEXITCODE
    if ($bypassExit -eq 1) { continue }
    if ($bypassExit -eq 0) { throw "validation bypass hit for '$pattern'." }
    throw "validation bypass search tool failure for '$pattern' with exit $bypassExit."
}
$negativeFixture = 'tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py'
foreach ($pattern in @('# type: ignore', 'assert_type', 'cast\(')) {
    & rg -n -- $pattern $negativeFixture
    $negativeFixtureExit = $LASTEXITCODE
    if ($negativeFixtureExit -eq 0) { throw "negative fixture bypass hit for '$pattern'." }
    if ($negativeFixtureExit -ne 1) { throw "negative fixture bypass search failed for '$pattern' with exit $negativeFixtureExit." }
}
~~~

OpenAI混入検索はADRを対象から外す。ADRにはPhase 1候補を記録するためである。

~~~powershell
$requirementsTxt = @(Get-ChildItem -LiteralPath . -File -Filter "requirements*.txt" | Select-Object -ExpandProperty FullName)
$openAiHits = @(rg -ni "openai|^(from|import) openai" ($requirementsTxt + @("pyproject.toml")) 2>$null)
$openAiExit = $LASTEXITCODE
if ($openAiExit -eq 0) { $openAiHits; throw "OpenAI content is forbidden in Phase 0" }
if ($openAiExit -ne 1) { throw "OpenAI search tool failure with exit $openAiExit." }
foreach ($pattern in @('TurnStarted', 'EmptyPayload', 'reference_projection', 'Plugin', 'Hook', 'Profile', 'ProviderRegistry')) {
    $productionForbiddenHits = @(rg -n -- $pattern src/neontof 2>$null)
    $productionForbiddenExit = $LASTEXITCODE
    if ($productionForbiddenExit -eq 0) { $productionForbiddenHits; throw "Production forbidden content found: $pattern" }
    if ($productionForbiddenExit -ne 1) { throw "Production forbidden search failed for $pattern with exit $productionForbiddenExit." }
}
foreach ($pattern in @('openai', 'anthropic', 'sqlite3\.connect', 'sqlite3\.Connection', 'provider_registry')) {
    $sourceOnlyHits = @(rg -ni -- $pattern src/neontof 2>$null)
    $sourceOnlyExit = $LASTEXITCODE
    if ($sourceOnlyExit -eq 0) { $sourceOnlyHits; throw "Source-only forbidden content found: $pattern" }
    if ($sourceOnlyExit -ne 1) { throw "Source-only search failed for $pattern with exit $sourceOnlyExit." }
}
$networkHits = @(rg -n "socket\.(socket|create_connection|create_server|getaddrinfo)|http\.client|urllib\.(request|parse)|requests\.|httpx\.(Client|AsyncClient)|urlopen" src 2>$null)
$networkExit = $LASTEXITCODE
if ($networkExit -eq 0) { $networkHits; throw "External socket/API source usage is forbidden" }
if ($networkExit -ne 1) { throw "External network search tool failure with exit $networkExit." }
Write-Output "openai_import_network_plugin_sqlite_source=0"
~~~

内容検索は補助証拠であり、禁止pathの存在検査とallowed root manifestの集合差分を代替しない。
production-only forbidden語は`src/neontof`だけを対象にし、testsのreject case語を許す。source-only
patternは`openai`、`anthropic`、`sqlite3.connect`、`sqlite3.Connection`、`provider_registry`とし、
全ての`rg`はexit 1だけをzero-hit成功、exit 0をhitによるFAIL、exit 2以上をtool failureとして扱う。

~~~powershell
$repoRoot = (Get-Location).Path
$forbiddenRootFiles = @(
  "package.json", "package-lock.json", ".node-version", "eslint.config.mjs",
  "prettier.config.mjs", "vitest.config.ts", "Dockerfile"
)
foreach ($relative in $forbiddenRootFiles) {
  if (Test-Path -LiteralPath (Join-Path $repoRoot $relative)) { throw "Forbidden path exists: $relative" }
}
$allFiles = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -File |
  Where-Object { $_.FullName -notlike "$repoRoot\.git\*" })
$forbiddenFiles = @($allFiles | Where-Object {
  $relative = $_.FullName.Substring($repoRoot.Length + 1).Replace("\", "/")
  $_.Name -like "tsconfig*.json" -or $_.Name -like "*.ts" -or
    $_.Name -in @("package.json", "package-lock.json", ".node-version", "eslint.config.mjs",
      "prettier.config.mjs", "vitest.config.ts", "Dockerfile") -or
    $relative -match "^src/(?:.*/)?openai[^/]*\.py$" -or
    $relative -match "^src/(?:.*/)?provider_registry\.py$" -or
    $_.Name -like "*.sqlite" -or $_.Name -like "*.db"
})
$forbiddenDirs = @(Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -Directory |
  Where-Object { $_.FullName -notlike "$repoRoot\.git\*" -and $_.Name -in @("client", "migrations") })
if ($forbiddenFiles.Count -gt 0 -or $forbiddenDirs.Count -gt 0) {
  ($forbiddenFiles + $forbiddenDirs).FullName
  throw "Forbidden Phase 0 file or directory exists"
}
$allowedRootManifest = @(
  ".python-version", "pyproject.toml", "requirements.in", "requirements-dev.in",
  "requirements.lock.txt", ".env.example", ".gitignore", ".github/workflows/ci.yml",
  "src/neontof/**", "tests/**", "docs/adr/**", "docs/specs/**", "docs/status/**"
)
function Test-AllowedPhasePath([string] $path) {
  $normalized = $path.Replace("\", "/")
  foreach ($root in $allowedRootManifest) {
    $prefix = $root -replace "/\*\*$", ""
    if ($normalized -eq $prefix -or $normalized.StartsWith("$prefix/")) { return $true }
  }
  return $false
}
$changedPaths = @(git diff --name-only $phaseBaseCommit --)
$unexpectedPaths = @($changedPaths | Where-Object { -not (Test-AllowedPhasePath $_) })
if ($unexpectedPaths.Count -gt 0) { $unexpectedPaths; throw "Path is outside Phase 0 allowed root manifest" }
Write-Output "forbidden_paths=0; allowed_root_manifest_diff=0"
~~~

上のactive path検索が0件で、候補比較の背景節だけにA/Cのtoolchain語が残ることを許容する。
実装pathに残ったTypeScript実行経路はFAILとする。禁止file / directoryは検索結果が空でも
存在すればFAILであり、`phaseBaseCommit`はP0-01b入口で記録して計画編集diffと実装diffを分離する。

### Phase 0 final verification

~~~powershell
# P0-01b final Gate is the canonical block in §9.5 above. Execute that block verbatim;
# do not substitute the existing repository .venv. It creates a unique TEMP/fresh isolated
# venv, reruns the fixed TEMP pip-tools / pip-compile block, and saves every native exit code.
# Its fixed inputs remain Python 3.14.3, requirements-dev.in, requirements.lock.txt,
# --generate-hashes, and pip install --require-hashes. It includes pip check, compileall,
# ruff format/check, normal mypy, pytest, openai absence, API-key restore, network guard,
# lifecycle, workers=2 output probe, cleanup, and remote CI pending.
# Then execute the P0-03 parser / projection / negative-mypy / forbidden / rglob blocks above.
git diff --check
git diff --numstat
git diff --ignore-cr-at-eol --numstat
git status --short --untracked-files=all
~~~

P0-01b final Gateはrepository `.venv` installだけを証拠にしない。negative mypyだけはexpected exit 1なので
通常qualityのexit 0とは別の証拠欄へ記録し、stdout / stderr、error lines exactly 2、両方`[arg-type]`、
other errors 0、fixture filename / `TranscriptEntry` / `TelemetryEntry` / `DomainEvent` fragmentを残す。
`pip-tools (7.6.1)`、direct root set集合一致、禁止path存在0件、manifest外changed path 0件、
sqlite3 connection source 0件、全pytest sessionのnetwork call 0を同じGate証拠へ記録する。
Phase完了報告にはentrypointのHTTP status / JSON、shutdown / PID / rebind、stdout / stderr、
CI failure / green runの実出力を含め、実Providerの一回きりの出力を使わない。

---

## 16. 既知リスクとrollback戦略

| リスク | level | 予防 / 検出 | rollback |
|---|---|---|---|
| Python exact version / dependency選択の誤り | 高 | ADR、fresh venv、lock、pip check | ADRと基盤commitをPhase 1前にrevert |
| lock生成toolのruntime混入 / root set過不足 | 高 | TEMPのpip-tools==7.6.1、固定pip-compile、direct root set集合比較、require-hashes install | requirements入力とlockを再生成し、tool venvをcommitしない |
| FastAPI sync routeとSQLite ownerの混同 | 高 | Phase 0 sqlite3.connect 0件、single worker、P1-01 owner契約 | 接続を追加せずP1-01へ差し戻す |
| Event contract過剰固定 | 高 | 最小fixture、Event version、cold-reader review | 依存commitを逆順revert |
| LLM自由文から状態流入 | 高 | Narrative-only test、禁止検索 | P0-04/P0-07をrevert、P0-03維持 |
| Secret / API key混入 | 高 | sentinel、fixture scan、request type、socket禁止 | commit停止、fixture除去、実keyならrotation判断 |
| Transcript / Telemetry混入 | 高 | union分離、negative mypy、Projection input type | P0-03をrevertして再設計 |
| PyYAML runtime混入 / unsafe load | 中 | requirements分離、lock、safe_load、src I/O 0件 | runtime依存を除去しP0-05/P0-06再実装 |
| Fakeが実Provider抽象化へ肥大 | 中 | Callable一つ、registry検索0件 | P0-07だけrevert |
| OpenAI SDK混入 | 高 | requirements/source/import/registry検索0件 | 混入commitをrevert |
| 外部socket / API混入 | 高 | 全pytest sessionのautouse禁止境界、src static scan、API keyなし、network call 0 | 実装をcommitせずP0-07を縮小 |
| client / migrations先取り | 高 | path禁止、Non-goal検索 | 該当commitをrevert |
| graceful lifecycle / port再bindの未検証 | 高 | CTRL_BREAK_EVENT、exit code 0、2回目health、bind / timeout FAIL | shutdown endpointを足さずentrypoint probeを修正 |
| 禁止pathの存在 / allowed manifest逸脱 | 高 | Test-Path、Get-ChildItem、manifest集合差分 | 該当pathを削除せず停止してscopeを戻す |
| CIとlocalの乖離 | 中 | 同一Python command、failure injection、remote run | CI commitをrevertしP0-01b修正 |
| CI remote未確認 | 中 | statusをpendingと明記 | Phase 1へ進まずevidence待ち |
| LF / UTF-8事故 | 中 | ruff line-ending、BOM/CR検査、numstat比較 | 該当fileだけ修復し再review |

---

## 17. Commit boundary とPhase Completion

1. 1 commit = 1 logical change。件名は英語type + 日本語命令形とする。
2. **この計画更新のcommit名:** docs: Phase 0計画をPython Stackへ更新する。stageするのは
   docs/plans/phase-00-foundation.mdだけである。
3. **P0-02b ADR commit名:** docs: NeontoFのPython技術スタックを決定する。stageするのは
   docs/adr/0001-technology-stack.mdだけである。
4. **P0-02b MyWorkflow commit boundary:** ADR commit後に`docs/neontof-phase-00-guides` branchを
   切り、`git add architecture.md coding-style.md build-and-verify.md`だけを行い、review後に
   MyWorkflow側でcommit / deployする。P0-01b完了後のactual command反映は
   `git add build-and-verify.md`だけの別commitとする。MyWorkflow `main`へ直接commitせず、pushせず、
   NeontoFと同一commitにしない。
5. Failing Test → Minimal Implementation → Refactor → 文書の順を既定とする。ただしP0-01bは
   runner bootstrap後にimport REDを作り、最小health実装でGreenにする。
6. dangerous spec / ADR diffは一次・クロスAI二次review後にcommitする。
7. stageは宣言scopeのpathを明示し、git add -A / git add .を使わない。pushしない。
8. commit前にgit diff --check、numstat 2種、git status --short --untracked-files=all、関係
   testを実行する。
9. Phase completion commitはdocs: Phase 0のGate証拠を記録する。stageはdocs/status/
   phase-00-foundation.mdだけである。
10. completion条件はPhase Gate全件PASS。ただしCI remote未確認はpendingとしてcompletion不可。
11. Gate通過後もPhase 1 file、client、migrations、OpenAI SDKを作らず停止する。

---

## 18. ユーザー判断が必要な点

1. このB専用詳細計画の一次reviewと非メイン側AI二次review後、実装前に一度承認を待つ。
2. Stack承認Bは完了済み。追加のA/B/C比較、P0-02a再probe、Stack変更は不要。次はADR
   commit後にMyWorkflowの`docs/neontof-phase-00-guides` branch / 3-file commit / deployを
   着地させ、その後P0-01bへ進む。P0-01bの実測後にMyWorkflow `build-and-verify.md`を
   actual command / expected output / CI parityへ別commitで更新する。ADRにはPyYAML probe
   evidenceとOpenAI Phase 1候補を記録するが、OpenAI SDKはP0へ入れない。
3. CI反映操作はユーザーが行う。P0-01b commit後にbranchをremoteへ反映し、failure probeと
   復元後green runのURL/statusを共有する。未確認はpending。
4. Phase 0 Gate後のPhase 1開始は自動ではなく、ユーザーが判断する。
5. migrations/0001_initial.sqlとOpenAI Responses API + official Python SDKはPhase 1の別計画・
   別承認で扱い、Phase 0完了を理由に先行作成しない。
