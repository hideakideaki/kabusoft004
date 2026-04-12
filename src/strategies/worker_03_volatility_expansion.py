from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_03"
STRATEGY_NAME = "worker_03"
STRATEGY_TYPE = "rule_based"


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir=None) -> pd.DataFrame:
    signals = features[
        (features["volatility_20"] < 0.03)
        & (features["range_pct"] > 0.035)
        & (features["volume_ratio_20"] > 1.2)
        & (features["ret_1"] > 0)
        & features["next_open"].notna()
        & features[f"exit_close_{holding_days}"].notna()
    ][["date", "symbol", "range_pct", "volume_ratio_20", "ret_1"]].copy()
    signals["score"] = (
        signals["range_pct"] * 100.0
        + signals["volume_ratio_20"]
        + signals["ret_1"] * 100.0
    )
    return signals[["date", "symbol", "score"]]
