このリポジトリで投資戦略研究を進めてください。

最初に以下を必ず読んでください。
- AGENTS.md
- docs/spec.md
- docs/acceptance_criteria.md
- docs/experiment_rules.md

今回の目的:
- supervisor として全体計画を立てる
- worker を複数立ち上げる前提で、仮説の重複が少ない担当分けを行う
- 各 worker 用の作業指示を、prompts/worker_template.md の方針に沿って具体化する
- 実装後は reviewer に査読を依頼する
- 最後に summary_writer に全体要約を書かせる

厳守:
- 未来データ利用禁止
- ベンチマーク比較必須
- 手数料・スリッページ考慮
- 成果物は worker ごとに runs 配下へ分離保存
- 良い数値が出るまで恣意的に条件調整しない

進め方:
1. まず今回走らせる worker 案を3〜5本提案する
2. それぞれの仮説が重複していないかを自己点検する
3. 実装と検証の計画を示す
4. 実行後、reviewer と summary_writer へ引き継ぐ
