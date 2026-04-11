---
name: result-summarizer
description: 複数 worker の結果を比較し、次回へ引き継ぐ論点を抽出する skill
---

# 目的
複数の worker 結果を数値だけでなく仮説単位で整理する。

# 手順
1. 各 worker の metrics.json を確認する
2. 各 worker の result_summary.md を確認する
3. 有効仮説と弱い仮説を分ける
4. 次回統合候補を3点以内で提案する

# 出力形式
- 上位仮説
- 弱い仮説
- 次回統合候補
- 要再検証ポイント
