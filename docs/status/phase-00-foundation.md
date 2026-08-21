# Phase 0 Foundation Contracts Status Report

## 1. Status / date / branch / scope / Phase 1 stopped

| 項目 | 判定・値 |
|---|---|
| status | Phase 0 Gate: **PASS（local）** / remote CI: **pending** |
| date | 2026-08-21 |
| branch | `docs/phase-00-foundation` |
| scope | `Phase 0: Foundation Contracts`。この報告の書き込み対象は `docs/status/phase-00-foundation.md` のみ |
| HEAD | `66f4fd2` |
| Phase 1 stopped | **停止**。Phase 1の実装・ファイル作成・自動遷移は行わない |

この文書は ROADMAP §15.3 の Phase Status Report、Gate Check 結果、Test 結果、Known Issues、
Playtest 非該当理由、次Phase開始条件をまとめる。Phase 0 Gate後もユーザー判断なしにPhase 1へ進まない。

## 2. Goal / Non-goal / Entry conditions / Gate / Stop conditions

### Goal — PASS（local）

Event互換性、保存データ、テスト、後続機能へ波及する最小契約を固定し、Phase 1を開始できる
Foundation Contractsと、API key・実Provider・外部networkなしで再現可能なTest Harnessを用意した。
実装された契約は次の境界を含む。

- Event Logをゲーム状態の唯一の権威とし、State / CanonをEventから再構築するProjectionとして扱う。
- Semantic ResultをSchema Validation後のStructured Resultとして扱い、Narrative自由文を状態へparseしない。
- Visibility、Evidence、stable ID、strict / frozen contract modelを固定する。
- Fake Provider、Scripted Provider、Recorded Fixtureでsuccess、failure、retry、timeout、invalid JSONを再現する。
- Transcript / Telemetryをゲーム状態のtransaction外へ置き、秘密とraw requestをsanitized call logへ渡さない。

### Non-goal — PASS（未実装を確認）

Phase 0のNon-goalである実Scenarioを遊ぶTurn Engine、Browser Client / UI、永続Event Store、
production Context Builder / visibility filter、migration、SQLite connection、実Provider、
OpenAI SDK、Plugin、Hook、Profile、Manifest、Capability Graph、二つ目のProvider / Ruleset / Scenario形式、
認証、Docker、複数人対応は実装していない。禁止path、source scan、production manifestの証拠は §5 に示す。

### Entry conditions — すべて満たす

Phase開始時の計画記録および実ファイルから、次を満たしたと判定する。

- `docs/PRODUCT_PLAN.md` と `docs/IMPLEMENTATION_ROADMAP.md` が存在する。
- Git運用方針が `AGENTS.md` にあり、専用branch `docs/phase-00-foundation` で作業した。
- 候補Bの承認範囲と `docs/adr/0001-technology-stack.md` の `Accepted` が存在する。
- `.python-version` は `3.14.3`、runtime / dev dependency root set、hash付きlockが存在する。

### Phase 0 Gate — local PASS / remote pending

P0-01〜P0-07の契約、Fake / Fixture、Projection、秘密境界、Non-goal absence、品質ゲートはlocalで
PASSした。`requirements.lock.txt` のfresh install、`pip check`、compile、format、lint、strict mypy、
pytest、network guard、worker rejection、lifecycle、manifest、forbidden / secret scansは §5 の実測を参照する。

remote CIは現在のHEAD `66f4fd2` に対して実行されていないため、remote Gateはpendingであり、
local PASSをremote greenへ読み替えない。

### Stop conditions — Phase停止条件は未発火

Phaseを拡張・設計変更するRoadmap上のStop conditionは検出しなかった。P0-07の初期REDは意図した
Test Firstの失敗であり、初回PowerShell lifecycle probeとHook allowlistのsynthetic probeは検証方法の問題として
別経路へ切り替えた。Phaseの契約を縮小・再設計する条件、同一手法を2回失敗した条件は発生していない。

### Playtest report — 非該当

Phase 0のNon-goalに実Scenario、Turn Engine、Browser Clientが含まれるため、Playtestは実施対象外である。
Phase 1の最重要Gateである「最後まで遊び、翌日もう一度遊びたいと思う」はPhase 1で新たに判定する。

## 3. Work Packages

### P0-01 — Repository and Quality Baseline

**変更内容 / 主な変更ファイル・commit**

`.gitattributes`、`.gitignore`、`.env.example`、`.python-version`、`pyproject.toml`、
`requirements.in`、`requirements-dev.in`、`requirements.lock.txt`、`.github/workflows/ci.yml`、
`src/neontof/app.py`、`src/neontof/config.py`、`src/neontof/main.py`、baseline tests、
network guard、entrypoint lifecycle probeを追加した。主なcommitは次のとおり。

- `f7b7ca9` `chore: Stack非依存のRepository境界を固定する`
- `083f7ad` `chore: PythonのRepository境界を固定する`
- `41453ed` `chore: Pythonのlocked quality runnerをbootstrapする`
- `487f2fa` `test: localhost healthの最初のREDを固定する`
- `c99c478` `feat: 空のFastAPI ApplicationとPython entrypointを追加する`
- `503a9a3` `chore: CIにPython quality gateを再現する`

**実行コマンド / 実出力**

```text
py -3.14 --version
Python 3.14.3

pytest tests/test_app.py tests/test_config.py tests/test_main.py tests/test_no_external_network.py -q
24 passed, 1 warning in 0.38s
exit 0
```

最終品質ゲートのcompile、format、lint、mypy、full pytest、lifecycleは §5 で再実行した。

**Gate寄与**

Python runtime、locked install、CI command order、single worker、health、network禁止、API keyなし、
生成物と禁止pathの基本境界を後続WPへ提供した。

**Known Issue**

既存のdeprecation warningが1件（Starlette/httpx）残る。current HEADのremote CIは未実行でありpendingである。

**次WPとのinterface**

P0-02は `.python-version`、requirements、CI baseline、single-worker境界を入力として、実装stackをADRへ固定する。

### P0-02 — Technology Stack ADR

**変更内容 / 主な変更ファイル・commit**

候補比較を `docs/status/p0-02-technology-stack-evaluation.md` に記録し、候補Bを
`docs/adr/0001-technology-stack.md` へ `Accepted` として固定した。Python `3.14.3`、FastAPI、Pydantic、
Uvicorn、pytest、ruff、mypy、標準 `sqlite3` のownership境界、HTTP POST + SSE + buffered fallback、
Phase 1 Provider候補、Fake / Scripted / Recorded FixtureのPhase 0境界を記録した。主なcommitは次のとおり。

- `d694abc` `docs: 技術スタック候補の比較結果を記録する`
- `987b4ca` `docs: Phase 0計画をPython Stackへ更新する`
- `86745c3` `docs: 技術スタックの決定をADRに記録する`
- `5d21275` `docs: lock生成手順を再現可能に補正する`

主なファイルは `docs/adr/0001-technology-stack.md`、
`docs/status/p0-02-technology-stack-evaluation.md`、`docs/plans/phase-00-foundation.md` である。

**実行コマンド / 実出力**

```text
py -3.14 --version
Python 3.14.3

docs/adr/0001-technology-stack.md
状態: Accepted
決定者: 【承認メタデータ】ユーザーの明示承認「Bで承認」
```

fresh lock install、`pip check`、quality command、health / shutdown / rebindは §5 に示す。

**Gate寄与**

Stackの保留状態を解消し、P0-03以降が依存するruntime、validation、single-worker、Phase 0 Provider、
SQLite接続をまだ作らない境界を一意にした。

**Known Issue**

remote CI、実Provider call、Provider usage / timeout、migration実装、検索実装、Dockerは未確認またはPhase 0外である。

**次WPとのinterface**

P0-03はこのstack上で `ContractModel`、Event、Projection、turn status、TypeAdapterの契約を固定する。
Phase 0では `sqlite3.connect` を作らず、P1-01のowner契約へ送る。

### P0-03 — Core Domain and Event Model Specification

**変更内容 / 主な変更ファイル・commit**

`src/neontof/contracts/base.py`、`ids.py`、`domain.py`、`event_parser.py`、`projection.py`、
`turn_status.py`、`docs/specs/core-domain-and-events.md`、contract tests、event fixtures、negative mypy fixtureを追加した。
Test First RED、反証、unknown field redaction、直前Turn以外のrevert拒否を経て、EventからProjectionを再構築する実装と仕様を着地させた。
主なcommitは `6801c0b`、`d51686a`、`c7cca66`、`d65209e`、`b9cfab0`、`5622168`、`051a88f`、`e7fd42f` である。

**実行コマンド / 実出力**

```text
pytest tests/contracts/test_contract_model.py tests/contracts/test_domain.py tests/contracts/test_event_parser.py tests/contracts/test_turn_status.py -q
86 passed, 1 warning in 0.25s
exit 0
```

negative mypyの補助証拠は §5 に分離して記録する。

**Gate寄与**

Event Log唯一権威、stable ID、Event version / payload validation、Fact ID導出、Projection再構築、
`awaiting_player`を含むturn status、Transcript / TelemetryをDomain Eventへ渡さない型境界を固定した。

**Known Issue**

既存のPydantic `model_fields` instance access warningが1件残る。Event Store、永続Projection、migration、
direct State update APIはNon-goalとして実装していない。

**次WPとのinterface**

P0-04は `DomainEvent`、`FactRecord`、Visibility、Evidence、Projection型を入力に、
`SemanticResultV1`を検証してからAccepted proposalだけをmaterializeする。

### P0-04 — Semantic Result Specification

**変更内容 / 主な変更ファイル・commit**

`src/neontof/contracts/semantic_result.py`、`src/neontof/contracts/transport.py`、semantic result / transport tests、
fixture、`docs/specs/semantic-result.md`を追加した。主なcommitは `c51ab55`、`4865c2b`、`adb15d9`、
`b09b9ee`、`0e53039`、`7f3034e` である。

**実行コマンド / 実出力**

```text
pytest tests/contracts/test_semantic_result.py tests/contracts/test_transport.py -q
179 passed in 0.51s
exit 0
```

**Gate寄与**

`SemanticResultV1`、`AcceptedSemanticResult`、rejection / clarification、Evidence可視性、
`proposed_events` / `proposed_facts`とNarrativeの分離、validation前Narrative非送信、SSE / buffered fallbackの同値を固定した。

**Known Issue**

production Context Builder、visibility filter、Event append、retry runtime、real Provider endpointは作っていない。

**次WPとのinterface**

P0-05 / P0-06はこのVisibilityとstrict / frozen contract boundaryをfixtureへ適用する。P0-07は
`AcceptedSemanticResult`とtest-only `materialize_semantic_result_for_test`を再利用し、自由文から状態へ入る経路を作らない。

### P0-05 — Character Sheet Specification

**変更内容 / 主な変更ファイル・commit**

`src/neontof/contracts/character_sheet.py`、`tests/contracts/test_character_sheet.py`、
`tests/fixtures/characters/minimal-character.v1.yaml`、`docs/specs/character-sheet.md`を追加した。
主なcommitは `dc50c58`、`4f233da`、`34b535d`（共通の型境界補正は `0e53039`）である。

**実行コマンド / 実出力**

```text
pytest tests/contracts/test_character_sheet.py -q
84 passed in 0.29s
exit 0
```

**Gate寄与**

strict / frozen Character Sheet、required Visibility、immutable sequence、入力mutation非伝播、test-only YAML
`safe_load`、Resource / location / initial valuesの契約を固定した。

**Known Issue**

YAML file I/OとCharacter Loaderはproductionへ入れていない。`PyYAML==6.0.3`はdev-onlyであり、Phase 0のruntime dependencyではない。

**次WPとのinterface**

P0-06のScenario fixtureとP0-07の公開context test supportが、Character Sheetのstable ID / Visibility型を利用する。

### P0-06 — Scenario Format Specification

**変更内容 / 主な変更ファイル・commit**

`src/neontof/contracts/scenario.py`、Scenario tests / support、5つのScenario fixture、
`docs/specs/scenario-format.md`を追加した。主なcommitは `1d0c682`、`45fc149`、`74085fe`（共通の型境界補正は `0e53039`）である。

**実行コマンド / 実出力**

```text
pytest tests/contracts/test_scenario.py -q
140 passed in 0.89s
exit 0
```

**Gate寄与**

Scenario ID / version、cardinality、reference、duplicate ID、required Visibility、GM-onlyの公開拒否、
public projection、success / failure end condition、test-only YAML boundaryを固定した。

**Known Issue**

Scenario Loader、Editor、複数形式、production YAML I/O、汎用Graph DSLはNon-goalであり未実装である。

**次WPとのinterface**

P0-07はScenario / Characterの公開fixtureを `FactRecord`、Visibility、`SemanticResultV1`の入力検証境界と組み合わせる。

### P0-07 — Test Provider and Fixture Strategy

**変更内容 / 主な変更ファイル・commit**

`src/neontof/model/__init__.py`、`model_invoker.py`、`fake_provider.py`、`scripted_provider.py`、
`recorded_fixture.py`、provider fixtures、`tests/model/**`、network guard補正、
`docs/specs/test-provider-and-fixtures.md`を追加した。API keyや実networkを渡さず、Provider Call Logをtyped / sanitizedにし、
invalid JSONでは成功ModelResponseやEventを生成しない境界を固定した。

P0-07のsource / test historyは次のとおりで、全て履歴上存在する。

- `a357d42` — RED契約とfixtureを追加
- `24b1c16` — `ModelRequest` / `ModelResponse`等のモデル契約
- `1d97bf5` — Recorded Fixture Provider
- `e705da7` — Fake Provider
- `64209fc` — Scripted Provider
- `dcfcf0f` — fixture testの型境界補正
- `c7fc848` — 検証境界を計画へ同期
- `0c01a49` — 最終production manifest integration
- `a28f89a` — Test Provider / Fixture安全境界のspec
- `0607851` — Hook allowlistの比較境界を固定
- `66f4fd2` — Hook allowlistの実測証拠を同期

**実行コマンド / 実出力**

```text
pytest tests/model -q
68 passed
exit 0

pytest tests/test_no_external_network.py -q
8 passed
exit 0

pytest -q
587 passed, 2 warnings in 2.98s
exit 0
```

**Gate寄与**

Fake / Scripted / Recorded Fixtureによるsuccess、failure、retry、timeout、invalid JSONの再現、
sanitized call log、context digest、visibility filter、全pytest sessionのnetwork禁止、API keyなしを提供した。

**Known Issue**

初回PowerShell lifecycle probeはgraceful shutdown timeoutとなったため採用せず、`CREATE_NEW_PROCESS_GROUP`を使う
Python harnessへ切り替えた。これは実装Gateの失敗を隠したものではなく、検証方法の問題として §5 に記録する。

**次WPとのinterface**

P0-07で固定した `ModelResponse`、typed provider step、sanitized call log、Recorded Fixtureの再現性を、
Phase 1のModel Gateway / Turn Engineが利用する。ただしPhase 1のproduction Provider実装はここでは開始しない。

## 4. P0-07 Test First RED → GREEN

### RED — `a357d42` archiveのread-only展開

`a357d42`をgit archiveで一時ディレクトリへread-only展開し、production `neontof.model`がまだ存在しない状態で実行した。

```text
git archive --format=tar --output=<TEMP>\a357d42.tar a357d42
tar -xf <TEMP>\a357d42.tar -C <TEMP>\archive
pytest tests/model -q

63 failed, 5 passed in 0.62s
exit 1
```

63件の失敗は `ModuleNotFoundError: No module named 'neontof.model'` である。`SyntaxError`、collection error、
0 testsはなく、5 passedはtest-only / network / path系の契約である。REDの失敗理由は、後続の最小実装前に
focused contractが失敗することを固定した。

### GREEN — production model着地後

```text
pytest tests/model -q
68 passed
exit 0

pytest tests/test_no_external_network.py -q
8 passed
exit 0

pytest tests/test_no_external_network.py --setup-plan -q
SETUP    S _block_external_network
tests/test_no_external_network.py の8 test node
TEARDOWN S _block_external_network
no tests ran
exit 0

pytest -q
587 passed, 2 warnings in 2.98s
exit 0
```

setup-planは8 nodeを列挙し、session scopeの`_block_external_network`がsetup / teardownされることを示す。
これはsetup planのため実testは実行せず、`no tests ran`でもexit 0となる検査である。

## 5. Final Gate Evidence

以下はPhase 0 final verificationで使ったcanonical commandと実出力である。exit codeは各command直後に保存した。

### 5.1 Runtime / dependency boundary

```text
py -3.14 --version
Python 3.14.3

<TEMP>\venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock.txt
Successfully installed annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.14.2 ast-serialize-0.8.0 certifi-2026.7.22 click-8.4.2 colorama-0.4.6 fastapi-0.141.1 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.19 iniconfig-2.3.0 librt-0.15.0 mypy-2.3.1 mypy-extensions-1.1.0 packaging-26.3 pathspec-1.1.1 pluggy-1.6.0 pydantic-2.13.4 pydantic-core-2.46.4 pygments-2.21.0 pytest-9.1.1 pyyaml-6.0.3 ruff-0.16.3 starlette-1.6.0 types-pyyaml-6.0.12.20260815 typing-extensions-4.16.0 typing-inspection-0.4.4 uvicorn-0.52.3
pip_install_exit=0

<TEMP>\venv\Scripts\python.exe -m pip check
No broken requirements found.
pip_check_exit=0

<TEMP>\venv\Scripts\python.exe -c "import importlib.util; ..."
openai absent
```

fresh temp venvはPython `3.14.3`で作成し、`requirements.lock.txt`を`--require-hashes`でinstallした。
`openai`はimport可能なmoduleとして存在せず、API keyなしである。

### 5.2 Build / format / lint / type / test

```text
.venv\Scripts\python.exe -m compileall -q src
exit 0

.venv\Scripts\python.exe -m ruff format --check src tests
52 files already formatted
exit 0

.venv\Scripts\python.exe -m ruff check src tests
All checks passed!
exit 0

.venv\Scripts\python.exe -m mypy --strict src tests --exclude tests/typecheck_fixtures
Success: no issues found in 51 source files
exit 0

.venv\Scripts\python.exe -m pytest -q
587 passed, 2 warnings in 2.98s
exit 0
```

### 5.3 Network guard / negative mypy

```text
.venv\Scripts\python.exe -m pytest tests/test_no_external_network.py -q
8 passed
exit 0

.venv\Scripts\python.exe -m pytest tests/test_no_external_network.py --setup-plan -q
SETUP S _block_external_network
8 test nodes
TEARDOWN S _block_external_network
no tests ran
exit 0

.venv\Scripts\python.exe -m mypy --strict tests/typecheck_fixtures/transcript_telemetry_into_domain_event.py
tests\typecheck_fixtures\transcript_telemetry_into_domain_event.py:10: error: Argument 1 to "rebuild_projection" has incompatible type "tuple[TranscriptEntry]"; expected "Sequence[CampaignCreatedEvent | SessionStartedEvent | SceneStartedEvent | SceneEndedEvent | PlayerInputAcceptedEvent | <12 more items>]"  [arg-type]
tests\typecheck_fixtures\transcript_telemetry_into_domain_event.py:11: error: Argument 1 to "rebuild_projection" has incompatible type "tuple[TelemetryEntry]"; expected "Sequence[CampaignCreatedEvent | SessionStartedEvent | SceneStartedEvent | SceneEndedEvent | PlayerInputAcceptedEvent | <12 more items>]"  [arg-type]
Found 2 errors in 1 file (checked 1 source file)
negative_mypy_exit=1
error_lines=2
arg_type_lines=2
other_error_lines=0
fixture_filename_fragments=2
rebuild_projection_fragments=2
TranscriptEntry_fragments=1
TelemetryEntry_fragments=1
MYPYPATH restored
```

negative mypyは通常のstrict gateとは別のexpected REDであり、Transcript / TelemetryをDomain Eventへ渡す誤用を
正しく拒否している。`[arg-type]`以外のerrorは0件である。

### 5.4 Manifest / required terms

```text
final production manifest
expected_count=20 actual_count=20 extra=[] missing=[] duplicate=[]
manifest_exit=0

final required terms
required_final_terms_count=7; all_exit_0=True

P0-07 required terms
p0_07_required_terms_count=19; all_exit_0=True
```

final required 7 termsは`FactAsserted`、`derive_fact_id`、`SemanticResultV1`、`AcceptedSemanticResult`、
`CharacterSheetV1`、`ScenarioV1`、`ModelResponse`である。P0-07 required 19 termsも全てexit 0である。

### 5.5 Forbidden / secret / source / path scans

固定禁止語15件はそれぞれ`rg` exit 1、hits 0だった。

```text
publication_visibility.py exit=1 hits=0
filter_context_by_visibility exit=1 hits=0
ContextBuilder exit=1 hits=0
context_builder exit=1 hits=0
openai exit=1 hits=0
anthropic exit=1 hits=0
provider_registry exit=1 hits=0
ProviderRegistry exit=1 hits=0
Capability exit=1 hits=0
Plugin exit=1 hits=0
Profile exit=1 hits=0
sqlite3.connect exit=1 hits=0
sqlite3.Connection exit=1 hits=0
strict=False exit=1 hits=0
payload: FrozenJsonValue exit=1 hits=0
forbidden_fixed_count=15; all_exit_1_hits0=True
```

Hook token scanは現在のsourceで`object_pairs_hook`だけを検出し、allowlist外のviolationsは空だった。
synthetic probeはallowlistの挙動を反証可能にするため、禁止対象を含む入力を与えた。

```text
current_hook_scan_exit=0
current_hook_tokens=object_pairs_hook
current_hook_violations=
synthetic_probe_exit=0
synthetic_detected=Hook,LifecycleHook,hook_registry,object_pairs_hook
synthetic_violations=Hook,LifecycleHook,hook_registry
allowlist=object_pairs_hook
```

その他のscanは次のとおりである。`rg`のexit 1はzero-hitの成功である。

```text
secret_scan_exit=1 hits=0
network_source_exit=1 hits=0
sqlite_source_exit=1 hits=0
lock_openai_exit=1 hits=0
OPENAI_API_KEY_present=False
ANTHROPIC_API_KEY_present=False
root_forbidden_count=0
forbidden_files_count=0
forbidden_dirs_count=0
forbidden_paths_present=False
```

### 5.6 Worker rejection

```text
.venv\Scripts\python.exe -m neontof.main --workers 2
usage: python.exe -m neontof.main [-h] [--host HOST] [--port PORT]
                                  [--workers WORKERS]
python.exe -m neontof.main: error: NEONTOF_WORKERS must be 1
worker_exit=2
```

single worker境界のrejectionは、required message `NEONTOF_WORKERS must be 1`を含むargparse outputでexit 2となった。

### 5.7 Lifecycle / health / rebind

最初のPowerShell `Start-Process` probeはgraceful shutdown timeoutで失敗した。これは検証方法の失敗として記録し、
成功に見せるために削除していない。

```text
Start-Process probe
Graceful shutdown timeout
```

その後、一時 Python `CREATE_NEW_PROCESS_GROUP` harnessへ切り替えた。今回の成功確認では固定のentrypoint test scriptは実行していない。

```text
entrypoint_lifecycle: first status=200 body={"status":"ok"} exit=0 stdout_length=0 stderr_length=0; rebind status=200 body={"status":"ok"} exit=0 stdout_length=0 stderr_length=0; rebind=success
entrypoint_harness_exit=0
```

### 5.8 Line ending / scope

この報告を追加した後、次を実行した。

```text
git diff --numstat
git diff --ignore-cr-at-eol --numstat
（両コマンドとも未追跡ファイルのため出力なし）
git status --short --untracked-files=all
?? docs/status/phase-00-foundation.md
```

未追跡ファイルを含むstatusはこの1 pathだけであり、両numstatの出力は一致した。ファイル内容については
UTF-8 BOMなし・CRLFなしをbyte検査で確認した。`AGENTS.md` / `CLAUDE.md`、
source、tests、plan、ADR、`docs/agent-guide`はこのStatus Report作成で編集していない。

## 6. Commit list

Phase 0の履歴はP0-01〜P0-07の順で着地しており、current HEADまでの最終commitは次のとおりである。

```text
c7fc848 fix: P0-07の検証境界を実装へ同期する
0c01a49 test: 最終production manifestを統合する
a28f89a docs: Test ProviderとFixtureの安全境界を定義する
0607851 fix: Hook allowlistの比較境界を固定する
66f4fd2 docs: Hook allowlistの実測証拠を同期する
```

P0-07 sourceの先行commitも全て存在する。

```text
a357d42 test: P0-07のTest Provider RED契約を固定する
24b1c16 feat: P0-07のモデル契約を追加する
1d97bf5 feat: 記録済みProvider Fixtureを再生する
e705da7 feat: API不要のFake Providerを追加する
64209fc feat: API不要のScripted Providerを追加する
dcfcf0f fix: P0-07 fixtureテストの型境界を補正する
```

P0-01〜P0-06の主な履歴は各WP節のcommit列に記録した。Status Report自身はcommitしない。
commit境界はオーケストレーターが管理し、pushもしない。

## 7. Reviews

### P0-07 per-diff reviews

P0-07の各diffについて一次レビューとClaudeレビューを実施した。初回のblockingは複数diffにわたり計7件で、
修正後は各diffがPASS、blocking 0となった。全diffのnon-blocking総数はここでは推測しない。

### Integrated seam review

統合seamの一次レビューは、次の4 blockingを発見した。

1. production manifest
2. Hook false-positive / gate
3. mypy
4. spec missing

4件は全て修正済みである。Hookの最終allowlist強化はこの統合seam相談から生じ、synthetic probeとfinal verifierで検証した。

### Plan Hook correction

Hook correctionは一次レビュー初回がblocking 1、二周目は一次 / ClaudeともPASSだった。最大2周の収束規則に従い、
三周目レビューは実施していない。最終allowlist強化は統合seam相談で追加し、上記のsynthetic probe / final gateで検証した。
これは三周目レビューを実施したという意味ではなく、プロセス上の残留メモである。

### Spec review

`docs/specs/test-provider-and-fixtures.md` の初回レビューはblocking 4、二周目は一次 / ClaudeともPASSだった。
non-blockingの事実修正18/19はレビュー後に機械的に補正した。補正に対する新しいレビューは実施していない。

### Cross-AI evidence limitation

Claude seamの直接sessionはretrievable bodyを返さず、統合seamについてClaudeの本文を証拠として取得できなかった。
この制約は隠さない。個別diff、spec、planの二周目Claude review、およびfinal gatesが取得できたcross-AI / 独立チェックの範囲である。

### Roles / models

nicknameではなくrole-levelで記録する。

- work implementer: config既定の `gpt-5.6-luna` / Luna max
- quality `planner`、`plan_reviewer`、`impl_reviewer`、`test_designer`、`verifier`: `gpt-5.6-sol`、`xhigh`
- Claude direct review: `opus`、plan mode

## 8. MyWorkflow boundary

MyWorkflow側はNeontoFと別branch / 別commitで管理した。

```text
git branch --show-current
docs/neontof-phase-00-guides

git status --short --untracked-files=all
（出力なし。clean）

git diff --name-only main...docs/neontof-phase-00-guides
projects/NeontoF/agent-guide/architecture.md
projects/NeontoF/agent-guide/build-and-verify.md
projects/NeontoF/agent-guide/coding-style.md
```

sourceとdeployed `build-and-verify.md` のSHA256は一致した。

```text
source:   B12BC1EF3A6F3D74A66CCB364D7950D1221ADE0462FCC5E403FF074D96A697F1
deployed: B12BC1EF3A6F3D74A66CCB364D7950D1221ADE0462FCC5E403FF074D96A697F1
```

NeontoF側の `docs/agent-guide` は編集していない。将来Gate commandが変わる場合は、source-of-truthである
MyWorkflow側の `projects/NeontoF/agent-guide/build-and-verify.md`だけを先に更新し、deploy後にmirrorを再確認する。
pushは行っていない。

## 9. Known Issues / Residual

- full pytestに既存warningが2件ある。
  - Starlette/httpx deprecation: `fastapi\testclient.py` の `httpx` / `starlette.testclient` 境界。
  - Pydantic deprecation: `tests/contracts/test_event_parser.py` の instance `model_fields` access。
- current HEAD `66f4fd2`はpushしていないため、current HEADに対するremote CI runはなくpendingである。
  `gh run list`で見える履歴は `b9cfab0` の failureと `7b1fdc3` の successであり、current HEADのgreenではない。
- `docs/specs` required term evidenceはP0-07で19/19へ補正済み。残るnon-blockingはdocs table / link consistencyと
  `_ORIGINAL_GETADDRINFO`のdead valueである。
- P0-03 / §15の古いbare Hook scan表記は、P0-07 canonical pathのallowlist検証と衝突しない。gardeningへ繰り越し、
  このPhaseで追加修正しない。
- 一時的なexternal probe directoryがrepository外に残る可能性がある。repositoryへcommitしていない。
- 初回PowerShell lifecycle probeのgraceful timeoutと、Hook allowlistのsynthetic probeにおけるPowerShell入力ミスは、alternate verificationで
  修正した。どちらも成功証拠から隠していない。

## 10. Decision

**Phase 0 Gateはlocal PASS。remote CIはpending。Phase 1は未開始で、この時点で停止する。**

このPhaseについて追加のhuman judgmentはない。Phase 1開始には、新しいユーザー指示と、必要ならcurrent HEADをremoteへ反映した
CI結果の確認が必要である。Phase 0 Gateを通過したことを理由に、Phase 1のsource、tests、client、migrations、OpenAI SDK、
実Provider、production Context Builderを先行作成しない。
