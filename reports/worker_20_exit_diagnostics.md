# worker_20_exit_diagnostics

## 目的

- `worker_20` の出口条件が利益を伸ばしたか、取引単位の反実仮想で確認する。
- `base_20_return` は20営業日固定出口、`hold_40_return` は最大40営業日まで単純保有した場合の参考値。
- `trailing_3pct/4pct` は現在の継続条件を維持し、trailing 幅だけ締めた場合の取引単位シミュレーション。

## exit_reason 別

| exit_reason | trades | avg_actual_return | avg_base_20_return | avg_hold_40_return | avg_actual_minus_base_20 | avg_hold_40_minus_actual | avg_trailing_3pct_return | avg_trailing_4pct_return | avg_trailing_3pct_minus_actual | avg_trailing_4pct_minus_actual | actual_win_rate | base_20_win_rate | hold_40_win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trailing_exit | 475 | 0.051575 | 0.052318 | 0.104433 | -0.000743 | 0.052858 | 0.051231 | 0.051575 | -0.000344 | 0.0 | 0.543158 | 0.564211 | 0.570526 |
| continuation_failed | 129 | 0.117411 | 0.108597 | 0.147895 | 0.008815 | 0.030484 | 0.115106 | 0.117411 | -0.002306 | -0.0 | 0.914729 | 0.96124 | 0.837209 |
| base_time_exit | 119 | -0.107919 | -0.107919 | -0.081275 | -0.0 | 0.026643 | -0.107919 | -0.107919 | 0.0 | 0.0 | 0.042017 | 0.042017 | 0.260504 |
| max_holding_exit | 1 | 0.294133 | 0.058117 | 0.294133 | 0.236016 | -0.0 | 0.036661 | 0.294133 | -0.257472 | -0.0 | 1.0 | 1.0 | 1.0 |

## 延長有無別

| was_extended | trades | avg_actual_return | avg_base_20_return | avg_hold_40_return | avg_actual_minus_base_20 | avg_hold_40_minus_actual | avg_trailing_3pct_return | avg_trailing_4pct_return | avg_trailing_3pct_minus_actual | avg_trailing_4pct_minus_actual | actual_win_rate | base_20_win_rate | hold_40_win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| False | 562 | -0.002029 | -0.002029 | 0.03652 | -0.0 | 0.038548 | -0.002029 | -0.002029 | 0.0 | 0.0 | 0.423488 | 0.423488 | 0.483986 |
| True | 162 | 0.174296 | 0.167999 | 0.239397 | 0.006297 | 0.065101 | 0.169863 | 0.174296 | -0.004434 | -0.0 | 0.888889 | 0.987654 | 0.858025 |

