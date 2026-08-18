# NeontoF プロダクト計画書

- **文書状態**: Draft v0.2 — 外部レビュー反映版
- **作成日**: 2026-08-18
- **対象**: NeontoF の設計、実装、レビューに関わる人および開発エージェント
- **目的**: 実装技術を過度に固定せず、プロダクトの方向、責務境界、非交渉要件、段階的な到達像を定める
- **置換対象**: `NeontoF_PRODUCT_PLAN.md` Draft v0.1
- **実装順序**: `NeontoF_IMPLEMENTATION_ROADMAP.md` を正とする
- **推奨配置**: リポジトリでは本書を `docs/PRODUCT_PLAN.md`、実装ロードマップを `docs/IMPLEMENTATION_ROADMAP.md` として配置する

---

## 0. v0.2で変更した判断

外部レビューのうち、次を採用した。

- 「正しく動く」だけでなく、「実際に遊んで面白い」を最初のVertical Sliceの完了条件へ入れる
- Event Logを唯一の権威ある永続記録とし、CanonとStateをProjectionとして扱う
- Narratorへ新事実の生成を全面禁止するのではなく、新規詳細の捕捉を義務づける
- Turnに`awaiting_player`を含む中断状態を設ける
- TranscriptとTelemetryをゲーム状態のトランザクション境界から分離する
- Streamingと状態変更の原子性を、公開前検証と公開後照合へ分けて両立させる
- Canonの分類を、`kind`、`holder`、`status`、`visibility`へ分解する
- Entityの安定ID、表記、エイリアス、名寄せを最初から設計対象にする
- 日本語の全文検索とトークン量を技術選定上の制約として扱う
- Character SheetとScenario執筆を、Runtime実装とは別の明示的な成果物として扱う
- Plugin、Profile、複数Provider、複数Rulesetは、二つ目の具体例が必要になるまで一般化しない
- 完全なRecall Gate、検索基盤、長期キャンペーン最適化は、一度遊べるものを作ってから拡張する

一方、次は採用しない。

- セルフホスト可能なWebプラットフォームという最終像を外すこと
- 将来の複数人TRPGをプロダクト目標から外すこと
- NeontoFを実装者本人だけが使うローカルアプリとして固定すること

ただし、初期開発では配布、認証、Docker、運用管理、第三者向けプラグイン基盤を作らない。最初はlocalhost上で一人がブラウザから遊べるVertical Sliceを作り、最終像に必要な運用機能は後段で追加する。

---

## 1. エグゼクティブサマリー

NeontoFは、現在利用できるLLMだけで継続的に遊べるTRPGセッションを成立させるための、**AIゲームマスター・ランタイム兼セルフホスト可能なWebプラットフォーム**である。

名称は、かつて存在したオンラインTRPGセッション支援サイト「どどんとふ（DodontoF）」へのオマージュである。ただし、互換実装や直接的な後継を意味しない。

DodontoFがオンライン上の盤面、通信、セッション空間を提供したように、NeontoFは次を提供することを目指す。

- AIゲームマスターによる進行
- ルール裁定
- 世界状態とキャラクター状態の管理
- 長期キャンペーンの正史管理
- NPCごとの知識、信念、目的の管理
- シナリオ進行と逸脱への対応
- ダイスと結果の監査
- コスト、待ち時間、モデル利用量の制御
- ブラウザから参加できるセッション空間
- ルールセット、シナリオ、モデル構成の拡張

NeontoFは将来の万能モデルを待たない。現在のLLMに、記憶、状態、裁定、秘密、演出の全責務を任せると破綻することを前提に、ハーネス側で制約と外部状態を与える。

中心原則は次である。

> AIに決定事項を覚えさせない。  
> NeontoFが決定事項をEventとして保持し、CanonとStateを再構築する。  
> AIには必要な記録だけを見せ、記録を根拠にしない過去回答を許可しない。

---

## 2. 解決する問題

### 2.1 TRPGへ参加する障壁

TRPGには次の参加障壁がある。

- 人を集める必要がある
- 日程調整が必要である
- GMの経験、相性、進行能力に体験が強く依存する
- 長いキャンペーンほど再開が難しい
- 一人で試したいときに遊びにくい

AI GMはこれらを緩和し得るが、単純なチャットボットでは長期プレイに耐えない。

### 2.2 単純なAI GMが破綻する理由

- 過去に決めた名前、場所、約束、手掛かりを保持しない
- 記録にない過去を、それらしく生成する
- 状態変更と文章表現が食い違う
- NPCが知るはずのない秘密を知る
- 物語の都合で失敗や損失を無効化する
- ルールブックにないルールを創作する
- 自由入力に対して受け身になり、物語が動かない
- 文章が冗長になり、テンポが悪くなる
- コンテキストとモデル呼び出しが増え、費用と待ち時間が増大する

### 2.3 NeontoFの差別化

複数Provider、RAG、ダイス、セーブ、Web UI、シナリオ読込は差別化ではなく基礎機能である。

NeontoFの固有価値は次に置く。

> GMの裁定、状態、正史、知識境界、シナリオ進行、演出、費用を分離し、現在のLLMでも継続可能なTRPGとして成立させること。

---

## 3. プロダクト定義

### 3.1 一文での定義

> NeontoFは、現在のLLMをTRPGの役割ごとに制約・編成し、正史、状態、ルール、秘密、費用をモデル外で管理する、セルフホスト可能なAI TRPG実行基盤である。

### 3.2 最終的な提供形態

最終的には、管理者がサーバーへデプロイし、ブラウザからセッションへ参加できる形を目指す。

- セルフホスト
- 単一テナントを基本とする
- サーバー管理者を信頼する
- 管理者がモデルプロバイダーのAPIキーを設定する
- APIキーはサーバーからモデルAPIを呼ぶためだけに使用する
- APIキーはブラウザ、通常ログ、モデルプロンプトへ渡さない
- NeontoF自身がAPI費用を負担する運営型SaaSは前提にしない
- 決済、残高、課金、マルチテナントは初期目標に含めない

### 3.3 最初の提供形態

最初は、実装者がlocalhostで起動し、一人でブラウザから遊べる状態を目指す。

この段階では次を作らない。

- 認証
- 公開サーバー運用
- Docker等の標準配布
- 管理者向け高度な運用UI
- 複数人同時参加
- 第三者プラグイン配布

Webクライアントとサーバー処理は最初から分離するが、配布可能なプラットフォームとしての完成は後段とする。

### 3.4 利用者

最終的には次の利用者を想定する。

1. サーバー管理者
2. ルーム・セッション管理者
3. プレイヤー
4. シナリオ・ルールセット制作者
5. モデル構成・GM方針・拡張機能の開発者

最初のVertical Sliceでは、1〜3を一人の実装者が兼ねる。

### 3.5 最終目標

最終目標は複数人TRPGである。

ただし、複数人対応の複雑さを初期から前払いしない。最初から守るのは次の三点に限定する。

1. Entityを名前ではなく安定IDで参照する
2. 事実に可視範囲を持たせる
3. 状態を直接更新せず、EventをappendしてProjectionを更新する

これにより、一人用の実装を最短化しながら、将来の複数人化を全面的な作り直しにしない。

---

## 4. プロダクト原則

### 4.1 未来の万能モデルを待たない

NeontoFは、現在のモデルが責務衝突、長期記憶、秘密管理、状態整合を単独では扱えないことを前提にする。

### 4.2 モデルは権威ある保存先ではない

コンテキスト、会話履歴、Prompt Cache、Summary、モデル内部の推論を、正史や状態の保存先にしない。

### 4.3 プロンプトと強制機構を分ける

プロンプトで制御するもの:

- 文体
- NPCの演技
- 説明量
- テンポ
- 選択肢の提示方法

コードで強制するもの:

- Eventの追加
- HP、所持品、資源
- ダイス
- 可視性
- APIキー
- 予算
- 状態変更の原子性
- Evidenceの実在性

### 4.4 秘密を渡して守らせない

公開向けのNarrativeを生成するモデル呼び出しには、その公開先に見せてはいけない情報を渡さない。

単一のモデル呼び出しに、公開向け出力の生成と、その公開先に不可視な情報の参照を同時に含めてはならない。

### 4.5 意味を先に、文章を後に扱う

自由文を後から解析して状態へ反映する構造を標準にしない。

各Turnは、まず構造化されたSemantic Resultを生成し、検証した後にNarrativeを公開する。

### 4.6 公開した詳細を失わない

Narrativeが新しい具体物、場所、数量、人物の特徴を生成すること自体は許可する。

ただし、新しい詳細は同一Turn内で`provisional_detail`として捕捉する。プレイヤーが後から行動根拠として利用した場合、矛盾確認のうえCanonへ昇格する。

### 4.7 費用と待ち時間は品質である

費用、応答時間、初回表示までの時間、Prompt Cacheのヒット率を、非機能要件ではなくプレイ品質として扱う。

### 4.8 面白さを最初に検証する

正史管理を完全化してから遊ぶのではない。

最初のVertical Sliceで開始から終了まで通しで遊び、もう一度遊びたいと思えるかを確認する。

### 4.9 実装は必要になってから一般化する

Provider、Ruleset、Scenario、Plugin、Profileの抽象化は、二つ目の具体的実装が必要になるまで最小限にする。

### 4.10 重要判断を監査可能にする

少なくとも次を追跡できるようにする。

- Player Input
- Model RequestとResponse
- 使用したContext
- 提案されたSemantic Result
- 検証結果
- Event
- Dice
- Cost、Tokens、Latency
- 公開されたNarrative

---

## 5. 信頼モデル

### 5.1 信頼するもの

初期版では次を信頼する。

- サーバー管理者
- NeontoF Core
- リポジトリ内の実装コード
- 管理者が設定したモデルProvider

### 5.2 信頼しないもの

- プレイヤー入力
- LLM出力
- 自動生成されたSummary
- シナリオやルール文書に含まれる自然言語
- 外部から取得したテキスト

### 5.3 v0.1のセキュリティ範囲

初期版で必須とする。

- APIキーをクライアントへ渡さない
- LLM出力を検証せず状態へ適用しない
- 非信頼テキストを読むRoleへ状態変更Toolを渡さない
- Validatorへ、検証対象以外の非信頼指示を渡さない
- モデル呼び出し数と費用へ上限を設ける

公開サーバー向けのRate Limit、CSRF、アカウント回復、第三者プラグイン隔離は後段で扱う。

---

## 6. ドメインモデル

### 6.1 最初から必要な概念

- **Campaign**: 世界、正史、キャラクターを継続する単位
- **Session**: 一回のプレイ開始から終了まで
- **Scene**: 場所、登場人物、目的がまとまった進行単位
- **Turn**: 一つのPlayer Inputを受け、結果を公開する処理単位
- **Entity**: Character、NPC、Location、Itemなど、安定IDを持つ対象
- **Character**: プレイヤーが操作するEntity
- **NPC**: 目的、知識、関係、口調を持つEntity
- **Event**: 世界や状態に起きた変更の権威ある記録
- **Fact / Canon Projection**: Eventから導出される、検索しやすい事実表現
- **State Projection**: Eventから導出される現在状態
- **Transcript**: 実際に送受信・公開された内容の記録
- **Telemetry**: API利用、費用、Tokens、Latencyの記録
- **Scenario**: 初期世界、NPC、秘密、手掛かり、クロック、終了条件
- **Rule System**: 判定、資源、状態変更の規則

### 6.2 後から追加する概念

- Server
- Room
- Participant
- Observer
- Character Ownership
- Private Message
- Participantごとの可視性
- 複数入力の順序制御

### 6.3 Entity

Entityには最低限、次を持たせる。

```yaml
id: npc:gareth
kind: npc
canonical_name: ガレス卿
aliases:
  - ガレス
  - がれす
  - 騎士ガレス
  - Gareth
```

名前を主キーにしない。Entityの改名や呼称変更があっても、同一IDを維持する。

NPCの口調も継続対象とする。

```yaml
speech_style:
  first_person: 儂
  second_person: お主
  endings:
    - 〜じゃ
  forbidden_patterns:
    - 丁寧語
```

### 6.4 可視性

最初は次の最小形とする。

- `gm_only`
- `player_visible`
- `npc:<entity_id>`

将来、Participant単位の可視性へ拡張できるデータ形を選ぶ。

Safety Constraintは、ScenarioのHard Constraintより常に優先する。

---

## 7. 全体アーキテクチャ

```text
Browser Client
    ↓ HTTP / SSE / WebSocket
Application Server
    ├─ Session API
    ├─ Turn Engine
    ├─ Context Builder
    ├─ Model Gateway
    ├─ Rule Runtime
    ├─ Scenario Runtime
    └─ Projection Reader

Persistence
    ├─ Event Log           ← ゲーム状態の唯一の権威
    ├─ Transcript Store    ← 失敗Turnも残す
    ├─ Telemetry Store     ← 費用はロールバックしない
    ├─ Secret Store        ← APIキー
    ├─ Canon Projection    ← Eventから再構築
    ├─ State Projection    ← Eventから再構築
    └─ Search Index        ← 後から再構築
```

### 7.1 Core固定の責務

次は交換可能な判断ロジックから分け、Core側の薄い境界として扱う。

- Event appendのトランザクション境界
- Visibility Filter
- LLM出力のSchema Validation
- Budget Guard
- Dice Seed導出
- Transcript append
- Telemetry append
- APIキーの非公開

### 7.2 交換可能になり得る責務

- Model Provider Adapter
- Contextの選択方法
- GM Policy
- Ruleset
- Scenario形式
- Canon Projectionの高度化
- Search Strategy
- Director Strategy
- Narration Style

v0.1では正式なPlugin ABIを作らない。関数やモジュールの境界へ閉じ込め、二つ目の実装が現れた段階で抽象化する。

---

## 8. データの権威と寿命

### 8.1 Event Log

Event Logを、ゲーム世界と状態に関する唯一の権威ある永続記録とする。

例:

- `SessionStarted`
- `SceneStarted`
- `SceneEnded`
- `CharacterMoved`
- `DiceRolled`
- `ResourceChanged`
- `DamageApplied`
- `ClueDiscovered`
- `RelationshipChanged`
- `ClockAdvanced`
- `FactAsserted`
- `FactSuperseded`
- `TurnReverted`
- `SessionEnded`

### 8.2 Canon Projection

CanonはEventから再構築されるProjectionである。

Canonの最小概念は次とする。

```yaml
fact_id: c17
kind: fact | ruling | agreement | plan | promise
holder: world | player_character | npc:<id> | rumor
status: active | disputed | superseded
subject_id: npc:gareth
predicate: name
value: ガレス卿
visibility: player_visible
source_event_id: event:182
```

v0.1では必要な値だけ実装し、完全なbitemporal知識ベースを作らない。

### 8.3 State Projection

現在HP、所持品、位置、資源、状態異常、クロック、現在SceneなどをEventから再構築する。

### 8.4 Transcript

Transcriptはゲーム状態のトランザクション外へappendする。

保持対象:

- Player Input
- Model Request
- Model Response
- Tool Call
- エラー
- 再試行
- 公開されたNarrative
- 訂正表示

Turnが失敗しても、失敗理由と消費済みモデル呼び出しの記録を残す。

### 8.5 Telemetry

Telemetryもゲーム状態のトランザクション外へ記録する。

費用はTurnのロールバックで戻らないため、Event Projectionへ含めない。

### 8.6 派生データ

次は削除しても再生成できなければならない。

- Canon Projection
- State Projection
- Summary
- Search Index
- Embedding
- Cache

---

## 9. Turn実行モデル

### 9.1 Turn状態

```text
pending
  ↓
running
  ├─→ awaiting_player ─→ running
  ├─→ committed
  └─→ aborted
```

`awaiting_player`は次に使う。

- 入力の対象や方法が曖昧
- 判定前に技能、資源、方針を選ばせる
- Scene遷移の確認
- 複数候補のEntity解決

### 9.2 冪等性

各入力にTurn Request IDを持たせる。

- 同一IDの再送は二重処理しない
- 進行中なら進行中のTurnを返す
- 完了済みなら既存結果を返す

### 9.3 基本フロー

1. Player InputをTranscriptへappendする
2. 入力を正規化し、Entityを名寄せする
3. 必要なら`awaiting_player`へ移行する
4. 公開先に応じたVisibility Filterを適用する
5. Contextを構築する
6. 予算を確認する
7. Modelを呼び出す
8. Model RequestとResponse、Telemetryを記録する
9. Semantic Resultを検証する
10. Eventを単一トランザクションでappendする
11. Projectionを更新する
12. Narrativeを公開する
13. 公開後照合を行い、必要なら訂正する

### 9.4 Undo

v0.1では直前のコミット済みTurnだけを戻せる。

Eventを削除せず、`TurnReverted`をappendし、Projectionから対象Turnの効果を除外する。

分岐セーブ、任意時点への時間遡行、複数ブランチは含めない。

---

## 10. Semantic Result

Semantic ResultはNarrativeと分離する。

概念上、次を扱う。

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

### 10.1 公開前に検証するもの

- Schema適合
- Eventの型と参照先
- 現在Stateとの整合
- Visibility違反
- Evidence IDの実在性と可視性
- 予算と呼び出し上限
- `clarification_request`と`rejection`

### 10.2 公開後に照合するもの

- Narrativeに含まれる既知Entityの名前、属性、数値とCanonの矛盾
- NarrativeとEventの数値差
- `mentioned_details`の列挙漏れ
- NPC口調の逸脱

公開後に矛盾を検出した場合、ゲーム状態をロールバックせず、GMが言い直す形で訂正する。

---

## 11. Narrativeと暫定詳細

### 11.1 禁止方式を採らない

Narratorへ「新しい名詞を出すな」と要求すると、描写が成立しない。

そのため、新規詳細の生成は禁止せず、捕捉を義務づける。

### 11.2 provisional_detail

Narrativeに新しく現れた具体的詳細を、同一Turnの`mentioned_details`へ列挙する。

例:

```yaml
- id: pd:scene-4:12
  kind: object
  label: 埃をかぶった本棚
  scene_id: scene:4
  visibility: player_visible
```

### 11.3 昇格

プレイヤーが暫定詳細を行動根拠として参照した場合:

1. EntityまたはFactとして解決する
2. 既存Canonとの矛盾を確認する
3. 問題がなければEventをappendして通常Canonへ昇格する
4. 矛盾する場合は、却下またはGMによる訂正を明示する

### 11.4 寿命

昇格しなかった暫定詳細はScene終了時にProjectionから除外してよい。Transcriptには残す。

---

## 12. 正史、記憶、Recall

### 12.1 用語

- **Event**: 起きたことの権威ある履歴
- **Canon**: Eventから導出された事実のProjection
- **State**: Eventから導出された現在状態
- **Transcript**: 実際に送受信された原記録
- **Memory Context**: 今回モデルへ渡す選択済み情報
- **Summary**: 再生成可能な要約
- **Index**: 検索用派生データ
- **Prompt Cache**: 費用と速度の最適化

### 12.2 最初のRecall方式

Canonが少ない間は、公開先から見て可視なCanonをContextへまとめて投入する。

- 各Factへ短いEvidence IDを付ける
- 過去の事実を再言及する場合、Evidence IDを出力させる
- Evidence IDが存在しない、不可視、または内容と一致しない場合は再生成する
- Evidenceがない場合は「記録上は未決定」と答える

これにより、検索基盤なしでも根拠付き回答を検証できる。

### 12.3 高度なRecall方式

Canon量とキャンペーン長が増えた後に、次を追加する。

1. 表層文字列からEntity IDを解決する
2. 構造化検索
3. 日本語対応の全文検索
4. ベクトル検索による候補発見
5. Transcript原文検索
6. Evidence Packetの構築

結果状態:

- `found`
- `not_found`
- `ambiguous`
- `conflicting`
- `superseded`
- `forbidden`

`forbidden`は、外形上`not_found`と区別できない応答を返す。

### 12.4 Push型の整合確認

プレイヤーから過去を質問された場合だけでなく、GMが平常のNarrativeで既存事実へ言及した場合もCanonと照合する。

初期は、固有名詞、Entity Alias、数値の決定論的な照合から始める。

### 12.5 日本語検索

日本語全文検索は、素朴な空白区切りを前提にしない。

技術選定は、形態素解析またはN-gram索引を利用できることを条件にする。テストデータは必ず日本語を含める。

---

## 13. AIゲームマスターの責務

論理上、次の責務を区別する。

- Input Interpreter
- Referee
- World Simulator
- Director
- NPC Actor
- Narrator
- Memory Curator
- Validator

ただし、論理的責務とAPI呼び出し数は一対一ではない。

### 13.1 初期の実行方式

最初は一般的なTurnを一つのFast Pathで処理する。

- 公開向け呼び出しには、公開先から見える情報だけを渡す
- DirectorはScene開始、Scene終了、異常時のみ別の呼び出しとする
- Fast Pathへシナリオ秘密を渡さない
- Validatorは原則コードで行う
- 完全なTurn PlannerとStrict Pathは、実プレイで必要性が確認されてから追加する

### 13.2 Context View

Roleへ渡す情報は必要最小限とする。

| Role | 主に参照する情報 |
|---|---|
| Referee | 行為、適用候補ルール、公開済み状態 |
| Director | シナリオ秘密、未解決ビート、Clock、進行履歴 |
| NPC Actor | NPC自身の知識、目的、関係、口調 |
| Narrator | 検証済み結果、公開可能な事実、描写方針 |
| Validator | 不変条件、提案Event、現在State |

Directorの秘密を持つContextから、同じ呼び出しでプレイヤー向けNarrativeを生成しない。

---

## 14. ルールシステム

### 14.1 分離

ルールを次に分ける。

- **Executable Rule**: コードで処理する判定、ダイス、資源、状態変更
- **Declarative Rule**: 自然言語の解釈が必要な条件、例外、裁定方針

### 14.2 Ruling

裁定は最低限、次を持つ。

```yaml
rule_refs: []
facts_used: []
interpretation: ""
roll_spec: null
proposed_effects: []
is_house_ruling: false
```

根拠が見つからない場合は、ルールに明記されたものとして装わず、GM Rulingとして記録する。

### 14.3 Reference Ruleset

最初はNeontoF専用の極小ルールを用いる。

- 2d6による通常判定
- HP
- 資源1種
- 状態異常少数
- Clock
- 手掛かり

初回Vertical Sliceには、本格的な戦闘、複雑な対抗判定、大量の特殊能力を入れない。

既存TRPGへの正式対応は、CoreのVertical Sliceが成立してから判断する。

---

## 15. シナリオランタイム

### 15.1 最初のScenario

最初のScenarioは1〜2時間で完了できる規模とする。

- 場所 4〜6
- NPC 3〜4
- 秘密 1
- 手掛かり 3
- 主要NPCのClock 1
- 成功終了 1
- 失敗終了 1

Scenarioは手書きの構造化ファイルとする。初期は専用Editor、汎用Parser、公開用Validatorを作らない。

### 15.2 必須要素

- World Invariants
- NPC Goals
- NPC Knowledge
- Locations
- Clues
- Clock
- End Conditions

Failure Strategy、複雑なBeat Graph、複数形式のScenario Parserは後から追加する。

### 15.3 Scene

Sceneの開始と終了をEventとして記録する。

Scene遷移は次の場合に行う。

- プレイヤーが明示的に移動・休息・時間経過を宣言した
- `awaiting_player`で確認し、プレイヤーが同意した
- 終了条件により自明にSceneが閉じた

単に規定Turn数へ達したことだけを理由に、Directorが強制的にSceneを切らない。

### 15.4 時間

最初は実時刻を厳密に扱わず、Clockの目盛りで進行を表す。

- 主要なScene遷移でClockを進める
- 実時刻表現はNarrative上の装飾として扱う
- 期限判定はClockへ変換する

---

## 16. GMの振る舞いとプレイヤー体験

### 16.1 面白さを単一値にしない

面白さは結果であり、単一の`fun`値では制御できない。

最初に実装するプレイヤー向け設定は少数にする。

| 設定 | 初期の接続先 |
|---|---|
| 進行方針 | 選択肢サジェスト数、Director介入回数 |
| 厳しさ | 警告、救済経路、資源圧力 |
| ルール運用 | ルール参照の必須度 |
| テンポ | Scene目安Turn数、出力長 |
| 文章量 | 最大文字数 |
| 情報提示 | 手掛かりの明示度 |
| 裁定透明性 | ダイス、目標値、根拠の表示量 |

### 16.2 rescue_bias

`rescue_bias`はダイス、HP、資源値を書き換えない。

作用範囲を次に限定する。

- 致命的結果の前に警告する
- シナリオ上妥当な救援経路を提示する
- 失敗後に選べる脱出・代償案を増やす

### 16.3 最初から必要な体験要素

- 現在の場所、HP、所持品、目的を常時確認できる
- Turn末に2〜4個の行動候補を提示する
- Clockにより世界が能動的に進む
- GM応答の長さに上限を設ける
- モデル処理中の進行状況を表示する
- セッション中断と再開を可能にする

### 16.4 安全設定

Safety Constraintは単なる好みではなく、必ず守る制約として扱う。

- 避けたいテーマ
- 描写の上限
- 中断条件
- プレイヤーによる即時停止

---

## 17. モデルゲートウェイ、費用、キャッシュ

### 17.1 最初のProvider

最初は一つのProviderで動かす。

Provider呼び出しを一つのモジュールまたは関数へ閉じ込め、テスト用Fake Providerと交換できるようにする。

二つ目のProviderが必要になるまで、過度なCapability抽象化を作らない。

### 17.2 モデル呼び出し記録

各呼び出しについて次を記録する。

- Provider
- Model
- 担当Rolesの配列
- Input Tokens
- Output Tokens
- Cached Tokens
- Cost
- Latency
- Retry
- Result Status

ロール統合時に費用をRole別へ按分しない。

### 17.3 予算

最初は次で十分とする。

- セッション累計費用
- セッション上限
- 1Turnの最大呼び出し回数
- 上限到達時の強制停止

実消費は呼び出し後に確定するため、予算は一回の呼び出し分だけ超過し得る。

### 17.4 Prompt Cache

Prompt Cacheは正しさの前提にしない。

Cacheがすべて失われても、Event、Canon、State、Scenarioからセッションを再開できなければならない。

Cache効率のため、Contextを安定領域と動的領域へ分け、決定論的にserializeする。

### 17.5 Streaming

状態変更に関わる構造化結果を検証した後に、Narrativeの公開を開始する。

Providerが順序付きStructured Streamingを安定提供しない場合は、次へフォールバックする。

- モデル処理段階の進行表示
- 全体受信後のNarrative公開

正しさをStreaming挙動へ依存させない。

---

## 18. ダイスと再現性

ダイスSeedは呼び出し単位で決定論的に導出する。

```text
seed = H(campaign_seed, turn_id, action_id, roll_index)
```

記録対象:

- campaign_seed
- turn_id
- action_id
- roll_index
- 導出Seed
- Dice Formula
- Result

モデル構成を変更した比較で、同じ行為のダイス結果が不必要にずれないようにする。

---

## 19. 拡張戦略

### 19.1 v0.1

正式なPlugin、Manifest、Hook体系、Profile階層を作らない。

- Provider呼び出しを一箇所へ閉じ込める
- Ruleset処理を一つの境界へ閉じ込める
- Scenario Loaderを一つの境界へ閉じ込める
- ProjectionをEventから再構築できるようにする

### 19.2 抽象化の開始条件

次のいずれかが実際に必要になった時点で抽象化する。

- 二つ目のProvider
- 性質の異なる二つ目のRuleset
- 二つ目のScenario形式
- 異なるMemory Strategy
- 外部拡張者

### 19.3 正式なPlugin化

正式なPlugin化は、少なくとも二つの具体的実装から共通境界を抽出した後に行う。

将来検討するもの:

- Plugin Manifest
- Profile
- Hook
- Capability Graph
- MCP Adapter
- Sandboxing
- Distribution Index

---

## 20. Webプラットフォーム化

最初のVertical Sliceはlocalhostで動くが、最終的にはセルフホスト可能なWebプラットフォームへ進む。

後段で追加する。

- 認証
- Room
- Participant
- ルーム権限
- APIキー設定とRotation
- Docker等の標準デプロイ
- BackupとMigration
- 管理者向け使用量UI
- 複数クライアント接続
- 接続切断と再参加

含めない。

- NeontoF運営型SaaS
- 決済
- 公開マッチング
- 不特定多数向けマルチテナント
- プレイヤー各自がAPIキーを持ち込むBYOK

---

## 21. 評価

### 21.1 最初の評価

最初の評価は実装者本人の通しプレイである。

- 1〜2時間のScenarioを最後まで遊ぶ
- 翌日もう一度遊びたいと思うか記録する
- 読み飛ばしたTurnを記録する
- 入力に迷ったTurnを記録する
- 待ち時間が苦痛だったTurnを記録する
- NPCが受け身だった場面を記録する
- GMに意図を誤解された場面を記録する

### 21.2 自動評価

初期から自動化しやすいもの:

- EventからStateを再構築できる
- Evidence IDが実在し可視である
- 記録にない過去を未決定と扱う
- API失敗で部分Eventを残さない
- 予算上限を超えて無制限に呼び出さない
- 秘密文字列が公開出力へ現れない
- Dice Seedを再現できる
- Projectionを削除して再構築できる
- 同一Turn Request IDを二重処理しない

### 21.3 テスト用Provider

モデルを呼ばずにテストできるFake Providerと、記録済みResponseを再生するFixture Providerを用意する。

モデル依存テストだけにすると、課金、遅延、出力揺れによりテストが実行されなくなるためである。

### 21.4 長期評価

長期キャンペーン機能を追加した後に評価する。

- 5セッション前の約束をEvidence付きで参照できる
- NPCの口調と知識境界が維持される
- Canon訂正後に旧値と現在値を区別できる
- 日本語の別名、ひらがな、指示語からEntityを解決できる
- SummaryとIndexを削除しても正史が失われない

---

## 22. 主なリスク

### 22.1 遊んで面白くない

正しさを満たしても、文章量、待ち時間、選択肢不足、NPCの受動性により退屈になる。

対策:

- 最初のVertical Sliceで通しプレイする
- Clock、選択肢サジェスト、状態表示を初期から含める
- 実プレイで頻出した問題だけを優先して直す

### 22.2 設計と抽象化が実装を飲み込む

対策:

- 一つ目を具体実装する
- 二つ目が必要になるまでPlugin化しない
- 各Phaseで遊べる状態を維持する

### 22.3 NarrativeとCanonがずれる

対策:

- Semantic Resultを先に扱う
- provisional_detailを捕捉する
- 公開後に既知Entityと数値を照合する
- Transcriptを最終監査記録として残す

### 22.4 長期記憶を作り込みすぎる

対策:

- 最初は可視Canon全件とEvidence検証で始める
- 実際にContextへ収まらなくなってから検索を追加する
- Canon Schemaは使用実績に基づいて拡張する

### 22.5 秘密漏洩

対策:

- 公開向け呼び出しに秘密を渡さない
- Directorを公開Narrative生成から分離する
- 秘密文字列の回帰テストを持つ

### 22.6 費用と待ち時間

対策:

- 一つのProvider、一つのFast Pathから始める
- 呼び出し上限と累計費用を表示する
- Prompt Cacheを計測する
- 日本語で実測する

### 22.7 Scenario執筆が進行を止める

対策:

- 最初のScenario規模を固定する
- YAML等の一ファイルへ手書きする
- Editorや汎用形式を先に作らない

### 22.8 名寄せが失敗する

対策:

- Entity Aliasを保存する
- 曖昧なら`awaiting_player`で確認する
- 日本語の検索制約を技術選定へ入れる

### 22.9 名称とライセンス

私的開発段階では優先しない。公開・配布を具体化する時点で、NeontoFという名称、DodontoFへの言及、ルールセット、シナリオ、ロゴの法的整理を行う。

---

## 23. 現時点の未決事項

次は実装開始時のADRで決める。

- 実装言語
- Webフレームワーク
- Database
- 日本語検索方式
- 最初のModel Provider
- Structured OutputとStreamingの実現方式
- ScenarioとCharacter Sheetの具体フォーマット
- ProviderごとのPrompt Cache対応

判断基準:

1. 一人で保守できる
2. テスト用Providerへ差し替えられる
3. Eventのトランザクションを単純に実装できる
4. Browser ClientとServerを分離できる
5. 日本語検索へ拡張できる
6. Streamingまたは進行状況通知を実装できる
7. APIキーをサーバーに保持できる
8. Docker化を後から行える
9. ライブラリや規格の寿命が極端に短くない
10. 二つ目の実装がない段階で過剰な抽象化を要求しない

---

## 24. 実装計画との関係

本書は、NeontoFが何を目指し、何を守るかを定める。

具体的な作業順序、PhaseごとのGoal、Non-goal、成果物、受け入れGateは、`NeontoF_IMPLEMENTATION_ROADMAP.md`を正とする。

実装ロードマップは、次の順序を採る。

1. 後から変えると高くつく契約だけを固定する
2. localhostで最初のScenarioを遊べる状態を作る
3. 実際に10〜20時間遊び、頻出問題を直す
4. 長期キャンペーン用のRecallと検索を追加する
5. セルフホスト可能な単一テナントWebプラットフォームへ仕上げる
6. 二つ目の具体例から拡張境界を抽出する
7. 複数人セッションへ進む

---

## 25. プロダクトの北極星

NeontoFが目指す体験は、文章の豪華さだけではない。

- 一度決まったことが後から変わらない
- 記録にない過去をAIが作らない
- ルールに従った結果が演出都合で消えない
- NPCが自分の知識、目的、関係、口調に基づいて行動する
- 世界がプレイヤーを待たずに動く
- プレイヤーの選択が後の展開へ残る
- 過去の約束、失敗、手掛かりが長期的に意味を持つ
- 必要なときに裁定と根拠を確認できる
- 費用と待ち時間を理解したうえで継続できる
- 一人で始められ、将来は複数人で同じ世界を遊べる

NeontoFの成功は、最も賢い文章生成AIを作ることではない。

> 制約された現在のモデルから、一貫性があり、裁定可能で、選択に意味があり、継続して遊びたいと思えるTRPGセッションを成立させること。
