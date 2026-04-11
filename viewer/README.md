# Viewer

`viewer/index.html` は `file://` 直開きでも動くようにしていますが、ブラウザ差異を避けるためローカル HTTP サーバー経由で開くのを推奨します。

## 使い方
1. リポジトリのルートで `python -m http.server 8080` を実行する
2. ブラウザで `http://localhost:8080/viewer/index.html` を開く
3. `リポジトリを選択` を押して、このリポジトリのルートフォルダを指定する
4. Directory Picker が使えない場合は `フォルダ入力で開く` から同じルートフォルダを選ぶ
5. 読み込み完了後、上部の summary で戦略数、raw files 数、issues 数を確認する
6. `進捗ログ` で、フォルダ選択後に何を読み込んでいるか、どこで失敗したかを確認する
7. `戦略フィルタ` で検索語、戦略種別、benchmark のみ表示を切り替える
8. `戦略一覧と比較対象選択` で見たい戦略をクリックして詳細を開き、比較したい戦略にチェックを付ける
9. `複数戦略比較` で equity curve と Sharpe 比較を確認する
10. `戦略詳細` で `meta.json`、`metrics.json` 相当の内容、`equity.csv`、`trades.csv`、`result_summary.md` を確認する
11. `raw data / processed data` でファイル名検索やカテゴリ絞り込みを使い、選択した CSV のプレビューを確認する
12. `欠損・パース失敗` に問題が出ていないか確認する

## 起動時の注意
- 推奨起動方法は `python -m http.server 8080` です
- `python -m server.http 8080` ではなく `python -m http.server 8080` を使ってください
- 選択するのは `runs/` や `data/` そのものではなく、リポジトリのルートフォルダです
- `進捗ログ` に ``runs/` が見つかりません` のような表示が出た場合は、`viewer/` ではなく一つ上のリポジトリルートを選び直してください
- `file://` 直開きでも使えるように実装していますが、ブラウザによっては Directory Picker 非対応です
- `data/processed/` が空でも Viewer は動作します
- `.gitkeep` のような補助ファイルは一覧から除外されます

## 表示内容
- 戦略一覧、Sharpe/CAGR/Max Drawdown などの指標比較
- strategy ごとの `meta.json`、`metrics.json`、`equity.csv`、`trades.csv`、`result_summary.md`
- `reports/strategy_comparison.md` と `reports/final_summary.md`
- `data/raw/`、`data/processed/`、`data/manifests/` のファイル一覧
- 欠損ファイルやパース失敗の一覧
