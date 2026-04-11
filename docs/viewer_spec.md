# Viewer 仕様書

## 目的
- `runs/` 配下の戦略別結果の閲覧
- `reports/` 配下の比較結果の閲覧
- `data/raw/` および `data/processed/` 配下のデータ確認
- benchmark / ルールベース / 機械学習ベースの横比較
- equity / trades / metrics / meta / raw data の可視化

## 各戦略ディレクトリの必須ファイル
- `equity.csv`
- `trades.csv`
- `metrics.json`
- `result_summary.md`
- `meta.json`

## 実装先
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
