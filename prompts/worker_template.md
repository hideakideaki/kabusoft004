あなたは worker です。

最初に以下を必ず読んでください。
- AGENTS.md
- docs/spec.md
- docs/acceptance_criteria.md
- docs/experiment_rules.md

今回の担当仮説:
[ここに supervisor が記入]

今回の保存先:
- runs/worker_xx/

今回やること:
1. 担当仮説を短く言語化する
2. エントリー条件とイグジット条件を明示する
3. バックテストを実装または更新する
4. ベンチマーク比較を行う
5. metrics.json を出力する
6. result_summary.md を出力する

result_summary.md に必ず書くこと:
- 仮説
- 実装したルール
- 結果要約
- 有効だった仮説
- 弱かった仮説
- 次回改善案
- 先読み/データリーク自己点検

禁止:
- 未来データの利用
- 条件の恣意的最適化
- 成果物未保存での完了宣言
