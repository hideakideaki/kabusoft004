# Live buy candidate generation

既存のバックテスト成果物を変更せず、DB 最新日の特徴量から翌日または翌々日の買い候補を出すための専用フォルダです。

## 目的

- `src/` の既存戦略ロジック、設定、データ読み込みを読み取り専用で再利用する
- DB に入っている最新日を `signal_date` として、その翌日または翌々日を `planned_entry_date` として出力する
- 学習は未来リターンが確定している過去データだけを使う
- 結果は `live_signals/outputs/` に CSV と JSON で保存する

## 基本実行

```powershell
python live_signals\generate_buy_candidates.py --strategy-id worker_10c --entry-offset-days 1
```

翌々日用:

```powershell
python live_signals\generate_buy_candidates.py --strategy-id worker_10c --entry-offset-days 2
```

上位件数を指定:

```powershell
python live_signals\generate_buy_candidates.py --strategy-id worker_10c --top-n 3
```

## 対応 worker

現時点では、実運用候補として検証上位だった ML 系を中心に対応しています。

- `worker_04`
- `worker_05`
- `worker_06`
- `worker_08`
- `worker_10`
- `worker_10b`
- `worker_10c`
- `worker_10d`
- `worker_10e`
- `worker_10f`

デフォルトは `worker_10c` です。

## 出力

CSV には主に以下が入ります。

- `rank`
- `strategy_id`
- `signal_date`
- `planned_entry_date`
- `holding_days`
- `symbol`
- `score`
- `close`
- `volume`
- `ret_1`
- `ret_5`
- `ret_20`
- `volatility_20`
- `volume_ratio_20`

JSON には、使用した DB 最新日、学習期間、候補数、出力 CSV パスなどのメタ情報を残します。

## 注意

- `planned_entry_date` は DB 最新日からの暦日オフセットです。休場日を含む場合は、実際には次に取引できる営業日の寄り付きで扱ってください。
- 売買判断の最終責任は利用者側です。このスクリプトは、これまで検証した worker のロジックを再現可能な形で実行するためのものです。
## Meta consensus

主力候補戦略と `worker_15b` を使った live 合議候補も生成できる。

```powershell
python live_signals\generate_meta_candidates.py --entry-offset-days 1 --top-n-per-strategy 10
```
