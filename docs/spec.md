# spec.md

## 1. 研究対象
- 対象市場: 日本株
- 時系列: 日足
- 主用途: 壁打ちから実装、バックテスト、比較、改善までを一連で回す

## 2. 研究の基本単位
1回の worker 作業では、原則として1つの明確な戦略仮説を扱う。

例:
- 出来高急増＋低ボラ収縮後のブレイクアウト
- 20日リターンと5日出来高偏差の複合モメンタム
- 過度下落後の短期リバウンド

## 3. データ要件
最低限必要な列:
- Date
- Open
- High
- Low
- Close
- Volume

任意:
- 調整後価格
- 銘柄コード
- 売買代金
- 指数データ
- セクター分類

## 4. 売買ルールの基本枠
詳細は各戦略で定義するが、以下は固定。
- シグナル計算に使う情報は n 日目まで
- エントリーは n+1 日以降
- イグジットはルールベースで明示する
- 最大保有日数を設ける
- 手数料とスリッページを反映する

## 5. 比較対象
最低1つ以上のベンチマークを置く。
候補:
- buy & hold
- 市場指数連動の簡易ベンチマーク
- ランダムまたは単純ルール戦略

## 6. 期待する成果物
worker ごとに以下を保存する。
- `runs/worker_xx/equity.csv`
- `runs/worker_xx/trades.csv`
- `runs/worker_xx/metrics.json`
- `runs/worker_xx/result_summary.md`

必要に応じて:
- `runs/worker_xx/feature_importance.csv`
- `runs/worker_xx/plots/`
- `runs/worker_xx/debug_log.txt`

## 7. metrics.json の最低項目
- CAGR
- total_return
- max_drawdown
- sharpe_like
- win_rate
- avg_gain
- avg_loss
- profit_factor
- num_trades
- avg_holding_days
- turnover_like
- benchmark_comparison

## 8. result_summary.md の最低項目
- 戦略名
- 仮説
- 実装したエントリー条件
- 実装したイグジット条件
- 結果要約
- 有効だった仮説
- 弱かった仮説
- 改善案
- 先読み/データリーク懸念の自己点検

## 9. supervisor の役割
- 複数 worker に仮説を割り振る
- 成果物の欠落を確認する
- reviewer に査読を依頼する
- summary_writer に横断要約を依頼する

## 10. reviewer の役割
- 仕様適合性確認
- 先読みやデータリークの疑いの確認
- 実装の一貫性確認
- 指標の見せかけ改善の疑いの指摘

## 11. summary_writer の役割
- 複数 worker の結果を横断比較する
- 残す仮説、捨てる仮説、次回統合する仮説を整理する
- `reports/final_summary.md` を作成または更新する
