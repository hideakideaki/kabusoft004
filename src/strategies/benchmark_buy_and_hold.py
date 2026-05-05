from __future__ import annotations

from pathlib import Path

import pandas as pd


STRATEGY_ID = "benchmark_buy_and_hold"
STRATEGY_NAME = "benchmark_buy_and_hold"
STRATEGY_TYPE = "benchmark"


def run_benchmark(features: pd.DataFrame, config: dict):
    root = Path(config["_project_root"])
    initial_capital = float(config["initial_capital"])
    benchmark_symbol = str(config.get("benchmark_symbol", "1321"))
    trade_lot_size = int(config.get("benchmark_trade_lot_size", config.get("trade_lot_size", 1)))
    fee_rate = float(config.get("fee_bps", 0)) / 10000.0
    slippage_rate = float(config.get("slippage_bps", 0)) / 10000.0
    benchmark_path = root / "data" / "raw" / f"{benchmark_symbol}.csv"
    if not benchmark_path.exists():
        return pd.DataFrame(columns=["date", "equity"]), pd.DataFrame(), {
            "holding_days": None,
            "benchmark_symbol": benchmark_symbol,
            "trade_lot_size": trade_lot_size,
        }

    benchmark = pd.read_csv(benchmark_path)
    benchmark.columns = [column.lower() for column in benchmark.columns]
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    benchmark = benchmark.sort_values("date").reset_index(drop=True)

    start_date = config.get("start_date")
    end_date = config.get("end_date")
    if start_date:
        benchmark = benchmark[benchmark["date"] >= pd.to_datetime(start_date)]
    if end_date:
        benchmark = benchmark[benchmark["date"] <= pd.to_datetime(end_date)]
    if benchmark.empty:
        return pd.DataFrame(columns=["date", "equity"]), pd.DataFrame(), {
            "holding_days": None,
            "benchmark_symbol": benchmark_symbol,
            "trade_lot_size": trade_lot_size,
        }

    entry_row = benchmark.iloc[0]
    exit_row = benchmark.iloc[-1]
    entry_price = float(entry_row["open"]) * (1.0 + fee_rate + slippage_rate)
    lot_cost = entry_price * trade_lot_size
    lots = int(initial_capital // lot_cost)
    shares = lots * trade_lot_size
    if shares <= 0:
        return pd.DataFrame(columns=["date", "equity"]), pd.DataFrame(), {
            "holding_days": None,
            "benchmark_symbol": benchmark_symbol,
            "trade_lot_size": trade_lot_size,
        }

    remaining_cash = initial_capital - shares * entry_price
    exit_price = float(exit_row["close"]) * (1.0 - fee_rate - slippage_rate)

    equity_rows = [
        {
            "date": row.date.strftime("%Y-%m-%d"),
            "equity": round(remaining_cash + float(row.close) * shares, 6),
        }
        for row in benchmark.itertuples(index=False)
    ]

    trades_df = pd.DataFrame(
        [
            {
                "entry_date": entry_row["date"].strftime("%Y-%m-%d"),
                "exit_date": exit_row["date"].strftime("%Y-%m-%d"),
                "code": benchmark_symbol,
                "side": "long",
                "entry_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "return": round((exit_price / entry_price) - 1.0, 6),
                "holding_days": int((exit_row["date"] - entry_row["date"]).days),
                "shares": shares,
            }
        ],
        columns=[
            "entry_date",
            "exit_date",
            "code",
            "side",
            "entry_price",
            "exit_price",
            "return",
            "holding_days",
            "shares",
        ],
    )

    return pd.DataFrame(equity_rows), trades_df, {
        "holding_days": None,
        "benchmark_symbol": benchmark_symbol,
        "trade_lot_size": trade_lot_size,
    }
