# local_backtest_guide.md

## 目的
- 手元環境で各戦略のバックテストを再実行する
- `runs/` と `reports/` を再生成する
- 設定変更後に出力契約と整合性を確認する

## 前提
- Python 3.11 系
- 作業ディレクトリは `kabusoft004`
- 価格データは SQLite DB を使う

## セットアップ
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 主な設定ファイル
- [config/backtest.yaml](C:/Data/working/株ソフト004/kabusoft004/config/backtest.yaml)
- [config/features.yaml](C:/Data/working/株ソフト004/kabusoft004/config/features.yaml)
- [config/walkforward.yaml](C:/Data/working/株ソフト004/kabusoft004/config/walkforward.yaml)

## `backtest.yaml` の主な設定
- `database_path`: SQLite DB のパス
- `allow_csv_primary_source`: CSV を主経路に使うか
- `allow_csv_fallback`: DB 欠損時に CSV フォールバックを許すか
- `initial_capital`: 初期資金
- `start_date` `end_date`: 単一区間モードの期間
- `train_start_date` `train_end_date`: split モードの学習期間
- `test_start_date` `test_end_date`: split モードのテスト期間
- `holding_days_tested`: 評価する保有日数
- `fee_bps`: 手数料
- `slippage_bps`: スリッページ
- `trade_lot_size`: 通常戦略の売買単位
- `benchmark_symbol`: benchmark 銘柄
- `benchmark_trade_lot_size`: benchmark の売買単位
- `universe_size`: 対象銘柄数
- `max_positions`: 同時保有数
- `top_signals_per_day`: 1日あたりの候補上限
- `min_history_days`: 最低履歴日数
- `max_position_value_pct`: 1銘柄あたりの最大投入率。総資産に対する比率で、全worker共通の集中制限として使う。
- `min_signal_price`: シグナル日の終値がこの値未満の銘柄を除外する。低位株依存を抑えるための共通制約。
- `min_signal_traded_value`: シグナル日の `終値 * 出来高` がこの値未満の銘柄を除外する。流動性が低すぎる銘柄を避けるための共通制約。

## `walkforward.yaml` の主な設定
- `train_days`: 各 fold の学習営業日数
- `test_days`: 各 fold のテスト営業日数
- `step_days`: fold を前進させる営業日数

## 推奨の使い分け
### 長期の頑健性を見るとき
```yaml
start_date: null
end_date: null
train_start_date: null
train_end_date: null
test_start_date: null
test_end_date: null
```

### 直近 split を研究するとき
```yaml
start_date: null
end_date: null
train_start_date: 2025-02-20
train_end_date: 2026-02-13
test_start_date: 2026-02-16
test_end_date: 2026-05-12
```

## 単一戦略を再実行する
例: `worker_15`
```powershell
python src/pipelines/run_single_strategy.py worker_15 --refresh-reports
```

主な出力:
- `runs/worker_15/equity.csv`
- `runs/worker_15/trades.csv`
- `runs/worker_15/candidates.csv`
- `runs/worker_15/metrics.json`
- `runs/worker_15/meta.json`
- `runs/worker_15/result_summary.md`

## 全戦略を再実行する
```powershell
python src/pipelines/run_all_strategies.py
```

全戦略の再学習は重い。通常は目的に応じて対象を絞る。

### レポートだけ再生成する
既存の `runs/` を使い、`reports/` だけ更新する。
```powershell
python src/pipelines/run_all_strategies.py --reports-only
```

### 既存成果物がある戦略を飛ばす
未生成の戦略だけ実行し、最後にレポートを再生成する。
```powershell
python src/pipelines/run_all_strategies.py --skip-existing
```

### 単一または複数戦略だけ実行する
```powershell
python src/pipelines/run_all_strategies.py --strategy worker_22
python src/pipelines/run_all_strategies.py --strategy worker_19,worker_22
```

### グループ指定で実行する
```powershell
python src/pipelines/run_all_strategies.py --group profit_target
python src/pipelines/run_all_strategies.py --group core
```

主なグループ:
- `profit_target`: `worker_19` から `worker_22`
- `core`: benchmark と主力候補寄りの戦略
- `rule`: ルールベース戦略
- `meta`: `worker_16` 以降の meta 系

### 重い戦略を除外する
```powershell
python src/pipelines/run_all_strategies.py --exclude worker_21,worker_22
```

## レポートの見方
- `reports/strategy_ranking.csv`: 全期間の成績比較
- `reports/strategy_comparison.md`: 全戦略の要約
- `reports/final_summary.md`: 主要結果のまとめ
- `reports/operational_selection.csv`: 長期成績と直近20日/60日の成績を併記した運用選定表
- `reports/operational_selection.md`: 実運用向けの選び方メモ付き一覧
- `reports/outlier_contribution.csv`: 各workerの利益が少数トレード・少数銘柄に依存していないかを見る診断表
- `reports/outlier_contribution.md`: 外れ値寄与診断のMarkdown版
- `reports/archive/<YYYYMMDD_HHMMSS>/`: レポート生成時点の主要判断資料のスナップショット。後日、その時点の主要戦略・統合候補・ランキングを確認するために使う。

## 検証コマンド
出力契約:
```powershell
python src/validation/check_output_contract.py
```

バックテスト整合性:
```powershell
python src/validation/check_backtest_sanity.py
```

未来参照チェック:
```powershell
python src/validation/check_lookahead.py
```

## 学習済みモデルの保存先
ML 戦略は `runs/<worker>/models/` に fold ごとのモデルを保存する。どの期間で学習したかは `runs/<worker>/meta.json` の `walkforward_folds` で確認できる。

## 候補銘柄の確認
各戦略の候補銘柄は `runs/<worker>/candidates.csv` に出力する。主な列は次のとおり。
- `date`
- `symbol`
- `score`
- `strategy_id`
- `planned_holding_days`
- `signal_rank`

## 市場区分フィルタ
`config/backtest.yaml` の `markets` で検証対象市場を指定できる。

```yaml
markets: null
```

`null` は従来どおり全市場を対象にする。プライムのみで検証する場合は次のように指定する。

```yaml
markets: ["プライム"]
```

複数市場を対象にする場合は次のように指定する。

```yaml
markets: ["プライム", "スタンダード"]
```

このフィルタは `ticker_master.market` を使うため、SQLite DB を使う実行で有効になる。

## 固定円幅利確
`worker_24` は `config/backtest.yaml` の `profit_target_yen` を使う。

```yaml
profit_target_yen: 50
```

これは「始値から何円上がったら利確するか」を表す。例えば100円上がったら売却する検証に変える場合は `100` にする。
