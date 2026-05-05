from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_09"
STRATEGY_NAME = "worker_09"
STRATEGY_TYPE = "rule_based"


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir=None) -> pd.DataFrame:
    signals = features[
        (features["ret_20"] > 0.08)
        & (features["rebound_strength"] > 0.10)
        & (features["breakout_strength"] > -0.04)
        & (features["ret_5"] < -0.02)
        & (features["ret_5"] > -0.10)
        & (features["ret_1"] < 0.0)
        & (features["gap_open"] < 0.01)
        & (features["intraday_return"] > -0.015)
        & (features["volume_ratio_20"] > 0.8)
        & (features["volume_ratio_20"] < 2.5)
        & (features["volatility_20"] < 0.05)
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
            "rebound_strength",
            "intraday_return",
            "volume_ratio_20",
        ]
    ].copy()

    signals["score"] = (
        signals["ret_20"] * 80.0
        + signals["rebound_strength"] * 10.0
        + signals["breakout_strength"] * 12.0
        + signals["intraday_return"] * 45.0
        - signals["ret_5"].abs() * 18.0
        + signals["ret_1"].abs() * 10.0
        - (signals["volume_ratio_20"] - 1.0).abs() * 1.5
    )
    signals = (
        signals.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date", group_keys=False)
        .head(3)
    )
    return signals[["date", "symbol", "score"]]
