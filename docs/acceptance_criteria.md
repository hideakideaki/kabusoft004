# acceptance_criteria.md

## 戦略側
- 21 戦略すべてに成果物ディレクトリがある
- 各戦略に `equity.csv`, `trades.csv`, `candidates.csv`, `metrics.json`, `meta.json`, `result_summary.md` がある
- benchmark 戦略がある
- `reports/` が更新されている
- `operational_selection.csv` と `operational_selection.md` が生成されている

## Viewer 側
- `viewer/index.html` から成果物を閲覧できる
- 戦略一覧を見られる
- raw data を見られる
- 複数戦略比較ができる
- 欠損やパース失敗が画面で分かる
