# Character Sheet 契約（P0-05）

## 1. 位置づけ

本書は、Phase 0 の P0-05 で固定する `Character Sheet` の versioned contract を記録する。
対象は、手書き YAML から読み取った object を `Pydantic` で検証し、Campaign 開始前の
Character 初期入力として扱う境界である。

この契約の production source は次の一ファイルだけである。

- `src/neontof/contracts/character_sheet.py`

focused test と test-only fixture は次のファイルに置く。

- `tests/contracts/test_character_sheet.py`
- `tests/fixtures/characters/minimal-character.v1.yaml`

`Character Sheet` は Event Log や State Projection の代替ではない。検証済みの初期入力を
後続の Campaign 開始処理へ渡す値契約であり、Campaign 開始後の権威は Event Log にある。

## 2. Goal と Non-goal

### 2.1 Goal

手書き YAML 一 file から Character 初期状態の入力を読み取れる versioned contract を固定する。
P0-05 で決める範囲は次のとおりである。

- stable `CharacterId`、`canonical_name`、`aliases`
- `HitPoints` と一種類の `ResourceState`
- `InitialItem` の列と初期 `LocationId`
- 省略可能な `SpeechStyle`
- 最小の `CharacterRuleset`
- Character Sheet 全体に対する必須 `Visibility`
- `schema_version: Literal[1]`

### 2.2 Non-goal

次はこの契約に追加しない。

- UI、Browser Client、Editor、Skill Tree
- 複数の Ruleset、万能 Schema、第二の具体実装を前提にした抽象化
- production `loader`、YAML file I/O、loader から Event へ変換する code
- Event append、Event Store、State / Canon reducer、Provider、Model Gateway
- Plugin、Hook、Profile、Provider registry
- 自由文の Narrative を parse して状態へ反映する経路

`CHARACTER_SHEET_ADAPTER` は object の検証 adapter であり、file を読む `loader` ではない。

## 3. データの権威と境界

入力の概念上の流れは次のとおりである。

```text
test-only YAML safe_load -> mapping object -> CHARACTER_SHEET_ADAPTER -> CharacterSheetV1
```

この流れで生成される `CharacterSheetV1` は、Campaign 開始前の検証済み入力のみである。

### 3.1 Event normalization rule

Campaign 開始前に、後続の application contract がこの検証済み `CharacterSheetV1` から明示的な
`Event snapshot mapping` を作る。その Event の type、authoritative fields、append 経路、
transaction は後続契約で定義する。P0-05 は `Event` の create、append、loader を実装しない。

その Event が append された以後は Event Log がゲーム状態の唯一の権威であり、State と Canon は
Event から再構築できる Projection である。元の YAML は Event Log と並行する権威（parallel
authority）にならず、YAML file を後から修正しても既存 Campaign の State や Canon を直接変更しない。

既存 P0-03 Event union で authoritative fields の全てを表現できない場合は、Phase 1 loader の
実装前に domain contract と plan を改訂する。その場合も P0-05 で不足分の Event を追加しない。
`character_sheet.py` に State 直接更新 API、Event append API、Projection reducer を置かない。

`Transcript` と `Telemetry` はゲーム状態の transaction 外で記録される別の型であり、
Character Sheet の field や Event payload に混ぜない。Turn の失敗時にそれらを消去したり、
費用を戻したりする責務もこの契約にはない。

## 4. Module path、型、field、signature

### 4.1 正確な path と公開名

Python module path は `neontof.contracts.character_sheet`、source path は
`src/neontof/contracts/character_sheet.py` である。`__all__` の公開名は次の順で固定される。

```text
CHARACTER_SHEET_ADAPTER
CharacterRuleset
CharacterSheetV1
HitPoints
InitialItem
ResourceState
SpeechStyle
```

### 4.2 型定義

次のコード片は P0-05 の型と public field shape を示す。sequence field は、後述する private
`BeforeValidator` を適用した上で、検証後の値が `tuple` になる。

```python
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
    visibility: Visibility
    speech_style: SpeechStyle | None = None
    ruleset: CharacterRuleset

CHARACTER_SHEET_ADAPTER: TypeAdapter[CharacterSheetV1] = TypeAdapter(CharacterSheetV1)

def _copy_exact_yaml_sequence(value: object) -> object: ...
```

実装上の sequence annotation は次の private alias である。public な型はそれぞれ
`tuple[str, ...]` または `tuple[InitialItem, ...]` であり、private alias を root export しない。

```python
type _ExactStringSequence = Annotated[
    tuple[str, ...], BeforeValidator(_copy_exact_yaml_sequence)
]
type _ExactInitialItemSequence = Annotated[
    tuple[InitialItem, ...], BeforeValidator(_copy_exact_yaml_sequence)
]
```

### 4.3 field の制約

| field / path | 型 | 制約 |
| --- | --- | --- |
| `schema_version` | `Literal[1]` | version 1 だけを受理する。`str` と `bool` を数値へ変換しない。 |
| `id` | `CharacterId` | `character:<lowercase-slug>` の stable ID。表示名を ID にしない。 |
| `canonical_name` | `str` | 表示名。stable ID と分離する。 |
| `aliases` | `tuple[str, ...]` | 空文字と重複を拒否する。 |
| `description` | `str` | Character の初期説明。自由文を状態変更入力として扱わない。 |
| `hp` | `HitPoints` | `0 <= current <= max`。 |
| `resource` | `ResourceState` | `ResourceId` と label を持ち、`0 <= current <= max`。 |
| `initial_items` | `tuple[InitialItem, ...]` | 各 item の `ItemId` と canonical name を検証する。 |
| `initial_location_id` | `LocationId` | `location:<lowercase-slug>` の stable ID。 |
| `visibility` | `Visibility` | required。省略と `null` を拒否する。 |
| `speech_style` | `SpeechStyle \| None` | 省略または明示的 `null` を許可する。存在時は全 field を検証する。 |
| `ruleset` | `CharacterRuleset` | `id` は `ruleset:neontof-minimal-2d6-v1` に固定する。 |

`ResourceId`、`ItemId`、`LocationId`、`CharacterId` の ID grammar は P0-03 の stable ID 契約に
従う。`canonical_name`、`aliases`、各 ID、item / resource の metadata は Fact または text の
`Visibility` と混同しない。

`ResourceState` は P0-03 の `projection.ResourceState` と同名だが、同じ class ではない。
`neontof.contracts.character_sheet.ResourceState.__module__` は
`"neontof.contracts.character_sheet"`、`neontof.contracts.projection.ResourceState.__module__`
は `"neontof.contracts.projection"` であり、両者の identity は異なる。root
`neontof.contracts.ResourceState` は `projection.ResourceState` を指す。したがって利用側は
`character_sheet.ResourceState` または `projection.ResourceState` の module-qualified import
だけを使う。`CharacterSheetV1`、`CHARACTER_SHEET_ADAPTER`、`HitPoints` は root export に追加
しない。

## 5. 5 つの plain `int`

V1 で annotation が plain `int` である field は次の 5 つだけである。全て `ContractModel` の
`strict=True` により、文字列の数値や `bool` を受理しない。

| field | 理由 |
| --- | --- |
| `HitPoints.current` | 初期時点の HP 現在値を整数カウンタとして表す。 |
| `HitPoints.max` | HP の整数上限を表し、`current` の上限検証に使う。 |
| `ResourceState.current` | 一種類の resource の初期現在量を整数カウンタとして表す。 |
| `ResourceState.max` | resource の整数上限を表し、`current` の上限検証に使う。 |
| `CharacterRuleset.action_modifier` | 最小 Ruleset の modifier を整数値として表す。P0-05 では追加の範囲制約を定義しない。 |

`schema_version` は整数値に見えるが、plain `int` の数値 field ではなく `Literal[1]` である。
version を固定するための field validator も `type(value) is int and value == 1` を要求する。

## 6. Validation と immutable 値

全ての nested model を含め、`ContractModel` の共通設定を継承する。

```python
class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
```

各設定の意味は次のとおりである。

- `strict=True`: `"7"` を `7`、`true` を `1` のように暗黙変換しない。
- `extra="forbid"`: root、`hp`、`resource`、`initial_items`、`speech_style`、`ruleset` など、
  nested boundary の unknown field を拒否する。
- `frozen=True`: `CharacterSheetV1` と全 nested model の field 代入を拒否する。
- `revalidate_instances="always"`: 既に型付きの nested instance を受け取る境界でも再検証し、
  改変された instance を adapter の先へ通さない。

検証入口は `CHARACTER_SHEET_ADAPTER.validate_python(raw, strict=True)` である。
`schema_version` の strict な固定、ID kind と slug grammar、HP / resource の bounds、Alias の
空文字・重複、nested model の型と unknown field をこの入口で検証する。

## 7. `Visibility`、公開範囲、秘密

### 7.1 required `Visibility`

`CharacterSheetV1.visibility` は default のない required field であり、`null` も許可しない。
型は P0-03 の `Visibility` をそのまま使用する。

```python
Visibility = Literal["gm_only", "player_visible"] | NpcId
```

したがって受理する値は次の三種類である。

- `gm_only`
- `player_visible`
- `npc:<lowercase-slug>`（例: `npc:watcher`）

この field は Character Sheet 全体の初期公開範囲を記録する宣言である。Fact payload や text
の `Visibility` を埋め込む field ではない。公開処理や recipient ごとの filtering は後続の
application 境界の責務であり、P0-05 は公開 API を作らない。

### 7.2 秘密を渡さない境界

Character Sheet に Secret、API key、Provider credential、不可視の prompt context を field として
定義しない。fixture、通常 log、公開 Narrative、公開向け model call に秘密を渡さない。
`visibility` は秘密を格納する仕組みではなく、初期値の公開範囲を伝える metadata である。

`gm_only` または `npc:<id>` の値を持つ sheet を後続の公開先へ渡す場合、公開先から不可視な
内容を先に除外しなければならない。その filtering を実装するための Provider、Prompt、Secret
Store、公開 adapter は P0-05 に追加しない。

## 8. sequence の exactness、copy、`Iterable` 拒否

private `_copy_exact_yaml_sequence(value: object) -> object` は、次の 4 field に適用する。

- `CharacterSheetV1.aliases`
- `CharacterSheetV1.initial_items`
- `SpeechStyle.endings`
- `SpeechStyle.forbidden_patterns`

validator が受理する入力は、組み込み型そのものの `list` または `tuple` だけである。

- `type(value) is list` のとき、各要素を新しい `tuple` へ copy する。
- `type(value) is tuple` のときも、新しい `tuple` へ copy する。
- `tuple subclass` は組み込み `tuple` そのものではないため拒否する。
- `list` subclass、generator、`set`、任意の `Iterable` も拒否する。
- 検証後に入力側の list、tuple、nested item mapping を変更しても model へ伝播しない。
- model 上の sequence は exact `tuple` であり、要素代入は `TypeError` になる。

この制限は、任意の iterable を暗黙に受理して入力消費・遅延評価・aliasing の挙動を契約へ
持ち込まないためである。新しい tuple field を追加する場合は、P0-05 の対象列挙と test を
同時に更新する。Phase 0 で未要求の一般化は行わない。

## 9. YAML fixture の test-only 境界

fixture は `tests/fixtures/characters/minimal-character.v1.yaml` だけを使用する。fixture の
読み込みは `tests/contracts/test_character_sheet.py` に限定し、次の順序で行う。

```python
raw_bytes = FIXTURE_PATH.read_bytes()
fixture_text = raw_bytes.decode("utf-8")
loaded = yaml.safe_load(fixture_text)
sheet = CHARACTER_SHEET_ADAPTER.validate_python(loaded, strict=True)
```

実際の test は fixture を UTF-8 として decode し、BOM がないこと、日本語の `canonical_name`
と `aliases` が round-trip することも確認する。YAML parser は `PyYAML==6.0.3` の test/dev-only
依存であり、runtime production dependency ではない。

`src/neontof` に `yaml` import、`safe_load`、YAML filesystem read、`yaml.load`、unsafe loader、
`eval`、validation bypass を置かない。`character_sheet.py` は既に存在する object を検証する
だけで、fixture path や filesystem を知らない。

fixture に Secret、API key、実 Provider response、Transcript、Telemetry、公開先から不可視な
秘密文字列を入れない。

## 10. Event / State / Provider / I/O を持たない境界

| 境界 | P0-05 の責務 |
| --- | --- |
| Event Log | 読み書きしない。検証済み sheet を Event に append する経路は後続契約に委ねる。 |
| State / Canon | `State`、`Canon`、Projection、reducer を定義せず、直接更新 API を公開しない。 |
| Provider | model call、Provider abstraction、registry、prompt、API key を持たない。 |
| I/O | file read / write、YAML loader、HTTP、DB、SQLite connection を持たない。 |
| Narrative | 自由文を parse して `CharacterSheetV1` や状態へ変換しない。 |
| Transcript / Telemetry | field、store、transaction rollback の責務を持たない。 |

この境界で提供するのは、値を表す Pydantic model と `TypeAdapter` のみである。`ResourceState`
という名前は初期入力内の resource 値を表すが、P0-03 の Projection を直接更新する State API
ではない。

## 11. Phase 1 への先送り

Phase 0 では、P0-05 の validation contract と test-only YAML fixture までを着地させる。
次の判断・実装は Phase 1 へ送る。

- production Character / Scenario `loader`
- loader から Campaign 開始 Event へ正規化する application flow
- Model Gateway、Context Builder、production pipeline
- UI、Browser Client、Editor
- Skill Tree、複数 Ruleset、一般化された Schema / Plugin / Hook / Profile

P0-05 の変更は既存 Campaign の Event Log や Projection を書き換えない。Phase 1 で loader や
Campaign 開始 flow を追加するときも、Event Log を唯一の権威とする P0-03 の境界を越えない。

## 12. Plan、P0-03、ADR との関係

- 本書は承認済み `docs/plans/phase-00-foundation.md` §11 の P0-05 成果物である。P0-05 の
  production source は `src/neontof/contracts/character_sheet.py`、focused test は
  `tests/contracts/test_character_sheet.py`、fixture は
  `tests/fixtures/characters/minimal-character.v1.yaml` とする計画に従う。
- `docs/specs/core-domain-and-events.md`（P0-03）は stable ID、`Visibility`、
  `ContractModel` の strict / extra forbid / frozen / revalidation、Event Log と Projection の
  所有権、Transcript / Telemetry の transaction 外分離を上位の domain 境界として提供する。
  Character Sheet はそれらを再定義せず参照する。
- 技術選定は P0-02b の accepted ADR `docs/adr/0001-technology-stack.md` に従う。Pydantic は
  contract validation に、PyYAML 6.0.3 は test/dev-only fixture parser に限定する。本書は
  ADR を改訂せず、production YAML dependency や新しい runtime adapter を追加しない。
- versioned contract、ID grammar、Visibility、Event 正規化境界を変更する場合は、実装を先に
 変更せず、承認済み Plan と必要な ADR を先に更新する。

この P0-05 では `Plugin`、`Hook`、`Profile`、`loader`、`editor` を追加しない。また、
`contracts.__init__` の root export や production manifest は変更せず、`ResourceState` の
名前衝突を module-qualified import で避ける。

## 13. 検証コマンドと実測結果

次の結果は、2026-08-21 にこの workspace で実行した証拠である。P0-05 の既存実装と focused
test を対象にし、実 Provider、API key、外部 network は使用していない。

### 13.1 focused contract test

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contracts/test_character_sheet.py -q
```

```text
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 0.26s
```

### 13.2 strict type check

実行内容は `mypy --strict src tests --exclude tests/typecheck_fixtures` である。

```powershell
.\.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
```

```text
Success: no issues found in 38 source files
```

### 13.3 production source の承認済み YAML / I/O pattern scan

scan は承認済み plan の狭い pattern だけを対象にする。`_copy_exact_yaml_sequence` は helper
名であり、禁止 hit に含めない。

```powershell
$patterns = @(
    "import yaml",
    "safe_load",
    "yaml.load",
    "unsafe loader",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
    "open",
    "filesystem read",
    "strict=False",
    "publication_visibility.py"
)
foreach ($pattern in $patterns) {
    $hits = @(rg -ni --fixed-strings -- $pattern src/neontof/contracts/character_sheet.py)
    $exit = $LASTEXITCODE
    if ($exit -eq 0) { throw "forbidden source hit: $pattern" }
    if ($exit -ne 1) { throw "rg failed for $pattern with exit $exit" }
}
"production_forbidden_source_hits=0"
```

```text
production_forbidden_source_hits=0
```

### 13.4 本書の encoding、行末、空白、fence

```powershell
$path = "docs/specs/character-sheet.md"
$bytes = [System.IO.File]::ReadAllBytes($path)
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$text = $utf8.GetString($bytes)
$utf8Valid = $true
$hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xef -and $bytes[1] -eq 0xbb -and $bytes[2] -eq 0xbf
$lfCount = ([regex]::Matches($text, "`n")).Count
$crlfCount = ([regex]::Matches($text, "`r`n")).Count
$bareCrCount = ([regex]::Matches($text, '(?<!\r)\r(?!\n)')).Count
$finalLf = $bytes.Length -gt 0 -and $bytes[$bytes.Length - 1] -eq 0x0a
$trailingWhitespaceCount = ([regex]::Matches($text, '(?m)[\t ]+$')).Count
$fenceCount = @(rg -n '^```' $path).Count
if (-not $utf8Valid -or $hasBom -or $crlfCount -ne 0 -or $bareCrCount -ne 0 -or -not $finalLf -or $trailingWhitespaceCount -ne 0) {
    throw "encoding, line ending, final LF, or trailing whitespace check failed."
}
"utf8_bom=$hasBom"
"utf8_valid=$utf8Valid"
"lf_count=$lfCount"
"crlf_count=$crlfCount"
"bare_cr_count=$bareCrCount"
"final_lf=$finalLf"
"trailing_whitespace_count=$trailingWhitespaceCount"
"markdown_fence_lines=$fenceCount"
"markdown_fences_balanced=$($fenceCount % 2 -eq 0)"
```

```text
utf8_bom=False
utf8_valid=True
lf_count=474
crlf_count=0
bare_cr_count=0
final_lf=True
trailing_whitespace_count=0
markdown_fence_lines=34
markdown_fences_balanced=True
```

### 13.5 Git whitespace check

```powershell
$checkOutput = @(git diff --no-index --check -- /dev/null docs/specs/character-sheet.md 2>&1)
$checkExit = $LASTEXITCODE
if ($checkOutput.Count -ne 0) { $checkOutput; throw "git diff --no-index --check found whitespace errors." }
if ($checkExit -ne 1) { throw "unexpected git diff --no-index --check exit code: $checkExit" }
"git_diff_no_index_check=clean"
"git_diff_no_index_exit=$checkExit (untracked diff expected)"
```

```text
git_diff_no_index_check=clean
git_diff_no_index_exit=1 (untracked diff expected)
```

`git diff --no-index --check` は untracked file との比較差分があるため exit code `1` になるが、
空の出力は whitespace error がないことを示す。encoding、LF、bare CR、final LF、trailing whitespace
は 13.4 の直接検査でも確認する。
