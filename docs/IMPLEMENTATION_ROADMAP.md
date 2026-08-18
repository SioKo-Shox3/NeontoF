# NeontoF 実装ロードマップ

- **文書状態**: Draft v0.1
- **作成日**: 2026-08-18
- **対象**: NeontoFを実装する開発者、Codex、Claude Code等の開発エージェント
- **上位仕様**: `NeontoF_PRODUCT_PLAN_v0.2.md`
- **目的**: プロダクト計画を実装可能な段階へ分解し、作業順序、各PhaseのGoal、Non-goal、成果物、受け入れGateを定める
- **推奨配置**: リポジトリでは本書を `docs/IMPLEMENTATION_ROADMAP.md`、上位仕様を `docs/PRODUCT_PLAN.md` として配置する

> **重要**: この文書は、一度に全Phaseを実装するための指示書ではない。  
> 常に現在のPhaseだけを対象とし、受け入れGateを通過してから次のPhaseへ進む。

---

## 1. 文書の使い方

### 1.1 仕様の優先順位

文書間で矛盾がある場合、次の順で判断する。

1. ユーザーからの最新の明示指示
2. `NeontoF_PRODUCT_PLAN_v0.2.md`のCore原則と非交渉要件
3. 本書のPhase順序、Goal、Non-goal、受け入れGate
4. 現在Phase用の詳細Implementation Plan
5. ADR、個別仕様、コードコメント

旧`NeontoF_PRODUCT_PLAN.md` Draft v0.1はレビュー記録として残せるが、実装判断には使用しない。

### 1.2 本書と詳細Implementation Planの違い

本書はMaster Roadmapであり、技術スタック未確定の段階でファイルパスや関数名を固定しない。

各Phaseを開始する前に、開発エージェントは次の形式でPhase別の詳細計画を作る。

```text
docs/plans/phase-00-foundation.md
docs/plans/phase-01-first-playable.md
docs/plans/phase-02-playtest-hardening.md
...
```

Phase別計画には、少なくとも次を含める。

- 作成・変更する正確なファイルパス
- 型、Interface、関数Signature
- 依存関係
- Test Firstの手順
- 実行コマンド
- 期待する失敗と成功結果
- Commit単位
- Phase Gateの検証方法

### 1.3 エージェントへの基本命令

- 現在PhaseのNon-goalを実装しない
- 将来必要そうという理由だけで抽象化しない
- 二つ目の実装がないInterfaceを一般化しない
- LLM出力を自由文から状態へ直接反映しない
- 失敗TurnのTranscriptとTelemetryを消さない
- 実モデルなしで大半のテストを実行可能にする
- 各Work Packageを独立してReview可能な単位にする
- 作業後は必ずテスト、静的解析、フォーマット、差分確認を行う
- Phase Gateを通過しても、自動的に次Phaseへ進まない
- 人間による通しプレイがGateに含まれる場合、コード上のテストだけで完了扱いにしない

---

## 2. 全Phase共通の非交渉要件

以下はPhaseに関係なく守る。

### 2.1 データと状態

1. Event Logをゲーム状態に関する唯一の権威ある永続記録とする
2. StateとCanonはEventから再構築可能なProjectionとする
3. LLMはStateを直接変更しない
4. 状態変更は検証済みEventのappendを経由する
5. Entityは安定IDで参照し、名前を主キーにしない
6. 事実には可視範囲を持たせる
7. Summary、Index、Cacheは削除しても正史を失わない

### 2.2 Turn

1. Turnは`pending / running / awaiting_player / committed / aborted`を表現できる
2. Player Inputには冪等性キーを持たせる
3. Event appendは単一のトランザクション境界で行う
4. TranscriptとTelemetryはゲーム状態のトランザクション外へappendする
5. 直前TurnのUndoは削除ではなく`TurnReverted` Eventで表現する

### 2.3 LLM

1. Semantic ResultとNarrativeを分離する
2. Structured Resultを検証してからEventへ変換する
3. 公開向けモデル呼び出しへ、公開先に不可視な情報を渡さない
4. 非信頼テキストを読むRoleへ状態変更Toolを渡さない
5. 過去の事実に言及する場合、Evidence IDを要求する
6. Evidenceが存在しない場合、過去を推測しない
7. モデル呼び出し前に予算を確認する

### 2.4 乱数

Dice Seedを次から導出する。

```text
H(campaign_seed, turn_id, action_id, roll_index)
```

導出材料と結果を記録する。

### 2.5 実装方針

1. 最初のProviderは一つ
2. 最初のRulesetは一つ
3. 最初のScenario形式は一つ
4. Plugin ABI、Manifest、Profile体系は必要になるまで作らない
5. Public SaaS、決済、マルチテナントは全Phase共通で対象外

---

## 3. Phase構成

| Phase | 名称 | 主な検証 |
|---|---|---|
| 0 | Foundation Contracts | 後から変えると高くつく契約だけを固定できたか |
| 1 | First Playable Local Web Slice | 一人で最初から最後まで遊び、もう一度遊びたいと思えるか |
| 2 | Playtest and Reliability Hardening | 10〜20時間の実プレイで頻出する破綻を抑えられたか |
| 3 | Long Campaign Memory and Recall | 長期キャンペーンの過去を根拠付きで扱えるか |
| 4 | Self-hosted Single-tenant Platform | 別環境へデプロイして継続運用できるか |
| 5 | Proven Extension Seams | 二つ目の具体例から妥当な拡張境界を抽出できたか |
| 6 | Multiplayer Sessions | 2〜4人で秘密と順序を保ちながら遊べるか |
| 7 | Ecosystem and Rich Session Tools | 外部制作者と高度なセッション機能へ拡張する価値があるか |

Phase 7は必須ではない。Phase 6までにプロダクト目標の中核は達成できる。

---

## 4. Phase 0: Foundation Contracts

### 0.1 Goal

後から変更するとEvent履歴、セーブデータ、テスト、全機能へ波及する契約だけを決め、最初の実装を始められる状態にする。

このPhaseの目的はフレームワークを作ることではない。Phase 1のVertical Sliceを迷わず実装するための最小限の土台を作ることである。

### 0.2 Non-goal

- 実際のScenarioを遊べる状態
- 完成したWeb UI
- 完全なCanon Ledger
- Recall用検索基盤
- Plugin、Hook、Profile
- 二つ目のProvider
- 認証、Docker、公開デプロイ
- 複数人対応
- 汎用Scenario Editor
- 本格的な戦闘システム

### 0.3 Entry Conditions

- `NeontoF_PRODUCT_PLAN_v0.2.md`がリポジトリに配置されている
- 本ロードマップがリポジトリに配置されている
- 使用するGit運用方針が決まっている

### 0.4 Work Packages

#### P0-01: Repository and Quality Baseline

**目的**: 以降の作業を自動検証できる最小のRepository構造を作る。

**成果物**:

- Build、Test、Format、Lintのコマンド
- CIで同じコマンドを実行する設定
- `src`と`tests`の責務分離
- `.env.example`。実APIキーは含めない
- `docs/adr`、`docs/specs`、`docs/plans`、`docs/status`

**受け入れ**:

- APIキーなしでTest Suiteが通る
- 空のApplicationがlocalhostで起動できる
- Build、Test、Lint、Formatの失敗がCIで検出される

#### P0-02: Technology Stack ADR

**目的**: Phase 1で迷わないため、実装言語、Web方式、Database、Provider、Streaming方針を一度決める。

**ADRに必ず記録する項目**:

- Server言語とRuntime
- Web Frameworkまたは標準HTTP機能
- Client方式
- Database
- Migration方式
- Validation Library
- 最初のModel Provider
- Fake Providerの方式
- SSE、WebSocket、またはHTTP Streamingの選択
- 日本語全文検索へ拡張する経路
- Docker化の将来経路

**選定基準**:

- 一人で保守できる
- SQLite等の単一トランザクションを使いやすい
- Structured Validationを強く行える
- Fake Providerへ差し替えやすい
- BrowserとServerを分離できる
- 日本語検索へ拡張できる
- Streaming非対応時にも正しさを維持できる

**受け入れ**:

- 一つのStackを選び、採用理由と不採用理由がADRに記録されている
- 選択を保留したままPhase 1へ進まない

#### P0-03: Core Domain and Event Model Specification

**目的**: Event Logを唯一の権威として扱うための最小Domainを固定する。

**対象概念**:

- Campaign
- Session
- Scene
- Turn
- Entity
- Event
- Fact Projection
- State Projection
- Transcript Entry
- Telemetry Entry

**最低限定義するEvent**:

- `CampaignCreated`
- `SessionStarted`
- `SceneStarted`
- `SceneEnded`
- `PlayerInputAccepted`
- `DiceRolled`
- `ResourceChanged`
- `CharacterMoved`
- `ClockAdvanced`
- `FactAsserted`
- `FactSuperseded`
- `TurnCommitted`
- `TurnReverted`
- `SessionEnded`

**追加要件**:

- Event IDからFact IDを決定論的に導出できる
- `origin`で作中の発見と卓外訂正を区別できる
- Event Versionを持ち、Migration可能にする
- ProjectionをEventから再生成できる

**受け入れ**:

- Domain Specだけを読んで、Stateの直接更新が禁止されていると理解できる
- Event Sequenceから同じProjectionを再構築するTest Caseが書ける

#### P0-04: Semantic Result Specification

**目的**: LLMの自由文を状態更新の入力にしないため、出力契約を固定する。

**必須Field**:

```yaml
rulings: []
proposed_events: []
proposed_facts: []
knowledge_changes: []
visibility_changes: []
clarification_request: null
rejection: null
narrative_plan: []
narrative: ""
mentioned_details: []
evidence: []
suggested_actions: []
```

**仕様へ含める**:

- FieldごとのAuthority
- 公開前検証と公開後照合の区別
- `awaiting_player`への遷移条件
- `aborted`への遷移条件
- `provisional_detail`の寿命
- Evidence IDの検証規則
- 非Streaming fallback

**受け入れ**:

- 無効なEvent、不可視Evidence、曖昧入力、拒否入力を表現できる
- Narrative本文をparseしなくても状態変更を確定できる

#### P0-05: Character Sheet Specification

**目的**: 最初のTurnを開始できる初期状態を場当たりで作らない。

**最小内容**:

- Character ID
- NameとAliases
- Description
- HP
- Resource 1種
- Initial Items
- Initial Location
- Optional Speech Style
- Ruleset固有の最小値

**Non-goal**:

- Character Creation UI
- 複雑なSkill Tree
- Ruleset非依存の万能Schema

**受け入れ**:

- 一つの手書きファイルからCharacterを初期化できる仕様になっている

#### P0-06: Scenario Format Specification

**目的**: 最初のScenarioを執筆できる最小形式を固定する。

**最小内容**:

- Scenario IDとVersion
- Initial Scene
- Locations 4〜6
- NPC 3〜4
- World Invariants
- Secret 1
- Clues 3
- Clock 1
- Success End Condition
- Failure End Condition

**Non-goal**:

- 複数Scenario形式
- Editor
- 汎用Graph DSL
- 完全なSchema Validator

**受け入れ**:

- 手書きの一ファイルだけで最初のScenarioを表現できる
- 公開情報とGM専用情報を区別できる

#### P0-07: Test Provider and Fixture Strategy

**目的**: 課金とモデル出力揺れに依存しないTest Harnessを最初から持つ。

**成果物**:

- Fake Provider
- Scripted Response Provider
- Recorded Fixture Provider
- Provider Call Log
- Model Error、Timeout、Invalid JSONのFixture

**受け入れ**:

- APIキーなしでTurn Engineの成功、失敗、再試行をテストできる
- 同じFixtureから同じEvent Sequenceを得られる

### 0.5 Phase Gate

Phase 0完了には、次のすべてが必要である。

- Stack ADRが承認されている
- Core Domain/Event Specがある
- Semantic Result Specがある
- Character Sheet Specがある
- Scenario Format Specがある
- Fake ProviderでTestが実行できる
- EventからProjectionを再構築する最小Testが通る
- Plugin、Profile、複数Providerの実装が入っていない

### 0.6 Stop Conditions

次が発生したら、Phase 0を拡張せずに設計を縮小する。

- SpecがPhase 1のコードより先に大規模化している
- 二つ目の実装を想定したInterfaceが多数作られている
- Hook、Manifest、Capability Graphの設計へ進み始めた
- 1週間相当の作業後もScenarioの一Turnを通せない

---

## 5. Phase 1: First Playable Local Web Slice

### 1.1 Goal

localhostでServerを起動し、ブラウザから一人で1〜2時間のScenarioを開始から終了まで遊べる状態を作る。

Phase 1の最重要Gateは、技術的正しさだけではない。

> 実装者本人が最後まで遊び、翌日もう一度遊びたいと思った。

思わなかった場合は、次Phaseへ進まず、体験上の原因を記録する。

### 1.2 Non-goal

- 完全なRecall Gate
- 日本語全文検索
- Vector Database
- Summary階層の最適化
- 二つ目のProvider
- 二つ目のRuleset
- Turn PlannerとStrict Path
- Economy / Balanced / Qualityの三モード
- Plugin、Hook、Profile
- 認証
- Docker配布
- 公開サーバー
- 複数人
- 本格戦闘
- Character Creation UI
- Scenario Editor

### 1.3 Entry Conditions

- Phase 0 Gateを通過している
- Stack ADRと4つの最小Specが存在する
- Fake Provider Testが動く

### 1.4 実行方式

- 一般Turnは一つのFast Pathで処理する
- DirectorはScene境界だけ別処理にする
- Fast PathへGM専用秘密を渡さない
- Model Providerは一つ
- 通常Turnのモデル呼び出し上限は1回
- Scene開始時のDirector呼び出しは別Budgetとして記録する
- Structured部分を検証できないProviderではNarrativeをbufferしてから公開する

### 1.5 Work Packages

#### P1-01: Event Store and Projections

**成果物**:

- Event append
- Event read by Campaign / Session / Turn
- State Projection
- Fact Projection
- Projection rebuild
- Schema Version

**受け入れ**:

- Event Storeを空にせずProjectionだけ削除し、同じStateとFactを再構築できる
- Stateを直接更新するPublic APIが存在しない
- Event append失敗時に部分Eventを残さない

#### P1-02: Transcript and Telemetry Stores

**成果物**:

- Player Input、Model Request、Model Response、公開Narrativeのappend
- ErrorとRetryのappend
- Tokens、Cost、Latencyのappend
- Turn失敗時にも記録を残す

**受け入れ**:

- Model TimeoutでEventが0件でも、TranscriptとTelemetryへ失敗記録が残る
- 費用の合計がTurn rollbackで減らない

#### P1-03: Turn State Machine

**成果物**:

- `pending`
- `running`
- `awaiting_player`
- `committed`
- `aborted`
- Request IDによる冪等性
- 直前Turnの`TurnReverted`

**受け入れ**:

- 同一Request IDを二回送ってもDiceとEventが一回しか発生しない
- 曖昧入力でStateを変えずに質問を返せる
- `awaiting_player`から同じTurnを再開できる
- 最新TurnだけをUndoできる

#### P1-04: Minimal Rules and Dice

**成果物**:

- 2d6判定
- 目標値
- HP
- Resource 1種
- 状態異常少数
- Clock 1本
- Dice Seed導出

**受け入れ**:

- 同じ導出材料で同じDice結果になる
- ResultとSeedをUIとLogで確認できる
- LLMがDice結果を変更できない

#### P1-05: Character and Scenario Loading

**成果物**:

- 手書きCharacter Sheetの読込
- 手書きScenarioの読込
- Entity、Aliases、Speech Styleの初期化
- Scene、Clock、End Conditionの初期化

**受け入れ**:

- 一ファイルずつからCampaignを開始できる
- Secretがplayer-visible Contextへ入らない

#### P1-06: Model Gateway

**成果物**:

- 一つの実Provider
- Fake Providerとの交換
- Timeout
- Retry上限
- Structured Result Validation
- Usage Record
- Session Budget

**受け入れ**:

- Provider障害で部分Eventを残さない
- Retryが無限に続かない
- Budget超過時に呼び出し前に停止する
- APIキーがResponse、Transcript、Clientへ現れない

#### P1-07: Context Builder and Evidence Validation

**成果物**:

- VisibilityでFactをFilter
- Player-visible FactをContextへ投入
- Evidence IDを付与
- Evidenceの実在性、可視性、内容参照を検証
- Entity Aliasによる単純名寄せ

**受け入れ**:

- 記録にない過去を尋ねるFixtureが「未決定」を返す
- GM専用FactのEvidence IDを返したResponseを拒否する
- Aliasから同じEntityを解決できる

#### P1-08: Semantic Result Pipeline

**成果物**:

- Schema Validation
- `clarification_request`
- `rejection`
- Event Proposal変換
- Fact Proposal変換
- `mentioned_details`
- `suggested_actions`

**受け入れ**:

- Invalid Event Typeを拒否する
- 不明Entity参照を拒否または`awaiting_player`へ送る
- NarrativeだけではStateが変更されない

#### P1-09: provisional_detail

**成果物**:

- Scene内の暫定詳細保存
- Narrativeとの対応付け
- Player参照時の昇格
- Scene終了時の破棄

**受け入れ**:

- Narrativeに出た本棚を次Turnで調べられる
- 昇格時に既存Canonと矛盾すれば自動上書きしない
- 参照されなかった詳細が次SceneのContextを膨張させない

#### P1-10: Minimal Browser Client

**必要画面**:

- Narrative / Chat
- Player Input
- Suggested Actions 2〜4件
- Current Location
- HP
- Resource
- Inventory
- Current Objective
- Clock
- Dice / Ruling
- Cost
- Processing Status

**Non-goal**:

- SPAとしての高度なRouting
- 複雑なDesign System
- Mobile専用UI
- 管理者画面

**受け入れ**:

- BrowserだけでScenarioを完走できる
- Processing Statusが入力直後に表示される
- Reload後に進行中Turnまたは最後の状態を復元できる

#### P1-11: Streaming or Safe Fallback

**成果物**:

- 構造化部分の検証完了後にNarrativeをStreamingする経路
- Providerが順序を保証しない場合のbuffer fallback
- 公開後のEntity、数値照合
- 訂正表示

**受け入れ**:

- 未検証のState変更が画面に確定表示されない
- Streaming非対応でも同じ正しさを維持する
- 公開後矛盾を検出した場合、訂正を表示してLogへ残す

#### P1-12: First Scenario Content

**成果物**:

- 1〜2時間Scenario 1本
- Character Sheet 1件以上
- NPC 3〜4
- 秘密 1
- 手掛かり 3
- Clock 1
- 成功 / 失敗End

**受け入れ**:

- ScenarioがRuntimeの未実装機能へ依存しない
- 重要手掛かりのうち2件以上に複数取得経路がある
- NPCのうち1体以上がClockに基づき能動的に行動する

#### P1-13: First Complete Playtest

**実施内容**:

- Scenarioを最初から最後まで遊ぶ
- 所要時間を記録する
- TurnごとのLatencyとCostを記録する
- 読み飛ばしたNarrativeを記録する
- 入力に迷った箇所を記録する
- 意図を誤解された箇所を記録する
- NPCが受け身だった箇所を記録する
- 正史矛盾と秘密漏洩を記録する

**成果物**:

```text
docs/playtests/phase-01-first-complete-run.md
```

**受け入れ**:

- 成功または失敗Endへ到達した
- 技術的に完走しただけでなく、再プレイ意欲を明記した
- 再プレイしたくない場合、その理由を頻度と重大度で分類した

### 1.6 Phase Gate

次をすべて満たす。

#### Correctness

- EventからStateとFactを再構築できる
- Model失敗で部分Eventを残さない
- TranscriptとTelemetryは失敗Turnも保持する
- 記録にない過去を未決定と扱う
- GM専用秘密を公開Contextへ渡さない
- DiceをSeedとともに再現できる
- Request再送で二重処理しない

#### Experience

- BrowserからScenarioを完走できる
- 現在状況を常時確認できる
- 選択肢サジェストがある
- Clockにより世界が進む
- 処理状況が表示される
- 実装者が翌日もう一度遊びたいと思った、または思わなかった理由が記録されている

#### Scope

- Plugin、Profile、二つ目のProviderが入っていない
- 完全なSearch / Vector DBが入っていない
- 認証とDocker配布が入っていない

### 1.7 Stop Conditions

次の場合はPhase 2へ進まず、Phase 1を縮小または修正する。

- Scenarioを完走できない
- 1Turnの中央値が体感上許容できない
- Narrativeの大半を読み飛ばす
- 入力の選び方が分からず頻繁に停止する
- NPCが待つだけで世界が進まない
- Secretが一度でも公開Contextへ混入した
- EventとProjectionの差異を再構築で解消できない

---

## 6. Phase 2: Playtest and Reliability Hardening

### 2.1 Goal

実際に10〜20時間遊び、頻出する破綻を観測し、頻度と体験影響の高い問題から修正する。

設計者の予想ではなく、実プレイのEvidenceを次の設計判断へ使う。

### 2.2 Non-goal

- 完全な長期Recall
- Vector DB
- Plugin SDK
- 二つ目のRuleset
- 公開デプロイ
- 複数人
- Marketplace

### 2.3 Entry Conditions

- Phase 1 Gateを通過している
- First Playtest Reportがある
- 再プレイ可能なScenarioとSave Dataがある

### 2.4 Work Packages

#### P2-01: Playtest Issue Taxonomy

分類を固定する。

- Consistency
- Intent Misunderstanding
- Pacing
- Excessive Length
- Passive NPC
- Weak Choice
- Rule Error
- Secret Leak
- State Error
- Recall Error
- Cost
- Latency
- UI Confusion

各Issueに次を持たせる。

- Turn ID
- Severity
- Frequency
- Player Impact
- Reproduction Input
- Expected Behavior
- Actual Behavior

#### P2-02: Headless Input Driver

**目的**: 同じ入力列を繰り返し実行できるようにする。

**成果物**:

- JSONL等の入力列
- Fixture Providerまたは実Providerでの再生
- Event、Transcript、Telemetryの比較
- 実行結果Report

**受け入れ**:

- 同じFixture入力から同じEvent結果を得られる
- APIなしの回帰テストとしてCIで実行できる

#### P2-03: Synthetic Canon Test

**成果物**:

- 500件以上の合成Fact
- 任意FactのEvidence確認
- 不可視Factの拒否
- 存在しないFactの未決定応答

**目的**:

実プレイ500Turnを待たず、Fact量増加時の正しさとPrompt量を測る。

#### P2-04: Latency and Cost Baseline

計測する。

- First visible status
- Time to first Narrative token
- Total Turn latency
- Input / Output Tokens
- Cached Tokens
- Cost per Turn
- Cost per Session
- Retry rate

数値目標は実測後に決める。根拠のない事前目標を置かない。

#### P2-05: Prompt and Output Optimization

実測で効果が確認できるものだけ行う。

- Stable Prefix
- Canonical Serialization
- Contextの重複除去
- Narrative文字数上限
- Suggested Action数
- Provider Cache Telemetry

#### P2-06: NPC Initiative and Clock Tuning

- NPC GoalをScene Contextへ含める
- Clock進行条件を明示する
- 一定Turnごとの自動進行だけに依存しない
- NPC行動がPlayer選択を無効化しない

#### P2-07: Session End and Resume

**成果物**:

- `SessionEnded`
- Saveから再開
- 前回までのあらすじ
- Current Objective表示
- Transcript Export

あらすじは派生データとし、削除してもEventとTranscriptから再生成できる。

#### P2-08: Recorded Model Fixtures

実Providerの成功・失敗Responseを匿名化してFixture化する。

- Normal Turn
- Clarification
- Invalid Schema
- Timeout
- Secret Evidence
- Contradictory Narrative
- Long Output

#### P2-09: Second Complete Run

次のいずれかを実施する。

- 同じScenarioを異なる選択で二周目まで完走
- 同じRuntime形式で二本目の小Scenarioを完走

目的は拡張性の証明ではなく、最初のScenario固有の偶然を除くことである。

### 2.5 Phase Gate

- 合計10〜20時間の実プレイ記録がある
- 二回以上の完走記録がある
- 頻出上位5問題が特定され、対応方針が記録されている
- Fake / Fixture TestがCIで動く
- 合成500 Fact Testが動く
- CostとLatencyのBaselineがある
- Sessionを中断し、後日あらすじから再開できる
- Phase 3が必要な理由を、実測したContext量またはRecall失敗で説明できる

### 2.6 Stop Conditions

- 面白さの問題を検索基盤やPlugin設計で解こうとしている
- 実プレイより自動指標整備へ時間を使っている
- 10時間未満のプレイでCanon Schemaを大幅拡張しようとしている
- 二つ目のProvider実装へ寄り道している

---

## 7. Phase 3: Long Campaign Memory and Recall

### 3.1 Goal

複数Sessionにまたがる長期Campaignで、過去の決定、約束、NPC知識、訂正をEvidence付きで扱えるようにする。

Phase 3は「最初から必要だから」ではなく、Phase 2でCanon全件投入がContext、Cost、Recall精度の限界へ達したEvidenceがある場合に開始する。

### 3.2 Non-goal

- 認証
- 公開デプロイ
- 二つ目のProvider
- Plugin SDK
- 複数人
- 任意PDFの完全自動理解

### 3.3 Entry Conditions

次のいずれかを満たす。

- 可視Fact全件がPromptの支配要因になった
- 過去Factの取り違えが実プレイで反復した
- Session数増加によりSummaryだけでは再開できなくなった
- 既存方式のCostが許容範囲を超えた

### 3.4 Work Packages

#### P3-01: Entity Resolution

- Canonical Name
- Aliases
- ひらがな、カタカナ、英字表記
- 単純一致
- 部分一致
- 候補提示
- `awaiting_player`による曖昧解消

指示語や「あの騎士」の完全解決を最初から保証しない。まず名前とAliasを確実に扱う。

#### P3-02: Japanese Search Backend

ADRで次のいずれかを選ぶ。

- N-gram
- 形態素解析
- 日本語対応Database Extension

**受け入れ**:

- 日本語の部分表記でFactとTranscriptを検索できる
- 英語だけのTestで済ませない
- Index削除後に再構築できる

#### P3-03: Recall Gate

フロー:

1. Entity Resolution
2. Visibility Filter
3. Structured Query
4. Full-text Query
5. Vector Candidate Retrievalが必要なら実行
6. Transcript Fallback
7. Evidence Packet
8. Response Validation

結果:

- found
- not_found
- ambiguous
- conflicting
- superseded
- forbidden

#### P3-04: Canon Supersede and Correction

- `FactSuperseded`
- 現在値と旧値
- 作中の新発見
- 卓外訂正
- 事故Undoとの分離

Fact IDはEvent IDから決定論的に導出する。

#### P3-05: Knowledge Holders

- world
- player_character
- npc:<id>
- rumor

同じ命題をHolder違いで保持し、世界の真実とNPCの信念を混同しない。

#### P3-06: Push Consistency Checks

公開後に次を照合する。

- 既知Entity名
- 既知属性
- 数値
- 所持品
- 直近Event
- NPC Speech Style

完全な自然言語含意判定を目標にしない。決定論的に検出できる高頻度問題から始める。

#### P3-07: Summary Hierarchy

- Scene Summary
- Session Summary
- Campaign Recap

SummaryはEvent / Transcriptから再生成可能にする。SummaryをCanonの根拠にしない。

#### P3-08: Long Campaign Benchmark

- 10 Session相当の入力列
- 各時点の期待Fact
- 禁止出力文字列
- Expected State
- Evidence ID

### 3.5 Phase Gate

- 10 Session相当のCampaignを再生できる
- 5 Session前の約束をEvidence付きで回答できる
- 存在しない過去を生成しない
- `forbidden`と`not_found`が公開応答から区別できない
- NPCの誤認と世界の真実を分離できる
- Fact訂正後に現在値と旧値を区別できる
- Search IndexとSummaryを削除して再構築できる
- 日本語AliasからEntityを解決できる

### 3.6 Stop Conditions

- Vector DBをCanonの権威として扱い始めた
- Summaryを状態更新の根拠に使い始めた
- 完全な自然言語理解を前提にしている
- Phase 2で観測されていない分類軸を大量に追加している

---

## 8. Phase 4: Self-hosted Single-tenant Platform

### 4.1 Goal

開発環境以外の新しいHostへNeontoFをデプロイし、管理者がAPIキーを設定して、一人用Campaignを継続運用できる状態にする。

このPhaseで、localhost用Vertical Sliceをセルフホスト可能なWebプラットフォームへ引き上げる。

### 4.2 Non-goal

- NeontoF運営型SaaS
- 決済
- BYOK
- マルチテナント
- 公開マッチング
- 複数人同時プレイ
- 第三者Plugin Marketplace
- 悪意あるPluginの完全隔離

### 4.3 Entry Conditions

- Phase 3までのデータモデルが安定している
- 一人用Campaignを継続して遊べる
- Provider利用量とStorage量のBaselineがある

### 4.4 Work Packages

#### P4-01: Deployment Packaging

- 標準起動手順
- Container Imageまたは同等の配布形
- Persistent Volume
- Health Check
- Version表示
- Upgrade手順

#### P4-02: Authentication

最小の単一テナント認証を実装する。

- 管理者
- プレイヤー
- Session Cookieまたは同等方式
- CSRF等、選択した方式に必要な防御

公開SaaS用の複雑なAccount Recoveryは含めない。

#### P4-03: Secret Management

- APIキーの登録、更新、削除
- Clientへ非表示
- 通常Logへ非表示
- Rotation
- 起動時のSecret Injection

#### P4-04: Room / Campaign / Session Management

- Room作成
- Campaign選択
- Session開始と終了
- Save再開
- Log閲覧
- 一人のParticipant

複数人の順序制御はまだ実装しない。

#### P4-05: Admin Usage and Budget UI

- Provider / Model
- Calls
- Tokens
- Cost
- Cache
- Latency
- Session上限
- Error一覧

#### P4-06: Backup, Restore, Migration

- Database Backup
- Secretを含めないExport
- Restore
- Schema Migration
- Projection Rebuild

#### P4-07: Fresh-host Acceptance Test

開発機とは別の新規環境で、文書だけを使って次を実施する。

1. Install
2. Configure Secret
3. Start Server
4. Create Campaign
5. Play Session
6. Stop
7. UpgradeまたはRestart
8. Resume
9. Backup
10. Restore

### 4.5 Phase Gate

- 新しいHostで手順どおり起動できる
- APIキーがClientと通常Logに現れない
- BackupとRestore後に同じCampaign Stateを得られる
- Migration後にProjectionを再構築できる
- 一人用Scenarioをブラウザから完走できる
- SessionのCostとBudgetを管理画面で確認できる

---

## 9. Phase 5: Proven Extension Seams

### 5.1 Goal

二つ目の具体的実装を追加し、実際の差異からProvider、Ruleset、Scenario、GM構成の拡張境界を抽出する。

抽象化を先に設計するのではなく、既存コードの重複と差異を根拠にRefactorする。

### 5.2 Non-goal

- Marketplace
- 任意言語Plugin ABI
- 悪意あるPlugin Sandbox
- 完全なBackward Compatibility保証
- 大量のHook Point
- あらゆるTRPGへの対応

### 5.3 Entry Conditions

- 一つ目のProvider、Ruleset、Scenarioで実プレイが安定している
- 二つ目を追加する具体的な目的がある
- Refactor前の回帰Testが十分にある

### 5.4 Work Packages

#### P5-01: Second Model Provider

一つ目と異なるAPI特性を持つProviderを追加する。

比較する。

- Structured Output
- Streaming
- Tool Calling
- Prompt Cache
- Usage Metadata
- Error Model

差異からProvider Interfaceを抽出する。

#### P5-02: Second Ruleset

性質の異なるRulesetを一つ追加する。

目的は対応数ではなく、最初のRule Runtimeが特定Systemへ固定されていないか確認することである。

#### P5-03: Second Scenario or Format

必要性がある場合に限り追加する。

- 同じ形式の二つ目のScenarioで足りる場合、Parser抽象化は作らない
- 異なる形式が実際に必要なら、二形式から共通境界を抽出する

#### P5-04: Minimal Profile

実際に比較したい構成だけをProfile化する。

- Provider
- Model
- Ruleset
- GM Policy
- Memory Strategy

階層的なBundle、Patch、全Hook体系は作らない。

#### P5-05: Benchmark Comparison

同じ初期状態と入力列で、Provider、Ruleset設定、GM Policyを比較する。

- Event差分
- Cost
- Latency
- Rule Error
- Recall Error
- Human Rating

#### P5-06: Plugin Decision Gate

正式なPlugin SDKを作るか、内部Module境界のまま維持するか判断する。

作成条件:

- 外部拡張者が実際にいる
- 二つ以上の外部実装候補がある
- Core Repositoryへ直接追加する方式が明確に不便
- VersioningとSecurityのコストを負担する価値がある

### 5.5 Phase Gate

- 二つのProviderを同じCore Contractで利用できる
- 二つのRulesetを同じEvent / Turn基盤で利用できる
- 抽象化前後で既存Scenarioが壊れない
- Profile比較を同じInput Fixtureで実行できる
- Plugin SDKを作るか作らないかの判断がADRに記録されている

---

## 10. Phase 6: Multiplayer Sessions

### 6.1 Goal

2〜4人のPlayerが同じRoomへ参加し、個別のCharacter、知識、秘密を保ちながら、AI GMと一つのScenarioを完走できるようにする。

### 6.2 Non-goal

- 公開マッチング
- 大規模同時接続
- 課金分配
- マルチテナントSaaS
- Voice Chat
- Video Chat
- 高機能VTT
- Tournament運用

### 6.3 Entry Conditions

- 一人用Platformが安定している
- Fact VisibilityとEvent Modelが長期Campaignで検証済み
- Room、Auth、Reconnectの基盤がある

### 6.4 Work Packages

#### P6-01: Participant and Character Ownership

- Participant
- Room Membership
- Character Ownership
- Speaker Identity
- Observer

#### P6-02: Visibility Expansion

`gm_only / player_visible / npc:<id>`から、ParticipantとCharacter単位へ拡張する。

- all_players
- participant:<id>
- character:<id>
- npc:<id>
- gm_only

既存FactのMigrationを行う。

#### P6-03: Turn Coordination

最初は同時処理を行わず、明示的な順番または入力Queueを用いる。

- Turn Owner
- Pending Inputs
- Ready / Confirm
- Timeout
- Cancel
- Duplicate Request

#### P6-04: Group Decision

- 全員確認が必要なScene遷移
- 代表者入力
- 投票またはReady確認
- 判定前の個別資源使用

#### P6-05: Private Information

- 個別Recall
- 個別Message
- Character Knowledge
- 秘密の開示Event
- GMから特定Participantへの通知

#### P6-06: Reconnect and Recovery

- Connection Lost
- Rejoin
- Current Turn Restore
- Awaiting Player Restore
- Duplicate Submission Prevention

#### P6-07: Multiplayer Scenario Test

2〜4人で一つのScenarioを完走する。

記録する。

- 発言者混同
- 秘密漏洩
- 入力待ち
- Queue不満
- GMが誰へ質問したか
- 個別Character知識の混同

### 6.5 Phase Gate

- 2〜4人でScenarioを完走できる
- Participantごとの不可視Factが漏れない
- SpeakerとCharacterを混同しない
- Reconnect後に進行中Turnを復元できる
- 二重入力でEventが重複しない
- Group DecisionがAIの独断で確定されない

---

## 11. Phase 7: Ecosystem and Rich Session Tools

### 7.1 Goal

実利用により必要性が証明された拡張、制作支援、セッション表現を追加する。

### 7.2 Candidate Scope

- Plugin SDK
- Plugin Manifest
- Compatibility Check
- Sandboxing
- Distribution Index
- MCP Adapter
- Scenario Editor
- Ruleset Authoring Tools
- Map
- Token
- Handout
- Dice Visuals
- Voice
- Image Generation
- External Bot
- Public Server Directory

### 7.3 Non-goal

Phase 7の全候補を実装すること。

各項目は独立したProduct Decisionとして扱い、利用者のEvidence、保守費用、安全性を評価して採否を決める。

### 7.4 Gate

各候補について次を満たす場合だけ開始する。

- 実際の利用者要求がある
- 既存手段で代替できない
- Coreの品質を落とさない
- 継続保守できる
- 法的・Security上の扱いが明確である

---

## 12. Phase横断のWorkstream

番号はPhaseをまたぐが、実装は各Phaseで必要な範囲だけ行う。

### W-A: Documentation and ADR

維持する文書:

- Product Plan
- Implementation Roadmap
- Phase Plan
- ADR
- Domain Spec
- Semantic Result Spec
- Character Sheet Spec
- Scenario Spec
- Playtest Report
- Migration Notes

仕様とコードが食い違った場合は、同じ変更で文書も更新する。

### W-B: Testing

Test Pyramid:

1. Pure Domain Unit Test
2. Event / Projection Test
3. Fake Provider Turn Test
4. Recorded Fixture Test
5. Browser Integration Test
6. Limited Real Provider Test
7. Human Playtest

実Provider TestをCIの必須条件にしない。

### W-C: Observability

最初から相関IDを持つ。

- Campaign ID
- Session ID
- Scene ID
- Turn ID
- Model Call ID
- Event ID
- Transcript ID

生ログへSecretを含めない。

### W-D: Data Migration

- Event Schema Version
- Migration Command
- Projection Rebuild
- Backup before Migration
- Migration Test Fixture

v0.1から完全な互換保証はしないが、破壊変更を無言で行わない。

### W-E: Playtest Feedback

各Playtest後に次を更新する。

- Observed Problems
- Frequency
- Severity
- Proposed Fix
- Accepted Fix
- Rejected Fix
- Next Playtest Hypothesis

---

## 13. 優先順位の判断規則

複数の作業候補がある場合、次の順に優先する。

1. State、Canon、Visibilityを壊す不具合
2. Secret漏洩
3. 二重課金、無限Retry、Budget超過
4. Scenarioを完走不能にする不具合
5. プレイヤーの意図を無視して不可逆に進める不具合
6. 直近Turnの忘却や矛盾
7. 待ち時間、文章量、入力迷い
8. NPCの受動性
9. 長期Recall
10. 抽象化、Plugin、開発者体験
11. 見た目のPolish

---

## 14. Scope変更の規則

### 14.1 Phase内へ追加してよいもの

- 現在PhaseのGateを満たすために必須
- 後付けするとEvent互換性を破壊する
- Securityまたは費用暴走を防ぐ
- 実プレイでCriticalと判明した

### 14.2 次Phaseへ送るもの

- 「あると便利」だが完走には不要
- 二つ目の実装がない抽象化
- 公開配布だけに必要
- 将来の複数人だけに必要
- 実測されていない最適化

### 14.3 Product Planへ戻すもの

- 北極星を変える
- Eventを唯一の権威とする方針を変える
- セルフホストWeb最終像を変える
- 複数人を目標から外す
- LLMへState直接変更を許す
- 秘密を渡して守らせる設計へ変える

これらは単なる実装判断ではないため、Product Planの改訂を先に行う。

---

## 15. CommitとReviewの単位

### 15.1 Work Package

各`P*-*`を原則として独立Review可能な単位とする。

一つのWork Packageが大きい場合、次の条件で分割する。

- 独立した受け入れTestがある
- Reviewで一方だけRejectできる
- 後続Packageへ明確なInterfaceを提供する

### 15.2 Commit

推奨順序:

1. Failing Test
2. Minimal Implementation
3. Refactor
4. Documentation

Commit Messageは変更の目的を表す。

例:

```text
feat: add append-only event store
feat: add awaiting-player turn state
fix: reject invisible evidence references
test: cover duplicate turn submission
docs: define semantic result contract
```

### 15.3 Phase Completion

Phase完了CommitまたはTagには次を含める。

- Phase Status Report
- Gate Check結果
- Test結果
- Known Issues
- Playtest Report
- 次Phase開始条件

---

## 16. Codexへ渡す最初の指示

以下を最初の作業開始Promptとして使用できる。

```markdown
NeontoFの開発を開始します。

最初に、次の文書をすべて読んでください。

1. `docs/PRODUCT_PLAN.md`
2. `docs/IMPLEMENTATION_ROADMAP.md`

今回は `Phase 0: Foundation Contracts` だけを対象にします。Phase 1以降の機能は実装しないでください。

最初の作業は次です。

1. 現在のRepository構成と既存ファイルを確認する
2. Phase 0のGoal、Non-goal、Gateを要約する
3. 技術的に後戻りが高い判断と、後回しにすべき判断を分ける
4. `docs/plans/phase-00-foundation.md` に、正確なファイルパス、型、テスト、実行コマンド、Commit単位を含む詳細Implementation Planを書く
5. Implementation Planを自己レビューし、Product PlanおよびRoadmapとの矛盾を修正する
6. この時点では実装を開始せず、Planを提示してレビューを待つ

絶対条件:

- Event Logをゲーム状態の唯一の権威とする
- CanonとStateはEventから再構築可能なProjectionとする
- Semantic ResultとNarrativeを分離する
- Turnに`awaiting_player`を含める
- TranscriptとTelemetryをゲーム状態のトランザクション外へ置く
- Fake ProviderでAPIなしにテストできるようにする
- Plugin、Hook、Profile、二つ目のProviderを作らない
- 将来必要そうという理由だけで抽象化しない
```

---

## 17. 各Phase開始時の共通Prompt

```markdown
`docs/PRODUCT_PLAN.md` と `docs/IMPLEMENTATION_ROADMAP.md` を読み、現在のPhaseだけを実装対象にしてください。

開始前に次を行ってください。

1. 前PhaseのGate結果とKnown Issuesを確認する
2. 現在PhaseのGoal、Non-goal、Entry Conditions、Gateを列挙する
3. Repositoryの現状を確認する
4. Work Packageを依存順に並べる
5. 各Packageについて、正確なファイル、Interface、Failing Test、実行コマンド、Commitを定義する
6. 後続Phaseの機能が混入していないか自己レビューする
7. `docs/plans/phase-XX-*.md` を作成し、実装前にレビューを求める

実装中は、各Work Package完了時に次を報告してください。

- 変更内容
- 変更ファイル
- Test結果
- Gateへの寄与
- Known Issue
- 次PackageとのInterface
```

---

## 18. 完了の定義

NeontoF全体は、Phase 6のGateを通過した時点で、当初の中核目標を満たしたと判断できる。

- 現在のLLMでAI GMを成立させる
- 長期正史をモデル外で保持する
- 根拠のない過去捏造を抑止する
- ルール、状態、秘密をコードで守る
- セルフホストできる
- ブラウザから参加できる
- 一人で始められる
- 複数人で遊べる

Phase 7は完成条件ではなく、利用実績に応じた拡張である。

最終的な判断基準は、機能数ではない。

> 選択が後の展開へ残り、決定事項が失われず、ルール上の結果が尊重され、費用と待ち時間を許容しながら、継続して遊びたいと思えるTRPGが成立していること。
