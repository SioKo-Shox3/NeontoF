# P0-02a 技術スタック候補調査・比較・スパイク・評価報告

## 0. 判定サマリー

- 【外部】Node.js公式Release表では v26 は Current、v24 は LTS と表示される。候補Aの再評価runtimeは Node `v24.19.0` とする（URLは§2）。ただしNode24の`node:sqlite`公式文書は Stability `1.2 - Release candidate` と記載するため、承認済み計画の「supported LTS上でstableならbuilt-in」という条件を満たさない。
- 【実測】候補Aの初回 raw（Node `v26.3.0` + 未調整設定）は `typecheck` exit `1`（`TransferListItem`）と `build` exit `2`（`rootDir`要求）であり、既存のFAIL記録として保持する。raw FAILは後述の追加理由の一つであり、これだけを不採用理由にはしない。
- 【実測】候補Aの追加 remediated probeは `skipLibCheck: true` と build用 `rootDir: "src"` を明示し、Node `v24.19.0`で `npm run typecheck` / `npm run build` がともに exit `0`。同じNode24 `node:sqlite`構成でSQLite最小rollback、FTS5、minimal assertもexit `0`だった証拠を残す。
- 【未確認】候補Aは、上記と同一のNode24 `node:sqlite`最終構成でformat、lint、Vitest、common probe、client buildを通した記録がない。rawの`better-sqlite3`構成とNode24 `node:sqlite`最小probeを合成して最終quality PASSとは判定しない。
- 【推測】候補Aは、Node24 `node:sqlite`のRelease candidateであることと、同一最終構成の統合qualityが未確認であることから、今回のP0-02では不採用（追加検証が必要）とする。
- 【実測】候補Bは fresh lock venv/install exit `0`、Python `3.14.3` / FastAPI `0.141.1` / Pydantic `2.13.4` / Uvicorn `0.52.3`で、strict field path、実socket `127.0.0.1` health/shutdown/rebind、既存full quality/common probe、SQLite FTS5追加probe、Vite client buildを確認した。
- 【推測】推奨1案はB（Python 3.14系のsupported runtime / FastAPI / Pydantic strict / pytest / Python sqlite3 / Vite vanilla TypeScript / versioned SQL migration / HTTP POST + SSE + buffered fallback）とする。これはADRの`Accepted`ではなく、停止2の承認依頼である。
- 【実測】候補Cは既存quality/common probeに加え、SQLite `3.53.3` / `ENABLE_FTS5=1` / modernc.org/sqlite FTS5 trigram、3文字`MATCH`、2文字`MATCH`空、`LIKE` fallback、rollback、非cached qualityを確認した。Cは対抗案として維持する。
- 【実測】候補Dは実行可能なStack・quality command・health endpointを持たないため不採用とする。選択保留のままP0-01bまたはPhase 1へ進めない。
- 【未確認】CI parity、Docker、実Provider call、Provider usage/timeout、versioned SQL migration実装、検索実装、作業時間は未確認またはPhase 0外であり、承認前に自動確定しない。

### 証拠等級

- 【リポジトリ一次】計画・Product Plan・Roadmapの記述は「リポジトリ一次」、公式URLの記述は「外部」、子が実行したコマンド出力は「実測」、設計順位や保守/Docker比較は「推測」、未実行・未確認事項は「未確認」と明示する。
- 【レビュー】Claudeの助言はレビュー記録であり、決定根拠やADRの代替ではない。レビュー記録から導く親判断には別途「推測」を付ける。

## 1. Goal / Non-goal / Entry Conditions / Stop Conditions

### Goal

- 【リポジトリ一次】承認済み `docs/plans/phase-00-foundation.md` §7.2〜§7.6 に従い、候補 A/B/C/D を同一fixture・同一判定基準で比較し、実測出力・不採用理由・再評価条件・承認依頼を残す。
- 【リポジトリ一次】P0-02 の最終的な決定対象は Server言語/Runtime、Web方式、Client方式、Database、Migration、Validation、最初のProvider、Fake方式、Streaming方式、日本語検索経路、Docker化経路である。

### Non-goal

- 【リポジトリ一次】この作業では `docs/adr/0001-technology-stack.md`、`package.json`、lockfile、`src`、`tests`、Dockerfile、Database schema、Browser UI、実Provider本番Prompt、複数Provider Adapter、Plugin APIを作成しない。
- 【実測】Repositoryへの書き込みは本報告ファイルだけであり、候補probeのファイルはすべて `$env:TEMP` 配下に置いて削除した。
- 【リポジトリ一次】Stack承認前に ADR、P0-01b のStack依存実装、Phase 1実装へ進まない。

### Entry Conditions

- 【実測】branch は `docs/phase-00-foundation`、HEAD は `f7b7ca9fd5be60c4ee145074b46940866b4eb09e` だった。
- 【実測】`git ls-files -- src tests package.json package-lock.json go.mod go.sum` は空出力だった。
- 【実測】評価報告の開始前に `docs/status/p0-02-technology-stack-evaluation.md` は存在しなかった。
- 【リポジトリ一次】P0-01a はユーザー指定どおりコミット済みで、計画 §7.2〜§7.6 と `docs/agent-guide/coding-style.md`、`docs/agent-guide/build-and-verify.md` を作業前に確認した。
- 【実測】API keyの値は出力せず、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`API_KEY` はすべて `absent`、`.env` も `absent` だった。

### Stop Conditions

- 【リポジトリ一次】最終評価構成の共通probeまたは候補固有quality commandが一つでもFAILした候補は、そのprobe名・stderr・exit codeを記録してrejectする。初回REDは最終評価構成と分けて保存し、明示したremediated構成の再評価結果で採否を判定する。
- 【リポジトリ一次】A/B/Cがすべて最終評価構成でrejectになった場合はP0-02を停止し、P0-01b、P0-03、Phase 1を開始しない。
- 【リポジトリ一次】secret sentinelがresponse、log、fixtureのいずれかへ出た場合は評価を停止し、成果物を承認対象にしない。
- 【実測】TEMPの対象UUID directoryを削除できない場合は未完了とする。今回の4対象はすべて `exists=False` になった。
- 【リポジトリ一次】Claude独立裏取り、ユーザーのStack承認、ADR作成は後続であり、この報告で自動確定しない。

## 2. 選定基準と外部資料

### 選定基準

- 【リポジトリ一次】PRODUCT_PLAN §23 の基準は、(1)一人で保守できる、(2)Test Providerへ差し替えられる、(3)Event transactionを単純に実装できる、(4)Browser ClientとServerを分離できる、(5)日本語検索へ拡張できる、(6)Streamingまたは進行状況通知を実装できる、(7)API keyをserverに保持できる、(8)Docker化を後から行える、(9)ライブラリや規格の寿命が極端に短くない、(10)二つ目の実装がない段階で過剰な抽象化を要求しない、である。
- 【リポジトリ一次】ROADMAP P0-02 は上記に加え、SQLite等の単一transaction、強いStructured Validation、Fake Provider差し替え、Streaming非対応時にも正しさを維持することを受け入れ条件に含める。
- 【リポジトリ一次】Event Log単一権威、Semantic ResultとNarrativeの分離、秘密を渡さない、Transcript/Telemetryをゲーム状態transaction外に置くことはStackに依存しない評価前提である。

### 親が確認した公式一次資料

- 【外部】Node.js Releases: https://nodejs.org/en/about/previous-releases （アクセス日: 2026-08-18）
- 【外部】Fastify Validation and Serialization: https://fastify.dev/docs/v5.7.x/Reference/Validation-and-Serialization/ （アクセス日: 2026-08-18）
- 【外部】FastAPI Request Body / Pydantic: https://fastapi.tiangolo.com/tutorial/body/ （アクセス日: 2026-08-18）
- 【外部】SQLite Transactions: https://www.sqlite.org/lang_transaction.html （アクセス日: 2026-08-18）
- 【外部】Zod: https://zod.dev/ （アクセス日: 2026-08-18）
- 【外部】Vitest Getting Started: https://vitest.dev/guide/ （アクセス日: 2026-08-18）
- 【外部】Go `net/http`: https://go.dev/pkg/net/http/ （アクセス日: 2026-08-18）
- 【外部】Go relational DB tutorial: https://go.dev/doc/database/ （アクセス日: 2026-08-18）
- 【外部】OpenAI Platform overview: https://platform.openai.com/overview （Phase 1 Provider候補の公式一次資料URL）
- 【外部】OpenAI Responses streaming reference: https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal/delta?lang=curl （Phase 1のstreaming候補の公式一次資料URL）
- 【外部】OpenAI API key safety: https://help.openai.com/en/articles/5112595-best-practices-for-api-key （server-side key保持の公式一次資料URL）
- 【外部】Node.js v24 `node:sqlite`: https://nodejs.org/download/release/latest-v24.x/docs/api/sqlite.html （Node24のStability `1.2 - Release candidate`の公式文書）
- 【外部】SQLite FTS5: https://www.sqlite.org/fts5.html （FTS5 trigramとtoken長制約の公式一次資料URL）
- 【推測】上記資料は候補の公式機能境界を確認する根拠であり、性能ベンチマークや将来の寿命を証明するものではない。

## 3. 実行環境・共通fixture・実行規律

### 環境の再確認

【実測】実行コマンドとstdoutは次のとおりだった。API keyの値は一度も表示していない。

```text
--- node --version ---
v26.3.0
--- npm --version ---
11.16.0
--- python --version ---
Python 3.14.3
--- pip --version ---
pip 26.1.1 from C:\Users\KINGkawamura\AppData\Roaming\Python\Python314\site-packages\pip (python 3.14)
--- go version ---
go version go1.26.4 windows/amd64
--- gh --version (first line) ---
gh version 2.95.0 (2026-06-17)
--- node built-in sqlite ---
{"sqlite_version":"3.53.1","row":7}
--- python sqlite3 ---
{'sqlite_version': '3.50.4', 'row': 7}
--- API key presence (values never printed) ---
OPENAI_API_KEY=absent
ANTHROPIC_API_KEY=absent
GOOGLE_API_KEY=absent
API_KEY=absent
dot-env=absent
--- optional tools ---
docker=missing
actionlint=missing
act=missing
```

- 【実測】候補 A の `better-sqlite3` import probe は SQLite `3.53.4` と row `7` を返し、exit code `0` だった。
- 【実測】Nodeの依存installでは npm 11 が `better-sqlite3@13.0.3` と `esbuild@0.28.2` の install script pending warningを出したが、import・SQLite操作は実行できた。

### 同一fixture

【実測】A/B/C の各TEMP directoryへ次の同じUTF-8 JSONを作成した。sentinel secretはfixtureへ書いていない。

```json
{"schema_version":1,"action":"probe","value":7}
```

- 【リポジトリ一次】A/B/Cのfixture配置・初期RED・共通probeの順序は `docs/plans/phase-00-foundation.md` §7.5 の指定に従った。
- 【実測】Aは `tests/fixtures/probe-input.json`、Bは `tests/fixtures/probe-input.json`、Cは `tests/fixtures/probe-input.json` で同じ内容を読み込んだ。
- 【実測】Aの一時directory `neontof-p0-02-ts-7c98e42c30414d8ea5cd3e4914639cb2`、Bの初期/fresh directory `neontof-p0-02-python-8b1b3d3891014bdf84255b2d15b7ae80` / `neontof-p0-02-python-fresh-e7afff4f970641829dbe470972e0641f`、Cの `neontof-p0-02-go-f518f44c2d514753a3a4a152d5d1d5e7` は、検証後に削除した。

## 4. A/B/C/D 比較表

| 候補 | 構成 | 実測された適合 | 懸念・不採用理由 | 判定 |
|---|---|---|---|---|
| A | 【実測】rawはTypeScript / Node.js `v26.3.0` / Fastify / Zod / Vitest / Vite vanilla-tsで、既存記録のclean setupと共通probe 8 testsが通過した。追加probeはNode `v24.19.0` + `node:sqlite`の別構成で実施した。<br>【外部】Fastify、Zod、Vitest、Node Releases、Node24 `node:sqlite`の公式資料は§2のURL。 | 【実測】`skipLibCheck: true` / `rootDir: "src"`のremediated typecheck/build、Node24 `node:sqlite`のrollback、FTS5 trigram、minimal assertはexit `0`。FTS5は3文字`MATCH`、2文字`MATCH`空、`LIKE` fallbackを確認した。 | 【実測】rawの`TransferListItem`型エラーと`rootDir`要求は保持する。<br>【未確認】同一のNode24 `node:sqlite`最終構成でformat、lint、Vitest、common probe、client buildを通した記録がない。rawの`better-sqlite3`結果とNode24最小probeは合成できない。<br>【外部】Node24 `node:sqlite`はStability `1.2 - Release candidate`である。 | 【推測】今回のP0-02では不採用（追加検証が必要）。raw FAILだけでなく、未統合qualityとRelease candidateを理由として分離して判定する。 |
| B | 【実測】Python `3.14.3` / FastAPI `0.141.1` / Pydantic `2.13.4` / Uvicorn `0.52.3` / SQLite `3.50.4` / pytest `9.1.1` / Vite vanilla-ts。<br>【外部】FastAPI/Pydanticの公式資料は§2のURL。 | 【実測】fresh lock install、compileall、ruff format/check、mypy、pytest、common probe 9 tests、Vite client build、Pydantic strict field path、SQLite FTS5 trigram、実socket health/shutdown/rebindを確認した。 | 【実測】旧TestClientには`StarletteDeprecationWarning`が1件あるが補助結果に限定する。追加実socket probeは`127.0.0.1:7321`のHTTP 200、shutdown、PID終了、再bind、stdout/stderr emptyでPASS。<br>【推測】Client TypeScriptとServer Pythonの二言語toolchainは長期保守コストになり得る。 | 【推測】推奨1案。Bの採否health証拠は実socketであり、TestClientを代替にしない。 |
| C | 【実測】Go `1.26.4` / `net/http` / `database/sql` + `modernc.org/sqlite v1.56.0` / `validator/v10 v10.30.3` / 標準testing / Vite vanilla-ts。<br>【外部】Go公式資料は§2のURL。 | 【実測】build、gofmt、vet、`go test -count=1 -v ./...`、`go mod verify`、common probe、Vite client build、SQLite `3.53.3`/`ENABLE_FTS5=1`/FTS5 trigram、3文字`MATCH`、2文字`MATCH`空、`LIKE` fallback、rollback、non-cached qualityがPASS。<br>【推測】single binaryと明示的な並行性は運用面の利点になり得る。 | 【実測】strict decoder、validator、provider glueを手書きする量は追加実装で確認していない。 | 【推測】対抗案。長期保守や実作業量を測定したとは扱わない。 |
| D | 【実測】計画文書だけで、package/config/fixture/quality command/health endpointを作成しない。 | 【実測】実行可能な`build`、`format`、`lint`、`typecheck`、`test`、`GET /health`、CI parityがない。 | 【実測】P0-01b Gateの実行対象を提供できない。<br>【推測】保留したままP0-01bまたはPhase 1へ進むと受け入れ条件を検証できない。 | 【推測】不採用。選択保留のまま先へ進めない。 |

### 候補A内部要素

- 【実測】Package managerは npm `11.16.0` と `package-lock.json` clean installを確認した。
- 【実測】旧rawでは`better-sqlite3` importとtransactionを確認した。追加再評価では`better-sqlite3`依存を0にし、Node `v24.19.0`の`node:sqlite`だけでSQLite `3.53.3`、`ENABLE_FTS5=true`、rollback final row count `0`をassertした。
- 【外部】Provider、Fastify validation、Zod、Vitestの公式資料は §2 のURLで確認済みである。
- 【実測】Aの追加probeは`node:sqlite`をSQLite driverとしてnative addonを必須にしない最小経路を示した。TypeScript 6の依存型宣言には`skipLibCheck`、build出力には`rootDir: "src"`を明示したremediated typecheck/buildを確認した。
- 【未確認】Aの同一Node24 `node:sqlite`構成について、format/lint/Vitest/common probe/client buildを含む統合qualityは未確認であり、`better-sqlite3`構成のquality結果をAの最終構成へ移送しない。

## 5. 同一fixtureによる共通probe結果

【リポジトリ一次】判定は、各候補のテストrunnerが実際に起動し、期待結果をassertしてexit code `0`になることをPASSとする。A/B/Cの各表記には、期待値・実測exit code・一致/不一致を明記する。ただしAはraw `better-sqlite3`構成とNode24 `node:sqlite`最小probeを分離し、同一最終構成でない結果をquality判定へ合成しない。

### 5.1 Candidate A: TypeScript / Node（raw `better-sqlite3`構成とNode24最小probeを分離）

> 【実測】以下のhealth、strict validation、rollback、Fake、transport、secret、projectionのrunner結果は、既存のraw `better-sqlite3`構成の記録である。Node `v24.19.0` + `node:sqlite`は§5.5のrollback、FTS5、minimal assert、remediated typecheck/buildの追加probeだけであり、両構成の結果をAの統合qualityへ合成しない。

| Probe | 期待値 | 実行コマンド・実測 | 判定 |
|---|---|---|---|
| health | `127.0.0.1` loopbackの`GET /health`がHTTP 200と`{"status":"ok"}`を返し、closeできる。 | 【実測】`npm test -- tests/probe.test.ts` のhealth testを含むrunnerはexit `0`、`Test Files 1 passed`、`Tests 8 passed`。test内で`app.listen({host:"127.0.0.1",port:0})`、fetch、`app.close()`を実行した。 | 【実測】一致 / PASS。 |
| strict schema validation | unknown field、unknown event、不可視Evidence、invalid JSONをrejectし、Narrative parseで状態へ入れない。 | 【実測】同じ`npm test -- tests/probe.test.ts`の validation testがexit `0`。Zod `.strict()`、`UnknownEvent`、`gm_only`、`not-json`の4 rejectionをassertした。 | 【実測】一致 / PASS。 |
| SQLite rollback（raw `better-sqlite3`構成） | 2 insert後の故意の例外でrow countが`0`。 | 【実測】同じtestのrollback testがexit `0`。`better-sqlite3` transaction後のrow count `0`をassertした。これはNode24 `node:sqlite`の追加rollback probeとは別構成である。 | 【実測】raw構成では一致 / PASS。A最終構成の統合判定には使用しない。 |
| Fake Provider / retry | API key・networkなしでFake successとsuccess→error→timeoutの順、call count `3`を再現する。 | 【実測】同じtestのFake 2 testがexit `0`。successのcalls `1`、scriptのkind `[success,error,timeout]`、calls `3`をassertした。 | 【実測】一致 / PASS。 |
| streaming fallback | Semantic Resultを先にvalidationし、SSEとbuffered payloadのJSONが同値。 | 【実測】同じtestのtransport testがexit `0`。buffered JSONと`data: ...` payloadのdeep equal、content type、validation後公開flagをassertした。 | 【実測】一致 / PASS。 |
| secret probe | sentinelがresponse、sanitized log、fixtureに出ない。 | 【実測】同じtestのsecret testがexit `0`。3つのbooleanがすべて`false`になった。実secret値は出力していない。 | 【実測】一致 / PASS。 |
| projection determinism | 同じEvent配列を2回reduceしたProjectionがdeep equal。 | 【実測】同じtestのprojection testがexit `0`。時刻・global stateを使わず同じProjectionをassertした。 | 【実測】一致 / PASS。 |
| quality（A最終構成） | Node24 `node:sqlite`構成でformat、lint、typecheck、Vitest/common probe、build、client buildが個別にexit `0`。 | 【実測】Node24 remediatedのtypecheck/buildはexit `0`。一方、同一Node24 `node:sqlite`構成でformat/lint/Vitest/common probe/client buildを通した記録はない。raw Node26のtypecheck/build FAILとraw `better-sqlite3`のquality結果は分離して保持する。 | 【未確認】最終統合quality不成立。Aは今回のP0-02では不採用（追加検証が必要）。 |

### 5.2 Candidate B: Python / FastAPI

| Probe | 期待値 | 実行コマンド・実測 | 判定 |
|---|---|---|---|
| health | loopback healthがHTTP 200と`{"status":"ok"}`、実processがshutdownしPID終了後に再bindできる。 | 【実測】旧`fresh-python.exe -m pytest tests -q`は9 passedでTestClient結果を補助確認。追加fresh venvのuvicornは`127.0.0.1:7321`へ実bindし、GET `/health` HTTP200 / `{"status":"ok"}`、shutdown、PID終了、再bindに成功し、server stdout/stderrはemptyだった。 | 【実測】必須判定一致 / PASS。TestClient単独の結果は補助結果として扱う。 |
| strict schema validation | unknown field、文字列からintへのcoercion、不可視Evidence、invalid JSONをfield path付きでreject。 | 【実測】追加最小modelは`ConfigDict(strict=True, extra="forbid")`。unknown field=`[unknown_field]`、coercion=`[amount]`、不可視Evidence=`[evidence,0,visibility]`、invalid JSON=`[]`でreject。sentinelは出力なし。既存pytestもexit `0`。 | 【実測】一致 / PASS。 |
| SQLite rollback | 2 insert後の故意の例外でrow count `0`。 | 【実測】同じpytestのrollback testがexit `0`。`sqlite3` transaction後のcount `0`をassertした。 | 【実測】一致 / PASS。 |
| Fake Provider / retry | API key・networkなしでFake successとsuccess→error→timeout、call count `3`。 | 【実測】同じpytestのFake/script testがexit `0`。Protocol、FakeProvider calls `1`、script kind順、calls `3`をassertした。 | 【実測】一致 / PASS。 |
| streaming fallback | validation前にNarrativeを出さず、SSEとbuffered payloadが同値。 | 【実測】同じpytestのtransport/route testがexit `0`。`StreamingResponse`と`JSONResponse`のpayload同値、invalid invisible resultのrejectをassertした。 | 【実測】一致 / PASS。 |
| secret probe | sentinelがresponse、log、fixtureに出ない。 | 【実測】同じpytestのsecret testがexit `0`。3つのbooleanがすべて`False`。実secret値は出力していない。 | 【実測】一致 / PASS。 |
| projection determinism | 同じEvent配列を2回reduceして同じProjection。 | 【実測】同じpytestのprojection testがexit `0`。frozen dataclassのProjection deep equalをassertした。 | 【実測】一致 / PASS。 |
| quality | fresh lock venvのcompileall、format、ruff、mypy、pytestがexit `0`。 | 【実測】全quality commandがexit `0`。pytest stdoutは`9 passed, 1 warning in 0.29s`。 | 【実測】一致 / PASS。 |

### 5.3 Candidate C: Go / `net/http`

| Probe | 期待値 | 実行コマンド・実測 | 判定 |
|---|---|---|---|
| health | loopback healthがHTTP 200と`{"status":"ok"}`、serverをcloseできる。 | 【実測】`go test ./...` がexit `0`、`ok example.com/neontof-p0-02-go/internal/probe 2.413s`。`httptest.NewServer`、HTTP GET、JSON decode、closeを実行した。 | 【実測】一致 / PASS。 |
| strict schema validation | unknown field、unknown event、不可視Evidence、invalid JSONをfield validationでreject。 | 【実測】同じ`go test ./...`がexit `0`。`DisallowUnknownFields`、validator/v10の`eq=...`、invalid JSONをassertした。 | 【実測】一致 / PASS。 |
| SQLite rollback | 2 insert後の故意のrollbackでrow count `0`。 | 【実測】同じtestがexit `0`。`database/sql` transactionと`modernc.org/sqlite`でcount `0`をassertした。 | 【実測】一致 / PASS。 |
| Fake Provider / retry | API key・networkなしでFake successとsuccess→error→timeout、call count `3`。 | 【実測】同じtestがexit `0`。`ModelInvoker` function type、Fake calls `1`、script kind順、calls `3`をassertした。 | 【実測】一致 / PASS。 |
| streaming fallback | validation前にNarrativeをWriteせず、SSEとbuffered payloadが同値。 | 【実測】同じtestがexit `0`。`RequestBufferedOrStreamed`と`/probe/result?stream=true`のpayload同値をassertした。 | 【実測】一致 / PASS。 |
| secret probe | sentinelがresponse、log、fixtureに出ない。 | 【実測】同じtestがexit `0`。3つのbooleanがすべて`false`。実secret値は出力していない。 | 【実測】一致 / PASS。 |
| projection determinism | 同じEvent配列を2回reduceしてdeep equal。 | 【実測】同じtestがexit `0`。slice copyだけで時刻/global stateを使わないProjectionを比較した。 | 【実測】一致 / PASS。 |
| quality | build、gofmt、vet、compile-only test、testがexit `0`。 | 【実測】各quality commandがexit `0`。`gofmt -l .`は空出力、compile outputは`ok ... [no tests to run]`、test outputは`ok ... (cached)`。 | 【実測】一致 / PASS。 |

### 5.4 Candidate D

- 【実測】Dには共通fixture、runner、health server、quality commandがないため、common probeを実行する対象がない。
- 【リポジトリ一次】計画 §7.5 の停止文は `P0-02 STOP: D（何もしない／今は決めない）はP0-01b Gateの実行可能なStackを提供しない。` としている。
- 【実測】上記理由によりDをPASS扱いせず、実行可能なStackがないことをreject理由とした。

### 5.5 追加probe（一次/Claudeレビュー対応）

#### Candidate A: Node LTS remediated / `node:sqlite`（最小probeのみ。最終構成ではない）

- 【実測】`npx --yes --package=node@24 node --version` は exit `0`、stdout `v24.19.0`。Node `v26.3.0`はCurrentとしてraw側へ固定した。
- 【実測】既存raw（Node26 + 未調整設定）は `npm run typecheck` exit `1`（`thread-stream` の`worker_threads.TransferListItem`）、`npm run build` exit `2`（TS5011、`rootDir`要求）。このraw FAILは消去せず、最終評価構成から分離した。
- 【実測】別TEMPのremediated構成へ`tsconfig.json`の`skipLibCheck: true`、`tsconfig.build.json`の`rootDir: "src"`だけを追加し、Node `v24.19.0`で次を実行した。

```text
Command: npm run typecheck
Node runtime: v24.19.0
Exit code: 0
stderr: empty

Command: npm run build
Node runtime: v24.19.0
Exit code: 0
stderr: empty
```

- 【実測】`node:sqlite`のみのrollback probeは`better-sqlite3`依存0、SQLite `3.53.3`、`ENABLE_FTS5=true`、2 insert→故意例外→`row_count_after_rollback=0`、assert passed、exit `0`だった。

```json
{"node_runtime":"v24.19.0","sqlite_version":"3.53.3","enable_fts5":true,"row_count_after_rollback":0,"rollback_assert":"passed"}
```

- 【実測】Node24の最小assertはhealth、strict validation、Fake、stream fallback、secret boundary、projection determinismがすべて`passed`、exit `0`だった。API key/secretは出力していない。これは最小assertであり、Aの同一最終構成に対するVitest/common qualityの記録ではない。

```json
{"node_runtime":"v24.19.0","health":"passed","strict_validation":"passed","fake_provider":"passed","stream_fallback":"passed","secret_boundary":"passed","projection_determinism":"passed"}
```

- 【実測】Node24 `node:sqlite` FTS5 trigram probeはSQLite `3.53.3`、`ENABLE_FTS5=true`、3文字`MATCH`「図書館」、2文字`MATCH`空、`LIKE` fallback「天気」、exit `0`だった。

```json
{"node_runtime":"v24.19.0","sqlite_version":"3.53.3","enable_fts5":true,"tokenizer":"trigram","fixture":["図書館","天気"],"three_character_match":["図書館"],"two_character_match":{"status":"ok","rows":[]},"like_fallback":["天気"]}
```

#### Candidate B: strict field paths / real socket health

- 【実測】fresh venv/installはexit `0`。RuntimeはPython `3.14.3`、FastAPI `0.141.1`、Pydantic `2.13.4`、Uvicorn `0.52.3`。
- 【実測】`ConfigDict(strict=True, extra="forbid")`を使った最小modelは、unknown fieldをloc `[unknown_field]`、文字列からintへのcoercionをloc `[amount]`、不可視Evidenceをloc `[evidence,0,visibility]`、invalid JSONをloc `[]`でrejectした。sentinelはresponse/log/fixtureへ出力されなかった。
- 【実測】fresh venvの`uvicorn`実processを`127.0.0.1:7321`へbindし、GET `/health` HTTP `200` / `{"status":"ok"}`、shutdown、PID終了、再bindを確認した。server stdout/stderrはemptyだった。旧TestClient結果は補助結果として残し、必須health判定はこの実socket結果でPASSとした。

#### Candidate C: SQLite FTS5 Japanese path / non-cached quality

- 【実測】Go `1.26.4`、`modernc.org/sqlite v1.56.0`、SQLite `3.53.3`、`ENABLE_FTS5=1`。FTS5 trigram table createはPASSだった。
- 【実測】fixture「図書館」「天気」等で3文字`MATCH`はIDs `1,3`、2文字`MATCH`はerrorなしの0件、`LIKE` fallbackはIDs `2,3`、rollbackの`final_count=0`だった。
- 【実測】`go test -count=1 -v ./...`、`gofmt`、`go build`、`go vet`、`go mod verify`はすべてexit `0`だった。
- 【実測】Python `3.14.3` / `sqlite3 3.50.4`の追加FTS5 probeも`ENABLE_FTS5=true`、3文字`MATCH=[1]`、2文字`MATCH=[]`、`LIKE=[2]`、assertions passed、exit `0`だった。

#### 5.5の判定

- 【実測】A/B/CすべてでFTS5 trigram経路を確認した。AはNode24 `node:sqlite`最小probe、BはPython `sqlite3`追加probe、Cは`modernc.org/sqlite`追加probeである。3文字以上は`MATCH`、2文字語は`MATCH`結果0件、`LIKE`またはapplication-managed fallbackを使う結果が一致した。
- 【外部】SQLite FTS5のtokenizer仕様とtrigramの制約は§2のSQLite FTS5公式資料に紐づける。3文字以上を`MATCH`対象とし、2文字以下はtrigram `MATCH`では結果を得られないため、`LIKE`/application-managed fallbackへ分離する。検索実装自体はPhase 0外の設計課題として分離する。
- 【推測】Bの推奨案とCの対抗案は日本語検索経路の採用可能probeを満たす。AのFTS5結果は技術的証拠として残すが、Release candidateと未統合qualityのため今回の採用判定へ繋げない。長期性能、形態素解析との比較、実作業量はこのprobeから測定しない。

## 6. Clean setup / quality command の実出力

### 6.1 A: Node / npm

【実測】候補Aのsetup commandと結果は次のとおりである。

```text
Command: npm init -y --yes
Exit code: 0
Wrote to ...\package.json

Command: npm install --no-audit --no-fund fastify zod better-sqlite3
Exit code: 0
added 52 packages in 3s

Command: npm install --save-dev --no-audit --no-fund typescript tsx vitest eslint @eslint/js typescript-eslint prettier @types/node @types/better-sqlite3
Exit code: 0
added 133 packages in 11s
npm warn allow-scripts 2 packages have install scripts not yet covered by allowScripts:
npm warn allow-scripts   better-sqlite3@13.0.3 (install: node-gyp rebuild)
npm warn allow-scripts   esbuild@0.28.2 (postinstall: node install.js)
npm warn allow-scripts Run `npm approve-scripts --allow-scripts-pending` to review.

Command: npm ci --no-audit --no-fund
Exit code: 0
added 185 packages in 16s
npm warn allow-scripts 2 packages have install scripts not yet covered by allowScripts:
npm warn allow-scripts   better-sqlite3@13.0.3 (install: node-gyp rebuild)
npm warn allow-scripts   esbuild@0.28.2 (postinstall: node install.js)

Command: npm create vite@latest client -- --template vanilla-ts --yes
Exit code: 0
> create-vite client --template vanilla-ts --yes
Scaffolding project ...\client...
Done. Now run:

Command: npm --prefix client install --no-audit --no-fund
Exit code: 0
added 16 packages in 2s
```

【実測】Aの最初のREDは次のとおりで、runner起動後のmodule missingだった。

```text
Command: npm test -- tests/probe.test.ts
Exit code: 1
RUN  v4.1.10 ...
Test Files  1 failed (1)
Tests  no tests
Error: Cannot find module '../src/probe.js' imported from ...\tests\probe.test.ts
```

【実測】Aのraw `better-sqlite3`構成に対するhistorical quality command結果は次のとおりである。Node24 `node:sqlite`最終構成の結果ではない。

| Command | Exit code | stdout/stderr |
|---|---:|---|
| `npm run format:check`（最終） | 0 | `Checking formatting...` / `All matched files use Prettier code style!` |
| `npm run lint` | 0 | `> eslint src tests`（追加stderrなし） |
| `npm run typecheck` | 1 | `node_modules/thread-stream/index.d.ts(96,73): error TS2694: Namespace "worker_threads" has no exported member 'TransferListItem'.` |
| `npm test -- tests/probe.test.ts`（最終） | 0 | `Test Files 1 passed (1)` / `Tests 8 passed (8)` |
| `npm run build` | 1 | `tsconfig.build.json(5,5): error TS5011: The common source directory ... The 'rootDir' setting must be explicitly set ...` |
| `npm --prefix client run build` | 0 | `vite v8.2.1 ...` / `9 modules transformed.` / `✓ built in 205ms` |

【実測】format checkの初回は未整形probe 3 filesでexit `1`だった。その後、TEMP内だけで計画script `npm run format`を実行し、最終format checkはexit `0`になった。

```text
Command: npm run format:check (初回)
Exit code: 1
[warn] src/probe.ts
[warn] tests/fixtures/probe-input.json
[warn] tests/probe.test.ts
Code style issues found in 3 files. Run Prettier with --write to fix.

Command: npm run format
Exit code: 0
src/probe.ts 51ms
tests/fixtures/probe-input.json 6ms
tests/probe.test.ts 9ms
```

- 【実測】§6.1のA quality表は当時のrunnerが記録したhistorical raw（build exit `1`）として保持する。今回の別TEMP raw再現は同じ未調整設定のbuildがexit `2`だった。いずれもnon-zeroであり、raw FAILをremediated PASSへ上書きしていない。
- 【実測】別TEMPのNode `v24.19.0` remediated構成では`skipLibCheck: true`と`rootDir: "src"`を明示したtypecheck/buildだけがexit `0`である（§5.5）。
- 【未確認】Node24 `node:sqlite`と同一の最終構成でformat、lint、Vitest、common probe、client buildを完走した記録はない。§6.1のraw tableと§5.5のminimal probeをAの最終quality PASSへ合成しない。

### 6.2 B: Python / fresh lock venv

【実測】初期venvとfresh venvのsetup結果は次のとおりである。

```text
Command: py -m venv .venv
Exit code: 0

Command: .venv\Scripts\python.exe -m pip install --upgrade pip
Exit code: 0
Requirement already satisfied: pip ... (25.3)
Successfully installed pip-26.2.1
WARNING: Cache entry deserialization failed, entry ignored

Command: .venv\Scripts\python.exe -m pip install fastapi uvicorn pydantic pytest httpx ruff mypy
Exit code: 0
Successfully installed annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.14.2 ast_serialize-0.8.0 certifi-2026.7.22 click-8.4.2 colorama-0.4.6 fastapi-0.141.1 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.19 iniconfig-2.3.0 librt-0.15.0 mypy-2.3.1 mypy_extensions-1.1.0 packaging-26.3 pathspec-1.1.1 pluggy-1.6.0 pydantic-2.13.4 pydantic_core-2.46.4 Pygments-2.21.0 pytest-9.1.1 ruff-0.16.3 starlette-1.6.0 typing_extensions-4.16.0 typing_inspection-0.4.4 uvicorn-0.52.3

Command: .venv\Scripts\python.exe -m pip freeze | Sort-Object | Set-Content -LiteralPath requirements.lock.txt -Encoding utf8NoBOM
Exit code: 0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.14.2
ast_serialize==0.8.0
certifi==2026.7.22
click==8.4.2
colorama==0.4.6
fastapi==0.141.1
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.19
iniconfig==2.3.0
librt==0.15.0
mypy_extensions==1.1.0
mypy==2.3.1
packaging==26.3
pathspec==1.1.1
pluggy==1.6.0
pydantic_core==2.46.4
pydantic==2.13.4
Pygments==2.21.0
pytest==9.1.1
ruff==0.16.3
starlette==1.6.0
typing_extensions==4.16.0
typing-inspection==0.4.4
uvicorn==0.52.3

Command: C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-python-fresh-e7afff4f970641829dbe470972e0641f\.venv\Scripts\python.exe -m pip install -r C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-python-8b1b3d3891014bdf84255b2d15b7ae80\requirements.lock.txt
Exit code: 0
Successfully installed Pygments-2.21.0 annotated-doc-0.0.5 annotated-types-0.8.0 anyio-4.14.2 ast_serialize-0.8.0 certifi-2026.7.22 click-8.4.2 colorama-0.4.6 fastapi-0.141.1 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.19 iniconfig-2.3.0 librt-0.15.0 mypy-2.3.1 mypy_extensions-1.1.0 packaging-26.3 pathspec-1.1.1 pluggy-1.6.0 pydantic-2.13.4 pydantic_core-2.46.4 pytest-9.1.1 ruff-0.16.3 starlette-1.6.0 typing-inspection-0.4.4 typing_extensions-4.16.0 uvicorn-0.52.3
```

【実測】Bの初期REDは次のとおりで、pytest runner起動後のimport不足だった。

```text
Command: C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-python-fresh-e7afff4f970641829dbe470972e0641f\.venv\Scripts\python.exe -m pytest tests/probe_test.py -q
Exit code: 1
ERROR collecting tests/probe_test.py
ModuleNotFoundError: No module named 'probe_app'
1 warning, 1 error in 0.49s
```

【実測】Bの最終quality commandは次のとおりである。

| Command | Exit code | stdout/stderr |
|---|---:|---|
| `fresh python -m compileall -q src` | 0 | 空出力 |
| `fresh python -m ruff format --check src tests` | 0 | `2 files already formatted` |
| `fresh python -m ruff check src tests` | 0 | `All checks passed!` |
| `fresh python -m mypy src` | 0 | `Success: no issues found in 1 source file` |
| `fresh python -m pytest tests -q` | 0 | `......... [100%]` / `9 passed, 1 warning in 0.29s` |
| `npm --prefix client run build` | 0 | `vite v8.2.1` / `9 modules transformed.` / `✓ built in 130ms` |

【実測】Bのpytest stderr相当のwarningは次のとおりで、test failureではない。

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

【実測】Bのformat初回は2 files unformattedでexit `1`だった。TEMP内で`ruff format src tests`（exit `0`、`2 files reformatted`）を実行し、format checkを再実行してexit `0`にした。初回ruff checkはimport順とsentinel文字列規則でexit `1`だったが、TEMP内で`ruff check --fix src tests`（exit `0`、`1 fixed`）を実行し、再実行は`All checks passed!`となった。

### 6.3 C: Go

【実測】Cのsetup結果は次のとおりである。

```text
Command: go mod init example.com/neontof-p0-02-go
Exit code: 0
go: creating new go.mod: module example.com/neontof-p0-02-go

Command: go get github.com/go-playground/validator/v10 modernc.org/sqlite
Exit code: 0
go: added github.com/go-playground/validator/v10 v10.30.3
go: added modernc.org/sqlite v1.56.0
（依存するgo moduleも追加）

Command: go mod tidy
Exit code: 0
go: warning: "all" matched no packages
```

【実測】実装後に計画指定どおり追加importを反映した。

```text
Command: go get github.com/go-playground/validator/v10 modernc.org/sqlite
Exit code: 0
go: added github.com/go-playground/validator/v10 v10.30.3
go: added modernc.org/sqlite v1.56.0

Command: go mod tidy
Exit code: 0
go: downloading github.com/go-playground/assert/v2 v2.2.0
go: downloading github.com/google/pprof v0.0.0-20260802141513-ef3492d7dac3
go: downloading modernc.org/fileutil v1.4.0
go: downloading github.com/stretchr/testify v1.8.4
go: downloading golang.org/x/tools v0.47.0
go: downloading modernc.org/cc/v4 v4.29.1
go: downloading modernc.org/ccgo/v4 v4.34.6
go: downloading modernc.org/goabi0 v0.2.0
go: downloading gopkg.in/yaml.v3 v3.0.1
go: downloading github.com/pmezard/go-difflib v1.0.0
go: downloading github.com/davecgh/go-spew v1.1.1
go: downloading modernc.org/gc/v2 v2.6.5
go: downloading golang.org/x/mod v0.37.0
go: downloading modernc.org/gc/v3 v3.1.4
go: downloading modernc.org/strutil v1.2.1
go: downloading modernc.org/opt v0.2.0
go: downloading modernc.org/token v1.1.0
go: downloading modernc.org/sortutil v1.2.1
go: downloading github.com/hashicorp/golang-lru/v2 v2.0.7
go: downloading golang.org/x/sync v0.21.0
```

【実測】Cの初期REDと、依存反映前の一度だけの失敗は次のとおりである。

```text
Command: go test ./... (最初のRED)
Exit code: 1
FAIL .../internal/probe [build failed]
internal\probe\probe_test.go:6:6: undefined: BuildHandler

Command: go test ./... (実装後、go get/tidy前)
Exit code: 1
internal\probe\probe.go:13:2: no required module provides package github.com/go-playground/validator/v10
internal\probe\probe.go:14:2: no required module provides package modernc.org/sqlite
```

【実測】Cの最終quality commandは次のとおりである。

| Command | Exit code | stdout/stderr |
|---|---:|---|
| `go build ./...` | 0 | 空出力 |
| `gofmt -l .` | 0 | 空出力 |
| `go vet ./...` | 0 | 空出力 |
| `go test -run '^$' ./...` | 0 | `ok example.com/neontof-p0-02-go/internal/probe 1.600s [no tests to run]` |
| `go test ./...` | 0 | `ok example.com/neontof-p0-02-go/internal/probe (cached)` |
| `npm --prefix client run build` | 0 | `vite v8.2.1` / `9 modules transformed.` / `✓ built in 183ms` |

### 6.4 Provider SDK public surface（TEMP、API callなし）

- 【実測】API keyなしで専用TEMP directoryへOpenAI公式Python packageを一度だけinstallした。`openai-3.2.0`のwheelと依存packageがexit `0`でinstallされた。
- 【実測】install後はimport、version、Responses API client public surfaceだけを確認し、API callは実行しなかった。

```text
Command: python -c "import sys; sys.path.insert(0, TEMP); import openai; client = openai.OpenAI(api_key='not-a-real-key'); print('openai_version=' + openai.__version__); print('OpenAI=' + str(hasattr(openai, 'OpenAI'))); print('responses=' + str(hasattr(client, 'responses'))); print('responses.create=' + str(callable(client.responses.create))); print('api_call=False')"
Exit code: 0
openai_version=3.2.0
OpenAI=True
responses=True
responses.create=True
api_call=False
stderr: empty
```

- 【実測】API keyは実値を設定せず、synthetic probe valueだけをclient constructorへ渡した。`responses.create`の存在を測っただけで、Responses API、課金、usage、timeout、provider runtime behaviorは確認していない。
- 【実測】cleanupは専用pathに限定し、`PREDELETE_EXISTS=True` / `POSTDELETE_EXISTS=False`。Repositoryへpackage、venv、cacheは残していない。
- 【未確認】このsurface probeはProvider実装の採用判定や実provider runtime checkではない。B推奨のfirst Provider runtime checkはPhase 1 Entry Condition / 再評価トリガーへ送る。

### 6.5 D

- 【実測】Dにはclean install、package/config、quality command、health processがないため、A/B/Cのinstall・runner出力は存在しない。
- 【リポジトリ一次】Dは計画 §7.5 の停止文に従って、P0-01bの実装開始条件を提供しない。

## 7. 1日スパイク相当の検証方法と判定基準

### 実行方法

- 【リポジトリ一次】各候補を別のUUID付き `$env:TEMP` directoryへ作成し、Repositoryに`node_modules`、`.venv`、Go module cache、Fixtureを置かない。
- 【リポジトリ一次】初期REDは依存導入、package/config/fixture、test scriptの後にrunnerを起動し、script未定義やrunner未導入を理由にしない。
- 【実測】Aは npm clean setup、Bは初期venv→freeze lock→別fresh venv install、Cは`go mod init`→`go get`→`go mod tidy`を実行した。
- 【実測】Aは `eslint.config.mjs` をTEMP内に作成して `npm run lint` を実行した。Repositoryには作成していない。
- 【実測】Bはfresh venv interpreterをcompileall、ruff、mypy、pytestの全quality commandに使用した。
- 【実測】Cは`go build`、`gofmt -l`、`go vet`、compile-only test、testを実行した。
- 【実測】API keyは設定せず、Fake Providerだけで検証した。
- 【実測】開始時刻を記録する計測器を設けなかったため、正確な費やし時間は算定不能である。追加probeでClaudeレビュー対応と日本語FTS5経路は記録したが、CI parity、Docker、実Provider call、migration/search実装は未確認またはPhase 0外である。

### 判定基準

| Probe | PASS | 今回の実測 |
|---|---|---|
| clean setup | 【リポジトリ一次】locked dependencyを別fresh環境へ再installできる。 | 【実測】Bのfresh lock installはexit `0`、A/Cのclean installもexit `0`。 |
| quality commands | 【リポジトリ一次】Build/Test/Format/Lint/型チェックが個別に失敗を検出し、Windowsで再現する。 | 【実測】B、Cは各最終構成でPASS。Aはraw `better-sqlite3` qualityとNode24 `node:sqlite` remediated typecheck/buildを別々に確認しただけで、同一最終構成のformat/lint/Vitest/common probe/client buildは未確認。 |
| health server | 【リポジトリ一次】127.0.0.1へJSONを返しshutdownできる。 | 【実測】Bは追加uvicornでbind/shutdown/PID終了/rebindを確認し、採否のhealth証拠とした。AはNode24 minimal assert、Cは`go test`/実listen相当であり、Aの最終統合qualityとは分離する。TestClientはBの補助結果。 |
| SQLite transaction | 【リポジトリ一次】2 insert後の故意例外でrow count `0`。 | 【実測】AはNode24 `node:sqlite`最小probe、BはPython `sqlite3`、Cは`modernc.org/sqlite`で各々rollbackを確認。 |
| projection determinism | 【リポジトリ一次】同じEvent配列を2回reduceしてdeep equal。 | 【実測】B/CのrunnerとA Node24 minimal assertで各々PASS。Aの最終統合qualityとは分離する。 |
| structured validation | 【リポジトリ一次】unknown event、不可視Evidence、invalid JSONをfield path付きでrejectする。 | 【実測】B追加probeは`[unknown_field]`、`[amount]`、`[evidence,0,visibility]`、`[]`を確認。AのNode24結果はminimal assert、Cは既存strict rejectとして分離記録する。 |
| Fake / retry | 【リポジトリ一次】success→error→timeoutのscriptとcall countがAPI keyなしで再現する。 | 【実測】B/CのrunnerとA Node24 minimal assertでcalls `3`を確認。Aの最終統合qualityとは分離する。 |
| transport fallback | 【リポジトリ一次】structured部検証前にNarrativeを公開せず、streamなしでも完了Responseを返す。 | 【実測】B/CのrunnerとA Node24 minimal assertで確認。Aの最終統合qualityとは分離する。 |
| secret probe | 【リポジトリ一次】sentinelがresponse/log/fixtureへ現れない。 | 【実測】B/CのprobeとA Node24 minimal assertで3出力false。実secret値は出力しない。 |
| Japanese path | 【リポジトリ一次】公式資料と実測で日本語FTS5 trigram経路を示し、3文字以上`MATCH`、2文字以下fallbackを分離する。 | 【実測】A/B/CすべてFTS5 create、3文字`MATCH`、2文字`MATCH`空、`LIKE`/application fallbackを確認。検索実装はPhase 0外。 |

## 7.1 再現用 assertion manifest

- 【リポジトリ一次】既存の共通fixture `{"schema_version":1,"action":"probe","value":7}`は変更せず、追加assertionが参照する安全な最小 envelope を次の固定値として列挙する。event、visibility、requestは秘密を含まない。

```json
{
  "schema_version": 1,
  "event": {"type": "FactAsserted", "id": "fact:probe", "visibility": "player_visible"},
  "request": {"turn_request_id": "turn:probe", "input": "probe"},
  "secret_fixture_value": "<redacted>"
}
```

| Case ID | 期待値 | 実行runner / 相互参照 |
|---|---|---|
| `HEALTH-B` | `127.0.0.1` health HTTP 200、`{"status":"ok"}`、shutdown後に再bind可能 | 【実測】B追加uvicorn実socketのbind、HTTP 200、shutdown、PID終了、再bindがexit `0`。TestClientは補助結果。 |
| `HEALTH-A-MINIMAL` | Node24 minimal health assert | 【実測】A Node24 minimal assertはexit `0`。A最終統合qualityのhealth証拠とは分離する。 |
| `HEALTH-C` | Go health probe | 【実測】C `go test`/実listen相当がexit `0`。 |
| `STRICT-UNKNOWN-B` | unknown field / unknown event reject | 【実測】B fresh pytest 9 testsがexit `0`。 |
| `STRICT-FIELD-PATH-B` | coercion loc `[amount]`、不可視Evidence loc `[evidence,0,visibility]`、invalid JSON loc `[]` | 【実測】B追加strict modelが各locでrejectし、stdoutへsentinelを出さない。exit `0`。 |
| `SQL-ROLLBACK-A-MINIMAL` | 2 insert後の故意例外でfinal row count `0` | 【実測】A Node24 `node:sqlite` minimal probeがassert exit `0`。 |
| `SQL-ROLLBACK-B` | 2 insert後の故意例外でfinal row count `0` | 【実測】B Python `sqlite3` probeがassert exit `0`。 |
| `SQL-ROLLBACK-C` | 2 insert後の故意例外でfinal row count `0` | 【実測】C `modernc.org/sqlite` probeがassert exit `0`。 |
| `FAKE-RETRY-B-C` | Fake success call count `1`、script `success → error → timeout` call count `3` | 【実測】B/Cの各runnerで順序とcall countをassert、exit `0`。AのNode24結果はminimal assertとして分離する。 |
| `TRANSPORT-B-C` | Semantic Result検証後のbuffered/SSE canonical payloadがdeep equal、未検証Narrativeを先行公開しない | 【実測】B pytest / C Go testのstream fallbackがexit `0`。AはNode24 minimal assertの結果として別記録。 |
| `SECRET-B-C` | response、sanitized log、fixtureのsecret boolean 3項目がすべて`false` | 【実測】B/Cのsecret probeが3項目false。AはNode24 minimal assertで同じ結果だが、実secret値は出力しない。 |
| `PROJECTION-B-C` | 同一Event配列のreduce結果がdeep equal | 【実測】B/Cのprojection testがexit `0`。AはNode24 minimal assertで別記録。 |
| `FTS5-JA-A-B-C` | FTS5 trigram create、3文字`MATCH`、2文字`MATCH`空、`LIKE`/application fallback | 【実測】A Node24 `node:sqlite`、B Python `sqlite3`、C Go `modernc.org/sqlite`で各assert exit `0`。 |
| `QUALITY-A-FINAL` | Node24 `node:sqlite`最終構成のformat/lint/typecheck/Vitest/common probe/client buildがexit `0` | 【未確認】typecheck/buildのみexit `0`。同一構成のformat/lint/Vitest/common probe/client build記録がなく、AはPASSとしない。 |
| `QUALITY-B` | B fresh lock構成のformat/lint/typecheck/test/build相当がexit `0` | 【実測】B §6.2 + §5.5がexit `0`。 |
| `QUALITY-C` | C non-cached構成のformat/lint/typecheck/test/build相当がexit `0` | 【実測】C §6.3 + §5.5がexit `0`。 |

- 【実測】A raw runnerはVitest `Test Files 1 passed` / `Tests 8 passed`、Bはpytest `9 passed`、Cは`go test -count=1 -v ./...`。A rawのVitestはNode24 `node:sqlite`最終構成へ移送せず、BのwarningはTestClient補助結果に限定した。
- 【リポジトリ一次】計画§7.5のPowerShell手順は、各候補を一意な`$env:TEMP` directoryへ作り、同じfixture/判定を再生成する手順である。probe source、node_modules、venv、Go module cacheはthrowaway non-goalのためRepositoryへ残さない。
- 【実測】追加probeのTEMP source/log/cacheは検証後に削除し、Repositoryへ候補実装・fixture・生成物を持ち込んでいない。今回のOpenAI SDK surface probeもTEMPへinstallし、import/version/public surface確認後に明示pathを削除した。

## 7.2 追加probe replay appendix（canonical source）

- 【リポジトリ一次】元のP0-02 full probeのsetup、初期RED、common probeの順序とPowerShell手順は承認済み計画 `docs/plans/phase-00-foundation.md` §7.5を参照する。このappendixは、Claudeレビュー後に追加したstrict field path、実socket health、FTS5、rollback、最小assertを第三者が報告から再構成するためのcanonical sourceである。
- 【実測】以下の期待stdout/exit codeは今回の追加probeで確認した結果を記録する。recipeそのものをRepositoryへ配置したとは扱わず、各コードブロックをTEMPのthrowaway sourceへ保存して実行できる形にしている。
- 【リポジトリ一次】全recipeの入力fixtureは秘密を含まない。実行時は各recipe専用の明示UUID TEMP directory、fresh environment、locked dependencyを使い、実行後にそのdirectoryだけを削除する。元sourceを残さないのは、probe実装・依存展開・ログ・cacheを本体へ持ち込まないためである。

### 7.2.1 B supplementary Python recipe: strict field path and real-socket health

入力fixture（`tests/fixtures/probe-input.json`）:

```json
{"schema_version":1,"action":"probe","value":7}
```

`replay_b.py`:

```python
from __future__ import annotations

import http.client
import socket
import threading
import time
from typing import Literal

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, ValidationError


HOST = "127.0.0.1"
PORT = 7321
FIXTURE = {"schema_version": 1, "action": "probe", "value": 7}


class Evidence(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    visibility: Literal["player_visible"]


class SemanticResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    amount: int
    evidence: list[Evidence]


app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def expect_error(label: str, payload: object, expected_loc: list[object]) -> None:
    try:
        SemanticResult.model_validate(payload)
    except ValidationError as error:
        actual_loc = list(error.errors()[0]["loc"])
        assert actual_loc == expected_loc, (label, actual_loc)
        print(f"{label}_loc={actual_loc}")
        return
    raise AssertionError(label)


def expect_invalid_json() -> None:
    try:
        SemanticResult.model_validate_json("not-json")
    except ValidationError as error:
        actual_loc = list(error.errors()[0]["loc"])
        assert actual_loc == []
        print(f"invalid_json_loc={actual_loc}")
        return
    raise AssertionError("invalid_json")


def start_server() -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        access_log=False,
        log_config=None,
        log_level="critical",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.2):
                return server, thread
        except OSError:
            time.sleep(0.05)
    raise AssertionError("server did not bind")


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()


def get_health() -> tuple[int, str]:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    connection.request("GET", "/health")
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()
    return response.status, body


assert FIXTURE["value"] == 7
expect_error(
    "unknown_field",
    {"amount": 7, "evidence": [], "unknown_field": 1},
    ["unknown_field"],
)
expect_error(
    "coercion",
    {"amount": "7", "evidence": []},
    ["amount"],
)
expect_error(
    "invisible_evidence",
    {"amount": 7, "evidence": [{"id": "evidence:probe", "visibility": "gm_only"}]},
    ["evidence", 0, "visibility"],
)
expect_invalid_json()

first_server, first_thread = start_server()
status, body = get_health()
assert (status, body) == (200, '{"status":"ok"}')
print(f"health_status={status}")
print(f"health_body={body}")
stop_server(first_server, first_thread)
print("shutdown=True")

second_server, second_thread = start_server()
status, body = get_health()
assert (status, body) == (200, '{"status":"ok"}')
print(f"rebind_status={status}")
print(f"rebind_body={body}")
stop_server(second_server, second_thread)
print("rebind_shutdown=True")
print("exit_code=0")
```

- 【リポジトリ一次】実行command（fresh venv内）:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install fastapi==0.141.1 pydantic==2.13.4 uvicorn==0.52.3
.venv\Scripts\python.exe replay_b.py
```

- 【リポジトリ一次】期待値: `unknown_field`、`coercion`、`invisible_evidence`、`invalid_json`のlocと、実socket healthのHTTP 200、shutdown、同一portの再bindをassertする。
- 【実測】今回の追加probeのstdout:

```text
unknown_field_loc=['unknown_field']
coercion_loc=['amount']
invisible_evidence_loc=['evidence', 0, 'visibility']
invalid_json_loc=[]
health_status=200
health_body={"status":"ok"}
shutdown=True
rebind_status=200
rebind_body={"status":"ok"}
rebind_shutdown=True
exit_code=0
```

- 【実測】exit codeは`0`、stderrは`empty`。TestClientはこの実socket結果の補助であり、Bのhealth採否を代替しない。
- 【リポジトリ一次】cleanup: fresh venvと`replay_b.py`を置いた専用TEMP directoryだけを削除する。`$env:TEMP`の親、Repository、他候補のdirectoryは対象にしない。

### 7.2.2 C Go/SQL recipe: FTS5 trigram, Japanese fallback, and rollback

入力fixture:

```json
{"schema_version":1,"action":"probe","value":7}
```

`go.mod`:

```text
module replay

go 1.26

require modernc.org/sqlite v1.56.0
```

`main.go`:

```go
package main

import (
    "database/sql"
    "errors"
    "fmt"
    "log"

    _ "modernc.org/sqlite"
)

func must(err error) {
    if err != nil {
        log.Fatal(err)
    }
}

func main() {
    db, err := sql.Open("sqlite", ":memory:")
    must(err)
    defer db.Close()

    var sqliteVersion string
    var enableFTS5 int
    must(db.QueryRow("SELECT sqlite_version()").Scan(&sqliteVersion))
    must(db.QueryRow("SELECT sqlite_compileoption_used('ENABLE_FTS5')").Scan(&enableFTS5))
    _, err = db.Exec("CREATE TABLE items (value TEXT)")
    must(err)

    tx, err := db.Begin()
    must(err)
    _, err = tx.Exec("INSERT INTO items(value) VALUES (?)", "one")
    must(err)
    _, err = tx.Exec("INSERT INTO items(value) VALUES (?)", "two")
    must(err)
    forcedRollback := errors.New("forced rollback")
    if forcedRollback != nil {
        must(tx.Rollback())
    }

    var rollbackCount int
    must(db.QueryRow("SELECT count(*) FROM items").Scan(&rollbackCount))

    _, err = db.Exec("CREATE VIRTUAL TABLE docs USING fts5(title, tokenize='trigram')")
    must(err)
    _, err = db.Exec("INSERT INTO docs(title) VALUES (?), (?)", "図書館で本を読む", "天気予報を見る")
    must(err)

    var match3 int
    var match2 int
    var likeFallback int
    must(db.QueryRow("SELECT count(*) FROM docs WHERE docs MATCH ?", "図書館").Scan(&match3))
    must(db.QueryRow("SELECT count(*) FROM docs WHERE docs MATCH ?", "天気").Scan(&match2))
    must(db.QueryRow("SELECT count(*) FROM docs WHERE title LIKE ?", "%天気%").Scan(&likeFallback))

    fmt.Printf("sqlite_version=%s\n", sqliteVersion)
    fmt.Printf("enable_fts5=%d\n", enableFTS5)
    fmt.Printf("rollback_count=%d\n", rollbackCount)
    fmt.Printf("match_3=%d\n", match3)
    fmt.Printf("match_2=%d\n", match2)
    fmt.Printf("like_fallback=%d\n", likeFallback)
    fmt.Println("exit_code=0")
}
```

- 【リポジトリ一次】実行command（専用TEMP directory内）:

```powershell
go mod tidy
go run .
```

- 【リポジトリ一次】期待値: `ENABLE_FTS5=1`、rollback後のrow count `0`、3文字`MATCH` 1件、2文字`MATCH` 0件、`LIKE` fallback 1件。
- 【実測】今回のC追加probeのstdout:

```text
sqlite_version=3.53.3
enable_fts5=1
rollback_count=0
match_3=1
match_2=0
like_fallback=1
exit_code=0
```

- 【実測】exit codeは`0`、stderrは`empty`。cleanup後の専用TEMP directory、Go module cache以外のRepository生成物は残していない。
- 【リポジトリ一次】cleanup: `go.mod`、`go.sum`、`main.go`を置いた専用TEMP directoryを削除する。RepositoryへGo moduleやfixtureをコピーしない。

### 7.2.3 A/B SQLite in-memory SQL recipes

#### A: Node24 `node:sqlite`

入力fixture:

```json
{"schema_version":1,"action":"probe","value":7}
```

`replay_node24.mjs`:

```javascript
import { DatabaseSync } from "node:sqlite";

const db = new DatabaseSync(":memory:");
db.exec("CREATE TABLE items (value TEXT)");
db.exec("BEGIN");
db.prepare("INSERT INTO items(value) VALUES (?)").run("one");
db.prepare("INSERT INTO items(value) VALUES (?)").run("two");
try {
  throw new Error("forced rollback");
} catch {
  db.exec("ROLLBACK");
}

const version = db.prepare("SELECT sqlite_version() AS version").get().version;
const enabled = db.prepare("SELECT sqlite_compileoption_used('ENABLE_FTS5') AS enabled").get().enabled;
const rollbackCount = db.prepare("SELECT count(*) AS count FROM items").get().count;
db.exec("CREATE VIRTUAL TABLE docs USING fts5(title, tokenize='trigram')");
const insert = db.prepare("INSERT INTO docs(title) VALUES (?)");
insert.run("図書館で本を読む");
insert.run("天気予報を見る");
const match3 = db.prepare("SELECT title FROM docs WHERE docs MATCH ?").all("図書館").map((row) => row.title);
const match2 = db.prepare("SELECT title FROM docs WHERE docs MATCH ?").all("天気").map((row) => row.title);
const likeFallback = db.prepare("SELECT title FROM docs WHERE title LIKE ?").all("%天気%").map((row) => row.title);

if (rollbackCount !== 0 || match3.length !== 1 || match2.length !== 0 || likeFallback.length !== 1) {
  throw new Error("assertion failed");
}
console.log(`sqlite_version=${version}`);
console.log(`enable_fts5=${Number(enabled)}`);
console.log(`rollback_count=${rollbackCount}`);
console.log(`match_3=${JSON.stringify(match3)}`);
console.log(`match_2=${JSON.stringify(match2)}`);
console.log(`like_fallback=${JSON.stringify(likeFallback)}`);
console.log("exit_code=0");
```

- 【リポジトリ一次】実行command: `npx --yes --package=node@24 node --no-warnings replay_node24.mjs`
- 【実測】今回のA追加probeのstdout:

```text
sqlite_version=3.53.3
enable_fts5=1
rollback_count=0
match_3=["図書館で本を読む"]
match_2=[]
like_fallback=["天気予報を見る"]
exit_code=0
```

- 【実測】exit codeは`0`、stderrは`empty`。期待値は上記stdoutと一致する。
- 【リポジトリ一次】cleanup: Node24 package展開と`replay_node24.mjs`を置いた専用TEMP directoryだけを削除する。Node24最小probeの成功をAの統合quality PASSへ昇格しない。

#### B: Python `sqlite3`

入力fixture:

```json
{"schema_version":1,"action":"probe","value":7}
```

`replay_sqlite.py`:

```python
import sqlite3


db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE items (value TEXT)")
try:
    with db:
        db.executemany("INSERT INTO items(value) VALUES (?)", [("one",), ("two",)])
        raise RuntimeError("forced rollback")
except RuntimeError:
    pass

version = db.execute("SELECT sqlite_version()").fetchone()[0]
enabled = db.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0]
rollback_count = db.execute("SELECT count(*) FROM items").fetchone()[0]
db.execute("CREATE VIRTUAL TABLE docs USING fts5(title, tokenize='trigram')")
db.executemany(
    "INSERT INTO docs(title) VALUES (?)",
    [("図書館で本を読む",), ("天気予報を見る",)],
)
match3 = [row[0] for row in db.execute("SELECT title FROM docs WHERE docs MATCH ?", ("図書館",))]
match2 = [row[0] for row in db.execute("SELECT title FROM docs WHERE docs MATCH ?", ("天気",))]
like_fallback = [row[0] for row in db.execute("SELECT title FROM docs WHERE title LIKE ?", ("%天気%",))]

assert rollback_count == 0
assert match3 == ["図書館で本を読む"]
assert match2 == []
assert like_fallback == ["天気予報を見る"]
print(f"sqlite_version={version}")
print(f"enable_fts5={enabled}")
print(f"rollback_count={rollback_count}")
print(f"match_3={match3}")
print(f"match_2={match2}")
print(f"like_fallback={like_fallback}")
print("exit_code=0")
```

- 【リポジトリ一次】実行command: `python replay_sqlite.py`
- 【実測】期待stdoutは`sqlite_version=3.50.4`、`enable_fts5=1`、`rollback_count=0`、`match_3=['図書館で本を読む']`、`match_2=[]`、`like_fallback=['天気予報を見る']`、`exit_code=0`。exit codeは`0`、stderrは`empty`。
- 【リポジトリ一次】cleanup: `replay_sqlite.py`を置いた専用TEMP directoryだけを削除する。Python標準libraryのin-memory databaseはRepositoryへ保存しない。

- 【推測】A/B/Cのrecipeは、FTS5を検索実装そのものへ拡張するものではない。3文字以上の`MATCH`、2文字以下の`MATCH`空、`LIKE`/application-managed fallback、rollbackというP0-02の技術経路だけを再現し、形態素解析・性能比較・production search routeはPhase 0外へ送る。

## 8. CI parity と生成物検査

- 【実測】`Get-Command`結果は `docker=missing`、`actionlint=missing`、`act=missing` だった。
- 【実測】`.github/workflows/ci.yml=absent` だったため、local quality commandとCI workflowの同一性は確認できない。
- 【実測】`gh --version` は `gh version 2.95.0 (2026-06-17)` だったが、pushもremote runも実施していない。
- 【推測】CI parityは `pending` とする。remote run URL/status/conclusionは未確認であり、local PASSをCI PASSと扱わない。
- 【実測】cleanup後の生成物検査は次のとおりだった。

```text
--- temp targets ---
C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-ts-7c98e42c30414d8ea5cd3e4914639cb2 exists=False
C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-python-8b1b3d3891014bdf84255b2d15b7ae80 exists=False
C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-python-fresh-e7afff4f970641829dbe470972e0641f exists=False
C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-go-f518f44c2d514753a3a4a152d5d1d5e7 exists=False
C:\Users\KINGKA~1\AppData\Local\Temp\neontof-p0-02-openai-sdk-20260818 exists=False
--- repository generated directories ---
node_modules exists=False
.venv exists=False
go.mod exists=False
```

- 【実測】cleanupでは安全ポリシーにより`Remove-Item -Recurse -Force`が拒否されたため、事前に確認した4つの明示UUID pathだけへPowerShell内の`.NET [System.IO.Directory]::Delete(path, $true)`を使った。各削除はexit `0`、Repositoryや`$env:TEMP`親は対象にしていない。

## 9. 再評価トリガー

【リポジトリ一次】承認済み計画 §7.2 のトリガーを、停止2の推奨候補Bと対抗候補Cに合わせて記録する。Aは追加検証が必要な不採用候補として別トリガーを持つ。

- 【リポジトリ一次】選択したRuntime、HTTP framework、Validation library、SQLite driver、Provider SDKがsecurity fixのあるsupported releaseを失い、30日以内に互換upgradeを通せない。
- 【リポジトリ一次】dependency update後にSQLite rollback、unknown-field rejection、API key sentinel test、FTS5 3文字MATCH/2文字fallbackのいずれかが再現可能にFAILする。
- 【リポジトリ一次】選択Providerがstrict structured output、usage metadata、timeoutのいずれかを廃止し、同じSemantic Result契約を一回のpublic Fast Pathで満たせない。
- 【リポジトリ一次】Phase 1の実測でBrowserからServerへの同時双方向messageが必須になり、HTTP POST + SSEで`awaiting_player`再開を表現できない事例が2件以上記録される。
- 【リポジトリ一次】Phase 3 Entry Conditions時点で、選択Databaseから日本語3文字以上のFTS5 trigram検索と2文字以下のLIKE/application fallbackへ進む公式support経路がなく、合成日本語fixtureを検索できない。
- 【リポジトリ一次】fresh Windows hostまたは将来のcontainer base imageでlocked dependencyのclean installが2回連続して再現不能になる。
- 【推測】BのTestClient warningは実socket probeの採否を変えなかった。将来のdependency更新でwarningがerror化する、またはfresh lock install/quality gateが再現不能になる場合は、B推奨案を再評価する。
- 【外部】OpenAI公式資料に記録したStructured Outputsの`json_schema`/`strict`、Responses streaming、server-side SDK、backend envのAPI key保持をPhase 1で再確認できない場合は、Provider runtime checkを再評価トリガーへ送る。
- 【未確認】Aについて、Node24 `node:sqlite`がStability `1.2 - Release candidate`からstableへ移行し、同一構成のformat/lint/Vitest/common probe/client buildを通すまで、Aの不採用判定を解除しない。

## 10. Codex外部調査とClaude独立裏取り

### Codex側

- 【外部】公式一次資料は§2のURLを使用した。Node LTS/Current、Fastify/FastAPI、SQLite/FTS5、Zod、Vitest、Go、OpenAI API key/Responses streamingの機能境界をURLに紐づけ、性能値や長期保守期間を測定したとは主張していない。
- 【実測】A/B/Cのローカルprobeとquality commandは §5〜§6 の出力どおりである。
- 【実測】追加probeによりB/Cは採用候補として必要なquality・common・strict/healthまたはFTS5経路を確認し、Dはreject、AはNode24最小probeとraw/remediatedを分離したまま不採用とした。
- 【推測】今回の親判断はBを推奨1案、Cを対抗案、Aを今回のP0-02では不採用（追加検証が必要）、Dをrejectとする。これはユーザー承認前の設計推論であり、ADRの決定ではない。

### Claude独立裏取り（レビュー対応）

- 【レビュー】一致点: D reject、B/C元probeのquality/cleanup/secret衛生、CI parity pending、ADR前に自動確定しないことを確認した。A/B/C各追加probeでFTS5の3文字`MATCH`/2文字制約も一致した。
- 【レビュー】不一致点: Claudeは初回報告のA rejectを未評価と判断し、B>C順位を根拠不足と判断した。またB healthがTestClientだけで、strict coercionとfield pathの実測が揃っていない点を指摘した。
- 【レビュー】二周目Claudeの判断: B strict/health、C/A/B FTS5、raw/remediated分離、Claude助言と親判断の分離は対応済み。残存blockingはAの単一構成PASS断定、Node24 `node:sqlite`のstable条件、再現性、Provider/Migrationだった。
- 【実測】今回の修正では、Aを不採用へ戻し、Bのstrict field pathと実socket healthを推奨根拠へ固定し、Cを対抗案として維持し、A/B/CのFTS5結果を比較表へ残し、Provider/Migrationの承認射程とcanonical replay appendixを追加した。
- 【レビュー】Claudeの助言は提案物であり、今回のB推奨/C対抗/A不採用/D rejectは親判断である。Claudeの助言を決定扱いしない。
- 【リポジトリ一次】レビューは最大2周で閉じており、今回の修正後に三周目レビューを実施しない。
- 【未確認】Claudeが指摘したProvider実call、Provider usage/timeout、Migration実装、日本語検索実装、Docker、CI parityは、公式資料URLと承認射程を追記したが、P0-02aで実装・実行したとは扱わない。
- 【リポジトリ一次】Claudeへのレビュー対象は計画§7.4の選定基準、公式一次資料URL、Event Log単一権威、Structured Validation、SQLite transaction、Fake Provider、HTTP/SSE fallback、日本語検索、秘密非公開、単独保守である。

## 11. 1日スパイク後の未確認点

- 【実測】Bのhealthは旧TestClient結果に加え、追加uvicorn実socketで`127.0.0.1:7321` bind、HTTP200、shutdown、PID終了、再bind、stdout/stderr emptyを確認した。TestClientは補助結果であり、B推奨の採否health証拠は実socketである。
- 【実測】Aのraw typecheck/build failureは保持し、`skipLibCheck`と`rootDir`を明示したNode24 remediated typecheck/build、Node24 `node:sqlite` rollback/FTS5/minimal assertを別probeとして残した。同一最終構成のformat/lint/Vitest/common probe/client buildは未確認である。
- 【実測】A/B/CのFTS5 trigram create、3文字`MATCH`、2文字`MATCH`空、`LIKE`/application fallbackを確認した。検索実装は未実装である。B/Cの採用候補根拠とAの技術的証拠を比較表・appendixへ分離した。
- 【実測】API keyなしでOpenAI Python SDK `3.2.0`をTEMPへinstallし、import/version/`OpenAI`/`responses`/`responses.create`の存在だけを確認した。API callはしなかった。
- 【未確認】CI parity、remote run URL/status、Dockerfile/実container、実Provider call、Provider usage/timeout、versioned SQL migration実装、検索実装、正確なdeveloper-day作業時間は未確認またはPhase 0外である。
- 【推測】BのStarlette/httpx warningは旧TestClientの補助結果に限定され、実socket probeがPASSしたためB推奨案の採否を変えない。
- 【リポジトリ一次】実Provider・Dockerfile・ADR、migration/searchのproduction実装はP0-02aのNon-goalまたは承認B後/Phase 1以降の成果物であり、今回作成していない。

## 12. P0-02 STOP 2 — 推奨案と承認依頼

### 推奨1案（暫定）

- 【推測】B: Python 3.14系のsupported runtime / FastAPI / Pydantic strict / pytest / Python sqlite3 / Vite vanilla TypeScript / versioned SQL migration / HTTP POST + SSE + buffered fallbackを推奨1案とする。
- 【実測】Bはfresh lock install、compileall、ruff format/check、mypy、pytest、common probe 9 tests、Vite client build、Pydantic strict field path、Python sqlite3 rollback/FTS5、実socket `127.0.0.1` health/shutdown/rebindを確認した。
- 【推測】FastAPIのHTTP境界、Pydantic strict validation、Python標準`sqlite3`、Vite vanilla TypeScriptを一人保守の初期Stackとして停止2で承認対象にする。長期保守や実作業量を測定した結論ではない。
- 【推測】この推奨はユーザー承認前の停止2依頼であり、ADRの`Accepted`やP0-01b開始許可ではない。

### 対抗案

- 【推測】C: Go / `net/http` / `database/sql` + `modernc.org/sqlite` / strict decoder + validator / 標準testing / Vite vanilla TypeScriptを対抗案として維持する。
- 【実測】Cは全quality、common probe、non-cached test、FTS5 trigram、3文字`MATCH`、2文字`MATCH`空、`LIKE` fallback、rollbackがPASSした。
- 【推測】single binaryと明示的な並行性は候補理由だが、validation/provider glueの長期保守や実作業量を1日probeから確定しない。
- 【実測】AのNode24 `node:sqlite` FTS5/rollback/minimal assertも比較表へ残す。ただしAは同一最終構成の統合quality未確認かつRelease candidateのため、対抗案として承認を求めない。

### 不採用理由

- 【実測】D: build、format、lint、typecheck、test、health、CI parityの実行可能なStackがなく、P0-01b Gateを提供しない。
- 【実測】Aのraw Node26 FAIL（`TransferListItem` / `rootDir`）は保持するが、不採用理由の唯一の理由ではない。
- 【未確認】Aは同一Node24 `node:sqlite`最終構成でformat/lint/Vitest/common probe/client buildを通した記録がなく、raw `better-sqlite3` qualityを合成できない。
- 【外部】Node24 `node:sqlite`はStability `1.2 - Release candidate`であり、承認済み計画のstable built-in条件を満たさない。
- 【推測】Aは今回のP0-02では不採用（追加検証が必要）。Dはreject。A/Dの選択保留のままP0-01bまたはPhase 1へ進めない。

### 停止2で承認を求めるStack構成要素

| 構成要素 | 停止2で承認を求める境界 | 承認後/Phase 1以降へ回す範囲 |
|---|---|---|
| Server runtime/language | 【推測】Python 3.14系のsupported runtime + FastAPI。評価実機はPython `3.14.3`、FastAPI `0.141.1`。 | 【リポジトリ一次】server実装、P0-01b quality baseline、runtime pin/lockのRepository配置は承認後。 |
| HTTP | 【推測】FastAPIのHTTP endpoint境界。turn inputはHTTP POST、healthはloopback HTTP GET。 | 【リポジトリ一次】endpoint、request/response contract、Browser接続は承認後/Phase 1。 |
| Client | 【推測】Vite + vanilla TypeScript。 | 【リポジトリ一次】Browser UI、client/server contract共有、client buildのRepository配置は承認後/Phase 1。 |
| Database/driver | 【推測】SQLite + Python標準`sqlite3`。BのSQLite `3.50.4` rollback/FTS5と、A/CのFTS5比較結果を技術根拠として残す。 | 【リポジトリ一次】database schema、connection lifetime、production driver設定は承認後。 |
| transaction/migration boundary | 【推測】`versioned SQL migration files`はschema evolutionの決定であり、Event append transactionとは別に扱う。Event appendのtransaction境界はP0-03/Phase 1契約へ送る。ORM/automatic migrationは採用しない。 | 【リポジトリ一次】migration file、Event append、rollback/error atomicityのproduction実装はPhase 0外。 |
| Validation | 【推測】Pydantic strict model（`ConfigDict(strict=True, extra="forbid")`）でSemantic Resultを先に検証し、Narrative自由文を状態へparseしない。 | 【リポジトリ一次】production contract、Event変換、visibility/evidence policyはP0-03/P0-07以降。 |
| first Provider | 【推測】first ProviderはOpenAI Responses API + official Python SDK。Structured Outputsの`json_schema`/`strict`、Responses API streaming、server-side SDK、API keyのbackend env保持を承認対象とする。<br>【外部】根拠URLはOpenAI Platform overview、Responses streaming reference、API key safety（§2）。<br>【実測】API keyなしで`openai 3.2.0`をTEMPへinstallし、import/version/`OpenAI`/`responses`/`responses.create`のpublic surfaceだけを確認した。 | 【未確認】API call、課金、実Providerのusage/timeout/runtime behaviorは未確認。API callをしない理由はAPIキーなしStop ConditionとP0-02 Non-goalであり、Phase 0ではFake/公式schemaで代替する。実provider runtime check、SDKのproduction配置、prompt、call policyはPhase 1 Entry Condition/再評価トリガーへ送る。 |
| Fake boundary | 【推測】P0-02で確認したFake Provider / recorded fixtureをtest-only boundaryとして維持する。production provider hierarchy/registryは作らない。 | 【リポジトリ一次】Fake contract、retry/timeout fixture、実Providerとの差分検証はP0-07/Phase 1以降。 |
| Transport | 【推測】HTTP POST + SSE + buffered fallback。Semantic Resultを検証してからNarrativeを公開し、stream非対応でもbuffered responseで正しさを保つ。 | 【リポジトリ一次】SSE endpoint、buffered fallback、awaiting_player再開、Browser UIはPhase 1。 |
| Japanese search route | 【推測】SQLite FTS5 trigramの公式経路。3文字以上は`MATCH`、2文字以下は`MATCH`不可のため`LIKE`/application-managed fallback。<br>【外部】SQLite FTS5公式資料: https://www.sqlite.org/fts5.html。<br>【実測】A/B/CでFTS5 create、3文字`MATCH`、2文字`MATCH`空、fallbackを確認。 | 【リポジトリ一次】検索実装、性能比較、形態素解析、production routeはPhase 0外/Phase 3以降。 |
| Docker path | 【推測】Python runtime + locked install + one SQLite volume。 | 【未確認】Dockerfile、Docker実行、actionlint、act、remote CIは未確認でpending。Docker/actionlint/act/remote CIをPhase 0で実装しない。 |

- 【推測】停止2で承認を求める範囲は、上表のB Stack境界、OpenAI first Provider、versioned SQL migration filesとEvent append transactionを分離する方針、Japanese search route、Docker pathである。
- 【リポジトリ一次】承認B後にADRを作成し、承認発言・採用Stack・不採用理由・再評価トリガーを記録する。承認前にADR、P0-01b/Phase 1のStack依存実装へ進まない。

### 承認前の未確認点

- 【未確認】CI parity、remote run URL/status、Docker/実container、OpenAI API call、実Providerのusage/timeout/runtime behavior、versioned SQL migration実装、Event append transaction実装、検索実装、正確なdeveloper-day作業時間。
- 【実測】API keyなしFake/recorded probeとOpenAI SDK public surface probeは、実Providerのstructured output/usage/timeoutや課金を証明しない。
- 【未確認】Aの同一Node24 `node:sqlite`最終構成のformat/lint/Vitest/common probe/client build、Node24 `node:sqlite`のstable化は未確認であり、Aの不採用判定を維持する。

### ユーザーへの承認依頼

- 【推測】Bを推奨1案、Cを対抗案、Aを今回のP0-02では不採用（追加検証が必要）、Dをrejectとして、上表のStack境界、OpenAI first Provider、migration boundary、Japanese search route、Docker pathの承認を求める。追加spikeが必要なら指示してほしい。
- 【リポジトリ一次】ユーザー承認BなしにADR、P0-01bのStack依存実装、Phase 1を開始しない。Dを保留のままPhase 1へ進めない。
- 【実測】本報告作成時点でcommitはしていない。次のコミット境界は計画 §7.6 の `docs: 技術スタック候補の比較結果を記録する` だが、コミット操作は親／オーケストレーターの指示範囲で行う。

## 13. 最終スコープ・行末確認

- 【実測】変更対象は `docs/status/p0-02-technology-stack-evaluation.md` のみである。
- 【実測】probe削除後、Repository内の`node_modules`、`.venv`、`go.mod`、OpenAI SDK展開先は存在しない。
- 【実測】対象は未追跡ファイルのため通常の`git diff --numstat` / `git diff --ignore-cr-at-eol --numstat`には表示されず、`git status --untracked-files=all`で対象pathを確認する。最終検証の実出力はこの作業の完了報告へ返す。
- 【実測】最終報告ファイルのUTF-8(BOMなし)/CR/LF検査、`git diff --check`、TEMP cleanup、repository secret-like pattern scanはこの作業の完了報告へ実出力を返す。
- 【リポジトリ一次】AGENTS.md / CLAUDE.md / `docs/agent-guide/` はハーネス管理対象であり、今回変更していない。

### 今回レビュー対応のスコープ

- 【リポジトリ一次】今回の許可されたRepository書き込みパスは `docs/status/p0-02-technology-stack-evaluation.md` のみであり、ADR、src、tests、package/config、planは変更しない。
- 【実測】既存raw・初回RED・過去のcleanup記録は削除せず、追加probe、assertion manifest、Claudeレビュー要約、Stack承認射程を追記した。commitとpushは実施しない。
