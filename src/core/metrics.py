from __future__ import annotations

import math

import pandas as pd


def calculate_metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict:
    if equity.empty:
        return {"cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "win_rate": 0.0, "num_trades": 0}

    series = equity["equity"].astype(float)
    returns = series.pct_change().fillna(0.0)
    total_return = series.iloc[-1] / series.iloc[0]
    years = max(len(series) / 252.0, 1 / 252.0)
    cagr = total_return ** (1.0 / years) - 1.0
    volatility = returns.std()
    sharpe = 0.0 if volatility == 0 else (returns.mean() / volatility) * math.sqrt(252)
    drawdown = series / series.cummax() - 1.0
    max_drawdown = float(drawdown.min())

    if trades.empty:
        win_rate = 0.0
        num_trades = 0
    else:
        win_rate = float((trades["return"].astype(float) > 0).mean())
        num_trades = int(len(trades))

    return {
        "cagr": round(float(cagr), 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe": round(float(sharpe), 6),
        "win_rate": round(win_rate, 6),
        "num_trades": num_trades,
    }
