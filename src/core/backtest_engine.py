from __future__ import annotations

from collections import defaultdict

import pandas as pd


def _compute_actual_holding_trading_days(
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
    trading_index_map: dict[pd.Timestamp, int],
) -> int:
    entry_idx = trading_index_map.get(entry_date.normalize())
    exit_idx = trading_index_map.get(exit_date.normalize())
    if entry_idx is None or exit_idx is None or exit_idx < entry_idx:
        return 0
    return (exit_idx - entry_idx) + 1


def run_backtest(signals: pd.DataFrame, prices: pd.DataFrame, config: dict):
    holding_days = int(config["holding_days"])
    initial_capital = float(config["initial_capital"])
    trade_lot_size = int(config.get("trade_lot_size", 1))
    max_positions = int(config["max_positions"])
    top_signals_per_day = int(config.get("top_signals_per_day", max_positions))
    max_new_positions_per_day = int(config.get("max_new_positions_per_day", top_signals_per_day))
    capital_deployment_ratio = float(config.get("capital_deployment_ratio", 1.0))
    fee_rate = float(config.get("fee_bps", 0)) / 10000.0
    slippage_rate = float(config.get("slippage_bps", 0)) / 10000.0
    stop_loss_pct = config.get("stop_loss_pct")
    take_profit_pct = config.get("take_profit_pct")
    stop_loss_pct = None if stop_loss_pct in (None, "") else float(stop_loss_pct)
    take_profit_pct = None if take_profit_pct in (None, "") else float(take_profit_pct)

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
    bar_lookup = {
        (row.date, row.symbol): {
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
        }
        for row in market[["date", "symbol", "high", "low", "close"]].itertuples(index=False)
    }
    calendar = sorted(market["date"].drop_duplicates())
    trading_index_map = {
        pd.Timestamp(date).normalize(): idx for idx, date in enumerate(calendar)
    }

    cash = initial_capital
    open_positions: dict[str, dict] = {}
    last_close: dict[str, float] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []
    exit_reason_counts: dict[str, int] = defaultdict(int)

    for current_date in calendar:
        for symbol, position in list(open_positions.items()):
            if position["exit_date"] != current_date:
                continue

            open_positions.pop(symbol, None)
            exit_price = position["exit_price_raw"] * (1.0 - fee_rate - slippage_rate)
            proceeds = position["shares"] * exit_price
            cash += proceeds
            actual_calendar_days = int((current_date - position["entry_date"]).days)
            actual_trading_days = _compute_actual_holding_trading_days(
                position["entry_date"],
                current_date,
                trading_index_map,
            )
            trades.append(
                {
                    "entry_date": position["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": current_date.strftime("%Y-%m-%d"),
                    "code": symbol,
                    "side": "long",
                    "entry_price": round(position["entry_exec_price"], 6),
                    "exit_price": round(exit_price, 6),
                    "return": round((exit_price / position["entry_exec_price"]) - 1.0, 6),
                    "planned_holding_days": holding_days,
                    "actual_holding_calendar_days": actual_calendar_days,
                    "actual_holding_trading_days": actual_trading_days,
                    "shares": int(position["shares"]),
                }
            )
            exit_reason_counts["time_exit"] += 1

        todays_candidates = [
            candidate
            for candidate in pending_entries.get(current_date, [])
            if candidate["symbol"] not in open_positions
        ][:top_signals_per_day]
        available_slots = max_positions - len(open_positions)
        selected = todays_candidates[: min(available_slots, max_new_positions_per_day)]
        if selected:
            allocation = (cash * capital_deployment_ratio) / len(selected)
            for candidate in selected:
                entry_exec_price = candidate["entry_price_raw"] * (1.0 + fee_rate + slippage_rate)
                lot_cost = entry_exec_price * trade_lot_size
                lots = int(allocation // lot_cost)
                shares = lots * trade_lot_size
                if shares <= 0:
                    continue
                cost = shares * entry_exec_price
                if cost > cash:
                    continue
                cash -= cost
                open_positions[candidate["symbol"]] = {
                    **candidate,
                    "shares": shares,
                    "entry_exec_price": entry_exec_price,
                }

        for symbol, position in list(open_positions.items()):
            if position["exit_date"] <= current_date:
                continue
            bar = bar_lookup.get((current_date, symbol))
            if bar is None:
                continue

            exit_reason = None
            exit_price_raw = None

            if stop_loss_pct is not None:
                stop_price_raw = position["entry_price_raw"] * (1.0 - stop_loss_pct)
                if bar["low"] <= stop_price_raw:
                    exit_reason = "stop_loss"
                    exit_price_raw = stop_price_raw

            if take_profit_pct is not None and exit_reason is None:
                take_profit_price_raw = position["entry_price_raw"] * (1.0 + take_profit_pct)
                if bar["high"] >= take_profit_price_raw:
                    exit_reason = "take_profit"
                    exit_price_raw = take_profit_price_raw

            if exit_reason is None or exit_price_raw is None:
                continue

            open_positions.pop(symbol, None)
            exit_price = exit_price_raw * (1.0 - fee_rate - slippage_rate)
            proceeds = position["shares"] * exit_price
            cash += proceeds
            actual_calendar_days = int((current_date - position["entry_date"]).days)
            actual_trading_days = _compute_actual_holding_trading_days(
                position["entry_date"],
                current_date,
                trading_index_map,
            )
            trades.append(
                {
                    "entry_date": position["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": current_date.strftime("%Y-%m-%d"),
                    "code": symbol,
                    "side": "long",
                    "entry_price": round(position["entry_exec_price"], 6),
                    "exit_price": round(exit_price, 6),
                    "return": round((exit_price / position["entry_exec_price"]) - 1.0, 6),
                    "planned_holding_days": holding_days,
                    "actual_holding_calendar_days": actual_calendar_days,
                    "actual_holding_trading_days": actual_trading_days,
                    "shares": int(position["shares"]),
                }
            )
            exit_reason_counts[exit_reason] += 1

        portfolio_value = cash
        for symbol, position in open_positions.items():
            bar = bar_lookup.get((current_date, symbol))
            mark_price = (
                bar["close"]
                if bar is not None
                else last_close.get(symbol, position["entry_price_raw"])
            )
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
            "planned_holding_days",
            "actual_holding_calendar_days",
            "actual_holding_trading_days",
            "shares",
        ],
    )
    return equity_df, trades_df, {
        "holding_days": holding_days,
        "initial_capital": initial_capital,
        "trade_lot_size": trade_lot_size,
        "max_new_positions_per_day": max_new_positions_per_day,
        "capital_deployment_ratio": capital_deployment_ratio,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "exit_reason_counts": dict(exit_reason_counts),
    }
