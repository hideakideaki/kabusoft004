# AGENTS.md

## 1. このリポジトリの目的
このリポジトリは、日本株の日足データを用いた投資戦略研究を行うためのものである。
目的は、複数の戦略を同一条件で比較可能な形で実装・検証し、その結果を再利用可能な成果物として蓄積することである。

## 2. 基本原則
- 最初に関連文書を読む
- 憶測で仕様を緩めない
- 共通処理と個別処理を分離する
- 出力契約を安定させる
- 結果だけでなく過程も残す
- 未来情報を使わない
- 恣意的な評価をしない
- 比較可能な形式で成果物を残す

## 3. 最初に読むべきファイル
### 全担当共通
- `AGENTS.md`
- `docs/acceptance_criteria.md`

### 戦略側担当
- `docs/spec.md`
- `docs/experiment_rules.md`
- `docs/strategy_catalog.md`

### Viewer 側担当
- `docs/viewer_spec.md`

### 親スレッド / supervisor
- `prompts/kickoff_parent_prompt.md`

## 4. 責務分離
### 4.1 戦略側の責務
- データ読み込み
- 特徴量生成
- シグナル生成
- 学習
- バックテスト
- 指標算出
- 結果保存
- 比較レポート生成

### 4.2 Viewer 側の責務
- `runs/` の閲覧
- `reports/` の閲覧
- `data/raw/` `data/processed/` の閲覧
- 戦略比較表示
- 結果可視化
- 欠損や異常の表示

Viewer 側は、戦略ロジックやバックテスト本体を変更してはならない。

## 5. 出力契約
### 各戦略ディレクトリ
- `equity.csv`
- `trades.csv`
- `metrics.json`
- `meta.json`
- `result_summary.md`

### 全体成果物
- `reports/strategy_ranking.csv`
- `reports/strategy_comparison.md`
- `reports/final_summary.md`

## 6. 重複を避ける
- 全体原則は `AGENTS.md`
- 研究仕様は `docs/spec.md`
- 実験ルールは `docs/experiment_rules.md`
- 合格条件は `docs/acceptance_criteria.md`
- 初期戦略一覧は `docs/strategy_catalog.md`
- Viewer 契約は `docs/viewer_spec.md`
- 実行開始用指示は `prompts/`
- 再利用検査手順は `skills/`

## 7. skills
- `skills/lookahead-bias-check`
- `skills/backtest-sanity-check`
- `skills/walkforward-eval`
- `skills/result-summarizer`

## 8. 禁止事項
- 未来情報の使用
- データリーク
- 成績を良く見せるためだけの恣意的調整
- 同じ仮説の焼き直し
- 検証なしで完了扱いにすること
- Viewer が依存する出力仕様の無断変更
