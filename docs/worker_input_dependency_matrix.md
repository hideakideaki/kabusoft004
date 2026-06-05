## worker_24
- `worker_24` は rule_based。個別銘柄の日足だけを使って候補順位を作り、翌営業日の高値/終値は売却判定のバックテスト結果としてのみ使う。
- benchmark、市場breadth、他workerの成績には依存しない。

# Worker Input Dependency Matrix

この文書は、各 worker が売買候補を作る際に何を見ているかを整理したものです。

分類は次の 4 つです。

- `銘柄単体のみ`: 個別銘柄の日足系列と、そこから作られる特徴量だけを使う
- `市場状態あり`: 個別銘柄に加えて、市場 breadth や市場中央値などの市場全体情報を使う
- `benchmark あり`: 個別銘柄に加えて、`^N225` など benchmark の変化を明示的に使う
- `meta 選択あり`: 個別銘柄そのものを直接判定する前に、他戦略の過去成績から採用戦略を切り替える

## 一覧

| worker | 種別 | 日経平均を直接見るか | 市場全体を見るか | 他戦略の成績を見るか | 補足 |
| --- | --- | --- | --- | --- | --- |
| `benchmark_buy_and_hold` | benchmark | はい | いいえ | いいえ | `^N225` を benchmark として単純保有 |
| `worker_01` | rule_based | いいえ | いいえ | いいえ | 銘柄単体の breakout / volume |
| `worker_02` | rule_based | いいえ | いいえ | いいえ | 銘柄単体の mean reversion / rebound |
| `worker_03` | rule_based | いいえ | いいえ | いいえ | 銘柄単体の volatility expansion |
| `worker_04` | ml_based | いいえ | いいえ | いいえ | 銘柄単体特徴量で Logistic Regression |
| `worker_05` | ml_based | いいえ | いいえ | いいえ | 銘柄単体特徴量で Gradient Boosting |
| `worker_06` | ml_based | いいえ | いいえ | いいえ | 銘柄単体特徴量で Random Forest |
| `worker_07` | ml_based | いいえ | いいえ | いいえ | 銘柄単体特徴量の event + ML ハイブリッド |
| `worker_08` | ml_based | いいえ | いいえ | いいえ | `worker_07` の低回転版 |
| `worker_09` | rule_based | いいえ | いいえ | いいえ | 銘柄単体の trend pullback |
| `worker_10` | ml_based | いいえ | いいえ | いいえ | 銘柄単体の event + pullback + ML |
| `worker_10b` | ml_based | いいえ | いいえ | いいえ | `worker_10` の defensive 版 |
| `worker_10c` | ml_based | いいえ | いいえ | いいえ | 銘柄間の特徴量距離で分散するが market 指標は見ない |
| `worker_10d` | ml_based | いいえ | いいえ | いいえ | 銘柄間の直近相関を使うが benchmark は見ない |
| `worker_10e` | ml_based | いいえ | いいえ | いいえ | `worker_10` 系の blend |
| `worker_10f` | ml_based | いいえ | いいえ | いいえ | `worker_10d` 系の exposure 制御版 |
| `worker_11` | rule_based | いいえ | いいえ | いいえ | 銘柄単体の low-vol trend continuation |
| `worker_12` | ml_based | いいえ | いいえ | いいえ | 銘柄単体特徴量の split-hybrid ML |
| `worker_13` | ml_based | いいえ | いいえ | いいえ | `worker_12` 系の consensus 強化版 |
| `worker_14` | ml_based | はい | いいえ | いいえ | `benchmark_ret_*` や `benchmark_drawdown_20` を使う |
| `worker_15` | ml_based | いいえ | はい | いいえ | `market_breadth_*` など市場状態を使う |
| `worker_15b` | ml_based | はい | はい | いいえ | 市場状態に加えて benchmark 相対強弱を使う |
| `worker_16` | ml_based | 間接的 | 間接的 | はい | 他戦略候補を合議する meta backtest |
| `worker_17` | ml_based | 間接的 | 間接的 | はい | 過去成績で主力戦略を切り替える regime switch |
| `worker_17b` | ml_based | 間接的 | 間接的 | はい | `worker_17` の adaptive 版 |
| `worker_17c` | ml_based | 間接的 | 間接的 | はい | train window と判定特徴量を広げた heuristic meta |
| `worker_17d` | ml_based | 間接的 | 間接的 | はい | fold 次成績を予測する supervised meta selector |
| `worker_17e` | ml_based | 間接的 | 間接的 | はい | 主力候補群を絞った supervised meta selector |
| `worker_18` | rule_based | はい | はい | いいえ | benchmark と市場 breadth が弱い局面での短期反発狙い |
| `worker_19` | ml_based | いいえ | いいえ | いいえ | N営業日後までにM%以上のリターンへ到達する銘柄を直接学習 |
| `worker_20` | ml_based | いいえ | いいえ | いいえ | `worker_19` の予測に保有延長と動的出口を追加 |
| `worker_21` | ml_based | いいえ | いいえ | いいえ | `worker_20` の継続条件を緩めた保有延長版 |
| `worker_22` | ml_based | いいえ | いいえ | いいえ | `worker_21` の trailing を 6% にした中間版 |

## 補足

### 1. 多くの worker は「銘柄単体のみ」

`worker_01` から `worker_13` までの多くは、基本的に次の共通特徴量だけを使います。

- `ret_1`
- `ret_5`
- `ret_20`
- `gap_open`
- `intraday_return`
- `range_pct`
- `volume_ratio_20`
- `volatility_20`
- `breakout_strength`
- `drawdown_20`
- `rebound_strength`

これらは [C:/Data/working/株ソフト004/kabusoft004/src/core/feature_engineering.py](C:/Data/working/株ソフト004/kabusoft004/src/core/feature_engineering.py) で、各銘柄の OHLCV から計算されています。

### 2. `worker_14` は benchmark を直接見る

`worker_14` は `benchmark_ret_5`, `benchmark_ret_20`, `benchmark_drawdown_20`, `benchmark_volatility_20` などを使います。つまり、日経平均の地合いを明示的に使う戦略です。

### 3. `worker_15` は benchmark ではなく市場全体を見る

`worker_15` は `market_breadth_20`, `market_breadth_5`, `market_median_ret_5`, `market_median_drawdown_20` を使います。これは指数そのものではなく、市場全体の広がりや中央値で地合いを見る設計です。

### 4. `worker_15b` は市場状態と benchmark の両方を見る

`worker_15b` は `worker_15` の市場状態特徴量に加えて、`benchmark_ret_*` や relative return を使います。したがって、benchmark 非依存ではありません。

### 5. `worker_16` 以降は meta 戦略

`worker_16` 以降は、銘柄の上がりそう/下がりそうを直接1本のモデルで判定するというより、

- どの構成戦略を採用するか
- 何本 blend するか
- cash にするか

を、構成戦略の過去成績や予測スコアから決めます。

このため、`worker_16` 以降は「銘柄単体のみ」とは言えません。

## 実務上の読み方

- benchmark 依存を避けたいなら、まず `worker_14` と `worker_15b` は除外して考える
- 市場全体の地合いを少しは見たいなら、`worker_15` は候補になる
- 相場局面で戦略を切り替えたいなら、`worker_16` 以降の meta 系を使う
- 銘柄単体の情報だけで完結したいなら、`worker_01` から `worker_13` と `worker_10` 系が中心になる
- profit target 型の予測を見たいなら、`worker_19` は N/M 条件を明示した比較対象になる
- profit target 到達後の保有延長を検証したいなら、`worker_20` を比較対象にする
- 早期終了を抑えて利益を伸ばす仮説を検証したいなら、`worker_21` を比較対象にする
- 収益伸長とドローダウンのバランスを見るなら、`worker_22` を比較対象にする
| `worker_23` | ml_based | 間接的 | 間接的 | はい | 統合候補の係数を walk-forward で学習する calibrated consensus |
| `worker_23b` | ml_based | 間接的 | 間接的 | はい | profit target 到達を目的変数にした calibrated consensus |
