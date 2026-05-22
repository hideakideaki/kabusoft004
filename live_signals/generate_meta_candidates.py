from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_signals.generate_buy_candidates import generate_buy_candidates  # noqa: E402


SUPPORT_STRATEGY_ID = "worker_15b"


def _read_main_selection(root: Path) -> list[dict[str, Any]]:
    path = root / "reports" / "main_strategy_selection.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows


def _pick_main_strategies(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if str(row.get("eligible_as_main", "")).lower() == "true"
        and str(row.get("is_fresh", "")).lower() == "true"
    ]
    eligible.sort(
        key=lambda row: (
            float(row.get("long_term_sharpe") or 0.0),
            float(row.get("recent_60d_sharpe") or 0.0),
        ),
        reverse=True,
    )
    return eligible[:limit]


def _main_strategy_weights(rows: list[dict[str, Any]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        strategy_id = str(row["strategy_id"])
        weights[strategy_id] = (
            float(row.get("long_term_sharpe") or 0.0)
            + max(float(row.get("recent_60d_sharpe") or 0.0), 0.0)
        )
    return weights


def generate_meta_candidates(
    root: Path,
    entry_offset_days: int,
    top_n_per_strategy: int,
    max_main_strategies: int,
) -> dict[str, Any]:
    main_selection_rows = _read_main_selection(root)
    main_rows = _pick_main_strategies(main_selection_rows, max_main_strategies)
    if not main_rows:
        raise RuntimeError("no eligible main strategies found in reports/main_strategy_selection.csv")

    main_ids = [row["strategy_id"] for row in main_rows]
    weights = _main_strategy_weights(main_rows)

    main_payloads = [
        generate_buy_candidates(root, strategy_id, entry_offset_days, top_n_per_strategy)
        for strategy_id in main_ids
    ]
    support_payload = generate_buy_candidates(root, SUPPORT_STRATEGY_ID, entry_offset_days, top_n_per_strategy)
    support_symbols = {item["symbol"] for item in support_payload["candidates"]}

    latest_signal_date = max(payload["signal_date"] for payload in main_payloads)
    planned_entry_date = max(payload["planned_entry_date"] for payload in main_payloads)

    symbol_rows: dict[str, dict[str, Any]] = {}
    for payload in main_payloads:
        strategy_id = str(payload["strategy_id"])
        strategy_weight = weights.get(strategy_id, 0.0)
        for item in payload["candidates"]:
            symbol = str(item["symbol"])
            bucket = symbol_rows.setdefault(
                symbol,
                {
                    "signal_date": latest_signal_date,
                    "planned_entry_date": planned_entry_date,
                    "symbol": symbol,
                    "support_count": 0,
                    "weighted_support": 0.0,
                    "avg_rank": 0.0,
                    "main_strategies": [],
                    "stable_confirmation": symbol in support_symbols,
                },
            )
            bucket["support_count"] += 1
            bucket["weighted_support"] += strategy_weight
            bucket["avg_rank"] += float(item["rank"])
            bucket["main_strategies"].append(strategy_id)
            bucket["stable_confirmation"] = bucket["stable_confirmation"] or (symbol in support_symbols)

    rows: list[dict[str, Any]] = []
    for bucket in symbol_rows.values():
        support_count = int(bucket["support_count"])
        avg_rank = bucket["avg_rank"] / support_count if support_count else 0.0
        stable_bonus = 0.75 if bucket["stable_confirmation"] else 0.0
        final_score = bucket["weighted_support"] + support_count * 0.5 + stable_bonus - avg_rank * 0.05
        rows.append(
            {
                "signal_date": bucket["signal_date"],
                "planned_entry_date": bucket["planned_entry_date"],
                "symbol": bucket["symbol"],
                "support_count": support_count,
                "weighted_support": round(bucket["weighted_support"], 6),
                "avg_rank": round(avg_rank, 4),
                "stable_confirmation": bucket["stable_confirmation"],
                "main_strategies": "|".join(bucket["main_strategies"]),
                "final_score": round(final_score, 6),
            }
        )

    rows.sort(
        key=lambda item: (
            int(item["support_count"]),
            float(item["final_score"]),
            -float(item["avg_rank"]),
        ),
        reverse=True,
    )

    output_dir = root / "live_signals" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"meta_consensus_{latest_signal_date.replace('-', '')}_entry_{planned_entry_date.replace('-', '')}"
    csv_path = output_dir / f"{stem}.csv"
    json_path = output_dir / f"{stem}.json"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "signal_date",
                "planned_entry_date",
                "symbol",
                "support_count",
                "weighted_support",
                "avg_rank",
                "stable_confirmation",
                "main_strategies",
                "final_score",
            ],
        )
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({"rank": index, **row})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signal_date": latest_signal_date,
        "planned_entry_date": planned_entry_date,
        "entry_offset_days": int(entry_offset_days),
        "main_strategy_ids": main_ids,
        "support_strategy_id": SUPPORT_STRATEGY_ID,
        "top_n_per_strategy": int(top_n_per_strategy),
        "candidate_count": len(rows),
        "csv_path": str(csv_path),
        "main_payloads": main_payloads,
        "support_payload": support_payload,
        "candidates": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["json_path"] = str(json_path)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate consensus live buy candidates from main strategies.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--entry-offset-days", type=int, choices=(1, 2), default=1)
    parser.add_argument("--top-n-per-strategy", type=int, default=10)
    parser.add_argument("--max-main-strategies", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate_meta_candidates(
        args.root.resolve(),
        args.entry_offset_days,
        args.top_n_per_strategy,
        args.max_main_strategies,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
