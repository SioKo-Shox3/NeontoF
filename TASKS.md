# TASKS — NeontoF

## 実証契約

Real Provider の入口を確認する。対象は Codex CLI `0.153.3`、`gpt-5.3-codex-spark`、reasoning `low`。実装側の adapter、test、dependency、migration、既存計画の変更は含まない。Public Context へ進まない。

- 実証用 CLI は `C:\Users\KINGkawamura\.codex\packages\standalone\releases\0.153.3-x86_64-pc-windows-msvc\bin\codex.exe`。`--version` の実出力は `codex-cli 0.153.3`。PATH の現行版は `0.153.4` なので実証に使わない。
- 一時 root は `C:\Users\KINGkawamura\AppData\Local\Temp\NeontoF-provider-proof\codex-0.153.3\`。実証資材はこの root の `offline-home/`、`live-home/`、`public-work/`、`config/spark-models.json`、`config/offline.toml`、`config/live.toml`、`config/response.schema.json`、`input/public-request.json`、`evidence/offline/`、`evidence/live/`、`probe_cli.py` だけに置く。
- メインが自分で実証資材を書く。Python 標準ライブラリだけを使い、production code と repository tests は変更しない。実証資材・ログ・認証情報を git に追加しない。
- 計画とこの作業一覧の差は、HTTP ストリーム成立前の 401 認証復旧を評価上の限定例外とすること。通常 response HTTP attempt=1、401 復旧は同一 stream 内で初回を含め最大3 attempt、成功生成は最大1、追加 stream=0。CLI job 数・HTTP attempt 数・モデル生成数を混同しない。ストリーム成立後の失敗、timeout、5xx、切断の再送は0。
- `request_max_retries=0`、`stream_max_retries=0`、`supports_websockets=false`、`features.unbounded_connection_retries=false` を適用する候補。built-in `openai` ID を上書きしない。custom ID / `name="OpenAI"` / `requires_openai_auth=true` / base_url 省略を live 候補とする。
- 起動時の `model_catalog_json` に Spark 一件の公開 metadata を指定し、`apply_patch_tool_type=null` と shell の無効化を候補として使う。全 Tool、AGENTS、skills、MCP、plugins、hooks、memory、環境情報の混入を実 payload で確認する。`--ignore-user-config` や `debug prompt-input` 単独で合格にしない。
- `CODEX_ROLLOUT_TRACE_ROOT` の診断 trace は送信意図の記録。source の送信経路、offline receiver の受信数、live の response ID / 完了結果を合わせる。trace 欠落は不合格。Authorization、cookie、実 auth 本文を収集・表示しない。診断 trace のその他の payload に認証情報が出ないことを source で確認してから利用する。
- offline は人工認証だけを使用。localhost 以外への通信を遮断する手段を先に成立させ、成立しなければ offline CLI も起動しない。HTTP proxy の設定だけを OS レベルの遮断と偽らない。live と別の CODEX_HOME を使用し、実 credential を offline へ渡さない。
- live は公式 CLI ログインだけを使用。既存 `auth.json` の読取り・コピー・抽出は禁止。ログインの対話が必要なら起動と安全な案内まで進め、未ログインを完了扱いにしない。
- 通常 API key は子環境から除去する。live 前に公式 login status / model list / rateLimits・credit metadata と公式資料で、ChatGPT 認証、Spark 利用枠内、有料 credit / 有料 fallback を避けられる条件を確認する。不明なら live を呼ばない。trace や API key 未使用だけから実請求0を断定しない。追加購入や有料設定変更は禁止。
- 共通設定は version/model/catalog/prompt/Tool隔離/retry/timeout。offline と live の相違は home、認証、生成先、認証更新先、metadata 経路、証跡 directory として明示する。offline 合格を live の保証にしない。
- live 生成先は `https://chatgpt.com/backend-api/codex/responses`、認証更新先は `https://auth.openai.com/oauth/token`。公式ログインの通信は認証通信として別扱い。入力は秘密を含まない人工公開 TRPG 入力。live 生成は全実証を通して1回だけ、timeout は60秒。呼出し直前にローカル receipt を永続化し、失敗・再起動・verify 再実行でも live を再呼出ししない。
- 同一手法の失敗2回で停止して非メイン AI に相談する。独立 evaluator は Claude opus、先頭行 PASS / NEEDS_WORK、最大2周。同じ差分の2周目は対応箇所だけ。実行不能・不明な保証は blocked に記録し、成功としない。
- 公式 source は `https://github.com/openai/codex/tree/rust-v0.153.3`。関係箇所: `codex-rs/core/src/client.rs` の stream_responses_api、`codex-rs/login/src/auth/manager.rs` の UnauthorizedRecovery、`codex-rs/core/src/tools/spec_plan.rs` の add_core_utility_tools、`codex-rs/rollout-trace/src/inference.rs` と `thread.rs`。大きなファイルの全読を避ける。
- repository への記録は TASKS / PROGRESS / LESSONS / NEXT_FINDINGS / STEER、必要時の `blocked/T-*.md`、訂正に対応する教訓1件に限定する。実装・上位仕様・既存2計画・ハーネスを変更しない。日本語、UTF-8 BOMなし、LF。明示列挙で stage し、日本語で commit、pushしない。

## T-001: Codex CLI の offline 入力隔離と再送境界を実証する
- status: blocked
- blocker: 既存 Windows sandbox の実効設定では localhost receiver の TCP 全ポートも遮断される。承認範囲内で外部遮断と receiver 到達性を両立する設定を確立できていない。構成確認の証拠と再開条件は `blocked/T-001.md`。
- done-when: 承認済み一時 root 内に標準ライブラリの probe と公開設定があり、外部通信の遮断根拠、最終 tools=[]、非公開入力混入なし、正常/401/timeout/5xx/切断の最小ケースの source と受信数と trace の対応を evidence/offline に記録する。verify-offline が保存済みの証拠を開いて検証し exit 0。再現できない必須分岐は合格でなく blocked とする。
- verify: `& .\.venv\Scripts\python.exe C:\Users\KINGkawamura\AppData\Local\Temp\NeontoF-provider-proof\codex-0.153.3\probe_cli.py verify-offline`
- paths: TASKS.md, PROGRESS.md, LESSONS.md, NEXT_FINDINGS.md, STEER.md, blocked/T-001.md, .harness/runs/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/offline-home/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/public-work/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/config/spark-models.json, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/config/offline.toml, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/config/response.schema.json, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/input/public-request.json, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/evidence/offline/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/probe_cli.py
- notes: live 接続・実 credential 読取り・Spark生成は禁止。可能な分岐調査と必要資材は自分で作る。新しい worktree、OS Firewall の恒久変更、資格情報の転用、CLIのforkは範囲外。権限不足や隔離方式の未成立は証拠を記録して停止する。verify は保存済み証拠の検査だけで実験を再実行しない。probe を作る前にブロックした場合は不存在の verify を実行せず、その理由を blocked に記録する。

## T-002: 専用ログインと Spark 正常呼出し一回の入口を確認する
- status: blocked
- blocker: T-001 の完了条件が未成立。ログイン・生成は開始していない。`blocked/T-002.md`。
- done-when: T-001がdoneで、公式ログイン・利用枠・credit条件を確認でき、live receiptにより一回限りの呼出しを実施し、実 payload の tools=[]・公開入力のみ・追加streamなし・正常生成1回を evidence/live の証拠で検証できる。verify-live が再生成せず保存済み証拠を検査して exit 0。一時資材と認証領域の保持/片付け結果を明示する。
- verify: `& .\.venv\Scripts\python.exe C:\Users\KINGkawamura\AppData\Local\Temp\NeontoF-provider-proof\codex-0.153.3\probe_cli.py verify-live`
- paths: TASKS.md, PROGRESS.md, LESSONS.md, NEXT_FINDINGS.md, STEER.md, blocked/T-002.md, .harness/runs/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/live-home/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/public-work/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/config/live.toml, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/evidence/live/**, C:/Users/KINGkawamura/AppData/Local/Temp/NeontoF-provider-proof/codex-0.153.3/probe_cli.py
- notes: T-001未完なら依存ブロックを記録し、ログインもlive呼出しも開始しない。対話的ログインや利用枠条件が未成立ならblockedへ理由と必要なユーザー操作だけを記録する。実装コード・test・migrationは作らない。不要資材の削除は実在する解決済み絶対pathが承認root内であることを確認してから行い、実行結果を記録する。認証領域はこの実証以外へ転用しない。通常verifyは保存済み証拠を確認するだけでモデルを再呼出ししない。
