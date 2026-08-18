# Phase 0: Foundation Contracts 詳細 Implementation Plan

> **実行エージェント向け:** この計画の実行には `superpowers:subagent-driven-development` または
> `superpowers:executing-plans` を使い、Work Package ごとに Test First・レビュー・コミットを完結させる。
> 危険地帯を含むため全 Work Package を重量パスで扱う。

**Goal:** Event 履歴、セーブデータ、テスト、後続機能へ波及する最小契約と、API キーなしで反証可能な品質基盤を固定し、Phase 1 の実装を開始できる状態にする。

**期待する挙動変化:** 現在は計画文書しかない。Phase 0 完了時には、承認済み Stack ADR、起動可能な空 Application、CI とローカルで同じ Build/Test/Format/Lint/型チェック、実行可能な Domain・Semantic Result・Character Sheet・Scenario の契約テスト、Fake / Scripted / Recorded Fixture Provider が存在する。実 Scenario の Turn、Web UI、実 Provider 呼び出しはまだ存在しない。

**Architecture:** Event Log をゲーム状態の唯一の権威とし、State / Canon は Event から再構築する Projection とする。Semantic Result は Narrative と分離し、検証済みの canonical `proposed_events`（非Fact Event）と `proposed_facts`（`FactAsserted`）だけが将来の Turn Engine の append 経路へ進める。Phase 0 の実装は契約、純粋関数、テスト用 Provider、空 HTTP Application に限定し、Event Store、Turn Engine、Context Builder、実 Provider Adapter は Phase 1 に残す。

**暫定推奨 Stack:** P0-02 の比較・実測・ユーザー承認を条件に、TypeScript / Node.js、Fastify、SQLite、versioned SQL migration、Zod、Vitest、ESLint、Prettier、Vite + vanilla TypeScript、HTTP POST + SSE、公式 Provider SDK 一つを第一候補とする。これは承認済み決定ではない。

**上位仕様:** `docs/PRODUCT_PLAN.md` Draft v0.2、`docs/IMPLEMENTATION_ROADMAP.md` Draft v0.1、`docs/agent-guide/architecture.md`、`docs/agent-guide/build-and-verify.md`、`docs/agent-guide/coding-style.md`、`docs/agent-guide/technique-selection.md`

---

## 1. Phase 定義と承認境界

### 1.1 Goal

後から変更すると Event 互換性、保存データ、テスト、全機能へ波及する契約だけを決め、Phase 1 の Vertical Slice を迷わず実装できる最小の土台を作る。Phase 0 はフレームワークやゲーム機能を完成させる Phase ではない。

### 1.2 Non-goal

- 実際の Scenario を開始・進行・終了できる Turn Engine
- 完成した Web UI、Browser Client、Streaming UI
- 永続 Event Store、完成した State / Canon Projection
- 完全な Canon Ledger、Recall、日本語全文検索、Vector Database
- 実 Provider へのネットワーク呼び出しを CI 必須にすること
- Plugin、Hook、Profile、Manifest、Capability Graph
- 二つ目の実 Provider、二つ目の Ruleset、二つ目の Scenario 形式
- Provider / Ruleset / Scenario / Memory の汎用拡張 Interface
- 認証、Docker 配布、公開デプロイ、複数人、Scenario Editor、本格戦闘
- Phase 1 の Character / Scenario Loader、Model Gateway、Context Builder、Semantic Result Pipeline の先取り

### 1.3 Entry Conditions と実測状態

| 条件 | 2026-08-18 の実測 | 判定 |
|---|---|---|
| `docs/PRODUCT_PLAN.md` がある | Draft v0.2 を確認 | 満たす |
| `docs/IMPLEMENTATION_ROADMAP.md` がある | Draft v0.1 を確認 | 満たす |
| Git 運用方針がある | `AGENTS.md` に branch / commit / no-push 規律がある | 満たす |
| 作業 branch が Phase 専用 | `docs/phase-00-foundation` | 満たす |
| コード未着地 | `git ls-files` に実装・Build 設定なし | 満たす |

### 1.4 Phase Gate

次をすべて満たした場合だけ Phase 0 Gate を通過とする。

- Stack ADR がユーザー承認済みである。
- Core Domain / Event Spec、Semantic Result Spec、Character Sheet Spec、Scenario Format Spec がある。
- API キーなしで Build/Test/Format/Lint/型チェックが成功し、CI も同じコマンドを実行する。
- 空 Application が `127.0.0.1` で起動し、`GET /health` が `{"status":"ok"}` を返す。
- Fake Provider と Recorded Fixture のテストがネットワークなしで成功する。
- 同じ Event Sequence から同じ State / Fact Projection を再構築する最小テストが成功する。
- Narrative の文字列だけでは Event Sequence が変わらないテストが成功する。
- 受信・保存境界が `parseDomainEvent(input: unknown): DomainEvent` を通り、`event_version`、stable ID grammar、unknown field、unknown version、payload 不正を reject するテストが成功する。`rebuildProjection` へ型 cast した値を渡すだけのテストは Gate 証拠にしない。
- Evidence が Fact ID の存在・publication Visibility・構造化された predicate/value の一致を検証し、`unknown_evidence`、`invisible_evidence`、`evidence_claim_mismatch` を区別するテストが成功する。
- Scenario の `objective`、NPC `goal`、End Condition、その他の初期事実に必須 Visibility があり、欠落と `gm_only` の player 公開を reject するテストが成功する。
- Provider call log が sanitized entry だけを保持し、raw `ModelRequest`、任意 context、API key / secret field、sentinel が出力・log・Fixtureに現れないテストが成功する。
- Semantic Result の状態変更源が `proposed_events`（非Fact Eventのみ）と `proposed_facts`（`FactAsserted`の唯一の宣言源）に一意化され、重複 Proposal を reject し、materialize 時に二重 append しないテストが成功する。
- `TurnAwaitingPlayer`、`TurnResumed`、`TurnAborted` を含む Event から `projectTurnStatus(events: readonly DomainEvent[]): TurnStatus` を再構築し、再起動後も `awaiting_player` を維持するテストが成功する。
- Plugin、Hook、Profile、二つ目の実 Provider / Ruleset、Phase 1 UI が diff にない。
- `docs/status/phase-00-foundation.md` に Gate 結果、実コマンドと出力、Known Issues、Phase 1 Entry Conditions、Playtest 非該当理由が記録されている。
- Gate 通過後も Phase 1 へ自動的に進まず、ユーザー判断を待つ。

### 1.5 Stop Conditions

次のいずれかを検出したら新機能を足さず、該当 Work Package を停止して計画・契約を縮小する。

- Spec が最小 Fixture と契約テストで使わない型を増やし始めた。
- 二つ目の実装を想定した class hierarchy、Plugin、Hook、Manifest、Capability Graph が現れた。
- P0-02 の候補で共通 probe の一つでも non-zero になった場合、その候補を明示的に reject する。全候補が reject された場合、または D（何もしない／今は決めない）が選ばれた場合は、`P0-02 STOP: P0-01b Gateに必要なBuild / Format / Lint / Typecheck / Test、health endpoint、CI parityを実行可能なStackがないためPhase 0を通過できない` と記録し、P0-01b・P0-03・Phase 1を開始しない。
- P0-03〜P0-07 が Event Store、Turn Engine、実 Provider、Browser UI を実装し始めた。
- State / Canon を直接更新する API、Narrative を parse して Event を作る関数、公開向け Context へ秘密を混ぜる経路が提案された。
- `docs/PRODUCT_PLAN.md` または `docs/IMPLEMENTATION_ROADMAP.md` の改訂が必要になった。上位文書改訂を先にユーザーへ提案する。
- 同一手法が 2 回失敗した。3 回目を試さず、コマンドと出力を返す。
- 1 週間相当の作業後も、Fake Provider の一応答を Semantic Result として検証し、最小 Event Sequence を Projection へ適用する契約テストを通せない。

### 1.6 二つのユーザー承認

1. **承認 A — この計画:** 計画一次レビューと非メイン側 AI の独立二次レビュー後にユーザー承認を待つ。承認前に ADR 本文、実装、Fixture を作らない。承認 A 後は、Stackに依存しない P0-01a（Repository baseline）から開始する。
2. **承認 B — P0-02 技術スタック:** P0-01a の独立Commit後に、`docs/status/p0-02-technology-stack-evaluation.md` だけを成果物として候補比較・外部調査・一時ディレクトリのスパイクを行う。ADR 本文と Stack 依存コードは書かず、推奨案を提示してユーザー承認を待つ。承認 B 後に `docs/adr/0001-technology-stack.md` を確定し、P0-01b（Stack依存 Quality baseline）を完了する。

承認 B で暫定推奨 Stack 以外が選ばれた場合、この文書の TypeScript 固有パス・Signature・コマンドは実行せず、選択された Stack 用の P0-01b 以降の正確な差分計画を同じファイルへ反映して計画レビューを通す。P0-01a の baseline はそのまま利用し、技術選択を暗黙に読み替えない。Stack依存部分を承認後へ分割することは、追加のユーザー判断を要求する停止点ではなく、この実行手順で解消する依存である。

---

## 2. 中核不変条件

全 Work Package、Test、レビューで次を再確認する。

1. Event Log がゲーム状態の唯一の権威である。State / Canon は Event から再構築可能な Projection であり、直接更新する公開 API を作らない。
2. Semantic Result と Narrative を分離する。自由文を parse して状態へ反映しない。Structured Result を Schema と文脈で検証してから Event へ変換する。
3. Entity は安定 ID を主キーとし、名前・Alias・表示名を主キーにしない。
4. Visibility は `gm_only` / `player_visible` / NPC Entity ID の最小集合を持つ。公開向け呼び出しへ不可視情報を渡さない。
5. API キーを Browser、通常ログ、Prompt、Fixture、Transcript へ渡さない。秘密は「渡さない」ことで守る。
6. 非信頼テキストを読む Role へ状態変更 Tool を渡さない。Validator へ検証対象外の非信頼指示を渡さない。
7. Turn は `pending` / `running` / `awaiting_player` / `committed` / `aborted` を表現する。`awaiting_player` は同一 Turn を再開する状態であり、statusの権威は`TurnAwaitingPlayer` / `TurnResumed` / `TurnAborted`を含むEvent列と `projectTurnStatus` にある。runtime変数、Transcript、Telemetryを権威にしない。
8. Event append は単一トランザクション境界で行う。Transcript / Telemetry はその外へ append し、失敗 Turn の記録と消費済み費用を消さない。
9. Undo は Event 削除ではなく `TurnReverted` append で表現する。
10. Dice Seed は `H(campaign_seed, turn_id, action_id, roll_index)` から導出し、材料と結果を記録する。Phase 0 は式と Contract Fixture を固定し、Dice Runtime は作らない。
11. 実 Provider なし・API キーなしで必須テストを実行する。実 Provider テストは CI 必須条件にしない。
12. 二つ目の具体実装がない Interface を一般化しない。P0-07 の `ModelInvoker` は実 Provider 抽象基盤ではなく、Fake / Scripted Fixture を Turn 契約へ注入する単一関数境界に限定する。

---

## 3. Scope と書き込み境界

### 3.1 この計画作成ターン

**許可:** `docs/plans/phase-00-foundation.md`

**禁止:** 上記以外の全ファイル。特に `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/adr/**`、`docs/specs/**`、実装コード、MyWorkflow 正本は編集しない。

### 3.2 承認後の Phase 0 実行

**NeontoF リポジトリ内で許可するパス:**

- `.gitattributes`
- `.gitignore`
- `.env.example`
- `.node-version`
- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `tsconfig.build.json`
- `eslint.config.mjs`
- `prettier.config.mjs`
- `vitest.config.ts`
- `.github/workflows/ci.yml`
- `src/app.ts`
- `src/config.ts`
- `src/main.ts`
- `src/contracts/**`
- `src/model/**`
- `tests/**`
- `docs/adr/0001-technology-stack.md`
- `docs/specs/core-domain-and-events.md`
- `docs/specs/semantic-result.md`
- `docs/specs/character-sheet.md`
- `docs/specs/scenario-format.md`
- `docs/specs/test-provider-and-fixtures.md`
- `docs/status/p0-02-technology-stack-evaluation.md`
- `docs/status/phase-00-foundation.md`
- P0-02のthrowaway probeは `$env:TEMP` 配下の一意な一時directoryだけを使い、Repository内にspike pathを作らない。probeの一時生成物はcommitしない。

**MyWorkflow 正本で許可するパス:**

- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/architecture.md`
- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/coding-style.md`
- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/build-and-verify.md`

MyWorkflow は別 Repository であり、`main` へ直接 commit しない。`docs/neontof-phase-00-guides` branch を作り、上の 3 ファイルだけを明示 stage して commit する。レビュー後にローカル `main` へ merge し、`node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs --apply NeontoF` で展開する。展開先 `docs/agent-guide/**` は直接編集も git 追跡も禁止する。

### 3.3 禁止パスと禁止成果物

- `docs/PRODUCT_PLAN.md`、`docs/IMPLEMENTATION_ROADMAP.md`
- `README.md`、`LICENSE`
- `AGENTS.md`、`CLAUDE.md`、`.claude/**`、`.codex/**`、`.harness/**`
- 展開先 `docs/agent-guide/**` の直接編集
- `src/client/**`、UI asset、Browser Integration 実装
- 実 Provider Adapter、二つ目の Provider / Ruleset / Scenario 形式
- Plugin / Hook / Profile / Manifest / Capability Graph 用ファイル
- `.env`、実 API キー、匿名化前の実 Provider Response
- `*.sqlite`、`*.db`、Event / Transcript / Telemetry の実データ、`dist/**`、`node_modules/**`、Playtest 生ログ

`docs/adr`、`docs/specs`、`docs/status` は実ファイル作成によって成立させる。空 directory を追跡するための `.gitkeep` は作らない。

---

## 4. 実装方針

### 4.1 Ownership と寿命

- Phase 0 の Event / Projection コードは副作用を持たない純粋な Contract 実装とする。永続 Event Store の所有権は Phase 1 で Turn Engine の append 経路へ与える。
- `TranscriptEntry` と `TelemetryEntry` は `DomainEvent` union に含めず、Projection reducer の入力型にも含めない。これでゲーム状態トランザクションとの混同を型とテストで防ぐ。
- Fake / Scripted Provider の script cursor と call log は Provider instance が所有する。global singleton にせず、各 Test が instance を作り破棄する。
- Fixture は versioned・sanitized・API キーなしとし、同じ入力から同じ出力を返す。実応答を取得する機能は Phase 0 に置かない。
- Character Sheet / Scenario は初期入力であり、Campaign 開始時に Event へ正規化される前提を Spec に記す。元ファイルを Event Log の代わりの権威にしない。

### 4.2 Dependency direction

```text
src/app.ts, src/config.ts, src/main.ts
    └─ HTTP framework only; Domain/Game codeを参照しない

src/contracts/semantic-result.ts
    └─ src/contracts/domain.ts の EventType / ID / Visibility を参照。型と構造Schemaだけ

src/contracts/character-sheet.ts
src/contracts/scenario.ts
    └─ src/contracts/domain.ts の stable ID / Visibility だけを参照

src/model/model-invoker.ts
    └─ src/contracts/semantic-result.ts の provider-neutral payload type を参照

src/model/fake-provider.ts
src/model/scripted-provider.ts
src/model/recorded-fixture.ts
    └─ src/model/model-invoker.ts を参照

tests/** → src/**
tests/contracts/support/** は参照oracleを所有し、productionから参照しない
src/** から tests/** を参照しない
```

Model output から State への依存矢印は作らない。`validateSemanticResult()` の成功値から取得した `proposed_events` も Proposal であり、Phase 1 の Turn Engine が Domain Rule と現在 State を検証して Event envelope を付けるまで権威を持たない。

### 4.3 Threading / concurrency

- Stack ADR に Node.js event loop、HTTP request concurrency、SQLite writer serialization の前提を記録する。
- Phase 0 では共有可変ゲーム状態、worker thread、background queue、同時 Event append を実装しない。
- Projection reducer と Validator は同じ入力へ同じ結果を返す純粋関数とし、時刻・global random・process-global cache を参照しない。
- Scripted Provider は 1 instance を 1 Test / 1 Turn 用に使う。並列 Test は別 instance を使い、call order を共有しない。
- 将来の同一 Turn Request ID の同時再送は Domain Spec に不変条件として固定するが、lock / transaction 実装は Phase 1 に残す。

### 4.4 Compatibility / migration

- Event は `event_version`、Semantic Result は `schema_version`、Character Sheet は `schema_version`、Scenario は `schema_version` と `version`、Recorded Fixture は `fixture_version` を持つ。
- Phase 0 は version `1` だけを受理し、未知 version を暗黙変換しない。
- Event ID から Fact ID を決定論的に導出する。ID generation algorithm は Event envelope の互換契約から分離し、opaque token として扱う。
- ADR は versioned SQL migration を選ぶが、Database schema と migration runner は Phase 1 の P1-01 まで作らない。
- Phase 0 には永続セーブデータがないため、契約を撤回する場合は Work Package commit を逆順に `git revert` する。履歴を書き換える `git reset --hard` は使わない。

---

## 5. 判断境界

### 5.1 後戻りが高くつくため Phase 0 で決める判断

| 判断 | Phase 0 で固定する範囲 | 固定しすぎない境界 |
|---|---|---|
| Stack | Server Runtime、HTTP方式、Client方式、Database、Migration、Validation、実 Provider 一つ、Fake方式、Streaming fallback | Phase 5 前に Provider Plugin APIを作らない |
| Event | envelope、version、stable ID、順序、origin、最低限の Event type、Fact ID導出、rebuild規則 | Database table、完全な payload、全 Ruleset Event を固定しない |
| Projection | Event だけを入力にする純粋な `rebuildProjection()` 契約 | 完成 Canon Ledger、Search Indexを作らない |
| Turn | status集合、request ID冪等性、単一 Event transaction、`TurnReverted` | state machine / lock / retry runtimeを作らない |
| Semantic Result | field、Authority、pre-publication validation、post-publication check、Narrative非権威 | PromptやNarration Styleを固定しない |
| Visibility / Secret | 最小 visibility、Contextへ不可視情報を渡さない、APIキー非公開 | Participant単位Visibilityを作らない |
| Authoring format | Character / Scenario の手書き一形式と version | Editor、万能Schema、Graph DSLを作らない |
| Test Provider | narrow function boundary、script、recorded fixture、sanitization、call log | 実 Provider capability matrixを作らない |

### 5.2 後回しにすべき判断

- Event Store の table / index / repository class と transaction 実装
- State / Canon Projection の全 field と性能最適化
- Turn Engine の retry、idempotency lock、`awaiting_player` resume 実装
- 実 Provider SDK の request mapping、Prompt Cache、Tool Calling、課金換算
- SSE の本番 endpoint、WebSocket、Browser rendering
- Character / Scenario から Event Sequence への完全 mapping
- 日本語 FTS / N-gram の実装と benchmark
- Search、Summary、Embedding、Vector Database
- Participant、Room、Auth、Docker、Backup、公開運用
- Plugin、Hook、Profile、二つ目の Provider / Ruleset / Scenario 形式

---

## 6. Work Package 依存関係と並列化

承認 A 後は、まず Stack 非依存の P0-01a を開始する。P0-01 全体を Stack 未決のまま完了できるという前提は置かない。P0-01a で Repository の共通境界だけを独立Commitにし、その後 P0-02a で候補比較・スパイクを行い、承認 B 後に P0-01b の Stack 依存 Quality baseline（package/config/runner、実コマンド、空 Application、CI）を完了する。この分割で、P0-01 の実コマンド・言語固有 Signature・空 ApplicationがStack承認後になる依存を隠さず、ユーザー判断を追加要求する停止点にもせずに処理する。

```text
承認 A
  ↓
P0-01a Stack非依存 Repository baseline
  ↓
P0-02a 候補調査・比較・スパイク・評価報告（ADR本文なし）
  ↓
承認 B
  ↓
P0-02b ADR確定 + MyWorkflow architecture/coding-style正本更新
  ↓
P0-01b 承認Stack依存 Quality baseline + build-and-verify正本更新
  ↓
P0-03 Core Domain / Event Contract
  ├────────────┬────────────┐
  ↓            ↓            ↓
P0-04        P0-05        P0-06       ← 互いに素な書き込みパスで1 batch並列
  ↓
P0-07                              ← P0-04 commit後に開始可
  └────────────┴────────────┘
                ↓
統合シーム監査・Phase Gate・Status Report
```

| Package | 直列依存 | 並列可否 |
|---|---|---|
| P0-01a | 承認 A | P0-02aより先。Stack非依存部分だけを単独 |
| P0-02a | P0-01a | 候補比較・外部調査・一時ディレクトリのprobe。単独 |
| P0-02b | 承認 B | 単独。ADR commit後にP0-01b |
| P0-01b | P0-02b | 共通 Build 設定とStack依存品質設定を所有するため単独 |
| P0-03 | P0-01b | 共通 ID / Event / Visibility を所有するため単独 |
| P0-04 | P0-03 | P0-05 / P0-06 と並列可 |
| P0-05 | P0-03 | P0-04 / P0-06 と並列可 |
| P0-06 | P0-03 | P0-04 / P0-05 と並列可 |
| P0-07 | P0-04 | P0-05 / P0-06 のレビューと並列可 |

P0-01a、P0-02a、P0-02b、P0-01bはこの順序で直列に着地させる。P0-03以降の並列 bundle の各 implementer は共通設定ファイルを変更しない。依存する後続を開始する前に、依存元 diff を一次レビュー、非メイン側 AI 二次レビュー、検証、commit まで着地させる。全 diff 統合後に、重複・Signature衝突・versionずれ・合成退行だけを見るシーム監査を 1 回行う。

---

## 7. P0-02: Technology Stack ADR

### 7.1 Goal、決定境界、Non-goal

**Goal:** Phase 1 と承認後の P0-01b が一つの実行可能な Stack で進められるよう、比較根拠・実測・不採用理由・再評価条件を残し、ユーザー承認後に ADR を確定する。

**決定する:** Server Runtime / language、HTTP framework、Client方式、Database、Migration、Validation、実 Provider 一つ、Fake方式、HTTP POST + SSE / WebSocket / buffered HTTP、将来の日本語検索経路、Docker化経路。

**Non-goal:** 複数 Provider Adapter、Plugin API、Database schema、Browser UI、実 Provider への本番 Prompt、検索実装、Dockerfile。

### 7.2 候補と暫定推奨

この表は調査開始時の仮説であり、根拠等級を明記する。P0-02a で公式一次資料 URL と実コマンド出力へ置き換え、等級なしの主張を評価報告へ入れない。

| 候補 | 構成 | 根拠 | 主な懸念 | 初期判定 |
|---|---|---|---|---|
| A: TypeScript 一系統 | Node.js supported LTS / TypeScript / Fastify / Vite + vanilla TypeScript / SQLite / versioned SQL / Zod / Vitest / SSE + buffered fallback | 【実測】現環境で Node `v26.3.0` と npm `11.16.0` が起動する。【推測】Serverと将来Clientで型・toolchainを共有でき、一人保守とFixture作成が単純になる | 【推測】SQLite driver、Structured Output、SSE中断時の挙動を実測する必要がある | **暫定推奨** |
| B: Python Server | Python / FastAPI / Pydantic / Vite + vanilla TypeScript / SQLite / pytest / SSE + buffered fallback | 【実測】現環境で Python `3.14.3` が起動する。【推測】Schema Validation と test fixture の記述性が高い | 【推測】ServerとClientで二つの言語・formatter・dependency graphを保守する | 強い比較対象 |
| C: Go Server | Go / `net/http` / Vite + vanilla TypeScript / SQLite / strict JSON decoder + field validator / SSE + buffered fallback | 【実測】現環境で Go `1.26.4` が起動する。【推測】単一 binary と明示的な並行性に利点がある | 【推測】LLM SDK と深い構造化 Validation の glue code が A/B より増える | 必須probeの比較対象 |
| D: 何もしない／今は決めない | 計画文書のまま Stack を保留する | 【実測】コード未着地なので短期の変更費用はゼロ | 【実測】P0-01b の実 Build/Test と空 Application を定義できず、Phase 0 Gate を通過できない | 不採用を推奨 |

候補 A の内部選択も評価報告で比較する。

| 項目 | 暫定推奨 | 比較対象と暫定理由 |
|---|---|---|
| Package manager | npm + `package-lock.json` | 【実測】現環境でnpmが起動する。【推測】別package managerを増やす利点がPhase 0にはない |
| SQLite access | supported LTS上でstableならbuilt-in `node:sqlite` | 【推測】native addon dependencyを減らせる。transaction / migration API不足なら`better-sqlite3`を採用する |
| Provider | OpenAI公式SDK | 【推測】strict structured output probeを最優先する。Anthropic公式SDKとFake-onlyを比較し、Schema・usage・timeoutの必須probeを通らなければ不採用にする |
| Transport | HTTP POST + SSE + buffered HTTP fallback | 【推測】Phase 1はServer→Browser進捗が主用途。WebSocketは双方向同時messageの実例がないため不採用候補 |
| Client | Vite + vanilla TypeScript | 【推測】Phase 1の画面要件だけならReact / Router / Design Systemの保守面を増やさずに済む |
| 日本語検索経路 | SQLite FTS tokenizerまたはapplication-managed N-gram | 【推測】Phase 0は実装せず、公式資料と日本語FixtureでPhase 3への到達経路だけを確認する |
| Docker経路 | Node runtime + locked install + single SQLite volume | 【推測】Phase 4でcontainer化できる構成だけを確認し、Dockerfileは作らない |

ADRには次の具体的な再評価トリガーをそのまま記録する。

- 選択したRuntime、HTTP framework、Validation library、SQLite driver、Provider SDKのいずれかがsecurity fixのあるsupported releaseを失い、30日以内に互換upgradeを通せない。
- dependency update後に、P0-02のSQLite rollback probe、unknown-field rejection、API key sentinel testのいずれかが再現可能にFAILする。
- 選択Providerがstrict structured output、usage metadata、timeoutのいずれかを廃止し、同じSemantic Result契約を一回のpublic Fast Pathで満たせない。
- Phase 1の実測でBrowserからServerへの同時双方向messageが必須になり、HTTP POST + SSEではTurnの`awaiting_player`再開を表現できない事例が2件以上記録される。
- Phase 3 Entry Conditionsを満たした時点で、選択Databaseから日本語N-gram / 形態素解析へ進む公式にsupportされた経路がなく、合成日本語Fixtureを検索できない。
- fresh Windows hostと将来のcontainer base imageのどちらかでlocked dependencyのclean installが2回連続して再現不能になる。

### 7.3 ファイルと責務

**P0-02a で Create:**

- `docs/status/p0-02-technology-stack-evaluation.md` — 課題、制約、候補、証拠等級付き比較、スパイク出力、Codex調査とClaude裏取りの一致・不一致、推奨、不採用理由、再評価トリガー、承認依頼を記録する。ADRではない。
- 候補 A/B/C の throwaway probe — すべて `$env:TEMP` 配下の一意な一時ディレクトリへ作成し、Repositoryには作らない。`node_modules`、`.venv`、Go module cache、probeのFixtureをRepositoryへ置かない。

**承認 B 後に Create:**

- `docs/adr/0001-technology-stack.md` — `Accepted`、ユーザー承認発言の引用、採用 Stack、各不採用理由、再評価トリガーを記録する。

**承認 B 後に Modify（MyWorkflow 正本）:**

- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/architecture.md` — 実際の path、依存方向、Node event loop / SQLite writer前提を反映する。
- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/coding-style.md` — TypeScript strict、ES module、import、Zod schema、formatter/linter、test namingを反映する。

### 7.4 外部調査、独立裏取り、1日スパイク

1. Codex researcher が候補 A/B/C、SQLite driver、Validation、Provider、SSE、日本語検索経路について、公式 documentation、公式 repository、標準仕様だけを調査する。各主張へ URL とアクセス日を付ける。blog 二次情報だけで load-bearing な結論を出さない。
2. Codex が候補 A、B、C の throwaway spike をそれぞれ別の `$env:TEMP` directory で実行する。上限は 1 developer-day（8時間）で、評価報告へ費やした時間と未完 probe を記録する。各候補の最初のREDは、依存導入後に package/config/fixture と test script を作成してから実行し、runner自体が起動したうえで最小実装の不在を理由にFAILすることを確認する。
3. Claude が Codex の結論を渡されない clean context で同じ選定基準を独立調査する。実行コマンド:

   ```powershell
   claude -p "NeontoF Phase 0 の技術スタックを独立に評価せよ。AGENTS.md、docs/PRODUCT_PLAN.md、docs/IMPLEMENTATION_ROADMAP.md、docs/agent-guide/architecture.md、docs/agent-guide/technique-selection.md を読み、TypeScript/Node、Python/FastAPI、Go/net-http、何もしない案を比較する。Event Log 単一権威、強いStructured Validation、SQLite単一transaction、Fake Provider、HTTP/SSE fallback、日本語検索経路、秘密非公開、単独保守を観点に、公式一次資料URL付きで推奨1案・不採用理由・再評価トリガーを日本語で返せ。" --model opus --permission-mode plan
   ```

4. Codex と Claude の一致点・不一致点を評価報告へ並記する。助言を決定として扱わず、ユーザーが承認する。

**スパイクの必須 probe と判定基準:**

| Probe | PASS | FAIL |
|---|---|---|
| clean setup | lockされた依存で再installできる | 手修正したglobal環境が必須 |
| quality commands | Build/Test/Format/Lint/型チェックが個別に失敗を検出する | commandが空成功する、またはWindowsで再現しない |
| health server | `127.0.0.1` の `/health` がJSONを返す | public bindが既定、またはshutdown不能 |
| SQLite transaction | 2 insertの途中で故意に例外を起こし、row countが0 | 部分rowが残る |
| projection determinism | 同じEvent配列を2回reduceしてdeep equal | 時刻・global stateで差が出る |
| structured validation | unknown event、不可視Evidence、invalid JSONをfield path付きで拒否 | Narrative parseまたは曖昧coercionが必要 |
| Fake / retry | success→error→timeoutのscriptとcall countがAPIキーなしで再現 | networkまたは課金が必須 |
| transport fallback | structured部の検証完了前にNarrativeを公開せず、SSEなしでも完了Responseを返せる | streamingが正しさの前提になる |
| secret probe | sentinel secretがresponse/log/fixtureに現れない | 1箇所でも現れる |
| Japanese path | 公式資料で日本語N-gram/形態素解析へ進める具体経路を示せる | 英語空白tokenize以外の経路がない |

各候補の probe は同じ入力Fixtureと同じ判定を使う。共通probeの全項目（health、strict schema validation、SQLite rollback、Fake Provider、streaming fallback、secret probe、projection determinism、quality commands）が exit code `0` でPASSし、出力が期待値と一致した場合だけ候補を採用可能とする。一つでもFAILした候補は、失敗したprobe名、実コマンド、exit code、stderrを評価報告へ記録して明示的にrejectする。候補A/B/Cのすべてがrejectされた場合は、Dと同じくP0-02を停止し、P0-01b Gateを満たすStackがないことを記録する。「どれかがFAILしても他がPASSなら成功」とは判定しない。

### 7.5 候補スパイクの再現可能な手順、Test First と期待結果

候補ごとの最初のREDは、依存導入後、package/config/fixture と test script を作成した後に実行する。`npm run`をscripts未定義のまま呼ばない。以下の全pathは `$env:TEMP` 配下であり、Repositoryへ `node_modules` / `.venv` / Go生成物を作らない。

#### 候補 A: TypeScript / Node

```powershell
$neontofTsSpike = Join-Path $env:TEMP "neontof-p0-02-ts-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $neontofTsSpike -Force | Out-Null
$neontofTsResolved = (Resolve-Path -LiteralPath $neontofTsSpike).Path
if (-not $neontofTsResolved.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Spike is outside TEMP' }
Set-Location -LiteralPath $neontofTsSpike
npm init -y --yes
npm install --no-audit --no-fund fastify zod better-sqlite3
npm install --save-dev --no-audit --no-fund typescript tsx vitest eslint @eslint/js typescript-eslint prettier @types/node @types/better-sqlite3
@'
import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts", "tests/**/*.ts"],
  },
);
'@ | Set-Content -LiteralPath eslint.config.mjs -Encoding utf8NoBOM
npm pkg set type=module
npm pkg set scripts.build='tsc -p tsconfig.build.json'
npm pkg set scripts.format='prettier --write "src/**/*.{ts,json}" "tests/**/*.{ts,json}" "*.{json,mjs,ts}"'
npm pkg set scripts.format:check='prettier --check "src/**/*.{ts,json}" "tests/**/*.{ts,json}" "*.{json,mjs,ts}"'
npm pkg set scripts.lint='eslint src tests'
npm pkg set scripts.typecheck='tsc -p tsconfig.json --noEmit'
npm pkg set scripts.test='vitest run'
New-Item -ItemType Directory -Path src, tests, tests/fixtures -Force | Out-Null
@'
{"schema_version":1,"action":"probe","value":7}
'@ | Set-Content -LiteralPath tests/fixtures/probe-input.json -Encoding utf8NoBOM
@'
{"compilerOptions":{"strict":true,"target":"ES2022","module":"NodeNext","moduleResolution":"NodeNext","noEmit":true},"include":["src","tests","vitest.config.ts"]}
'@ | Set-Content -LiteralPath tsconfig.json -Encoding utf8NoBOM
@'
{"extends":"./tsconfig.json","compilerOptions":{"noEmit":false,"outDir":"dist"},"include":["src"]}
'@ | Set-Content -LiteralPath tsconfig.build.json -Encoding utf8NoBOM
@'
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["tests/**/*.test.ts"] } });
'@ | Set-Content -LiteralPath vitest.config.ts -Encoding utf8NoBOM
@'
import { describe, expect, it } from "vitest";
import { buildApp } from "../src/probe.js";
describe("probe bootstrap", () => {
  it("loads the app contract", () => expect(buildApp()).toBeDefined());
});
'@ | Set-Content -LiteralPath tests/probe.test.ts -Encoding utf8NoBOM
npm ci --no-audit --no-fund
$env:npm_config_yes = 'true'
npm create vite@latest client -- --template vanilla-ts --yes
npm --prefix client install --no-audit --no-fund
Remove-Item Env:npm_config_yes -ErrorAction SilentlyContinue
```

上のsetup commandはすべてexit code `0`を期待する。`npm init`、依存install、`npm ci`、package/config/Fixture作成、非対話Vite作成のいずれかがnon-zeroなら候補Aをそのcommandのstderrとともにrejectする。

`npm run lint` は上で作成した `eslint.config.mjs` の flat config（`src/**/*.ts` と `tests/**/*.ts`）を前提とし、対象TypeScriptのerror `0`を期待する。設定ファイルがない、またはlintがnon-zeroなら候補Aをrejectする。

`tests/probe.test.ts` は `src/probe.ts` の `buildApp()`、`parseProbeInput()`、`runRollbackProbe()`、`createFakeProvider()`、`reduceProjection()`、`requestBufferedOrStreamed()`をimportする。`src/probe.ts` は `GET /health` が `{ "status": "ok" }` を返すFastify app、Zod `.strict()`によるunknown field reject、`better-sqlite3`のtransaction内でinsert後にthrowしてrow count `0`、Provider関数のFake差し替え、同じEvent列を2回reduceしてdeep equalになるProjection、structured resultを全検証してからSSEまたはbuffered JSONを返すfallbackを実装する。`GET /probe/result` はstreamingを使えない指定でも同じ検証済みJSONを返し、未検証Narrativeを先に送らない。`tests/fixtures/probe-input.json`を使い、sentinelはFixtureへ書かずtestのメモリ上だけに置く。

```powershell
npm test -- tests/probe.test.ts
# 期待FAIL: Vitest runnerは起動し、`Failed to load url ../src/probe` または `Cannot find module` を表示してexit code 1。npm script未定義によるFAILではない。

npm run format:check
npm run lint
npm run typecheck
npm test -- tests/probe.test.ts
npm run build
# 実装後の期待PASS: 上記5 commandがすべてexit code 0、Vitestの全test passed、rollback row count=0、health JSON一致、fallback body一致。
```

`npm run format:check`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`のいずれかがFAILした場合は候補Aをrejectする。`npm test`をpackage.jsonやVitest設定より先に実行する手順は採用しない。

#### 候補 B: Python / FastAPI

```powershell
$neontofPythonSpike = Join-Path $env:TEMP "neontof-p0-02-python-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $neontofPythonSpike -Force | Out-Null
$neontofPythonResolved = (Resolve-Path -LiteralPath $neontofPythonSpike).Path
if (-not $neontofPythonResolved.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Spike is outside TEMP' }
Set-Location -LiteralPath $neontofPythonSpike
py -m venv (Join-Path $neontofPythonSpike '.venv')
$neontofPython = Join-Path $neontofPythonSpike '.venv\Scripts\python.exe'
& $neontofPython -m pip install --upgrade pip
& $neontofPython -m pip install fastapi uvicorn pydantic pytest httpx ruff mypy
& $neontofPython -m pip freeze | Sort-Object | Set-Content -LiteralPath requirements.lock.txt -Encoding utf8NoBOM
$neontofPythonFreshSpike = Join-Path $env:TEMP "neontof-p0-02-python-fresh-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $neontofPythonFreshSpike -Force | Out-Null
$neontofPythonFreshResolved = (Resolve-Path -LiteralPath $neontofPythonFreshSpike).Path
if (-not $neontofPythonFreshResolved.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Fresh spike is outside TEMP' }
py -m venv (Join-Path $neontofPythonFreshSpike '.venv')
$neontofPythonFresh = Join-Path $neontofPythonFreshSpike '.venv\Scripts\python.exe'
& $neontofPythonFresh -m pip install -r (Join-Path $neontofPythonSpike 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Fresh venv lock install failed' }
New-Item -ItemType Directory -Path src, tests, tests/fixtures -Force | Out-Null
@'
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
[tool.ruff]
line-length = 100
[tool.ruff.format]
quote-style = "double"
'@ | Set-Content -LiteralPath pyproject.toml -Encoding utf8NoBOM
@'
{"schema_version":1,"action":"probe","value":7}
'@ | Set-Content -LiteralPath tests/fixtures/probe-input.json -Encoding utf8NoBOM
@'
from fastapi.testclient import TestClient
from probe_app import app
def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}
'@ | Set-Content -LiteralPath tests/probe_test.py -Encoding utf8NoBOM
```

`src/probe_app.py` は `FastAPI()`、`GET /health`、`ProbeInput(BaseModel)`（`ConfigDict(extra="forbid")`）、`sqlite3` transaction rollback、`Protocol`によるFake Provider、同じEvent列を2回reduceしてdeep equalになるProjection、`/probe/result` のStreamingResponse/buffered JSON fallbackを持つ。`tests/probe_test.py` はhealth、unknown field reject、insert後rollback row count `0`、Fake応答、Projection同値、stream/buffer同値、検証前Narrative非送信、sentinelのoutput/log/Fixture不在を検証する。`ProbeInput.model_validate`は未知fieldをrejectする。Python候補でVite clientを確認する場合は、同じ一時directory内で次を実行する。

```powershell
$env:npm_config_yes = 'true'
npm create vite@latest client -- --template vanilla-ts --yes
npm --prefix client install --no-audit --no-fund
Remove-Item Env:npm_config_yes -ErrorAction SilentlyContinue
```

上のsetup commandはすべてexit code `0`を期待する。既存venvとは別のfresh venv作成、生成した`requirements.lock.txt`からの通常の`pip install -r`、依存install、lock生成、package/config/Fixture作成、非対話Vite作成のいずれかがnon-zeroなら候補Bをそのcommandのstderrとともにrejectする。`--no-deps`だけでは依存解決が不足するため使用しない。

```powershell
& $neontofPythonFresh -m pytest tests/probe_test.py -q
# 期待RED: pytest runnerは起動し、未実装のrollback/Fake/stream probe assertionまたはimport不足でexit code 1。pytest未導入によるFAILではない。

& $neontofPythonFresh -m compileall -q src
& $neontofPythonFresh -m ruff format --check src tests
& $neontofPythonFresh -m ruff check src tests
& $neontofPythonFresh -m mypy src
& $neontofPythonFresh -m pytest tests -q
# 実装後の期待PASS: fresh lock venvのcompileall、format check、ruff、mypy、pytestがすべてexit code 0。health JSON、strict schema reject、rollback row count=0、Fake応答、stream/buffer同値がPASS。
```

Pythonでは `compileall`をbuild、`ruff format --check`をformat、`ruff check`をlint、`mypy`をtypecheck、`pytest`をtestとして固定する。候補Bの採用条件は、fresh lock venvの通常のlock installと、その同じfresh interpreterでのcompileall、format check、ruff、mypy、pytestの全PASSであり、いずれかがFAILした場合は候補Bをrejectする。

#### 候補 C: Go / net-http

```powershell
$neontofGoSpike = Join-Path $env:TEMP "neontof-p0-02-go-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $neontofGoSpike -Force | Out-Null
$neontofGoResolved = (Resolve-Path -LiteralPath $neontofGoSpike).Path
if (-not $neontofGoResolved.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Spike is outside TEMP' }
Set-Location -LiteralPath $neontofGoSpike
go mod init example.com/neontof-p0-02-go
go get github.com/go-playground/validator/v10 modernc.org/sqlite
go mod tidy
New-Item -ItemType Directory -Path cmd/probe, internal/probe, tests/fixtures -Force | Out-Null
@'
{"schema_version":1,"action":"probe","value":7}
'@ | Set-Content -LiteralPath tests/fixtures/probe-input.json -Encoding utf8NoBOM
@'
package probe
import "testing"
func TestProbeBootstrap(t *testing.T) {
    _ = BuildHandler()
}
'@ | Set-Content -LiteralPath internal/probe/probe_test.go -Encoding utf8NoBOM
```

上のsetup commandはすべてexit code `0`を期待する。module初期化、依存取得、`go mod tidy`、Fixture/test作成のいずれかがnon-zeroなら候補Cをそのcommandのstderrとともにrejectする。

`internal/probe`に `BuildHandler() http.Handler`、`ParseProbeInput([]byte) (ProbeInput, error)`、`RunRollbackProbe() (int, error)`、`FakeInvoker`、`ReduceProjection`、`RequestBufferedOrStreamed`を作る。`net/http`の `/health` はJSON `{ "status": "ok" }`、JSON decoderの `DisallowUnknownFields` とvalidator tagでunknown field/invalid valueをreject、`database/sql` + `modernc.org/sqlite`のtransactionでinsert後にrollbackしてrow count `0`、`ModelInvoker func(context.Context, ModelRequest) (ModelResponse, error)`をFakeへ差し替え、同じEvent列を2回reduceしてdeep equalになるProjection、`httptest`でSSEが使えない場合のbuffered JSONとstreaming結果を同じ検証済みpayloadから返す。Narrativeはpayload検証前にWriteしない。`internal/probe/probe_test.go`はhealth、schema、rollback、Fake、Projection、streaming fallback、sentinelのoutput/log/Fixture不在を検証する。

```powershell
go test ./...
# 期待RED: Go test runner/compilerが起動し、`undefined: BuildHandler` 等の未実装エラーでexit code 1。module未準備によるFAILではない。

# 実装で追加したimportを`go.mod` / `go.sum`へ反映するため、quality commandの前に次を実行する。
go get github.com/go-playground/validator/v10 modernc.org/sqlite
go mod tidy

go build ./...
gofmt -l .
go vet ./...
go test -run '^$' ./...
go test ./...
# 実装後の期待PASS: build、gofmtの出力空、vet、compile-only test、testがすべてexit code 0。health JSON、schema reject、rollback row count=0、Fake差し替え、stream/buffer同値がPASS。
```

Goでは `go build ./...`をbuild、`gofmt -l .`の空出力をformat、`go vet ./...`をlint、`go test -run '^$' ./...`をtypecheck/compile、`go test ./...`をtestとして固定する。いずれかがFAILした場合は候補Cをrejectする。Go候補でVite clientを確認する場合は、同じ一時directory内で `$env:npm_config_yes='true'; npm create vite@latest client -- --template vanilla-ts --yes; npm --prefix client install --no-audit --no-fund; Remove-Item Env:npm_config_yes` を実行し、clientの `npm run build` はscripts生成後にだけ実行する。

#### 候補 D: 何もしない／今は決めない

Dには実行可能なStack、package/config、Fixture、quality commandがないため、比較候補として名前だけを残す。Dを選ぶ操作は、`P0-01b`の `build`、`format:check`、`lint`、`typecheck`、`test`、health endpoint、CI command parityを一つも実行できず、P0-01b Gateを満たせない具体的な失敗になる。評価報告へ次をそのまま記録して停止する。

```text
P0-02 STOP: D（何もしない／今は決めない）はP0-01b Gateの実行可能なStackを提供しない。
Required evidence missing: build, format, lint, typecheck, test, GET /health, CI parity.
Do not start P0-01b, P0-03, or Phase 1.
```

#### 一時ディレクトリの削除とRepository汚染検査

各候補の全PASSまたは明示的rejectを記録した後、候補ごとに次を実行する。削除対象はUUID付きのその候補directoryだけで、Repositoryの親や `$env:TEMP` 全体を対象にしない。

```powershell
$neontofSpikeTarget = $neontofTsSpike # 実行した候補の変数へ置き換える
$neontofSpikeResolved = (Resolve-Path -LiteralPath $neontofSpikeTarget).Path
if (-not $neontofSpikeResolved.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected spike target' }
Remove-Item -LiteralPath $neontofSpikeResolved -Recurse -Force
Set-Location -LiteralPath 'C:/Users/KINGkawamura/Documents/NeontoF'
if (Test-Path -LiteralPath 'node_modules' -PathType Container) { throw 'Repository node_modules must not exist' }
if (Test-Path -LiteralPath '.venv' -PathType Container) { throw 'Repository .venv must not exist' }
git status --short
```

`git status --short`に候補の一時directory、`node_modules`、`.venv`、Go生成物が現れた場合はP0-02a未完了とする。P0-02aの成功は、採用候補一つについて共通probeとその候補固有の全quality commandがPASSし、他候補のreject理由または比較結果を評価報告へ記録し、一時directoryを削除した状態である。

### 7.6 Commit boundary、Gate証拠、rollback

**Commit 1:** `docs: 技術スタック候補の比較結果を記録する`

- stage: `docs/status/p0-02-technology-stack-evaluation.md` のみ
- 条件: 証拠等級、URL、実出力、Codex/Claude差分、推奨、不採用理由、再評価トリガーが揃い、spike生成物が消えている。
- commit後に承認 B を待つ。

**Commit 2（承認 B 後）:** `docs: Phase 1 の技術スタックを決定する`

- stage: `docs/adr/0001-technology-stack.md` のみ
- 条件: `Accepted`、承認発言引用、採用1案、全候補の不採用理由、再評価トリガーがある。

**MyWorkflow Commit:** `docs: NeontoF の技術スタック規約を確定する`

- stage: `projects/NeontoF/agent-guide/architecture.md` と `projects/NeontoF/agent-guide/coding-style.md` のみ
- 展開後 `node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF` が差分ゼロを報告する。

**リスク:** 高。Stack、threading、validation、database、provider、transportを固定する危険地帯。

**Rollback:** Phase 1着手前なら ADR と MyWorkflow commit を `git revert` し、正本を再展開する。ADR選択を変える場合は評価報告を消さず、根拠を残した新しいADRまたは明示的なsupersede記録で扱う。実 Providerをもう一つ試しに実装しない。

---

## 8. P0-01: Repository and Quality Baseline

### 8.1 Goal、決定境界、Non-goal

**Goal:** P0-01aでStack非依存のRepository境界を先に固定し、承認済み Stack 後のP0-01bで空 Application と API キー不要の品質コマンドをローカル・CIの両方で実行できるようにする。P0-01aだけではP0-01完了とは扱わない。

**決定する:** P0-01aではRepository layout、責務分離、LF、生成物除外を決める。P0-01bでは承認Stackに対応するRuntime pin、dependency lock、strict type設定、Format/Lint/Test/Build command、localhost bind、CI command parity、`.env.example`を決める。

**Non-goal:** Game endpoint、Browser Client、Database、Event Store、実 Provider、Secret Store、Turn処理。

### 8.2 作成・変更ファイルと責務

**P0-01a Create（承認A後、P0-02aより先）:**

- `.gitattributes` — `* text=auto eol=lf`、binary除外。
- `.gitignore` — `.env`、`node_modules/`、`dist/`、coverage、`*.sqlite`、`*.db`、spike生成物を除外する。
- P0-01aでは `src/` と `tests/` の責務境界だけを計画上固定し、Stack固有のimport、runner、production codeを作らない。

P0-01aの独立Commitには `package.json`、runner、言語固有のconfig、空Application、Fixtureを含めない。これらは候補比較後のP0-01bで作る。

**P0-01b Create（承認BとADR commit後）:**

- `.env.example` — `NEONTOF_HOST=127.0.0.1`、`NEONTOF_PORT=3000`、承認されたProviderのAPI key名を空値で一つだけ記す。実値を含めない。
- `.node-version` — ADRで承認したsupported LTS majorの具体version（TypeScript/Nodeを選んだ場合）。
- `package.json` / `package-lock.json` — exact dependency lock と、先に定義した scripts。
- `tsconfig.json` — `strict: true`、Node ESM、`src/**`と`tests/**`のno-emit typecheck（TypeScript/Nodeを選んだ場合）。
- `tsconfig.build.json` — `tsconfig.json`をextendsし、`src/**`だけを`dist/**`へemitする（TypeScript/Nodeを選んだ場合）。
- `eslint.config.mjs`、`prettier.config.mjs`、`vitest.config.ts` — 一つの品質設定（TypeScript/Nodeを選んだ場合）。
- `.github/workflows/ci.yml` — 承認Stackのlocal scriptsと同じ固定command。
- `src/config.ts` — host / portだけを読み、API keyを読まない。
- `src/app.ts` — `/health` だけを持つ承認Stackのapplication factory。
- `src/main.ts` — explicit host / portでlistenし、終了signalでcloseする入口。
- `tests/app.test.ts` — health response、default localhost、API key不要を検証する。

**Modify（MyWorkflow 正本）:**

- `C:/Users/KINGkawamura/Documents/MyWorkflow/projects/NeontoF/agent-guide/build-and-verify.md` — 未確定blockを下記の実command、期待出力、CI parityへ置換する。展開先を直接編集しない。

### 8.3 型と Signature

```ts
export interface ServerOptions {
  readonly host: string;
  readonly port: number;
}

export function loadServerOptions(env: NodeJS.ProcessEnv): ServerOptions;
export function buildApp(): FastifyInstance;
export async function startServer(options: ServerOptions): Promise<FastifyInstance>;
```

`loadServerOptions({})` は `{ host: "127.0.0.1", port: 3000 }` を返す。不正portは起動前にrejectする。`buildApp()` はSecretやGame stateを所有しない。

TypeScript / Node が承認された場合、P0-01bの `package.json` scriptsは次で固定する。別Stackが承認された場合はこのscriptを実行せず、承認Stackの同等commandをこの計画へ反映してから進む。

```json
{
  "scripts": {
    "build": "tsc -p tsconfig.build.json",
    "start": "node dist/main.js",
    "dev": "tsx src/main.ts",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "lint": "eslint src tests vitest.config.ts",
    "format": "prettier --write \"src/**/*.{ts,json}\" \"tests/**/*.{ts,json,yaml}\" \".github/**/*.yml\" \"*.{json,mjs,ts}\"",
    "format:check": "prettier --check \"src/**/*.{ts,json}\" \"tests/**/*.{ts,json,yaml}\" \".github/**/*.yml\" \"*.{json,mjs,ts}\""
  }
}
```

P0-01bでinstallするproduction dependencyは`fastify`、`zod`、`yaml`だけとする。development dependencyは`typescript`、`tsx`、`vitest`、`eslint`、`@eslint/js`、`typescript-eslint`、`prettier`、`@types/node`とする。承認済みProvider SDKとSQLite driverはADRへ記録してもPhase 0 production codeから未使用なのでinstallせず、Phase 1の該当Work Packageで追加する。

### 8.4 Test First

- [ ] **P0-01b Commit 1 — runner bootstrap:** 承認Stackの最小 `package.json`、`test` script、依存lock、Vitest（または承認Stackのrunner）設定だけを先に作る。TypeScript / Node なら `package.json` の `test` script を `vitest run` としてから `npm install --save-dev vitest` と `npm test -- --passWithNoTests` を実行し、runnerが起動することを確認する。scripts未定義のまま `npm test` を呼ばない。
- [ ] **P0-01b Commit 2 — 最初のRED:** runner bootstrap commitの後に `tests/app.test.ts` を作り、`GET /health` status `200`、`{status:"ok"}`、empty envのlocalhost、API key envなしを検証する。`npm test -- tests/app.test.ts` を実行し、Vitestが実際に起動したうえで `../src/app.js` 不在またはexport不在によりexit code `1`になることを確認する。空repoでnpm自体が準備前に失敗する旧手順は採用しない。
- [ ] **P0-01b Commit 3 — 最小実装:** `src/config.ts`、`src/app.ts`、`src/main.ts` を作り、app testをPASSさせる。最初のREDと同じ `npm test -- tests/app.test.ts` がexit code `0`になったcommitをgreenと記録する。
- [ ] **P0-01b Commit 4 — quality scripts:** `npm install fastify zod yaml` と `npm install --save-dev typescript tsx eslint @eslint/js typescript-eslint prettier @types/node` を実行し、scripts/configを完成させる。`npm run format:check`、`npm run lint`、`npm run typecheck`、`npm test`、`npm run build`を実行する。
- [ ] `.github/workflows/ci.yml` の固定commandを一つ故意に失敗させた一時workflowまたは利用可能なlocal runner/remote runで、CIが失敗を検出できることを確認してから元へ戻す。CIのremote run URL/statusが未確認ならPhase Gateは`pending`とする。
- [ ] MyWorkflow正本を更新、展開し、差分ゼロcheckを通す。

### 8.5 実行コマンドと期待結果

```powershell
npm ci
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

成功証拠は各command exit code `0`、Vitestの全Test Files passed、ESLint error 0、Prettier対象差分0、TypeScript error 0、`dist/main.js`生成である。API key環境変数は設定しない。

localhost probe:

```powershell
$neontofServer = Start-Process node -ArgumentList 'dist/main.js' -PassThru -WindowStyle Hidden
try {
  $neontofHealth = $null
  for ($neontofAttempt = 0; $neontofAttempt -lt 20; $neontofAttempt++) {
    try {
      $neontofHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:3000/health'
      break
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if ($null -eq $neontofHealth) {
    throw 'Health endpoint did not become ready'
  }
  $neontofHealth | ConvertTo-Json -Compress
} finally {
  if (-not $neontofServer.HasExited) {
    Stop-Process -Id $neontofServer.Id
  }
}
```

期待出力は `{"status":"ok"}`。`0.0.0.0` bind、key要求、process残留はFAIL。

CI parity とハーネス:

```powershell
rg -n 'npm ci|npm run format:check|npm run lint|npm run typecheck|npm test|npm run build' .github/workflows/ci.yml
node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs --apply NeontoF
node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF
git status --short
```

`.github/workflows/ci.yml` の `quality` job は、local scriptsと同じ順序で次の固定commandを列挙する。コマンドをworkflow内で別名に置換したり、localにない成功処理を追加したりしない。

```yaml
- run: npm ci
- run: npm run format:check
- run: npm run lint
- run: npm run typecheck
- run: npm test
- run: npm run build
```

最後のdeploy checkは展開差分0、`git status` はハーネス・生成物を表示しないこと。

CI failure detectionは次の順で実行する。

```powershell
actionlint .github/workflows/ci.yml
# 期待PASS: stdout/stderrにerrorがなくexit code 0。

$ciPath = Join-Path (Get-Location) '.github/workflows/ci.yml'
$ciBackup = Join-Path $env:TEMP "neontof-ci-$([guid]::NewGuid().ToString('N')).yml"
Copy-Item -LiteralPath $ciPath -Destination $ciBackup
try {
  $ciText = Get-Content -Raw -LiteralPath $ciPath
  $ciFailureText = $ciText.Replace('npm run build', "npm run build`n      - name: injected failure probe`n        run: exit 1")
  if ($ciFailureText -eq $ciText) { throw 'CI build command was not found for failure injection' }
  $ciFailureText | Set-Content -LiteralPath $ciPath -Encoding utf8NoBOM
  actionlint $ciPath
  if (Get-Command act -ErrorAction SilentlyContinue) {
    docker info | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not available for act' }
    act -W $ciPath -j quality --pull=false
    if ($LASTEXITCODE -eq 0) { throw 'Failure injection unexpectedly passed' }
    # 期待FAIL: actのjobが `injected failure probe` と `exit code 1` を表示してnon-zero。
  }
} finally {
  Copy-Item -LiteralPath $ciBackup -Destination $ciPath -Force
  Remove-Item -LiteralPath $ciBackup -Force
}
```

`actionlint`はworkflow構文の検査、`act` + Dockerがある環境では故意の `exit 1` の実行証拠に使う。`act`またはDockerがない環境では上のlocal検査をCI実行証拠としない。その場合はエージェントがpushせず、ユーザーが一時的なfailure workflowをremote branchへ反映した後、次でremote runの非zeroと復元後のgreen runを確認する。

```powershell
$neontofBranch = 'docs/phase-00-foundation'
gh run list --workflow ci.yml --branch $neontofBranch --limit 10 --json databaseId,status,conclusion,url
$failureRun = gh run list --workflow ci.yml --branch $neontofBranch --limit 10 --json databaseId,status,conclusion,url | ConvertFrom-Json | Where-Object { $_.conclusion -eq 'failure' } | Select-Object -First 1
if ($null -eq $failureRun) { throw 'Remote failure probe run was not found' }
gh run watch $failureRun.databaseId --exit-status
# 期待FAIL: `Process completed with exit code 1`、conclusionがfailure、URLを記録。
gh run view $failureRun.databaseId --log-failed

gh run list --workflow ci.yml --branch $neontofBranch --limit 10 --json databaseId,status,conclusion,url
$greenRun = gh run list --workflow ci.yml --branch $neontofBranch --limit 10 --json databaseId,status,conclusion,url | ConvertFrom-Json | Where-Object { $_.conclusion -eq 'success' } | Select-Object -First 1
if ($null -eq $greenRun) { throw 'Remote green run was not found' }
gh run watch $greenRun.databaseId --exit-status
gh run view $greenRun.databaseId --json status,conclusion,url
# 期待PASS: status=completed、conclusion=success、remote run URLを記録。
```

failure probeの後は必ず元の `ci.yml` を復元し、failure差分をpushしない。`act`/Dockerの実行証拠もremote run URL/statusもない場合、localのactionlint・workflow文字列検査だけではCI Gateを満たさず、P0-01とPhase 0 Gateを`pending`にする。GitHub Actionsのremote runを確認するまでPhase 1へ進まない。

GitHub Actionsの実runはremoteへbranchが反映されなければ取得できない。エージェントは明示指示なしにpushしないため、local P0-01b commit後にユーザーが手動pushしてrun URLを返すか、そのturnだけpushを明示指示する。run未確認の間はP0-01b codeを完成と報告できてもPhase 0 Gateは`pending`とし、Phase 1へ進まない。

### 8.6 Commit boundary、Gate証拠、rollback

1. `chore: Stack非依存のRepository境界を固定する` — P0-01aの `.gitattributes`、`.gitignore`。
2. `chore: Vitestの最小runnerをbootstrapする` — P0-01bの `package.json`、test script、runner設定、lockfile。`npm test -- --passWithNoTests`がgreen。
3. `test: localhost 起動契約を固定する` — `tests/app.test.ts` のfailing test。runner起動後にsrc不在でRED。
4. `feat: 空の Application と品質基盤を追加する` — P0-01b root設定、`src/**`、quality scripts。app testがgreen。
5. `chore: CI にローカル品質ゲートを再現する` — `.github/workflows/ci.yml`、failure injectionとremote/act evidence。
6. MyWorkflow: `docs: NeontoF の実コマンドを品質ガイドへ記録する` — 正本 `build-and-verify.md` のみ。

**Gate証拠:** 上記commandの実出力、health JSON、`actionlint`結果、故意の`exit 1`を検出した`act`またはremote failure run URL/status/log、復元後のremote green run URL/status、deploy差分ゼロ、API key未設定証拠。act/Dockerもremote runもない間は`pending`。

**リスク:** 中。Repository基盤だが後続全Packageが依存する。

**Rollback:** NeontoF commitを逆順に`git revert`し、MyWorkflow commitも別Repositoryで`git revert`して再展開する。`package-lock.json`だけを手編集しない。

---

## 9. P0-03: Core Domain and Event Model Specification

### 9.1 Goal、決定境界、Non-goal

**Goal:** Event Log単一権威、stable ID、Visibility、Turn状態、version、Projection rebuild、Transcript / Telemetry分離を、文書と実行可能な純粋contractで固定する。

**決定する:** ID grammar、Event envelope、最低Event type、`TurnAwaitingPlayer` / `TurnResumed` / `TurnAborted`、Fact ID導出、受信・保存用Schema/parser Signature、Projection reducer signature、`projectTurnStatus`、revert semantics、Event順序、version rejection。

**Non-goal:** Database table、Event repository、transaction runner、完全なState/Canon、Ruleset event全種、migration command、Turn Engine。

### 9.2 作成ファイルと責務

- `docs/specs/core-domain-and-events.md` — Domain語彙、Authority、Event envelope、Event type、payload最小項目、Projection、Transcript / Telemetry、Undo、version / migration規則を記述する。
- `src/contracts/domain.ts` — ID、Visibility、TurnStatus、Event envelope、TranscriptEntry、TelemetryEntryの型。永続化やstate mutationは持たない。
- `src/contracts/domain-event-parser.ts` — 承認StackのSchema libraryでEvent受信・保存境界を検証する。`domainEventSchema`、`parseDomainEvent`、sequence検証をここへ集約し、raw JSONを`DomainEvent`へcastしない。
- `src/contracts/turn-status.ts` — Event列だけからTurn statusを再構築する純粋関数。runtimeのmutable statusを所有しない。
- `tests/contracts/support/reference-projection.ts` — Phase Gate用の最小純粋reducer。production codeではなく、Phase 1実装が同じFixtureへ適合するための参照oracle。
- `tests/contracts/domain.test.ts` — stable ID、Fact ID、rebuild、revert、separate logsを反証する。
- `tests/contracts/domain-event-parser.test.ts` — valid Event、unknown field/version、ID grammar、payload各不正、受信→parser→rebuildの境界を反証する。
- `tests/contracts/turn-status.test.ts` — status transition、再起動、同一request再送を反証する。
- `tests/fixtures/events/minimal-session.v1.json` — 固定Event Sequenceとexpected State / Facts。Transcript / Telemetryを含めない。
- `tests/fixtures/events/invalid-unknown-field.v1.json`、`invalid-unknown-version.v1.json`、`invalid-unknown-event.v1.json`、`invalid-payloads.v1.json`、`turn-status-sequences.v1.json`、`same-request-resend.v1.json` — parserとEvent-derived statusのreject/transition Fixture。秘密文字列は含めない。

### 9.3 型と Signature

```ts
export type JsonValue = null | boolean | number | string | JsonValue[] | { readonly [key: string]: JsonValue };

export type CampaignId = `campaign:${string}`;
export type SessionId = `session:${string}`;
export type SceneId = `scene:${string}`;
export type TurnId = `turn:${string}`;
export type TurnRequestId = `turn-request:${string}`;
export type EventId = `event:${string}`;
export type FactId = `fact:${string}:${number}`;
export type TranscriptId = `transcript:${string}`;
export type TelemetryId = `telemetry:${string}`;
export type ModelCallId = `model-call:${string}`;
export type CharacterId = `character:${string}`;
export type NpcId = `npc:${string}`;
export type LocationId = `location:${string}`;
export type ItemId = `item:${string}`;
export type ClockId = `clock:${string}`;
export type ResourceId = `resource:${string}`;
export type ActionId = `action:${string}`;
export type ScenarioId = `scenario:${string}`;
export type SecretId = `secret:${string}`;
export type ClueId = `clue:${string}`;
export type InvariantId = `invariant:${string}`;
export type EndConditionId = `end:${string}`;
export type EntityId = CharacterId | NpcId | LocationId | ItemId | ClockId;
export type FactSubjectId = EntityId | CampaignId | SceneId | ScenarioId | SecretId | ClueId | InvariantId | EndConditionId;
export type Visibility = "gm_only" | "player_visible" | NpcId;
export type TurnStatus = "pending" | "running" | "awaiting_player" | "committed" | "aborted";
export type EventOrigin = "in_world" | "table_correction";
export type FactKind = "fact" | "ruling" | "agreement" | "plan" | "promise";
export type FactHolder = "world" | "player_character" | NpcId | "rumor";
export type FactStatus = "active" | "disputed" | "superseded";

export type EventType =
  | "CampaignCreated"
  | "SessionStarted"
  | "SceneStarted"
  | "SceneEnded"
  | "PlayerInputAccepted"
  | "DiceRolled"
  | "ResourceChanged"
  | "CharacterMoved"
  | "ClockAdvanced"
  | "FactAsserted"
  | "FactSuperseded"
  | "TurnAwaitingPlayer"
  | "TurnResumed"
  | "TurnAborted"
  | "TurnCommitted"
  | "TurnReverted"
  | "SessionEnded";

export interface FactAssertion {
  readonly ordinal: number;
  readonly kind: FactKind;
  readonly holder: FactHolder;
  readonly status: FactStatus;
  readonly subject_id: FactSubjectId;
  readonly predicate: string;
  readonly value: JsonValue;
  readonly visibility: Visibility;
}

export interface CampaignRef {
  readonly id: CampaignId;
}

export interface SessionRef {
  readonly id: SessionId;
  readonly campaign_id: CampaignId;
}

export interface SceneRef {
  readonly id: SceneId;
  readonly session_id: SessionId;
}

export interface TurnRef {
  readonly id: TurnId;
  readonly session_id: SessionId;
  readonly request_id: TurnRequestId;
  readonly status: TurnStatus;
}

export interface EntityRef {
  readonly id: EntityId;
  readonly canonical_name: string;
  readonly aliases: readonly string[];
}

export interface EventPayloadMap {
  readonly CampaignCreated: { readonly campaign_seed: string };
  readonly SessionStarted: Readonly<Record<string, never>>;
  readonly SceneStarted: { readonly scene_id: SceneId };
  readonly SceneEnded: { readonly scene_id: SceneId };
  readonly PlayerInputAccepted: { readonly request_id: TurnRequestId; readonly transcript_id: TranscriptId };
  readonly DiceRolled: {
    readonly action_id: ActionId;
    readonly roll_index: number;
    readonly formula: string;
    readonly seed: string;
    readonly values: readonly number[];
    readonly total: number;
  };
  readonly ResourceChanged: {
    readonly entity_id: EntityId;
    readonly resource_id: ResourceId;
    readonly delta: number;
    readonly resulting_value: number;
  };
  readonly CharacterMoved: {
    readonly character_id: CharacterId;
    readonly from_location_id: LocationId | null;
    readonly to_location_id: LocationId;
  };
  readonly ClockAdvanced: {
    readonly clock_id: ClockId;
    readonly previous: number;
    readonly current: number;
    readonly reason: string;
  };
  readonly FactAsserted: FactAssertion;
  readonly FactSuperseded: {
    readonly superseded_fact_id: FactId;
    readonly replacement: FactAssertion;
  };
  readonly TurnAwaitingPlayer: {
    readonly request_id: TurnRequestId;
    readonly reason: "clarification" | "confirmation" | "entity_resolution" | "resource_choice";
  };
  readonly TurnResumed: { readonly request_id: TurnRequestId };
  readonly TurnAborted: {
    readonly request_id: TurnRequestId;
    readonly code: "unsafe" | "impossible" | "invalid_input" | "budget_exceeded";
  };
  readonly TurnCommitted: { readonly request_id: TurnRequestId };
  readonly TurnReverted: { readonly reverted_turn_id: TurnId };
  readonly SessionEnded: { readonly outcome: "success" | "failure" | "abandoned" };
}

export interface EventEnvelope<TType extends EventType = EventType> {
  readonly event_id: EventId;
  readonly event_version: 1;
  readonly campaign_id: CampaignId;
  readonly session_id: SessionId | null;
  readonly scene_id: SceneId | null;
  readonly turn_id: TurnId | null;
  readonly sequence: number;
  readonly occurred_at: string;
  readonly origin: EventOrigin;
  readonly visibility: Visibility;
  readonly type: TType;
  readonly payload: EventPayloadMap[TType];
}

export type DomainEvent = { readonly [TType in EventType]: EventEnvelope<TType> }[EventType];

export interface DomainEventValidationIssue {
  readonly path: readonly (string | number)[];
  readonly code: "schema" | "unknown_field" | "unknown_event" | "unknown_version" | "invalid_id" | "invalid_sequence" | "invalid_payload";
  readonly message: string;
}

export class DomainEventValidationError extends Error {
  readonly issues: readonly DomainEventValidationIssue[];
}

// `src/contracts/domain-event-parser.ts` に置く。Schema libraryのunknown-key拒否とgrammar検証を保存/受信境界で必ず通す。
export const domainEventSchema: ZodType<DomainEvent>;
export function parseDomainEvent(input: unknown): DomainEvent;
export function parseDomainEventSequence(inputs: readonly unknown[]): readonly DomainEvent[];

export interface TranscriptEntry {
  readonly transcript_id: TranscriptId;
  readonly campaign_id: CampaignId;
  readonly session_id: SessionId;
  readonly turn_id: TurnId | null;
  readonly kind: "player_input" | "model_request" | "model_response" | "tool_call" | "error" | "retry" | "narrative" | "correction";
  readonly recorded_at: string;
  readonly content: JsonValue;
}

export interface TelemetryEntry {
  readonly telemetry_id: TelemetryId;
  readonly campaign_id: CampaignId;
  readonly session_id: SessionId;
  readonly turn_id: TurnId | null;
  readonly model_call_id: ModelCallId;
  readonly provider: string;
  readonly model: string;
  readonly roles: readonly string[];
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly cached_tokens: number;
  readonly cost: number;
  readonly latency_ms: number;
  readonly retry: number;
  readonly status: "succeeded" | "failed" | "timed_out" | "rejected";
}

export interface Projection {
  readonly applied_through_sequence: number;
  readonly state: Readonly<Record<string, JsonValue>>;
  readonly facts: Readonly<Record<FactId, FactRecord>>;
  readonly reverted_turn_ids: ReadonlySet<TurnId>;
}

export interface FactRecord extends FactAssertion {
  readonly fact_id: FactId;
  readonly source_event_id: EventId;
}

export function deriveFactId(eventId: EventId, ordinal: number): FactId;
// 以下3関数は tests/contracts/support/reference-projection.ts だけに置く。
export function collectRevertedTurnIds(events: readonly DomainEvent[]): ReadonlySet<TurnId>;
export function applyEvent(projection: Projection, event: DomainEvent, revertedTurnIds: ReadonlySet<TurnId>): Projection;
export function rebuildProjection(events: readonly DomainEvent[]): Projection;

// `src/contracts/turn-status.ts` に置く。Transcript / Telemetryやruntime変数を入力にしない。
export function projectTurnStatus(events: readonly DomainEvent[]): TurnStatus;
```

`EventPayloadMap` は次の最小payloadをdiscriminated unionで定義する。

| Event | 必須payload |
|---|---|
| `CampaignCreated` | `campaign_seed` |
| `SessionStarted` | 空object |
| `SceneStarted` / `SceneEnded` | `scene_id` |
| `PlayerInputAccepted` | `request_id`, `transcript_id`。入力本文はTranscript側 |
| `DiceRolled` | `action_id`, `roll_index`, `formula`, `seed`, `values`, `total` |
| `ResourceChanged` | `entity_id`, `resource_id`, `delta`, `resulting_value` |
| `CharacterMoved` | `character_id`, `from_location_id`, `to_location_id` |
| `ClockAdvanced` | `clock_id`, `previous`, `current`, `reason` |
| `FactAsserted` | `ordinal`, `kind`, `holder`, `status`, `subject_id`, `predicate`, `value`, `visibility` |
| `FactSuperseded` | `superseded_fact_id` と新Factの同項目 |
| `TurnAwaitingPlayer` | `request_id`, `reason` |
| `TurnResumed` | `request_id` |
| `TurnAborted` | `request_id`, `code` |
| `TurnCommitted` | `request_id` |
| `TurnReverted` | `reverted_turn_id` |
| `SessionEnded` | `outcome: "success" | "failure" | "abandoned"` |

ID grammarは `kind:slug` を基本形とし、kindは宣言済みの小文字ASCII token、slugは `[a-z0-9]+(?:-[a-z0-9]+)*` とする。`EventId` は `event:<slug>`、`EntityId` は `character|npc|location|item|clock:<slug>`、`TurnRequestId` は `turn-request:<slug>`、`FactId` は `fact:<event-slug>:<ordinal>`（ordinalは0以上の十進数）に限定する。大文字、空slug、未宣言kind、余分なfieldをparserがrejectする。

`sequence` はCampaign内で厳密増加、重複・欠落・未知versionは`parseDomainEventSequence`またはrebuild前にrejectする。`occurred_at` はProjectionのゲーム判断に使わない。`deriveFactId("event:abc", 0)` は `fact:abc:0` を返す。`domainEventSchema`は全objectをstrictにし、`event_version !== 1`を`unknown_version`、Event envelope不正を`schema` / `invalid_id`、各Eventの必須payload欠落・余分field・型不正を`invalid_payload`としてrejectする。受信JSON、Fixture、保存から読み出したJSONはすべて `parseDomainEvent` を通し、`rebuildProjection(raw as DomainEvent[])` のようなcastを互換性証拠にしない。

`rebuildProjection()` は最初に `TurnReverted` を走査し、対象TurnのEventを除外してから残りをsequence順に適用する。`applyEvent()`単体が過去のStateを直接書き戻す設計にはしない。`TurnReverted`は直前のcommitted Turnだけを対象にでき、Event自体は削除しない。Event envelopeと`FactAssertion.visibility`は一致しなければrejectする。

Turn statusもEventから再構築する。`PlayerInputAccepted` は `pending → running`、`TurnAwaitingPlayer` は `running → awaiting_player`、`TurnResumed` は `awaiting_player → running`、`TurnCommitted` は `running → committed`、`TurnAborted` は `running` または `awaiting_player` から `aborted` へ遷移させる。同じ `request_id` の再送は既存のTurn結果を返し、同じ遷移やEventを二重に作らない。未完了のEvent列を再起動後に `projectTurnStatus` へ渡した結果が `awaiting_player` なら、その値をruntimeのメモリに頼らず維持する。`TurnAwaitingPlayer`、`TurnResumed`、`TurnAborted` をROADMAP §0.4 のP0-03最低Event一覧へ補う理由は、同じROADMAPの`awaiting_player`受入条件と、Product Plan §9の再開・中断をEvent Log単一権威で満たすためである。

Character Sheet / Scenario の初期値は、Phase 1 loaderが次の既存Eventへ正規化する契約とする。Phase 0ではconverterを実装しない。

- Name、Aliases、Description、Speech Style、NPC Goal / Knowledge、World Invariant、Secret、Clue、End Condition、Item ownershipはvisibility付き`FactAsserted`。
- HP / Resourceは0から初期値への`ResourceChanged`。
- Characterの初期Locationは`from_location_id:null`の`CharacterMoved`。
- Clock初期値は0からの`ClockAdvanced`、initial Sceneは`SceneStarted`。

これにより元YAMLの変更で既存Campaignが変わらず、Event Sequenceだけから初期Projectionを再構築できる。新しい初期化Event typeをPhase 0で増やさない。

### 9.4 Test First

- [ ] runner bootstrap後、`domain-event-parser.test.ts` に valid envelopeを `parseDomainEvent` へ渡す最初のREDを書く。実装前の期待FAILはVitestが起動し、`domain-event-parser.ts`のmodule/export不在でexit code `1`。npm自体の準備不足をREDの理由にしない。
- [ ] `domain-event-parser.test.ts` にunknown event type、unknown top-level field、unknown payload field、`event_version:2`、`event_id` / `entity_id` / `fact_id` のgrammar違反、`CampaignCreated.campaign_seed`、`SessionStarted`の空payloadへのunknown field、`SceneStarted.scene_id`、`SceneEnded.scene_id`、`PlayerInputAccepted.request_id/transcript_id`、`DiceRolled.action_id/roll_index/formula/seed/values/total`、`ResourceChanged.entity_id/resource_id/delta/resulting_value`、`CharacterMoved.character_id/from_location_id/to_location_id`、`ClockAdvanced.clock_id/previous/current/reason`、`FactAsserted`各Fact field、`FactSuperseded.superseded_fact_id/replacement`、`TurnAwaitingPlayer.request_id/reason`、`TurnResumed.request_id`、`TurnAborted.request_id/code`、`TurnCommitted.request_id`、`TurnReverted.reverted_turn_id`、`SessionEnded.outcome`の各必須payload欠落・型不正・payload内unknown fieldをFixtureごとに書き、`unknown_field`、`unknown_event`、`unknown_version`、`invalid_id`、`invalid_payload`を期待する。
- [ ] parser実装後、同じraw Fixtureを `parseDomainEventSequence` で検証してから `rebuildProjection(parsed)` へ渡す。rawを `as DomainEvent` へcastしてrebuildするテストは禁止し、`rg -n 'as DomainEvent|as readonly DomainEvent' tests src`を0件にする。
- [ ] `domain.test.ts` に同一Event配列の2回rebuild deep equal、Fact ID決定性、`TurnReverted`で対象Turn効果除外、順序重複reject、unknown version rejectを書く。
- [ ] `TranscriptEntry` / `TelemetryEntry` が `DomainEvent[]` へ渡せないcompile-time testまたは`tsd`相当の`@ts-expect-error` testを書く。
- [ ] `turn-status.test.ts` に `pending → running → awaiting_player → running → committed`、`aborted`、再起動後の`awaiting_player`維持、`same-request-resend.v1.json`（同じ`request_id`の入力を二度受けてもaccepted Eventと結果が一つ）を追加する。`projectTurnStatus(events: readonly DomainEvent[]): TurnStatus`がEvent列だけで同じ結果を返し、Transcript / Telemetryを入力にしないことを確認する。
- [ ] `npm test -- tests/contracts/domain-event-parser.test.ts tests/contracts/domain.test.ts tests/contracts/turn-status.test.ts` を実行し、parser/reducer未実装の初回はmodule/export不在でexit code `1`、最小実装後は全test PASSになることを確認する。
- [ ] 最小typeとtest-only pure reducerを実装し、Fixture expected projectionと一致させる。`src/**` にEvent Store / Projection implementationを作らない。
- [ ] specに「State direct mutation public API禁止」「Character/Scenario入力はCampaign開始時にEventへ正規化」「Transcript/TelemetryはEvent transaction外」「受信・保存境界はparserを通る」「Turn statusはEventから再構築」を明記する。

### 9.5 実行コマンドと期待結果

```powershell
npm test -- tests/contracts/domain.test.ts
npm test -- tests/contracts/domain-event-parser.test.ts tests/contracts/turn-status.test.ts
npm run typecheck
rg -n 'State.*direct|Event Log|Projection|Transcript|Telemetry|TurnReverted|TurnAwaitingPlayer|TurnResumed|TurnAborted|awaiting_player|event_version|parseDomainEvent|unknown_version|invalid_payload' docs/specs/core-domain-and-events.md src/contracts
rg -n 'setState|updateState|mutateState|saveProjection|as DomainEvent|as readonly DomainEvent' src tests
```

PASSはVitest全test成功、type error 0、specの必須語が検出され、禁止API・DomainEvent cast検索が0件である。unknown field、unknown version、各payload不正、status fixtureの一つをvalid扱いへ故意に変えるとtestがFAILすることも確認し、戻してPASSさせる。

### 9.6 Commit boundary、Gate証拠、rollback

1. `test: Event から Projection を再構築する契約を固定する`
2. `feat: Domain と Event の最小契約を追加する`
3. `docs: Core Domain と Event の仕様を確定する`

**Gate証拠:** valid/invalid Event Fixture名、parserのValidationIssue code、Event件数、expected Projection、turn status transition / restart / resendのFAIL/PASS出力、`DomainEvent` cast禁止検索0件。

**リスク:** 高。Event互換性とAuthorityの危険地帯。

**Rollback:** P0-04〜P0-07着手前なら3commitを逆順revertする。後続着手後は先に依存diffをrevertする。永続Eventはまだないためdata migrationは発生しない。

---

## 10. P0-04: Semantic Result Specification

### 10.1 Goal、決定境界、Non-goal

**Goal:** LLMの自由文を状態更新入力にしない出力契約を、Schema、Authority表、pre/public post check、Fixtureで固定する。

**決定する:** 必須field、field type、model-proposable Event whitelist、`proposed_events` / `proposed_facts`の単一Authority、Ruling / knowledge / visibilityの参照関係、Evidenceの存在・Visibility・predicate/value一致validation、clarification / rejection、`awaiting_player` / `aborted`、`provisional_detail`寿命、non-stream fallback。

**Non-goal:** Prompt本文、実Model call、Event append、公開UI、完全な自然言語矛盾検出、Streaming endpoint。

### 10.2 作成ファイルと責務

- `docs/specs/semantic-result.md` — field authority、state transition、validation順、secret境界、publish前後の扱い。
- `src/contracts/semantic-result.ts` — TypeScript型とZodの構造Schemaだけ。Evidence / 現在Stateを読むproduction Validatorは置かない。
- `tests/contracts/support/evaluate-semantic-contract.ts` — invisible Evidence、control field、whitelistをFixtureに対して評価するtest-only oracle。productionからimportしない。
- `tests/contracts/support/materialize-proposed-events.ts` — `proposed_events`を非Fact Eventへ、`proposed_facts`を`FactAsserted`へ一度だけ変換するtest-only oracle。`rulings`、`knowledge_changes`、`visibility_changes`から追加Eventを作らない。
- `tests/contracts/semantic-result.test.ts` — valid / invalid / invisible evidence / clarification / rejection / narrative-onlyを検証。
- `tests/fixtures/semantic-results/valid-normal.v1.json`
- `tests/fixtures/semantic-results/invalid-event.v1.json`
- `tests/fixtures/semantic-results/invisible-evidence.v1.json`
- `tests/fixtures/semantic-results/unrelated-visible-evidence.v1.json`
- `tests/fixtures/semantic-results/unknown-evidence.v1.json`
- `tests/fixtures/semantic-results/evidence-claim-mismatch.v1.json`
- `tests/fixtures/semantic-results/duplicate-resource-proposal.v1.json`
- `tests/fixtures/semantic-results/duplicate-fact-proposal.v1.json`
- `tests/fixtures/semantic-results/duplicate-materialization.v1.json`
- `tests/fixtures/semantic-results/clarification.v1.json`
- `tests/fixtures/semantic-results/rejection.v1.json`

### 10.3 型と Signature

```ts
export type ModelProposableEventType = "ResourceChanged" | "CharacterMoved" | "ClockAdvanced";

export type ProposedEvent = {
  readonly [TType in ModelProposableEventType]: {
    readonly type: TType;
    readonly payload: EventPayloadMap[TType];
  }
}[ModelProposableEventType];

export type ProposalRef =
  | { readonly kind: "event"; readonly index: number }
  | { readonly kind: "fact"; readonly index: number };

export interface ProposedFact extends Omit<FactAssertion, "ordinal" | "status"> {
  readonly status: "active" | "disputed";
}

export interface KnowledgeChange {
  readonly entity_id: CharacterId | NpcId;
  readonly proposal_ref: ProposalRef;
  readonly operation: "learn" | "forget";
}

export interface VisibilityChange {
  readonly proposal_ref: ProposalRef;
  readonly from: Visibility;
  readonly to: Visibility;
}

export interface RollSpec {
  readonly action_id: ActionId;
  readonly formula: "2d6";
  readonly target: number;
}

export interface Ruling {
  readonly rule_refs: readonly string[];
  readonly facts_used: readonly FactId[];
  readonly interpretation: string;
  readonly roll_spec: RollSpec | null;
  readonly proposal_refs: readonly ProposalRef[];
  readonly is_house_ruling: boolean;
}

export interface ClarificationRequest {
  readonly question: string;
  readonly choices: readonly { readonly id: string; readonly label: string }[];
}

export interface Rejection {
  readonly code: "unsafe" | "impossible" | "invalid_input" | "budget_exceeded";
  readonly reason: string;
}

export interface NarrativeBeat {
  readonly order: number;
  readonly intent: string;
}

export interface ProvisionalDetail {
  readonly id: `provisional:${string}`;
  readonly kind: "object" | "place_detail" | "appearance" | "quantity";
  readonly label: string;
  readonly scene_id: SceneId;
  readonly visibility: Visibility;
}

export interface EvidenceClaim {
  readonly predicate: string;
  readonly value: JsonValue;
}

export interface EvidenceRef {
  readonly fact_id: FactId;
  readonly claim: EvidenceClaim;
}

export interface SuggestedAction {
  readonly id: `suggested-action:${string}`;
  readonly label: string;
}

export interface SemanticResultV1 {
  readonly schema_version: 1;
  readonly rulings: readonly Ruling[];
  readonly proposed_events: readonly ProposedEvent[];
  readonly proposed_facts: readonly ProposedFact[];
  readonly knowledge_changes: readonly KnowledgeChange[];
  readonly visibility_changes: readonly VisibilityChange[];
  readonly clarification_request: ClarificationRequest | null;
  readonly rejection: Rejection | null;
  readonly narrative_plan: readonly NarrativeBeat[];
  readonly narrative: string;
  readonly mentioned_details: readonly ProvisionalDetail[];
  readonly evidence: readonly EvidenceRef[];
  readonly suggested_actions: readonly SuggestedAction[];
}

export interface SemanticValidationContext {
  readonly known_entity_ids: ReadonlySet<EntityId>;
  readonly known_fact_subject_ids: ReadonlySet<FactSubjectId>;
  readonly facts_by_id: ReadonlyMap<FactId, EvidenceFact>;
  readonly current_turn_status: "running" | "awaiting_player";
  readonly publication_visibility: "player_visible" | NpcId;
}

export interface EvidenceFact {
  readonly fact_id: FactId;
  readonly visibility: Visibility;
  readonly predicate: string;
  readonly value: JsonValue;
}

export interface ValidationIssue {
  readonly path: readonly (string | number)[];
  readonly code:
    | "schema"
    | "unknown_event"
    | "unknown_entity"
    | "unknown_evidence"
    | "invisible_evidence"
    | "evidence_claim_mismatch"
    | "duplicate_proposal"
    | "invalid_proposal_reference"
    | "conflicting_control"
    | "invalid_transition";
  readonly message: string;
}

export type SemanticValidationOutcome =
  | { readonly ok: true; readonly value: SemanticResultV1; readonly next_status: "running" | "awaiting_player" | "aborted" }
  | { readonly ok: false; readonly issues: readonly ValidationIssue[]; readonly next_status: "awaiting_player" | "aborted" };

export const semanticResultV1Schema: ZodType<SemanticResultV1>;
export function normalizeEvidenceClaim(input: unknown): EvidenceClaim;
// tests/contracts/support/evaluate-semantic-contract.ts だけに置く。Phase 0のvalidator oracleの正確なSignature。
export function validateSemanticResult(input: unknown, context: SemanticValidationContext): SemanticValidationOutcome;
// tests/contracts/support/materialize-proposed-events.ts だけに置く。production Turn Engineではない。
export function materializeSemanticResultForTest(result: SemanticResultV1, context: FixtureEventContext): readonly DomainEvent[];
```

| Field | Authority / 処理 | Eventへの包含関係 |
|---|---|---|
| `rulings` | 裁定・解釈と既存Proposalへの参照。Rule Runtime検証前は非権威。直接のEvent effects fieldを持たない | 既存の`proposal_refs`を注釈するだけで、Eventを新規生成しない |
| `proposed_events` | 非Factの許可Event（`ResourceChanged` / `CharacterMoved` / `ClockAdvanced`）の唯一の宣言源。ValidatorとTurn Engineを通るまで非権威 | 各要素を最大一回だけ同型Eventへmaterializeする |
| `proposed_facts` | `FactAsserted`の唯一の宣言源。`FactAssertion`の`ordinal`と最終envelopeはmaterialize側が付与する | 各要素を最大一回だけ`FactAsserted`へmaterializeする。`proposed_events`にはFactを含めない |
| `knowledge_changes` | `ProposalRef`への学習/忘却の注釈。参照先のProposalがなければreject | 単独Eventを作らず、参照先Proposalのmaterialize後処理へ渡す |
| `visibility_changes` | `ProposalRef`へのVisibility変更の注釈。from/toと参照先の整合だけを検証する | 単独Eventを作らず、既存Proposalの注釈に限定する |
| `clarification_request` | Eventなしで同じTurnを`awaiting_player`へ送るcontrol proposal | Event配列へ含めず、Phase 1が`TurnAwaitingPlayer`をappendする |
| `rejection` | EventなしでTurnを`aborted`へ送るcontrol proposal | Event配列へ含めず、Phase 1が`TurnAborted`をappendする |
| `narrative_plan` / `narrative` | 表現。状態入力に使わない | Eventへ含めない |
| `mentioned_details` | Scene寿命のprovisional data。Transcriptには残す | Canon/State Eventへ含めない |
| `evidence` | Fact IDの存在・publication Visibility・構造化claim対応を検証するcitation | Eventを作らず、公開前後検証の証拠だけに使う |
| `suggested_actions` | Player向け提案。状態を変えない | Eventへ含めない |

制約:

- 12 mandatory fieldsのAuthorityは上表で一つずつ固定する。`proposed_events`と`proposed_facts`だけが状態変更Proposalの宣言配列であり、それぞれの配列要素はmaterialize時に一つのEventへ一度だけ包含される。Ruling、knowledge、visibilityの各配列は参照・注釈であり、別のEvent源ではない。
- lifecycle Event、`DiceRolled`、`FactSuperseded`、`TurnReverted` はmodel-proposable whitelist外。
- `proposed_events`はFactを含まない。`proposed_facts`だけが新しいFactの宣言源であり、`knowledge_changes` / `visibility_changes` / `rulings[].proposal_refs`は既存Proposalへの参照・注釈であって、単独でEventを作らない。Phase 1のTurn Engineが現在State、holder、visibilityを検証し、`proposed_events`を対応する非Fact Eventへ、`proposed_facts`を`FactAsserted`へ一度だけ変換するまでProjectionへ入れない。
- 同じ`proposed_events`要素（同一Event type、target entity/resource、delta/value）または同じ`proposed_facts`命題（subject、predicate、value、visibility）が二重に現れた場合は`duplicate_proposal`でrejectする。`ProposalRef`のindexが配列範囲外、kindと参照先配列が不一致、同一refの二重materializeは`invalid_proposal_reference`または`duplicate_proposal`でrejectする。
- `clarification_request`が非nullなら`next_status="awaiting_player"`、Event proposalは空。
- `rejection`が非nullなら`next_status="aborted"`、Event proposalは空。
- clarificationとrejectionの同時指定はreject。
- Evidence IDは`facts_by_id`に実在し、publication先からvisibleでなければrejectする。存在するFactでも `claim.predicate` と `claim.value` がFactの構造化内容とdeep equalでなければ`evidence_claim_mismatch`でrejectする。`claim`は`normalizeEvidenceClaim(input: unknown): EvidenceClaim`で正規化し、自由文の含意判定を行わない。
- `narrative`、`narrative_plan`、`suggested_actions`は非権威。これらの文字列からEventを生成しない。
- `mentioned_details`は同一Sceneのprovisional dataで、Scene終了時にProjectionから除外可能だがTranscriptから消さない。
- structured partを先に全受信・検証できないProviderではNarrativeをbufferし、検証成功後に公開する。

### 10.4 Test First

- [ ] 5 Fixtureのtestに加え、Narrativeを「HPが0になった」へ変更しても`proposed_events=[]`ならEvent 0件であるtestを書く。
- [ ] `SemanticValidationContext.facts_by_id`へpredicate/valueを含む可視Factと、別のIDの`gm_only` Factを渡し、Fixtureごとに`publication_visibility`を切り替える。`unrelated-visible-evidence.v1.json`（可視だがclaim内容が別Fact）、`invisible-evidence.v1.json`（不可視）、`unknown-evidence.v1.json`（未知ID）、`evidence-claim-mismatch.v1.json`（IDは実在・可視だがpredicate/value不一致）をそれぞれ `evidence_claim_mismatch`、`invisible_evidence`、`unknown_evidence`、`evidence_claim_mismatch`としてrejectするtestを書く。valid FixtureはID・visibility・claim内容一致でPASSする。
- [ ] `duplicate-resource-proposal.v1.json`（同じHP/resource変更を`proposed_events`へ二重指定）、`duplicate-fact-proposal.v1.json`（同じsubject/predicate/value/visibilityを`proposed_facts`へ二重指定）、`duplicate-materialization.v1.json`（ruling/knowledge/visibility注釈が同じProposalを複製）を`duplicate_proposal`または`invalid_proposal_reference`でrejectするtestを書く。
- [ ] `materializeSemanticResultForTest`の出力を検査し、`proposed_events`の件数と非Fact Event件数、`proposed_facts`の件数と`FactAsserted`件数が一対一で一致し、Ruling / knowledge / visibility配列を増やしてもEvent件数が増えないことをPASSさせる。Phase 1 materializeがcanonical proposalを一度だけappendする証拠とする。
- [ ] `npm test -- tests/contracts/semantic-result.test.ts` を実行し、module missingでFAILすることを確認する。runnerが準備前で失敗する手順は採用しない。
- [ ] `semanticResultV1Schema`とtest-only contract oracleの最小実装でPASSさせる。
- [ ] production `validateSemanticResult`、Event converter、State readerを`src/**`へ追加するとscope testがFAILすることを確認し、先取りcodeを削除する。

### 10.5 実行コマンドと期待結果

```powershell
npm test -- tests/contracts/semantic-result.test.ts
npm run typecheck
rg -n '自由文|Narrative|Authority|公開前|公開後|awaiting_player|aborted|provisional_detail|Evidence|evidence_claim_mismatch|duplicate_proposal|proposed_events|proposed_facts|buffer' docs/specs/semantic-result.md
rg -n 'parseNarrative|eventsFromNarrative|narrativeToEvent|validateSemanticResult|convertSemanticResult' src
```

PASSはvalid Fixtureのみ`ok:true`、Evidence 4種とduplicate 3種が期待code、Narrative-only Event 0、materializeの一対一、禁止関数検索0件。invalid Fixtureをvalidとして期待するとtestがFAILする証拠も残す。

### 10.6 Commit boundary、Gate証拠、rollback

1. `test: Semantic Result の拒否条件を固定する`
2. `feat: Semantic Result の型と構造Schemaを追加する`
3. `docs: Semantic Result と Narrative の契約を分離する`

**リスク:** 高。LLM→State境界と秘密・Visibilityの危険地帯。

**Gate証拠:** 12 mandatory fieldsのAuthority表、valid/invalid Evidence FixtureのID・Visibility・predicate/value判定、`ValidationIssue.code`、duplicate proposalのreject、materialize前後のEvent件数、Narrative-only Event 0、実行commandのFAIL/PASS出力。

**Rollback:** P0-07より先にrevertする。P0-03 Event contractは独立して残せる。

---

## 11. P0-05: Character Sheet Specification

### 11.1 Goal、決定境界、Non-goal

**Goal:** 手書き一ファイルから最初のCharacter初期状態を読み取れるversioned契約を固定する。

**決定する:** YAML一形式、stable Character ID、Name/Alias、HP、resource一種、items、location、optional speech style、最小Ruleset値。

**Non-goal:** Character Creation UI、Skill Tree、複数Ruleset、万能Schema、loaderからEventへ変換するproduction code。

### 11.2 作成ファイルと責務

- `docs/specs/character-sheet.md` — field、制約、初期値がCampaign開始時にEventへ正規化される規則。
- `src/contracts/character-sheet.ts` — YAML parse後のunknown値を検証するTypeScript型とZod構造Schema。file I/O / Campaign初期化は持たない。
- `tests/contracts/character-sheet.test.ts` — valid一件、duplicate Alias、HP範囲、ID kind、location/item IDを検証。
- `tests/fixtures/characters/minimal-character.v1.yaml` — 日本語名・Aliasを持つ手書き一件。Playable contentではなくcontract fixture。

### 11.3 型と Signature

```ts
export interface CharacterSheetV1 {
  readonly schema_version: 1;
  readonly id: `character:${string}`;
  readonly canonical_name: string;
  readonly aliases: readonly string[];
  readonly description: string;
  readonly hp: { readonly current: number; readonly max: number };
  readonly resource: {
    readonly id: `resource:${string}`;
    readonly label: string;
    readonly current: number;
    readonly max: number;
  };
  readonly initial_items: readonly {
    readonly id: `item:${string}`;
    readonly canonical_name: string;
  }[];
  readonly initial_location_id: `location:${string}`;
  readonly speech_style?: {
    readonly first_person: string;
    readonly second_person: string;
    readonly endings: readonly string[];
    readonly forbidden_patterns: readonly string[];
  };
  readonly ruleset: {
    readonly id: "ruleset:neontof-minimal-2d6-v1";
    readonly action_modifier: number;
  };
}

export const characterSheetV1Schema: ZodType<CharacterSheetV1>;
```

`0 <= hp.current <= hp.max`、resourceも同じ、Aliasは空文字と重複禁止、display nameとIDは分離する。初期fileの修正で既存Campaign状態を変えず、Campaign開始時のEvent snapshotが権威になる。

### 11.4 Test First と実行コマンド

- [ ] valid fixture parse testと、`id: npc:*`、HP超過、duplicate Aliasをrejectするtestを書く。
- [ ] `npm test -- tests/contracts/character-sheet.test.ts` を実行し、module missingでFAILすることを確認する。
- [ ] Test内で`YAML.parse()`したunknown値を`characterSheetV1Schema`へ渡し、最小構造SchemaでPASSさせる。production loaderは作らない。
- [ ] Fixtureの日本語Name / AliasがUTF-8でround-tripするtestをPASSさせる。

```powershell
npm test -- tests/contracts/character-sheet.test.ts
npm run typecheck
rg -n 'Character ID|Aliases|HP|Resource|Initial Items|Initial Location|Speech Style|Ruleset' docs/specs/character-sheet.md
```

期待PASSはvalid 1件、invalid各件がfield path付きreject、日本語round-trip一致。

### 11.5 Commit boundary、Gate証拠、rollback

1. `test: Character Sheet の最小入力契約を固定する`
2. `feat: 手書き Character Sheet の構造Schemaを追加する`
3. `docs: Character Sheet の単一形式を定義する`

**リスク:** 高。初期state formatの危険地帯。ただし runtime loaderを作らないためblast radiusは限定。

**Rollback:** P0-06と独立してrevert可能。P0-03 stable ID contractは残す。

---

## 12. P0-06: Scenario Format Specification

### 12.1 Goal、決定境界、Non-goal

**Goal:** 公開情報とGM専用情報を分離した、手書き一ファイルの最小Scenario形式を固定する。

**決定する:** YAML一形式、Scenario ID/version、initial Scene、4〜6 Locations、3〜4 NPCs、World Invariants、Secret 1、Clues 3、Clock 1、success/failure End Condition、全初期事実と`objective` / `goal` / End Conditionの必須`visibility: Visibility`。

**Non-goal:** Scenario Editor、二つ目のformat、Graph DSL、汎用Validator、実Scenario本文、Scenario Runtime、Director。

### 12.2 作成ファイルと責務

- `docs/specs/scenario-format.md` — field、count、stable ID、Visibility、Safety優先、initial Event正規化規則。
- `src/contracts/scenario.ts` — 一形式だけのTypeScript型とZod構造Schema。file I/O / Scenario Runtimeは持たない。
- `tests/contracts/support/validate-scenario-publication.ts` — 宣言済みVisibilityだけをfilterするtest-only oracle。Phase 1 Loaderではない。
- `tests/contracts/scenario.test.ts` — count、ID reference、secret visibility、end conditions、required Visibilityを検証。
- `tests/fixtures/scenarios/minimal-scenario.v1.yaml` — 4 locations、3 NPCs、secret 1、clues 3、clock 1を持つsynthetic contract fixture。PlayableなNarrativeを作り込まない。
- `tests/fixtures/scenarios/missing-objective-visibility.v1.yaml`
- `tests/fixtures/scenarios/missing-npc-goal-visibility.v1.yaml`
- `tests/fixtures/scenarios/missing-end-condition-visibility.v1.yaml`
- `tests/fixtures/scenarios/gm-only-player-publication.v1.yaml`

### 12.3 型と Signature

```ts
export interface ScenarioV1 {
  readonly schema_version: 1;
  readonly id: ScenarioId;
  readonly version: string;
  readonly initial_scene: SceneDefinition;
  readonly locations: readonly LocationDefinition[];
  readonly npcs: readonly NpcDefinition[];
  readonly world_invariants: readonly WorldInvariant[];
  readonly secret: SecretDefinition;
  readonly clues: readonly [ClueDefinition, ClueDefinition, ClueDefinition];
  readonly clock: ClockDefinition;
  readonly end_conditions: {
    readonly success: EndCondition;
    readonly failure: EndCondition;
  };
}

export interface ScenarioText {
  readonly text: string;
  readonly visibility: Visibility;
}

export interface SceneDefinition {
  readonly id: SceneId;
  readonly location_id: LocationId;
  readonly npc_ids: readonly NpcId[];
  readonly objective: ScenarioText;
}

export interface LocationDefinition {
  readonly id: LocationId;
  readonly canonical_name: string;
  readonly description: string;
  readonly visibility: Visibility;
}

export interface NpcDefinition {
  readonly id: NpcId;
  readonly canonical_name: string;
  readonly aliases: readonly string[];
  readonly goal: ScenarioText;
  readonly knowledge: readonly {
    readonly statement: string;
    readonly visibility: Visibility;
  }[];
}

export interface WorldInvariant {
  readonly id: InvariantId;
  readonly statement: string;
  readonly visibility: Visibility;
}

export interface SecretDefinition {
  readonly id: SecretId;
  readonly text: string;
  readonly visibility: Visibility;
}

export interface ClueDefinition {
  readonly id: ClueId;
  readonly text: string;
  readonly location_ids: readonly LocationId[];
  readonly visibility: Visibility;
}

export interface ClockDefinition {
  readonly id: ClockId;
  readonly label: string;
  readonly segments: number;
  readonly initial: number;
  readonly visibility: Visibility;
}

export type EndCondition =
  | {
      readonly id: EndConditionId;
      readonly kind: "clues_discovered";
      readonly clue_ids: readonly [ClueId, ClueId, ClueId];
      readonly visibility: Visibility;
    }
  | {
      readonly id: EndConditionId;
      readonly kind: "clock_reached";
      readonly clock_id: ClockId;
      readonly value: number;
      readonly visibility: Visibility;
    };

export const scenarioV1Schema: ZodType<ScenarioV1>;
// tests/contracts/support/validate-scenario-publication.ts だけに置く。
export interface ScenarioVisibilityIssue {
  readonly path: readonly (string | number)[];
  readonly code: "missing_visibility" | "invisible_scenario_content";
}
export function validateScenarioPublicationForTest(
  scenario: ScenarioV1,
  publication_visibility: "player_visible" | NpcId,
): readonly ScenarioVisibilityIssue[];
```

Location数4〜6、NPC数3〜4、Secretはexactly 1、Clueはexactly 3、Clockはexactly 1。全reference IDは同一file内で解決する。`SceneDefinition.objective`、`NpcDefinition.goal`、両End Condition、Location、Knowledge、World Invariant、Secret、Clue、Clockなどの初期事実は、すべて必須 `visibility: Visibility` を持つ。SchemaはSecretを`gm_only`に限定し、player-visibleなSecretをrejectする。Safety ConstraintはWorld InvariantやScenario指示より優先する。player-visible fieldからsecret textへ参照するfieldを持たせない。Phase 1 Loaderはfield名、section名、文字列内容からVisibilityを推測せず、欠落をrejectして宣言済みVisibilityだけをfilterへ渡す。

### 12.4 Test First と実行コマンド

- [ ] valid fixture、Location 3件、NPC 5件、Secret visibility変更、initial Sceneのunknown Location / NPC、missing failure Endをrejectするtestを書く。
- [ ] valid fixtureの`objective.visibility`、`goal.visibility`、success/failure `EndCondition.visibility`、既存の各初期事実Visibilityを検証する。`missing-objective-visibility.v1.yaml`、`missing-npc-goal-visibility.v1.yaml`、`missing-end-condition-visibility.v1.yaml`は`missing_visibility`としてrejectする。
- [ ] `gm-only-player-publication.v1.yaml`を`validateScenarioPublicationForTest(scenario, "player_visible")`へ渡し、`invisible_scenario_content`としてrejectする。`player_visible`の正常系Fixtureはissues `[]`でPASSし、`npc:<id>`公開では一致するNPC VisibilityだけがPASSする。Schemaがfieldを受理するだけ、またはSection名を見て推測するだけのtestはGate証拠にしない。
- [ ] `npm test -- tests/contracts/scenario.test.ts` を実行し、module missingでFAILすることを確認する。runnerが準備前で失敗する手順は採用しない。
- [ ] Test内で`YAML.parse()`したunknown値を`scenarioV1Schema`へ渡し、最小構造SchemaでPASSさせる。production loaderは作らない。
- [ ] secret sentinelをplayer-visible subset相当のFixture field検索で0件にするtestを入れる。Context Builderは作らない。

```powershell
npm test -- tests/contracts/scenario.test.ts
npm run typecheck
rg -n 'Scenario ID|Version|Initial Scene|Locations|NPC|objective|goal|World Invariants|Secret|Clues|Clock|Success|Failure|visibility|gm_only' docs/specs/scenario-format.md src/contracts tests/contracts
```

期待PASSはvalid 1件、required Visibility欠落3件と`gm_only` player公開1件が期待codeでreject、player_visible正常系1件、全invalidがfield path付きreject、secret sentinelのpublic field出現0件。Phase 1 Loaderは宣言済みVisibilityを読み、推測しない。

### 12.5 Commit boundary、Gate証拠、rollback

1. `test: Scenario の最小入力契約を固定する`
2. `feat: 手書き Scenario の構造Schemaを追加する`
3. `docs: Scenario の単一形式と秘密境界を定義する`

**リスク:** 高。Scenario formatと秘密境界の危険地帯。

**Gate証拠:** `objective`、`goal`、End Condition、各初期事実の`visibility: Visibility` schema、欠落/`gm_only` player公開のValidationIssue、player_visible正常系、Phase 1 LoaderがVisibilityを推測しないことを記録したspec。

**Rollback:** P0-05 / P0-04と独立してrevert可能。P0-03 stable ID / Visibilityは残す。

---

## 13. P0-07: Test Provider and Fixture Strategy

### 13.1 Goal、決定境界、Non-goal

**Goal:** APIキー、課金、network、出力揺れなしで、success、failure、retry、timeout、invalid JSON、同一Fixtureの決定性を表現できるTest Providerを持つ。

**決定する:** provider-neutral request/response envelope、single function injection、Fake、Scripted step、Recorded Fixture format、raw requestを保持しないsanitized call logのSignatureとshape、公開Contextの別Visibility filter契約、error taxonomy。

**Non-goal:** 実 Provider Adapter、Provider registry、capability negotiation、複数実Provider、production retry loop、Turn Engine、raw実Response収集。

### 13.2 作成ファイルと責務

- `docs/specs/test-provider-and-fixtures.md` — Fixture version、sanitization、error、call log、CI policy。
- `src/model/model-invoker.ts` — narrow function typeとrequest/response type。
- `src/model/publication-visibility.ts` — 公開ContextのVisibility filterだけを持つ純粋境界。Context Builder、Prompt生成、秘密取得は持たない。
- `src/model/fake-provider.ts` — 一つの固定responseまたはerrorを返すfactory。
- `src/model/scripted-provider.ts` — step列とinstance-local call log。
- `src/model/recorded-fixture.ts` — sanitized JSON fixture load / validate。network取得機能なし。
- `tests/model/fake-provider.test.ts`
- `tests/model/scripted-provider.test.ts`
- `tests/model/recorded-fixture.test.ts`
- `tests/model/provider-security.test.ts` — sanitized call log、API key/secret field禁止、公開Context filter、sentinel不在を検証。
- `tests/fixtures/providers/normal-turn.v1.json`
- `tests/fixtures/providers/model-error.v1.json`
- `tests/fixtures/providers/timeout.v1.json`
- `tests/fixtures/providers/invalid-json.v1.json`
- `tests/fixtures/providers/retry-then-success.v1.json`
- `tests/fixtures/providers/sanitized-call-log.v1.json` — raw request/contextを含まないsanitized entryだけを持つ。
- `tests/support/materialize-proposed-events.ts` — test-only oracle。validated `proposed_events`を非Fact Eventへ、validated `proposed_facts`を`FactAsserted`へ固定envelope付きで一度だけmaterializeし、`rulings` / `knowledge_changes` / `visibility_changes`をEvent源にしない。productionからimportしない。
- `tests/support/run-invocation-scenario.ts` — test-only driver。Provider stepのsuccess / failure / retry順を再生し、production retry policyを持たない。

### 13.3 型と Signature

```ts
export interface ModelRequest {
  readonly model_call_id: ModelCallId;
  readonly turn_id: TurnId;
  readonly roles: readonly ("referee" | "world_simulator" | "npc_actor" | "narrator")[];
  readonly publication_visibility: "player_visible" | NpcId;
  readonly context: JsonValue;
  readonly output_schema: "semantic-result-v1";
  // API key、secret、credential、任意のSecretStore参照値をfieldとして持たない。
}

export interface ModelUsage {
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly cached_tokens: number;
}

export interface ModelResponse {
  readonly payload: unknown;
  readonly usage: ModelUsage;
}

export type ModelInvoker = (request: ModelRequest) => Promise<ModelResponse>;

export type ProviderStep =
  | { readonly kind: "success"; readonly response: ModelResponse }
  | { readonly kind: "model_error"; readonly code: string; readonly message: string }
  | { readonly kind: "timeout" }
  | { readonly kind: "invalid_json"; readonly body: string };

export type SanitizedProviderErrorCode = "model_error" | "timeout" | "invalid_json" | "script_exhausted";

export interface ProviderCallLogMeta {
  readonly attempt: number;
  readonly status: "succeeded" | "failed" | "timed_out" | "rejected";
  readonly usage: ModelUsage | null;
  readonly context_item_count: number;
  readonly error_code: SanitizedProviderErrorCode | null;
}

export interface SanitizedProviderCallLogEntry {
  readonly request_id: ModelCallId;
  readonly attempt: number;
  readonly publication_visibility: "player_visible" | NpcId;
  readonly context_digest: string;
  readonly context_item_count: number;
  readonly usage: ModelUsage | null;
  readonly status: "succeeded" | "failed" | "timed_out" | "rejected";
  readonly error_code: SanitizedProviderErrorCode | null;
}

// 既存名を使うconsumerの型名。raw ModelRequest / contextは含まない。
export type ProviderCallLogEntry = SanitizedProviderCallLogEntry;

export interface TestProvider {
  readonly invoke: ModelInvoker;
  readonly calls: readonly SanitizedProviderCallLogEntry[];
}

export interface RecordedFixtureV1 {
  readonly fixture_version: 1;
  readonly name: string;
  readonly steps: readonly ProviderStep[];
  readonly expected: {
    readonly call_count: number;
    readonly final_outcome: "success" | "model_error" | "timeout" | "invalid_json";
    readonly proposed_events: readonly ProposedEvent[];
  };
}

export function createFakeProvider(step: ProviderStep): TestProvider;
export function createScriptedProvider(steps: readonly ProviderStep[]): TestProvider;
export function loadRecordedFixture(source: string): RecordedFixtureV1;
export function createRecordedFixtureProvider(source: string): TestProvider;
export function sanitizeProviderCallLog(input: ModelRequest, meta: ProviderCallLogMeta): SanitizedProviderCallLogEntry;
export function filterContextByVisibility(
  facts: readonly FactRecord[],
  publication_visibility: "player_visible" | NpcId,
): readonly FactRecord[];

export interface FixtureEventContext {
  readonly campaign_id: CampaignId;
  readonly session_id: SessionId;
  readonly scene_id: SceneId;
  readonly turn_id: TurnId;
  readonly event_ids: readonly EventId[];
  readonly first_sequence: number;
  readonly occurred_at: string;
  readonly origin: EventOrigin;
  readonly visibility: Visibility;
}

export interface InvocationScenarioResult {
  readonly attempts: number;
  readonly outcome: "success" | "model_error" | "timeout" | "invalid_json";
  readonly response: ModelResponse | null;
}

// tests/support 配下だけで定義し、src/** から import しない。
export function materializeProposedEvents(events: readonly ProposedEvent[], context: FixtureEventContext): readonly DomainEvent[];
export function runInvocationScenarioForTest(provider: TestProvider, maxAttempts: number): Promise<InvocationScenarioResult>;
```

`ModelRequest`にAPI key / secret fieldを作らない。公開ContextのVisibility filterは `filterContextByVisibility(facts, publication_visibility)` という別の純粋契約であり、`sanitizeProviderCallLog`の責務と混ぜない。filterは`player_visible`または対象NPCへ明示的に可視なFactだけを返し、`gm_only`を返さない。完全なContext BuilderやPrompt生成はPhase 1に残す。

`sanitizeProviderCallLog(input, meta)`は `input.model_call_id`、`input.publication_visibility`、canonical JSONのSHA-256 `context_digest`、`meta.context_item_count`、usage、status、error_codeだけを返す。返り値にraw `ModelRequest`、`context`、roles、payload、任意JSON、環境変数、error messageを保持しない。`ProviderCallLogEntry`はこのsanitized shapeの別名であり、任意の`request` fieldを追加しない。Recorded Fixtureは`fixture_version:1`とexpected call count / validated proposed eventsを持つ。同じFixtureと固定envelope contextから同じEvent Sequenceを得る。

`TestProvider`はP0-07に必要な観測用return typeであり、production Provider hierarchyではない。実 ProviderがPhase 1で一つ現れるまでregistry、base class、capability flagを追加しない。

ROADMAPの「Turn Engineの成功、失敗、再試行をテストできる」は、Phase 0では `ModelInvoker` を注入でき、test-only driverで各stepとattempt順を決定論的に再生できることとして検証する。production Turn Engine、retry policy、Event appendはPhase 1の範囲なので作らない。P0-07の成果物だけで、Phase 1のTurn Engine testがnetworkやAPI keyを要求せず同じscenarioを注入できる状態にする。

### 13.4 Test First

- [ ] fixed success、model error、timeout、invalid JSON、retry-then-success、script exhaustをtestに書く。
- [ ] `provider-security.test.ts` に、`sanitizeProviderCallLog(input: ModelRequest, meta: ProviderCallLogMeta)`の返り値が`request`、`context`、任意JSON、API key / secret fieldを持たないtestを書く。`ModelRequest`へAPI key fieldを追加するcompile-time shape testもrejectする。
- [ ] 公開Context filterへ`gm_only`、`player_visible`、対象外NPC、対象NPCのFactを渡し、player公開とNPC公開の結果を固定する。filterは`sanitizeProviderCallLog`とは別のtestで検証する。
- [ ] `TOP_SECRET_SENTINEL`をModelRequestのcontext、model response、error pathへtest内だけで注入し、sanitized output、captured log、Recorded Fixtureファイルにsentinelが現れないことを検証する。Fixtureには実sentinelを書かず、`<redacted>`だけを置く。
- [ ] call count / order、同一Fixtureから同一validated proposed Event Sequenceをtestする。
- [ ] `npm test -- tests/model` を実行し、module missingでFAILすることを確認する。runnerが準備前で失敗する手順は採用しない。
- [ ] `ModelInvoker`と3 factoryを最小実装しPASSさせる。
- [ ] `normal-turn` FixtureのNarrativeだけを変えてもEvent Sequenceが不変、`proposed_events`を変えるとtestがFAILすることを確認する。
- [ ] 実 Provider、network、`.env`なしで全testを再実行する。

### 13.5 実行コマンドと期待結果

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
npm test -- tests/model
npm test -- tests/contracts/semantic-result.test.ts tests/model/recorded-fixture.test.ts
npm run typecheck
rg -n 'sk-[A-Za-z0-9]{20,}|TOP_SECRET_SENTINEL' tests/fixtures src/model
rg -n 'ProviderRegistry|Capability|Plugin|Hook|Profile' src tests
```

PASSはprovider test全成功、retry fixture call countの期待一致、同じEvent Sequence deep equal、sanitized logにraw request/contextがなく、公開Context filterが期待通りで、`tests/fixtures`と`src/model`に実secret値・sentinelがなく、abstraction検索0件。test sourceのsentinel注入は安全性testの入力であり、output、captured log、Fixtureへ漏れていないことをtestで確認する。`invalid-json`を成功扱いへ変える、または`ProviderCallLogEntry.request`を復活させるとtestまたは検索がFAILすることを確認して戻す。

### 13.6 Commit boundary、Gate証拠、rollback

1. `test: Provider の成功失敗Fixtureを固定する`
2. `feat: API不要のFakeとScripted Providerを追加する`
3. `feat: 記録済みProvider Fixtureを再生する`
4. `docs: Test Provider とFixtureの安全境界を定義する`

**Gate証拠:** API key除去command、Fixture別test結果、call count、Event Sequence hashまたはJSON、`SanitizedProviderCallLogEntry`のshape（request/context/raw payloadなし）、`sanitizeProviderCallLog` Signature、公開Context filterの結果、sentinelのoutput/log/Fixture検索0件、実Provider file 0件。

**リスク:** 高。将来のModel Gateway seamとFixture秘密漏洩に影響する。

**Rollback:** P0-07だけをrevertできる。P0-04 Semantic Result contractは残す。匿名化前実Responseが混入した場合はcommitせず即時停止し、credential rotationの要否をユーザーへ報告する。

---

## 14. 重量パスのレビューと統合

各危険地帯diffは次を満たしてからcommitする。

1. 実装者と別の最上位 `impl-reviewer` が承認済み計画、Authority、Visibility、version、Phase Non-goalを一次レビューする。
2. 非メイン側 AI がclean contextで独立二次レビューする。Codexメイン時のコマンド:

   ```powershell
   claude -p "まず .claude/agents/impl-reviewer.md を読み、その役割を完全に引き受けよ。docs/plans/phase-00-foundation.md と対象diffを突き合わせ、Event Log単一権威、Semantic Result/Narrative分離、Visibility/秘密、Transcript/Telemetry分離、Phase 0 Non-goal、過剰抽象化をレビューせよ。指摘をblocking/non-blockingへ分類し、位置・帰結・修正案を日本語で返せ。" --model opus --permission-mode plan
   ```

3. blockingだけを修正する。再レビューは対応diffだけ、最大2周。3周目を作らない。
4. P0-04 / P0-05 / P0-06 は独立diffとして並列レビュー可能。P0-07はP0-04 commit後にレビューする。
5. 統合後、部分レビュー済みの内部を再評価せず、重複・Signature / version衝突・dependency逆転・合成退行だけを1回シーム監査する。
6. レビュー済みdiffを依存後続の開始前にcommitする。`git add -A` / `git add .`を使わず、各節のpathを列挙する。

---

## 15. Phase Gate 検証表

| Gate | 証拠command / artifact | 成功条件 |
|---|---|---|
| Stack承認 | `docs/adr/0001-technology-stack.md` | `Accepted`、承認引用、採用/不採用/再評価条件 |
| API key不要 | API key envを除去して`npm test` | 全test成功、network call 0 |
| 空Application | localhost probe | `{"status":"ok"}` |
| Build | `npm run build` | exit 0、`dist/main.js` |
| Format | `npm run format:check` | diff 0 |
| Lint | `npm run lint` | error 0 |
| Type | `npm run typecheck` | error 0 |
| Test | `npm test` | Test Files全件passed |
| CI parity | `actionlint .github/workflows/ci.yml`、`act -W .github/workflows/ci.yml -j quality --pull=false`、または `gh run watch <run-id> --exit-status` と `gh run view <run-id> --json status,conclusion,url` | `.github/workflows/ci.yml` がlocalと同じ6commandを列挙し、故意の`exit 1`をnon-zeroで検出した後、復元後のremote green run URL/statusを記録。act/Dockerもremote runも未確認はGate pending |
| CI failure detection | 一時workflowの`actionlint`、`act`または `gh run watch <failure-run-id> --exit-status`、`gh run view <failure-run-id> --log-failed` | `injected failure probe`、exit code `1`、failure URL/statusを観測し、元workflowへ復元。local文字列検査だけは証拠にしない |
| Event runtime parser | `npm test -- tests/contracts/domain-event-parser.test.ts`、`rg -n 'as DomainEvent|as readonly DomainEvent' src tests` | parser経由でvalid Eventを受信し、unknown field/version、ID grammar、各payload不正を期待codeでreject。cast検索0件 |
| Projection rebuild | `npm test -- tests/contracts/domain.test.ts tests/contracts/turn-status.test.ts` | 同一Event→同一Projection、revert test、`pending → running → awaiting_player → running → committed`、aborted、再起動後awaiting、同一request再送がPASS |
| Semantic分離 | `npm test -- tests/contracts/semantic-result.test.ts` | Narrative-only Event 0、invalid/invisible/unknown/mismatched evidence reject、duplicate proposal reject、materialize一対一 |
| Evidence content match | `npm test -- tests/contracts/semantic-result.test.ts` | 可視Factのpredicate/value一致だけPASS、unrelated visible / invisible / unknown / claim mismatchがそれぞれ期待code |
| Character | `npm test -- tests/contracts/character-sheet.test.ts` | 手書き一file parse、invalid reject |
| Scenario | `npm test -- tests/contracts/scenario.test.ts` | objective/goal/EndConditionを含むrequired Visibility欠落、gm_only player公開をrejectし、player_visible正常系がPASS |
| Fake / Fixture | `npm test -- tests/model` | success/failure/retry/timeout/invalid JSON、sanitized call log、公開Context filter、sentinel不在がPASS |
| Secret不在 | `rg` sentinel / key pattern | source・Fixture 0件 |
| Non-goal不在 | `rg -n 'ProviderRegistry|Capability|Plugin|Hook|Profile|WebSocket|React' src tests` | 0件。ADR比較文書は除外 |
| Harness整合 | `node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF` | 展開差分0 |
| 行末 | `git diff --numstat` と `git diff --ignore-cr-at-eol --numstat` | 同一 |
| 生成物不在 | `git status --short` | `dist`、DB、key、harness追跡なし |
| Status Report | `docs/status/phase-00-foundation.md` | Gate結果、出力、Known Issues、Phase 1停止 |

Phase 0 final verification:

```powershell
npm ci
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
node C:/Users/KINGkawamura/Documents/MyWorkflow/deploy.mjs NeontoF
git diff --check
git diff --numstat
git diff --ignore-cr-at-eol --numstat
git status --short
```

Phase完了報告にはcommand名だけでなく実出力を貼る。実Providerの一回きりの出力をGate証拠に使わない。

---

## 16. 既知リスクと rollback 戦略

| リスク | level | 予防 / 検出 | rollback |
|---|---|---|---|
| Stack選択の誤り | 高 | 公式一次資料、Codex実測、Claude独立裏取り、1日spike、承認B | ADRと基盤commitをrevert、正本再展開。Phase 1開始前に限定 |
| Event contract過剰固定 | 高 | Fixtureで使うfieldだけ、Event version、cold-reader review | 依存commitを逆順revert。永続dataなし |
| LLM自由文から状態流入 | 高 | Narrative-only test、禁止関数検索、Semantic reviewer | P0-04/P0-07をrevert、P0-03維持 |
| Secret / API key混入 | 高 | sentinel、fixture scan、request typeにkey fieldなし | commit停止、fixture除去、key実在時はrotation判断を依頼 |
| Transcript / TelemetryをEventに混入 | 高 | union分離、compile-time test、projection input type | P0-03 contract commitをrevertして再設計 |
| Fakeが実Provider抽象化へ肥大 | 中 | function type一つ、registry/capability検索 | P0-07だけrevert |
| CIとlocalの乖離 | 中 | script一元化、同一command、failure injection | CI commitをrevertしP0-01内で修正 |
| MyWorkflow正本と展開先の乖離 | 高 | 正本だけ編集、deploy apply、差分ゼロcheck | MyWorkflow commit revert後に再展開 |
| LF / UTF-8事故 | 中 | `.gitattributes`、numstat比較、BOM/CR検査 | 該当fileだけLF/UTF-8へ修復し再review |
| Phase 1先取り | 高 | path禁止、Non-goal rg、plan diff review | 該当commitをrevert。便利機能として残さない |

---

## 17. Commit boundary と Phase Completion

1. 1 commit = 1 logical change。件名は英語type + 日本語命令形。
2. Failing Test → Minimal Implementation → 文書の順を既定とする。ただしP0-01bはrunnerが未準備の空repoでREDを作らないため、runner bootstrapを独立Commitにしてからfailing test、最小実装、文書の順へ進む。
3. dangerous spec / ADR diffは一次・クロスAI二次レビュー後にcommitする。
4. NeontoFとMyWorkflowを同一commitに混ぜない。各Repositoryで明示stage・review・commitする。
5. commit前に `git diff --check`、numstat 2種、`git status --short`、関係するtestを実行する。
6. Phase completion commitは `docs: Phase 0 の Gate 証拠を記録する` とし、`docs/status/phase-00-foundation.md` だけをstageする。
7. completion commit条件はPhase Gate全件PASS、Known Issues記録、未追跡生成物なし、MyWorkflow差分ゼロ、統合シーム監査blocking 0。
8. pushしない。レビュー済みcommitをlocalに残し、ユーザーへ実出力とcommit IDを報告する。
9. Phase 0 Gate通過後もPhase 1 fileを作らず停止する。

---

## 18. ユーザー判断が必要な点

1. **この詳細計画の承認。** 計画レビュー完了後、実装前に一度待つ。
2. **P0-02 Stackの承認。** `docs/status/p0-02-technology-stack-evaluation.md` の推奨案、比較、スパイク、独立裏取りを読んで判断する。承認前にADR本文・P0-01bのStack依存実装へ進まない。P0-01aのRepository baselineは承認A後に先行する。
3. **CI反映操作。** エージェントはpushしないため、P0-01b commit後にユーザーがbranchをremoteへ反映し、CI runの結果を共有する。これはStack判断とは別の外部Gate証拠である。
4. **Phase 0 Gate後のPhase 1開始判断。** Gateを通過しても自動開始しない。

暫定推奨 A が承認された場合だけ、この計画の TypeScript 固有path・Signature・commandをそのまま実行する。別案を選ぶ場合は Stop Condition に従い、暗黙変換せず計画差分をレビューする。
