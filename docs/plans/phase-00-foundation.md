# Phase 0: Foundation Contracts 詳細 Implementation Plan（候補B実行版）

> **実行エージェント向け:** この計画はユーザー承認済みの候補Bを前提にする。P0-01b以降は
> Pythonのfresh venv、locked dependency、src layout、Test First、RED/Green、実コマンドの順で
> Work Packageを完了させる。承認後の実行経路にNode、npm、TypeScript、Fastify、Zod、Vitestは
> 存在しない。P0-02aの候補比較と過去評価に現れるA/Cは背景であり、再実行しない。

**Goal:** Event履歴、セーブデータ、テスト、後続機能へ波及する最小契約と、APIキーなしで反証
可能な品質基盤を固定し、Phase 1の実装を開始できる状態にする。

**期待する挙動変化:** 現在は計画文書しかない。Phase 0完了時には、候補Bを記録した承認済み
Stack ADR、起動可能な空Application、CIとローカルで同じPython Build/Test/Format/Lint/型
チェック、Domain・Semantic Result・Character Sheet・Scenarioの契約テスト、Fake / Scripted /
Recorded Fixture Providerが存在する。実ScenarioのTurn、Web UI、client、永続Event Store、
実Provider、migrations directoryはまだ存在しない。

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
- OpenAIの文字列検索はrequirementsとsrc/testsの実行対象で0件、src/**/provider_registry.py、
  client/**、migrations/**、Dockerfile、package系、TypeScript実行経路が存在しない。禁止
  file / directoryはTest-Path / Get-ChildItemで存在そのものをFAILにする。
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

- Phase 0のEvent / Projection codeは副作用を持たない純粋Contract実装とtest-only reducer
  とする。永続Event Storeの所有権はPhase 1でTurn Engineのappend経路へ与える。
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
    └─ HealthResponseだけを参照。Game state、Event、sqlite3、Providerを所有しない
src/neontof/contracts/domain.py
src/neontof/contracts/event_parser.py
src/neontof/contracts/turn_status.py
    └─ base.py / ids.pyのContractModel、ID、Visibility、Event型だけを参照
src/neontof/contracts/semantic_result.py
    └─ domain.pyのEvent / ID / Visibilityを参照。NarrativeをEventへ変換しない
src/neontof/contracts/character_sheet.py
src/neontof/contracts/scenario.py
    └─ domain.pyのstable ID / Visibilityだけを参照。file I/Oを持たない
src/neontof/model/*
    └─ semantic_result.py / domain.pyのprovider-neutral contractを参照
tests/** → src/neontof/**
tests/**のsupportはtest-only oracle / driverを所有する
src/neontof/** → tests/** は参照しない
~~~

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
`node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs --apply NeontoF`、続けて
`node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF`を実行し、展開差分0を
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
Set-Location C:/Users/KINGkawamura/Documents/MyWorkflow
git switch -c docs/neontof-phase-00-guides
# architecture.md、coding-style.md、build-and-verify.mdだけを編集する
git add architecture.md coding-style.md build-and-verify.md
git diff --cached -- architecture.md coding-style.md build-and-verify.md
git diff --cached --name-only
# staged diffのreview完了を確認してからcommitする
git commit -m "docs: NeontoFのPythonガイドを更新する"
git show --check --stat HEAD
node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs --apply NeontoF
node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF
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
別commandはexpected exit 1で、[arg-type]または[assert-type]の実出力をGate証拠へ貼る。
error-code付きignoreはnegative fixture内の意図した型エラー位置だけに置き、productionや
通常quality対象へ拡張しない。

negative fixtureは次のように、Transcript / TelemetryをDomainEventへ渡す型境界を明示する。
assert_typeの不一致が[assert-type]でexit 1になり、呼び出し行のignoreは[arg-type]を明記
する。fixture以外のsource / testsにはこのignoreを置かない。

~~~python
from typing import assert_type

assert_type(transcript_entry, DomainEvent)  # expected [assert-type]
append_domain_event(transcript_entry)  # type: ignore[arg-type]
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
$requirementsDevInput = (Resolve-Path -LiteralPath "requirements-dev.in").Path
$requirementsLockOutput = Join-Path (Get-Location) "requirements.lock.txt"
& $pipCompile --generate-hashes --output-file $requirementsLockOutput $requirementsDevInput
if ($LASTEXITCODE -ne 0) { throw "pip-compile failed" }
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
& $neontofPython -m mypy --strict tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py
~~~

期待結果は[arg-type]または[assert-type]を含むexit 1。通常qualityはnegative fixtureを除外
してexit 0、負例単独は型境界が壊れた場合にexit 1となる。

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

**Non-goal:** Database table、Event repository、sqlite3 transaction、migration runner、完全な
State / Canon、Ruleset event全種、Turn Engine。

### 9.2 作成ファイルと責務

- docs/specs/core-domain-and-events.md — Domain語彙、Authority、Event、Projection、Transcript /
  Telemetry、Undo、version / migration規則。
- src/neontof/contracts/base.py — ContractModelとimmutable JSON helper。
- src/neontof/contracts/ids.py — Annotated ID、StringConstraints、Visibility、stable grammar。
- src/neontof/contracts/domain.py — Event subtype、DomainEvent union、TranscriptEntry、
  TelemetryEntry、FactRecord、Projection。
- src/neontof/contracts/event_parser.py — TypeAdapterによる受信・保存境界、parse function、
  ValidationIssue。
- src/neontof/contracts/turn_status.py — Event列だけからTurn statusを再構築する純粋関数。
- tests/contracts/support/reference_projection.py — test-only pure reducer。
- tests/contracts/test_domain.py、test_event_parser.py、test_turn_status.py、
  test_contract_model.py — valid / invalid / rebuild / transition / sabotage。
- tests/fixtures/events/minimal-session.v1.json、invalid-unknown-field.v1.json、
  invalid-unknown-version.v1.json、invalid-unknown-event.v1.json、invalid-payloads.v1.json、
  turn-status-sequences.v1.json、same-request-resend.v1.json。

### 9.3 型とSignature

~~~python
from typing import Annotated, Literal, TypeAlias
from pydantic import Field, TypeAdapter

CampaignId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^campaign:[a-z0-9]+(?:-[a-z0-9]+)*$")]
SessionId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^session:[a-z0-9]+(?:-[a-z0-9]+)*$")]
SceneId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^scene:[a-z0-9]+(?:-[a-z0-9]+)*$")]
TurnId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^turn:[a-z0-9]+(?:-[a-z0-9]+)*$")]
TurnRequestId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^turn-request:[a-z0-9]+(?:-[a-z0-9]+)*$")]
EventId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^event:[a-z0-9]+(?:-[a-z0-9]+)*$")]
FactId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^fact:[a-z0-9]+:[0-9]+$")]
NpcId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^npc:[a-z0-9]+(?:-[a-z0-9]+)*$")]
Visibility: TypeAlias = Literal["gm_only", "player_visible"] | NpcId
VISIBILITY_ADAPTER = TypeAdapter(Visibility)
~~~

EntityId、FactSubjectId、CharacterId、LocationId、ItemId、ClockId、ResourceId、ActionId、
ScenarioId、SecretId、ClueId、InvariantId、EndConditionId、TranscriptId、TelemetryId、
ModelCallIdも同じkind:slug grammarで個別に定義する。

各Event subtypeはContractModelで、typeをdiscriminatorにする。Event typeはCampaignCreated、
SessionStarted、SceneStarted、SceneEnded、PlayerInputAccepted、DiceRolled、ResourceChanged、
CharacterMoved、ClockAdvanced、FactAsserted、FactSuperseded、TurnAwaitingPlayer、TurnResumed、
TurnAborted、TurnCommitted、TurnReverted、SessionEndedを固定する。

~~~python
class SessionStartedEvent(ContractModel):
    type: Literal["SessionStarted"]
    event_id: EventId
    event_version: Literal[1]
    campaign_id: CampaignId
    session_id: SessionId | None
    scene_id: SceneId | None
    turn_id: TurnId | None
    sequence: int
    occurred_at: str
    origin: Literal["in_world", "table_correction"]
    visibility: Visibility
    payload: SessionStartedPayload

DomainEvent: TypeAlias = Annotated[
    CampaignCreatedEvent | SessionStartedEvent | SceneStartedEvent | SceneEndedEvent
    | PlayerInputAcceptedEvent | DiceRolledEvent | ResourceChangedEvent
    | CharacterMovedEvent | ClockAdvancedEvent | FactAssertedEvent
    | FactSupersededEvent | TurnAwaitingPlayerEvent | TurnResumedEvent
    | TurnAbortedEvent | TurnCommittedEvent | TurnRevertedEvent | SessionEndedEvent,
    Field(discriminator="type"),
]
DOMAIN_EVENT_ADAPTER = TypeAdapter(DomainEvent)

def parse_domain_event(input_value: object) -> DomainEvent: ...
def parse_domain_event_sequence(inputs: Sequence[object]) -> tuple[DomainEvent, ...]: ...
def derive_fact_id(event_id: EventId, ordinal: int) -> FactId: ...
def rebuild_projection(events: Sequence[DomainEvent]) -> Projection: ...
def project_turn_status(events: Sequence[DomainEvent]) -> TurnStatus: ...
~~~

DomainEventValidationIssueはpath、code（schema、unknown_field、unknown_event、unknown_version、
invalid_id、invalid_sequence、invalid_payload）、messageを持つfrozen ContractModelとする。
Pydantic ValidationErrorはDomainEventValidationErrorへ変換する。raw JSONをDomainEventとして
扱わず、event_version != 1、unknown field、ID grammar、payloadの欠落・余分field・型不正を
期待codeでrejectする。

TranscriptEntryとTelemetryEntryはDomainEvent unionに含めず、Projection reducerの入力にも
含めない。Projectionはapplied_through_sequence、immutable state、facts、frozensetの
reverted_turn_idsを持つ。sequenceはCampaign内で厳密増加し、occurred_atはゲーム判断に
使わない。TurnRevertedはEventを削除せず、対象Turnの効果だけをrebuildで除外する。
PlayerInputAccepted、TurnAwaitingPlayer、TurnResumed、TurnCommitted、TurnAbortedの遷移と
same-request resend、再起動後awaiting_playerをEvent列から再構築する。

### 9.4 Test First、RED / Green

- [ ] ContractModelのstrict、extra forbid、frozen、tuple / frozenset、mutation、
  revalidation sabotageを先に書く。
- [ ] valid Eventをparserへ渡す最初のREDを、runner起動後のmodule/export不在で作る。
- [ ] unknown event、unknown top-level / payload field、version 2、ID grammar違反、全Eventの
  必須payload欠落・型不正をfixtureごとに書き、ValidationIssue codeを期待する。
- [ ] raw fixtureをparse_domain_event_sequenceで検証してからreference reducerへ渡す。
- [ ] 同一Event配列の2回rebuild deep equal、Fact ID、TurnReverted、sequence重複、unknown
  version、same-request resend、awaiting_player restartをtestする。
- [ ] Transcript / TelemetryをDomainEventへ渡せないnegative mypy fixtureを作り、通常quality
  からだけ除外して独立mypy commandのexpected exit 1を記録する。
- [ ] 次を実行し、初回REDと最小実装後Greenを記録する。

~~~powershell
& $neontofPython -m pytest tests/contracts/test_event_parser.py tests/contracts/test_domain.py tests/contracts/test_turn_status.py -q
~~~

### 9.5 実行コマンドと期待結果

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $neontofPython -m pytest tests/contracts/test_contract_model.py -q
& $neontofPython -m pytest tests/contracts/test_event_parser.py -q
& $neontofPython -m pytest tests/contracts/test_domain.py tests/contracts/test_turn_status.py -q
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
rg -n "Event Log|Projection|Transcript|Telemetry|TurnReverted|TurnAwaitingPlayer|TurnResumed|TurnAborted|awaiting_player|event_version|parse_domain_event|unknown_version|invalid_payload" docs/specs/core-domain-and-events.md src/neontof/contracts
rg -n "setState|updateState|mutateState|saveProjection|model_construct\(|\bcast\(" src/neontof tests --glob "!tests/typecheck_fixtures/**"
~~~

PASSはpytest全成功、mypy error 0、必須spec語、State直接更新API・model_construct・castの
production / normal test検索0件である。

### 9.6 Commit boundary、Gate証拠、rollback

1. test: EventからProjectionを再構築する契約を固定する
2. feat: PythonのDomainとEvent最小契約を追加する
3. docs: Core DomainとEventの仕様を確定する

Gate証拠はvalid / invalid fixture、ValidationIssue、Projection、turn status、sabotage、
normal mypy 0、negative mypy expected exit 1、禁止API検索0件とする。リスクは高い。
後続着手前なら3commitを逆順revertし、永続Eventがないためdata migrationは作らない。

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
rg -n "^(from|import) openai|openai" src/neontof tests requirements.in requirements-dev.in requirements.lock.txt pyproject.toml
rg -n "provider_registry\.py|ProviderRegistry|Capability|Plugin|Hook|Profile" src/neontof tests
rg -n "socket\.(socket|create_connection|create_server|getaddrinfo)|http\.client|urllib\.(request|parse)|requests\.|httpx\.(Client|AsyncClient)|urlopen" src/neontof
~~~

PASSはprovider test全成功、retry call count一致、Event Sequence deep equal、sanitized logに
raw request / contextなし、filter正常、src/neontofとtests/fixturesにsecret・sentinelなし、
openai・registry等なし、source network pattern 0件、全pytest sessionのautouse network禁止PASS、
API keyなし、network call 0である。Provider testはFake / Scripted / Recorded Fixtureだけで、
OpenAI SDKはPhase 1候補のADR記録だけにする。

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
| Dependency install | fresh venv、lock install、pip check | exit 0、No broken requirements found. |
| Lock generation | TEMP tool venv、pip-tools==7.6.1、固定pip-compile | Python 3.14.3 version assert、`requirements-dev.in` input、`--generate-hashes`、明示output、`pip-tools (7.6.1)` |
| Dependency root set | requirements.in / requirements-dev.in / requirements.lock.txt | runtime root setがfastapi/pydantic/uvicornだけ、dev root setがPyYAML/httpx/mypy/pytest/ruff/types-PyYAMLだけ、余分なrootはFAIL |
| Dependency boundary | requirements.in / requirements-dev.in / requirements.lock.txt | runtime/dev分離、PyYAML 6.0.3はdev-only、openai 0件 |
| Build | python -m compileall -q src | exit 0 |
| Format | python -m ruff format --check src tests | 差分なし、exit 0 |
| Lint | python -m ruff check src tests | error 0 |
| Type | python -m mypy --strict src tests --exclude tests/typecheck_fixtures | error 0、Pydantic plugin、warn_unused_ignores |
| Negative type | negative fixture単独mypy | expected exit 1、arg-type/assert-type実出力 |
| Test | python -m pytest -q | 全test passed、API keyなし |
| Empty Application | 実entrypoint probe | HTTP 200、{"status":"ok"}、127.0.0.1 |
| Process lifecycle | entrypoint probe | --workers 1、CTRL_BREAK_EVENT相当、graceful exit code 0、PID終了、2回目health 200 / JSON、rebind、stdout/stderr empty。bind failure / timeoutはFAIL |
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

Pydantic bypass検索はnegative fixtureを除外する。negative fixture内のerror-code付きignoreだけ
は別証拠とする。

~~~powershell
rg -n "model_construct\(|\bcast\(|# type: ignore" src/neontof tests --glob "!tests/typecheck_fixtures/**"
rg -n "# type: ignore\[arg-type\]|assert_type" tests/typecheck_fixtures
~~~

OpenAI混入検索はADRを対象から外す。ADRにはPhase 1候補を記録するためである。

~~~powershell
$requirementsTxt = @(Get-ChildItem -LiteralPath . -File -Filter "requirements*.txt" | Select-Object -ExpandProperty FullName)
$openAiHits = @(rg -n "openai|^(from|import) openai" ($requirementsTxt + @("pyproject.toml", "src", "tests")) 2>$null)
if ($LASTEXITCODE -eq 0) { $openAiHits; throw "OpenAI content is forbidden in Phase 0" }
$forbiddenApiHits = @(rg -n "\b(Plugin|Hook|Profile|ProviderRegistry)\b|provider_registry" src tests 2>$null)
if ($LASTEXITCODE -eq 0) { $forbiddenApiHits; throw "Plugin/Hook/Profile/ProviderRegistry content is forbidden" }
$sqliteHits = @(rg -n "sqlite3\.connect|sqlite3\.Connection" src 2>$null)
if ($LASTEXITCODE -eq 0) { $sqliteHits; throw "Phase 0 must have zero sqlite3 connection source hits" }
$networkHits = @(rg -n "socket\.(socket|create_connection|create_server|getaddrinfo)|http\.client|urllib\.(request|parse)|requests\.|httpx\.(Client|AsyncClient)|urlopen" src 2>$null)
if ($LASTEXITCODE -eq 0) { $networkHits; throw "External socket/API source usage is forbidden" }
Write-Output "openai_import_network_plugin_sqlite_source=0"
~~~

内容検索は補助証拠であり、禁止pathの存在検査とallowed root manifestの集合差分を代替しない。

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
# First run the fixed TEMP pip-tools / pip-compile block in §8.5 without changing its
# Python 3.14.3, requirements-dev.in input, requirements.lock.txt output, or --generate-hashes.
py -3.14 --version
py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
py -3.14 -m venv .venv
$neontofPython = (Resolve-Path -LiteralPath ".venv/Scripts/python.exe").Path
& $neontofPython -c "import sys; assert sys.version_info[:3] == (3, 14, 3); print(sys.version)"
& $neontofPython -m pip install --require-hashes -r requirements.lock.txt
& $neontofPython -m pip check
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
& $neontofPython -m compileall -q src
& $neontofPython -m ruff format --check src tests
& $neontofPython -m ruff check src tests
& $neontofPython -m mypy --strict src tests --exclude "tests/typecheck_fixtures"
& $neontofPython -m pytest -q
& $neontofPython -m mypy --strict tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py
& $neontofPython -c "import sys; assert sys.version_info[:3] == (3, 14, 3)"
$requirementsTxt = @(Get-ChildItem -LiteralPath . -File -Filter "requirements*.txt" | Select-Object -ExpandProperty FullName)
$openAiHits = @(rg -n "openai|^(from|import) openai" ($requirementsTxt + @("pyproject.toml", "src", "tests")) 2>$null)
if ($openAiHits.Count -gt 0) { throw "OpenAI content found" }
$forbiddenApiHits = @(rg -n "\b(Plugin|Hook|Profile|ProviderRegistry)\b|provider_registry" src tests 2>$null)
if ($forbiddenApiHits.Count -gt 0) { throw "Forbidden extension content found" }
$sqliteHits = @(rg -n "sqlite3\.connect|sqlite3\.Connection" src 2>$null)
if ($sqliteHits.Count -gt 0) { throw "sqlite3 connection source found" }
$networkHits = @(rg -n "socket\.(socket|create_connection|create_server|getaddrinfo)|http\.client|urllib\.(request|parse)|requests\.|httpx\.(Client|AsyncClient)|urlopen" src 2>$null)
if ($networkHits.Count -gt 0) { throw "External network source found" }
rg -n "model_construct\(|\bcast\(|# type: ignore" src/neontof tests --glob "!tests/typecheck_fixtures/**"
# Run the Test-Path / Get-ChildItem forbidden-path and allowed-root-manifest block from §15.
# Run the §8.5 graceful entrypoint probe: CTRL_BREAK_EVENT, exit code 0, second health 200 / JSON,
# port rebind, and empty stdout/stderr; bind failure or timeout is FAIL.
git diff --check
git diff --numstat
git diff --ignore-cr-at-eol --numstat
git status --short --untracked-files=all
~~~

negative mypyだけはexpected exit 1なので通常qualityのexit 0とは別の証拠欄へ記録する。
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
