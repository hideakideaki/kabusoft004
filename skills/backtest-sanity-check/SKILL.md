---
name: backtest-sanity-check
description: バックテスト結果と出力ファイルの基本整合性を確認する skill
---

# 目的
見かけの成績ではなく、最低限のバックテスト整合性を確認する。

# チェック項目
1. equity.csv, trades.csv, metrics.json が揃っているか
2. trade 数と metrics の num_trades が矛盾していないか
3. 平均保有日数や勝率が trade 明細と大きく矛盾しないか
4. 取引が極端に少なくないか
5. 手数料・スリッページ前提が明記されているか

# 出力形式
- 合格 / 要修正
- 不整合の箇所
- 直す順番
