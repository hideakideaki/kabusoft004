from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import STRATEGY_IDS, project_root
from src.pipelines.build_reports import build_reports
from src.pipelines.run_single_strategy import execute_strategy
from src.validation.check_output_contract import validate_project


STRATEGY_GROUPS = {
    "all": tuple(STRATEGY_IDS),
    "benchmark": ("benchmark_buy_and_hold",),
    "rule": tuple(
        strategy_id
        for strategy_id in STRATEGY_IDS
        if strategy_id
        in (
            "worker_01",
            "worker_02",
            "worker_03",
            "worker_09",
            "worker_11",
            "worker_18",
            "worker_24",
        )
    ),
    "core": (
        "benchmark_buy_and_hold",
        "worker_05",
        "worker_06",
        "worker_10d",
        "worker_17e",
        "worker_19",
        "worker_20",
        "worker_21",
        "worker_22",
        "worker_23",
        "worker_23b",
    ),
    "profit_target": (
        "worker_19",
        "worker_20",
        "worker_21",
        "worker_22",
    ),
    "consensus": (
        "worker_16",
        "worker_17e",
        "worker_23",
        "worker_23b",
    ),
    "meta": tuple(
        strategy_id
        for strategy_id in STRATEGY_IDS
        if strategy_id.startswith("worker_16")
        or strategy_id.startswith("worker_17")
    ),
    "normal": (
        "benchmark_buy_and_hold",
        "worker_04",
        "worker_06",
        "worker_08",
        "worker_10e",
        "worker_10f",
        "worker_16",
        "worker_17e",
        "worker_19",
        "worker_20",
        "worker_21",
        "worker_22",
        "worker_23b",
    ),
}


def _parse_strategy_csv(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    strategy_ids: list[str] = []
    for value in values:
        strategy_ids.extend(item.strip() for item in value.split(",") if item.strip())
    return strategy_ids


def _complete_run_exists(root: Path, strategy_id: str) -> bool:
    run_dir = root / "runs" / strategy_id
    required = (
        "equity.csv",
        "trades.csv",
        "candidates.csv",
        "metrics.json",
        "meta.json",
        "result_summary.md",
    )
    return run_dir.exists() and all((run_dir / name).exists() for name in required)


def _select_strategy_ids(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    for group in args.group:
        selected.extend(STRATEGY_GROUPS[group])
    selected.extend(_parse_strategy_csv(args.strategy))
    if not selected:
        selected = list(STRATEGY_IDS)

    excluded = set(_parse_strategy_csv(args.exclude))
    unknown = [
        strategy_id
        for strategy_id in selected + list(excluded)
        if strategy_id not in STRATEGY_IDS
    ]
    if unknown:
        raise SystemExit(f"unknown strategy_id: {', '.join(sorted(set(unknown)))}")

    unique_selected = []
    seen = set()
    for strategy_id in selected:
        if strategy_id in seen or strategy_id in excluded:
            continue
        unique_selected.append(strategy_id)
        seen.add(strategy_id)
    return unique_selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all strategy backtests and rebuild reports.")
    parser.add_argument("--root", type=Path, default=project_root())
    parser.add_argument(
        "--strategy",
        action="append",
        help="Strategy id or comma-separated ids to run. Can be repeated.",
    )
    parser.add_argument(
        "--group",
        action="append",
        choices=sorted(STRATEGY_GROUPS),
        default=[],
        help="Named strategy group to run. Defaults to all when neither --group nor --strategy is given.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        help="Strategy id or comma-separated ids to skip. Can be repeated.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip strategies whose required run files already exist.",
    )
    parser.add_argument(
        "--reports-only",
        action="store_true",
        help="Only rebuild reports and validate existing outputs.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip output contract validation after building reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    strategy_ids = _select_strategy_ids(args)
    results = []
    skipped = []

    if not args.reports_only:
        for strategy_id in strategy_ids:
            if args.skip_existing and _complete_run_exists(root, strategy_id):
                skipped.append(strategy_id)
                continue
            print(f"[run_all] running {strategy_id}", flush=True)
            results.append(execute_strategy(root, strategy_id, refresh_reports=False))

    build_outputs = build_reports(root)
    validation = {"ok": True, "issues": []}
    if not args.no_validate:
        validation = validate_project(root)
    print(
        json.dumps(
            {
                "requested_strategy_count": len(strategy_ids),
                "skipped": skipped,
                "results": results,
                "build_outputs": {key: str(value) for key, value in build_outputs.items()},
                "validation_ok": validation["ok"],
                "issue_count": len(validation["issues"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
