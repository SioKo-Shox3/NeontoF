# NeontoF Planning Package

このパッケージは、NeontoFの設計方針と実装順序を開発者または開発エージェントへ渡すための文書一式です。

## 読む順序

1. `docs/PRODUCT_PLAN.md`
2. `docs/IMPLEMENTATION_ROADMAP.md`
3. `docs/reviews/2026-08-18-product-plan-review.md`（判断の背景を確認するとき）

## 文書の役割

- `PRODUCT_PLAN.md`: NeontoFが目指すもの、Core原則、責務境界、非交渉要件
- `IMPLEMENTATION_ROADMAP.md`: Phaseの順序、Goal、Non-goal、成果物、受け入れGate、Codex向け開始指示
- `reviews/...`: Draft v0.1への外部レビュー原文

## 実装開始時

`IMPLEMENTATION_ROADMAP.md`の「Codexへ渡す最初の指示」を使用し、Phase 0の詳細Implementation Planを作成してから実装を開始します。

一度に全Phaseを実装せず、各PhaseのGateで人間のレビューと必要な通しプレイを行ってください。
