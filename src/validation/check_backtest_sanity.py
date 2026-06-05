from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import STRATEGY_IDS, load_run_snapshot, project_root


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def check_strategy(root: Path, strategy_id: str) -> list[str]:
    snapshot = load_run_snapshot(root, strategy_id)
    issues = list(snapshot.issues)
    selected_engine_meta = snapshot.meta.get("selected_engine_meta", {})
    allow_early_exit = any(
        selected_engine_meta.get(key) not in ("", None)
        for key in ("stop_loss_pct", "take_profit_pct")
    )

    equity_path = snapshot.run_dir / "equity.csv"
    if equity_path.exists():
        with equity_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            dates = []
            equities = []
            for row in reader:
                dates.append(_parse_date(row["date"]))
                equities.append(float(row["equity"]))
        if dates != sorted(dates):
            issues.append(f"{strategy_id}: equity dates are not sorted ascending")
        if len(set(dates)) != len(dates):
            issues.append(f"{strategy_id}: equity dates contain duplicates")
        if any(value <= 0 for value in equities):
            issues.append(f"{strategy_id}: equity contains non-positive values")

    trades_path = snapshot.run_dir / "trades.csv"
    if trades_path.exists():
        with trades_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            trade_count = 0
            for row in reader:
                trade_count += 1
                entry_date = _parse_date(row["entry_date"])
                exit_date = _parse_date(row["exit_date"])
                planned_holding_days_raw = row.get("planned_holding_days")
                if exit_date < entry_date:
                    issues.append(f"{strategy_id}: trade exits before it enters")
                if planned_holding_days_raw not in ("", None):
                    planned_holding_days = int(float(planned_holding_days_raw))
                    if planned_holding_days < 0:
                        issues.append(f"{strategy_id}: planned_holding_days is negative")
                    actual_trading_days_raw = row.get("actual_holding_trading_days")
                    if actual_trading_days_raw not in ("", None):
                        actual_holding_days = int(float(actual_trading_days_raw))
                    else:
                        actual_holding_days = (exit_date - entry_date).days
                    if not allow_early_exit and actual_holding_days < planned_holding_days:
                        issues.append(
                            f"{strategy_id}: planned_holding_days is longer than the actual holding period"
                        )
        metric_trades = snapshot.metrics.get("num_trades")
        if metric_trades not in ("", None) and int(metric_trades) != trade_count:
            issues.append(
                f"{strategy_id}: metrics.json num_trades {metric_trades} != trades.csv rows {trade_count}"
            )

    win_rate = snapshot.metrics.get("win_rate")
    if win_rate not in ("", None):
        numeric_win_rate = float(win_rate)
        if not 0.0 <= numeric_win_rate <= 1.0:
            issues.append(f"{strategy_id}: win_rate is outside [0, 1]")

    return issues


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run basic backtest sanity checks on all strategy outputs."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="Repository root. Defaults to the current project root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    issues = {strategy_id: check_strategy(root, strategy_id) for strategy_id in STRATEGY_IDS}
    failures = {key: value for key, value in issues.items() if value}

    print(
        json.dumps(
            {"ok": not failures, "issues": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
