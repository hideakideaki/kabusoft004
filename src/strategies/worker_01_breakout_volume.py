from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_01"
STRATEGY_NAME = "worker_01"
STRATEGY_TYPE = "rule_based"


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int) -> pd.DataFrame:
    signals = features[
        (features["breakout_strength"] > 0.0)
        & (features["volume_ratio_20"] > 1.5)
        & (features["volatility_20"] > 0.01)
        & features["next_open"].notna()
        & features[f"exit_close_{holding_days}"].notna()
    ][["date", "symbol", "breakout_strength", "volume_ratio_20", "ret_20"]].copy()
    signals["score"] = (
        signals["breakout_strength"] * 100.0
        + signals["volume_ratio_20"]
        + signals["ret_20"].fillna(0.0) * 10.0
    )
    return signals[["date", "symbol", "score"]]
