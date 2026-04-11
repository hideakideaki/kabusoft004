# 日本株投資戦略研究プロジェクト

## 概要
このリポジトリは、日本株の日足データを用いた投資戦略研究を行うためのプロジェクトです。
複数の戦略を同一条件で実装・検証し、比較可能な形で成果物を残します。
結果確認用の Viewer を戦略実装と分離しています。

## 戦略構成
- benchmark_buy_and_hold
- worker_01
- worker_02
- worker_03
- worker_04
- worker_05
- worker_06

## まず読むべきファイル
- `AGENTS.md`
- `docs/acceptance_criteria.md`
- `docs/spec.md`
- `docs/experiment_rules.md`
- `docs/strategy_catalog.md`
- `docs/viewer_spec.md`

## Codex での使い方
### 戦略側
- `prompts/kickoff_parent_prompt.md`

### Viewer 側
- `prompts/viewer_builder.md`

### skills
- `skills/lookahead-bias-check`
- `skills/backtest-sanity-check`
- `skills/walkforward-eval`
- `skills/result-summarizer`
