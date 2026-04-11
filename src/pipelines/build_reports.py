from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import STRATEGY_IDS, load_run_snapshot, project_root, relative_to_root


def score(snapshot) -> tuple[float, float, float]:
    metrics = snapshot.metrics
    return (
        float(metrics.get("sharpe", float("-inf"))),
        float(metrics.get("cagr", float("-inf"))),
        float(metrics.get("max_drawdown", float("-inf"))),
    )


def rank_snapshots(snapshots: list[Any]) -> list[Any]:
    return sorted(snapshots, key=score, reverse=True)


def write_strategy_ranking(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "strategy_ranking.csv"
    fieldnames = [
        "rank",
        "strategy_id",
        "strategy_name",
        "strategy_type",
        "status",
        "cagr",
        "max_drawdown",
        "sharpe",
        "win_rate",
        "num_trades",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, snapshot in enumerate(ranked, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "strategy_id": snapshot.strategy_id,
                    "strategy_name": snapshot.meta.get("strategy_name", snapshot.strategy_id),
                    "strategy_type": snapshot.meta.get("strategy_type", ""),
                    "status": snapshot.meta.get("status", ""),
                    "cagr": snapshot.metrics.get("cagr", ""),
                    "max_drawdown": snapshot.metrics.get("max_drawdown", ""),
                    "sharpe": snapshot.metrics.get("sharpe", ""),
                    "win_rate": snapshot.metrics.get("win_rate", ""),
                    "num_trades": snapshot.metrics.get("num_trades", ""),
                }
            )

    return output_path


def _summary_line(summary_text: str) -> str:
    if not summary_text:
        return "要約なし"
    for line in summary_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "要約なし"


def _display_strategy_type(value: str) -> str:
    mapping = {
        "benchmark": "ベンチマーク",
        "rule_based": "ルールベース",
        "ml_based": "機械学習",
    }
    return mapping.get(value, value)


def _display_status(value: str) -> str:
    mapping = {
        "placeholder": "プレースホルダー",
        "completed": "完了",
        "failed": "失敗",
    }
    return mapping.get(value, value)


def write_strategy_comparison(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "strategy_comparison.md"
    lines = [
        "# strategy_comparison.md",
        "",
        "## 全体比較",
        "",
        "| 順位 | 戦略ID | 種別 | 状態 | Sharpe | CAGR | 最大ドローダウン | 取引数 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]

    for index, snapshot in enumerate(ranked, start=1):
        lines.append(
            "| {rank} | {strategy} | {strategy_type} | {status} | {sharpe} | {cagr} | {max_drawdown} | {num_trades} |".format(
                rank=index,
                strategy=snapshot.strategy_id,
                strategy_type=_display_strategy_type(snapshot.meta.get("strategy_type", "")),
                status=_display_status(snapshot.meta.get("status", "")),
                sharpe=snapshot.metrics.get("sharpe", ""),
                cagr=snapshot.metrics.get("cagr", ""),
                max_drawdown=snapshot.metrics.get("max_drawdown", ""),
                num_trades=snapshot.metrics.get("num_trades", ""),
            )
        )

    lines.extend(["", "## 戦略別メモ", ""])
    for snapshot in ranked:
        lines.extend(
            [
                f"### {snapshot.strategy_id}",
                "",
                f"- 戦略名: {snapshot.meta.get('strategy_name', snapshot.strategy_id)}",
                f"- 種別: {_display_strategy_type(snapshot.meta.get('strategy_type', ''))}",
                f"- 状態: {_display_status(snapshot.meta.get('status', ''))}",
                f"- ベンチマーク: {'はい' if snapshot.meta.get('benchmark', False) else 'いいえ'}",
                f"- 要約: {_summary_line(snapshot.summary_text)}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_final_summary(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "final_summary.md"
    benchmark = next((item for item in ranked if item.meta.get("benchmark")), None)
    best_overall = ranked[0] if ranked else None
    best_rule = next((item for item in ranked if item.meta.get("strategy_type") == "rule_based"), None)
    best_ml = next((item for item in ranked if item.meta.get("strategy_type") == "ml_based"), None)

    lines = ["# final_summary.md", "", "## サマリー", ""]
    if best_overall:
        lines.append(
            f"- Sharpe 基準の総合首位: {best_overall.strategy_id} (Sharpe {best_overall.metrics.get('sharpe', '')}, CAGR {best_overall.metrics.get('cagr', '')})"
        )
    if best_rule:
        lines.append(
            f"- ルールベース首位: {best_rule.strategy_id} (Sharpe {best_rule.metrics.get('sharpe', '')})"
        )
    if best_ml:
        lines.append(
            f"- 機械学習系首位: {best_ml.strategy_id} (Sharpe {best_ml.metrics.get('sharpe', '')})"
        )
    if benchmark and best_overall:
        lines.append(
            f"- ベンチマーク参照: {benchmark.strategy_id} (Sharpe {benchmark.metrics.get('sharpe', '')}, CAGR {benchmark.metrics.get('cagr', '')})"
        )

    lines.extend(["", "## 注意点", ""])
    lines.append("- このレポートは `runs/*` の成果物から自動生成しており、Viewer が安定して比較できる形式を維持します。")
    lines.append("- 失敗結果やプレースホルダー結果も `runs/` に残し、比較履歴の再現性を保ちます。")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_manifests(root: Path, ranked: list[Any], report_paths: list[Path]) -> tuple[Path, Path]:
    generated_at = datetime.now(timezone.utc).isoformat()

    runs_manifest_path = root / "runs" / "manifest.json"
    runs_manifest = {
        "generated_at": generated_at,
        "strategies": [
            {
                "strategy_id": snapshot.strategy_id,
                "path": relative_to_root(snapshot.run_dir, root),
                "meta": snapshot.meta,
                "metrics": snapshot.metrics,
                "row_counts": snapshot.row_counts,
                "files": snapshot.files,
                "issues": snapshot.issues,
            }
            for snapshot in ranked
        ],
    }
    runs_manifest_path.write_text(
        json.dumps(runs_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reports_manifest_path = root / "reports" / "manifest.json"
    reports_manifest = {
        "generated_at": generated_at,
        "reports": [relative_to_root(path, root) for path in report_paths],
        "runs_manifest": relative_to_root(runs_manifest_path, root),
        "strategy_ids": list(STRATEGY_IDS),
    }
    reports_manifest_path.write_text(
        json.dumps(reports_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return runs_manifest_path, reports_manifest_path


def build_reports(root: Path) -> dict[str, Any]:
    snapshots = [load_run_snapshot(root, strategy_id) for strategy_id in STRATEGY_IDS]
    ranked = rank_snapshots(snapshots)

    ranking_path = write_strategy_ranking(root, ranked)
    comparison_path = write_strategy_comparison(root, ranked)
    final_summary_path = write_final_summary(root, ranked)
    runs_manifest_path, reports_manifest_path = write_manifests(
        root,
        ranked,
        [ranking_path, comparison_path, final_summary_path],
    )

    return {
        "ranking": ranking_path,
        "comparison": comparison_path,
        "final_summary": final_summary_path,
        "runs_manifest": runs_manifest_path,
        "reports_manifest": reports_manifest_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build comparable strategy reports from runs artifacts.")
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="Repository root. Defaults to the current project root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = build_reports(args.root.resolve())
    print(
        json.dumps(
            {key: str(value) for key, value in outputs.items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
