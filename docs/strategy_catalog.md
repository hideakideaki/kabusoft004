# strategy_catalog.md

## benchmark_buy_and_hold
比較基準。ロジックを複雑化しない。

## worker_01
高値更新と出来高急増のブレイクアウト。

## worker_02
急落後反発の逆張り。

## worker_03
低ボラ収縮後の拡大。

## worker_04
線形モデル系。例: Logistic Regression

## worker_05
勾配ブースティング系。例: LightGBM

## worker_06
木系アンサンブル。例: Random Forest

## worker_07
低ボラ拡大型の局面フィルタと、Logistic Regression / Random Forest の合成順位付けを組み合わせたハイブリッド。
