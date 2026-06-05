from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.data_loader import load_backtest_config, load_feature_config
from src.pipelines.run_single_strategy import _prepare_market
from src.strategies.worker_20_profit_target_hold_extension import (
    CONTINUATION_DRAWDOWN_PCT,
    CONTINUATION_MIN_RET_5,
    MAX_HOLDING_DAYS,
    TARGET_RETURN_THRESHOLD,
)


TRAILING_VARIANTS = (0.03, 0.04, 0.05)


def _trade_return(entry_exec_price: float, exit_raw_price: float, exit_cost_rate: float) -> float:
    exit_exec_price = exit_raw_price * (1.0 - exit_cost_rate)
    return (exit_exec_price / entry_exec_price) - 1.0


def _continuation_holds(close: float, ret_5: float, best_high: float) -> bool:
    if pd.isna(ret_5):
        return False
    near_high = close >= best_high * (1.0 - CONTINUATION_DRAWDOWN_PCT)
    momentum_ok = float(ret_5) >= CONTINUATION_MIN_RET_5
    return bool(near_high and momentum_ok)


def _simulate_exit(
    frame: pd.DataFrame,
    entry_idx: int,
    holding_days: int,
    trailing_drawdown_pct: float,
) -> dict[str, Any]:
    base_exit_idx = entry_idx + holding_days - 1
    if base_exit_idx >= len(frame):
        return {}

    max_exit_idx = min(entry_idx + MAX_HOLDING_DAYS - 1, len(frame) - 1)
    entry_raw_price = float(frame["open_values"][entry_idx])
    target_price = entry_raw_price * (1.0 + TARGET_RETURN_THRESHOLD)
    best_high = float(frame["high_values"][entry_idx])
    target_reached = False

    for idx in range(entry_idx, base_exit_idx + 1):
        best_high = max(best_high, float(frame["high_values"][idx]))
        if best_high >= target_price:
            target_reached = True

    if not target_reached:
        return {
            "exit_idx": base_exit_idx,
            "exit_date": frame["date_values"][base_exit_idx],
            "exit_price_raw": float(frame["close_values"][base_exit_idx]),
            "exit_reason": "base_time_exit",
        }

    for idx in range(base_exit_idx, max_exit_idx + 1):
        best_high = max(best_high, float(frame["high_values"][idx]))
        close = float(frame["close_values"][idx])
        ret_5 = frame["ret_5_values"][idx]

        if close <= best_high * (1.0 - trailing_drawdown_pct):
            return {
                "exit_idx": idx,
                "exit_date": frame["date_values"][idx],
                "exit_price_raw": close,
                "exit_reason": f"trailing_{int(trailing_drawdown_pct * 100)}pct",
            }

        if not _continuation_holds(close, ret_5, best_high):
            return {
                "exit_idx": idx,
                "exit_date": frame["date_values"][idx],
                "exit_price_raw": close,
                "exit_reason": "continuation_failed",
            }

    return {
        "exit_idx": max_exit_idx,
        "exit_date": frame["date_values"][max_exit_idx],
        "exit_price_raw": float(frame["close_values"][max_exit_idx]),
        "exit_reason": "max_holding_exit",
    }


def _prepare_symbol_frames(features: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for symbol, frame in features.sort_values(["symbol", "date"]).groupby("symbol"):
        prepared = frame.reset_index(drop=True).copy()
        prepared["date_norm"] = pd.to_datetime(prepared["date"]).dt.normalize()
        prepared.attrs["date_positions"] = {
            date: idx for idx, date in enumerate(prepared["date_norm"])
        }
        prepared["date_values"] = prepared["date"].to_numpy()
        prepared["open_values"] = prepared["open"].astype(float).to_numpy()
        prepared["high_values"] = prepared["high"].astype(float).to_numpy()
        prepared["close_values"] = prepared["close"].astype(float).to_numpy()
        prepared["ret_5_values"] = prepared["ret_5"].to_numpy()
        frames[str(symbol)] = prepared
    return frames


def _mean(series: pd.Series) -> float:
    return round(float(series.dropna().mean()), 6) if not series.dropna().empty else 0.0


def _rate(series: pd.Series) -> float:
    return round(float((series.dropna() > 0).mean()), 6) if not series.dropna().empty else 0.0


def _summarize(rows: pd.DataFrame, group_column: str) -> pd.DataFrame:
    summary_rows: list[dict[str, Any]] = []
    for key, group in rows.groupby(group_column, dropna=False):
        summary_rows.append(
            {
                group_column: key,
                "trades": int(len(group)),
                "avg_actual_return": _mean(group["actual_return"]),
                "avg_base_20_return": _mean(group["base_20_return"]),
                "avg_hold_40_return": _mean(group["hold_40_return"]),
                "avg_actual_minus_base_20": _mean(group["actual_minus_base_20"]),
                "avg_hold_40_minus_actual": _mean(group["hold_40_minus_actual"]),
                "avg_trailing_3pct_return": _mean(group["trailing_3pct_return"]),
                "avg_trailing_4pct_return": _mean(group["trailing_4pct_return"]),
                "avg_trailing_3pct_minus_actual": _mean(
                    group["trailing_3pct_return"] - group["actual_return"]
                ),
                "avg_trailing_4pct_minus_actual": _mean(
                    group["trailing_4pct_return"] - group["actual_return"]
                ),
                "actual_win_rate": _rate(group["actual_return"]),
                "base_20_win_rate": _rate(group["base_20_return"]),
                "hold_40_win_rate": _rate(group["hold_40_return"]),
            }
        )
    return pd.DataFrame(summary_rows).sort_values("trades", ascending=False)


def analyze(root: Path) -> dict[str, Path]:
    backtest_cfg = load_backtest_config(root)
    feature_cfg = load_feature_config(root)
    features = _prepare_market(root, backtest_cfg, feature_cfg)
    frames = _prepare_symbol_frames(features)

    trade_path = root / "runs" / "worker_20" / "trades.csv"
    trades = pd.read_csv(trade_path)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"]).dt.normalize()
    trades["exit_date"] = pd.to_datetime(trades["exit_date"]).dt.normalize()
    exit_cost_rate = (
        float(backtest_cfg.get("fee_bps", 0)) + float(backtest_cfg.get("slippage_bps", 0))
    ) / 10000.0

    rows: list[dict[str, Any]] = []
    for trade in trades.to_dict("records"):
        symbol = str(trade["code"])
        frame = frames.get(symbol)
        if frame is None:
            continue
        entry_idx = frame.attrs["date_positions"].get(pd.Timestamp(trade["entry_date"]))
        if entry_idx is None:
            continue

        holding_days = int(trade["planned_holding_days"])
        base_exit_idx = entry_idx + holding_days - 1
        hold_40_idx = min(entry_idx + MAX_HOLDING_DAYS - 1, len(frame) - 1)
        if base_exit_idx >= len(frame):
            continue

        entry_exec_price = float(trade["entry_price"])
        base_20_return = _trade_return(
            entry_exec_price,
            float(frame["close_values"][base_exit_idx]),
            exit_cost_rate,
        )
        hold_40_return = _trade_return(
            entry_exec_price,
            float(frame["close_values"][hold_40_idx]),
            exit_cost_rate,
        )

        variant_payload: dict[str, Any] = {}
        for trailing in TRAILING_VARIANTS:
            simulated = _simulate_exit(frame, entry_idx, holding_days, trailing)
            key = f"trailing_{int(trailing * 100)}pct"
            if simulated:
                variant_payload[f"{key}_return"] = _trade_return(
                    entry_exec_price,
                    float(simulated["exit_price_raw"]),
                    exit_cost_rate,
                )
                variant_payload[f"{key}_reason"] = simulated["exit_reason"]
            else:
                variant_payload[f"{key}_return"] = pd.NA
                variant_payload[f"{key}_reason"] = ""

        actual_return = float(trade["return"])
        actual_holding_days = int(trade["actual_holding_trading_days"])
        rows.append(
            {
                "entry_date": pd.Timestamp(trade["entry_date"]).strftime("%Y-%m-%d"),
                "exit_date": pd.Timestamp(trade["exit_date"]).strftime("%Y-%m-%d"),
                "symbol": symbol,
                "exit_reason": trade.get("exit_reason", ""),
                "planned_holding_days": holding_days,
                "actual_holding_trading_days": actual_holding_days,
                "was_extended": actual_holding_days > holding_days,
                "actual_return": actual_return,
                "base_20_return": base_20_return,
                "hold_40_return": hold_40_return,
                "actual_minus_base_20": actual_return - base_20_return,
                "hold_40_minus_actual": hold_40_return - actual_return,
                **variant_payload,
            }
        )

    detail = pd.DataFrame(rows)
    report_dir = root / "reports"
    detail_path = report_dir / "worker_20_exit_diagnostics.csv"
    summary_path = report_dir / "worker_20_exit_diagnostics_summary.csv"
    md_path = report_dir / "worker_20_exit_diagnostics.md"

    by_reason = _summarize(detail, "exit_reason")
    by_extended = _summarize(detail, "was_extended")
    summary = pd.concat(
        [
            by_reason.assign(section="by_exit_reason"),
            by_extended.assign(section="by_extension"),
        ],
        ignore_index=True,
    )

    detail.to_csv(detail_path, index=False, encoding="utf-8")
    summary.to_csv(summary_path, index=False, encoding="utf-8")
    md_path.write_text(_build_markdown(by_reason, by_extended), encoding="utf-8")
    return {
        "detail": detail_path,
        "summary": summary_path,
        "markdown": md_path,
    }


def _markdown_table(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["該当なし"]
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.to_dict("records"):
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def _build_markdown(by_reason: pd.DataFrame, by_extended: pd.DataFrame) -> str:
    lines = [
        "# worker_20_exit_diagnostics",
        "",
        "## 目的",
        "",
        "- `worker_20` の出口条件が利益を伸ばしたか、取引単位の反実仮想で確認する。",
        "- `base_20_return` は20営業日固定出口、`hold_40_return` は最大40営業日まで単純保有した場合の参考値。",
        "- `trailing_3pct/4pct` は現在の継続条件を維持し、trailing 幅だけ締めた場合の取引単位シミュレーション。",
        "",
        "## exit_reason 別",
        "",
        *_markdown_table(by_reason),
        "",
        "## 延長有無別",
        "",
        *_markdown_table(by_extended),
        "",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze worker_20 dynamic exit behavior.")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = analyze(args.root.resolve())
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
