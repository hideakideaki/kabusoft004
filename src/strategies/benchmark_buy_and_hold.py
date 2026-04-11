from __future__ import annotations

import pandas as pd


STRATEGY_ID = "benchmark_buy_and_hold"
STRATEGY_NAME = "benchmark_buy_and_hold"
STRATEGY_TYPE = "benchmark"


def run_benchmark(features: pd.DataFrame, config: dict):
    initial_capital = float(config["initial_capital"])
    benchmark_positions = int(config.get("benchmark_positions", 20))
    fee_rate = float(config.get("fee_bps", 0)) / 10000.0
    slippage_rate = float(config.get("slippage_bps", 0)) / 10000.0

    first_day = features.groupby("symbol")["date"].min().reset_index(name="first_date")
    start_date = first_day["first_date"].max()
    entry_rows = features[features["date"] == start_date].copy()
    entry_rows = entry_rows.sort_values("liquidity_score", ascending=False).head(benchmark_positions)

    last_dates = features.groupby("symbol")["date"].max().rename("exit_date")
    last_close = features.groupby("symbol")["close"].last().rename("exit_price_raw")
    exit_info = pd.concat([last_dates, last_close], axis=1).reset_index()
    benchmark = entry_rows.merge(exit_info, on="symbol", how="left")
    benchmark = benchmark.dropna(subset=["open", "exit_price_raw"])

    allocation = initial_capital / max(len(benchmark), 1)
    trades = []
    remaining_cash = initial_capital
    for row in benchmark.itertuples(index=False):
        entry_price = float(row.open) * (1.0 + fee_rate + slippage_rate)
        shares = int(allocation // entry_price)
        if shares <= 0:
            continue
        exit_price = float(row.exit_price_raw) * (1.0 - fee_rate - slippage_rate)
        remaining_cash -= shares * entry_price
        trades.append(
            {
                "symbol": row.symbol,
                "entry_date": row.date,
                "exit_date": row.exit_date,
                "shares": shares,
                "entry_price": entry_price,
                "exit_price": exit_price,
            }
        )

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return pd.DataFrame(columns=["date", "equity"]), pd.DataFrame(), {"holding_days": None}

    market = features[["date", "symbol", "close"]].copy()
    trade_lookup = {}
    for trade in trades_df.itertuples(index=False):
        trade_lookup[trade.symbol] = trade

    calendar = sorted(market["date"].drop_duplicates())
    equity_rows = []
    for current_date in calendar:
        equity = remaining_cash
        for symbol, trade in trade_lookup.items():
            if current_date < trade.entry_date or current_date > trade.exit_date:
                continue
            close_row = market[(market["date"] == current_date) & (market["symbol"] == symbol)]
            if close_row.empty:
                continue
            equity += float(close_row["close"].iloc[0]) * trade.shares
        equity_rows.append({"date": current_date.strftime("%Y-%m-%d"), "equity": round(equity, 6)})

    output_trades = []
    for trade in trades_df.itertuples(index=False):
        output_trades.append(
            {
                "entry_date": trade.entry_date.strftime("%Y-%m-%d"),
                "exit_date": trade.exit_date.strftime("%Y-%m-%d"),
                "code": trade.symbol,
                "side": "long",
                "entry_price": round(trade.entry_price, 6),
                "exit_price": round(trade.exit_price, 6),
                "return": round((trade.exit_price / trade.entry_price) - 1.0, 6),
                "holding_days": int((trade.exit_date - trade.entry_date).days),
            }
        )

    return pd.DataFrame(equity_rows), pd.DataFrame(output_trades), {"holding_days": None}
