from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_11"
STRATEGY_NAME = "worker_11"
STRATEGY_TYPE = "rule_based"
BACKTEST_OVERRIDES = {
    "max_positions": 8,
    "top_signals_per_day": 4,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.22,
}


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir=None) -> pd.DataFrame:
    signals = features[
        (features["ret_20"] > 0.07)
        & (features["ret_5"] > 0.01)
        & (features["ret_5"] < 0.08)
        & (features["ret_1"] > -0.01)
        & (features["breakout_strength"] > -0.02)
        & (features["breakout_strength"] < 0.035)
        & (features["drawdown_20"] > -0.05)
        & (features["rebound_strength"] > 0.18)
        & (features["volatility_20"] > 0.008)
        & (features["volatility_20"] < 0.028)
        & (features["volume_ratio_20"] > 0.75)
        & (features["volume_ratio_20"] < 1.35)
        & (features["gap_open"].abs() < 0.02)
        & (features["range_pct"] < 0.045)
        & (features["intraday_return"] > -0.012)
        & features["next_open"].notna()
        & features[f"exit_close_{holding_days}"].notna()
    ][
        [
            "date",
            "symbol",
            "ret_20",
            "ret_5",
            "ret_1",
            "breakout_strength",
            "drawdown_20",
            "rebound_strength",
            "volatility_20",
            "volume_ratio_20",
            "gap_open",
            "range_pct",
            "intraday_return",
        ]
    ].copy()

    signals["score"] = (
        signals["ret_20"] * 70.0
        + signals["ret_5"] * 36.0
        + signals["rebound_strength"] * 10.0
        + signals["breakout_strength"] * 28.0
        - signals["volatility_20"] * 85.0
        - signals["range_pct"] * 22.0
        - signals["gap_open"].abs() * 15.0
        - (signals["volume_ratio_20"] - 1.0).abs() * 3.0
        - signals["drawdown_20"].abs() * 6.0
        + signals["intraday_return"] * 18.0
        + signals["ret_1"] * 12.0
    )

    signals = (
        signals.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", group_keys=False)
        .head(4)
    )
    return signals[["date", "symbol", "score"]]
