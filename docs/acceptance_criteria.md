# acceptance_criteria.md

## 戦略側
- 17 系列すべてに結果ディレクトリがある
- 各戦略に `equity.csv`, `trades.csv`, `metrics.json`, `meta.json`, `result_summary.md` がある
- benchmark 比較がある
- reports が生成されている

## Viewer 側
- `viewer/index.html` から起動できる
- 戦略一覧が見られる
- raw data が見られる
- 複数戦略比較ができる
- 欠損やパース失敗が画面で分かる
