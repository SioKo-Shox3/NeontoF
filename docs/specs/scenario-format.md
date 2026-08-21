# Scenario Format Specification（P0-06）

## 1. 位置づけ

本書は、Phase 0 の P0-06 で固定する、手書き YAML 一 file の Scenario authoring
contract を定義する。対象は `ScenarioV1` と、その入力を検証する
`SCENARIO_ADAPTER` である。Scenario はゲーム状態の権威ではない。初期入力は将来の
Event 正規化の対象となるが、ゲーム状態と Canon は Event Log から再構築される。
この契約は State を直接更新する公開 API を定義しない。

本書の上位契約は P0-03 の `docs/specs/core-domain-and-events.md` である。Stable ID、
`Visibility`、strict な `ContractModel`、immutable model、versioned contract の
規則を再定義せずに利用する。P0-06 の承認済み境界と成果物は
`docs/plans/phase-00-foundation.md` §12 に従う。

## 2. Goal と Non-goal

### 2.1 Goal

公開情報と GM 専用情報を同一 Scenario source 内で明示的に分離し、次を固定する。

- `ScenarioV1` の一形式、`schema_version`、Scenario ID、authoring `version`
- `initial_scene`、4〜6 Locations、3〜4 NPCs
- World Invariants、Secret exactly 1、Clues exactly 3、Clock exactly 1
- `success` と `failure` の End Condition を各 exactly 1
- 同一 file 内の stable ID reference、duplicate ID／duplicate reference の拒否
- 全ての初期事実と本文に対する明示的な `Visibility`
- source の `gm_only` を正当な値として受理し、公開投影時に秘密を除外する境界
- strict、extra field 拒否、frozen、再検証、入力 alias 切断の契約

### 2.2 Non-goal

次は P0-06 では作らない。

- Scenario Editor、Graph DSL、二つ目の Scenario format、汎用 Validator
- production YAML loader、filesystem I/O、Runtime、Turn Engine、Director、Context Builder
- Scenario を遊ぶ処理、Web UI、Model Gateway、production pipeline
- 二つ目の Provider、Plugin、Hook、Profile、または将来用の空の拡張 interface
- Narrative の自由文を状態へ反映する parser、State の直接更新 API

## 3. 入力境界と top-level shape

production code は YAML と filesystem を扱わない。test-only の
`tests/contracts/test_scenario.py` が `yaml.safe_load` で UTF-8 YAML を mapping へ読み、
その値を `SCENARIO_ADAPTER.validate_python` へ渡す。従って YAML の読み込みは fixture と
test の責務であり、`src/neontof/contracts/scenario.py` は model と adapter だけを提供する。

`ScenarioV1` の top-level field は次の順序と型である。top-level の未知 field は
`ContractModel` の `extra="forbid"` により拒否する。

| path | 型・制約 | 検証 |
|---|---|---|
| `schema_version` | `Literal[1]` | before validator で built-in `int` かつ値 `1` だけを受理。`bool` と `"1"` は拒否 |
| `id` | `ScenarioId` | P0-03 の strict stable ID grammar（`scenario:<slug>`） |
| `version` | strict `str` | `ContractModel` の strict 検証。追加の literal／range は持たない |
| `initial_scene` | `SceneDefinition` | nested model として検証 |
| `locations` | `tuple[LocationDefinition, ...]` | exact list／tuple を新しい tuple へコピーし、`min_length=4`、`max_length=6` |
| `npcs` | `tuple[NpcDefinition, ...]` | exact list／tuple を新しい tuple へコピーし、`min_length=3`、`max_length=4` |
| `world_invariants` | `tuple[WorldInvariant, ...]` | exact list／tuple を新しい tuple へコピー。件数の下限・上限は定義しない |
| `secret` | `SecretDefinition` | 単一の nested model。list／tuple の代替形は受理しない |
| `clues` | `tuple[ClueDefinition, ClueDefinition, ClueDefinition]` | exact list／tuple を新しい tuple へコピーし、exactly 3 |
| `clock` | `ClockDefinition` | 単一の nested model。list／tuple の代替形は受理しない |
| `end_conditions` | `tuple[EndCondition, EndCondition]` | exact list／tuple を新しい tuple へコピーし、exactly 2 |

`Secret` と `Clock` は定義の単数 field であり、`secret: [ ... ]` や
`clock: [ ... ]` にはしない。`world_invariants`、`SceneDefinition.npc_ids`、NPC の
`knowledge`、Clue の `location_ids` は field 自体を必須とするが、P0-06 の型には件数の
下限・上限を追加しない。

## 4. `ScenarioV1` の型と全 field

### 4.1 本文・Scene・Location・NPC

| model | exact path | 型 |
|---|---|---|
| `ScenarioText` | `initial_scene.objective`、`npcs[*].goal`、`npcs[*].knowledge[*]` | `text: str`、`visibility: Visibility` |
| `SceneDefinition` | `initial_scene` | `id: SceneId`、`location_id: LocationId`、`npc_ids: tuple[NpcId, ...]`、`objective: ScenarioText` |
| `LocationDefinition` | `locations[*]` | `id: LocationId`、`canonical_name: str`、`description: str`、`visibility: Visibility` |
| `NpcDefinition` | `npcs[*]` | `id: NpcId`、`canonical_name: str`、`aliases: tuple[str, ...]`、`goal: ScenarioText`、`knowledge: tuple[ScenarioText, ...]` |

### 4.2 World Invariant・Secret・Clue・Clock

| model | exact path | 型 |
|---|---|---|
| `WorldInvariant` | `world_invariants[*]` | `id: InvariantId`、`statement: str`、`visibility: Visibility` |
| `SecretDefinition` | `secret` | `id: SecretId`、`text: str`、`visibility: Literal["gm_only"]` |
| `ClueDefinition` | `clues[*]` | `id: ClueId`、`text: str`、`location_ids: tuple[LocationId, ...]`、`visibility: Visibility` |
| `ClockDefinition` | `clock` | `id: ClockId`、`label: str`、`segments: int`、`initial: int`、`visibility: Visibility` |

`canonical_name`、`aliases`、各 model の ID、Scenario の `version` は metadata であり、
metadata の名前や値から `Visibility` を推測しない。本文・初期事実の公開範囲は必ず
宣言 field から決める。

### 4.3 End Condition union

`EndCondition` は `type` を discriminator とする次の union である。section 名や field の
形から variant を推測しない。

| variant | exact path | 型 |
|---|---|---|
| `CluesDiscoveredEndCondition` | `end_conditions[*]`（`type="clues_discovered"`） | `type: Literal["clues_discovered"]`、`id: EndConditionId`、`outcome: Literal["success", "failure"]`、`clue_ids: tuple[ClueId, ClueId, ClueId]`、`visibility: Visibility` |
| `ClockReachedEndCondition` | `end_conditions[*]`（`type="clock_reached"`） | `type: Literal["clock_reached"]`、`id: EndConditionId`、`outcome: Literal["success", "failure"]`、`clock_id: ClockId`、`value: int`、`visibility: Visibility` |

実装上は次の型 alias と adapter を公開する。

```python
type EndCondition = Annotated[
    CluesDiscoveredEndCondition | ClockReachedEndCondition,
    Field(discriminator="type"),
]
END_CONDITION_ADAPTER: TypeAdapter[EndCondition]
SCENARIO_ADAPTER: TypeAdapter[ScenarioV1]
```

`segments`、`initial`、End Condition の `value` は strict `int` である。P0-06 はそれらの
数値の相互関係や追加の range validator を定義しない。例えば `"6"` は文字列なので拒否し、
値そのもののゲームルール解釈は Runtime の責務である。

## 5. Cardinality、ID、reference

### 5.1 Cardinality

`ScenarioV1` の構造上、次の件数だけを contract とする。

| section | 許可件数 |
|---|---:|
| `locations` | 4〜6 |
| `npcs` | 3〜4 |
| `world_invariants` | 型で固定しない |
| `secret` | 1（単一 field） |
| `clues` | exactly 3 |
| `clock` | 1（単一 field） |
| `end_conditions` | exactly 2 |

### 5.2 Stable ID と duplicate

全 ID は名前ではなく stable ID で参照する。P0-03 の ID は strict `str` で、共通 grammar
は次である。

```text
^<prefix>:[a-z0-9]+(?:-[a-z0-9]+)*$
```

P0-06 で使う prefix は `scenario`、`scene`、`location`、`npc`、`invariant`、`secret`、
`clue`、`clock`、`end-condition` である。例えば `npc:warden` は有効だが、表示名だけの
値、大文字、空 slug、連続または末尾の hyphen は無効である。

`_validate_end_condition_outcomes`（`mode="after"`）は、反復定義 namespace ごとに次の
duplicate ID を拒否する。

- `locations[*].id`
- `npcs[*].id`
- `world_invariants[*].id`
- `clues[*].id`
- `end_conditions[*].id`

### 5.3 Reference

同一 Scenario file 内の reference は、表示名ではなく stable ID で解決する。
`_validate_end_condition_outcomes` は次を検証する。

| source path | target | 追加検証 |
|---|---|---|
| `initial_scene.location_id` | `locations[*].id` | target が存在する |
| `initial_scene.npc_ids[*]` | `npcs[*].id` | reference 自身に duplicate がなく、全 target が存在する |
| `clues[*].location_ids[*]` | `locations[*].id` | reference 自身に duplicate がなく、全 target が存在する |
| `end_conditions[*].clue_ids[*]` | `clues[*].id` | `clues_discovered` variant だけ。reference 自身に duplicate がなく、全 target が存在する |
| `end_conditions[*].clock_id` | `clock.id` | `clock_reached` variant の target が Scenario の clock と一致する |

`initial_scene.id`、`secret.id`、`clock.id` 自体には別定義への reference validator を追加しない。
また、aliases や本文の文字列から ID を推測しない。

## 6. `schema_version`、strict、unknown field

`schema_version` には専用の before validator がある。

```python
@field_validator("schema_version", mode="before")
@classmethod
def _validate_schema_version(cls, value: object) -> object:
    if type(value) is not int or value != 1:
        raise ValueError("schema_version must be the strict integer 1")
    return value
```

従って次は同じ意味として解釈せず reject する。

- `schema_version: true`／`false`（Python では `bool` であり、`int` として扱わない）
- `schema_version: "1"`（string）
- `schema_version: 2`、その他の数値や型

P0-03 の `ContractModel` 設定は全 nested model に適用される。

```python
model_config = ConfigDict(
    strict=True,
    extra="forbid",
    frozen=True,
    revalidate_instances="always",
)
```

そのため、数値 field への数値文字列、`bool` の数値代用、top-level／nested の未知 field、
variant の未知または欠落した `type` を受理しない。End Condition の `outcome` も必須である。
`outcome` field 自体が欠落した場合は `required field missing` として reject し、field が存在するが
`"success"`／`"failure"` 以外の値なら `Literal["success", "failure"]` の Literal rejection
として reject する。これは下記の `model_validator(mode="after")` が行う success／failure の
件数検査とは別の段階である。

## 7. `Visibility` と秘密の境界

P0-03 の `Visibility` は次のいずれかである。

```text
"gm_only" | "player_visible" | NpcId
```

`NpcId` branch は `npc:<lowercase-slug>` grammar を持つ。`gm_only` は Scenario source に
現れてよい正当な値であり、source validation だけで reject しない。一方、`SecretDefinition`
の `visibility` はさらに狭く `Literal["gm_only"]` であるため、player-visible Secret は
contract 上表現できない。

### 7.1 Visibility が必須の path

次の全 path は、本文または初期事実の公開範囲として `visibility` を必須にする。

- `initial_scene.objective.visibility`
- `locations[*].visibility`（`locations` の各 item）
- `npcs[*].goal.visibility`
- `npcs[*].knowledge[*].visibility`
- `world_invariants[*].visibility`
- `secret.visibility`
- `clues[*].visibility`
- `clock.visibility`
- `end_conditions[*].visibility`

`Location.description`、`WorldInvariant.statement`、`Secret.text`、`Clue.text`、
`Clock.label`、`ScenarioText.text`、End Condition の predicate 相当の reference は、
上述の item 自身の `visibility` と組で扱う。`canonical_name`、`aliases`、ID、`version` は
metadata なので visibility を要求しない。

### 7.2 test-only publication oracle

`tests/contracts/support/validate_scenario_publication.py` にある次の型と関数は test-only
であり、production `scenario.py` の公開 API ではない。

```python
type ScenarioVisibilityIssueCode = Literal[
    "missing_visibility",
    "invisible_scenario_content",
    "unknown_npc_visibility",
]

class ScenarioVisibilityIssue(ContractModel):
    path: str
    code: ScenarioVisibilityIssueCode
    message: str

class PublishedScenarioText(ContractModel):
    path: str
    text: str
    visibility: Visibility

def normalize_missing_visibility_for_test(
    input_value: object,
) -> tuple[ScenarioVisibilityIssue, ...]: ...

def validate_scenario_publication_for_test(
    source: ScenarioV1,
    publication_visibility: Literal["player_visible"] | NpcId,
    candidate: Sequence[PublishedScenarioText] | None = None,
) -> tuple[ScenarioVisibilityIssue, ...]: ...

def project_scenario_public_text_for_test(
    scenario: ScenarioV1,
    publication_visibility: Literal["player_visible"] | NpcId,
) -> tuple[PublishedScenarioText, ...]: ...
```

`ScenarioVisibilityIssue` は test-only の公開 shape であり、production `scenario.py` には置かない。
`path` は入力値ではなく、検証対象を表す sanitized な構造 path の `str` とする。
`code` は上の `Literal` 以外を持たず、`message` は code ごとに定めた固定の sanitized message
だけを持つ。したがって raw Pydantic error、raw text／value、Secret、secret sentinel、例外の
context や cause を `path`／`message`／issue の他の観測面へ残さない。

責務は混ぜない。

1. `normalize_missing_visibility_for_test` だけが raw fixture mapping を受け、missing
   `visibility` を sanitized な `missing_visibility` issue へ正規化する。raw Pydantic error、
   raw text、raw value、Secret、secret sentinel を issue に残さない。
2. `validate_scenario_publication_for_test` は typed な `source: ScenarioV1` を受ける。全ての
   source visibility が `player_visible`、`gm_only`、または同じ Scenario の既知 NPC ID で
   あることを確認し、未知 NPC ID だけを `unknown_npc_visibility` とする。`gm_only` が source
   に存在するだけでは失敗しない。
3. `candidate` が渡された場合だけ、candidate の本文と visibility が publication 先へ完全
   一致しているかを検証する。`gm_only` 本文、Secret 本文、対象外 NPC 本文、または本文を別の
   visibility に relabel して混ぜた場合は `invisible_scenario_content` とする。`candidate=None`
   の source 検証へこの issue を混ぜない。
4. `project_scenario_public_text_for_test` は valid な Scenario から、指定先に明示的に許可
   された本文だけを `tuple[PublishedScenarioText, ...]` で返す。`player_visible` には
   `player_visible` だけ、`npc:X` には `npc:X` との完全一致だけを含め、`gm_only` は公開しない。
   Secret、対象外 NPC の本文、`canonical_name`、aliases、ID などの metadata は projection に
   含めない。返り値には元の許可 visibility を保持する。

この境界により、公開先へ不可視情報を渡さない。Narrative の自由文を parse して Scenario
source や Event へ変換する処理は、この oracle にも `ScenarioV1` にも含めない。

## 8. exact tuple、入力 mutation、immutable model

### 8.1 exact sequence validator

`_copy_exact_yaml_sequence` は private `BeforeValidator` で、次だけを受理する。

- `type(value) is list` の built-in list
- `type(value) is tuple` の built-in tuple

受理時は要素を走査して新しい tuple を作る。従って、次は `SceneDefinition.npc_ids`、
`ScenarioV1.locations`、`npcs`、`world_invariants`、`clues`、`end_conditions`、
`NpcDefinition.aliases`、`knowledge`、`ClueDefinition.location_ids`、
`CluesDiscoveredEndCondition.clue_ids` の全対象 field で reject する。

- `tuple subclass`
- `list` subclass
- `generator`
- `set`
- arbitrary iterable

`list`／`tuple` は YAML test input の sequence として受理するが、model 内の値は必ず built-in
tuple になる。tuple field の型長制約（Clue の 3、End Condition の 2）は sequence copy 後に
Pydantic field constraint で検証する。

### 8.2 mutation と再検証

入力 sequence と nested mapping は検証後に変更しても、作成済み model へ伝播しない。sequence
validator が新しい tuple を作り、nested model も immutable な `ContractModel` として保持する。

`frozen=True` により、例えば `scenario.clock.initial = 99` や
`scenario.initial_scene.objective.text = "tampered"` は拒否する。`revalidate_instances="always"`
により、既存 typed instance を `SCENARIO_ADAPTER.validate_python` の境界へ再投入した場合も
再検証される。`object.__setattr__` や `model_copy` などで nested 値が壊された instance を
reducer 側へ通さないための境界であり、検証済み instance を無条件に信頼しない。

## 9. End Condition の outcome

`ScenarioV1._validate_end_condition_outcomes` は、各 End Condition の `outcome` が schema validation
を通過した後に `model_validator(mode="after")` で `end_conditions` の2件を検査する。
`outcome` field 自体が欠落した入力は、この validator ではなく `required field missing` として
reject する。field が存在しても `"success"`／`"failure"` 以外の値なら、同じくこの validator
ではなく `Literal["success", "failure"]` の Literal rejection として reject する。
その後、`outcome` の集合ではなく件数を数え、次を必須とする。

```text
outcomes.count("success") == 1
outcomes.count("failure") == 1
```

従って `success, success`、`failure, failure`、success 欠落、failure 欠落は、この件数検査で
reject する。`outcome` が欠落した場合や Literal 外の値の場合は上記の schema validation で
reject されるため、件数検査の失敗と混同しない。tuple が2件あるだけでは valid にならない。

## 10. Fixture と最小形

`tests/fixtures/scenarios/minimal-scenario.v1.yaml` は契約テスト用の synthetic fixture で、
次を含む。

- `schema_version: 1`、`scenario:minimal`、`version: v1`
- 4 locations、3 NPCs、2 `world_invariants`
- `secret` 1、3 clues、clock 1、End Condition 2
- `clues_discovered` の success 1件と `clock_reached` の failure 1件
- `player_visible`、`gm_only`、`npc:warden`、`npc:scholar` の visibility 例

次の fixture は source validation と publication oracle の責務分離を確認する。

| fixture | 目的 |
|---|---|
| `missing-objective-visibility.v1.yaml` | `initial_scene.objective.visibility` の missing を `missing_visibility` へ正規化 |
| `missing-npc-goal-visibility.v1.yaml` | `npcs[0].goal.visibility` の missing を `missing_visibility` へ正規化 |
| `missing-end-condition-visibility.v1.yaml` | `end_conditions[0].visibility` の missing を `missing_visibility` へ正規化 |
| `gm-only-player-publication.v1.yaml` | source の `gm_only` を受理し、player publication には除外 |

fixture の本文は test-only の入力データであり、production prompt、通常 log、公開 response に
秘密を移すための材料ではない。Secret sentinel は issue、projection、publication output に
現れてはならない。

## 11. Event Log と I/O の境界

Scenario source は初期 authoring input であって、State または Canon の直接書き換え手段では
ない。将来の application layer が検証済み source を Semantic Result／検証済み Event へ
正規化する場合も、Event Log が唯一の権威であり、projection は Event から再構築する。
この仕様の責務は、その前段で安全に検証できる typed source と visibility 境界を固定する
ところまでである。

`src/neontof/contracts/scenario.py` は次を持たない。

- YAML parser、`safe_load`、file open、filesystem path、production loader
- Scenario Editor、Runtime、Turn execution、Event Store、直接 State mutation
- Provider 呼び出し、API key、Plugin／Hook／Profile の登録

Transcript と Telemetry はゲーム状態の transaction 外にある別責務であり、Scenario format の
field へ混ぜない。失敗した Turn の記録や費用を Scenario model の rollback で扱わない。

## 12. Phase 1 への先送り

P0-06 完了時点では、次を Phase 1 へ送る。

- Character／Scenario Loader と production YAML I/O
- Model Gateway、Context Builder、production pipeline
- Runtime、Turn Engine、Scenario の開始・進行・終了
- Scenario Editor、複数人 session、Web UI
- Event への具体的な正規化実装と、実運用の公開 projection pipeline

これらを先回りして `scenario.py` に追加しない。二つ目の Scenario format、Provider、
Plugin、Hook、Profileも追加しない。

## 13. Plan・P0-03・ADR との関係

- `docs/plans/phase-00-foundation.md` §12 が P0-06 の承認済み実行境界、作成 file、型、test
  first、Gate、commit boundary を定める。本書はそのうち Scenario format の利用者向け契約を
  日本語で記録する。計画にない実装や別 file を追加する根拠にはならない。
- `docs/specs/core-domain-and-events.md`（P0-03）が Stable ID grammar、`Visibility` の
  literal、`ContractModel` の `strict=True`／`extra="forbid"`／`frozen=True`／
  `revalidate_instances="always"`、versioned contract の変更規則を所有する。本書はそれらと
  整合する Scenario 固有の field／count／reference／publication 境界を記録する。
- ADR は上位の技術・所有権・互換性の判断を記録する場所であり、本書で代替しない。ID grammar、
  Visibility、Event Log の権威性、またはこの format の互換性を変更する場合は、実装を先に
  変更せず、承認済み Plan と必要な ADR／上位仕様を先に更新する。今回の許可 path は
  `docs/specs/scenario-format.md` だけなので、Plan、P0-03仕様、ADR は編集しない。

## 14. 検証コマンドと実測結果

以下は P0-06 の focused test と本書の提出前検査で実行するコマンドである。出力はこの作業
ツリーでの実測値を記録する。

### 14.1 focused contract test

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "src"
.\.venv\Scripts\python.exe -m pytest tests/contracts/test_scenario.py -q
```

実測結果:

```text
140 passed
```

### 14.2 strict mypy 型チェック

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "src"
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
```

実測結果:

```text
Success: no issues found in 38 source files
```

### 14.3 UTF-8 BOM／CRLF 検査

```powershell
$path = "docs/specs/scenario-format.md"
$bytes = [System.IO.File]::ReadAllBytes($path)
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$null = $utf8.GetString($bytes)
$bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
$crlf = ([System.Text.Encoding]::UTF8.GetString($bytes) -split "`r`n").Count - 1
"UTF-8 decode: PASS"
"BOM: $bom"
"CRLF count: $crlf"
```

実測結果:

```text
UTF-8 decode: PASS
BOM: False
CRLF count: 0
```

### 14.4 Markdown fence 検査

```powershell
$path = "docs/specs/scenario-format.md"
$fences = @(Select-String -LiteralPath $path -Pattern '^```' | ForEach-Object { $_.LineNumber })
"fence lines: $($fences.Count)"
"fence pairs: $([int]($fences.Count / 2))"
"closed: $($fences.Count -gt 0 -and $fences.Count % 2 -eq 0)"
```

実測結果:

```text
fence lines: 38
fence pairs: 19
closed: True
```

### 14.5 Git whitespace 検査（untracked 対応）

```powershell
$path = "docs/specs/scenario-format.md"
$text = [System.IO.File]::ReadAllText($path)
$trailingWhitespaceMatches = [regex]::Matches($text, "(?m)[ \t]+(?:\r?$)").Count
$lfCount = [regex]::Matches($text, "`n").Count
$crlfCount = [regex]::Matches($text, "`r`n").Count
"trailing_whitespace_matches=$trailingWhitespaceMatches"
"LF_count=$lfCount"
"CRLF_count=$crlfCount"
if ($trailingWhitespaceMatches -ne 0 -or $crlfCount -ne 0) {
    throw "direct whitespace inspection failed."
}

$noIndexOutput = & git diff --no-index --check -- /dev/null $path 2>&1
$noIndexExit = $LASTEXITCODE
$noIndexOutput
"git diff --no-index --check exit=$noIndexExit (untracked file differs from /dev/null)"
if ($noIndexExit -notin @(0, 1)) {
    throw "git diff --no-index --check failed with exit $noIndexExit."
}
```

実測結果:

```text
trailing_whitespace_matches=0
LF_count=564
CRLF_count=0
git diff --no-index --check exit=1 (untracked file differs from /dev/null)
```

untracked file は通常の `git diff --check` の対象外なので、上の直接検査を併用する。
`git diff --no-index --check -- /dev/null docs/specs/scenario-format.md` の exit code `1` は
`/dev/null` と untracked file に差分があることを示し、出力がないことと直接検査の結果で
whitespace error がないことを確認する。`git diff --numstat` と
`git diff --ignore-cr-at-eol --numstat` も照合し、行末変換による全体書き換えがないことを確認する。
コミットは行わない。

### 14.6 Production forbidden source scan

production source scan は `src/neontof/contracts/scenario.py` だけを対象に、plan の狭い
実行時／I/O pattern と一致させる。`_copy_exact_yaml_sequence` の helper 名と fixture／docs の
`safe_load` 説明は production I/O ではないため、scan の禁止 hit として扱わない。

```powershell
$forbiddenRgPatterns = @(
    "import yaml", "safe_load", "yaml.load", "unsafe loader", "read_text", "read_bytes",
    "write_text", "write_bytes", "open", "filesystem read", "strict=False", "publication_visibility.py"
)
foreach ($pattern in $forbiddenRgPatterns) {
    $forbiddenHits = @(rg -ni --fixed-strings -- $pattern src/neontof/contracts/scenario.py)
    $forbiddenExit = $LASTEXITCODE
    if ($forbiddenExit -eq 0) { $forbiddenHits; throw "forbidden rg hit '$pattern'." }
    if ($forbiddenExit -ne 1) { throw "forbidden rg failed for '$pattern' with exit $forbiddenExit." }
}
"forbidden_source_hits=0"
```

実測結果:

```text
forbidden_source_hits=0
```
