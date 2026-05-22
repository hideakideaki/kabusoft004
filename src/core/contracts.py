from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STRATEGY_IDS = (
    "benchmark_buy_and_hold",
    "worker_01",
    "worker_02",
    "worker_03",
    "worker_04",
    "worker_05",
    "worker_06",
    "worker_07",
    "worker_08",
    "worker_09",
    "worker_10",
    "worker_10b",
    "worker_10c",
    "worker_10d",
    "worker_10e",
    "worker_10f",
    "worker_11",
    "worker_12",
    "worker_13",
    "worker_14",
    "worker_15",
    "worker_15b",
)

REQUIRED_RUN_FILES = (
    "equity.csv",
    "trades.csv",
    "candidates.csv",
    "metrics.json",
    "meta.json",
    "result_summary.md",
)

REQUIRED_REPORT_FILES = (
    "strategy_ranking.csv",
    "strategy_comparison.md",
    "final_summary.md",
    "operational_selection.csv",
    "operational_selection.md",
)

REQUIRED_EQUITY_COLUMNS = (
    "date",
    "equity",
)

REQUIRED_TRADES_COLUMNS = (
    "entry_date",
    "exit_date",
    "code",
    "side",
    "entry_price",
    "exit_price",
    "return",
    "planned_holding_days",
)

REQUIRED_CANDIDATE_COLUMNS = (
    "date",
    "symbol",
    "score",
    "strategy_id",
    "planned_holding_days",
)

REQUIRED_METRICS_KEYS = (
    "cagr",
    "max_drawdown",
    "sharpe",
    "win_rate",
    "num_trades",
)

REQUIRED_META_KEYS = (
    "strategy_id",
    "strategy_type",
    "strategy_name",
    "benchmark",
    "status",
)

ALLOWED_STRATEGY_TYPES = {
    "benchmark",
    "rule_based",
    "ml_based",
}


@dataclass
class RunSnapshot:
    strategy_id: str
    run_dir: Path
    files: dict[str, bool]
    meta: dict[str, Any]
    metrics: dict[str, Any]
    row_counts: dict[str, int]
    summary_text: str
    issues: list[str]

    @property
    def complete(self) -> bool:
        return not self.issues


def project_root(start: Path | None = None) -> Path:
    if start is None:
        start = Path(__file__).resolve()
    return start.parents[2]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def relative_to_root(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def has_required_columns(header: list[str], required: tuple[str, ...]) -> bool:
    if len(header) < len(required):
        return False
    return tuple(header[: len(required)]) == required


def load_run_snapshot(root: Path, strategy_id: str) -> RunSnapshot:
    run_dir = root / "runs" / strategy_id
    files = {name: (run_dir / name).exists() for name in REQUIRED_RUN_FILES}
    issues: list[str] = []

    if not run_dir.exists():
        return RunSnapshot(
            strategy_id=strategy_id,
            run_dir=run_dir,
            files=files,
            meta={},
            metrics={},
            row_counts={},
            summary_text="",
            issues=[f"missing run directory: {relative_to_root(run_dir, root)}"],
        )

    for name, exists in files.items():
        if not exists:
            issues.append(f"missing file: {relative_to_root(run_dir / name, root)}")

    meta: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    row_counts: dict[str, int] = {}
    summary_text = ""

    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        meta = read_json(meta_path)

    metrics_path = run_dir / "metrics.json"
    if metrics_path.exists():
        metrics = read_json(metrics_path)

    summary_path = run_dir / "result_summary.md"
    if summary_path.exists():
        summary_text = read_text(summary_path).strip()

    equity_path = run_dir / "equity.csv"
    if equity_path.exists():
        header = read_csv_header(equity_path)
        if not has_required_columns(header, REQUIRED_EQUITY_COLUMNS):
            issues.append(
                f"invalid equity.csv header for {strategy_id}: expected prefix {REQUIRED_EQUITY_COLUMNS}, got {tuple(header)}"
            )
        row_counts["equity"] = count_csv_rows(equity_path)

    trades_path = run_dir / "trades.csv"
    if trades_path.exists():
        header = read_csv_header(trades_path)
        if not has_required_columns(header, REQUIRED_TRADES_COLUMNS):
            issues.append(
                f"invalid trades.csv header for {strategy_id}: expected prefix {REQUIRED_TRADES_COLUMNS}, got {tuple(header)}"
            )
        row_counts["trades"] = count_csv_rows(trades_path)

    candidates_path = run_dir / "candidates.csv"
    if candidates_path.exists():
        header = read_csv_header(candidates_path)
        if not has_required_columns(header, REQUIRED_CANDIDATE_COLUMNS):
            issues.append(
                f"invalid candidates.csv header for {strategy_id}: expected prefix {REQUIRED_CANDIDATE_COLUMNS}, got {tuple(header)}"
            )
        row_counts["candidates"] = count_csv_rows(candidates_path)

    missing_metric_keys = [key for key in REQUIRED_METRICS_KEYS if key not in metrics]
    if missing_metric_keys:
        issues.append(f"metrics.json missing keys for {strategy_id}: {missing_metric_keys}")

    missing_meta_keys = [key for key in REQUIRED_META_KEYS if key not in meta]
    if missing_meta_keys:
        issues.append(f"meta.json missing keys for {strategy_id}: {missing_meta_keys}")

    if meta.get("strategy_id") not in ("", None, strategy_id):
        issues.append(
            f"meta.json strategy_id mismatch for {strategy_id}: {meta.get('strategy_id')}"
        )

    strategy_type = meta.get("strategy_type")
    if strategy_type and strategy_type not in ALLOWED_STRATEGY_TYPES:
        issues.append(
            f"meta.json strategy_type invalid for {strategy_id}: {strategy_type}"
        )

    return RunSnapshot(
        strategy_id=strategy_id,
        run_dir=run_dir,
        files=files,
        meta=meta,
        metrics=metrics,
        row_counts=row_counts,
        summary_text=summary_text,
        issues=issues,
    )
