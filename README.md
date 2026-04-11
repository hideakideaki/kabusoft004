# Codex投資戦略研究テンプレート

Codex app / Codex cloud で、日本株の日足戦略を壁打ち・実装・査読・改善するための最小構成です。

## 目的
- AIに一発で最強戦略を作らせるのではなく、仮説生成→実装→検証→反省→次回改善のループを回す
- 同じ説明を毎回プロンプトへ重複記載しない
- Codexの並列スレッド / worktree / skills を活かして、研究プロトコルを安定運用する

## 使い方の流れ
1. `AGENTS.md` をリポジトリ直下に置く
2. `docs/` を読ませて研究ルールを固定する
3. `prompts/kickoff_parent_prompt.md` を親スレッドに貼る
4. 必要に応じて `prompts/worker_template.md` を複製して worker を増やす
5. worker の作業後、`skills/` のチェックを使って結果を確認する
6. `reports/final_summary.md` に改善サイクルの要約を残す

## 重複排除の方針
- 作業の一般原則は `AGENTS.md`
- 研究対象・データ・成果物は `docs/spec.md`
- 合格条件は `docs/acceptance_criteria.md`
- 実験運用ルールは `docs/experiment_rules.md`
- 役割ごとの短い依頼文は `prompts/`
- 毎回繰り返す検査は `skills/`

## 想定構成
- `prompts/supervisor.md`: worker へ指示を出す統括役
- `prompts/worker_template.md`: 戦略実装役
- `prompts/reviewer.md`: 査読役
- `prompts/summary_writer.md`: 横断サマリ作成役
- `skills/lookahead-bias-check`: 先読み混入チェック
- `skills/backtest-sanity-check`: バックテスト基本整合性チェック
- `skills/walkforward-eval`: walk-forward評価の確認
- `skills/result-summarizer`: 結果まとめ補助

## 注意
このテンプレートは研究支援用です。実運用前には必ず人手で、データ品質、約定可能性、制度信用/現物制約、手数料、税務、銘柄入替時の生存バイアスを確認してください。
