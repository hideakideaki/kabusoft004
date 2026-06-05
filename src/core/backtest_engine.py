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


def _optional_float(value, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(value)


def _current_portfolio_value(
    cash: float,
    open_positions: dict[str, dict],
    last_close: dict[str, float],
) -> float:
    value = cash
    for symbol, position in open_positions.items():
        mark_price = last_close.get(symbol, position["entry_price_raw"])
        value += position["shares"] * mark_price
    return float(value)


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
    stop_loss_pct = _optional_float(stop_loss_pct)
    take_profit_pct = _optional_float(take_profit_pct)
    max_position_value_pct = _optional_float(config.get("max_position_value_pct"))
    min_signal_price = _optional_float(config.get("min_signal_price"))
    min_signal_traded_value = _optional_float(config.get("min_signal_traded_value"))

    enriched = signals.merge(
        prices[
            [
                "date",
                "symbol",
                "close",
                "volume",
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
            "close": "signal_close",
            "volume": "signal_volume",
            "entry_date": "entry_date",
            "next_open": "entry_price_raw",
            f"exit_date_{holding_days}": "exit_date",
            f"exit_close_{holding_days}": "exit_price_raw",
        }
    )
    pre_filter_count = int(len(enriched))
    exclusion_counts: dict[str, int] = {}
    if min_signal_price is not None and min_signal_price > 0:
        before = len(enriched)
        enriched = enriched[enriched["signal_close"].astype(float) >= min_signal_price].copy()
        exclusion_counts["below_min_signal_price"] = int(before - len(enriched))
    if min_signal_traded_value is not None and min_signal_traded_value > 0:
        before = len(enriched)
        signal_traded_value = (
            enriched["signal_close"].astype(float) * enriched["signal_volume"].astype(float)
        )
        enriched = enriched[signal_traded_value >= min_signal_traded_value].copy()
        exclusion_counts["below_min_signal_traded_value"] = int(before - len(enriched))

    enriched["entry_date"] = pd.to_datetime(enriched["entry_date"])
    if "custom_exit_date" in enriched.columns:
        custom_exit_mask = enriched["custom_exit_date"].notna()
        enriched.loc[custom_exit_mask, "exit_date"] = enriched.loc[
            custom_exit_mask, "custom_exit_date"
        ]
    if "custom_exit_price_raw" in enriched.columns:
        custom_exit_price_mask = enriched["custom_exit_price_raw"].notna()
        enriched.loc[custom_exit_price_mask, "exit_price_raw"] = enriched.loc[
            custom_exit_price_mask, "custom_exit_price_raw"
        ]
    enriched["exit_date"] = pd.to_datetime(enriched["exit_date"])
    if "custom_exit_reason" not in enriched.columns:
        enriched["custom_exit_reason"] = "time_exit"
    enriched["custom_exit_reason"] = enriched["custom_exit_reason"].fillna("time_exit")
    enriched = enriched.sort_values(["entry_date", "score"], ascending=[True, False])

    pending_entries: dict[pd.Timestamp, list[dict]] = defaultdict(list)
    for row in enriched.itertuples(index=False):
        pending_entries[row.entry_date].append(
            {
                "signal_date": row.signal_date,
                "symbol": row.symbol,
                "score": float(row.score),
                "signal_close": float(row.signal_close),
                "signal_volume": float(row.signal_volume),
                "signal_traded_value": float(row.signal_close) * float(row.signal_volume),
                "entry_date": row.entry_date,
                "entry_price_raw": float(row.entry_price_raw),
                "exit_date": row.exit_date,
                "exit_price_raw": float(row.exit_price_raw),
                "exit_reason": row.custom_exit_reason,
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
                    "entry_value": round(position["shares"] * position["entry_exec_price"], 6),
                    "exit_value": round(position["shares"] * exit_price, 6),
                    "pnl": round(position["shares"] * (exit_price - position["entry_exec_price"]), 6),
                    "exit_reason": position.get("exit_reason", "time_exit"),
                }
            )
            exit_reason_counts[position.get("exit_reason", "time_exit")] += 1

        todays_candidates = [
            candidate
            for candidate in pending_entries.get(current_date, [])
            if candidate["symbol"] not in open_positions
        ][:top_signals_per_day]
        available_slots = max_positions - len(open_positions)
        selected = todays_candidates[: min(available_slots, max_new_positions_per_day)]
        if selected:
            portfolio_value_before_entries = _current_portfolio_value(cash, open_positions, last_close)
            base_allocation = (cash * capital_deployment_ratio) / len(selected)
            if max_position_value_pct is not None and max_position_value_pct > 0:
                allocation = min(base_allocation, portfolio_value_before_entries * max_position_value_pct)
            else:
                allocation = base_allocation
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
            if position["exit_date"] > current_date:
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
                    "entry_value": round(position["shares"] * position["entry_exec_price"], 6),
                    "exit_value": round(position["shares"] * exit_price, 6),
                    "pnl": round(position["shares"] * (exit_price - position["entry_exec_price"]), 6),
                    "exit_reason": position.get("exit_reason", "time_exit"),
                }
            )
            exit_reason_counts[position.get("exit_reason", "time_exit")] += 1

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
                    "entry_value": round(position["shares"] * position["entry_exec_price"], 6),
                    "exit_value": round(position["shares"] * exit_price, 6),
                    "pnl": round(position["shares"] * (exit_price - position["entry_exec_price"]), 6),
                    "exit_reason": exit_reason,
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

    equity_df = pd.DataFrame(equity_rows, columns=["date", "equity"])
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
            "entry_value",
            "exit_value",
            "pnl",
            "exit_reason",
        ],
    )
    return equity_df, trades_df, {
        "holding_days": holding_days,
        "initial_capital": initial_capital,
        "trade_lot_size": trade_lot_size,
        "max_new_positions_per_day": max_new_positions_per_day,
        "capital_deployment_ratio": capital_deployment_ratio,
        "max_position_value_pct": max_position_value_pct,
        "min_signal_price": min_signal_price,
        "min_signal_traded_value": min_signal_traded_value,
        "pre_filter_candidate_count": pre_filter_count,
        "post_filter_candidate_count": int(len(enriched)),
        "candidate_exclusion_counts": exclusion_counts,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "exit_reason_counts": dict(exit_reason_counts),
    }
