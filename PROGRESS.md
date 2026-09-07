# PROGRESS — NeontoF

## Done

- Local Gateway の Fake / Recorded 部分と残課題修正は `6e2ea12` までに着地。
- CLI 接続と subscription budget の候補契約は `8fbb0bf`。Real Provider と Public Context は未完了。
- 2026-09-08 基線: `.venv\Scripts\python.exe -m pytest tests/model_gateway tests/test_repository_contracts.py -q` は `60 passed in 12.14s`、exit 0。API key 環境変数を一時除去し finally で復元。

## In progress

- T-001 は blocked。CLI `0.153.3` の実在を確認したが、既存 Windows sandbox の実効規則は localhost の TCP 全ポートも遮断する。外部遮断と検証 receiver の到達性を両立する構成は未成立。
- T-002 は依存 blocked。専用ログイン・Spark 生成・アプリ実装は未開始。

## Next

- `blocked/T-001.md` の再開条件を満たす隔離環境を用意する。既存 OS 設定の変更が必要なら、その具体的な対象と復元手順を別途確定する。
- T-001 の証跡が合格した場合だけ T-002 の専用ログインと Spark 正常一回へ進む。

## Notes

- branch: `feature/phase-01-local-web-slice`。初期 HEAD: `8fbb0bf`。初期作業ツリーは clean。
- PATH の CLI は `0.153.4`。実証は TASKS に固定した `0.153.3` の絶対パスを使う。
- 2026-09-08 の承認は、401限定例外の実証評価、指定一時領域、offline検証、条件成立後のSpark正常一回、片付けまで。アプリ実装・既存計画書換えは範囲外。
- 実証資材・証跡・認証情報は公開 git に含めない。サブスク利用は承認済み。実請求0の断定はしない。
- 一時領域には `evidence/offline/network-preflight.json` だけを保持。構成確認の記録であり、通信実測・offline 合格証拠ではない。probe と認証領域は未作成。
- バックグラウンド runner の `Start-Process` は無人モード、通常モードとも自動承認レビューが `blocked by policy` で拒否。第三の起動方法は試さず、相談後にメインから構成確認を実施した。runner は起動していない。
