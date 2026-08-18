# ADR 0001: NeontoF の技術スタックを候補 B で固定する

- 日付: 2026-08-18
- 状態: Accepted
- 決定者: 【承認メタデータ】ユーザーの明示承認「Bで承認」
- 対象: Phase 0 / P0-02b
- 主な証拠: [P0-02a 技術スタック候補調査・比較・スパイク・評価報告](../status/p0-02-technology-stack-evaluation.md)
- 計画: [Phase 0 Foundation Contracts 詳細 Implementation Plan](../plans/phase-00-foundation.md)

## 証拠等級と状態ラベル

この ADR の主等級は、`【実測】`（この ADR または評価報告に記録した再現可能な実行結果）、
`【外部】`（公式ドキュメント等の一次資料）、`【ベンダー主張】`（ベンダー自身の説明）、
`【推測】`（実測や資料から導く設計判断）である。`【リポジトリ一次】` は
`PRODUCT_PLAN.md`、`IMPLEMENTATION_ROADMAP.md`、評価報告など、リポジトリ内の一次資料を示す
出典補助ラベルであり、主等級を置き換えない。`【承認メタデータ】` はユーザーの決定権限を示す
メタデータであって、技術的な証拠ではない。`【未確認】` は未実行、未実装、または Phase 0 外で
あるという状態ラベルであり、主等級ではない。

## 課題定義

NeontoF の Event 履歴、契約、テスト、後続の保存データと Browser Client に波及する最小の
技術境界を、API key なしで反証可能な形で固定する。これは Phase 0 の Stack 決定であり、
実 Scenario、実 Provider、永続 Event Store、Browser UI を完成させる決定ではない。

### 制約

- 【リポジトリ一次】上位仕様の non-negotiable として、Event Log がゲーム状態の唯一の権威であり、
  State と Canon は Event から再構築する Projection とする。State を直接更新する公開 API は作らない。
- 【リポジトリ一次】Semantic Result は Schema Validation を通した構造化値として扱い、Narrative と
  分離する。自由文を parse して State や Event に変換しない。
- 【リポジトリ一次】公開向け呼び出しへ不可視情報を渡さず、API key を Browser、通常ログ、Prompt、
  Fixture、Transcript に渡さない。非信頼テキストを読む Role に状態変更 Tool を渡さない。
- 【リポジトリ一次】Transcript と Telemetry はゲーム状態の transaction 外へ記録し、失敗した Turn の
  記録や消費済み費用をゲーム状態の rollback で消さない。
- 【リポジトリ一次】Phase 0 は API key、外部 network、実 Provider、production YAML I/O、Database 接続を
  必須にしない。Fake / Scripted / Recorded Fixture で検証可能にする。
- 【リポジトリ一次】現在 Phase の Non-goal を実装せず、二つ目の具体実装がない Provider / Ruleset の
  汎用階層、Plugin、Hook、Profile、Manifest、Capability Graph を作らない。

### 成功基準

- 【実測】候補 B の fresh lock install、compileall、ruff format/check、mypy、pytest、実 socket
  health、Pydantic strict validation、SQLite rollback/FTS5、Fake Provider、transport fallback、
  secret boundary が評価報告に記録されている。
- 【推測】採用値と runtime/dev dependency の境界、Uvicorn single worker、SQLite の所有権、
  migration 境界、Phase 1 Provider 候補、A/C/D の判定がこの ADR から一意に読める。
- 【推測】Semantic Result を検証してから公開し、SSE 非対応時も buffered fallback で同じ
  Semantic Result を返す契約を維持できる。
- 【リポジトリ一次】Phase 0 の必須検証は API key なし・実 Provider なし・外部 network なしで再現できる。
- 【未確認】CI parity、Docker / 実 container、実 Provider call、Provider の usage / timeout、
  versioned SQL migration の実装、検索実装はこの ADR の成功証拠に含めない。

## 決定

【実測】【リポジトリ一次】評価報告に記録された候補 B の fresh lock install、quality、strict
validation、実 socket lifecycle、SQLite、Fake Provider、transport、secret、projection の結果と、
下記の設計推測を根拠に候補 B を採用し、Phase 0 以降の実行経路として固定する。候補 C は対抗案、
候補 A は追加検証が必要な不採用、候補 D は不採用とする。
【承認メタデータ】ユーザーの「Bで承認」はこの技術決定を承認する権限を記録するものであり、
技術的な採用理由の代替ではない。候補比較の一次記録は評価報告であり、この ADR はその評価と
承認を記録する。

### B と C を分けた採用理由

#### B（採用）

- 【実測】B は fresh lock venv/install を exit `0` で再現した。 【推測】Phase 0 の契約を実行する依存集合を、再現可能な locked install の境界として採用する。
- 【実測】B の Pydantic probe は `ConfigDict(strict=True, extra="forbid")` による unknown field、
  文字列から int への coercion、不可視 Evidence、invalid JSON の reject と field path を確認した。
  【推測】この Structured Validation を Semantic Result の固定境界に置けば、Narrative 自由文を
  状態へ流し込まない契約を実装できる。
- 【実測】B の Uvicorn probe は health、shutdown、PID 終了、再 bind を確認した。 【外部】Uvicorn は
  worker 数と ASGI lifespan を別々に扱い、複数 worker では lifespan が worker ごとに実行される。
  【推測】Phase 0 の lifecycle と所有権を一つに保つため、Uvicorn は single process / single worker
  境界で採用する。
- 【実測】B の transport probe は、検証後の HTTP POST + SSE payload と buffered fallback payload の
  同値、および未検証 Narrative を先行公開しない境界を確認した。 【推測】SSE の有無で Semantic Result
  の意味を変えないことが B の採用境界である。
- 【実測】B の標準 `sqlite3` probe は rollback と FTS5 trigram を exit `0` で確認した。 【外部】Python
  `sqlite3` は既定で接続作成スレッドを検査し、別 thread からの利用や共有時の書き込み直列化を説明する。
  【推測】Phase 1 は標準 `sqlite3` の connection owner を一つに閉じ込め、single writer として扱う。
- 【推測】B の fresh lock、Pydantic strict field path、Uvicorn の実 socket health / shutdown / rebind、
  Python 標準 `sqlite3` の connection owner 境界を、Phase 0 の契約と後続の一人保守境界へ採用する。
  これは C の共通 probe PASS と両立する採用判断である。fixture の記述性、長期保守コスト、
  developer-day を比較測定したとは主張しない。

#### C（対抗案）

- 【実測】C は Go `1.26.4`、`net/http`、`database/sql`、`modernc.org/sqlite v1.56.0`、標準 testing、
  Vite vanilla TypeScript で quality、common probe、rollback、FTS5、3文字 `MATCH`、2文字 `MATCH` 空、
  `LIKE` fallback を PASS し、技術的に成立した。
- 【実測】P0-02 評価報告の共通 probe では、C も strict schema validation、Fake Provider / retry、
  streaming / transport fallback、secret、projection determinism を各 exit `0`・一致・PASS とした。
  C の health は `httptest.NewServer` による close までの実測であり、B の Uvicorn 実 socket health /
  shutdown / rebind とは別の実測である。
- 【推測】B と C の選択は C の共通 probe PASS や技術的成立性を否定するものではない。B は上記の
  B 固有の実測を Phase 0 契約と後続の一人保守境界へ採用する設計判断により採用し、C は対抗案として
  再評価トリガーまで保持する。

### 採用する Stack

| 領域 | 採用値 | 証拠と適用境界 |
|---|---|---|
| Runtime | Python 3.14.3 | 【実測】評価報告の B fresh venv で確認。Phase 0 の runtime pin と lock の基準にする。 |
| Server | FastAPI `0.141.1` / Uvicorn `0.52.3` | 【実測】B の install と実 socket health、shutdown、PID 終了、再 bind を確認。 【外部】Uvicorn の worker / lifespan の資料に基づき、【推測】single process / single worker 境界で使う。 |
| Contract validation | Pydantic `2.13.4` | 【実測】`ConfigDict(strict=True, extra="forbid")` で unknown field、文字列から int への coercion、不可視 Evidence、invalid JSON を field path 付きで reject。 【推測】固定境界は `ConfigDict(strict=True, extra="forbid", frozen=True)`、公開 collection の `tuple` / `frozenset`、discriminated union の `TypeAdapter` 検証、Pydantic mypy plugin 設定を含む。 |
| Database / driver | SQLite + Python 標準 `sqlite3` | 【実測】B で rollback と FTS5 trigram の追加 probe が exit `0`。 【推測】Phase 0 は接続を作らず、Phase 1 では後述の single writer / connection owner 境界を守る。 |
| Test | pytest `9.1.1` | 【実測】B の `pytest` は `9 passed`。Fake、契約、secret、projection、transport の API key なし検証に使う。 |
| Format / lint / type | ruff `0.16.3` / mypy `2.3.1` | 【実測】B の format check、lint、mypy が exit `0`。 |
| Client | Vite + vanilla TypeScript | 【実測】B 評価で Vite client build を確認。 【推測】採用は Phase 1 の Client 境界に限り、Phase 0 に `client/**` を作らない。 |
| Transport | HTTP POST + SSE + buffered fallback | 【実測】B の transport probe で、検証後の SSE payload と buffered payload の同値、および未検証 Narrative を先行公開しない境界を確認。 【推測】Phase 0 は pure contract のみを固定する。 |
| Migration | versioned SQL migration files | 【推測】Schema evolution の方式だけを固定する。将来の `migrations/0001_initial.sql` は記録上の候補であり、Phase 0 に migration file、schema、runner、`migrations/**` を作らない。 |
| Phase 0 Provider | Fake / Scripted / Recorded Fixture | 【実測】API key と network なしで success、error、timeout、retry、call count、sanitized call log を再現。 【推測】実 Provider の代替ではなく、Phase 0 の test-only boundary とする。 |
| Phase 1 first Provider 候補 | OpenAI Responses API + official Python SDK | 【ベンダー主張】OpenAI の公式資料は Responses API の Structured Outputs / streaming と server-side key 保持を説明する。 【実測】評価では `openai==3.2.0` の import と `responses.create` の存在だけを TEMP で確認し、`api_call=False`。 【推測】これは候補の記録に留め、Phase 0 の依存、実通信、API key、課金、production prompt に含めない。 |

### Contract validation の固定境界

- 【実測】P0-02a 評価で実行済みなのは、候補 B の `ConfigDict(strict=True, extra="forbid")` による
  unknown field、coercion、visibility（不可視 Evidence）、invalid JSON の negative probe と field path
  の確認である。これは候補構成の評価 probe が実行済みという意味であり、NeontoF repository の
  Contract 実装が済んだという意味ではない。
- 【推測】P0-01b 以降の公開契約は `ConfigDict(strict=True, extra="forbid", frozen=True)` を固定境界とする。
  `frozen=True` だけに依存せず、公開契約の immutable collection は `tuple` / `frozenset` 等で表現する。
  discriminated union は discriminator を持つ型として定義し、Pydantic `TypeAdapter` を入口に検証する。
- 【未確認】P0-01b で、上記の strict / unknown / coercion / visibility / invalid JSON の negative fixture、
  immutable collection、discriminated union の `TypeAdapter`、および mypy の `pydantic.mypy` plugin と
  その設定の読み込み・型エラー検出を repository の quality gate として実装・検証する。P0-02a の
  probe 結果を P0-01b の実装済み証拠へ昇格させない。

### Dependency の補助境界

- 【実測】PyYAML 6.0.3（`PyYAML==6.0.3`）は UTF-8 mapping fixture を `safe_load` する test/dev-only の
  実測補助であり、production YAML I/O ではない。2026-08-19 に Python 3.14.3 の TEMP venv で、API key を
  設定せず、Provider その他の外部 API call を行わない probe を実行した。`TEMP_ROOT` はリポジトリ外で、
  probe 後に削除した。実行した PowerShell コマンドと、そのコマンドの実出力を分けて記録する。

  **実行した PowerShell コマンド:**
  ```powershell
  $ErrorActionPreference = 'Stop'
  $probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('neontof-pyyaml-' + [guid]::NewGuid().ToString('N'))
  $venv = Join-Path $probeRoot 'venv'
  $python = Join-Path $venv 'Scripts\python.exe'
  $probeExitCode = 0
  $cleanupAttempted = $false
  $cleanupResult = 'not_attempted'
  $cleanupExitCode = $null
  $cleanupError = $null

  function Stop-OnNonZero {
    param(
      [Parameter(Mandatory = $true)][string]$Name,
      [Parameter(Mandatory = $true)][int]$ExitCode
    )
    if ($ExitCode -ne 0) {
      throw "$Name exit code=$ExitCode"
    }
  }

  try {
    Write-Output "TEMP_ROOT=$probeRoot"

    & py -3.14 --version
    $pythonVersionExitCode = $LASTEXITCODE
    Write-Output "python_version_exit_code=$pythonVersionExitCode"
    Stop-OnNonZero -Name 'python_version' -ExitCode $pythonVersionExitCode

    & py -3.14 -m venv $venv
    $venvExitCode = $LASTEXITCODE
    Write-Output "venv_exit_code=$venvExitCode"
    Stop-OnNonZero -Name 'venv' -ExitCode $venvExitCode

    & $python -m pip install --disable-pip-version-check --no-input --quiet --only-binary=:all: PyYAML==6.0.3
    $installExitCode = $LASTEXITCODE
    Write-Output "install_exit_code=$installExitCode"
    Stop-OnNonZero -Name 'install' -ExitCode $installExitCode

    & $python -m pip check
    $pipCheckExitCode = $LASTEXITCODE
    Write-Output "pip_check_exit_code=$pipCheckExitCode"
    Stop-OnNonZero -Name 'pip_check' -ExitCode $pipCheckExitCode

    $safeLoadCode = @'
  import platform
  import yaml

  payload = "名前: ネオント\n件数: 3\n"
  parsed = yaml.safe_load(payload)
  assert parsed == {"名前": "ネオント", "件数": 3}
  print(f"python={platform.python_version()}")
  print("package=PyYAML")
  print(f"PyYAML={yaml.__version__}")
  print("safe_load=utf8_and_mapping_pass")
  print("api_call=False")
  '@
    & $python -c $safeLoadCode
    $safeLoadExitCode = $LASTEXITCODE
    Write-Output "safe_load_exit_code=$safeLoadExitCode"
    Stop-OnNonZero -Name 'safe_load' -ExitCode $safeLoadExitCode
  }
  catch {
    $probeExitCode = 1
    Write-Output "probe_exception=$($_.Exception.Message)"
  }
  finally {
    $cleanupAttempted = $true
    try {
      Remove-Item -Recurse -Force -LiteralPath $probeRoot -ErrorAction Stop
      $cleanupResult = 'success'
      $cleanupExitCode = 0
    }
    catch {
      $cleanupResult = 'exception'
      $cleanupExitCode = 1
      $cleanupError = $_.Exception.Message
    }

    $existsAfterCleanup = Test-Path -LiteralPath $probeRoot
    $cleanupTestPathResult = if ($existsAfterCleanup) { 'exists' } else { 'absent' }
    Write-Output "cleanup_attempted=$cleanupAttempted"
    Write-Output "cleanup_result=$cleanupResult"
    Write-Output "cleanup_exit_code=$cleanupExitCode"
    Write-Output "TEMP_exists_after_cleanup=$existsAfterCleanup"
    Write-Output "cleanup_test_path_result=$cleanupTestPathResult"
    if ($cleanupError) {
      Write-Output "cleanup_error=$cleanupError"
    }
    if ($cleanupResult -ne 'success' -or $existsAfterCleanup) {
      $probeExitCode = 1
    }
  }

  Write-Output "probe_exit_code=$probeExitCode"
  if ($probeExitCode -ne 0) {
    exit $probeExitCode
  }
  ```

  **そのコマンドの実出力:**
  ```text
  TEMP_ROOT=<TEMP_ROOT>
  Python 3.14.3
  python_version_exit_code=0
  venv_exit_code=0
  install_exit_code=0
  No broken requirements found.
  pip_check_exit_code=0
  python=3.14.3
  package=PyYAML
  PyYAML=6.0.3
  safe_load=utf8_and_mapping_pass
  api_call=False
  safe_load_exit_code=0
  cleanup_attempted=True
  cleanup_result=success
  cleanup_exit_code=0
  TEMP_exists_after_cleanup=False
  cleanup_test_path_result=absent
  probe_exit_code=0
  ```

  （出力の `TEMP_ROOT` の具体パスだけは、リポジトリ外の実測値を `<TEMP_ROOT>` に正規化した。）

- 【推測】PyYAML は `requirements-dev.in` と lock の test/dev 側だけに置き、production code に
  YAML import、`safe_load`、YAML filesystem read を置かない。
- 【推測】pip-tools 7.6.1（`pip-tools==7.6.1`）は TEMP の tool venv で lock を生成するための lock-generation tool
  であり、runtime dependency ではない。runtime root set に含めず、Repository に tool venv を
  残さない。
- 【推測】Phase 0 の runtime root set は FastAPI、Pydantic、Uvicorn、dev/test root set は
  PyYAML、httpx、mypy、pytest、ruff、types-PyYAML とする。Phase 0 lock に `openai` を入れない。

### Docker 化の将来経路

- 【推測】採用境界は Python runtime + hash-locked install + 単一 SQLite volume とし、これらを後から
  Dockerfile / container に包めることを将来経路とする。これは Phase 0 に Docker 実装を追加する決定ではない。
- 【外部】Docker の Dockerfile は runtime image を組み立てる命令を、volume は永続データの mount を定義する。
  この資料に基づく将来経路の採用境界と、NeontoF の single-writer SQLite 境界を組み合わせる。
- 【未確認】Dockerfile、image build、container runtime、volume mount、Docker 上の実測は Phase 0 非対象であり、
  今回作らない。Docker 化の再現性は Phase 0 の成功証拠に含めない。

## 候補比較

| 候補 | 構成と適合 | 懸念 / 判定 |
|---|---|---|
| A | 【実測】TypeScript / Node の raw 構成は共通 probe を通過した。別の Node `v24.19.0` + `node:sqlite` probe では remediated typecheck/build、rollback、FTS5、minimal assert が exit `0`。 | 【外部】Node24 `node:sqlite` は Stability `1.2 - Release candidate`。 【未確認】同じ最終構成で format、lint、Vitest、common probe、client build を統合実行した記録がない。 【推測】今回の P0-02 では不採用（追加検証が必要）。raw `better-sqlite3` の結果と Node24 最小 probe は合成しない。 |
| B | 【実測】Python `3.14.3`、FastAPI `0.141.1`、Pydantic `2.13.4`、Uvicorn `0.52.3`、pytest `9.1.1`、ruff `0.16.3`、mypy `2.3.1` で fresh lock、quality、strict validation、実 socket health、SQLite、Fake、transport、secret、projection を確認。 | 【実測】上記の B 固有の証拠と、B/C の採用理由に記した設計推測に基づき採用する。 【承認メタデータ】ユーザーの「Bで承認」は承認権限の記録であり、長期保守コストや正確な作業時間を測定した根拠ではない。 |
| C | 【実測】Go `1.26.4`、`net/http`、`database/sql`、`modernc.org/sqlite v1.56.0`、標準 testing、Vite vanilla TypeScript で quality と共通 probe（strict validation、Fake / retry、transport fallback、secret、projection）を PASS し、rollback、FTS5、3文字 `MATCH`、2文字 `MATCH` 空、`LIKE` fallback を確認。 | 【推測】対抗案として記録する。single binary や明示的な並行性は候補理由になり得るが、長期保守や validation / provider glue の実作業量を測定したとは扱わない。承認後に C の toolchain を再実行しない。 |
| D | 【実測】実行可能な package/config、quality command、health endpoint がなく、build、format、lint、typecheck、test、CI parity の判定対象を提供しない。 | 【推測】不採用。何もしないまま P0-01b または Phase 1 へ進むと Gate を検証できないため、選択保留にはしない。 |

【推測】B を選ぶことは、C が技術的に成立しないという主張ではない。B の採用理由は、評価報告に
記録された B 固有の実測と上記の設計推測であり、ユーザー承認はその決定権限を示すメタデータである。
長期性能・保守費・developer-day を比較測定した結論ではない。

## 1日スパイク方法と判定基準

### 方法

【実測】評価報告では、各候補を UUID 付きの別 TEMP directory に置き、Repository に
`node_modules`、`.venv`、Go module cache、Fixture を残さずに次を実行した。API key は設定せず、
Fake Provider だけを使った。正確な経過時間は計測していないため、「1日」は作業枠の呼称であり、
developer-day の実測値ではない。

1. 【実測】候補ごとに clean setup と、B では初期 venv から lock を生成して別 fresh venv へ
   install する。
2. 【実測】Build / compile、Format、Lint、Typecheck、Test を個別の exit code で確認する。
3. 【実測】`127.0.0.1` の health が JSON を返し、shutdown、PID 終了、再 bind まで成功することを確認する。
4. 【実測】2 insert 後の故意の例外で SQLite の row count が `0` になる rollback を確認する。
5. 【実測】unknown field、coercion、unknown event、不可視 Evidence、invalid JSON を reject し、
   field path を確認する。
6. 【実測】Fake の success、success → error → timeout、retry、call count を API key なしで再現する。
7. 【実測】Semantic Result の検証前に Narrative を公開せず、SSE と buffered fallback の payload が
   同値になることを確認する。
8. 【実測】secret sentinel が response、sanitized log、fixture に出ないことを確認する。
9. 【実測】同じ Event 列を二度 reduce して同じ Projection になることを確認する。
10. 【実測】SQLite FTS5 trigram で3文字以上を `MATCH`、2文字以下を `MATCH` の結果なしとして
    `LIKE` / application-managed fallback へ分離できることを確認する。検索実装や性能比較は行わない。

### 判定基準

- 【推測】最終評価構成の各必須 command が exit `0` で、期待値と一致することを PASS とする。
- 【推測】secret sentinel が漏れず、API key、外部 network、未管理の生成物がないことを必須とする。
- 【推測】候補内の構成を混ぜない。特に A は raw `better-sqlite3` の quality と Node24
  `node:sqlite` の最小 probe を、同一最終構成の PASS として合成しない。
- 【実測】B は fresh lock install、quality、strict validation、実 socket health、SQLite、Fake、
  transport、secret、projection の判定を満たした。
- 【実測】C は候補固有 quality と共通 probe の判定を満たした。
- 【未確認】A は同一最終構成の統合 quality が未確認で、Node24 built-in SQLite も Release candidate。
- 【実測】D は実行可能な判定対象がない。

## アーキテクチャ境界

### ゲーム状態と公開結果

- 【リポジトリ一次】Event Log の append だけがゲーム状態を変更する。State / Canon は Event 列から再構築する
  Projection であり、State を直接 update する公開 API を作らない。
- 【リポジトリ一次】Pydantic で検証した Semantic Result は Event Proposal の入力候補に過ぎず、現在 State、
  Domain Rule、Visibility を検証する Phase 1 の append 経路を通るまで権威を持たない。
- 【リポジトリ一次】Narrative は表示用の出力であり、Narrative 自由文から Event、Fact、State を生成しない。
- 【リポジトリ一次】不可視情報を公開向け Context や model call に混ぜない。Transcript と Telemetry は
  Domain Event union や State projection の入力に含めず、ゲーム状態 transaction の外へ append する。

### SQLite、Migration、Transaction

- 【外部】FastAPI の通常の `def` path operation（sync def route）は外部 threadpool へ移る可能性がある。
  【推測】Phase 1 の SQLite は単一 writer とし、`sqlite3.Connection` の生成・利用・close を同じ実行境界
  （同じ connection owner / thread）へ閉じ込める。connection を event loop、thread、route 間で共有しない。
  【外部】Python 標準 `sqlite3` の `check_same_thread=True` 既定と書き込み直列化の注意もこの境界を支持する。
- 【推測】Event append の transaction 境界は Phase 1 で定義し、検証済み Event の append と projection
  の再構築可能性を守る。Transcript / Telemetry の append はその境界の外に置く。
- 【推測】Migration transaction と Event append transaction は別契約にする。`versioned SQL migration`
  を採用するが、Migration は別の Phase 0 成果物ではない。
- 【未確認】Phase 0 では `sqlite3.connect`、Database file、schema、Event Store、migration runner、
  migration file を作らない。上記の SQLite 所有権と transaction 境界は Phase 1 実装へ引き継ぐ設計決定であり、
  Phase 0 の production 実測ではない。

### Provider、秘密、Network

- 【リポジトリ一次】Phase 0 の Provider 境界は Fake / Scripted / Recorded Fixture のみとする。成功、失敗、
  retry、timeout、invalid JSON を API key と network なしで再現できるようにする。
- 【推測】OpenAI Responses API と official Python SDK は Phase 1 の first Provider 候補であり、
  Phase 0 の requirements、lock、source、test、fixture、実通信、API key に含めない。
- 【未確認】OpenAI API の実 Provider call、Structured Outputs の runtime 挙動、usage、timeout、課金は
  未確認である。SDK surface probe の `api_call=False` を実 Provider の証拠に昇格させない。

## Phase 境界と Non-goal

### Phase 0 に固定する範囲

- 【リポジトリ一次】この ADR の exact Stack、runtime/dev dependency 分離、Pydantic strict validation、
  Fake / Recorded Provider、HTTP POST + SSE + buffered fallback の契約境界を固定する。
- 【リポジトリ一次】Vite + vanilla TypeScript は Phase 1 Client の採用値として記録するが、Phase 0 に
  `client/**`、`package.json`、Node toolchain を作らない。
- 【リポジトリ一次】versioned SQL migration は方式として記録するが、Phase 0 に `migrations/**`、
  `migrations/0001_initial.sql`、schema、runner を作らない。
- 【リポジトリ一次】Phase 0 の quality は API key なしで実行し、実 Provider、外部 network、production YAML I/O、
  Database 接続を持たない。

### Phase 1 以降へ送る範囲

- 【推測】Event Store、single-writer SQLite connection owner、Event append transaction、migration
  transaction、Turn Engine、State / Canon projection の production 実装。
- 【推測】OpenAI first Provider の runtime check、SDK の production 配置、prompt / call policy、
  usage / timeout、API key を server-side environment に保持する経路。
- 【推測】Browser Client、HTTP endpoint、SSE、buffered fallback の production 実装と、
  `awaiting_player` の再開。
- 【推測】日本語検索の production route、FTS5 query、2文字以下の fallback、性能・形態素解析の比較。

### 明示的な Non-goal

- 【リポジトリ一次】Plugin、Hook、Profile、Manifest、Capability Graph、複数 Provider、複数 Ruleset、複数
  Scenario 形式、Provider registry、汎用 Plugin API。
- 【リポジトリ一次】State の直接更新 API、Narrative parser、公開 Context への不可視情報混入、API key の
  Browser / log / prompt / fixture への露出。
- 【リポジトリ一次】実 Scenario、完成 Browser UI、複数人、認証、Dockerfile / container / Docker 配布、公開 deploy、永続 Save、
  完成した検索、実 Provider による Playtest。

## Advisor 往復と証拠の扱い

- 【実測】評価報告には Claude の独立裏取りが記録され、A の raw / remediated 構成の分離、B の
  strict field path と実 socket health、B/C の FTS5 結果、Provider / Migration / CI の未確認が整理されている。
- 【推測】Claude の助言はレビュー記録であり、ユーザーの承認やこの ADR の決定の代替ではない。
- 【推測】load-bearing な採否は、評価報告の実測、公式一次資料、または明示した設計推測のいずれかに
  必ず結び付ける。性能、長期寿命、保守日数を probe から推定しない。

## 再評価トリガー

- 【推測】採用した Runtime、HTTP framework、Validation library、SQLite driver、または Phase 1
  Provider が security fix のある supported release を失い、30日以内に互換 upgrade を通せない。
- 【推測】依存更新後に SQLite rollback、unknown-field rejection、API key sentinel、または FTS5 の
  3文字 `MATCH` / 2文字 fallback のいずれかが再現可能に FAIL する。
- 【推測】Phase 1 の Provider が strict structured output、usage metadata、timeout のいずれかを
  満たせず、同じ Semantic Result 契約を一回の public Fast Path で成立させられない。
- 【推測】Phase 1 で Browser と Server の同時双方向 message が必須となり、HTTP POST + SSE で
  `awaiting_player` の再開を表現できない実例が2件以上記録される。
- 【推測】fresh Windows host または将来の container base image で locked dependency の clean install
  が2回連続して再現不能になる。
- 【推測】日本語の3文字以上の FTS5 trigram と2文字以下の fallback を、選択した SQLite から
  公式仕様に沿って再現できなくなる。
- 【外部】Node24 `node:sqlite` が Release candidate から stable へ移行し、同一最終構成で format、
  lint、Vitest、common probe、client build を通した記録が揃った場合に限り、A の不採用判定を再評価する。

## 公式一次資料

技術選定の外部根拠は必要な機能境界に限る。以下は評価報告が 2026-08-18 に参照した URL と、今回の
blocking 修正で追加した公式資料であり、性能ベンチマーク、長期保守期間、実 Provider の runtime 成功を
証明するものではない。

- 【外部】[Node.js Releases](https://nodejs.org/en/about/previous-releases)
- 【外部】[Node.js v24 `node:sqlite`](https://nodejs.org/download/release/latest-v24.x/docs/api/sqlite.html)
- 【外部】[FastAPI Request Body / Pydantic](https://fastapi.tiangolo.com/tutorial/body/)
- 【外部】[FastAPI concurrency and sync path operation functions](https://fastapi.tiangolo.com/async/)
- 【外部】[Pydantic Configuration](https://docs.pydantic.dev/latest/api/config/)
- 【外部】[Pydantic Unions](https://docs.pydantic.dev/latest/concepts/unions/)
- 【外部】[Pydantic Type Adapter](https://docs.pydantic.dev/latest/concepts/type_adapter/)
- 【外部】[Pydantic Mypy integration](https://docs.pydantic.dev/latest/integrations/mypy/)
- 【外部】[Python `sqlite3`](https://docs.python.org/3/library/sqlite3.html)
- 【外部】[Uvicorn Deployment](https://www.uvicorn.org/deployment/)
- 【外部】[Uvicorn Lifespan](https://www.uvicorn.org/concepts/lifespan/)
- 【外部】[SQLite Transactions](https://www.sqlite.org/lang_transaction.html)
- 【外部】[SQLite FTS5](https://www.sqlite.org/fts5.html)
- 【外部】[Go `net/http`](https://go.dev/pkg/net/http/)
- 【外部】[Go relational database access](https://go.dev/doc/database/)
- 【外部】[Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
- 【外部】[Docker volumes](https://docs.docker.com/engine/storage/volumes/)
- 【外部】[OpenAI Platform overview](https://platform.openai.com/overview)
- 【外部】[OpenAI Responses streaming reference](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal/delta?lang=curl)
- 【外部】[OpenAI API key safety](https://help.openai.com/en/articles/5112595-best-practices-for-api-key)

## 既知の未完了事項と次の入口

- 【未確認】CI workflow と remote run の parity、Dockerfile / 実 container、実 Provider call、Provider
  usage / timeout、versioned SQL migration の実装、Event append transaction の実装、production 検索、
  正確な developer-day 作業時間は未確認または Phase 0 外である。
- 【未確認】A の同一 Node24 `node:sqlite` 最終構成の統合 quality と Node24 `node:sqlite` の stable 化は
  未確認であり、A は追加検証が必要な不採用のままにする。
- 【推測】この ADR の Accepted は技術選定の承認であり、P0-01b の local / CI Gate、実装完了、または
  Phase 1 開始の承認ではない。
- 【推測】Phase 1 へは進まない。まず P0-01b の候補 B による fresh venv、locked dependency、quality
  baseline とその CI parity を完了し、未確認事項を別途解消してから、明示的な入口条件を満たす。
- 【推測】Migration は方式の記録に留まり、Phase 0 の別成果物として扱わない。Phase 1 の SQLite owner、
  Event append、migration transaction の実装判断は、ここで定めた境界を引き継いで行う。
