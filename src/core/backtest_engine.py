from __future__ import annotations

from collections import defaultdict

import pandas as pd


def run_backtest(signals: pd.DataFrame, prices: pd.DataFrame, config: dict):
    holding_days = int(config["holding_days"])
    initial_capital = float(config["initial_capital"])
    max_positions = int(config["max_positions"])
    top_signals_per_day = int(config.get("top_signals_per_day", max_positions))
    fee_rate = float(config.get("fee_bps", 0)) / 10000.0
    slippage_rate = float(config.get("slippage_bps", 0)) / 10000.0

    enriched = signals.merge(
        prices[
            [
                "date",
                "symbol",
                "entry_date",
                "next_open",
                f"exit_date_{holding_days}",
                f"exit_close_{holding_days}",
            ]
        ],
        on=["date", "symbol"],
        how="left",
    ).dropna(
        subset=["entry_date", "next_open", f"exit_date_{holding_days}", f"exit_close_{holding_days}"]
    )
    enriched = enriched.rename(
        columns={
            "date": "signal_date",
            "entry_date": "entry_date",
            "next_open": "entry_price_raw",
            f"exit_date_{holding_days}": "exit_date",
            f"exit_close_{holding_days}": "exit_price_raw",
        }
    )
    enriched["entry_date"] = pd.to_datetime(enriched["entry_date"])
    enriched["exit_date"] = pd.to_datetime(enriched["exit_date"])
    enriched = enriched.sort_values(["entry_date", "score"], ascending=[True, False])

    pending_entries: dict[pd.Timestamp, list[dict]] = defaultdict(list)
    for row in enriched.itertuples(index=False):
        pending_entries[row.entry_date].append(
            {
                "signal_date": row.signal_date,
                "symbol": row.symbol,
                "score": float(row.score),
                "entry_date": row.entry_date,
                "entry_price_raw": float(row.entry_price_raw),
                "exit_date": row.exit_date,
                "exit_price_raw": float(row.exit_price_raw),
            }
        )

    market = prices.sort_values(["date", "symbol"]).copy()
    close_lookup = {
        (row.date, row.symbol): float(row.close) for row in market[["date", "symbol", "close"]].itertuples(index=False)
    }
    calendar = sorted(market["date"].drop_duplicates())

    cash = initial_capital
    open_positions: dict[str, dict] = {}
    exit_schedule: dict[pd.Timestamp, list[str]] = defaultdict(list)
    last_close: dict[str, float] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []

    for current_date in calendar:
        for symbol in exit_schedule.pop(current_date, []):
            position = open_positions.pop(symbol, None)
            if position is None:
                continue
            exit_price = position["exit_price_raw"] * (1.0 - fee_rate - slippage_rate)
            proceeds = position["shares"] * exit_price
            cash += proceeds
            trades.append(
                {
                    "entry_date": position["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": current_date.strftime("%Y-%m-%d"),
                    "code": symbol,
                    "side": "long",
                    "entry_price": round(position["entry_exec_price"], 6),
                    "exit_price": round(exit_price, 6),
                    "return": round((exit_price / position["entry_exec_price"]) - 1.0, 6),
                    "holding_days": holding_days,
                }
            )

        todays_candidates = [
            candidate
            for candidate in pending_entries.get(current_date, [])
            if candidate["symbol"] not in open_positions
        ][:top_signals_per_day]
        available_slots = max_positions - len(open_positions)
        selected = todays_candidates[:available_slots]
        if selected:
            allocation = cash / len(selected)
            for candidate in selected:
                entry_exec_price = candidate["entry_price_raw"] * (1.0 + fee_rate + slippage_rate)
                shares = int(allocation // entry_exec_price)
                if shares <= 0:
                    continue
                cost = shares * entry_exec_price
                cash -= cost
                open_positions[candidate["symbol"]] = {
                    **candidate,
                    "shares": shares,
                    "entry_exec_price": entry_exec_price,
                }
                exit_schedule[candidate["exit_date"]].append(candidate["symbol"])

        portfolio_value = cash
        for symbol, position in open_positions.items():
            mark_price = close_lookup.get((current_date, symbol), last_close.get(symbol, position["entry_price_raw"]))
            last_close[symbol] = mark_price
            portfolio_value += position["shares"] * mark_price

        equity_rows.append(
            {"date": current_date.strftime("%Y-%m-%d"), "equity": round(portfolio_value, 6)}
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(
        trades,
        columns=[
            "entry_date",
            "exit_date",
            "code",
            "side",
            "entry_price",
            "exit_price",
            "return",
            "holding_days",
        ],
    )
    return equity_df, trades_df, {"holding_days": holding_days, "initial_capital": initial_capital}
