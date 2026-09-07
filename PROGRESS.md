# PROGRESS — NeontoF

## Done

- Local Gateway の Fake / Recorded 部分と残課題修正は `6e2ea12` までに着地。
- CLI 接続と subscription budget の候補契約は `8fbb0bf`。Real Provider と Public Context は未完了。
- 2026-09-08 基線: `.venv\Scripts\python.exe -m pytest tests/model_gateway tests/test_repository_contracts.py -q` は `60 passed in 12.14s`、exit 0。API key 環境変数を一時除去し finally で復元。

## In progress

- T-001: Codex CLI `0.153.3` の offline 実証準備。実証対象の旧版は standalone releases に保持されている。

## Next

- T-001 の証跡が合格した場合だけ T-002 の専用ログインと Spark 正常一回へ進む。

## Notes

- branch: `feature/phase-01-local-web-slice`。初期 HEAD: `8fbb0bf`。初期作業ツリーは clean。
- PATH の CLI は `0.153.4`。実証は TASKS に固定した `0.153.3` の絶対パスを使う。
- 2026-09-08 の承認は、401限定例外の実証評価、指定一時領域、offline検証、条件成立後のSpark正常一回、片付けまで。アプリ実装・既存計画書換えは範囲外。
- 実証資材・証跡・認証情報は公開 git に含めない。サブスク利用は承認済み。実請求0の断定はしない。
