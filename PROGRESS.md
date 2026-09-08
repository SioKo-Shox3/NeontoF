# PROGRESS — NeontoF

## Done

- Local Gateway の Fake / Recorded 部分と残課題修正は `6e2ea12` までに着地。
- CLI 接続と subscription budget の候補契約は `8fbb0bf`。Real Provider と Public Context は未完了。
- 2026-09-08 基線: `.venv\Scripts\python.exe -m pytest tests/model_gateway tests/test_repository_contracts.py -q` は `60 passed in 12.14s`、exit 0。API key 環境変数を一時除去し finally で復元。

## In progress

- T-001 完了。通信先固定の条件で6ケースの `verify-offline` が exit 0。OS 全通信遮断は保証に含めない。
- T-002: 専用ログインと当日の利用枠確認を開始。Spark 生成とアプリ実装は未実施。

## Next

- 専用ログインと利用枠が確認できた場合だけ Spark 正常一回へ進む。

## Notes

- branch: `feature/phase-01-local-web-slice`。初期 HEAD: `8fbb0bf`。初期作業ツリーは clean。
- PATH の CLI は `0.153.4`。実証は TASKS に固定した `0.153.3` の絶対パスを使う。
- 2026-09-08 の承認は、401限定例外の実証評価、指定一時領域、offline検証、条件成立後のSpark正常一回、片付けまで。アプリ実装・既存計画書換えは範囲外。
- 実証資材・証跡・認証情報は公開 git に含めない。サブスク利用は承認済み。実請求0の断定はしない。
- 一時領域には `evidence/offline/network-preflight.json` だけを保持。構成確認の記録であり、通信実測・offline 合格証拠ではない。probe と認証領域は未作成。
- バックグラウンド runner の `Start-Process` は無人モード、通常モードとも自動承認レビューが `blocked by policy` で拒否。第三の起動方法は試さず、相談後にメインから構成確認を実施した。runner は起動していない。
- 停止判断と記録の独立評価は PASS、blocking なし。実 model は CLI 出力の `claude-opus-5`。実証成功の判定ではない。用語と設定候補の説明を補足し、UTF-8 BOMなし/LF と diff の空白検査を確認した。
- 記録の途中状態は別操作の `8b61e19` と `d08cf43` に保存された。内容を保持し、残る補足を追加コミットする。
