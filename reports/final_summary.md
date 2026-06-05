# final_summary.md

## サマリー

- Sharpe 首位: worker_08 (Sharpe 1.634021, CAGR 0.37046)
- ルールベース首位: worker_03 (Sharpe 1.609606)
- 機械学習首位: worker_08 (Sharpe 1.634021)
- ベンチマーク: benchmark_buy_and_hold (Sharpe 0.879012, CAGR 0.189754)

## 備考

- `strategy_ranking.csv` は全期間の成績比較、`operational_selection.*` は実運用向けの長期安定性と直近成績の併記に使う。
- split 設定を使った run と全期間 run を混在させると比較が崩れるため、運用判断前には同一設定で全戦略を再実行する。
