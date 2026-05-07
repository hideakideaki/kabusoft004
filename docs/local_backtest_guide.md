# ローカルバックテスト手順

## 目的
- 手元の環境で同じ条件のバックテストを再実行する
- `runs/` と `reports/` を再生成する
- 初期資金、バックテスト期間、保有日数などの共通設定を変更できるようにする

## 前提
- Python 3.11 以上を推奨
- 作業ディレクトリはリポジトリ直下 `kabusoft004`
- `data/raw/` 配下に株価 CSV が配置済み

## 初回セットアップ
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 共通設定
- バックテスト共通設定: [config/backtest.yaml](C:/Data/working/株ソフト004/kabusoft004/config/backtest.yaml)
- 特徴量設定: [config/features.yaml](C:/Data/working/株ソフト004/kabusoft004/config/features.yaml)
- walk-forward 設定: [config/walkforward.yaml](C:/Data/working/株ソフト004/kabusoft004/config/walkforward.yaml)

主要な設定項目:
- `database_path`: 価格DBのパス。既定値は `C:\Data\working\株価取得\data\prices.db`
- `allow_csv_primary_source`: DB が使えないときに CSV を主データ源として使うか。既定値は `false`
- `allow_csv_fallback`: DB に個別銘柄データが無いときに CSV フォールバックを許すか。既定値は `false`
- `initial_capital`: 初期資金
- `start_date`: バックテスト開始日。例: `2022-01-01`
- `end_date`: バックテスト終了日。例: `2024-12-31`
- `holding_days_tested`: 試験する保有日数
- `fee_bps`: 手数料
- `slippage_bps`: スリッページ
- `trade_lot_size`: 売買単位。日本株を通常通り扱うなら `100`
- `benchmark_symbol`: ベンチマークに使う銘柄コード。既定値は `^N225`
- `benchmark_trade_lot_size`: ベンチマーク銘柄の売買単位。指数を仮想保有するなら `1`
- `universe_size`: 読み込む流動性上位銘柄数
- `max_positions`: 同時保有上限

`start_date` と `end_date` を `null` にすると、データの全期間を使います。

## 単一戦略の実行
例: `worker_03` を再実行する

```powershell
python src/pipelines/run_single_strategy.py worker_03 --refresh-reports
```

実行後に更新される主な出力:
- `runs/worker_03/equity.csv`
- `runs/worker_03/trades.csv`
- `runs/worker_03/metrics.json`
- `runs/worker_03/meta.json`
- `runs/worker_03/result_summary.md`
- `reports/strategy_ranking.csv`
- `reports/strategy_comparison.md`
- `reports/final_summary.md`

## 全戦略の一括実行
```powershell
python src/pipelines/run_all_strategies.py
```

このコマンドは以下をまとめて行う:
- 7 戦略のバックテスト再実行
- `reports/` の再生成
- 出力契約チェック

## 検証コマンド
出力契約の確認:
```powershell
python src/validation/check_output_contract.py
```

バックテスト整合性の確認:
```powershell
python src/validation/check_backtest_sanity.py
```

先読みパターンの簡易確認:
```powershell
python src/validation/check_lookahead.py
```

## バックテスト期間を変更する場合
1. [config/backtest.yaml](C:/Data/working/株ソフト004/kabusoft004/config/backtest.yaml) の `start_date` と `end_date` を変更する
2. 例:
```yaml
start_date: 2022-01-01
end_date: 2024-12-31
```
3. `python src/pipelines/run_all_strategies.py` を再実行する

## 初期資金を変更する場合
1. [config/backtest.yaml](C:/Data/working/株ソフト004/kabusoft004/config/backtest.yaml) の `initial_capital` を変更する
2. 必要なら `max_positions` や `universe_size` も調整する
3. `python src/pipelines/run_all_strategies.py` を再実行する

## 学習済みモデルの保存先
ML 系戦略 `worker_04` `worker_05` `worker_06` は、walk-forward の各 fold ごとに学習済みモデルを保存します。

保存先:
- `runs/worker_04/models/holding_10/`
- `runs/worker_04/models/holding_20/`
- `runs/worker_05/models/holding_10/`
- `runs/worker_05/models/holding_20/`
- `runs/worker_06/models/holding_10/`
- `runs/worker_06/models/holding_20/`

ファイル名:
- `fold_01.pkl`
- `fold_02.pkl`
- ...

対応する学習期間とテスト期間は各 `runs/<worker>/meta.json` の `walkforward_folds` に保存されます。

## 補足
- 現在の実装では `holding_days_tested` にある営業日数をすべて試し、Sharpe が最も高い結果を各戦略の正式出力に採用する
- `meta.json` には採用された保有日数、候補ごとの成績、ML 系では fold ごとの学習期間と保存モデルパスを記録する
- Viewer は `runs/` と `reports/` を読む前提なので、出力ファイル名は変更しない
