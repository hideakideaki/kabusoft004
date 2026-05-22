# viewer_spec.md

## 目的
- `runs/` 配下の各戦略成果物を閲覧する
- `reports/` 配下の比較レポートを閲覧する
- `data/raw/` と `data/processed/` の中身を確認する
- benchmark / rule_based / ml_based の比較を分かりやすく表示する

## 各戦略ディレクトリの契約
- `equity.csv`
- `trades.csv`
- `candidates.csv`
- `metrics.json`
- `meta.json`
- `result_summary.md`

## reports/ の契約
- `strategy_ranking.csv`
- `strategy_comparison.md`
- `final_summary.md`
- `operational_selection.csv`
- `operational_selection.md`

## Viewer が最低限表示できるべき項目
- 戦略一覧
- equity の推移
- trades の一覧
- candidates の一覧
- metrics の一覧
- meta の一覧
- 欠損ファイルやパース失敗の検知
- reports/ の比較レポート一覧

## 主な対象ファイル
- `viewer/index.html`
- `viewer/style.css`
- `viewer/app.js`
- `viewer/data_loader.js`
- `viewer/charts.js`
- `viewer/tables.js`
- `viewer/filters.js`
- `viewer/state.js`
- `viewer/utils.js`
- `viewer/README.md`
